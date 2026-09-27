"""Bot-side assisted connection transport. Tokens never leave this process."""
import os
import re
from datetime import datetime, timedelta, timezone
import requests
import db
import repo
import assist_connections as workflow
from whatsapp_signup import binding_lock, normalize_phone_digits


def configuration():
    """Allowlisted configuration evidence, safe for internal operational logs.

    Credentials and arbitrary environment fields never cross the service boundary.
    This is not a provider connectivity or delivery test.
    """
    sha = os.environ.get('RENDER_GIT_COMMIT', '')
    return {'commit':sha if re.fullmatch(r'[a-f0-9]{40}', sha) else 'unavailable',
            'whatsapp':bool(os.environ.get('WHATSAPP_ACCESS_TOKEN', '').strip()),
            'openai':bool(os.environ.get('OPENAI_API_KEY', '').strip()),
            'claude':bool(os.environ.get('ANTHROPIC_API_KEY', '').strip()),
            'webhook_signature':bool(os.environ.get('WHATSAPP_APP_SECRET', '').strip()),
            'assist_runtime':os.environ.get('KILAS_ASSIST_RUNTIME_ENABLED','').lower()=='true'}


def health():
    db.query_one('SELECT 1 AS ok')
    return dict(configuration(), status='ok', database=True)


def _token(bid, ref):
    if ref not in ('', None, 'WHATSAPP_TOKEN__TENANT_'+str(bid)):
        raise ValueError('invalid_reference')
    token = os.environ.get(ref or 'WHATSAPP_ACCESS_TOKEN', '').strip()
    if not token:
        raise ValueError('credentials_unavailable')
    return token


def graph(method, path, token, **kwargs):
    version = os.environ.get('META_GRAPH_API_VERSION', 'v21.0')
    if not re.fullmatch(r'v\d+\.\d+', version):
        raise ValueError('invalid_graph_version')
    try:
        response = requests.request(method, 'https://graph.facebook.com/'+version+'/'+path,
            headers={'Authorization': 'Bearer '+token}, timeout=(3, 12), allow_redirects=False, **kwargs)
        result = response.json()
        if response.status_code != 200 or not isinstance(result, dict) or result.get('error'):
            raise ValueError('meta_request_failed')
        return result
    except (requests.RequestException, ValueError, TypeError):
        raise ValueError('meta_request_failed') from None


def verify(payload):
    bid = int(payload['business_id'])
    row = workflow.get(bid)
    if not row or row['state'] not in ('Processing', 'Waiting OTP', 'Error'):
        raise ValueError('not_processing')
    waba, pid = str(payload.get('waba_id') or ''), str(payload.get('phone_number_id') or '')
    if not all(re.fullmatch(r'[0-9]{1,32}', v) for v in (waba, pid)):
        raise ValueError('invalid_mapping')
    if pid == os.environ.get('WHATSAPP_PHONE_NUMBER_ID'):
        raise ValueError('platform_number_reserved')
    token = _token(bid, payload.get('credentials_reference'))
    # Read membership from WABA, not merely whether an arbitrary phone id exists.
    after = None
    for _ in range(10):
        params = {'fields': 'id,display_phone_number', 'limit': 100}
        if after:
            params['after'] = after
        response = graph('GET', waba+'/phone_numbers', token, params=params)
        for asset in response.get('data') or []:
            if str(asset.get('id')) == pid:
                phone = normalize_phone_digits(asset.get('display_phone_number'))
                if not phone or phone != row['requested_phone']:
                    raise ValueError('requested_number_mismatch')
                return {'status': 'ok', 'display_phone_number': phone}
        after = ((response.get('paging') or {}).get('cursors') or {}).get('after')
        if not (response.get('paging') or {}).get('next') or not after:
            break
    raise ValueError('asset_not_in_waba')


def outbound(bid):
    bid = int(bid)
    with binding_lock():
        workflow._eligible(bid)
        row, cfg = workflow.get(bid), repo.get_whatsapp_config(bid) or {}
        if (not row or row['state'] != 'Processing' or not row['inbound_at']
                or row['mapping_fingerprint'] != workflow.fingerprint(cfg)):
            raise ValueError('inbound_test_required')
        at = datetime.fromisoformat(row['inbound_at'])
        if at < datetime.now(timezone.utc)-timedelta(hours=23):
            raise ValueError('test_window_expired')
        if row['outbound_state']:
            return {'status': 'ok', 'delivery': row['outbound_state']}
        token = _token(bid, cfg.get('credentials_reference'))
        owner = normalize_phone_digits(repo.get_business(bid).get('trusted_owner_phone'))
        if not owner:
            raise ValueError('owner_phone_required')
        db.execute("UPDATE kw_assist_connections SET outbound_state='sending',updated_at=? WHERE business_id=?", (workflow.now(), bid))
        mapping = row['mapping_fingerprint']
    # Commit sending before network. Unknown delivery is never automatically retried.
    try:
        data = graph('POST', cfg['phone_number_id']+'/messages', token, json={
            'messaging_product':'whatsapp', 'to':owner, 'type':'text',
            'text':{'body':'Uji koneksi Kilas Assist berhasil. Pesan ini dikirim dari nomor bisnis Anda.'}})
        message_id = (data.get('messages') or [{}])[0].get('id')
        if not message_id:
            raise ValueError('delivery_unknown')
    except Exception:
        with binding_lock():
            db.execute("UPDATE kw_assist_connections SET outbound_state='unknown',last_error='delivery_unknown' WHERE business_id=? AND mapping_fingerprint=?", (bid,mapping))
        raise ValueError('delivery_unknown') from None
    with binding_lock():
        receipt = db.query_one('''SELECT * FROM kw_assist_connection_deliveries
            WHERE provider_id=? AND business_id=? AND mapping_fingerprint=?''', (message_id,bid,mapping))
        state = 'delivered' if receipt else 'sent'
        db.execute('''UPDATE kw_assist_connections SET outbound_event_id=?,outbound_state=?,outbound_at=?,updated_at=?
            WHERE business_id=? AND mapping_fingerprint=? AND outbound_state='sending' ''',
            (message_id, state, receipt['received_at'] if receipt else None, workflow.now(),bid,mapping))
    return {'status':'ok','delivery':state}
