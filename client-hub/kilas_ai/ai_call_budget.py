"""Call account metering, with the historical trial allowance kept separate."""
import hashlib
import re
import secrets
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from . import live_gemini_budget as native, audio_transcription_budget as ledger, usage
from .autonomous_store import transaction

MODEL = 'gemini-3.8-live'
LEASE_SECONDS = 90
RENEW_SECONDS = 80  # Settle before shared 120s stale-operation recovery.


def account_allowance(conn,owner,value,operation=None):
    """Use existing Premium capacity/topups and existing server-owned exemptions.

    A paid/exempt account is not funded by the old shared trial campaign. No
    invoice, plan, balance, exemption or historical trial spend is changed here.
    The existing conservative Call envelope is recorded as estimated usage.
    """
    from . import capacity, topups
    topups._lock_user(conn,owner)
    now=usage._now();plan,start,end=usage._plan(conn,owner,now)
    exempt=usage._qa_quota_exempt(conn,owner,now)
    if plan=='FREE' and not exempt:return None
    source='BASE';cost=Decimal(value['reserve'])/Decimal(1000000)
    if not exempt:
        cycle=usage._period(plan,start,end,'CHAT',now)[0]
        if capacity.spent(conn,owner,cycle,now)+cost>capacity.allowance():
            remaining=sum(max(0,int(total)-int(spent)) for _,total,spent in topups._lots(conn,owner,now))
            if remaining<value['reserve']:raise ledger.BudgetError('account_credit_limit',402)
            source='TOPUP'
    if operation:
        if source=='TOPUP':topups.reserve(conn,owner,operation,'AI_CALL','SMART',now,forecast_micro=value['reserve'])
        usage._query(conn,"INSERT INTO kilas_ai_usage(user_id,operation_key,operation_type,mode,status,quota_source,estimated_cost_usd,created_at) VALUES (?,?,'AI_CALL','SMART','PENDING',?,?,?)",(owner,operation,source,str(cost),now.isoformat()))
    return source


def settle_account(conn,owner,operation,dispatched):
    from . import topups
    topups._lock_user(conn,owner)
    row=usage._query(conn,"SELECT estimated_cost_usd FROM kilas_ai_usage WHERE user_id=? AND operation_key=? AND operation_type='AI_CALL' AND status='PENDING'",(owner,operation),one=True)
    if not row:return
    micro=int(Decimal(row[0])*Decimal(1000000)) if dispatched else 0
    usage._query(conn,"UPDATE kilas_ai_usage SET status=?,provider=?,model=?,estimated_cost_usd=? WHERE user_id=? AND operation_key=? AND operation_type='AI_CALL' AND status='PENDING'",('COMPLETE' if dispatched else 'FAILED','google' if dispatched else None,MODEL if dispatched else None,row[0] if dispatched else None,owner,operation))
    topups.settle(conn,owner,operation,dispatched,micro)


def config(*, for_end=False):
    base = native.policy(enabled_key='KILAS_AI_ENABLED' if for_end else 'KILAS_AI_CALL_ENABLED')
    if not base or base['mode'] != 'owner_lifetime' or base['reserve'] < 250000:
        return None
    return {**base, 'base':base, 'id':'gml-call-'+hashlib.sha256(base['id'].encode()).hexdigest()[:24],
            'price_version':'gemini-3.8-live-bounded90-v1:'+base['price_version']}


def key(ident):
    if not isinstance(ident,str) or not re.fullmatch(r'[a-f0-9]{32}',ident):
        raise ledger.BudgetError('invalid_operation',400)
    return 'live-'+ident+'-gc'


def source(conn, value):
    base=value['base']
    row=usage._query(conn,'SELECT global_micro,account_micro,expires_at,price_version,blocked FROM kilas_vo_stt_campaigns WHERE id=?',(base['id'],),one=True)
    if not row or row[4] or tuple(row[:4])!=tuple(base[k] for k in ('global_micro','account_micro','expires_at','price_version')):
        raise ledger.BudgetError('call_unavailable',503)


