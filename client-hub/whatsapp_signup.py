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


def platform_settings():
    """Minimum server-side configuration for Kilas Works' own platform number.

    Unlike tenant onboarding, this path does not need provider client-WABA sharing/admin assignment
    because the platform number belongs to Kilas Works itself. It still validates the same app,
    runtime System User and messaging scopes before any mutation.
    """
    keys = ('META_APP_ID', 'META_EMBEDDED_SIGNUP_CONFIG_ID', 'WHATSAPP_APP_SECRET',
            'META_PROVIDER_SYSTEM_USER_ID', 'WHATSAPP_ACCESS_TOKEN', 'WHATSAPP_PHONE_NUMBER_ID')
    values = {k: os.environ.get(k, '').strip() for k in keys}
    version = os.environ.get('META_GRAPH_API_VERSION', 'v21.0').strip()
    if (not all(values.values()) or not re.fullmatch(r'v\d+\.\d+', version)
            or any(not re.fullmatch(r'[0-9]{1,32}', values[k]) for k in
                   ('META_APP_ID', 'META_EMBEDDED_SIGNUP_CONFIG_ID',
                    'META_PROVIDER_SYSTEM_USER_ID', 'WHATSAPP_PHONE_NUMBER_ID'))):
        raise SignupError('configuration_missing')
    values['version'] = version
    return values


def normalize_phone_digits(value):
    digits = re.sub(r'\D', '', str(value or ''))
    return digits if re.fullmatch(r'\d{6,20}', digits) else None


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

    def list_rows(self, path, token, fields='id'):
        """Bounded cursor-only listing; never follows Meta-supplied paging URLs."""
        params = {'fields': fields, 'limit': 100}
        rows = []
        for _ in range(20):
            page = self.call('GET', path, token, params=params)
            data = page.get('data', [])
            if not isinstance(data, list):
                raise SignupError('meta_response_invalid')
            rows.extend(row for row in data if isinstance(row, dict))
            paging = page.get('paging') or {}
            after = (paging.get('cursors') or {}).get('after')
            if not paging.get('next') or not isinstance(after, str) or len(after) > 4096:
                return rows
            params = dict(params, after=after)
        raise SignupError('meta_listing_limit')

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


def _platform_runtime(config, graph):
    """Return the configured platform runtime token only after app/user/scope verification."""
    runtime = config['WHATSAPP_ACCESS_TOKEN']
    debug = graph.call(
        'GET', 'debug_token', config['META_APP_ID'] + '|' + config['WHATSAPP_APP_SECRET'],
        params={'input_token': runtime},
    ).get('data', {})
    if (debug.get('is_valid') is not True
            or str(debug.get('app_id')) != config['META_APP_ID']
            or str(debug.get('user_id')) != config['META_PROVIDER_SYSTEM_USER_ID']
            or not {'whatsapp_business_management', 'whatsapp_business_messaging'}.issubset(
                debug.get('scopes', []))):
        raise SignupError('provider_token_invalid')
    return runtime


def platform_current_identity():
    """Live identity/status for Kilas Works' own currently configured Cloud API number."""
    config = platform_settings()
    graph = Graph(config)
    runtime = _platform_runtime(config, graph)
    phone = config['WHATSAPP_PHONE_NUMBER_ID']
    row = graph.call(
        'GET', phone, runtime,
        params={'fields': 'id,display_phone_number,status,is_on_biz_app,platform_type'},
    )
    digits = normalize_phone_digits(row.get('display_phone_number'))
    if str(row.get('id')) != phone or not digits:
        raise SignupError('platform_phone_unavailable')
    return {
        'phone_number_id': phone,
        'display_phone_number': row.get('display_phone_number'),
        'display_phone_digits': digits,
        'status': row.get('status'),
        'is_on_biz_app': row.get('is_on_biz_app'),
        'platform_type': row.get('platform_type'),
    }


def deregister_platform_phone(expected_phone_digits):
    """Explicitly remove ONLY the configured platform Phone Number ID from Cloud API.

    The caller must already have required a typed human confirmation. No WABA, app, webhook or
    tenant row is deleted. This is the reversible Meta registration step used before putting the
    same number into WhatsApp Business App and then onboarding it back as Coexistence.
    """
    expected = normalize_phone_digits(expected_phone_digits)
    if not expected:
        raise SignupError('platform_phone_unavailable')
    identity = platform_current_identity()
    if identity['display_phone_digits'] != expected:
        raise SignupError('platform_phone_mismatch')
    if identity.get('is_on_biz_app') is True:
        raise SignupError('platform_already_coexistence')

    config = platform_settings()
    graph = Graph(config)
    runtime = _platform_runtime(config, graph)
    result = graph.call('POST', identity['phone_number_id'] + '/deregister', runtime)
    if result.get('success') is not True:
        raise SignupError('meta_step_incomplete')
    return identity


