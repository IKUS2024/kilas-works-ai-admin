"""Independent VO preview allowance. Never debits Audio credits or commercial plans.

Default OFF; finite campaign/account caps, with explicit owner-only monthly usage.
QA campaigns still require a fixed expiry. Conservative estimated
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

MODEL = 'scribe_v2'
PRICE_VERSION = 'elevenlabs-scribe-v2-20261011-base-022usd-hour'
REALTIME_LEASE_PRICE_VERSION = 'elevenlabs-realtime-public-039usd-hour-200s-lease-unverified-v1'
# Public base estimate $0.22/hour, rounded UP to integer microUSD.
# This is an internal allowance, not observed supplier billing or a credit guarantee.
RATE_MICRO_PER_HOUR = 220000


def reserve_micro(ms):
    if type(ms) is not int or not 0 < ms <= 600000:
        raise BudgetError('invalid_audio', 400)
    return (ms * RATE_MICRO_PER_HOUR + 3599999) // 3600000
DAILY_ATTEMPTS = 2
OWNER_DAILY_ATTEMPTS = 120
OWNER_HOURLY_ATTEMPTS = 20
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
        if not 1<=account_micro<=global_micro<=1000000000:return None
        if os.environ.get('KILAS_VO_STT_PRICE_VERSION')!=PRICE_VERSION:return None
        allowed_owner=None
        if 'KILAS_VO_STT_ALLOWED_OWNER_ID' in os.environ:
            allowed_owner=int(os.environ['KILAS_VO_STT_ALLOWED_OWNER_ID'])
            if not 1<=allowed_owner<=1000000000:return None
        mode=os.environ.get('KILAS_VO_STT_USAGE_MODE','qa')
        if mode=='owner':
            if allowed_owner is None:return None
            now=datetime.now(timezone.utc)
            campaign+='-'+now.strftime('%Y%m')
            if len(campaign)>80:return None
            expiry=datetime(now.year+(now.month==12),now.month%12+1,1,tzinfo=timezone.utc)
        elif mode=='qa':
            expiry=datetime.fromisoformat(os.environ['KILAS_VO_STT_EXPIRES_AT'].replace('Z','+00:00'))
            if expiry.tzinfo is None or expiry<=datetime.now(timezone.utc):return None
        else:return None
        return {'id':campaign,'global_micro':global_micro,'account_micro':account_micro,'expires_at':expiry.astimezone(timezone.utc).isoformat(),'price_version':PRICE_VERSION,'allowed_owner':allowed_owner,'mode':mode}
    except (KeyError,ValueError,TypeError,OverflowError):return None


def configured():
    return bool(os.environ.get('ELEVENLABS_API_KEY','').strip())


def ready(owner=None):
    config=policy()
    return bool(config and configured() and (config['allowed_owner'] is None or config['allowed_owner']==owner))


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
    # Realtime has a separately typed 200s transport lease/expiry. It remains in
    # the same admission ledger and cannot be expired by this batch 120s rule.
    usage._query(conn,"UPDATE kilas_vo_stt_operations SET status='UNKNOWN' WHERE status IN ('RESERVED','DISPATCHED') AND campaign NOT IN (SELECT id FROM kilas_vo_stt_campaigns WHERE price_version=?) AND created_at<?"+suffix,(REALTIME_LEASE_PRICE_VERSION,cutoff,campaign if campaign else owner))
    rt_cutoff=(datetime.now(timezone.utc)-timedelta(seconds=240)).isoformat()
    usage._query(conn,"UPDATE kilas_vo_stt_operations SET status='UNKNOWN' WHERE status IN ('RESERVED','DISPATCHED') AND campaign IN (SELECT id FROM kilas_vo_stt_campaigns WHERE price_version=?) AND created_at<?"+suffix,(REALTIME_LEASE_PRICE_VERSION,rt_cutoff,campaign+'-rt' if campaign else owner))


def _row(conn,owner,key):
    return usage._query(conn,'SELECT id,campaign,fingerprint,status,charge_micro,lease_digest,duration_ms FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key=?',(owner,key),one=True)


def owned(owner,key):
    key_valid(key)
    with transaction() as conn:
        _global_lock(conn);_owner(conn,owner);_expire(conn,owner=owner)
        row=_row(conn,owner,key)
        return {'status':row[3],'operation_key':key} if row else None


def _admit(conn,owner,config,reserve=0,key=''):
    cutoff=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    # Live QA has its own finite allowance; a successful dictation must not
    # consume the two turns needed to test translation in both directions.
    if key.startswith('live-') and config['mode']=='owner':
        mode=os.environ.get('KILAS_LIVE_TRANSLATOR_USAGE_MODE','qa')
        if config['allowed_owner']!=owner or mode not in ('qa','owner'):
            raise BudgetError('budget_unavailable')
        daily=4 if mode=='qa' else OWNER_DAILY_ATTEMPTS
        used=usage._query(conn,"SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key LIKE ? AND created_at>=?",(owner,'live-%',cutoff),one=True)[0]
        if used>=daily:raise BudgetError('attempt_limit',429)
        hour=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        if usage._query(conn,"SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key LIKE ? AND created_at>=?",(owner,'live-%',hour),one=True)[0]>=OWNER_HOURLY_ATTEMPTS:
            raise BudgetError('rate_limit',429)
    else:
        _attempts(conn,owner,config,key,cutoff)
    if usage._query(conn,"SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE user_id=? AND status IN ('RESERVED','DISPATCHED')",(owner,),one=True)[0]:raise BudgetError('already_processing',429)
    if usage._query(conn,"SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE status IN ('RESERVED','DISPATCHED')",one=True)[0]>=GLOBAL_CONCURRENCY:raise BudgetError('service_busy',429)
    base=config.get('base_id',config['id'])
    total=usage._query(conn,'SELECT COALESCE(SUM(charge_micro),0) FROM kilas_vo_stt_operations WHERE campaign IN (?,?,?)',(base,base+'-rt',base+'-rt-check'),one=True)[0]
    account=usage._query(conn,'SELECT COALESCE(SUM(charge_micro),0) FROM kilas_vo_stt_operations WHERE campaign IN (?,?,?) AND user_id=?',(base,base+'-rt',base+'-rt-check',owner),one=True)[0]
    if total+reserve>config['global_micro'] or account+reserve>config['account_micro']:raise BudgetError('budget_limit',429)


def _attempts(conn,owner,config,key,cutoff):
    normal_dictation=config['mode']=='owner' and key.startswith('dictate-')
    daily_limit=OWNER_DAILY_ATTEMPTS if normal_dictation else DAILY_ATTEMPTS
    if usage._query(conn,'SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE user_id=? AND created_at>=?',(owner,cutoff),one=True)[0]>=daily_limit:raise BudgetError('attempt_limit',429)
    if normal_dictation:
        hour=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        if usage._query(conn,'SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE user_id=? AND created_at>=?',(owner,hour),one=True)[0]>=OWNER_HOURLY_ATTEMPTS:raise BudgetError('rate_limit',429)


def claim(owner,key,fingerprint,ms):
    key_valid(key)
    config=policy()
    if not config or not configured():raise BudgetError('budget_unavailable')
    if config['allowed_owner'] is not None and config['allowed_owner']!=owner:raise BudgetError('not_owned',404)
    if not re.fullmatch(r'[a-f0-9]{64}',fingerprint) or type(ms) is not int or not 0<ms<=600000:raise BudgetError('invalid_audio',400)
    with transaction() as conn:
        _campaign(conn,config);_owner(conn,owner);_expire(conn,campaign=config['id'])
        old=_row(conn,owner,key)
        if old:
            if old[3]!='CANCELLED' and old[2]!=fingerprint:raise BudgetError('operation_conflict',409)
            return {'status':old[3],'operation_key':key},None
        reserve=reserve_micro(ms)
        _admit(conn,owner,config,reserve,key)
        lease=secrets.token_hex(32)
        usage._query(conn,"INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at) VALUES (?,?,?,?,'RESERVED',?,?,?,?)",(owner,key,config['id'],fingerprint,reserve,ms,_hash(lease),datetime.now(timezone.utc).isoformat()))
        return {'status':'RESERVED','operation_key':key},Reservation(owner,key,lease)


def dispatch(capability,fingerprint,ms):
    # Only a persisted, unconsumed owner-bound nonce can admit paid IO.
    if type(capability) is not Reservation:raise BudgetError('invalid_reservation')
    config=policy()
    if not config or not configured():raise BudgetError('budget_unavailable')
    if config['allowed_owner'] is not None and config['allowed_owner']!=capability.owner:raise BudgetError('not_owned',404)
    with transaction() as conn:
        _campaign(conn,config);_owner(conn,capability.owner);_expire(conn,campaign=config['id'])
        row=_row(conn,capability.owner,capability.key)
        if not row or row[1]!=config['id'] or row[2]!=fingerprint or row[3]!='RESERVED' or row[5]!=_hash(capability.lease) or row[6]!=ms or row[4]<reserve_micro(ms):raise BudgetError('invalid_reservation')
        usage._query(conn,"UPDATE kilas_vo_stt_operations SET status='DISPATCHED',dispatched_at=? WHERE id=? AND status='RESERVED'",(datetime.now(timezone.utc).isoformat(),row[0]))


def _lock_existing_campaign(conn,owner,key):
    _global_lock(conn)
    row=_row(conn,owner,key)
    if row:
        lock=' FOR UPDATE' if db.BACKEND=='postgres' else ''
        usage._query(conn,'SELECT id FROM kilas_vo_stt_campaigns WHERE id=?'+lock,(row[1],),one=True)
    return row


def finish(capability,success):
    # Completion is allowed after flag OFF/expiry; it cannot admit new calls.
    # Scribe's response is NOT an invoice. Keep the duration allowance on every
    # dispatch outcome, with no token conversion, credit deduction or refund.
    with transaction() as conn:
        _lock_existing_campaign(conn,capability.owner,capability.key);_owner(conn,capability.owner)
        row=_row(conn,capability.owner,capability.key)
        if not row or row[5]!=_hash(capability.lease):raise BudgetError('invalid_reservation')
        version=usage._query(conn,'SELECT price_version FROM kilas_vo_stt_campaigns WHERE id=?',(row[1],),one=True)[0]
        compatible=version==PRICE_VERSION and row[4]>=reserve_micro(row[6])
        if not compatible:
            usage._query(conn,'UPDATE kilas_vo_stt_campaigns SET blocked=1 WHERE id=?',(row[1],))
        if row[3]!='DISPATCHED':return False
        usage._query(conn,'UPDATE kilas_vo_stt_operations SET status=?,finished_at=? WHERE id=?',('UNKNOWN' if not compatible else 'COMPLETED' if success else 'FAILED',datetime.now(timezone.utc).isoformat(),row[0]))
        # Historical token/actual_estimate columns remain untouched and nullable.
        return compatible


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
            _expire(conn,campaign=config['id']);_admit(conn,owner,config,key=key)
            usage._query(conn,"INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at) VALUES (?,?,?,'cancelled-before-start','CANCELLED',0,0,'',?)",(owner,key,config['id'],datetime.now(timezone.utc).isoformat()))
        else:
            # RESERVED has not dispatched; all unknown/provider states retain allowance.
            usage._query(conn,"UPDATE kilas_vo_stt_operations SET charge_micro=CASE WHEN status='RESERVED' THEN 0 ELSE charge_micro END,status='CANCELLED',finished_at=? WHERE id=? AND status IN ('RESERVED','DISPATCHED','UNKNOWN')",(datetime.now(timezone.utc).isoformat(),row[0]))
        return {'status':_row(conn,owner,key)[3],'operation_key':key}
