"""Execution audience reuses existing packages/fixed-end sponsorship, not a grant."""
import os
from . import usage,free_test


def entitled(user_id,conn=None,now=None):
    if type(user_id) is not int or user_id<=0:return False
    now=now or usage._now()
    plan=usage._plan(conn,user_id,now)[0] if conn is not None else usage.effective_plan(user_id)['plan']
    if plan in usage.PLANS and plan!='FREE':return True
    return free_test.eligible(user_id,conn,now)


def allowed(user_id):
    if not entitled(user_id):return False
    audience=os.environ.get('KILAS_EXECUTION_AUDIENCE','')
    if audience=='entitled':return True
    if audience not in ('','allowlist'):return False
    return str(user_id) in {value.strip() for value in os.environ.get('KILAS_EXECUTION_ALLOWED_USERS','').split(',') if value.strip().isdecimal()}


def log_readiness():
    """Non-generating startup evidence; no identities, keys or customer content."""
    import logging,hashlib,sys
    from pathlib import Path
    import db
    from . import workspace_execution as execution,workspace_execution_proof as proof
    audience=os.environ.get('KILAS_EXECUTION_AUDIENCE','')
    audience=audience if audience in ('entitled','allowlist','') else 'invalid'
    candidate=next((row['id'] for row in db.query_all('SELECT id FROM users WHERE id<>? ORDER BY id',(proof.OWNER_ID,)) if entitled(row['id'])),None)
    ready=bool(candidate is not None and execution.capability(candidate)['available'])
    verifier=Path(__file__).with_name('workspace_execution_rollout.py')
    pinned=os.environ.get('KILAS_EXECUTION_COMPATIBILITY_SHA256','')
    pin_matches=bool(pinned and hashlib.sha256(verifier.read_bytes()).hexdigest()==pinned)
    reason='pin_mismatch'
    if pin_matches:
        from . import workspace_execution_rollout as rollout
        reason=rollout.diagnostic_reason({'proof_passed':True,'proof_fingerprint':rollout.ORIGINAL_PROOF_FINGERPRINT})
    logging.getLogger(__name__).warning('KILAS_EXECUTION_AUDIENCE audience=%s acceptance_verified=%s nonowner_entitled_available=%s customer_reservation_required=True global_budget_micro_usd=%s compatibility_pin_matches=%s source_compatibility_reason=%s python_minor=%s',audience,execution.accepted(),ready,execution.GLOBAL_BUDGET_MICRO_USD,pin_matches,reason,'.'.join(map(str,sys.version_info[:2])))
    return ready
