"""Opt-in remote microVM execution. Never execute source on the application host."""
import hashlib
import importlib.util
import json
import os
import time
from pathlib import Path
import db
from . import workspace_files, usage, autonomous_store as store

POLICY='e2b-hobby-60s-5usd-v1'
MAX_SECONDS=60
GLOBAL_BUDGET_MICRO_USD=5000000
BUDGET_WINDOW_DAYS=35  # Stricter than any monthly billing period; no guessed anchor.
RESERVE_MICRO_USD=8880  # Worst Hobby ceiling (8 vCPU/8 GiB), including failed boundary attestation.
MAX_REPORT=512*1024
RUNNER_COMMAND=("env -i PATH=/usr/bin:/bin KILAS_REMOTE_GUEST=e2b-ephemeral-v1 /usr/bin/python3 -I -B /root/kilas-runner.py; "
    "code=$?; if [ \"$code\" -ne 0 ] && [ ! -f /root/kilas-done.json ]; then "
    "printf '%s' '{\"exit_code\":1,\"stdout\":\"\",\"stderr\":\"KILAS_GUEST_FAILURE:guest_launch_error\",\"timed_out\":false,\"outputs\":{},\"evidence\":{}}' > /root/kilas-done.json; fi")


def validated_evidence(value,success):
    # Only fixed labels/scalars. Never persist raw mount tables, paths or options.
    if not isinstance(value,dict) or set(value)-{'root','scratch','child'}:raise ValueError('invalid_boundary_evidence')
    for label in ('root','scratch'):
        if label not in value:continue
        item=value[label]
        if not isinstance(item,dict) or set(item)!={'total_bytes','available_bytes','total_inodes','readonly','filesystem'}:raise ValueError('invalid_boundary_evidence')
        if any(type(item[k]) is not int or not 0<=item[k]<2**63 for k in ('total_bytes','available_bytes','total_inodes')) or type(item['readonly']) is not bool or item['filesystem'] not in ('ext4','xfs','overlay','tmpfs','other'):raise ValueError('invalid_boundary_evidence')
    child=value.get('child',{})
    if not isinstance(child,dict):raise ValueError('invalid_boundary_evidence')
    fields={'ready','root_readonly','scratch_writable','mount_namespace_private','ipc_namespace_private','capabilities_zero','seccomp','no_new_privs','scratch_bytes','scratch_inodes'}
    if child:
        if child.get('ready') is False:
            from .workspace_guest import FAILURES
            if set(child)!={'ready','error'} or child['error'] not in FAILURES:raise ValueError('invalid_boundary_evidence')
        elif set(child)!=fields or any(type(child[k]) is not bool for k in fields-{'seccomp','scratch_bytes','scratch_inodes'}) or any(type(child[k]) is not int for k in ('seccomp','scratch_bytes','scratch_inodes')):raise ValueError('invalid_boundary_evidence')
    if success:
        scratch=value.get('scratch',{})
        if not ('root' in value and set(child)==fields and all(child[k] is True for k in fields-{'seccomp','scratch_bytes','scratch_inodes'}) and child['seccomp']==2 and child['scratch_bytes']==67108864 and child['scratch_inodes']==4096 and scratch.get('filesystem')=='tmpfs' and scratch.get('readonly') is False and 0<scratch.get('total_bytes',0)<=67108864 and 0<scratch.get('total_inodes',0)<=4096):raise ValueError('execution_boundary_unverified')
    return value


def accepted():
    from .workspace_execution_proof import key,fingerprint
    row=db.query_one("SELECT e.outcome_json FROM kilas_workspace_executions e JOIN kilas_agent_jobs j ON j.id=e.job_id WHERE e.operation_key=? AND e.state='SUCCEEDED' AND e.cleanup_confirmed=1 AND j.status='COMPLETED'",('execution:'+key(),))
    outcome=json.loads(row['outcome_json']) if row else {}
    if outcome.get('proof_passed') is not True:return False
    if outcome.get('proof_fingerprint')==fingerprint():return True
    # One explicitly reviewed admission-only transition; original proof untouched.
    # Exact helper bytes are pinned by nonsecret deployment configuration.
    pinned=os.environ.get('KILAS_EXECUTION_COMPATIBILITY_SHA256','')
    verifier=Path(__file__).with_name('workspace_execution_rollout.py')
    if not pinned or hashlib.sha256(verifier.read_bytes()).hexdigest()!=pinned:return False
    from . import workspace_execution_rollout as rollout
    return rollout.accepts(outcome)


