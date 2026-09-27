"""Assisted registration. Mapping authority is tenant_whatsapp_config, never a phone string.

OTP is exchanged directly with the operator in Meta; it is never stored here. Signed Meta
webhooks supply test evidence. No UI or internal API can simply assert tests passed.
"""
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
import requests
import db
import repo
import assist_journey
from whatsapp_signup import binding_lock, normalize_phone_digits, _platform_bot_base_url

STATES = ('Pending', 'Processing', 'Waiting OTP', 'Connected', 'Error', 'Disconnected')


def now():
    return datetime.now(timezone.utc).isoformat()


def get(bid):
    return db.query_one('SELECT * FROM kw_assist_connections WHERE business_id=?', (bid,))


def fingerprint(cfg):
    return hashlib.sha256(('|'.join(str(cfg.get(k) or '') for k in
        ('business_id', 'waba_id', 'phone_number_id', 'credentials_reference'))).encode()).hexdigest()


def _admin(actor):
    if not actor or actor.get('role') != 'KILAS_ADMIN':
        raise PermissionError('admin_required')


def _eligible(bid):
    business = repo.get_business(bid)
    if not business or business.get('status') in ('ARCHIVED', 'SUSPENDED', 'CANCELLED'):
        raise ValueError('business_unavailable')
    import payment_service
    state = assist_journey.state(business)
    if not state['paid'] or not payment_service.has_verified_ai_admin_payment(bid):
        raise ValueError('verified_subscription_required')
    return business, state


def enqueue(bid, actor_id, requested_phone=None):
    # May run inside the existing verified-payment transaction. No nested transaction here.
    business, state = _eligible(bid)
    existing = get(bid)
    if existing:
        if not existing['requested_phone']:
            phone = normalize_phone_digits(requested_phone or (repo.get_business_profile(bid) or {}).get('business_phone'))
            if phone:
                db.execute('UPDATE kw_assist_connections SET requested_phone=? WHERE business_id=?', (phone,bid))
        return get(bid)
    phone = normalize_phone_digits(requested_phone or (repo.get_business_profile(bid) or {}).get('business_phone'))
    phone = phone or ''  # Payment verification must not fail because a profile needs completion.
    db.execute('''INSERT INTO kw_assist_connections(business_id,state,requested_phone,updated_at)
                  VALUES (?,'Pending',?,?) ON CONFLICT(business_id) DO NOTHING''', (bid, phone, now()))
    repo.write_audit(actor_id, bid, 'ASSIST_CONNECTION_REQUESTED', 'assisted registration')
    return get(bid)


def set_stage(bid, actor, stage):
    _admin(actor)
    with binding_lock():
        _eligible(bid)
        row = get(bid)
        if not row:
            row = enqueue(bid, actor['id'])
        allowed = {'Pending': ('Processing',), 'Processing': ('Waiting OTP',),
                   'Waiting OTP': ('Processing',), 'Error': ('Processing',),
                   'Disconnected': ('Processing',), 'Connected': ('Disconnected',)}
        if stage not in allowed.get(row['state'], ()):
            raise ValueError('invalid_connection_transition')
        db.execute('UPDATE kw_assist_connections SET state=?,operator_id=?,updated_at=? WHERE business_id=?',
                   (stage, actor['id'], now(), bid))
        if stage == 'Disconnected':
            db.execute("UPDATE tenant_whatsapp_config SET connection_status='NOT_CONNECTED' WHERE business_id=?", (bid,))
            db.execute('UPDATE businesses SET whatsapp_connected=? WHERE id=?', (False, bid))
        repo.write_audit(actor['id'], bid, 'ASSIST_CONNECTION_STAGE', stage)


def bridge(action, payload):
    base = _platform_bot_base_url()
    secret = os.environ.get('INTERNAL_SERVICE_SECRET', '').strip()
    if not base or not secret:
        raise ValueError('connection_bridge_unavailable')
    try:
        response = requests.post(base+'/internal/assist-connection/'+action, json=payload,
            headers={'X-Internal-Service-Secret': secret}, timeout=(3, 20), allow_redirects=False)
        data = response.json()
        if response.status_code != 200 or not isinstance(data, dict) or data.get('status') != 'ok':
            raise ValueError('connection_test_failed')
        return data
    except (requests.RequestException, TypeError):
        raise ValueError('connection_bridge_unavailable') from None
    except ValueError:
        raise ValueError('connection_test_failed') from None


