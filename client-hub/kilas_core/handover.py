"""Deterministic closed-signal handover after the existing WEB event fence."""
import time
from . import attention, operation_access
from .operation_contracts import OperationError
from public_chat import store


def request_human(tx,bid,cid,signal):
    operation_access.require(tx,bid)
    if signal not in ('HUMAN','UNSUPPORTED'): raise OperationError('invalid_handover')
    conv=store._locked(tx,bid,cid)
    generation=conv['version'] if conv['mode']=='AI_ACTIVE' else conv['version']-1
    item=attention.ensure(tx,bid,f'human:{cid}:{generation}','HUMAN_REPLY_NEEDED',conversation_id=cid)
    # Same mode/version/event fence as manual Phase 2 takeover, within this transaction.
    store._set_mode(tx,bid,cid,'HUMAN_TAKEOVER',None,origin='WEB_AUTOMATION')
    if cid.startswith('wa_'):
        from .adapters.whatsapp import binding
        import wa_takeover_service
        link=binding(tx,bid,cid)
        if link:
            wa_takeover_service.set_state_in_transaction(tx,bid,link['customer_phone'],'HUMAN_TAKEOVER',None)
    return item


def resolve_human_attention(tx,bid,cid):
    rows=tx.execute("SELECT source_key FROM kw_core_attention WHERE business_id=? AND conversation_id=? AND reason='HUMAN_REPLY_NEEDED' AND status='OPEN'",(bid,cid))
    for row in rows: attention.resolve_source(tx,bid,row['source_key'],int(time.time()))


def observe_uncertainty(tx,row):
    key='uncertain:'+row['id']
    if row['fields'].get('uncertain_fields'):
        attention.ensure(tx,row['business_id'],key,'NEEDS_INFORMATION_STUCK',job_id=row['id'])
    else:
        attention.resolve_source(tx,row['business_id'],key,int(time.time()))