def capability(user_id=None):
    from . import workspace_execution_access as access
    if user_id is None:
        from flask import has_request_context,session
        if has_request_context():user_id=session.get('user_id')
    configured=(os.environ.get('KILAS_EXECUTION_APPROVAL')==POLICY and
                bool(os.environ.get('E2B_API_KEY')) and importlib.util.find_spec('e2b') is not None and access.allowed(user_id))
    ready=bool(configured and accepted())
    return {'available':ready,'reason':None if ready else 'isolated_execution_acceptance_pending' if configured else 'isolated_execution_not_configured',
            'provider':'e2b','languages':['python'] if ready else [],'network':False,
            'production_host_execution':False,'sandbox_seconds':MAX_SECONDS,'monthly_cap_usd':5,
            'budget_window_days':BUDGET_WINDOW_DAYS,'budget_scope':'all_tenants_and_processes',
            'daily_run_limit':10,'concurrency':1,'runtime_acceptance':'fixed synthetic proof passed' if ready else 'pending remote verification'}


def checked(files,entrypoint):
    workspace_files.package(files)
    if entrypoint!='unittest' and (entrypoint not in files or not entrypoint.endswith('.py')):
        raise ValueError('invalid_python_entrypoint')
    if entrypoint=='unittest' and not any(n.startswith('tests/') and n.endswith('.py') for n in files):
        raise ValueError('python_tests_missing')
    return {'files':files,'entrypoint':entrypoint}


def active(job):
    # Let the DB compare its native lease timestamp (Postgres returns datetime,
    # SQLite stores ISO text). Never compare a datetime to a Python string.
    return bool(db.query_one("SELECT id FROM kilas_agent_jobs WHERE id=? AND user_id=? AND status='RUNNING' AND revision=? AND lease_token=? AND lease_until>?",(job['id'],job['user_id'],job['revision'],job.get('lease_token'),store.stamp())))


def reserve(job,key,*,customer=False):
    from datetime import timedelta
    from . import workspace_execution_credits as credits
    with store.transaction() as conn:
        if db.BACKEND=='postgres':usage._query(conn,'SELECT pg_advisory_xact_lock(74110601)',())
        if not store.locked(conn,job['id'],job.get('lease_token'),job['revision']):raise ValueError('execution_cancelled')
        if usage._query(conn,'SELECT id FROM kilas_workspace_executions WHERE operation_key=?',(key,),one=True):raise ValueError('execution_already_dispatched')
        now=store.now();day=store.stamp(now)[:10]
        credits.expired(conn,now)
        spent=usage._query(conn,'SELECT COALESCE(SUM(reserved_micro_usd),0) FROM kilas_workspace_executions WHERE created_at>=?',(store.stamp(now-timedelta(days=BUDGET_WINDOW_DAYS)),),one=True)[0]
        count=usage._query(conn,'SELECT COUNT(*) FROM kilas_workspace_executions WHERE created_at LIKE ?',(day+'%',),one=True)[0]
        running=usage._query(conn,"SELECT COUNT(*) FROM kilas_workspace_executions WHERE state IN ('CREATING','RUNNING','UNKNOWN','CLEANUP_REQUIRED') AND expires_at>?",(store.stamp(),),one=True)[0]
        if spent+RESERVE_MICRO_USD>GLOBAL_BUDGET_MICRO_USD or count>=10 or running:raise ValueError('execution_capacity_limit')
        if customer:credits.reserve(conn,job['user_id'],key,RESERVE_MICRO_USD)
        return usage._query(conn,"INSERT INTO kilas_workspace_executions(user_id,job_id,operation_key,state,reserved_micro_usd,created_at,expires_at) VALUES (?,?,?,'CREATING',?,?,?) RETURNING id",(job['user_id'],job['id'],key,RESERVE_MICRO_USD,store.stamp(),store.stamp(store.now()+timedelta(seconds=90))),one=True)[0]


