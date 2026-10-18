"""Once-only fixed synthetic startup proof; OFF without specific owner approval."""
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import threading
from datetime import timedelta
import db
from . import workspace_execution as execution,autonomous_store as store,usage

from . import workspace_acceptance_fixture as acceptance

CHECKS=acceptance.CHECKS
OWNER_ID=9
PROOF_POLICY='e2b-boundary-acceptance-30s-5usd-v1'
FIXTURE={'main.py':Path(acceptance.__file__).read_text()}


def passed(outcome):
    """Require actual adversarial evidence and retrieval, not just VM creation."""
    try:
        if not (type(outcome['exit_code']) is int and outcome['exit_code']==0 and outcome['timed_out'] is False
                and outcome.get('customer_metered') is False and outcome.get('sandbox_created') is True
                and outcome.get('cleanup_confirmed') is True
                and outcome['stdout'].strip()=='KILAS_ACCEPTANCE_OK'
                and outcome['stderr']==''
                and set(outcome['outputs'])=={'answer.txt','proof.json'}
                and outcome['outputs']['answer.txt']=='42\n'):return False
        execution.validated_evidence(outcome['boundary_evidence'],True)
        scratch=outcome['boundary_evidence']['scratch']
        if scratch['total_bytes']!=acceptance.BYTES or scratch['total_inodes']!=acceptance.INODES:return False
        report=json.loads(outcome['outputs']['proof.json'])
        if set(report)!={'answer','checks','evidence'} or type(report['answer']) is not int or report['answer']!=42 or report['checks']!=CHECKS:return False
        evidence=report['evidence']
        if set(evidence)!={'data','inodes'}:return False
        data,inodes=evidence['data'],evidence['inodes']
        if set(data)!={'written_bytes','requested_bytes','available_before','errno'} or set(inodes)!={'created_files','available_before','errno'}:return False
        if any(type(value) is not int for section in (data,inodes) for value in section.values()):return False
        return (0<data['written_bytes']<=data['available_before']<=acceptance.BYTES
                and data['available_before']<data['requested_bytes']<=acceptance.BYTES+acceptance.CHUNK
                and data['errno']==acceptance.errno.ENOSPC
                and 0<inodes['created_files']==inodes['available_before']<=acceptance.INODES
                and inodes['errno']==acceptance.errno.ENOSPC)
    except (KeyError,ValueError,TypeError,AttributeError):return False


def fingerprint():
    root=Path(__file__).parent
    digest=hashlib.sha256(b''.join((root/name).read_bytes() for name in ('workspace_execution.py','workspace_guest.py','workspace_execution_proof.py','workspace_acceptance_fixture.py'))).hexdigest()
    return digest


def key():
    # Owner explicitly approved exactly one THIRD VM for the reviewed enforced
    # quota fixture. Both prior consumed keys/rows remain untouched. Stable
    # across restarts, deployments and fingerprint changes: never auto-retry.
    return 'boundary-acceptance-proof-v1'


def authorized():
    return os.environ.get('KILAS_EXECUTION_PROOF_APPROVAL')==PROOF_POLICY and bool(os.environ.get('E2B_API_KEY'))


def run(app):
    from . import autonomous_runner,workspace_execution_worker
    with app.app_context():
        operation='execution:'+key()
        if not authorized() or db.query_one('SELECT id FROM kilas_workspace_executions WHERE operation_key=?',(operation,)):return
        if not db.query_one('SELECT id FROM users WHERE id=?',(OWNER_ID,)):return
        # Not due to cron: only this trusted fixed-code path may claim the proof.
        ident=store.create(OWNER_ID,'Verify isolated Python sandbox',conversation_id=None,wake_at=store.now()+timedelta(days=3650))
        token=secrets.token_hex(24)
        db.execute("UPDATE kilas_agent_jobs SET status='RUNNING',lease_token=?,lease_until=?,next_wake_at=NULL WHERE id=?",(token,store.stamp(store.now()+timedelta(seconds=120)),ident))
        with store.transaction() as conn:
            step_id=usage._query(conn,"INSERT INTO kilas_agent_steps(job_id,sequence,worker,action,instruction,input_json,idempotency_key,status,attempts) VALUES (?,1,'EXECUTION','python','Fixed synthetic sandbox proof','{}',?,'RUNNING',1) RETURNING id",(ident,key()),one=True)[0]
        job=store.get(OWNER_ID,ident);step=dict(db.query_one('SELECT * FROM kilas_agent_steps WHERE id=?',(step_id,)))
        try:
            outcome=execution.execute(job,step,FIXTURE,_proof=True)
            verified=passed(outcome)
            public={k:v for k,v in outcome.items() if k not in ('stdout','stderr','outputs')}
            execution.update(outcome['run_id'],outcome_json=json.dumps({**public,'proof_passed':verified,'proof_fingerprint':fingerprint()}))
            result=workspace_execution_worker.result(outcome)
            if not verified:
                from .agent_workers import Result
                result=Result('FAILED','Hasil eksekusi belum terverifikasi.',
                              {**public,'reason':'execution_proof_failed'},result.artifacts,verified=False)
            autonomous_runner.finish(job,token,step,result)
            logging.getLogger(__name__).warning('KILAS_EXECUTION_PROOF state=%s','PASSED' if verified else 'FAILED')
        except Exception:
            from .agent_workers import Result
            autonomous_runner.finish(job,token,step,Result('FAILED','Hasil eksekusi belum terverifikasi.',{'reason':'execution_proof_failed'}))
            logging.getLogger(__name__).warning('KILAS_EXECUTION_PROOF state=FAILED')


def maybe_start(app):
    logging.getLogger(__name__).warning('KILAS_EXECUTION_GATE proof_requested=%s general_requested=%s proof_passed=%s host_execution=False e2b_key_present=%s global_budget_micro_usd=%s budget_window_days=%s',authorized(),os.environ.get('KILAS_EXECUTION_APPROVAL')==execution.POLICY,execution.accepted(),bool(os.environ.get('E2B_API_KEY')),execution.GLOBAL_BUDGET_MICRO_USD,execution.BUDGET_WINDOW_DAYS)
    if authorized():threading.Thread(target=run,args=(app,),name='fixed-isolation-proof',daemon=True).start()
