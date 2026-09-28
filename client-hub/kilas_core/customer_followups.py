"""Human-reviewed Customer Detail follow-up through authoritative WhatsApp transports."""
import hashlib
import re
import time
from datetime import datetime, timezone

import assist_demo
import db
import inbox_service
import platform_inbox_service
import platform_workspace
import wa_inbox_shared
import wa_takeover_service
from public_chat import store
from kilas_core import customers, customer_insights
from kilas_core.adapters import whatsapp
from kilas_core import whatsapp_access, whatsapp_transport


class FollowUpError(ValueError):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status = code, status


def _core_target(business_id, customer_id):
    for conversation in customer_insights.whatsapp_conversation_rows(business_id, customer_id):
        with store.transaction() as tx:
            link = whatsapp.binding(tx, business_id, conversation['id'])
        if link:
            return {
                'source': 'core',
                'conversation_id': conversation['id'],
                'phone': link['customer_phone'],
                'last_inbound_at': int(link.get('last_inbound_at') or 0),
            }
    return None


def _demo_target(business_id, customer):
    phone = platform_inbox_service.normalize_customer_phone(customer.get('phone'))
    bound = assist_demo.binding(business_id, phone) if phone else None
    if (not bound or not bound.get('active')
            or int(bound.get('expires_at') or 0) <= int(time.time())):
        return None
    # Scoped rows prove the association. A matching phone string alone is insufficient.
    if not assist_demo.rows(business_id, phone, limit=1):
        return None
    return {
        'source': 'demo',
        'conversation_id': 'demo:' + bound['id'],
        'phone': phone,
        'session_id': bound['id'],
    }


def _platform_target(business_id, customer):
    if not platform_workspace.is_scope_business(business_id):
        return None
    conversation = customer_insights.platform_conversation_row(business_id, customer)
    if not conversation:
        return None
    return {
        'source': 'platform',
        'conversation_id': conversation['id'],
        'phone': conversation['phone'],
    }


def _legacy_target(business_id, customer):
    # Core remains authoritative when selected. Never fall back to an old sender merely because
    # a historical row has the same phone number.
    if whatsapp_access.selected(business_id):
        return None
    phone = inbox_service.normalize_customer_phone(customer.get('phone'))
    if not phone or not inbox_service.customer_exists(business_id, phone):
        return None
    return {
        'source': 'legacy',
        'conversation_id': 'legacy:' + phone,
        'phone': phone,
    }


def _target(business, customer):
    business_id = business['id']
    return (_core_target(business_id, customer['id'])
            or _demo_target(business_id, customer)
            or _platform_target(business_id, customer)
            or _legacy_target(business_id, customer))


def _operation_key(business_id, customer_id, conversation_id, insight):
    meta = insight.get('_meta') or {}
    source = ':'.join((str(business_id), customer_id, conversation_id,
                       str(meta.get('updated_at') or 0), str(insight.get('follow_up') or '')))
    return 'followup-' + hashlib.sha256(source.encode()).hexdigest()[:32]


def _window_and_template(business_id, target):
    source = target['source']
    if source == 'core':
        last = target.get('last_inbound_at') or 0
        window = wa_inbox_shared.compute_freeform_window_status(
            datetime.fromtimestamp(last, timezone.utc) if last else None)
        template = inbox_service.template_readiness(business_id) if not window['allowed'] else None
    elif source in ('demo', 'platform'):
        window = platform_inbox_service.freeform_window_status(target['phone'])
        template = platform_inbox_service.template_readiness() if not window['allowed'] else None
    else:
        window = inbox_service.freeform_window_status(business_id, target['phone'])
        template = inbox_service.template_readiness(business_id) if not window['allowed'] else None
    return window, template


def context(business, customer, insight):
    if not insight.get('follow_up') or not (insight.get('_meta') or {}).get('has_history'):
        return None
    target = _target(business, customer)
    if not target:
        return None
    window, template = _window_and_template(business['id'], target)
    return dict(target,
                operation_key=_operation_key(
                    business['id'], customer['id'], target['conversation_id'], insight),
                window=window, template=template)


def _name(customer):
    name = str(customer.get('display_name') or '').strip()
    phone = str(customer.get('phone') or '').strip()
    if not name or name == phone or name.lower().startswith('pengunjung '):
        return 'Kak'
    return name


def _payment_amount(insight):
    evidence = ' '.join(str(insight.get(key) or '') for key in
                        ('_payment_evidence', '_action_evidence', 'buying_signal_reason', 'action'))
    if not re.search(r'bayar|pembayaran|invoice|tagihan|transfer|dp|pelunasan', evidence, re.I):
        return None
    match = re.search(r'\bRp\s*[0-9][0-9.,]*(?:\s*(?:juta|ribu|jt|rb))?\b', evidence, re.I)
    if match:
        return re.sub(r'^rp\s*', 'Rp', match.group(0), flags=re.I)
    match = re.search(r'\b[0-9][0-9.,]*\s*(?:juta|ribu|jt|rb)\b', evidence, re.I)
    return 'Rp' + match.group(0) if match else ''