def sync_mapping(bid, actor, waba_id, phone_number_id, credentials_reference=''):
    _admin(actor)
    if not all(re.fullmatch(r'[0-9]{1,32}', str(v or '')) for v in (waba_id, phone_number_id)):
        raise ValueError('invalid_mapping')
    # A reference, never a credential. The shared system token may manage multiple assigned assets.
    if credentials_reference not in ('', 'WHATSAPP_TOKEN__TENANT_'+str(bid)):
        raise ValueError('invalid_credential_reference')
    with binding_lock():
        _eligible(bid)
        row = get(bid)
        if not row or row['state'] not in ('Processing', 'Waiting OTP', 'Error'):
            raise ValueError('connection_not_processing')
        if repo.find_business_id_by_phone_number_id(phone_number_id, exclude_business_id=bid):
            raise ValueError('mapping_already_assigned')
        result = bridge('verify', dict(business_id=bid, waba_id=waba_id,
            phone_number_id=phone_number_id, credentials_reference=credentials_reference))
        display = normalize_phone_digits(result.get('display_phone_number'))
        if display != row['requested_phone']:
            raise ValueError('requested_number_mismatch')
        repo.upsert_whatsapp_config(bid, phone_number_id, waba_id, credentials_reference)
        cfg = repo.get_whatsapp_config(bid)
        db.execute('''UPDATE kw_assist_connections SET state='Processing',display_phone_number=?,
            mapping_fingerprint=?,version=version+1,challenge_hash=NULL,challenge_until=NULL,
            inbound_event_id=NULL,inbound_at=NULL,outbound_event_id=NULL,outbound_state=NULL,
            outbound_at=NULL,last_error=NULL,operator_id=?,updated_at=? WHERE business_id=?''',
            (display, fingerprint(cfg), actor['id'], now(), bid))
        db.execute('UPDATE tenant_whatsapp_config SET validated_at=NULL WHERE business_id=?', (bid,))
        db.execute('UPDATE businesses SET whatsapp_connected=? WHERE id=?', (False, bid))
        repo.write_audit(actor['id'], bid, 'ASSIST_MAPPING_SYNCED', 'Meta asset membership verified; tests required')


