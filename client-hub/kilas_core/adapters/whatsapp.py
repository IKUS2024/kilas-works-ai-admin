"""Official WhatsApp metadata adapter; all business reasoning lives in conversation.process.

The historically named kw_web_* tables are the shared conversation/event log. WA rows
have expires_at=0 and a typed real provider identity, never a visitor token or fake phone.
"""
from datetime import datetime, timezone
import re
import time
import uuid
import repo
from public_chat import store
from kilas_core import customers, jobs, conversation, whatsapp_access
from kilas_core.contracts import InboundMessage


def binding(tx,bid,cid):
    return tx.one('SELECT * FROM kw_core_wa_conversations WHERE business_id=? AND conversation_id=?',(bid,cid))


def mapped(bid,cid):
    # Prefix is assigned only here; old schemas need not have Phase 8 installed.
    if not isinstance(cid,str) or not cid.startswith('wa_'): return None
    with store.transaction() as tx: return binding(tx,bid,cid)


def _phone(value):
    if not isinstance(value,str) or not re.fullmatch(r'[1-9][0-9]{5,19}',value):
        raise store.ChatError('invalid_provider_identity')
    return value


def ensure(bid,pid,phone,*,event_id=None,payload_hash=None):
    phone = _phone(phone)
    now = int(time.time())
    with store.transaction() as tx:
        jobs._lock(tx,bid)
        if event_id:
            previous=tx.one('SELECT * FROM kw_core_wa_inbound WHERE business_id=? AND phone_number_id=? AND provider_id=?',(bid,pid,event_id))
            if previous and previous['payload_hash']!=payload_hash: raise store.ChatError('event_conflict',409)
        row = tx.one('SELECT * FROM kw_core_wa_conversations WHERE business_id=? AND phone_number_id=? AND customer_phone=?',(bid,pid,phone))
        if row:
            if event_id: _inbound(tx,bid,pid,event_id,row['conversation_id'],payload_hash)
            return row
        channel = tx.one('SELECT * FROM kw_web_channels WHERE business_id=?',(bid,))
        if not channel or not channel['enabled']: raise store.ChatError('core_not_ready',409)
        cid = 'wa_'+uuid.uuid4().hex
        # Domain-separated provider identity, NOT a WEB visitor hash/credential.
        identity = 'WHATSAPP:'+pid+':'+phone
        tx.execute('INSERT INTO kw_web_conversations(id,business_id,visitor_hash,expires_at,created_at,updated_at) VALUES (?,?,?,0,?,?)',
                   (cid,bid,identity,now,now))
        tx.execute('INSERT INTO kw_core_wa_conversations(business_id,conversation_id,phone_number_id,customer_phone) VALUES (?,?,?,?)', (bid,cid,pid,phone))
        customers.ensure_channel_customer(tx,bid,cid,'WHATSAPP_PHONE',store.digest(phone),'WHATSAPP',now=now)
        if event_id: _inbound(tx,bid,pid,event_id,cid,payload_hash)
        return binding(tx,bid,cid)


def _inbound(tx,bid,pid,eid,cid,fingerprint):
    tx.execute('INSERT INTO kw_core_wa_inbound(business_id,phone_number_id,provider_id,conversation_id,payload_hash) VALUES (?,?,?,?,?) ON CONFLICT(business_id,phone_number_id,provider_id) DO NOTHING',(bid,pid,eid,cid,fingerprint))


def sync_human(tx,bid,cid,phone):
    row = tx.one('SELECT mode FROM wa_conversation_state WHERE business_id=? AND customer_phone=?',(bid,phone))
    if row and row['mode']=='HUMAN_TAKEOVER':
        store._set_mode(tx,bid,cid,'HUMAN_TAKEOVER',None,origin='WHATSAPP')
    return store._locked(tx,bid,cid)['mode']=='AI_ACTIVE'


def mode(bid,cid,value,actor):
    import wa_takeover_service
    if value not in ('AI_ACTIVE','HUMAN_TAKEOVER'): raise store.ChatError('invalid_mode')
    with store.transaction() as tx:
        jobs._lock(tx,bid)
        link = binding(tx,bid,cid)
        if not link: raise store.ChatError('not_found',404)
        store._set_mode(tx,bid,cid,value,actor,origin='WHATSAPP')
        wa_takeover_service.set_state_in_transaction(tx,bid,link['customer_phone'],value,actor)
        if value=='AI_ACTIVE':
            from kilas_core.handover import resolve_human_attention
            resolve_human_attention(tx,bid,cid)
    return value


