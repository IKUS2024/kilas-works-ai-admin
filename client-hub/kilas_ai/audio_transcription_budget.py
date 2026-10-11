"""Independent VO preview allowance. Never debits Audio credits or commercial plans.

Default OFF; mandatory finite campaign/account caps and expiry. Conservative estimated
reservation is retained after every dispatch, including timeout/cancel/failure.
No audio, filenames, transcripts, prompts or API keys enter this ledger.
"""
import hashlib
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import db
from . import usage
from .autonomous_store import transaction

MODEL = 'gpt-4o-mini-transcribe'
PRICE_VERSION = 'openai-mini-transcribe-20261011-standard'
# Model-window estimate: 16k input @ $1.25/M + 2k output @ $5/M.
# This is not a documented per-file invoice cap; overruns halt admissions.
RESERVE_MICRO = 30000
DAILY_ATTEMPTS = 2
GLOBAL_CONCURRENCY = 3


class BudgetError(ValueError):
    def __init__(self, code, status=503):
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True)
class Reservation:
    owner: int
    key: str
    lease: str


def policy():
    try:
        if os.environ.get('KILAS_VOICE_VIDEO_SCRIPT_ENABLED','').lower() not in ('1','true','yes','on'):return None
        campaign=os.environ['KILAS_VO_STT_CAMPAIGN']
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',campaign):return None
        global_micro=int(os.environ['KILAS_VO_STT_GLOBAL_BUDGET_MICRO_USD'])
        account_micro=int(os.environ['KILAS_VO_STT_ACCOUNT_BUDGET_MICRO_USD'])
        expiry=datetime.fromisoformat(os.environ['KILAS_VO_STT_EXPIRES_AT'].replace('Z','+00:00'))
        if expiry.tzinfo is None or expiry<=datetime.now(timezone.utc):return None
        if not RESERVE_MICRO<=account_micro<=global_micro<=1000000000:return None
        if os.environ.get('KILAS_VO_STT_PRICE_VERSION')!=PRICE_VERSION:return None
        return {'id':campaign,'global_micro':global_micro,'account_micro':account_micro,'expires_at':expiry.astimezone(timezone.utc).isoformat(),'price_version':PRICE_VERSION}
    except (KeyError,ValueError,TypeError,OverflowError):return None


def configured():
    return bool(os.environ.get('OPENAI_API_KEY','').strip())


def ready():
    return bool(policy() and configured())


def key_valid(key):
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',key):raise BudgetError('invalid_operation',400)


def _hash(lease):return hashlib.sha256(lease.encode()).hexdigest()


def _global_lock(conn):
    # Serialize admission/settlement across campaign changes, not only one row.
    if db.BACKEND=='postgres':usage._query(conn,'SELECT pg_advisory_xact_lock(?)',(74109101,),one=True)


def _campaign(conn, config):
    _global_lock(conn)
    usage._query(conn,'INSERT INTO kilas_vo_stt_campaigns(id,global_micro,account_micro,expires_at,price_version) VALUES (?,?,?,?,?) ON CONFLICT(id) DO NOTHING',tuple(config[k] for k in ('id','global_micro','account_micro','expires_at','price_version')))
    lock=' FOR UPDATE' if db.BACKEND=='postgres' else ''
    row=usage._query(conn,'SELECT global_micro,account_micro,expires_at,price_version,blocked FROM kilas_vo_stt_campaigns WHERE id=?'+lock,(config['id'],),one=True)
    if row[4]:raise BudgetError('campaign_blocked')
    if tuple(row[:4])!=tuple(config[k] for k in ('global_micro','account_micro','expires_at','price_version')):raise BudgetError('campaign_policy_changed')


def _owner(conn,owner):
    lock=' FOR UPDATE' if db.BACKEND=='postgres' else ''
    row=usage._query(conn,'SELECT role FROM users WHERE id=?'+lock,(owner,),one=True)
    if not row or row[0]!='CLIENT_OWNER':raise BudgetError('not_owned',404)


def _expire(conn,owner=None,campaign=None):
    cutoff=(datetime.now(timezone.utc)-timedelta(seconds=120)).isoformat()
    # Unknown dispatch spend remains fully reserved; never auto-retry.
    suffix=' AND campaign=?' if campaign else ' AND user_id=?'
    usage._query(conn,"UPDATE kilas_vo_stt_operations SET status='UNKNOWN' WHERE status IN ('RESERVED','DISPATCHED') AND created_at<?"+suffix,(cutoff,campaign if campaign else owner))


def _row(conn,owner,key):
    return usage._query(conn,'SELECT id,campaign,fingerprint,status,charge_micro,lease_digest,duration_ms FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key=?',(owner,key),one=True)


def owned(owner,key):
    key_valid(key)
    with transaction() as conn:
        _global_lock(conn);_owner(conn,owner);_expire(conn,owner=owner)
        row=_row(conn,owner,key)
        return {'status':row[3],'operation_key':key} if row else None


def _admit(conn,owner,config):
    cutoff=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    if usage._query(conn,'SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE user_id=? AND created_at>=?',(owner,cutoff),one=True)[0]>=DAILY_ATTEMPTS:raise BudgetError('attempt_limit',429)
    if usage._query(conn,"SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE user_id=? AND status IN ('RESERVED','DISPATCHED')",(owner,),one=True)[0]:raise BudgetError('already_processing',429)
    if usage._query(conn,"SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE status IN ('RESERVED','DISPATCHED')",one=True)[0]>=GLOBAL_CONCURRENCY:raise BudgetError('service_busy',429)
    total=usage._query(conn,'SELECT COALESCE(SUM(charge_micro),0) FROM kilas_vo_stt_operations WHERE campaign=?',(config['id'],),one=True)[0]
    account=usage._query(conn,'SELECT COALESCE(SUM(charge_micro),0) FROM kilas_vo_stt_operations WHERE campaign=? AND user_id=?',(config['id'],owner),one=True)[0]
    if total+RESERVE_MICRO>config['global_micro'] or account+RESERVE_MICRO>config['account_micro']:raise BudgetError('budget_limit',429)