def owned(owner,ident):
    return ledger.db.query_one('SELECT status,charge_micro,campaign FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key=?',(owner,key(ident)))


def active(owner,ident,capability=None):
    value=config()
    if not value or not native.allowed(owner,value):return False
    with transaction() as conn:
        source(conn,value)
        row=ledger._row(conn,owner,capability.key if capability else key(ident))
        campaign=usage._query(conn,'SELECT global_micro,account_micro,expires_at,price_version,blocked FROM kilas_vo_stt_campaigns WHERE id=?',(value['id'],),one=True)
        return bool(row and row[1]==value['id'] and row[3] in ('RESERVED','DISPATCHED')
                    and row[2]==hashlib.sha256(('call:'+ident).encode()).hexdigest()
                    and campaign and not campaign[4]
                    and tuple(campaign[:4])==tuple(value[k] for k in ('global_micro','account_micro','expires_at','price_version')))


def status(owner):
    value=config()
    if not value or not native.allowed(owner,value):
        return {'available':False,'reason':'call_unavailable'}
    with transaction() as conn:
        ledger._global_lock(conn);source(conn,value)
        campaign=usage._query(conn,'SELECT global_micro,account_micro,expires_at,price_version,blocked FROM kilas_vo_stt_campaigns WHERE id=?',(value['id'],),one=True)
        if campaign and (campaign[4] or tuple(campaign[:4])!=tuple(value[k] for k in ('global_micro','account_micro','expires_at','price_version'))):
            return {'available':False,'reason':'call_unavailable'}
        remaining=max(0,value['global_micro']-native._spend(conn,value))
        busy=bool(usage._query(conn,"SELECT 1 FROM kilas_vo_stt_operations WHERE user_id=? AND status IN ('RESERVED','DISPATCHED')",(owner,),one=True))
        try:funded=bool(account_allowance(conn,owner,value))
        except ledger.BudgetError as error:return {'available':False,'reason':error.code}
    return {'available':not busy and (funded or remaining>=value['reserve']),
            'reason':'already_processing' if busy else 'budget_limit' if not funded and remaining<value['reserve'] else None,
            'funding':'account' if funded else 'trial',
            'remaining_micro_usd':remaining,'reserve_micro_usd':value['reserve'],'metering_seconds':LEASE_SECONDS}


def claim(owner,ident):
    operation=key(ident);value=config()
    if not value or not native.allowed(owner,value):raise ledger.BudgetError('call_unavailable',503)
    with transaction() as conn:
        ledger._global_lock(conn);source(conn,value);native._authorize(conn,owner,value)
        ledger._campaign(conn,value)
        now=datetime.now(timezone.utc);stamp=now.isoformat()
        # Only this feature's expired90s leases; retained dispatch cost never falls.
        usage._query(conn,"UPDATE kilas_vo_stt_operations SET status=CASE WHEN status='RESERVED' THEN 'CANCELLED' ELSE 'UNKNOWN' END,charge_micro=CASE WHEN status='RESERVED' THEN 0 ELSE charge_micro END,finished_at=? WHERE campaign LIKE ? AND status IN ('RESERVED','DISPATCHED') AND created_at<?",(stamp,'gml-call-%',(now-timedelta(seconds=120)).isoformat()))
        if usage._query(conn,'SELECT 1 FROM kilas_vo_stt_operations WHERE operation_key=?',(operation,),one=True):
            raise ledger.BudgetError('duplicate_turn',409)
        if usage._query(conn,"SELECT 1 FROM kilas_vo_stt_operations WHERE user_id=? AND status IN ('RESERVED','DISPATCHED')",(owner,),one=True):raise ledger.BudgetError('already_processing',429)
        if usage._query(conn,"SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE status IN ('RESERVED','DISPATCHED')",one=True)[0]>=ledger.GLOBAL_CONCURRENCY:raise ledger.BudgetError('service_busy',429)
        for seconds,maximum in ((3600,ledger.OWNER_HOURLY_ATTEMPTS),(86400,ledger.OWNER_DAILY_ATTEMPTS)):
            count=usage._query(conn,"SELECT COUNT(DISTINCT CASE WHEN campaign LIKE ? THEN fingerprint ELSE operation_key END) FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key LIKE ? AND created_at>=?",('gml-%',owner,'live-%',(now-timedelta(seconds=seconds)).isoformat()),one=True)[0]
            if count>=maximum:raise ledger.BudgetError('attempt_limit',429)
        funded=account_allowance(conn,owner,value,operation)
        if not funded and native._spend(conn,value)+value['reserve']>value['global_micro']:raise ledger.BudgetError('budget_limit',429)
        lease=secrets.token_hex(32)
        usage._query(conn,"INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at) VALUES (?,?,?,?,'RESERVED',?,?,?,?)",(owner,operation,value['id'],hashlib.sha256(('call:'+ident).encode()).hexdigest(),value['reserve'],90000,ledger._hash(lease),stamp))
        return ledger.Reservation(owner,operation,lease)


