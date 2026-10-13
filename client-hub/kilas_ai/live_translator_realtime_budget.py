"""Typed realtime lease in existing bounded STT ledger; never customer credits.

Public USD/hour is only a conservative internal allowance estimate. Actual
account credit billing/rounding remains unverified, so activation stays OFF.
Full lease estimate survives every possible supplier dispatch outcome.
"""
import hashlib
import secrets
import re
from datetime import datetime,timezone
from . import audio_transcription_budget as batch,usage
from .autonomous_store import transaction

LEASE_MS=200000
PRICE_VERSION=batch.REALTIME_LEASE_PRICE_VERSION
RESERVE_MICRO=(LEASE_MS*390000+3599999)//3600000


def config():
    value=batch.policy()
    if not value or len(value['id'])>77:raise batch.BudgetError('budget_unavailable')
    return {**value,'base_id':value['id'],'id':value['id']+'-rt','price_version':PRICE_VERSION}


def ledger_key(key):
    if not isinstance(key,str) or not re.fullmatch(r'live-[a-f0-9]{32}',key):raise batch.BudgetError('invalid_operation',400)
    return key+'-rt'


def claim(owner,ident,key):
    policy=config();operation=ledger_key(key)
    if not batch.configured() or not batch.free_test.speech_audience(owner,policy,allow_unscoped=False):raise batch.BudgetError('budget_unavailable')
    fingerprint=hashlib.sha256((ident+':'+key).encode()).hexdigest()
    with transaction() as conn:
        batch._campaign(conn,policy);batch._owner(conn,owner)
        # At most200s transport + bounded shutdown; a dead worker stays counted
        # through240s. The stale ledger keeps its full unknown-cost estimate.
        batch._expire(conn,campaign=policy['base_id'])
        if batch._row(conn,owner,operation):raise batch.BudgetError('duplicate_turn',409)
        batch._admit(conn,owner,policy,RESERVE_MICRO,operation)
        lease=secrets.token_hex(32)
        usage._query(conn,"INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at) VALUES (?,?,?,?,'RESERVED',?,?,?,?)",(owner,operation,policy['id'],fingerprint,RESERVE_MICRO,LEASE_MS,batch._hash(lease),datetime.now(timezone.utc).isoformat()))
        return batch.Reservation(owner,operation,lease)


def dispatch(capability):
    if type(capability) is not batch.Reservation:raise batch.BudgetError('invalid_reservation')
    policy=config()
    if not batch.free_test.speech_audience(capability.owner,policy,allow_unscoped=False):raise batch.BudgetError('budget_unavailable')
    with transaction() as conn:
        row=batch._lock_existing_campaign(conn,capability.owner,capability.key);batch._owner(conn,capability.owner)
        if not row or row[1]!=policy['id'] or row[3]!='RESERVED' or row[5]!=batch._hash(capability.lease) or row[4]!=RESERVE_MICRO or row[6]!=LEASE_MS:raise batch.BudgetError('invalid_reservation')
        # Durably committed BEFORE a WebSocket handshake that might bill even
        # when the client sees no successful connection acknowledgement.
        usage._query(conn,"UPDATE kilas_vo_stt_operations SET status='DISPATCHED',dispatched_at=? WHERE id=?",(datetime.now(timezone.utc).isoformat(),row[0]))


def finish(capability,success):
    with transaction() as conn:
        row=batch._lock_existing_campaign(conn,capability.owner,capability.key);batch._owner(conn,capability.owner,settlement=True)
        if not row or row[5]!=batch._hash(capability.lease):raise batch.BudgetError('invalid_reservation')
        if row[3] not in ('RESERVED','DISPATCHED'):return False
        dispatched=row[3]=='DISPATCHED'
        usage._query(conn,"UPDATE kilas_vo_stt_operations SET status=?,charge_micro=?,finished_at=? WHERE id=?",('COMPLETED' if success and dispatched else 'UNKNOWN' if dispatched else 'CANCELLED',row[4] if dispatched else 0,datetime.now(timezone.utc).isoformat(),row[0]))
        return bool(success and dispatched)
