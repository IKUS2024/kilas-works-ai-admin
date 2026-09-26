"""Bounded official transport. Durable at-most-once attempt; ambiguous sends need owner review."""
import json
import os
import re
import time
import requests
import repo
import wa_inbox_shared
from public_chat import store
from . import jobs, whatsapp_access
from .adapters.whatsapp import binding, sync_human


def deliver(bid,cid,eid,*,role,template=False):
    with store.transaction() as tx:
        jobs._lock(tx,bid)
        conv=store._locked(tx,bid,cid); link=binding(tx,bid,cid)
        if not link: raise store.ChatError('not_found',404)
        message=tx.one('SELECT * FROM kw_web_messages WHERE business_id=? AND conversation_id=? AND event_id=? AND role=?',(bid,cid,eid,role))
        if not message: return None
        cfg=whatsapp_access.channel(bid,link['phone_number_id'])
        if not cfg: raise store.ChatError('channel_not_ready',409)
        payload={'messaging_product':'whatsapp','to':link['customer_phone'],'type':'text','text':{'body':message['content']}}
        if template:
            name,language=wa_inbox_shared.resolve_reengagement_template_config_for_tenant(repo.get_whatsapp_config(bid),os.environ.get)
            if not name: raise store.ChatError('reengagement_template_not_configured',409)
            payload=wa_inbox_shared.build_template_message_payload(link['customer_phone'],name,language)
        fingerprint=store.digest(json.dumps(payload,sort_keys=True))
        existing=tx.one('SELECT * FROM kw_core_wa_outbound WHERE business_id=? AND conversation_id=? AND event_id=?',(bid,cid,eid))
        if existing:
            if existing['payload_hash']!=fingerprint: raise store.ChatError('event_conflict',409)
            return existing
        active=sync_human(tx,bid,cid,link['customer_phone'])
        permitted=(active if role=='assistant' else not active)
        if not template and int(time.time())-link['last_inbound_at']>=23*3600: permitted=False
        status='attempting' if permitted else 'suppressed'
        tx.execute('INSERT INTO kw_core_wa_outbound(business_id,conversation_id,event_id,payload_hash,status,created_at) VALUES (?,?,?,?,?,?)',
                   (bid,cid,eid,fingerprint,status,int(time.time())))
    if not permitted: return {'status':'suppressed'}
    # Reserve durably, then serialize send against takeover on the same conversation.
    # A process crash leaves attempting terminal-for-retry, never a duplicate send.
    with store.transaction() as tx:
        jobs._lock(tx,bid)
        store._locked(tx,bid,cid)
        active=sync_human(tx,bid,cid,link['customer_phone'])
        if (role=='assistant' and not active) or (role=='human' and active):
            tx.execute("UPDATE kw_core_wa_outbound SET status='suppressed' WHERE business_id=? AND conversation_id=? AND event_id=?",(bid,cid,eid))
            return {'status':'suppressed'}
        cfg=whatsapp_access.channel(bid,link['phone_number_id'])
        version=os.environ.get('META_GRAPH_API_VERSION','v21.0')
        provider_id=None; error=None
        if not cfg or not re.fullmatch(r'v[0-9]+\.[0-9]+',version):
            status,error='suppressed','channel_not_ready'
        else:
            try:
                response=requests.post(f"https://graph.facebook.com/{version}/{cfg['phone_number_id']}/messages",
                    headers={'Authorization':'Bearer '+cfg['access_token'],'Content-Type':'application/json'},
                    json=payload,timeout=(3,20),allow_redirects=False)
                data=response.json()
                entries=data.get('messages') if isinstance(data,dict) else None
                if response.status_code==200 and isinstance(entries,list) and entries and isinstance(entries[0],dict) and isinstance(entries[0].get('id'),str) and entries[0]['id']:
                    status,provider_id='accepted',entries[0]['id']
                elif response.status_code>=500 or 200<=response.status_code<300:
                    status,error='unknown','provider_ambiguous'
                else: status,error='failed','provider_rejected'
            except Exception:
                status,error='unknown','provider_transport_uncertain'
        tx.execute('UPDATE kw_core_wa_outbound SET status=?,provider_id=?,error=? WHERE business_id=? AND conversation_id=? AND event_id=?',
                   (status,provider_id,error,bid,cid,eid))
    return {'status':status,'error':error}


def system_text(bid, cid, event_id, text, actor):
    """Owner-authorized transactional text that preserves the current AI/Human mode."""
    if not isinstance(event_id, str) or not 1 <= len(event_id) <= 256:
        raise store.ChatError('invalid_event')
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise store.ChatError('invalid_message')
    text = text.strip()
    with store.transaction() as tx:
        jobs._lock(tx, bid)
        store._locked(tx, bid, cid)
        link = binding(tx, bid, cid)
        if not link:
            raise store.ChatError('not_found', 404)
        active = sync_human(tx, bid, cid, link['customer_phone'])
        existing = tx.one(
            "SELECT role,content FROM kw_web_messages WHERE business_id=? AND conversation_id=? "
            "AND event_id=? AND role IN ('assistant','human') ORDER BY id DESC LIMIT 1",
            (bid, cid, event_id),
        )
        if existing:
            if existing['content'] != text:
                raise store.ChatError('event_conflict', 409)
            role = existing['role']
        else:
            role = 'assistant' if active else 'human'
            store._message(tx, bid, cid, event_id, role, text)
            tx.execute(
                'INSERT INTO audit_log(actor_user_id,business_id,action,detail) VALUES (?,?,?,?)',
                (actor, bid, 'SYSTEM_TRANSACTIONAL_MESSAGE', cid + ':' + event_id),
            )
    return deliver(bid, cid, event_id, role=role)


def statuses(bid,pid,events):
    ranking={'accepted':0,'sent':1,'delivered':2,'read':3}
    with store.transaction() as tx:
        jobs._lock(tx,bid)
        for event in events:
            if not isinstance(event,dict) or event.get('status') not in (*ranking,'failed'): continue
            rows=tx.execute('SELECT o.* FROM kw_core_wa_outbound o JOIN kw_core_wa_conversations c '
                'ON c.business_id=o.business_id AND c.conversation_id=o.conversation_id '
                'WHERE o.business_id=? AND c.phone_number_id=? AND o.provider_id=? AND c.customer_phone=?',
                (bid,pid,event.get('id'),event.get('recipient_id')))
            for row in rows:
                new=event['status']; old=row['status']
                if old=='read' or (new=='failed' and old in ('delivered','read')): continue
                if new in ranking and ranking.get(old,-1)>=ranking[new]: continue
                tx.execute('UPDATE kw_core_wa_outbound SET status=? WHERE business_id=? AND conversation_id=? AND event_id=?',(new,bid,row['conversation_id'],row['event_id']))


def manual(bid,cid,eid,text,actor,*,template=False):
    if template:
        name,_=wa_inbox_shared.resolve_reengagement_template_config_for_tenant(repo.get_whatsapp_config(bid),os.environ.get)
        if not name: raise store.ChatError('reengagement_template_not_configured',409)
        text='[Template: '+name+']'
    store.human_reply(bid,cid,eid,text,actor)
    result=deliver(bid,cid,eid,role='human',template=template)
    if result['status'] not in ('accepted','sent','delivered','read'):
        raise store.ChatError('whatsapp_'+result['status'],409)
    return result