def dispatch(capability):
    value=config()
    if not value:raise ledger.BudgetError('call_unavailable',503)
    with transaction() as conn:
        ledger._global_lock(conn);source(conn,value);native._authorize(conn,capability.owner,value)
        ledger._campaign(conn,value)
        row=ledger._lock_existing_campaign(conn,capability.owner,capability.key)
        if not row or row[1]!=value['id'] or row[3]!='RESERVED' or row[5]!=ledger._hash(capability.lease):raise ledger.BudgetError('call_ended',409)
        created=usage._query(conn,'SELECT created_at FROM kilas_vo_stt_operations WHERE id=?',(row[0],),one=True)[0]
        if not 0<=(datetime.now(timezone.utc)-datetime.fromisoformat(created.replace('Z','+00:00'))).total_seconds()<=20:raise ledger.BudgetError('reservation_expired',409)
        usage._query(conn,"UPDATE kilas_vo_stt_operations SET status='DISPATCHED',dispatched_at=? WHERE id=?",(datetime.now(timezone.utc).isoformat(),row[0]))
        settle_account(conn,capability.owner,capability.key,True)


def renew(capability):
    """Atomically retain prior spend and fund the next envelope, without IO/retry.

    Each envelope still bounds time, PCM and responses at the old approved
    reservation. It is accounting, not a user-visible Call/session deadline.
    Separate durable rows preserve stale recovery and logical-start rate limits.
    """
    if type(capability) is not ledger.Reservation or not re.fullmatch(r'live-[a-f0-9]{32}-gc',capability.key):
        raise ledger.BudgetError('invalid_reservation')
    value=config()
    if not value:raise ledger.BudgetError('call_unavailable',503)
    with transaction() as conn:
        ledger._global_lock(conn);source(conn,value);native._authorize(conn,capability.owner,value)
        ledger._campaign(conn,value)
        row=ledger._lock_existing_campaign(conn,capability.owner,capability.key)
        if not row or row[1]!=value['id'] or row[3]!='DISPATCHED' or row[5]!=ledger._hash(capability.lease):
            raise ledger.BudgetError('call_ended',409)
        stamp=datetime.now(timezone.utc).isoformat();lease=secrets.token_hex(32);operation=key(secrets.token_hex(16))
        account=usage._query(conn,"SELECT 1 FROM kilas_ai_usage WHERE user_id=? AND operation_key=? AND operation_type='AI_CALL'",(capability.owner,capability.key),one=True)
        funded=account_allowance(conn,capability.owner,value,operation) if account else None
        if account and not funded:raise ledger.BudgetError('account_credit_limit',402)
        if not funded and native._spend(conn,value)+value['reserve']>value['global_micro']:raise ledger.BudgetError('budget_limit',429)
        usage._query(conn,"UPDATE kilas_vo_stt_operations SET status='UNKNOWN',finished_at=? WHERE id=?",(stamp,row[0]))
        usage._query(conn,"INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at,dispatched_at) VALUES (?,?,?,?,'DISPATCHED',?,?,?,?,?)",(capability.owner,operation,value['id'],row[2],value['reserve'],90000,ledger._hash(lease),stamp,stamp))
        settle_account(conn,capability.owner,operation,True)
        return ledger.Reservation(capability.owner,operation,lease)


