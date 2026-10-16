"""Read-only native Start gates for worker diagnostics; never an admission grant."""
from . import audio_store, live_gemini as native, live_gemini_budget as budget
from . import live_translator as live, live_translator_store as sessions, routes, usage


SAFE_REASONS = frozenset({
    'gemini_unavailable', 'campaign_blocked', 'campaign_policy_changed',
    'already_processing', 'budget_limit', 'live_audio_limit',
    'zero_balance', 'insufficient_balance',
})


def report(owner=None):
    """Inspect configuration and existing rows without cleanup or paid IO.

    This instant snapshot cannot reserve a future Start. Real admission still
    checks its original identity, policy, balance and concurrency fences.
    """
    result = {'owner_id': None, 'user_id': None, 'audience': None,
              'start_eligible': False, 'reason': 'policy_unavailable'}
    try:
        config = budget.policy()
        if not config:
            return result
        funding_owner = config['allowed_owner']
        if type(funding_owner) is not int or funding_owner <= 0:
            return result
        owner = funding_owner if owner is None else owner
        audience = config.get('audience', 'owner')
        result.update(owner_id=funding_owner, audience=audience)
        if type(owner) is not int or owner <= 0 or not budget.allowed(owner, config):
            result['reason'] = 'user_unavailable'
            return result
        result['user_id'] = owner
        if not routes.enabled():
            result['reason'] = 'app_unavailable'
            return result
        if owner == funding_owner and not native.preview_owner(owner):
            result['reason'] = 'owner_unverified'
            return result
        if not native.ready(owner):
            result['reason'] = 'gemini_unavailable'
            return result
        allowance = budget.status(owner, streams=2)
        result.update(input_mode='gemini-live-two-way-v1', streams=2)
        for name in ('remaining_micro_usd', 'remaining_leases', 'reserve_micro_usd'):
            value = allowance.get(name)
            if type(value) is int and value >= 0:
                result[name] = value
        valuation = allowance.get('valuation_mode')
        if valuation in ('conservative_internal', 'verified_ceiling'):
            result['valuation_mode'] = valuation
        if not allowance.get('available'):
            reason = allowance.get('reason')
            result['reason'] = reason if reason in SAFE_REASONS else 'budget_unavailable'
            return result
        if sessions.active(owner):
            result['reason'] = 'session_busy'
            return result
        conn = usage._connect()
        try:
            # balance()/require_balance() expire stranded jobs and therefore
            # cannot be used by this strictly observational report.
            row = usage._query(conn, 'SELECT seconds FROM kilas_audio_balances WHERE user_id=?',
                               (owner,), one=True)
            seconds = int(row[0]) if row else 0
            reserved, active_jobs = usage._query(conn,
                "SELECT COALESCE(SUM(reserved_seconds),0),COUNT(*) FROM kilas_audio_jobs "
                "WHERE user_id=? AND status IN ('QUEUED','PROCESSING')", (owner,), one=True)
            exempt = bool(usage._qa_quota_exempt(conn, owner, usage._now()))
        finally:
            conn.close()
        result['audio_exempt'] = exempt
        if active_jobs:
            result['reason'] = 'audio_busy'
            return result
        available = max(0, seconds-int(reserved))
        if not exempt and available < 90:
            result['reason'] = 'zero_balance' if not available else 'insufficient_balance'
            return result
        live.require_audio_allowance(owner, 90)  # Existing SELECT-only safety allowance.
        result.update(start_eligible=True, reason='ready')
        return result
    except audio_store.AudioError as error:
        result['reason'] = error.code if error.code in SAFE_REASONS else 'readiness_error'
    except Exception:
        # Never crash a worker or emit database/provider exceptions or secrets.
        result['reason'] = 'readiness_error'
    return result


def audience_report(owner_report=None):
    """Report one existing nonowner account without creating or acting as it."""
    result = {'audience': None, 'owner': owner_report, 'nonowner': None,
              'nonowner_reason': 'policy_unavailable'}
    try:
        config = budget.policy()
        if not config:
            return result
        result['audience'] = config.get('audience', 'owner')
        if result['owner'] is None:
            result['owner'] = report()
        if result['audience'] != 'authenticated':
            result['nonowner_reason'] = 'owner_only'
            return result
        conn = usage._connect()
        try:
            # Prefer an existing customer account; every existing role remains
            # governed by the native authenticated-audience policy itself.
            row = usage._query(conn,
                "SELECT id FROM users WHERE id<>? "
                "ORDER BY CASE WHEN role='CLIENT_OWNER' THEN 0 ELSE 1 END,id LIMIT 1",
                (config['allowed_owner'],), one=True)
        finally:
            conn.close()
        if not row:
            result['nonowner_reason'] = 'no_existing_nonowner'
            return result
        result['nonowner'] = report(row[0])
        result['nonowner_reason'] = result['nonowner']['reason']
    except Exception:
        result['nonowner_reason'] = 'readiness_error'
    return result