def verify_platform_coexistence(code, waba, phone=None, *, expected_phone_digits):
    """Verify the platform number after WhatsApp Business App Coexistence Embedded Signup.

    This is intentionally separate from tenant verify_and_prepare(): the platform number is
    reserved from tenant binding and its WABA is Kilas Works' own asset, not a provider-shared
    client WABA. Authorization still comes from the one-time customer/business login code and the
    configured runtime System User must independently see the exact same display phone number.
    """
    config = platform_settings()
    expected = normalize_phone_digits(expected_phone_digits)
    if (not expected or not isinstance(code, str) or not 1 <= len(code) <= 4096
            or not isinstance(waba, str) or not re.fullmatch(r'[0-9]{1,32}', waba)
            or (phone is not None and
                (not isinstance(phone, str) or not re.fullmatch(r'[0-9]{1,32}', phone)))):
        raise SignupError('invalid_payload')

    graph = Graph(config)
    exchanged = graph.call('GET', 'oauth/access_token', params={
        'client_id': config['META_APP_ID'],
        'client_secret': config['WHATSAPP_APP_SECRET'],
        'code': code,
    })
    customer_token = exchanged.get('access_token')
    if not isinstance(customer_token, str) or not customer_token:
        raise SignupError('meta_token_missing')

    debug = graph.call(
        'GET', 'debug_token', config['META_APP_ID'] + '|' + config['WHATSAPP_APP_SECRET'],
        params={'input_token': customer_token},
    ).get('data', {})
    targets = {
        str(target)
        for scope in debug.get('granular_scopes', [])
        if scope.get('scope') == 'whatsapp_business_management'
        for target in scope.get('target_ids', [])
    }
    if (debug.get('is_valid') is not True
            or str(debug.get('app_id')) != config['META_APP_ID']
            or waba not in targets):
        raise SignupError('customer_grant_mismatch')

    rows = graph.list_rows(waba + '/phone_numbers', customer_token, 'id,display_phone_number')
    if not rows or len(rows) > 25:
        raise SignupError('coexistence_phone_missing')
    matches = []
    for row in rows:
        candidate = str(row.get('id') or '')
        if not re.fullmatch(r'[0-9]{1,32}', candidate):
            continue
        detail = graph.call(
            'GET', candidate, customer_token,
            params={'fields': 'id,display_phone_number,status,is_on_biz_app,platform_type'},
        )
        if (str(detail.get('id')) == candidate
                and normalize_phone_digits(detail.get('display_phone_number')) == expected
                and detail.get('is_on_biz_app') is True):
            matches.append((candidate, detail))

    if phone:
        matches = [item for item in matches if item[0] == phone]
    if len(matches) != 1:
        raise SignupError('coexistence_phone_ambiguous' if matches else 'coexistence_phone_missing')
    selected = matches[0][0]

    runtime = _platform_runtime(config, graph)
    runtime_row = graph.call(
        'GET', selected, runtime,
        params={'fields': 'id,display_phone_number,status,is_on_biz_app,platform_type'},
    )
    if (str(runtime_row.get('id')) != selected
            or normalize_phone_digits(runtime_row.get('display_phone_number')) != expected):
        raise SignupError('platform_phone_mismatch')
    if (runtime_row.get('is_on_biz_app') is not True
            or runtime_row.get('status') != 'CONNECTED'
            or runtime_row.get('platform_type') not in (None, 'CLOUD_API')):
        raise SignupError('coexistence_not_ready')

    graph.success(waba + '/subscribed_apps', runtime, {})
    return waba, selected


def verify_and_prepare(code, waba, phone=None, *, coexistence=False):
    """Verify Embedded Signup entirely server-side.

    Coexistence completion can omit phone_number_id. In that case the phone is discovered only
    inside the customer-granted WABA, then re-verified with the provider runtime credential.
    """
    config = settings()
    if not isinstance(code, str) or not 1 <= len(code) <= 4096:
        raise SignupError('invalid_payload')
    if (type(coexistence) is not bool or not isinstance(waba, str)
            or not re.fullmatch(r'[0-9]{1,32}', waba)
            or (phone is not None and (not isinstance(phone, str)
                or not re.fullmatch(r'[0-9]{1,32}', phone)))):
        raise SignupError('invalid_payload')
    if phone and phone == os.environ.get('WHATSAPP_PHONE_NUMBER_ID', ''):
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
    customer_phones = graph.list_rows(waba + '/phone_numbers', customer_token, 'id')
    customer_phone_ids = {
        str(row.get('id')) for row in customer_phones
        if isinstance(row.get('id'), (str, int)) and re.fullmatch(r'[0-9]{1,32}', str(row.get('id')))
    }
    if phone:
        if phone not in customer_phone_ids:
            raise SignupError('phone_waba_mismatch')
    elif coexistence:
        # FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING may return only waba_id. Resolve the unique
        # Business-App-backed phone from the customer's own granted WABA; never guess across WABAs.
        if not customer_phone_ids or len(customer_phone_ids) > 25:
            raise SignupError('coexistence_phone_missing')
        candidates = []
        for candidate in sorted(customer_phone_ids):
            detail = graph.call('GET', candidate, customer_token,
                                params={'fields': 'id,is_on_biz_app'})
            if str(detail.get('id')) == candidate and detail.get('is_on_biz_app') is True:
                candidates.append(candidate)
        if len(candidates) != 1:
            raise SignupError('coexistence_phone_ambiguous' if candidates else 'coexistence_phone_missing')
        phone = candidates[0]
        if phone == os.environ.get('WHATSAPP_PHONE_NUMBER_ID', ''):
            raise SignupError('platform_phone_reserved')
    else:
        raise SignupError('invalid_payload')
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
    status = graph.call('GET', phone, runtime,
                        params={'fields': 'id,status,is_on_biz_app,platform_type'})
    if str(status.get('id')) != phone:
        raise SignupError('phone_waba_mismatch')
    if coexistence:
        # A Business App number is already registered. Never call /register here: doing so would
        # treat it as a normal API-only number and risks breaking the supported coexistence flow.
        if status.get('is_on_biz_app') is not True:
            raise SignupError('coexistence_not_ready')
        platform_type = status.get('platform_type')
        if platform_type not in (None, 'CLOUD_API') or status.get('status') != 'CONNECTED':
            raise SignupError('coexistence_not_ready')
        return waba, phone, 'COEXISTENCE'
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
    return waba, phone, 'CLOUD_API'
