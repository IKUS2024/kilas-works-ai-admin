"""Large-profile lifecycle; disabled until its own reviewed actual acceptance."""
import hashlib,json,os,time
from .workspace_execution import (checked,active,reserve,update,reconcile,bounded_read,validated_evidence,MAX_SECONDS,RESERVE_MICRO_USD,RUNNER_COMMAND)
from . import workspace_large_outputs as large, workspace_large_guest as guest
from . import workspace_execution as base

def execute(job,step,files,entrypoint='main.py',*,_proof=False,_document_proof=False):
    payload=checked(files,entrypoint)
    from . import workspace_document_runtime as document, workspace_document_bundle as bundle
    if _proof and _document_proof:raise ValueError('invalid_proof_profile')
    receipt=None
    if _document_proof:
        if not document.authorized_for(job,step,files,entrypoint):raise ValueError('document_proof_not_authorized')
    elif _proof:
        from . import workspace_large_proof as proof
        if not (proof.authorized() and job['user_id']==proof.OWNER_ID and files==proof.fixture() and entrypoint=='main.py' and step['idempotency_key']==proof.KEY):raise ValueError('large_proof_not_authorized')
    else:
        if not large.capability(job['user_id'])['available']:raise ValueError('large_output_acceptance_pending')
        receipt=document.receipt()
    if not base.capability(job['user_id'])['available']:raise ValueError('isolated_execution_not_configured')
    document_mode=bool(_document_proof or receipt)
    prepared=bundle.prepare() if document_mode else None  # Inert free downloads before VM dispatch.
    memory_before=large.memory_admission()
    proof_fingerprint=large.fingerprint() if _proof else None
    document_fingerprint=document.fingerprint() if document_mode else None
    internal_proof=_proof or _document_proof
    if not active(job):raise ValueError('execution_cancelled')
    from e2b import Sandbox
    from .work_runtime import progress
    key='execution:'+step['idempotency_key']
    run_id=reserve(job,key,customer=not internal_proof);sandbox=None;outcome={'execution':'unknown','run_id':run_id}
    seconds=MAX_SECONDS
    terminal='UNKNOWN';started=time.monotonic();deadline=started+45;boundary_verified=False;phase='storage_admission'
    try:
        large.reserve_storage(run_id)
        if _proof:update(run_id,outcome_json=json.dumps({'large_storage_reserved':large.STORAGE_RESERVATION,'large_proof_fingerprint':proof_fingerprint}))
        if document_mode:update(run_id,outcome_json=json.dumps({'large_storage_reserved':large.STORAGE_RESERVATION,'document_fingerprint':document_fingerprint}))
        phase='creating'
        progress(job,'STARTING_SANDBOX','Menyiapkan sandbox…')
        sandbox=Sandbox.create(template=receipt['template_id'] if receipt else 'base',api_key=os.environ['E2B_API_KEY'],timeout=seconds,
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
        runtime_spec=None
        if document_mode:
            import re
            template_id=getattr(info,'template_id',None)
            if not isinstance(template_id,str) or not re.fullmatch('[a-z0-9-]{3,64}',template_id) or template_id=='base' or (receipt and template_id!=receipt['template_id']):raise ValueError('document_template_unverified')
            phase='runtime_preflight'
            runtime_spec=document.probe(sandbox,receipt)
            phase='uploading_runtime'
            for wheel in prepared[runtime_spec['abi']]:
                remaining=deadline-time.monotonic()
                if remaining<=0 or not active(job):raise ValueError('execution_timeout')
                with wheel.open('rb') as source:
                    sandbox.files.write('/root/'+wheel.name,source,user='root',gzip=False,request_timeout=min(8,remaining))
        phase='uploading_input'
        sandbox.files.write('/root/kilas-input.json',json.dumps(payload),user='root',request_timeout=5)
        if document_mode:
            from .workspace_document_guest import runner_source
            harness=runner_source(runtime_spec,bundle.manifest_digest(),proof=_document_proof)
        else:harness=guest.proof_runner_source() if _proof else guest.runner_source()
        phase='uploading_runner'
        sandbox.files.write('/root/kilas-runner.py',harness,user='root',request_timeout=5)
        phase='launching'
        sandbox.commands.run(RUNNER_COMMAND,
                             user='root',background=True,timeout=35,request_timeout=5)
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
        expected={'exit_code','stdout','stderr','outputs','timed_out','evidence'}|({'collector_evidence'} if internal_proof and 'collector_evidence' in report else set())|({'runtime_evidence'} if document_mode and 'runtime_evidence' in report else set())
        if internal_proof and report.get('exit_code')==0 and 'collector_evidence' not in report:raise ValueError('invalid_execution_report')
        if set(report)!=expected or type(report['exit_code']) is not int or type(report['timed_out']) is not bool:raise ValueError('invalid_execution_report')
        evidence=validated_evidence(report['evidence'],report['exit_code']==0 and not report['timed_out'])
        if document_mode and report['exit_code']==0 and not document.valid_runtime(report.get('runtime_evidence')):raise ValueError('document_runtime_unverified')
        files=large.download(sandbox,report['outputs'],deadline,lambda:active(job)) if report['outputs'] else []
        if any(not isinstance(report[k],str) or len(report[k].encode())>65536 for k in ('stdout','stderr')):raise ValueError('execution_output_limit')
        terminal='SUCCEEDED' if report['exit_code']==0 and not report['timed_out'] else 'FAILED'
        outcome={'execution':'completed','provider':'e2b','run_id':run_id,'exit_code':report['exit_code'],
                 'timed_out':bool(report['timed_out']),'stdout':report['stdout'],'stderr':report['stderr'],
                 'outputs':{},'large_files':files,'entrypoint':entrypoint,'tests_asserted':False,'boundary_evidence':evidence}
        outcome['host_memory_before']=memory_before;outcome['host_memory_after']=large.host_memory()
        if internal_proof:outcome['collector_evidence']=report.get('collector_evidence',{})
        if document_mode:outcome.update(runtime_evidence=report.get('runtime_evidence',{}),template_id=template_id)
        from .workspace_guest import FAILURES
        guest_failures=FAILURES|{'guest_runner_error'}
        if report['stderr'].startswith('KILAS_GUEST_FAILURE:'):
            code=report['stderr'].removeprefix('KILAS_GUEST_FAILURE:')
            if code in guest_failures:outcome['guest_failure']=code
        if not active(job):raise ValueError('execution_cancelled')
        return outcome
    except Exception as exc:
        terminal='FAILED' if phase=='storage_admission' else 'CANCELLED' if str(exc)=='execution_cancelled' else 'UNKNOWN'
        outcome={'execution':'cancelled' if terminal=='CANCELLED' else 'unknown','run_id':run_id,'phase':phase,'reason':str(exc) if isinstance(exc,ValueError) else 'remote_execution_error'}
        raise ValueError(outcome['reason']) from None
    finally:
        cleaned=phase=='storage_admission' and sandbox is None  # Proven no dispatch.
        if sandbox:
            try:sandbox.kill(request_timeout=5);cleaned=True
            except Exception:pass
        outcome['cleanup_confirmed']=cleaned
        outcome['sandbox_created']=sandbox is not None
        outcome['customer_metered']=not internal_proof
        outcome['large_storage_reserved']=large.STORAGE_RESERVATION if 'large_files' in outcome else 0
        micro=0 if phase=='storage_admission' else RESERVE_MICRO_USD
        if cleaned and boundary_verified:
            import math
            # Include creation, transfers and kill acknowledgement plus one second.
            # The accepted <=2 vCPU / <=4 GiB profile costs <=46 micro-USD/s.
            micro=min(micro,46*min(seconds,max(1,math.ceil(time.monotonic()-started)+1)))
        outcome['compute_cost_upper_estimate_micro_usd']=micro
        outcome['elapsed_ms']=int((time.monotonic()-started)*1000)
        if _proof:outcome['large_proof_fingerprint']=proof_fingerprint
        if document_mode:outcome['document_fingerprint']=document_fingerprint
        reconcile(run_id,terminal,{k:v for k,v in outcome.items() if k!='large_files'},cleaned,micro)
