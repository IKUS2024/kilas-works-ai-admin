"""Shared channel-neutral business orchestration. Model IO occurs before the fenced transaction."""
import os
import ai_onboarding
import ai_usage
import repo
from kilas_core import actions, customers, jobs, service, understanding, operation_access
from kilas_core.contracts import HistoryMessage
from kilas_core.playbook_definitions import select
from public_chat import store, security


def enabled():
    return (os.environ.get('KILAS_PLAYBOOKS_V2_ENABLED', '').lower() == 'true'
            and customers.enabled() and jobs.enabled())


def _eligible(bid):
    business = repo.get_business(bid)
    channel = store.channel(bid=bid)
    return bool(enabled() and security.available(business) and channel and channel['enabled'])


def process(business, message, event, history, *, eligibility=None, fence=None):
    eligible = eligibility or _eligible
    bid, cid = business['id'], message.conversation_id
    try:
        if not eligible(bid):
            return store.finish(event, error='provider_error')
        book = select((repo.get_business_profile(bid) or {}).get('category'))
        with jobs.transaction() as tx:
            expected = actions.snapshot(tx, bid, cid)
        resolved = actions.state(book, expected)
        if resolved is None:
            return store.finish(event, reply='Permintaan ini perlu ditinjau tim agar tidak tercatat sebagai pekerjaan ganda.')
        known, uncertain = resolved
        settings = repo.get_ai_settings(bid) or {}
        customer = customers.get_customer(bid, expected['customer_id'])
        context = {'business_name': business['business_name'], 'customer_name': customer['display_name'],
                   'knowledge': settings.get('normalized_config') or {}, 'uncertain': uncertain}
        prompt = understanding.prompt(book, known, context)

        def provider(inbound, scoped_history):
            with ai_usage.scope(bid, 'tenant_customer'):
                raw, _, error = ai_onboarding._call_claude(prompt,
                    [{'role': row.role, 'content': row.content} for row in scoped_history]
                    + [{'role':'user', 'content':inbound.text}], max_tokens=1200,
                    model=ai_onboarding.CLIENT_HUB_SIMULATION_MODEL)
            return raw, error

        result = service.process_message(message,
            history=tuple(HistoryMessage('assistant' if r['role']=='human' else r['role'], r['content']) for r in history),
            reply_provider=provider)
        if result.error:
            return store.finish(event, error=result.error)
        interpretation = understanding.parse(result.reply, message.text)
        if not eligible(bid):
            return store.finish(event, error='provider_error')
        with store.transaction() as tx:
            # Fixed lock order. Phase 4 manual edits also lock the business first.
            jobs._lock(tx, bid)
            def commit_action(transaction):
                if fence is not None and not fence(transaction):
                    return None
                operations = operation_access.enabled() and operation_access.eligible(transaction,bid)
                if operations and interpretation.intent in ('HUMAN','UNSUPPORTED'):
                    from kilas_core.handover import request_human
                    request_human(transaction,bid,cid,interpretation.intent)
                    return None
                row, reply = actions.apply(transaction,bid,cid,expected=expected,book=book,
                                         interpretation=interpretation,event_id=message.external_message_id,channel=message.channel)
                if operations and row:
                    from kilas_core.handover import observe_uncertainty
                    observe_uncertainty(transaction,row)
                return reply
            return store._finish(tx,event,before_reply=commit_action)
    except jobs.JobError as error:
        if error.code == 'stale_version':
            return store.finish(event, reply='Tim baru memperbarui rincian permintaan. Mohon konfirmasi perubahan yang masih dibutuhkan agar tidak tertimpa.')
        return store.finish(event, error='invalid_provider_result')
    except understanding.UnderstandingError:
        return store.finish(event, error='invalid_provider_result')
    except Exception:
        # Rollback first; never expose model output, internal errors, or fake success.
        return store.finish(event, error='provider_error')
