"""Provider-shared Embedded Signup. Customer tokens exist only in this request's memory.

See WHATSAPP_SELF_SERVICE.md for official API sources and deployment prerequisites.
"""
import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from contextlib import contextmanager

import requests
import db
import repo

log = logging.getLogger(__name__)
PUBLIC_ERROR = 'WhatsApp belum dapat dihubungkan. Muat ulang untuk mencoba lagi atau hubungi Kilas Works.'


class SignupError(Exception):
    pass


def settings():
    keys = ('META_APP_ID', 'META_EMBEDDED_SIGNUP_CONFIG_ID', 'WHATSAPP_APP_SECRET',
            'META_PROVIDER_BUSINESS_ID', 'META_PROVIDER_SYSTEM_USER_ID',
            'META_PROVIDER_ADMIN_ACCESS_TOKEN', 'WHATSAPP_ACCESS_TOKEN', 'META_REGISTRATION_PIN_KEY',
            'WHATSAPP_PHONE_NUMBER_ID')
    values = {k: os.environ.get(k, '').strip() for k in keys}
    version = os.environ.get('META_GRAPH_API_VERSION', 'v21.0').strip()
    if (not all(values.values()) or not re.fullmatch(r'v\d+\.\d+', version)
            or len(values['META_REGISTRATION_PIN_KEY']) < 32
            or any(not re.fullmatch(r'[0-9]{1,32}', values[k]) for k in
                   ('META_APP_ID', 'META_EMBEDDED_SIGNUP_CONFIG_ID', 'META_PROVIDER_BUSINESS_ID', 'META_PROVIDER_SYSTEM_USER_ID', 'WHATSAPP_PHONE_NUMBER_ID'))):
        raise SignupError('configuration_missing')
    values['version'] = version
    return values


def eligible(business_id, user):
    import security
    import payment_service
    business = security.require_business_access(business_id, user=user)
    if business['package'] not in ('AI_ADMIN', 'AI_ADMIN_BASIC', 'AI_ADMIN_PRO'):
        raise SignupError('package_ineligible')
    if business['status'] != 'APPROVED':
        raise SignupError('approval_required')
    if not payment_service.has_verified_ai_admin_payment(business_id):
        raise SignupError('payment_verification_required')
    if not repo.get_tenant_config_row(business_id):
        raise SignupError('provisioning_required')
    return business


def new_state(business_id, user_id):
    state = secrets.token_urlsafe(32)
    now = int(time.time())
    db.execute('INSERT INTO whatsapp_signup_sessions (business_id,user_id,state_hash,expires_at,used) '
               'VALUES (?,?,?,?,FALSE) ON CONFLICT(business_id) DO UPDATE SET '
               'user_id=excluded.user_id,state_hash=excluded.state_hash,expires_at=excluded.expires_at,used=FALSE',
               (business_id, user_id, hashlib.sha256(state.encode()).hexdigest(), now + 600))
    return state


def consume_state(business_id, user_id, state):
    if not isinstance(state, str) or len(state) > 128:
        raise SignupError('invalid_state')
    cur = db.execute('UPDATE whatsapp_signup_sessions SET used=TRUE WHERE business_id=? AND user_id=? '
                     'AND state_hash=? AND expires_at>? AND used=FALSE',
                     (business_id, user_id, hashlib.sha256(state.encode()).hexdigest(), int(time.time())))
    if cur.rowcount != 1:
        raise SignupError('invalid_state')


@contextmanager
def binding_lock():
    """Serialize phone bindings across tenants/workers, including the manual validator.

    No secrets in the lock table. Acquire before the per-business knowledge_writer lock.
    Nested DB helpers must not release the outer transaction.
    """
    if db._transaction_active():
        raise RuntimeError('nested_whatsapp_binding')
    conn = db.get_connection()
    cur = conn.cursor()
    try:
        cur.execute('UPDATE whatsapp_signup_lock SET id=id WHERE id=1')
        if cur.rowcount != 1:
            raise RuntimeError('whatsapp_binding_lock_missing')
        db._local.commerce_transaction = True
        db._local.commerce_failed = False
        yield
        if db._local.commerce_failed:
            raise RuntimeError('whatsapp_binding_aborted')
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        db._local.commerce_transaction = False
        cur.close()


