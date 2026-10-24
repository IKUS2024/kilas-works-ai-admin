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


def policy(*, enabled_key='KILAS_LIVE_GEMINI_ENABLED', _environment=None):
    environment = os.environ if _environment is None else _environment
    try:
        if environment.get(enabled_key, '').lower() not in ('true', '1', 'on'):
            return None
        if environment.get('KILAS_LIVE_GEMINI_BILLING_VERIFIED') != 'yes':
            return None
        campaign = environment['KILAS_LIVE_GEMINI_CAMPAIGN']
        owner = int(environment['KILAS_LIVE_GEMINI_ALLOWED_OWNER_ID'])
        cap = int(environment['KILAS_LIVE_GEMINI_BUDGET_MICRO_USD'])
        reserve = int(environment['KILAS_LIVE_GEMINI_LEASE_RESERVE_MICRO_USD'])
        mode = environment.get('KILAS_LIVE_GEMINI_POLICY', 'qa')
        audience = environment.get('KILAS_LIVE_GEMINI_AUDIENCE', 'owner')
        if audience not in ('owner', 'authenticated'):
            return None
        valuation = {}
        price_version = PRICE_VERSION
        if mode == 'owner_lifetime':
            approved_idr = int(environment['KILAS_LIVE_GEMINI_TOTAL_IDR'])
            if not 0 < approved_idr <= 500000:
                return None
            valuation_mode = environment.get('KILAS_LIVE_GEMINI_IDR_VALUATION_MODE', 'verified_ceiling')
            if valuation_mode == 'verified_ceiling':
                # A verified tax/fee-inclusive bound remains a separate path.
                # Neither a wallet balance nor a market quote verifies it.
                if environment.get('KILAS_LIVE_GEMINI_IDR_CEILING_VERIFIED') != 'yes':
                    return None
                ceiling = int(environment['KILAS_LIVE_GEMINI_IDR_PER_USD_CEILING'])
                guard_idr = approved_idr
            elif valuation_mode == 'conservative_internal':
                # Explicit internal accounting assumption, NOT actual FX,
                # supplier usage, an invoice ceiling or a prepaid hard stop.
                # All amounts need affirmative configuration; no spend defaults.
                if environment.get('KILAS_LIVE_GEMINI_INTERNAL_VALUATION_ACK') != 'yes':
                    return None
                ceiling = int(environment['KILAS_LIVE_GEMINI_IDR_PER_USD_INTERNAL'])
                guard_idr = int(environment['KILAS_LIVE_GEMINI_INTERNAL_GUARD_IDR'])
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
            expiry = datetime.fromisoformat(environment['KILAS_LIVE_GEMINI_EXPIRES_AT'].replace('Z', '+00:00'))
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
        policy_id = 'gml-'+campaign
        # Explicit approvals: $1 on Oct23, another $1 on Oct24, Translator only.
        # Other enabled_key callers (especially AI Call) retain byte-identical
        # base policy. New immutable metadata does not reset global history.
        extension = environment.get('KILAS_TRANSLATOR_TRIAL_EXTENSION_MICRO_USD', '0')
        if enabled_key == 'KILAS_LIVE_GEMINI_ENABLED' and extension != '0':
            if (extension not in ('1000000', '2000000', '2400000', '7400000') or mode != 'owner_lifetime'
                    or audience != 'authenticated' or cap != 10000000
                    or valuation.get('valuation_mode') != 'conservative_internal'):
                return None
            cap += int(extension)
            valuation['guard_idr'] += (int(extension)*valuation['idr_per_usd']+999999)//1000000
            if valuation['guard_idr'] > valuation['total_idr']:
                return None
            identity = campaign if extension == '1000000' else campaign+':'+extension
            policy_id = 'gml-translator-extension-'+hashlib.sha256(identity.encode()).hexdigest()[:24]
            price_version += '-translator-approved-extra'+extension+'-v1'
        if enabled_key == 'KILAS_LIVE_GEMINI_ENABLED' and mode == 'owner_lifetime':
            policy_id = 'gml-usage-v1-'+hashlib.sha256(policy_id.encode()).hexdigest()[:24]
            price_version += '-prospective-usage-v1'
        return {'id':policy_id, 'allowed_owner':owner, 'global_micro':cap,
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
    # Every historical dispatch remains charged. Only Translator trial accounting
    # excludes Call envelopes proven funded separately by the same account/key.
    # Call callers retain their existing calculation and admission behavior.
    lifetime = config['mode'] == 'owner_lifetime'
    total = int(usage._query(conn,
        'SELECT COALESCE(SUM(charge_micro),0) FROM kilas_vo_stt_operations WHERE campaign '+('LIKE ?' if lifetime else '=?'),
        ('gml-%' if lifetime else config['id'],), one=True)[0])
    if not lifetime or config['id'].startswith('gml-call-'):
        return total
    candidates = usage._rows(conn,
        "SELECT user_id,operation_key,charge_micro FROM kilas_vo_stt_operations "
        "WHERE campaign LIKE ? AND charge_micro>0 AND dispatched_at IS NOT NULL "
        "AND status IN ('DISPATCHED','COMPLETED','UNKNOWN')", ('gml-call-%',))
    if not candidates:
        return total
    from decimal import Decimal, DecimalException
    accounts = {}
    for record in usage._rows(conn,
            "SELECT u.user_id,u.operation_key,u.operation_type,u.mode,u.status,u.quota_source,u.provider,u.model,u.estimated_cost_usd "
            "FROM kilas_ai_usage u JOIN kilas_vo_stt_operations o "
            "ON o.user_id=u.user_id AND o.operation_key=u.operation_key "
            "WHERE o.campaign LIKE ? AND o.charge_micro>0 AND o.dispatched_at IS NOT NULL "
            "AND o.status IN ('DISPATCHED','COMPLETED','UNKNOWN')", ('gml-call-%',)):
        accounts.setdefault(tuple(record[:2]), []).append(record[2:])
    excluded = 0
    for owner, key, charge in candidates:
        if not re.fullmatch(r'live-[a-f0-9]{32}-gc', key):
            continue
        # Full evidence must be unique and exact; partial, mismatched, duplicate,
        # pending or refunded records cannot free trial capacity. Never infer
        # funding from another user's matching key or from a campaign name alone.
        records = accounts.get((owner, key), [])
        if len(records) != 1:
            continue
        kind, mode, status, source, provider, model, cost = records[0]
        if (kind, mode, status, provider, model) != ('AI_CALL', 'SMART', 'COMPLETE', 'google', 'gemini-3.8-live') or source not in ('BASE', 'TOPUP'):
            continue
        try:
            amount = Decimal(str(cost))*1000000
            if amount.is_finite() and amount == charge:
                excluded += charge
        except (DecimalException, ValueError, TypeError):
            continue
    return total-excluded


def _stream_count(streams):
    if type(streams) is not int or streams not in (1, 2):
        raise ledger.BudgetError('invalid_operation', 400)
    return streams


def _capability_streams(capability):
    if (type(capability) is not ledger.Reservation or not isinstance(capability.key, str)
            or not re.fullmatch(r'live-[a-f0-9]{32}-gm(?:2:parent)?', capability.key)):
        raise ledger.BudgetError('invalid_reservation')
    return 2 if capability.key.endswith('-gm2:parent') else 1


def _group_rows(conn, capability, row, streams):
    if streams == 1:
        return [row]
    slot = ledger._row(conn, capability.owner, capability.key.removesuffix(':parent')+':slot')
    if (not slot or slot[1:4] != row[1:4] or slot[4] != 0 or slot[5:] != row[5:]
            or (row[4] <= 0 and row[3] != 'CANCELLED'
                    and not (row[3] == 'COMPLETED' and row[1].startswith('gml-usage-v1-')))):
        # A malformed or partially changed pair cannot dispatch or release its
        # parent charge. Ordinary lifecycle transitions always update both.
        raise ledger.BudgetError('invalid_reservation')
    return [row, slot]


def _preview_active(conn, owner):
    """Observe typed native expiry without mutating or releasing a ledger row."""
    cutoff=datetime.now(timezone.utc)-timedelta(seconds=120)
    for key,campaign,created,price in usage._rows(conn,
            "SELECT o.operation_key,o.campaign,o.created_at,c.price_version "
            "FROM kilas_vo_stt_operations o LEFT JOIN kilas_vo_stt_campaigns c ON c.id=o.campaign "
            "WHERE o.user_id=? AND o.status IN ('RESERVED','DISPATCHED')",(owner,)):
        # Only this product's proven 90s native leases have the 120s fence.
        # Other products, unknown policies/keys and malformed dates fail closed.
        typed=(isinstance(key,str) and re.fullmatch(r'live-[a-f0-9]{32}-gm(?:2:(?:parent|slot))?',key)
               and isinstance(campaign,str) and campaign.startswith('gml-')
               and isinstance(price,str) and (price==PRICE_VERSION or price.startswith(PRICE_VERSION+'-')))
        if typed:
            try:
                start=datetime.fromisoformat(created)
                if start.tzinfo is not None and start<cutoff:
                    continue  # claim() performs the original locked expiry.
            except (ValueError,TypeError):
                pass
        return True
    return False


def status(owner, *, streams=1):
    """Read-only internal allowance snapshot; never a supplier wallet balance.

    This snapshot grants no reservation. Each physical connection must still
    claim and dispatch under the shared PostgreSQL admission lock.
    """
    streams = _stream_count(streams)
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
        active = _preview_active(conn,owner)
    reserve = config['reserve']*streams
    reason = 'already_processing' if active else 'budget_limit' if remaining < reserve else None
    return {'available': reason is None, 'reason': reason, 'policy_mode': config['mode'], 'audience': config['audience'],
            'valuation_mode': config.get('valuation_mode'), 'total_idr': config.get('total_idr'),
            'guard_idr': config.get('guard_idr'), 'idr_per_usd': config.get('idr_per_usd'),
            'cap_micro_usd': config['global_micro'], 'charged_micro_usd': charged,
            'remaining_micro_usd': remaining, 'reserve_micro_usd': reserve,
            'remaining_leases': remaining//reserve, 'lease_ms': LEASE_MS, 'active': active,
            'streams': streams}


def claim(owner, ident, key, *, streams=1):
    streams = _stream_count(streams)
    config = policy()
    if not config or not allowed(owner, config):
        raise ledger.BudgetError('gemini_unavailable', 404)
    if not re.fullmatch(r'live-[a-f0-9]{32}', key):
        raise ledger.BudgetError('invalid_operation', 400)
    # New pair keys cannot pass the generic STT cancellation key validator.
    # The existing single-stream namespace stays compatible with prior callers.
    operation = key+('-gm2:parent' if streams == 2 else '-gm')
    reserve = config['reserve']*streams
    # Native start already claims the owner-bound logical session. Its stable
    # rate bucket is not a capability: unique keys and lease nonces still fence
    # every physical dispatch. Preserve historical/QA per-operation hashes.
    fingerprint = hashlib.sha256(('native-logical-session:'+ident if config['mode'] == 'owner_lifetime'
                                  else ident+':'+key).encode()).hexdigest()
    with transaction() as conn:
        ledger._campaign(conn, config)
        _authorize(conn, owner, config)
        ledger._expire(conn, owner=owner)
        if any(ledger._row(conn, owner, candidate) for candidate in (key+'-gm', key+'-gm2:parent', key+'-gm2:slot')):
            raise ledger.BudgetError('duplicate_turn', 409)
        # Share paid-STT concurrency/rate fences, without sharing its funding.
        if usage._query(conn, "SELECT 1 FROM kilas_vo_stt_operations WHERE user_id=? AND status IN ('RESERVED','DISPATCHED')", (owner,), one=True):
            raise ledger.BudgetError('already_processing', 429)
        if usage._query(conn, "SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE status IN ('RESERVED','DISPATCHED')", one=True)[0]+streams > ledger.GLOBAL_CONCURRENCY:
            raise ledger.BudgetError('service_busy', 429)
        now = datetime.now(timezone.utc)
        if config['mode'] == 'owner_lifetime' and usage._query(conn,
                'SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE user_id=? AND campaign LIKE ? AND created_at>=?',
                (owner, 'gml-%', (now-timedelta(hours=1)).isoformat()), one=True)[0]+streams > OWNER_PHYSICAL_LEASES_PER_HOUR:
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
            if attempts+(streams if config['mode'] == 'qa' else 1) > maximum:
                raise ledger.BudgetError('attempt_limit', 429)
        spent = _spend(conn, config)
        if spent + reserve > config['global_micro']:
            raise ledger.BudgetError('budget_limit', 429)
        lease = secrets.token_hex(32)
        usage._query(conn, "INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at) VALUES (?,?,?,?,'RESERVED',?,?,?,?)",
                     (owner, operation, config['id'], fingerprint,
                      reserve, LEASE_MS, ledger._hash(lease), now.isoformat()))
        if streams == 2:
            # A zero-charge companion occupies the second physical capacity
            # unit in every existing STT COUNT fence. The parent owns all cost.
            usage._query(conn, "INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at) VALUES (?,?,?,?,'RESERVED',0,?,?,?)",
                         (owner, key+'-gm2:slot', config['id'], fingerprint,
                          LEASE_MS, ledger._hash(lease), now.isoformat()))
        return ledger.Reservation(owner, operation, lease)


def dispatch(capability):
    streams = _capability_streams(capability)
    config = policy()
    if not config or not allowed(capability.owner, config):
        raise ledger.BudgetError('gemini_unavailable', 404)
    with transaction() as conn:
        ledger._campaign(conn, config)  # Recheck campaign block/config before dispatch.
        row = ledger._lock_existing_campaign(conn, capability.owner, capability.key)
        _authorize(conn, capability.owner, config)
        if (not row or row[1] != config['id'] or row[3] != 'RESERVED'
                or row[4] != config['reserve']*streams or row[5] != ledger._hash(capability.lease)
                or row[6] != LEASE_MS):
            raise ledger.BudgetError('invalid_reservation')
        rows = _group_rows(conn, capability, row, streams)
        admissions = [usage._query(conn, 'SELECT created_at FROM kilas_vo_stt_operations WHERE id=?', (item[0],), one=True)[0] for item in rows]
        if any(value != admissions[0] for value in admissions):
            raise ledger.BudgetError('invalid_reservation')
        try:
            admitted_at = datetime.fromisoformat(admissions[0].replace('Z', '+00:00'))
            age = (datetime.now(timezone.utc)-admitted_at).total_seconds()
        except (ValueError, TypeError, AttributeError):
            raise ledger.BudgetError('invalid_reservation') from None
        if not 0 <= age <= DISPATCH_MAX_AGE_SECONDS:
            raise ledger.BudgetError('reservation_expired', 409)
        for item in rows:
            usage._query(conn, "UPDATE kilas_vo_stt_operations SET status='DISPATCHED',dispatched_at=? WHERE id=?",
                         (datetime.now(timezone.utc).isoformat(), item[0]))


def finish(capability, success, *, verified_usage=None):
    # Settlement remains possible after expiry, flag-off, End or policy edits.
    streams = _capability_streams(capability)
    if type(capability.owner) is not int or not 0 < capability.owner <= 10**9:
        raise ledger.BudgetError('invalid_reservation')
    with transaction() as conn:
        row = ledger._lock_existing_campaign(conn, capability.owner, capability.key)
        ledger._owner(conn, capability.owner, settlement=True)
        if not row or row[5] != ledger._hash(capability.lease):
            raise ledger.BudgetError('invalid_reservation')
        rows = _group_rows(conn, capability, row, streams)
        if row[3] not in ('RESERVED', 'DISPATCHED'):
            return False
        dispatched = row[3] == 'DISPATCHED'
        status = 'COMPLETED' if success and dispatched else 'UNKNOWN' if dispatched else 'CANCELLED'
        charge = row[4] if dispatched else 0
        from .live_gemini_usage import VerifiedUsage
        if (success and dispatched and MODEL == 'gemini-3.5-live-translate-preview'
                and row[1].startswith('gml-usage-v1-')
                and type(verified_usage) is VerifiedUsage and verified_usage.streams == streams
                and type(verified_usage.input_tokens) is int and verified_usage.input_tokens >= 0
                and type(verified_usage.output_tokens) is int and verified_usage.output_tokens >= 0
                ):
            usage._query(conn, 'UPDATE kilas_vo_stt_operations SET input_tokens=?,output_tokens=?,actual_estimate_micro=? WHERE id=?',
                         (verified_usage.input_tokens,verified_usage.output_tokens,verified_usage.micro_usd,row[0]))
            if verified_usage.micro_usd <= charge:
                charge = verified_usage.micro_usd
            else:
                # A violated envelope cannot silently admit another operation.
                usage._query(conn, 'UPDATE kilas_vo_stt_campaigns SET blocked=1 WHERE id=?', (row[1],))
        for item in rows:
            usage._query(conn, 'UPDATE kilas_vo_stt_operations SET status=?,charge_micro=?,finished_at=? WHERE id=?',
                         (status, charge if item is rows[0] else 0, datetime.now(timezone.utc).isoformat(), item[0]))
        return success and dispatched
