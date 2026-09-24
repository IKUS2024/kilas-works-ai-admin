"""Anonymous public WEB endpoints. Owner endpoints are added separately, never WA sends."""
from flask import Blueprint, jsonify, make_response, render_template, request
from . import security, store

public_bp = Blueprint('public_web', __name__)


@public_bp.before_request
def guard():
    request.max_content_length = 20 * 1024
    if request.method == 'POST':
        security.same_origin()


@public_bp.after_request
def headers(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


@public_bp.errorhandler(store.ChatError)
def chat_error(error):
    response = jsonify(error=error.code)
    response.status_code = error.status
    if error.status == 429:
        response.headers['Retry-After'] = '60'
    return response


@public_bp.get('/chat/<slug>')
def page(slug):
    return render_template('public_web_chat.html', business=security.resolve(slug), slug=slug)


@public_bp.post('/chat/<slug>/session')
def session_start(slug):
    business = security.resolve(slug)
    bid = business['id']
    conversation, token = store.visitor(bid, request.cookies.get(security.cookie_name(bid)), security.ip_key())
    response = make_response(jsonify(conversation_id=conversation['id'], csrf=security.csrf(token), channel='WEB'))
    response.set_cookie(security.cookie_name(bid), token, httponly=True, secure=request.is_secure,
                        samesite='Strict', max_age=7*86400, path='/chat/' + slug)
    return response


@public_bp.get('/chat/<slug>/<cid>/messages')
def messages(slug, cid):
    business = security.resolve(slug)
    conversation = security.identity(business['id'], cid)
    with store.transaction() as tx:
        store.limit(tx, 'read:' + conversation['id'], 60, 60)
    after = request.args.get('after', 0, type=int)
    if after is None or after < 0:
        raise store.ChatError('invalid_cursor')
    return jsonify(channel='WEB', mode=conversation['mode'], messages=store.thread(business['id'], cid, after))
