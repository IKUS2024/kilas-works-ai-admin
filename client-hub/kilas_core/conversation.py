"""Shared channel-neutral business orchestration. Model IO occurs before the fenced transaction."""
import os
import logging
import time
import ai_onboarding
import ai_usage
import repo
from kilas_core import actions, customers, jobs, service, understanding, operation_access, playbooks
from kilas_core.contracts import HistoryMessage
from kilas_core.playbook_definitions import select
from public_chat import store, security


log = logging.getLogger(__name__)
_JOB_CODES = frozenset({'stale_version', 'invalid_fields', 'invalid_text', 'fields_too_large',
    'invalid_kind', 'invalid_scope', 'invalid_operation', 'invalid_channel', 'not_found',
    'operation_conflict', 'invalid_status', 'invalid_transition'})


def _diagnostic(bid, stage, code):
    # Values are closed code-owned enums; no exception repr, prompt, output, text or secrets.
    safe = code if code in understanding.UnderstandingError.CODES | _JOB_CODES else 'other'
    log.warning('core_interpretation business_id=%d stage=%s code=%s', bid, stage, safe)


def _handover_invalid(bid, cid, event, eligible, fence):
    if not eligible(bid):
        return store.finish(event, error='provider_error')
    with store.transaction() as tx:
        jobs._lock(tx, bid)
        if not (operation_access.enabled() and operation_access.eligible(tx, bid)):
            return store._finish(tx, event, error='invalid_provider_result')
        def handover(transaction):
            if fence is not None and not fence(transaction):
                return None
            from kilas_core.handover import request_human
            request_human(transaction, bid, cid, 'UNSUPPORTED')
            return None
        return store._finish(tx, event, before_reply=handover)


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
        # A greeting is not a business request and must never manufacture a Job or trigger
        # Human Takeover just because the extraction model labels it HUMAN/UNSUPPORTED.
        # Keep this deterministic and narrowly scoped to whole-message greetings only.
        if understanding.is_simple_greeting(message.text):
            return store.finish(event, reply='Halo! Ada yang bisa saya bantu hari ini?')
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

        repair_code = None
        stop_reason = None

        def provider(inbound, scoped_history):
            nonlocal stop_reason
            with ai_usage.scope(bid, 'tenant_customer'):
                raw, stop_reason, error = ai_onboarding._call_claude(prompt + (
                    '\nKeluaran sebelumnya ditolak (' + repair_code + '). Ekstrak ulang dari pesan terakhir; '
                    'jangan menebak atau menyalin keluaran sebelumnya. Patuhi semua tipe, intent, allowed_fields '
                    'dan kutipan persis. Jika tidak dapat dipahami dengan aman, gunakan UNSUPPORTED '
                    'dengan fields={}, evidence={}, corrections=[], ambiguous=[].' if repair_code else ''),
                    [{'role': row.role, 'content': row.content} for row in scoped_history]
                    + [{'role':'user', 'content':inbound.text}], max_tokens=1200,
                    model=ai_onboarding.CLIENT_HUB_SIMULATION_MODEL)
            return raw, error

        for attempt in range(2):
            result = service.process_message(message,
                history=tuple(HistoryMessage('assistant' if r['role']=='human' else r['role'], r['content']) for r in history),
                reply_provider=provider)
            if result.error:
                _diagnostic(bid, 'provider_contract' if result.error == 'invalid_provider_result' else 'provider', 'other')
                return store.finish(event, error=result.error)
            try:
                if stop_reason == 'max_tokens':
                    raise understanding.UnderstandingError('truncated_output')
                interpretation = understanding.parse(result.reply, message.text)
                # Validate workflow before any write; action boundary revalidates after fencing.
                playbooks.decide(book, interpretation, known=known, uncertain=uncertain,
                    current_status=expected['job']['status'] if expected['job'] else None,
                    has_job=bool(expected['job']))
                break
            except understanding.UnderstandingError as error:
                _diagnostic(bid, 'understanding', error.code)
                if attempt or not eligible(bid) or event['lease_until'] - time.time() <= 46:
                    raise
                current = store.conversation(bid, cid)
                if current['mode'] != 'AI_ACTIVE' or current['version'] != event['version']:
                    return store.finish(event)
                # At most one new extraction; never accept or persist rejected facts.
                repair_code = error.code
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
        _diagnostic(bid, 'job', error.code)
        if error.code == 'stale_version':
            return store.finish(event, reply='Tim baru memperbarui rincian permintaan. Mohon konfirmasi perubahan yang masih dibutuhkan agar tidak tertimpa.')
        return store.finish(event, error='invalid_provider_result')
    except understanding.UnderstandingError as error:
        _diagnostic(bid, 'handover', error.code)
        try:
            return _handover_invalid(bid, cid, event, eligible, fence)
        except Exception:
            _diagnostic(bid, 'handover_failed', 'other')
            return store.finish(event, error='provider_error')
    except Exception:
        _diagnostic(bid, 'core', 'other')
        # Rollback first; never expose model output, internal errors, or fake success.
        return store.finish(event, error='provider_error')
