"""Owner-only native Live allowance. No supplier invoice/balance claims.

One conservative, operator-approved lease estimate is retained after ANY dispatch.
The ledger contains no key, audio or transcript. This does not extend ElevenLabs,
Voice Over, Learning or customer plan allowances. No IO merely on import.
"""
import hashlib
import os
import re
import secrets
from datetime import datetime, timezone, timedelta
from . import audio_transcription_budget as ledger, usage
from .autonomous_store import transaction

MODEL = 'gemini-3.5-live-translate-preview'
PRICE_VERSION = 'gemini-live-translate-approved-90s-envelope-v1'
LEASE_MS = 90000  # Less than the existing ledger's 120s stale-operation fence.


def policy():
    try:
        if os.environ.get('KILAS_LIVE_GEMINI_ENABLED', '').lower() not in ('true', '1', 'on'):
            return None
        if os.environ.get('KILAS_LIVE_GEMINI_BILLING_VERIFIED') != 'yes':
            return None
        campaign = os.environ['KILAS_LIVE_GEMINI_CAMPAIGN']
        owner = int(os.environ['KILAS_LIVE_GEMINI_ALLOWED_OWNER_ID'])
        cap = int(os.environ['KILAS_LIVE_GEMINI_BUDGET_MICRO_USD'])
        reserve = int(os.environ['KILAS_LIVE_GEMINI_LEASE_RESERVE_MICRO_USD'])
        mode = os.environ.get('KILAS_LIVE_GEMINI_POLICY', 'qa')
        if mode == 'owner_lifetime':
            # Operator must verify a tax/fee-inclusive USD->IDR upper bound.
            # Never infer one from a claimed balance or a market spot quote.
            if os.environ.get('KILAS_LIVE_GEMINI_IDR_CEILING_VERIFIED') != 'yes':
                return None
            ceiling = int(os.environ['KILAS_LIVE_GEMINI_IDR_PER_USD_CEILING'])
            approved_idr = int(os.environ['KILAS_LIVE_GEMINI_TOTAL_IDR'])
            if not 0 < approved_idr <= 500000 or ceiling <= 0 or cap*ceiling > approved_idr*1000000:
                return None
            # Stable TEXT value in the existing immutable policy ledger. This
            # is a lifetime cap, not an artificial distant date or auto-renewal.
            expiry_text = 'owner-lifetime-v1'
        elif mode == 'qa':
            expiry = datetime.fromisoformat(os.environ['KILAS_LIVE_GEMINI_EXPIRES_AT'].replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            if expiry.tzinfo is None or not now < expiry <= now + timedelta(days=31):
                return None
            expiry_text = expiry.astimezone(timezone.utc).isoformat()
        else:
            return None
        if (not re.fullmatch(r'[A-Za-z0-9_-]{1,70}', campaign) or not 0 < owner <= 10**9
                or not 1 <= reserve <= cap <= 10**9
                or (mode == 'owner_lifetime' and reserve < 100000)):
            return None
        return {'id':'gml-'+campaign, 'allowed_owner':owner, 'global_micro':cap,
                'account_micro':cap, 'reserve':reserve,
                'expires_at':expiry_text, 'price_version':PRICE_VERSION, 'mode':mode}
    except (ValueError, KeyError, TypeError, OverflowError):
        return None


def ready(owner):
    config = policy()
    return bool(config and config['allowed_owner'] == owner)


def claim(owner, ident, key):
    config = policy()
    if not config or config['allowed_owner'] != owner:
        raise ledger.BudgetError('gemini_unavailable', 404)
    if not re.fullmatch(r'live-[a-f0-9]{32}', key):
        raise ledger.BudgetError('invalid_operation', 400)
    operation = key+'-gm'
    with transaction() as conn:
        ledger._campaign(conn, config)
        ledger._owner(conn, owner)
        ledger._expire(conn, owner=owner)
        if ledger._row(conn, owner, operation):
            raise ledger.BudgetError('duplicate_turn', 409)
        # Share paid-STT concurrency/rate fences, without sharing its funding.
        if usage._query(conn, "SELECT 1 FROM kilas_vo_stt_operations WHERE user_id=? AND status IN ('RESERVED','DISPATCHED')", (owner,), one=True):
            raise ledger.BudgetError('already_processing', 429)
        if usage._query(conn, "SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE status IN ('RESERVED','DISPATCHED')", one=True)[0] >= ledger.GLOBAL_CONCURRENCY:
            raise ledger.BudgetError('service_busy', 429)
        now = datetime.now(timezone.utc)
        for seconds, maximum in ((3600, ledger.OWNER_HOURLY_ATTEMPTS), (86400, ledger.OWNER_DAILY_ATTEMPTS)):
            if usage._query(conn, 'SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key LIKE ? AND created_at>=?',
                            (owner, 'live-%', (now-timedelta(seconds=seconds)).isoformat()), one=True)[0] >= maximum:
                raise ledger.BudgetError('attempt_limit', 429)
        if config['mode'] == 'owner_lifetime':
            # Same advisory lock as all admissions. Campaign rotation, earlier
            # QA, failures and unknown outcomes cannot reset the total budget.
            spent = usage._query(conn, 'SELECT COALESCE(SUM(charge_micro),0) FROM kilas_vo_stt_operations WHERE campaign LIKE ?', ('gml-%',), one=True)[0]
        else:
            spent = usage._query(conn, 'SELECT COALESCE(SUM(charge_micro),0) FROM kilas_vo_stt_operations WHERE campaign=?', (config['id'],), one=True)[0]
        if spent + config['reserve'] > config['global_micro']:
            raise ledger.BudgetError('budget_limit', 429)
        lease = secrets.token_hex(32)
        usage._query(conn, "INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at) VALUES (?,?,?,?,'RESERVED',?,?,?,?)",
                     (owner, operation, config['id'], hashlib.sha256((ident+':'+key).encode()).hexdigest(),
                      config['reserve'], LEASE_MS, ledger._hash(lease), now.isoformat()))
        return ledger.Reservation(owner, operation, lease)


def dispatch(capability):
    if type(capability) is not ledger.Reservation:
        raise ledger.BudgetError('invalid_reservation')
    config = policy()
    if not config or config['allowed_owner'] != capability.owner:
        raise ledger.BudgetError('gemini_unavailable', 404)
    with transaction() as conn:
        ledger._campaign(conn, config)  # Recheck campaign block/config before dispatch.
        row = ledger._lock_existing_campaign(conn, capability.owner, capability.key)
        ledger._owner(conn, capability.owner)
        if (not row or row[1] != config['id'] or row[3] != 'RESERVED'
                or row[4] != config['reserve'] or row[5] != ledger._hash(capability.lease)
                or row[6] != LEASE_MS):
            raise ledger.BudgetError('invalid_reservation')
        usage._query(conn, "UPDATE kilas_vo_stt_operations SET status='DISPATCHED',dispatched_at=? WHERE id=?",
                     (datetime.now(timezone.utc).isoformat(), row[0]))


def finish(capability, success):
    # Settlement remains possible after expiry, flag-off, End or policy edits.
    with transaction() as conn:
        row = ledger._lock_existing_campaign(conn, capability.owner, capability.key)
        ledger._owner(conn, capability.owner, settlement=True)
        if not row or row[5] != ledger._hash(capability.lease):
            raise ledger.BudgetError('invalid_reservation')
        if row[3] not in ('RESERVED', 'DISPATCHED'):
            return False
        dispatched = row[3] == 'DISPATCHED'
        status = 'COMPLETED' if success and dispatched else 'UNKNOWN' if dispatched else 'CANCELLED'
        usage._query(conn, 'UPDATE kilas_vo_stt_operations SET status=?,charge_micro=?,finished_at=? WHERE id=?',
                     (status, row[4] if dispatched else 0, datetime.now(timezone.utc).isoformat(), row[0]))
        return success and dispatched