def update(run_id,**fields):
    if not fields or set(fields)-{'state','sandbox_id','outcome_json','cleanup_confirmed'}:raise ValueError('invalid_execution_update')
    db.execute('UPDATE kilas_workspace_executions SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),run_id))


def reconcile(run_id,state,outcome,cleaned,micro):
    from . import workspace_execution_credits as credits
    with store.transaction() as conn:
        row=usage._query(conn,'SELECT user_id,operation_key FROM kilas_workspace_executions WHERE id=?',(run_id,),one=True)
        credits.settle(conn,row[0],row[1],micro,state=='SUCCEEDED')
        public={k:v for k,v in outcome.items() if k not in ('stdout','stderr','outputs')}
        public.update(compute_cost_upper_estimate_micro_usd=micro,cost_basis='conservative_compute_upper_bound')
        usage._query(conn,'UPDATE kilas_workspace_executions SET state=?,cleanup_confirmed=?,outcome_json=? WHERE id=?',(state if cleaned or not outcome.get('sandbox_created') else 'CLEANUP_REQUIRED',int(cleaned),json.dumps(public),run_id))


def bounded_read(sandbox,path):
    data=bytearray()
    with sandbox.files.read(path,format='stream',user='root',request_timeout=5) as chunks:
        for chunk in chunks:
            if len(chunk)>MAX_REPORT-len(data):raise ValueError('execution_output_limit')
            data.extend(chunk)
    return bytes(data)


def execute(job,step,files,entrypoint='main.py',*,_proof=False):
    payload=checked(files,entrypoint)
    if _proof:
        from .workspace_execution_proof import authorized,FIXTURE,key,OWNER_ID
        if not (authorized() and job['user_id']==OWNER_ID and files==FIXTURE and entrypoint=='main.py' and step['idempotency_key']==key()):raise ValueError('execution_proof_not_authorized')
    elif not capability(job['user_id'])['available']:raise ValueError('isolated_execution_not_configured')
    if not active(job):raise ValueError('execution_cancelled')
    from e2b import Sandbox
    from .work_runtime import progress
    key='execution:'+step['idempotency_key']
    run_id=reserve(job,key,customer=not _proof);sandbox=None;outcome={'execution':'unknown','run_id':run_id}
    seconds=30 if _proof else MAX_SECONDS
    terminal='UNKNOWN';started=time.monotonic();deadline=started+(25 if _proof else 45);boundary_verified=False;phase='creating'
    try:
        progress(job,'STARTING_SANDBOX','Menyiapkan sandbox…')
        sandbox=Sandbox.create(template='base',api_key=os.environ['E2B_API_KEY'],timeout=seconds,
            envs={},metadata={'operation':hashlib.sha256(key.encode()).hexdigest()},
            allow_internet_access=False,network={'allow_public_traffic':False,'deny_out':['0.0.0.0/0']},
            lifecycle={'on_timeout':'kill','auto_resume':False},request_timeout=10,retries=0)
        update(run_id,sandbox_id=sandbox.sandbox_id,state='RUNNING')
        phase='attesting'
        info=sandbox.get_info(request_timeout=5)
        if not (0<info.cpu_count<=2 and 0<info.memory_mb<=4096 and
                info.network and not info.network.get('allow_out') and
                (info.allow_internet_access is False or '0.0.0.0/0' in info.network.get('deny_out',[])) and
                info.network.get('allow_public_traffic') is False and
                info.lifecycle and str(info.lifecycle.get('on_timeout')).split('.')[-1].lower()=='kill' and
                info.lifecycle.get('auto_resume') is False):raise ValueError('execution_boundary_unverified')
        boundary_verified=True
        if not active(job):raise ValueError('execution_cancelled')
        phase='uploading_input'
        sandbox.files.write('/root/kilas-input.json',json.dumps(payload),user='root',request_timeout=5)
        harness=Path(__file__).with_name('workspace_guest.py').read_text()
        phase='uploading_runner'
        sandbox.files.write('/root/kilas-runner.py',harness,user='root',request_timeout=5)
        phase='launching'
        sandbox.commands.run(RUNNER_COMMAND,
                             user='root',background=True,timeout=23 if _proof else 35,request_timeout=5)
        progress(job,'RUNNING_CODE','Menjalankan Python…')
        phase='waiting_report'
        while True:
            if not active(job):raise ValueError('execution_cancelled')
            if time.monotonic()>deadline:raise ValueError('execution_timeout')
            state=sandbox.commands.run('test -f /root/kilas-done.json && printf ready || true',user='root',timeout=2,request_timeout=3)
            if state.stdout=='ready':break
            time.sleep(.25)
        progress(job,'VERIFYING','Memeriksa hasil…')
        phase='reading_report'
        report=json.loads(bounded_read(sandbox,'/root/kilas-done.json'))
        phase='validating_report'
        if set(report)!={'exit_code','stdout','stderr','outputs','timed_out','evidence'} or type(report['exit_code']) is not int or type(report['timed_out']) is not bool:raise ValueError('invalid_execution_report')
        evidence=validated_evidence(report['evidence'],report['exit_code']==0 and not report['timed_out'])
        outputs={}
        import base64
        if not isinstance(report['outputs'],dict) or len(report['outputs'])>8:raise ValueError('execution_output_limit')
        for name,encoded in report['outputs'].items():
            workspace_files.safe_path(name)
            raw=base64.b64decode(encoded,validate=True)
            if len(raw)>65536:raise ValueError('execution_output_limit')
            outputs[name]=raw.decode('utf-8')
            if name.endswith('.csv'):
                import csv,io,re
                for row in csv.reader(io.StringIO(outputs[name])):
                    for cell in row:
                        value=cell.lstrip()
                        if value.startswith(('=','+','-','@')) and not re.fullmatch(r'[+-]?\d+(?:\.\d+)?',value):raise ValueError('unsafe_csv_output')
        if sum(len(x.encode()) for x in outputs.values())>262144:raise ValueError('execution_output_limit')
        if any(not isinstance(report[k],str) or len(report[k].encode())>65536 for k in ('stdout','stderr')):raise ValueError('execution_output_limit')
        terminal='SUCCEEDED' if report['exit_code']==0 and not report['timed_out'] else 'FAILED'
        outcome={'execution':'completed','provider':'e2b','run_id':run_id,'exit_code':report['exit_code'],
                 'timed_out':bool(report['timed_out']),'stdout':report['stdout'],'stderr':report['stderr'],
                 'outputs':outputs,'entrypoint':entrypoint,'tests_asserted':False,'boundary_evidence':evidence}
        from .workspace_guest import FAILURES
        guest_failures=FAILURES|{'guest_runner_error'}
        if report['stderr'].startswith('KILAS_GUEST_FAILURE:'):
            code=report['stderr'].removeprefix('KILAS_GUEST_FAILURE:')
            if code in guest_failures:outcome['guest_failure']=code
        if not active(job):raise ValueError('execution_cancelled')
        return outcome
    except Exception as exc:
        terminal='CANCELLED' if str(exc)=='execution_cancelled' else 'UNKNOWN'
        outcome={'execution':'cancelled' if terminal=='CANCELLED' else 'unknown','run_id':run_id,'phase':phase,'reason':str(exc) if isinstance(exc,ValueError) else 'remote_execution_error'}
        raise ValueError(outcome['reason']) from None
    finally:
        cleaned=False
        if sandbox:
            try:sandbox.kill(request_timeout=5);cleaned=True
            except Exception:pass
        outcome['cleanup_confirmed']=cleaned
        outcome['sandbox_created']=sandbox is not None
        outcome['customer_metered']=not _proof
        micro=RESERVE_MICRO_USD
        if cleaned and boundary_verified:
            import math
            # Include creation, transfers and kill acknowledgement plus one second.
            # The accepted <=2 vCPU / <=4 GiB profile costs <=46 micro-USD/s.
            micro=min(micro,46*min(seconds,max(1,math.ceil(time.monotonic()-started)+1)))
        outcome['compute_cost_upper_estimate_micro_usd']=micro
        reconcile(run_id,terminal,outcome,cleaned,micro)