def claim(owner,key,fingerprint,ms):
    key_valid(key)
    config=policy()
    if not config or not configured():raise BudgetError('budget_unavailable')
    if not re.fullmatch(r'[a-f0-9]{64}',fingerprint) or type(ms) is not int or not 0<ms<=600000:raise BudgetError('invalid_audio',400)
    with transaction() as conn:
        _campaign(conn,config);_owner(conn,owner);_expire(conn,campaign=config['id'])
        old=_row(conn,owner,key)
        if old:
            if old[3]!='CANCELLED' and old[2]!=fingerprint:raise BudgetError('operation_conflict',409)
            return {'status':old[3],'operation_key':key},None
        _admit(conn,owner,config)
        lease=secrets.token_hex(32)
        usage._query(conn,"INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at) VALUES (?,?,?,?,'RESERVED',?,?,?,?)",(owner,key,config['id'],fingerprint,RESERVE_MICRO,ms,_hash(lease),datetime.now(timezone.utc).isoformat()))
        return {'status':'RESERVED','operation_key':key},Reservation(owner,key,lease)


def dispatch(capability,fingerprint,ms):
    # Only a persisted, unconsumed owner-bound nonce can admit paid IO.
    if type(capability) is not Reservation:raise BudgetError('invalid_reservation')
    config=policy()
    if not config or not configured():raise BudgetError('budget_unavailable')
    with transaction() as conn:
        _campaign(conn,config);_owner(conn,capability.owner);_expire(conn,campaign=config['id'])
        row=_row(conn,capability.owner,capability.key)
        if not row or row[1]!=config['id'] or row[2]!=fingerprint or row[3]!='RESERVED' or row[5]!=_hash(capability.lease) or row[6]!=ms:raise BudgetError('invalid_reservation')
        usage._query(conn,"UPDATE kilas_vo_stt_operations SET status='DISPATCHED',dispatched_at=? WHERE id=? AND status='RESERVED'",(datetime.now(timezone.utc).isoformat(),row[0]))


def _lock_existing_campaign(conn,owner,key):
    _global_lock(conn)
    row=_row(conn,owner,key)
    if row:
        lock=' FOR UPDATE' if db.BACKEND=='postgres' else ''
        usage._query(conn,'SELECT id FROM kilas_vo_stt_campaigns WHERE id=?'+lock,(row[1],),one=True)
    return row


def finish(capability,success,evidence=None):
    # Completion is allowed after flag OFF/expiry; it cannot admit new calls.
    evidence=evidence or {}
    incoming=evidence.get('input_tokens');outgoing=evidence.get('output_tokens')
    valid=evidence.get('type')=='tokens' and type(incoming) is int and type(outgoing) is int and 0<=incoming<=1000000000 and 0<=outgoing<=1000000000
    estimate=(incoming*125+outgoing*500+99)//100 if valid else None
    with transaction() as conn:
        _lock_existing_campaign(conn,capability.owner,capability.key);_owner(conn,capability.owner)
        row=_row(conn,capability.owner,capability.key)
        if not row or row[5]!=_hash(capability.lease):raise BudgetError('invalid_reservation')
        # Late cancellation still records real provider evidence; it cannot revive text/status.
        over=valid and (estimate>row[4] or incoming>16000 or outgoing>2000)
        if over:usage._query(conn,'UPDATE kilas_vo_stt_campaigns SET blocked=1 WHERE id=?',(row[1],))
        usage._query(conn,'UPDATE kilas_vo_stt_operations SET actual_estimate_micro=?,input_tokens=?,output_tokens=?,charge_micro=? WHERE id=?',(estimate,incoming if valid else None,outgoing if valid else None,max(row[4],estimate or 0),row[0]))
        if row[3]!='DISPATCHED':return False
        usage._query(conn,'UPDATE kilas_vo_stt_operations SET status=?,finished_at=? WHERE id=?',('UNKNOWN' if over else 'COMPLETED' if success else 'FAILED',datetime.now(timezone.utc).isoformat(),row[0]))
        return not over


def cancel(owner,key):
    key_valid(key)
    with transaction() as conn:
        row=_lock_existing_campaign(conn,owner,key)
        if not row:
            config=policy()
            if not config or not configured():raise BudgetError('budget_unavailable')
            _campaign(conn,config)
        _owner(conn,owner)
        row=_row(conn,owner,key)
        if not row:
            _expire(conn,campaign=config['id']);_admit(conn,owner,config)
            usage._query(conn,"INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at) VALUES (?,?,?,'cancelled-before-start','CANCELLED',0,0,'',?)",(owner,key,config['id'],datetime.now(timezone.utc).isoformat()))
        else:
            # RESERVED has not dispatched; all unknown/provider states retain allowance.
            usage._query(conn,"UPDATE kilas_vo_stt_operations SET charge_micro=CASE WHEN status='RESERVED' THEN 0 ELSE charge_micro END,status='CANCELLED',finished_at=? WHERE id=? AND status IN ('RESERVED','DISPATCHED','UNKNOWN')",(datetime.now(timezone.utc).isoformat(),row[0]))
        return {'status':_row(conn,owner,key)[3],'operation_key':key}
