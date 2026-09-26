"""Media parity for the official Core WhatsApp Inbox.

Metadata is tenant/conversation scoped in Core. Binary bytes are never persisted: inbound and
outbound media are fetched from Meta on demand. Human outbound is limited to JPG/PNG/PDF and
uses the same official tenant channel, Human Takeover gate, 23-hour safety window, delivery
state table and at-most-once event semantics as text sends.
"""
import hashlib
import json
import re
import time
import uuid

import requests
from werkzeug.utils import secure_filename

import inbox_media_service
from public_chat import store
from . import jobs, whatsapp_access
from .adapters.whatsapp import binding, sync_human

TYPES = frozenset(inbox_media_service.TYPES)


def _filename(kind, mime, meta):
    raw = secure_filename(str(meta.get('filename') or ''))[:150]
    if raw:
        return raw
    ext = {
        'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp',
        'video/mp4': '.mp4', 'video/3gpp': '.3gp',
        'audio/aac': '.aac', 'audio/mp4': '.m4a', 'audio/mpeg': '.mp3',
        'audio/amr': '.amr', 'audio/ogg': '.ogg', 'application/pdf': '.pdf',
    }.get(mime, '')
    return kind + ext


def record(tx, bid, cid, event, role='user'):
    kind = event.get('type') if isinstance(event,dict) else None
    if kind not in TYPES or role not in ('user','assistant','human'):
        return None
    meta = event.get(kind) or {}
    eid = str(event.get('id') or '')
    if not eid or len(eid) > 256:
        raise store.ChatError('invalid_provider_message')
    media_id = str(meta.get('id') or '')
    if media_id and not re.fullmatch(r'[0-9]{1,128}', media_id):
        media_id = ''
    mime = str(meta.get('mime_type') or '').split(';')[0].strip().lower()[:128]
    caption = str(meta.get('caption') or '')[:1024]
    try:
        created = int(event.get('timestamp'))
    except (TypeError,ValueError,OverflowError):
        created = int(time.time())
    key = uuid.uuid4().hex
    tx.execute(
        'INSERT INTO kw_core_wa_media'
        '(id,business_id,conversation_id,event_id,role,media_id,message_type,mime_type,filename,caption,created_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(business_id,conversation_id,event_id,role) DO NOTHING',
        (key,bid,cid,eid,role,media_id,kind,mime,_filename(kind,mime,meta),caption,created))
    return tx.one(
        'SELECT * FROM kw_core_wa_media WHERE business_id=? AND conversation_id=? AND event_id=? AND role=?',
        (bid,cid,eid,role))


def attach(bid, cid, rows):
    if not rows:
        return rows
    try:
        with store.transaction() as tx:
            store._locked(tx,bid,cid)
            events=[row.get('event_id') for row in rows if row.get('event_id')]
            if not events:
                return rows
            marks=','.join('?' for _ in events)
            media=tx.execute(
                'SELECT * FROM kw_core_wa_media WHERE business_id=? AND conversation_id=? '
                'AND event_id IN ('+marks+')',(bid,cid,*events))
    except Exception:
        # Staggered deploy/migration: text Inbox remains usable until media table is ready.
        return rows
    by_key={(row['event_id'],row['role']):row for row in media}
    for row in rows:
        item=by_key.get((row.get('event_id'),row.get('role')))
        if item:
            row['media']=item
    return rows


def get(bid,cid,key):
    if not isinstance(key,str) or not re.fullmatch(r'[a-f0-9]{32}',key):
        return None
    try:
        with store.transaction() as tx:
            store._locked(tx,bid,cid)
            return tx.one(
                'SELECT * FROM kw_core_wa_media WHERE id=? AND business_id=? AND conversation_id=?',
                (key,bid,cid))
    except Exception:
        return None


def _state(tx,bid,cid):
    jobs._lock(tx,bid)
    conv=store._locked(tx,bid,cid)
    link=binding(tx,bid,cid)
    if not link:
        raise store.ChatError('not_found',404)
    active=sync_human(tx,bid,cid,link['customer_phone'])
    allowed=(not active and int(time.time())-int(link.get('last_inbound_at') or 0)<23*3600)
    return conv,link,allowed


def freeform_allowed(bid,cid):
    try:
        with store.transaction() as tx:
            _conv,_link,allowed=_state(tx,bid,cid)
            return bool(allowed)
    except Exception:
        return False


def serve(bid,cid,row):
    from flask import Response
    cfg=whatsapp_access.channel(bid)
    if not cfg:
        response=Response('Media tidak tersedia',status=404,content_type='text/plain; charset=utf-8')
        response.headers['Cache-Control']='private, no-store'
        return response
    return inbox_media_service.serve(
        row,lambda: inbox_media_service.download(row,cfg['access_token'],cfg['phone_number_id']))


def _status_for_response(response, success_codes=(200,)):
    if response.status_code in success_codes:
        return None
    return 'unknown' if response.status_code>=500 or 200<=response.status_code<300 else 'failed'


