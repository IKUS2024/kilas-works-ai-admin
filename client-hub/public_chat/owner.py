"""Shared owner Inbox. Authenticated business scope; channel-specific delivery adapters."""
from datetime import datetime, timezone
from flask import Blueprint, abort, jsonify, render_template, request, url_for
import re
import time
import repo
import security as owner_security
import inbox_media_service
import inbox_service
import wa_inbox_shared
from kilas_core import customers as core_customers
from . import security, store
from kilas_core.job_routes import linked_context

owner_bp=Blueprint('owner_web',__name__)


def business_for_owner(bid):
    business=owner_security.require_business_access(bid)
    if not security.available(business):
        abort(404)
    return business


def _wa_state(bid,cid):
    from kilas_core.adapters import whatsapp
    link=whatsapp.mapped(bid,cid)
    if not link:
        return None,None
    raw=int(link.get('last_inbound_at') or 0)
    last=datetime.fromtimestamp(raw,timezone.utc) if raw>0 else None
    return link,wa_inbox_shared.compute_freeform_window_status(last)


def _media_projection(bid,row):
    media=row.get('media')
    if not media:
        return None
    return {
        'id':media['id'],
        'message_type':media['message_type'],
        'filename':media['filename'],
        'caption':media.get('caption') or '',
        'url':url_for('client.inbox_media',business_id=bid,media_key=media['id']),
    }


@owner_bp.errorhandler(store.ChatError)
def error_response(error):
    return jsonify(error=error.code),error.status


def inbox_page(business):
    if not security.available(business):
        abort(404)
    bid=business['id']
    conversations,total,page,pages=store.inbox(bid,request.args.get('page',1,type=int) or 1)
    cid=request.args.get('conversation')
    try:
        selected=store.conversation(bid,cid) if cid else None
    except store.ChatError as error:
        abort(error.status)
    selected_customer = core_customers.customer_for_conversation(bid, cid) if selected and core_customers.enabled() else None
    wa_link,window=_wa_state(bid,cid) if selected else (None,None)
    template_readiness=(
        inbox_service.template_readiness(bid)
        if wa_link and selected and selected['mode']=='HUMAN_TAKEOVER'
        and not (window and window.get('allowed')) else None
    )
    return render_template('web_inbox.html',business=business,conversations=conversations,
                           total=total,page=page,pages=pages,selected=selected,
                           mixed_channels=any(row['id'].startswith('wa_') for row in conversations),
                           selected_customer=selected_customer,window=window,
                           template_readiness=template_readiness,
                           linked_jobs=linked_context(business,selected_customer["id"],cid) if selected_customer else None)


@owner_bp.get('/business/<int:bid>/web-inbox/<cid>/messages')
@owner_security.login_required
def messages(bid,cid):
    business_for_owner(bid)
    selected=store.conversation(bid,cid)
    after=request.args.get('after',0,type=int)
    if after is None or after<0:
        raise store.ChatError('invalid_cursor')
    is_wa=cid.startswith('wa_')
    with store.transaction() as tx:
        store._locked(tx,bid,cid)
        messages=tx.execute(
            'SELECT id,event_id,role,content,created_at FROM kw_web_messages '
            'WHERE business_id=? AND conversation_id=? AND id>? ORDER BY id LIMIT 100',
            (bid,cid,after))
    delivery={}
    window=None
    template_ready=False
    if is_wa:
        inbox_media_service.attach_events(messages,bid)
        with store.transaction() as tx:
            states=tx.execute(
                'SELECT m.id,o.status FROM kw_web_messages m LEFT JOIN kw_core_wa_outbound o '
                'ON o.business_id=m.business_id AND o.conversation_id=m.conversation_id '
                'AND o.event_id=m.event_id WHERE m.business_id=? AND m.conversation_id=? AND m.role!=?',
                (bid,cid,'user'))
        delivery={r['id']:r['status'] for r in states}
        for message in messages:
            message['delivery_status']=delivery.get(message['id']) if message['role']!='user' else None
            media=_media_projection(bid,message)
            if media:
                message['media']=media
        _link,window=_wa_state(bid,cid)
        if selected['mode']=='HUMAN_TAKEOVER' and not (window and window.get('allowed')):
            template_ready=bool(inbox_service.template_readiness(bid).get('ready'))
    return jsonify(channel='WHATSAPP' if is_wa else 'WEB',mode=selected['mode'],
                   messages=messages,delivery=delivery,window=window,
                   template_ready=template_ready)