class Graph:
    def __init__(self, config):
        self.config = config
        self.base = 'https://graph.facebook.com/' + config['version'] + '/'

    def call(self, method, path, token=None, **kwargs):
        try:
            response = requests.request(method, self.base + path,
                headers={'Authorization': 'Bearer ' + token} if token else {},
                timeout=(3, 8), allow_redirects=False, **kwargs)
            try:
                if response.status_code != 200:
                    raise SignupError('meta_http_' + str(int(response.status_code)))
                data = response.json()
                if not isinstance(data, dict) or 'error' in data:
                    raise SignupError('meta_response_invalid')
                return data
            finally:
                response.close()
        except SignupError:
            raise
        except (requests.RequestException, ValueError, TypeError):
            raise SignupError('meta_unavailable') from None

    def contains(self, path, token, target):
        # Cursor-only paging: never follow a Meta-supplied URL containing tokens.
        params = {'fields': 'id', 'limit': 100}
        for _ in range(20):
            page = self.call('GET', path, token, params=params)
            if any(str(row.get('id')) == target for row in page.get('data', []) if isinstance(row, dict)):
                return True
            paging = page.get('paging') or {}
            after = (paging.get('cursors') or {}).get('after')
            if not paging.get('next') or not isinstance(after, str) or len(after) > 4096:
                return False
            params = dict(params, after=after)
        raise SignupError('meta_listing_limit')

    def success(self, path, token, payload):
        if self.call('POST', path, token, json=payload).get('success') is not True:
            raise SignupError('meta_step_incomplete')


def verify_and_prepare(code, waba, phone):
    """Untrusted browser IDs are selectors, never authorization evidence."""
    config = settings()
    if not isinstance(code, str) or not 1 <= len(code) <= 4096:
        raise SignupError('invalid_payload')
    if any(not isinstance(x, str) or not re.fullmatch(r'[0-9]{1,32}', x) for x in (waba, phone)):
        raise SignupError('invalid_payload')
    if phone == os.environ.get('WHATSAPP_PHONE_NUMBER_ID', ''):
        raise SignupError('platform_phone_reserved')
    graph = Graph(config)
    exchanged = graph.call('GET', 'oauth/access_token', params={
        'client_id': config['META_APP_ID'], 'client_secret': config['WHATSAPP_APP_SECRET'], 'code': code})
    customer_token = exchanged.get('access_token')
    if not isinstance(customer_token, str) or not customer_token:
        raise SignupError('meta_token_missing')
    # Debug validates app provenance and customer-specific WABA grant. Shared provider access
    # alone must NEVER authorize a user to claim a different customer's WABA.
    debug = graph.call('GET', 'debug_token', config['META_APP_ID'] + '|' + config['WHATSAPP_APP_SECRET'],
                       params={'input_token': customer_token}).get('data', {})
    targets = {str(target) for scope in debug.get('granular_scopes', [])
               if scope.get('scope') == 'whatsapp_business_management'
               for target in scope.get('target_ids', [])}
    if debug.get('is_valid') is not True or str(debug.get('app_id')) != config['META_APP_ID'] or waba not in targets:
        raise SignupError('customer_grant_mismatch')
    if not graph.contains(waba + '/phone_numbers', customer_token, phone):
        raise SignupError('phone_waba_mismatch')
    admin = config['META_PROVIDER_ADMIN_ACCESS_TOKEN']
    runtime = config['WHATSAPP_ACCESS_TOKEN']
    if not graph.contains(config['META_PROVIDER_BUSINESS_ID'] + '/client_whatsapp_business_accounts', admin, waba):
        raise SignupError('provider_sharing_required')
    # Check configured runtime token belongs to the intended system user/app with messaging scopes.
    runtime_debug = graph.call('GET', 'debug_token', config['META_APP_ID'] + '|' + config['WHATSAPP_APP_SECRET'],
                              params={'input_token': runtime}).get('data', {})
    if (runtime_debug.get('is_valid') is not True or str(runtime_debug.get('app_id')) != config['META_APP_ID']
            or str(runtime_debug.get('user_id')) != config['META_PROVIDER_SYSTEM_USER_ID']
            or not {'whatsapp_business_management', 'whatsapp_business_messaging'}.issubset(runtime_debug.get('scopes', []))):
        raise SignupError('provider_token_invalid')
    graph.success(waba + '/assigned_users', admin,
                  {'user': config['META_PROVIDER_SYSTEM_USER_ID'], 'tasks': ['MANAGE']})
    if not graph.contains(waba + '/phone_numbers', runtime, phone):
        raise SignupError('provider_access_missing')
    graph.success(waba + '/subscribed_apps', runtime, {})
    status = graph.call('GET', phone, runtime, params={'fields': 'id,status,is_on_biz_app'})
    if str(status.get('id')) != phone:
        raise SignupError('phone_waba_mismatch')
    if status.get('is_on_biz_app') is not False:
        raise SignupError('business_app_support_required')
    if status.get('status') != 'CONNECTED':
        # Stable unique per-phone PIN for safe retry; no PIN/token persisted or displayed.
        digest = hmac.new(config['META_REGISTRATION_PIN_KEY'].encode(), phone.encode(), hashlib.sha256).digest()
        pin = f'{int.from_bytes(digest, "big") % 1000000:06d}'
        graph.success(phone + '/register', runtime, {'messaging_product': 'whatsapp', 'pin': pin})
        status = graph.call('GET', phone, runtime, params={'fields': 'id,status,is_on_biz_app'})
        if str(status.get('id')) != phone or status.get('status') != 'CONNECTED':
            raise SignupError('registration_pending')
    return waba, phone
