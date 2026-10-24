"""Translator leases with explicit trial or operator provenance; no Call exemptions."""
import hashlib
import os
import re
import secrets
from datetime import datetime, timezone, timedelta
from . import live_gemini_budget as native, audio_transcription_budget as ledger, usage
from .autonomous_store import transaction

MODEL = 'gemini-3.8-live'
LEASE_SECONDS = 90
RENEW_SECONDS = 80  # Settle before shared 120s stale-operation recovery.


def config(*, for_end=False):
    base = native.policy()
    if not base or base['mode'] != 'owner_lifetime' or base['reserve'] < 250000:
        return None
    funding=os.environ.get('KILAS_TRANSLATOR_FUNDING_MODE','trial')
    if funding not in ('trial','operator'):return None
    if funding=='operator':
        # Dedicated provenance; these are estimates, never trial deductions.
        return {**base,'base':base,'funding':'operator','audience':'authenticated',
                # Legacy schema requires positive amounts: pin envelope estimate, not a spending cap.
                'id':'operator-interpreter-v1','global_micro':base['reserve'],'account_micro':base['reserve'],
                'expires_at':'operator-metering-v1',
                'price_version':'gemini-3.8-interpreter-bounded90-v1:operator'}
    return {**base, 'funding':'trial', 'base':base, 'id':'gml-interpreter-'+hashlib.sha256(base['id'].encode()).hexdigest()[:24],
            'price_version':'gemini-3.8-interpreter-bounded90-v1:'+base['price_version']}


def key(ident):
    if not isinstance(ident,str) or not re.fullmatch(r'[a-f0-9]{32}',ident):
        raise ledger.BudgetError('invalid_operation',400)
    return 'live-'+ident+'-gi'


def source(conn, value):
    if value['funding']=='operator':return
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
                    and row[2]==hashlib.sha256(('interpreter:'+ident).encode()).hexdigest()
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
        remaining=None if value['funding']=='operator' else max(0,value['global_micro']-native._spend(conn,value))
        busy=preview_busy(conn,owner)
        funded=value['funding']=='operator'
    return {'available':not busy and (funded or remaining>=value['reserve']),
            'reason':'already_processing' if busy else 'budget_limit' if not funded and remaining<value['reserve'] else None,
            'funding':value['funding'],
            'remaining_micro_usd':remaining,'reserve_micro_usd':value['reserve'],'metering_seconds':LEASE_SECONDS}


def claim(owner,ident):
    operation=key(ident);value=config()
    if not value or not native.allowed(owner,value):raise ledger.BudgetError('call_unavailable',503)
    with transaction() as conn:
        ledger._global_lock(conn);source(conn,value);native._authorize(conn,owner,value)
        ledger._campaign(conn,value)
        now=datetime.now(timezone.utc);stamp=now.isoformat()
        # Proven expired Translator envelopes only, retaining every charge.
        for expired in expired_keys(conn,owner):
            usage._query(conn,"UPDATE kilas_vo_stt_operations SET status='UNKNOWN',finished_at=? WHERE user_id=? AND operation_key=? AND status IN ('RESERVED','DISPATCHED')",(stamp,owner,expired))
        if usage._query(conn,'SELECT 1 FROM kilas_vo_stt_operations WHERE operation_key=?',(operation,),one=True):
            raise ledger.BudgetError('duplicate_turn',409)
        if usage._query(conn,"SELECT 1 FROM kilas_vo_stt_operations WHERE user_id=? AND status IN ('RESERVED','DISPATCHED')",(owner,),one=True):raise ledger.BudgetError('already_processing',429)
        if usage._query(conn,"SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE status IN ('RESERVED','DISPATCHED')",one=True)[0]>=ledger.GLOBAL_CONCURRENCY:raise ledger.BudgetError('service_busy',429)
        for seconds,maximum in ((3600,ledger.OWNER_HOURLY_ATTEMPTS),(86400,ledger.OWNER_DAILY_ATTEMPTS)):
            count=usage._query(conn,"SELECT COUNT(DISTINCT CASE WHEN (campaign LIKE ? OR campaign LIKE ?) THEN fingerprint ELSE operation_key END) FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key LIKE ? AND created_at>=?",('gml-%','operator-interpreter-%',owner,'live-%',(now-timedelta(seconds=seconds)).isoformat()),one=True)[0]
            if count>=maximum:raise ledger.BudgetError('attempt_limit',429)
        funded=value['funding']=='operator'
        if not funded and native._spend(conn,value)+value['reserve']>value['global_micro']:raise ledger.BudgetError('budget_limit',429)
        lease=secrets.token_hex(32)
        usage._query(conn,"INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at) VALUES (?,?,?,?,'RESERVED',?,?,?,?)",(owner,operation,value['id'],hashlib.sha256(('interpreter:'+ident).encode()).hexdigest(),value['reserve'],90000,ledger._hash(lease),stamp))
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


