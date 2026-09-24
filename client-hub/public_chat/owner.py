"""Owner WEB inbox. Authenticated business scope, independent from all WhatsApp handlers."""
from flask import Blueprint, abort, jsonify, render_template, request, url_for
import re
import repo
import security as owner_security
from kilas_core import customers as core_customers
from . import security, store

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
                           selected_customer=selected_customer)


@owner_bp.get('/business/<int:bid>/web-inbox/<cid>/messages')
@owner_security.login_required
def messages(bid,cid):
    business_for_owner(bid)
    selected=store.conversation(bid,cid)
    after=request.args.get('after',0,type=int)
    if after is None or after<0:
        raise store.ChatError('invalid_cursor')
    return jsonify(channel='WEB',mode=selected['mode'],messages=store.thread(bid,cid,after))


@owner_bp.post('/business/<int:bid>/web-inbox/<cid>/mode')
@owner_security.login_required
def mode(bid,cid):
    business_for_owner(bid)
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict): raise store.ChatError('invalid_mode')
    mode=store.set_mode(bid,cid,payload.get('mode'),owner_security.current_user()['id'])
    return jsonify(channel='WEB',mode=mode)


@owner_bp.post('/business/<int:bid>/web-inbox/<cid>/reply')
@owner_security.login_required
def reply(bid,cid):
    business_for_owner(bid)
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict): raise store.ChatError('invalid_message')
    text,event=payload.get('message'),payload.get('event_id')
    if not isinstance(text,str) or not text.strip() or len(text)>4000: raise store.ChatError('invalid_message')
    if not isinstance(event,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',event): raise store.ChatError('invalid_event_id')
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