def finish(capability):
    # Delegate only this feature's settlement to End; dispatch estimates stay.
    if type(capability) is not ledger.Reservation or not re.fullmatch(r'live-[a-f0-9]{32}-gc',capability.key):raise ledger.BudgetError('invalid_reservation')
    with transaction() as conn:
        ledger._global_lock(conn)
        row=ledger._lock_existing_campaign(conn,capability.owner,capability.key)
        if not row or row[5]!=ledger._hash(capability.lease):raise ledger.BudgetError('invalid_reservation')
        if row[3] not in ('RESERVED','DISPATCHED'):return
        settle_account(conn,capability.owner,capability.key,row[3]=='DISPATCHED')
        usage._query(conn,"UPDATE kilas_vo_stt_operations SET status=?,charge_micro=?,finished_at=? WHERE id=?",('UNKNOWN' if row[3]=='DISPATCHED' else 'CANCELLED',row[4] if row[3]=='DISPATCHED' else 0,datetime.now(timezone.utc).isoformat(),row[0]))


def end(owner,ident):
    operation=key(ident)
    with transaction() as conn:
        ledger._global_lock(conn)
        row=ledger._row(conn,owner,operation)
        if row:
            for operation,dispatched in usage._rows(conn,"SELECT operation_key,status='DISPATCHED' FROM kilas_vo_stt_operations WHERE user_id=? AND fingerprint=? AND campaign LIKE ? AND status IN ('RESERVED','DISPATCHED')",(owner,row[2],'gml-call-%')):
                settle_account(conn,owner,operation,dispatched)
            # Settle every renewed envelope for this owned logical Call. An End
            # racing renewal wins under the same lock; it cannot fund a successor.
            usage._query(conn,"UPDATE kilas_vo_stt_operations SET status=CASE WHEN status='RESERVED' THEN 'CANCELLED' ELSE 'UNKNOWN' END,charge_micro=CASE WHEN status='RESERVED' THEN 0 ELSE charge_micro END,finished_at=? WHERE user_id=? AND fingerprint=? AND campaign LIKE ? AND status IN ('RESERVED','DISPATCHED')",(datetime.now(timezone.utc).isoformat(),owner,row[2],'gml-call-%'))
            return
        if usage._query(conn,'SELECT 1 FROM kilas_vo_stt_operations WHERE operation_key=?',(operation,),one=True):raise ledger.BudgetError('not_owned',404)
        value=config(for_end=True)
        if not value or not native.allowed(owner,value,conn):return
        source(conn,value);ledger._campaign(conn,value)
        # End-before-admission tombstone: a late Start with this key cannot pay.
        recent=usage._query(conn,"SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE user_id=? AND campaign LIKE ? AND created_at>=?",(owner,'gml-call-%',(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()),one=True)[0]
        if recent>=ledger.OWNER_HOURLY_ATTEMPTS:return  # Admission is also fenced.
        stamp=datetime.now(timezone.utc).isoformat()
        usage._query(conn,"INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at,finished_at) VALUES (?,?,?,?,'CANCELLED',0,90000,?,?,?)",(owner,operation,value['id'],hashlib.sha256(('call:'+ident).encode()).hexdigest(),ledger._hash(secrets.token_hex(32)),stamp,stamp))
