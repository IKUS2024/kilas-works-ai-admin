"""Owner WEB inbox. Authenticated business scope, independent from all WhatsApp handlers."""
from flask import Blueprint, abort, jsonify, render_template, request
import security as owner_security
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
    return render_template('web_inbox.html',business=business,conversations=conversations,
                           total=total,page=page,pages=pages,selected=selected)


@owner_bp.get('/business/<int:bid>/web-inbox/<cid>/messages')
@owner_security.login_required
def messages(bid,cid):
    business_for_owner(bid)
    selected=store.conversation(bid,cid)
    after=request.args.get('after',0,type=int)
    if after is None or after<0:
        raise store.ChatError('invalid_cursor')
    return jsonify(channel='WEB',mode=selected['mode'],messages=store.thread(bid,cid,after))
