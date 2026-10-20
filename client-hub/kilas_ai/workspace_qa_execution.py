"""One approved server-funded QA run; same remote guest and isolation lifecycle."""
import hashlib
import json
import os
import time
from pathlib import Path
from . import autonomous_store as store, workspace_files
from .workspace_execution import (checked,capability,active,reserve,update,bounded_read,
    validated_evidence,reconcile,MAX_SECONDS,RESERVE_MICRO_USD,RUNNER_COMMAND)


def execute(job,step,files,entrypoint='main.py',*,_proof=False):
    payload=checked(files,entrypoint)
    from . import workspace_qa_once as qa
    scope=qa._active.get()
    qa._approval()
    if _proof or scope is None or scope['job']['id']!=job['id'] or scope['step']['id']!=step['id'] or step['idempotency_key']!=qa.KEY:raise ValueError('qa_scope_invalid')
    if not capability(job['user_id'])['available']:raise ValueError('isolated_execution_not_configured')
    with store.transaction() as conn:qa.resource_check(conn,job['user_id'])
    if not active(job):raise ValueError('execution_cancelled')
    from e2b import Sandbox
    from .work_runtime import progress
    key='execution:'+step['idempotency_key']
    run_id=reserve(job,key,customer=False);sandbox=None;outcome={'execution':'unknown','run_id':run_id}
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
        outcome['customer_metered']=False
        outcome['funding']='SERVER_QA'
        outcome['qa_rearm_of']=qa.PREVIOUS_JOB_ID
        micro=RESERVE_MICRO_USD
        if cleaned and boundary_verified:
            import math
            # Include creation, transfers and kill acknowledgement plus one second.
            # The accepted <=2 vCPU / <=4 GiB profile costs <=46 micro-USD/s.
            micro=min(micro,46*min(seconds,max(1,math.ceil(time.monotonic()-started)+1)))
        outcome['compute_cost_upper_estimate_micro_usd']=micro
        reconcile(run_id,terminal,outcome,cleaned,micro)
