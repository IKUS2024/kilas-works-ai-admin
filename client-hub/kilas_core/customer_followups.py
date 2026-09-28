"""Human-reviewed Customer Detail follow-up through the existing Core WhatsApp transport."""
import hashlib
from datetime import datetime, timezone

import inbox_service
import wa_inbox_shared
from public_chat import store
from kilas_core import customers, customer_insights
from kilas_core.adapters import whatsapp
from kilas_core import whatsapp_transport


class FollowUpError(ValueError):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status = code, status


def _conversation(business_id, customer_id):
    rows = customer_insights.whatsapp_conversation_rows(business_id, customer_id)
    return rows[0] if rows else None


def _operation_key(business_id, customer_id, conversation_id, insight):
    meta = insight.get('_meta') or {}
    source = ':'.join((str(business_id), customer_id, conversation_id,
                       str(meta.get('updated_at') or 0), str(insight.get('follow_up') or '')))
    return 'followup-' + hashlib.sha256(source.encode()).hexdigest()[:32]


def context(business, customer, insight):
    if not insight.get('follow_up') or not (insight.get('_meta') or {}).get('has_history'):
        return None
    conversation = _conversation(business['id'], customer['id'])
    if not conversation:
        return None
    with store.transaction() as tx:
        link = whatsapp.binding(tx, business['id'], conversation['id'])
    if not link:
        return None
    last_inbound = int(link.get('last_inbound_at') or 0)
    window = wa_inbox_shared.compute_freeform_window_status(
        datetime.fromtimestamp(last_inbound, timezone.utc) if last_inbound else None)
    template = inbox_service.template_readiness(business['id']) if not window['allowed'] else None
    return {
        'conversation_id': conversation['id'],
        'operation_key': _operation_key(
            business['id'], customer['id'], conversation['id'], insight),
        'window': window,
        'template': template,
    }


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

    # The explicit owner send action is also the explicit takeover action. This keeps AI silent
    # after a human follow-up without adding a second messaging implementation.
    whatsapp.mode(business['id'], target['conversation_id'], 'HUMAN_TAKEOVER', actor_id)
    try:
        result = whatsapp_transport.manual(
            business['id'], target['conversation_id'], operation_key,
            '' if use_template else message, actor_id, template=use_template)
    except store.ChatError as error:
        raise FollowUpError(error.code, error.status) from error
    return dict(result, conversation_id=target['conversation_id'], template=use_template)