def draft(customer, insight):
    """Deterministic editable draft grounded only in fields already present in Insight."""
    greeting = 'Halo ' + _name(customer) + ','
    amount = _payment_amount(insight)
    if amount is not None:
        subject = 'pembayaran' + ((' ' + amount) if amount else '')
        return (f'{greeting} terkait {subject} yang tadi dibahas, apakah ada detail pembayaran '
                'atau invoice yang masih perlu saya bantu?')
    topic = (str(insight.get('action') or '').strip()
             or next((str(item).strip() for item in insight.get('needs') or [] if str(item).strip()), '')
             or next((str(item).strip() for item in insight.get('interests') or [] if str(item).strip()), ''))
    if topic:
        topic = topic[0].lower() + topic[1:]
        return f'{greeting} terkait {topic} yang tadi dibahas, apakah ada detail lain yang masih perlu saya bantu?'
    return f'{greeting} apakah ada informasi dari percakapan tadi yang masih perlu saya bantu?'


def _claim_legacy_attempt(target, operation_key, message, use_template):
    payload_hash = hashlib.sha256(
        (target['source'] + ':' + str(bool(use_template)) + ':' + message).encode()).hexdigest()
    existing = db.query_one('SELECT * FROM platform_workspace_outbound WHERE event_id=?',
                            (operation_key,))
    if existing:
        if existing['customer_phone'] != target['phone'] or existing['payload_hash'] != payload_hash:
            raise FollowUpError('event_conflict')
        return existing
    try:
        db.execute('INSERT INTO platform_workspace_outbound'
                   '(event_id,customer_phone,payload_hash,status,created_at) VALUES (?,?,?,?,?)',
                   (operation_key, target['phone'], payload_hash, 'attempting', int(time.time())))
    except Exception:
        existing = db.query_one('SELECT * FROM platform_workspace_outbound WHERE event_id=?',
                                (operation_key,))
        if existing and existing['customer_phone'] == target['phone'] and existing['payload_hash'] == payload_hash:
            return existing
        raise FollowUpError('delivery_unknown')
    return None


def _legacy_delivery(business_id, target, operation_key, message, actor_id, use_template):
    existing = _claim_legacy_attempt(target, operation_key, message, use_template)
    if existing:
        status = existing['status']
        if status == 'accepted':
            return {'status': status}
        raise FollowUpError('delivery_unknown' if status in ('attempting', 'unknown') else 'whatsapp_' + status)

    source, phone = target['source'], target['phone']
    try:
        if source in ('demo', 'platform'):
            platform_inbox_service.start_human_takeover(phone, actor_id)
            scope = ({'business_id': business_id, 'session_id': target['session_id']}
                     if source == 'demo' else None)
            if use_template:
                ok, reason = platform_inbox_service.send_template_reply(phone, demo_scope=scope)
            else:
                ok, reason = platform_inbox_service.send_manual_reply(phone, message, demo_scope=scope)
        else:
            wa_takeover_service.start_human_takeover(business_id, phone, actor_id)
            if use_template:
                ok, reason = inbox_service.send_template_reply(business_id, phone)
            else:
                ok, reason = inbox_service.send_manual_reply(business_id, phone, message)
    except Exception:
        ok, reason = False, 'delivery_unknown'

    uncertain = {'delivery_unknown', 'transport_uncertain', 'meta_request_failed',
                 'bot_internal_bridge_timeout', 'bot_internal_bridge_network_error',
                 'bot_internal_bridge_bad_response', 'sent_history_write_failed'}
    if ok and reason != 'sent_history_write_failed':
        status, error = 'accepted', None
    elif reason in ('outside_24h_window', 'no_customer_inbound'):
        status, error = 'suppressed', reason
    elif reason in uncertain:
        status, error = 'unknown', reason
    else:
        status, error = 'failed', str(reason or 'send_failed')[:160]
    try:
        db.execute('UPDATE platform_workspace_outbound SET status=?,error=? WHERE event_id=?',
                   (status, error, operation_key))
    except Exception:
        status, error = 'unknown', 'ledger_update_failed'
    if status != 'accepted':
        raise FollowUpError('delivery_unknown' if status == 'unknown' else 'whatsapp_' + status)
    return {'status': status}


def send(business, customer_id, text, operation_key, actor_id):
    customer = customers.get_customer(business['id'], customer_id)
    if customer.get('stage') not in customers.STAGES:
        raise FollowUpError('invalid_customer', 400)
    insight = customer_insights.cached(business, customer)
    target = context(business, customer, insight)
    if not target:
        raise FollowUpError('whatsapp_conversation_required')
    if operation_key != target['operation_key']:
        raise FollowUpError('followup_draft_changed')

    message = (text or '').strip()
    if not message or len(message) > 4000:
        raise FollowUpError('invalid_message', 400)

    use_template = not target['window']['allowed']
    if use_template and not (target['template'] or {}).get('ready'):
        raise FollowUpError('approved_template_required')

    if target['source'] == 'core':
        whatsapp.mode(business['id'], target['conversation_id'], 'HUMAN_TAKEOVER', actor_id)
        try:
            result = whatsapp_transport.manual(
                business['id'], target['conversation_id'], operation_key,
                '' if use_template else message, actor_id, template=use_template)
        except store.ChatError as error:
            raise FollowUpError(error.code, error.status) from error
    else:
        result = _legacy_delivery(
            business['id'], target, operation_key, message, actor_id, use_template)
    return dict(result, conversation_id=target['conversation_id'],
                source=target['source'], template=use_template)