@owner_bp.post('/business/<int:bid>/web-inbox/<cid>/mode')
@owner_security.login_required
def mode(bid,cid):
    business_for_owner(bid)
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict): raise store.ChatError('invalid_mode')
    from kilas_core.adapters import whatsapp
    setter = whatsapp.mode if whatsapp.mapped(bid,cid) else store.set_mode
    mode=setter(bid,cid,payload.get('mode'),owner_security.current_user()['id'])
    return jsonify(channel='WHATSAPP' if cid.startswith('wa_') else 'WEB',mode=mode)


@owner_bp.post('/business/<int:bid>/web-inbox/<cid>/reply')
@owner_security.login_required
def reply(bid,cid):
    business_for_owner(bid)
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict): raise store.ChatError('invalid_message')
    text,event=payload.get('message'),payload.get('event_id')
    if not isinstance(text,str) or not text.strip() or len(text)>4000: raise store.ChatError('invalid_message')
    if not isinstance(event,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',event): raise store.ChatError('invalid_event_id')
    from kilas_core.adapters import whatsapp
    if whatsapp.mapped(bid,cid):
        from kilas_core.whatsapp_transport import manual
        result=manual(bid,cid,event,text.strip(),owner_security.current_user()['id'])
        return jsonify(channel='WHATSAPP',status=result['status'])
    mid=store.human_reply(bid,cid,event,text.strip(),owner_security.current_user()['id'])
    return jsonify(channel='WEB',message_id=mid)


@owner_bp.post('/business/<int:bid>/web-inbox/<cid>/media')
@owner_security.login_required
def media(bid,cid):
    business_for_owner(bid)
    if not request.content_length or request.content_length>12*1024*1024:
        raise store.ChatError('media_too_large',413)
    from kilas_core.adapters import whatsapp
    from kilas_core import whatsapp_access
    link=whatsapp.mapped(bid,cid)
    if not link:
        abort(404)
    channel=whatsapp_access.channel(bid,link['phone_number_id'])
    if not channel:
        raise store.ChatError('channel_not_ready',409)

    def allowed():
        with store.transaction() as tx:
            current=whatsapp.binding(tx,bid,cid)
            if not current:
                return False
            ai_active=whatsapp.sync_human(tx,bid,cid,current['customer_phone'])
            if ai_active:
                return False
            return bool(current.get('last_inbound_at')) and (
                int(time.time())-int(current['last_inbound_at'])<23*3600)

    ok,reason,detail=inbox_media_service.send_upload_detail(
        bid,link['customer_phone'],request.files.get('file'),request.form.get('caption'),
        channel,allowed)
    if not ok:
        raise store.ChatError('whatsapp_media_'+reason,409)
    history='stored'
    try:
        event=detail['provider_id']
        text=detail.get('caption') or '['+detail['kind']+']'
        with store.transaction() as tx:
            store._locked(tx,bid,cid)
            existing=tx.one(
                "SELECT id FROM kw_web_messages WHERE business_id=? AND conversation_id=? "
                "AND event_id=? AND role='human'",(bid,cid,event))
            if not existing:
                store._message(tx,bid,cid,event,'human',text)
                tx.execute(
                    'INSERT INTO audit_log(actor_user_id,business_id,action,detail) VALUES (?,?,?,?)',
                    (owner_security.current_user()['id'],bid,'WEB_MANUAL_MEDIA',cid+':'+event))
    except Exception:
        history='unavailable'
    return jsonify(channel='WHATSAPP',status='accepted',history=history)


@owner_bp.post('/business/<int:bid>/web-chat/link')
@owner_security.login_required
def share(bid):
    business_for_owner(bid)
    if not (repo.get_ai_settings(bid) or {}).get('normalized_config'):
        raise store.ChatError('business_setup_required',409)
    channel=store.ensure_channel(bid)
    if not channel['enabled']:
        raise store.ChatError('channel_disabled',409)
    return jsonify(path=url_for('public_web.page',slug=channel['slug']),channel='WEB')


@owner_bp.post('/business/<int:bid>/web-inbox/<cid>/template')
@owner_security.login_required
def template(bid,cid):
    business_for_owner(bid)
    from kilas_core.adapters import whatsapp
    from kilas_core.whatsapp_transport import manual
    if not whatsapp.mapped(bid,cid): abort(404)
    payload=request.get_json(silent=True)
    event=payload.get('event_id') if isinstance(payload,dict) else None
    if not isinstance(event,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',event):
        raise store.ChatError('invalid_event_id')
    result=manual(bid,cid,event,'',owner_security.current_user()['id'],template=True)
    return jsonify(channel='WHATSAPP',status=result['status'])