def renew(capability):
    """Atomically retain prior spend and fund the next envelope, without IO/retry.

    Each envelope still bounds time, PCM and responses at the old approved
    reservation. It is accounting, not a user-visible Call/session deadline.
    Separate durable rows preserve stale recovery and logical-start rate limits.
    """
    if type(capability) is not ledger.Reservation or not re.fullmatch(r'live-[a-f0-9]{32}-gi',capability.key):
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
        funded=value['funding']=='operator'
        if not funded and native._spend(conn,value)+value['reserve']>value['global_micro']:raise ledger.BudgetError('budget_limit',429)
        usage._query(conn,"UPDATE kilas_vo_stt_operations SET status='UNKNOWN',finished_at=? WHERE id=?",(stamp,row[0]))
        usage._query(conn,"INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at,dispatched_at) VALUES (?,?,?,?,'DISPATCHED',?,?,?,?,?)",(capability.owner,operation,value['id'],row[2],value['reserve'],90000,ledger._hash(lease),stamp,stamp))
        return ledger.Reservation(capability.owner,operation,lease)


def finish(capability):
    # Delegate only this feature's settlement to End; dispatch estimates stay.
    if type(capability) is not ledger.Reservation or not re.fullmatch(r'live-[a-f0-9]{32}-gi',capability.key):raise ledger.BudgetError('invalid_reservation')
    with transaction() as conn:
        ledger._global_lock(conn)
        row=ledger._lock_existing_campaign(conn,capability.owner,capability.key)
        if not row or row[5]!=ledger._hash(capability.lease):raise ledger.BudgetError('invalid_reservation')
        if row[3] not in ('RESERVED','DISPATCHED'):return
        usage._query(conn,"UPDATE kilas_vo_stt_operations SET status=?,charge_micro=?,finished_at=? WHERE id=?",('UNKNOWN' if row[3]=='DISPATCHED' else 'CANCELLED',row[4] if row[3]=='DISPATCHED' else 0,datetime.now(timezone.utc).isoformat(),row[0]))


def end(owner,ident):
    operation=key(ident)
    with transaction() as conn:
        ledger._global_lock(conn)
        row=ledger._row(conn,owner,operation)
        if row:
            # Settle every renewed envelope for this owned logical Call. An End
            # racing renewal wins under the same lock; it cannot fund a successor.
            usage._query(conn,"UPDATE kilas_vo_stt_operations SET status=CASE WHEN status='RESERVED' THEN 'CANCELLED' ELSE 'UNKNOWN' END,charge_micro=CASE WHEN status='RESERVED' THEN 0 ELSE charge_micro END,finished_at=? WHERE user_id=? AND fingerprint=? AND (campaign LIKE ? OR campaign LIKE ?) AND status IN ('RESERVED','DISPATCHED')",(datetime.now(timezone.utc).isoformat(),owner,row[2],'gml-interpreter-%','operator-interpreter-%'))
            return
        if usage._query(conn,'SELECT 1 FROM kilas_vo_stt_operations WHERE operation_key=?',(operation,),one=True):raise ledger.BudgetError('not_owned',404)
        value=config(for_end=True)
        if not value or not native.allowed(owner,value,conn):return
        source(conn,value);ledger._campaign(conn,value)
        # End-before-admission tombstone: a late Start with this key cannot pay.
        recent=usage._query(conn,"SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE user_id=? AND (campaign LIKE ? OR campaign LIKE ?) AND created_at>=?",(owner,'gml-interpreter-%','operator-interpreter-%',(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()),one=True)[0]
        if recent>=ledger.OWNER_HOURLY_ATTEMPTS:return  # Admission is also fenced.
        stamp=datetime.now(timezone.utc).isoformat()
        usage._query(conn,"INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at,finished_at) VALUES (?,?,?,?,'CANCELLED',0,90000,?,?,?)",(owner,operation,value['id'],hashlib.sha256(('interpreter:'+ident).encode()).hexdigest(),ledger._hash(secrets.token_hex(32)),stamp,stamp))


def expired_keys(conn,owner):
    rows=usage._rows(conn,"SELECT o.operation_key,o.campaign,o.created_at,c.price_version FROM kilas_vo_stt_operations o LEFT JOIN kilas_vo_stt_campaigns c ON c.id=o.campaign WHERE o.user_id=? AND o.status IN ('RESERVED','DISPATCHED')",(owner,))
    cutoff=datetime.now(timezone.utc)-timedelta(seconds=120);expired=[]
    for operation,campaign,created,price in rows:
        try:
            stamp=datetime.fromisoformat(created)
            own=(re.fullmatch(r'live-[a-f0-9]{32}-gi',operation) and campaign.startswith(('gml-interpreter-','operator-interpreter-')) and price.startswith('gemini-3.8-interpreter-bounded90-v1:'))
            old=(re.fullmatch(r'live-[a-f0-9]{32}-gm(?:2:(?:parent|slot))?',operation) and campaign.startswith('gml-') and (price==native.PRICE_VERSION or price.startswith(native.PRICE_VERSION+'-')))
            if (own or old) and stamp.tzinfo and stamp<cutoff:expired.append(operation)
        except (ValueError,TypeError,AttributeError):pass
    return expired


def preview_busy(conn,owner):
    expired=set(expired_keys(conn,owner))
    return any(row[0] not in expired for row in usage._rows(conn,"SELECT operation_key FROM kilas_vo_stt_operations WHERE user_id=? AND status IN ('RESERVED','DISPATCHED')",(owner,)))