def start_inbound_test(bid, actor):
    _admin(actor)
    with binding_lock():
        business, state = _eligible(bid)
        row, cfg = get(bid), repo.get_whatsapp_config(bid) or {}
        if (not row or row['state'] != 'Processing' or not row['mapping_fingerprint']
                or row['mapping_fingerprint'] != fingerprint(cfg)):
            raise ValueError('mapping_sync_required')
        if not normalize_phone_digits(business.get('trusted_owner_phone')):
            raise ValueError('owner_phone_required')
        code = 'KILAS-TEST-'+secrets.token_hex(8).upper()
        db.execute('''UPDATE kw_assist_connections SET challenge_hash=?,challenge_until=?,
            inbound_event_id=NULL,inbound_at=NULL,outbound_event_id=NULL,outbound_state=NULL,
            outbound_at=NULL,updated_at=? WHERE business_id=?''',
            (hashlib.sha256(code.encode()).hexdigest(), (datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat(), now(), bid))
        repo.write_audit(actor['id'], bid, 'ASSIST_INBOUND_TEST_STARTED', None)
        return code


def observe(waba_id, phone_number_id, value):
    """Only call AFTER webhook signature verification. True consumes pending test-only traffic."""
    if not waba_id or not phone_number_id:
        return False
    with binding_lock():
        rows = db.query_all('''SELECT q.* FROM kw_assist_connections q
            JOIN tenant_whatsapp_config c ON c.business_id=q.business_id
            WHERE c.waba_id=? AND c.phone_number_id=? AND q.state <> 'Connected' ''',
            (str(waba_id), str(phone_number_id)))
        if len(rows) != 1:
            return False
        row = rows[0]
        bid = row['business_id']
        cfg = repo.get_whatsapp_config(bid) or {}
        if row['state'] != 'Processing' or row['mapping_fingerprint'] != fingerprint(cfg):
            return True
        owner = normalize_phone_digits((repo.get_business(bid) or {}).get('trusted_owner_phone'))
        for message in value.get('messages') or []:
            body = str((message.get('text') or {}).get('body') or '').strip()
            digest = hashlib.sha256(body.encode()).hexdigest()
            if (row['challenge_hash'] and row['challenge_until'] > now()
                    and message.get('type') == 'text' and message.get('id')
                    and normalize_phone_digits(message.get('from')) == owner
                    and hmac.compare_digest(digest, row['challenge_hash'])):
                db.execute('''UPDATE kw_assist_connections SET inbound_event_id=?,inbound_at=?,
                    challenge_hash=NULL,updated_at=? WHERE business_id=? AND inbound_event_id IS NULL''',
                    (str(message['id'])[:255], now(), now(), bid))
        for receipt in value.get('statuses') or []:
            if (receipt.get('status') not in ('delivered','read') or not receipt.get('id')
                    or normalize_phone_digits(receipt.get('recipient_id')) != owner):
                continue
            db.execute('''INSERT INTO kw_assist_connection_deliveries
                (provider_id,business_id,mapping_fingerprint,status,received_at) VALUES (?,?,?,?,?)
                ON CONFLICT(provider_id) DO NOTHING''',
                (str(receipt['id'])[:255], bid, row['mapping_fingerprint'], receipt['status'], now()))
            db.execute('''UPDATE kw_assist_connections SET outbound_state='delivered',outbound_at=?,updated_at=?
                WHERE business_id=? AND outbound_event_id=?''', (now(), now(), bid, receipt['id']))
        return True


def test_outbound(bid, actor):
    _admin(actor)
    # Remote endpoint owns the claim, sends from the stored mapping, and records the returned id.
    _eligible(bid)
    result = bridge('outbound', {'business_id': bid})
    repo.write_audit(actor['id'], bid, 'ASSIST_OUTBOUND_TEST_REQUESTED', result.get('delivery', 'pending'))
    return result


def activate(bid, actor):
    _admin(actor)
    import provisioning
    with binding_lock():
        business, state = _eligible(bid)
        row, cfg = get(bid), repo.get_whatsapp_config(bid) or {}
        if row and row['state'] == 'Connected' and state['connected']:
            return False
        if (not row or row['state'] != 'Processing' or not row['inbound_at']
                or not row['outbound_at'] or row['outbound_state'] != 'delivered'
                or row['mapping_fingerprint'] != fingerprint(cfg)):
            raise ValueError('both_tests_required')
        if not state['ready'] or not state['onboarding_complete']:
            raise ValueError('training_required')
        if repo.find_business_id_by_phone_number_id(cfg['phone_number_id'], exclude_business_id=bid):
            raise ValueError('mapping_already_assigned')
        if business['status'] != 'ACTIVE':
            repo.approve_business(bid, actor['id'])
        provisioning.provision_tenant(bid, actor)
        repo.mark_whatsapp_validated(bid)
        db.execute('UPDATE businesses SET whatsapp_phone_number_id=?,whatsapp_connected=? WHERE id=?', (cfg['phone_number_id'], True, bid))
        provisioning._activate_tenant_core(bid, actor)
        # Shared inbox tables are channel-neutral; no anonymous public channel is enabled here.
        db.execute("INSERT INTO kw_web_channels(business_id,slug) VALUES (?,?) ON CONFLICT(business_id) DO NOTHING",
                   (bid,'bisnis-'+secrets.token_hex(12)))
        db.execute("UPDATE kw_assist_connections SET state='Connected',operator_id=?,updated_at=? WHERE business_id=?", (actor['id'], now(), bid))
        repo.write_audit(actor['id'], bid, 'ASSIST_CONNECTION_ACTIVATED', 'Signed inbound and delivered outbound passed')
        return True
