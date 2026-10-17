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

CHECKS=['uid','no_root','environment','root_path_denied','resources','network_denied','answer']
OWNER_ID=9
FIXTURE={'main.py':'''import json,os,resource,urllib.request
from pathlib import Path
assert os.getuid()==65534
try:
 os.setuid(0)
 raise AssertionError('root escalation')
except PermissionError: pass
for name in ('DATABASE_URL','OPENAI_API_KEY','GEMINI_API_KEY','ANTHROPIC_API_KEY','E2B_API_KEY','RENDER_API_KEY'):
 assert name not in os.environ
try:
 Path('/root/kilas-input.json').read_bytes()
 raise AssertionError('root path readable')
except PermissionError: pass
assert resource.getrlimit(resource.RLIMIT_AS)==(268435456,268435456)
assert resource.getrlimit(resource.RLIMIT_NPROC)==(16,16)
assert resource.getrlimit(resource.RLIMIT_FSIZE)==(65536,65536)
try:
 response=urllib.request.urlopen('https://example.com',timeout=3)
 response.read(1)
 raise AssertionError('unexpected outbound response')
except urllib.error.HTTPError: raise AssertionError('unexpected outbound HTTP response')
except (OSError,TimeoutError): pass
Path('output/proof.json').write_text(json.dumps({'answer':42,'checks':['uid','no_root','environment','root_path_denied','resources','network_denied','answer']}))
print('KILAS_PROOF_OK')
'''}


def fingerprint():
    root=Path(__file__).parent
    digest=hashlib.sha256(b''.join((root/name).read_bytes() for name in ('workspace_execution.py','workspace_guest.py','workspace_execution_proof.py'))).hexdigest()
    return digest


def key():
    # Fixed across restarts AND code changes: a future release cannot silently
    # spend another proof attempt while the old approval setting remains present.
    return 'initial-proof-v1'


def authorized():
    return os.environ.get('KILAS_EXECUTION_PROOF_APPROVAL')==execution.POLICY and bool(os.environ.get('E2B_API_KEY'))


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
            expected={'answer':42,'checks':CHECKS}
            passed=(outcome['exit_code']==0 and not outcome['timed_out'] and outcome.get('cleanup_confirmed') is True and
                    outcome['stdout'].strip()=='KILAS_PROOF_OK' and json.loads(outcome['outputs'].get('proof.json','null'))==expected)
            public={k:v for k,v in outcome.items() if k not in ('stdout','stderr','outputs')}
            execution.update(outcome['run_id'],outcome_json=json.dumps({**public,'proof_passed':passed,'proof_fingerprint':fingerprint()}))
            result=workspace_execution_worker.result(outcome)
            if not passed:
                from .agent_workers import Result
                result=Result('FAILED','Hasil eksekusi belum terverifikasi.',
                              {**public,'reason':'execution_proof_failed'},result.artifacts,verified=False)
            autonomous_runner.finish(job,token,step,result)
            logging.getLogger(__name__).warning('KILAS_EXECUTION_PROOF state=%s','PASSED' if passed else 'FAILED')
        except Exception:
            from .agent_workers import Result
            autonomous_runner.finish(job,token,step,Result('FAILED','Hasil eksekusi belum terverifikasi.',{'reason':'execution_proof_failed'}))
            logging.getLogger(__name__).warning('KILAS_EXECUTION_PROOF state=FAILED')


def maybe_start(app):
    logging.getLogger(__name__).warning('KILAS_EXECUTION_GATE proof_requested=%s general_requested=%s proof_passed=%s host_execution=False e2b_key_present=%s global_budget_micro_usd=%s budget_window_days=%s',authorized(),os.environ.get('KILAS_EXECUTION_APPROVAL')==execution.POLICY,execution.accepted(),bool(os.environ.get('E2B_API_KEY')),execution.GLOBAL_BUDGET_MICRO_USD,execution.BUDGET_WINDOW_DAYS)
    if authorized():threading.Thread(target=run,args=(app,),name='fixed-isolation-proof',daemon=True).start()
