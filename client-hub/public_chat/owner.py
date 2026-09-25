"""Shared owner Inbox. Authenticated business scope; channel-specific delivery adapters."""
from flask import Blueprint, abort, jsonify, render_template, request, url_for
import re
import repo
import security as owner_security
from kilas_core import customers as core_customers
from . import security, store
from kilas_core.job_routes import linked_context

owner_bp=Blueprint('owner_web',__name__)


def business_for_owner(bid):
    business=owner_security.require_business_access(bid)
    if not security.available(business):
        abort(404)
    return business


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
    return render_template('web_inbox.html',business=business,conversations=conversations,
                           total=total,page=page,pages=pages,selected=selected,
                           mixed_channels=any(row['id'].startswith('wa_') for row in conversations),
                           selected_customer=selected_customer,
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
    messages=store.thread(bid,cid,after)
    delivery={}
    if is_wa:
        with store.transaction() as tx:
            states=tx.execute('SELECT m.id,o.status FROM kw_web_messages m LEFT JOIN kw_core_wa_outbound o ON o.business_id=m.business_id AND o.conversation_id=m.conversation_id AND o.event_id=m.event_id WHERE m.business_id=? AND m.conversation_id=? AND m.role!=?',(bid,cid,'user'))
        delivery={r['id']:r['status'] for r in states}
        for message in messages:
            message['delivery_status']=delivery.get(message['id']) if message['role']!='user' else None
    return jsonify(channel='WHATSAPP' if is_wa else 'WEB',mode=selected['mode'],messages=messages,delivery=delivery)


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