def manual(bid,cid,event_id,upload,caption,actor):
    try:
        data,kind,mime,filename=inbox_media_service.validate_upload(upload)
    except ValueError as error:
        raise store.ChatError('invalid_media') from error
    caption=str(caption or '').strip()
    if len(caption)>1024:
        raise store.ChatError('invalid_media')
    digest=store.digest(json.dumps({
        'kind':kind,'mime':mime,'filename':filename,'caption':caption,
        'sha256':hashlib.sha256(data).hexdigest()
    },sort_keys=True,separators=(',',':')))

    with store.transaction() as tx:
        _conv,link,allowed=_state(tx,bid,cid)
        cfg=whatsapp_access.channel(bid,link['phone_number_id'])
        if not cfg:
            raise store.ChatError('channel_not_ready',409)
        existing=tx.one(
            'SELECT * FROM kw_core_wa_outbound WHERE business_id=? AND conversation_id=? AND event_id=?',
            (bid,cid,event_id))
        if existing:
            if existing['payload_hash']!=digest:
                raise store.ChatError('event_conflict',409)
            return existing
        if not allowed:
            raise store.ChatError('outside_24h_window',409)
        store.limit(tx,'owner-media:'+str(bid),60,20)
        tx.execute(
            'INSERT INTO kw_core_wa_outbound'
            '(business_id,conversation_id,event_id,payload_hash,status,created_at) VALUES (?,?,?,?,?,?)',
            (bid,cid,event_id,digest,'attempting',int(time.time())))

    version=__import__('os').environ.get('META_GRAPH_API_VERSION','v21.0')
    status='unknown';provider_id=None;error=None;media_id=None
    if not re.fullmatch(r'v[0-9]+\.[0-9]+',version):
        status,error='suppressed','channel_not_ready'
    else:
        headers={'Authorization':'Bearer '+cfg['access_token']}
        try:
            upload_response=requests.post(
                f"https://graph.facebook.com/{version}/{cfg['phone_number_id']}/media",
                headers=headers,data={'messaging_product':'whatsapp','type':mime},
                files={'file':(filename,data,mime)},timeout=(5,45),allow_redirects=False)
            upload_error=_status_for_response(upload_response,(200,201))
            if upload_error:
                status,error=upload_error,'media_upload_'+upload_error
            else:
                payload=upload_response.json()
                media_id=str(payload.get('id') or '') if isinstance(payload,dict) else ''
                if not re.fullmatch(r'[0-9]{1,128}',media_id):
                    status,error='unknown','media_upload_ambiguous'
                else:
                    meta={'id':media_id}
                    if caption: meta['caption']=caption
                    if kind=='document': meta['filename']=filename
                    send_response=requests.post(
                        f"https://graph.facebook.com/{version}/{cfg['phone_number_id']}/messages",
                        headers={**headers,'Content-Type':'application/json'},
                        json={'messaging_product':'whatsapp','to':link['customer_phone'],
                              'type':kind,kind:meta},
                        timeout=(5,30),allow_redirects=False)
                    send_error=_status_for_response(send_response,(200,))
                    if send_error:
                        status,error=send_error,'media_send_'+send_error
                    else:
                        body=send_response.json()
                        messages=body.get('messages') if isinstance(body,dict) else None
                        provider_id=(messages[0].get('id') if isinstance(messages,list) and messages
                                     and isinstance(messages[0],dict) else None)
                        if isinstance(provider_id,str) and provider_id:
                            status='accepted'
                        else:
                            status,error='unknown','media_send_ambiguous'
        except Exception:
            status,error='unknown','media_transport_uncertain'

    with store.transaction() as tx:
        jobs._lock(tx,bid)
        tx.execute(
            'UPDATE kw_core_wa_outbound SET status=?,provider_id=?,error=? '
            'WHERE business_id=? AND conversation_id=? AND event_id=?',
            (status,provider_id,error,bid,cid,event_id))

    if media_id:
        try:
            with store.transaction() as tx:
                jobs._lock(tx,bid); store._locked(tx,bid,cid)
                current=tx.one(
                    "SELECT id FROM kw_web_messages WHERE business_id=? AND conversation_id=? "
                    "AND event_id=? AND role='human'",(bid,cid,event_id))
                if not current:
                    label=caption or ('[PDF] '+filename if kind=='document' else '[Gambar]')
                    store._message(tx,bid,cid,event_id,'human',label)
                    record(tx,bid,cid,{
                        'id':event_id,'timestamp':int(time.time()),'type':kind,
                        kind:{'id':media_id,'mime_type':mime,'filename':filename,'caption':caption}
                    },'human')
                    tx.execute(
                        'INSERT INTO audit_log(actor_user_id,business_id,action,detail) VALUES (?,?,?,?)',
                        (actor,bid,'WHATSAPP_MEDIA_MANUAL',cid+':'+event_id))
        except Exception:
            # Provider result is authoritative; never encourage duplicate resend because history failed.
            return {'status':status,'error':'history_write_failed'}
    return {'status':status,'error':error}