def handle(bid,pid,value,field):
    """Called only after root webhook HMAC and authoritative channel resolution."""
    from kilas_core import whatsapp_transport as outbound
    if not whatsapp_access.channel(bid,pid): return {'status':'channel_not_ready'}
    if value.get('statuses'): outbound.statuses(bid,pid,value['statuses'])
    if field=='smb_message_echoes':
        for echo in value.get('message_echoes') or []:
            if not isinstance(echo,dict) or not echo.get('id'): continue
            link=ensure(bid,pid,echo.get('to'))
            cid=link['conversation_id']; eid='echo:'+str(echo['id'])[:256]
            text=((echo.get('text') or {}).get('body') or '[Media dari WhatsApp Business]')[:4000]
            with store.transaction() as tx:
                jobs._lock(tx,bid)
                store._locked(tx,bid,cid)
                # An API send echo is not a new human reply.
                sent=tx.one('SELECT event_id FROM kw_core_wa_outbound WHERE business_id=? AND provider_id=?',(bid,echo['id']))
                # Core Inbox media sends store the provider wamid directly as the human message
                # event id so shared media metadata can attach without copying private URLs.
                old=tx.one(
                    "SELECT id FROM kw_web_messages WHERE business_id=? AND conversation_id=? "
                    "AND event_id IN (?,?) AND role='human'",
                    (bid,cid,eid,str(echo['id'])))
                if sent or old: continue
                import wa_takeover_service
                wa_takeover_service.set_state_in_transaction(tx,bid,link['customer_phone'],'HUMAN_TAKEOVER',None)
                store._set_mode(tx,bid,cid,'HUMAN_TAKEOVER',None,origin='WHATSAPP_ECHO')
                store._message(tx,bid,cid,eid,'human',text)
        return {'status':'ok'}
    for message in value.get('messages') or []:
        if not isinstance(message,dict): raise store.ChatError('invalid_provider_message')
        eid=message.get('id')
        if not isinstance(eid,str) or not 1<=len(eid)<=256: raise store.ChatError('invalid_provider_message')
        timestamp=message.get('timestamp')
        if not isinstance(timestamp,(str,int)) or not str(timestamp).isdigit(): raise store.ChatError('invalid_provider_timestamp')
        stamp=int(timestamp)
        if not 0<stamp<=int(time.time())+300: raise store.ChatError('invalid_provider_timestamp')
        import json
        fingerprint=store.digest(json.dumps(message,sort_keys=True,separators=(',',':')))
        link=ensure(bid,pid,message.get('from'),event_id=eid,payload_hash=fingerprint); cid=link['conversation_id']
        if message.get('type')!='text':
            # Root persists supported bounded media first. Owner handles it, no invented extraction.
            mode(bid,cid,'HUMAN_TAKEOVER',None)
            text='[Media customer: perlu ditinjau tim]'
        else:
            text=(message.get('text') or {}).get('body')
        if not isinstance(text,str) or not text.strip() or len(text)>4000: raise store.ChatError('invalid_message')
        with store.transaction() as tx:
            jobs._lock(tx,bid)
            sync_human(tx,bid,cid,link['customer_phone'])
            tx.execute('UPDATE kw_core_wa_conversations SET last_inbound_at=CASE WHEN last_inbound_at<? THEN ? ELSE last_inbound_at END WHERE business_id=? AND conversation_id=?',(stamp,stamp,bid,cid))
        inbound=InboundMessage(business_id=bid,channel='whatsapp',conversation_id=cid,actor_type='visitor',
                               text=text.strip(),timestamp=datetime.fromtimestamp(stamp,timezone.utc),external_message_id=eid)
        event,history=store.claim(bid,cid,eid,inbound.text,store.digest(pid+':'+link['customer_phone']))
        if history is not None:
            def fence(tx):
                return bool(whatsapp_access.channel(bid,pid)) and sync_human(tx,bid,cid,link['customer_phone'])
            event=conversation.process(repo.get_business(bid),inbound,event,history,
                eligibility=lambda _: bool(whatsapp_access.channel(bid,pid)),fence=fence)
        if event['status']=='processing': raise store.ChatError('processing',503)
        outbound.deliver(bid,cid,eid,role='assistant')
    return {'status':'ok'}
