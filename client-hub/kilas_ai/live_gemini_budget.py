"""Native Live allowance with an explicit audience. No invoice/balance claims.

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
# Leave at least 10s between a full physical lease and stale-row recovery.
# Checked against the durable admission timestamp, never a browser timestamp.
DISPATCH_MAX_AGE_SECONDS = 20
INTERNAL_GUARD_MAX_IDR = 250000
INTERNAL_VALUATION_MIN_IDR_PER_USD = 25000
INTERNAL_RESERVE_MIN_MICRO_USD = 250000
# Anti-abuse only: ordinary 59s input + bounded drain stays below 60/hour.
# This never adds funding, resets lifetime spend, or changes other STT limits.
OWNER_PHYSICAL_LEASES_PER_HOUR = 80


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
        audience = os.environ.get('KILAS_LIVE_GEMINI_AUDIENCE', 'owner')
        if audience not in ('owner', 'authenticated'):
            return None
        valuation = {}
        price_version = PRICE_VERSION
        if mode == 'owner_lifetime':
            approved_idr = int(os.environ['KILAS_LIVE_GEMINI_TOTAL_IDR'])
            if not 0 < approved_idr <= 500000:
                return None
            valuation_mode = os.environ.get('KILAS_LIVE_GEMINI_IDR_VALUATION_MODE', 'verified_ceiling')
            if valuation_mode == 'verified_ceiling':
                # A verified tax/fee-inclusive bound remains a separate path.
                # Neither a wallet balance nor a market quote verifies it.
                if os.environ.get('KILAS_LIVE_GEMINI_IDR_CEILING_VERIFIED') != 'yes':
                    return None
                ceiling = int(os.environ['KILAS_LIVE_GEMINI_IDR_PER_USD_CEILING'])
                guard_idr = approved_idr
            elif valuation_mode == 'conservative_internal':
                # Explicit internal accounting assumption, NOT actual FX,
                # supplier usage, an invoice ceiling or a prepaid hard stop.
                # All amounts need affirmative configuration; no spend defaults.
                if os.environ.get('KILAS_LIVE_GEMINI_INTERNAL_VALUATION_ACK') != 'yes':
                    return None
                ceiling = int(os.environ['KILAS_LIVE_GEMINI_IDR_PER_USD_INTERNAL'])
                guard_idr = int(os.environ['KILAS_LIVE_GEMINI_INTERNAL_GUARD_IDR'])
                if (ceiling < INTERNAL_VALUATION_MIN_IDR_PER_USD
                        or not 0 < guard_idr <= min(approved_idr, INTERNAL_GUARD_MAX_IDR)
                        or reserve < INTERNAL_RESERVE_MIN_MICRO_USD):
                    return None
                # Pin the acknowledged assumption in the immutable campaign
                # ledger too, so same-campaign edits fail closed at dispatch.
                price_version += '-internal-{}-{}-{}'.format(ceiling, guard_idr, approved_idr)
            else:
                return None
            if ceiling <= 0 or cap*ceiling > guard_idr*1000000:
                return None
            valuation = {'valuation_mode': valuation_mode, 'total_idr': approved_idr,
                         'guard_idr': guard_idr, 'idr_per_usd': ceiling}
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
                or (mode == 'owner_lifetime' and reserve < 100000)
                or (mode == 'owner_lifetime' and audience == 'authenticated'
                    and (reserve < INTERNAL_RESERVE_MIN_MICRO_USD or cap > 10000000))):
            return None
        return {'id':'gml-'+campaign, 'allowed_owner':owner, 'global_micro':cap,
                'account_micro':cap, 'reserve':reserve,
                'expires_at':expiry_text, 'price_version':price_version, 'mode':mode,
                # Audience changes authorization, never the existing funding
                # policy, campaign, historical spend or lifetime ceiling.
                'audience': audience if mode == 'owner_lifetime' else 'owner',
                **valuation}
    except (ValueError, KeyError, TypeError, OverflowError):
        return None


def allowed(owner, config=None, conn=None):
    """Authorize an existing account ID supplied by server authentication.

    An ID is not a login credential. Routes must still obtain it from their
    authenticated user and keep session/turn ownership fences. The authenticated
    audience accepts every existing account role without granting any new role.
    """
    if type(owner) is not int or not 0 < owner <= 10**9:
        return False
    config = policy() if config is None else config
    if not config:
        return False
    shared = config['mode'] == 'owner_lifetime' and config.get('audience') == 'authenticated'
    if not shared and config['allowed_owner'] != owner:
        return False
    query = ('SELECT u.id FROM users u LEFT JOIN customer_auth_account_state a ON a.user_id=u.id '
             'WHERE u.id=? AND COALESCE(a.disabled,0)=0')
    if conn is None:
        return bool(ledger.db.query_one(query, (owner,)))
    # PostgreSQL cannot lock the nullable side of an outer join. Keep the
    # owner row fence while rechecking disabled state without creating it.
    lock = ' FOR UPDATE OF u' if ledger.db.BACKEND == 'postgres' else ''
    return bool(usage._query(conn, query+lock, (owner,), one=True))


def _authorize(conn, owner, config):
    if not allowed(owner, config, conn):
        raise ledger.BudgetError('gemini_unavailable', 404)
    if not (config['mode'] == 'owner_lifetime' and config.get('audience') == 'authenticated'):
        # Preserve owner/QA eligibility and every other STT policy. The shared
        # native audience alone bypasses this owner/free-test role restriction.
        ledger._owner(conn, owner)


def ready(owner):
    return allowed(owner)


def _spend(conn, config):
    # Lifetime means every native campaign, including historical QA, cancelled
    # dispatches and unknown outcomes. Renaming a campaign cannot reset spend.
    lifetime = config['mode'] == 'owner_lifetime'
    return int(usage._query(conn,
        'SELECT COALESCE(SUM(charge_micro),0) FROM kilas_vo_stt_operations WHERE campaign '+('LIKE ?' if lifetime else '=?'),
        ('gml-%' if lifetime else config['id'],), one=True)[0])


def status(owner):
    """Read-only internal allowance snapshot; never a supplier wallet balance.

    This snapshot grants no reservation. Each physical connection must still
    claim and dispatch under the shared PostgreSQL admission lock.
    """
    config = policy()
    unavailable = {'available': False, 'reason': 'gemini_unavailable'}
    if not config or not allowed(owner, config):
        return unavailable
    with transaction() as conn:
        ledger._global_lock(conn)
        _authorize(conn, owner, config)
        row = usage._query(conn,
            'SELECT global_micro,account_micro,expires_at,price_version,blocked FROM kilas_vo_stt_campaigns WHERE id=?',
            (config['id'],), one=True)
        if row and (row[4] or tuple(row[:4]) != tuple(config[k] for k in ('global_micro', 'account_micro', 'expires_at', 'price_version'))):
            return {'available': False, 'reason': 'campaign_blocked' if row[4] else 'campaign_policy_changed'}
        charged = _spend(conn, config)
        remaining = max(0, config['global_micro']-charged)
        active = bool(usage._query(conn,
            "SELECT 1 FROM kilas_vo_stt_operations WHERE user_id=? AND status IN ('RESERVED','DISPATCHED')",
            (owner,), one=True))
    reason = 'already_processing' if active else 'budget_limit' if remaining < config['reserve'] else None
    return {'available': reason is None, 'reason': reason, 'policy_mode': config['mode'], 'audience': config['audience'],
            'valuation_mode': config.get('valuation_mode'), 'total_idr': config.get('total_idr'),
            'guard_idr': config.get('guard_idr'), 'idr_per_usd': config.get('idr_per_usd'),
            'cap_micro_usd': config['global_micro'], 'charged_micro_usd': charged,
            'remaining_micro_usd': remaining, 'reserve_micro_usd': config['reserve'],
            'remaining_leases': remaining//config['reserve'], 'lease_ms': LEASE_MS, 'active': active}


def claim(owner, ident, key):
    config = policy()
    if not config or not allowed(owner, config):
        raise ledger.BudgetError('gemini_unavailable', 404)
    if not re.fullmatch(r'live-[a-f0-9]{32}', key):
        raise ledger.BudgetError('invalid_operation', 400)
    operation = key+'-gm'
    # Native start already claims the owner-bound logical session. Its stable
    # rate bucket is not a capability: unique keys and lease nonces still fence
    # every physical dispatch. Preserve historical/QA per-operation hashes.
    fingerprint = hashlib.sha256(('native-logical-session:'+ident if config['mode'] == 'owner_lifetime'
                                  else ident+':'+key).encode()).hexdigest()
    with transaction() as conn:
        ledger._campaign(conn, config)
        _authorize(conn, owner, config)
        ledger._expire(conn, owner=owner)
        if ledger._row(conn, owner, operation):
            raise ledger.BudgetError('duplicate_turn', 409)
        # Share paid-STT concurrency/rate fences, without sharing its funding.
        if usage._query(conn, "SELECT 1 FROM kilas_vo_stt_operations WHERE user_id=? AND status IN ('RESERVED','DISPATCHED')", (owner,), one=True):
            raise ledger.BudgetError('already_processing', 429)
        if usage._query(conn, "SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE status IN ('RESERVED','DISPATCHED')", one=True)[0] >= ledger.GLOBAL_CONCURRENCY:
            raise ledger.BudgetError('service_busy', 429)
        now = datetime.now(timezone.utc)
        if config['mode'] == 'owner_lifetime' and usage._query(conn,
                'SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE user_id=? AND campaign LIKE ? AND created_at>=?',
                (owner, 'gml-%', (now-timedelta(hours=1)).isoformat()), one=True)[0] >= OWNER_PHYSICAL_LEASES_PER_HOUR:
            raise ledger.BudgetError('attempt_limit', 429)
        for seconds, maximum in ((3600, ledger.OWNER_HOURLY_ATTEMPTS), (86400, ledger.OWNER_DAILY_ATTEMPTS)):
            cutoff = (now-timedelta(seconds=seconds)).isoformat()
            if config['mode'] == 'owner_lifetime':
                # Count each native logical session once in this window; old
                # QA hashes stay conservatively separate. Every original Live
                # or STT operation keeps its prior individual attempt weight.
                # Exclude this bucket only if it is present in the window, so
                # a session can renew at the logical-session limit, while a
                # different or long-idle session must still gain a new slot.
                attempts = usage._query(conn,
                    'SELECT COUNT(DISTINCT CASE WHEN campaign LIKE ? THEN fingerprint ELSE operation_key END) '
                    'FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key LIKE ? AND created_at>=? '
                    'AND (campaign NOT LIKE ? OR fingerprint<>?)',
                    ('gml-%', owner, 'live-%', cutoff, 'gml-%', fingerprint), one=True)[0]
            else:
                attempts = usage._query(conn,
                    'SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key LIKE ? AND created_at>=?',
                    (owner, 'live-%', cutoff), one=True)[0]
            if attempts >= maximum:
                raise ledger.BudgetError('attempt_limit', 429)
        spent = _spend(conn, config)
        if spent + config['reserve'] > config['global_micro']:
            raise ledger.BudgetError('budget_limit', 429)
        lease = secrets.token_hex(32)
        usage._query(conn, "INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at) VALUES (?,?,?,?,'RESERVED',?,?,?,?)",
                     (owner, operation, config['id'], fingerprint,
                      config['reserve'], LEASE_MS, ledger._hash(lease), now.isoformat()))
        return ledger.Reservation(owner, operation, lease)


def dispatch(capability):
    if type(capability) is not ledger.Reservation:
        raise ledger.BudgetError('invalid_reservation')
    config = policy()
    if not config or not allowed(capability.owner, config):
        raise ledger.BudgetError('gemini_unavailable', 404)
    with transaction() as conn:
        ledger._campaign(conn, config)  # Recheck campaign block/config before dispatch.
        row = ledger._lock_existing_campaign(conn, capability.owner, capability.key)
        _authorize(conn, capability.owner, config)
        if (not row or row[1] != config['id'] or row[3] != 'RESERVED'
                or row[4] != config['reserve'] or row[5] != ledger._hash(capability.lease)
                or row[6] != LEASE_MS):
            raise ledger.BudgetError('invalid_reservation')
        admitted = usage._query(conn, 'SELECT created_at FROM kilas_vo_stt_operations WHERE id=?', (row[0],), one=True)[0]
        try:
            admitted_at = datetime.fromisoformat(admitted.replace('Z', '+00:00'))
            age = (datetime.now(timezone.utc)-admitted_at).total_seconds()
        except (ValueError, TypeError, AttributeError):
            raise ledger.BudgetError('invalid_reservation') from None
        if not 0 <= age <= DISPATCH_MAX_AGE_SECONDS:
            raise ledger.BudgetError('reservation_expired', 409)
        usage._query(conn, "UPDATE kilas_vo_stt_operations SET status='DISPATCHED',dispatched_at=? WHERE id=?",
                     (datetime.now(timezone.utc).isoformat(), row[0]))


def finish(capability, success):
    # Settlement remains possible after expiry, flag-off, End or policy edits.
    if type(capability) is not ledger.Reservation or type(capability.owner) is not int or not 0 < capability.owner <= 10**9:
        raise ledger.BudgetError('invalid_reservation')
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
