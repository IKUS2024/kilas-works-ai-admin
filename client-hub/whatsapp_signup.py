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
from urllib.parse import urlparse

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
    """Browser-side Meta configuration for Kilas Works' own platform Coexistence flow.

    Platform Cloud API credentials deliberately stay in the AI Admin bot service. Client Hub only
    needs the app/config identity and app secret for the one-time Embedded Signup OAuth exchange.
    """
    keys = ('META_APP_ID', 'META_EMBEDDED_SIGNUP_CONFIG_ID', 'WHATSAPP_APP_SECRET')
    values = {k: os.environ.get(k, '').strip() for k in keys}
    version = os.environ.get('META_GRAPH_API_VERSION', 'v21.0').strip()
    if (not all(values.values()) or not re.fullmatch(r'v\d+\.\d+', version)
            or any(not re.fullmatch(r'[0-9]{1,32}', values[k]) for k in
                   ('META_APP_ID', 'META_EMBEDDED_SIGNUP_CONFIG_ID'))):
        raise SignupError('configuration_missing')
    values['version'] = version
    return values


def normalize_phone_digits(value):
    digits = re.sub(r'\D', '', str(value or ''))
    return digits if re.fullmatch(r'\d{6,20}', digits) else None


def _platform_bot_base_url():
    explicit = (os.environ.get('KILAS_BOT_INTERNAL_URL') or '').strip()
    if not explicit:
        explicit = (os.environ.get('KILAS_BOT_PLATFORM_REPLY_URL') or '').strip()
    if not explicit:
        return None
    try:
        parsed = urlparse(explicit)
    except Exception:
        return None
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return None
    return f'{parsed.scheme}://{parsed.netloc}'


def _platform_bot_call(action, payload=None):
    base = _platform_bot_base_url()
    secret = (os.environ.get('INTERNAL_SERVICE_SECRET') or '').strip()
    if not base or not secret:
        raise SignupError('platform_bot_bridge_unavailable')
    try:
        response = requests.post(
            f'{base}/internal/platform-wa-migration/{action}',
            json=payload or {},
            headers={'X-Internal-Service-Secret': secret},
            timeout=(3, 12),
            allow_redirects=False,
        )
        try:
            data = response.json()
        except ValueError:
            raise SignupError('platform_bot_bad_response') from None
        if response.status_code != 200 or not isinstance(data, dict) or data.get('status') != 'ok':
            reason = str(data.get('reason') or '') if isinstance(data, dict) else ''
            allowed = {
                'platform_phone_unavailable', 'platform_phone_mismatch',
                'platform_already_coexistence', 'coexistence_not_ready',
                'invalid_payload', 'meta_request_failed', 'access_denied',
            }
            raise SignupError(reason if reason in allowed else 'platform_bot_rejected')
        return data
    except SignupError:
        raise
    except requests.RequestException:
        raise SignupError('platform_bot_bridge_unavailable') from None


def platform_current_identity():
    data = _platform_bot_call('status')
    identity = data.get('identity')
    if not isinstance(identity, dict) or not identity.get('phone_number_id'):
        raise SignupError('platform_phone_unavailable')
    return identity


def deregister_platform_phone(expected_phone_digits):
    expected = normalize_phone_digits(expected_phone_digits)
    if not expected:
        raise SignupError('platform_phone_unavailable')
    data = _platform_bot_call('deregister', {'expected_phone_digits': expected})
    identity = data.get('identity')
    if not isinstance(identity, dict):
        raise SignupError('platform_bot_bad_response')
    return identity


def verify_platform_coexistence(code, waba, phone=None, *, expected_phone_digits):
    """Verify browser authorization in Client Hub, runtime access in the bot service.

    Client Hub never receives the production WhatsApp runtime token. The one-time Meta login code
    proves that the logged-in business granted this app access to the selected WABA/phone; the bot
    then independently verifies that its existing server-side runtime credential can see the same
    number in CONNECTED Business-App Coexistence state.
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
    runtime = _platform_bot_call('verify', {
        'waba_id': waba,
        'phone_number_id': selected,
        'expected_phone_digits': expected,
    })
    if str(runtime.get('phone_number_id') or '') != selected:
        raise SignupError('platform_phone_mismatch')
    return waba, selected


def eligible(business_id, user):
    import security
    import payment_service
    business = security.require_business_access(business_id, user=user)
    if business['package'] not in ('AI_ADMIN', 'AI_ADMIN_BASIC', 'AI_ADMIN_PRO'):
        raise SignupError('package_ineligible')
    from public_chat.security import available as web_available
    web_active = business['status']=='ACTIVE' and web_available(business)
    if business['status'] != 'APPROVED' and not web_active:
        raise SignupError('approval_required')
    if web_active and (repo.get_whatsapp_config(business_id) or {}).get('connection_status')=='CONNECTED':
        raise SignupError('channel_already_connected')
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
