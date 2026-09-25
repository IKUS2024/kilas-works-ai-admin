"""WEB-only rollout, tenant eligibility and independent anonymous visitor CSRF."""
import hashlib
import hmac
import os
from flask import abort, current_app, request
import repo
import subscription_service
from kilas_core.flags import enabled_for_business
from . import store


def available(business):
    eligible = bool(business and os.environ.get('KILAS_WEB_CHAT_ENABLED', '').lower() == 'true'
                    and enabled_for_business(business['id'])
                    and business.get('package') in ('AI_ADMIN', 'AI_ADMIN_BASIC', 'AI_ADMIN_PRO')
                    and business.get('status') not in ('ARCHIVED', 'SUSPENDED', 'CANCELLED'))
    if not eligible:
        return False
    # Same existing paid-runtime rule as WhatsApp, without importing its app/adapter.
    # Rollout permission is never a substitute for a paid AI Admin entitlement.
    try:
        subscription = subscription_service.get_subscription(business['id'])
        return bool(subscription and subscription['status'] in ('ACTIVE', 'GRACE'))
    except Exception:
        return False



def resolve(slug):
    if os.environ.get('KILAS_WEB_CHAT_ENABLED', '').lower() != 'true':
        abort(404)
    channel = store.channel(slug=slug)
    if not channel or not channel['enabled']:
        abort(404)
    business = repo.get_business(channel['business_id'])
    if not available(business):
        abort(404)
    return business


def cookie_name(bid):
    return 'kw_web_' + str(bid)


def csrf(token):
    return hmac.new(current_app.secret_key.encode(), ('web-csrf:' + token).encode(), hashlib.sha256).hexdigest()


def same_origin():
    # No CORS granted. All public writes require a non-simple header plus exact browser Origin.
    if request.headers.get('Origin') != request.host_url.rstrip('/') or request.headers.get('X-Web-Chat') != '1':
        abort(403)
    if request.headers.get('Sec-Fetch-Site') not in (None, 'same-origin'):
        abort(403)
    if not request.is_json:
        abort(415)


def identity(bid, cid, write=False):
    token = request.cookies.get(cookie_name(bid), '')
    conversation = store.authorized(bid, cid, token)
    if write and not hmac.compare_digest(request.headers.get('X-Web-CSRF', ''), csrf(token)):
        abort(403)
    return conversation


def ip_key():
    # Do not trust client-controlled X-Forwarded-For; proxy installations may be more restrictive.
    return hmac.new(current_app.secret_key.encode(), (request.remote_addr or 'unknown').encode(), hashlib.sha256).hexdigest()
