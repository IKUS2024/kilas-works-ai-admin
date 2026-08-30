"""Tenant-scoped automatic follow-up — Business Hub V2, Gap-fix Area F.

Closes the documented gap in ../app.py (see that file's own comment at the
"if is_kilas_tenant: mark_customer_activity(...)" call site): the bot's global follow-up
sales-engine (`followup_state` table + /cron/followups) was deliberately Kilas-Works-only, because
enrolling a client tenant's own customer into it would send that customer a nudge via Kilas Works'
GLOBAL WhatsApp channel — a clear cross-tenant identity leak. This module is the tenant-aware
equivalent, using EACH tenant's OWN validated WhatsApp channel, never the global one.

WHY A NEW TABLE, NOT AN EXTENSION OF ../app.py's `followup_state`: see migrations/0015's own
docstring for the full architecture reasoning (different database, different key shape, avoids
mixing global and tenant state). Every row here is scoped by (business_id, customer_phone), a
UNIQUE pair — two different tenants can have a customer with the identical phone number and their
follow-up state never collides (see test_two_tenants_same_customer_phone_stay_isolated).

ELIGIBILITY (an ineligible tenant/customer is skipped ENTIRELY — no partial/fallback send):
  - business must be ACTIVE (a SUSPENDED tenant — including one suspended purely for AI Admin
    subscription non-payment, see subscription_service.py — is never enrolled; this is the same
    single-column check every other tenant_config_service.py function already relies on).
  - the tenant's own subscription (subscription_service.get_subscription) must exist AND be in a
    currently-operating state (ACTIVE or GRACE) — Fix 4: a MISSING subscription row is explicitly
    INELIGIBLE, never treated as "unrestricted". SUSPENDED/CANCELLED are explicitly blocked too.
    This is checked redundantly with the business-status check above, so a future code path that
    changes subscription state WITHOUT (yet) flipping business.status still fails safe here.
  - the tenant's WhatsApp channel must be phone_number_id-configured AND its
    tenant_whatsapp_config.connection_status must be exactly 'CONNECTED' (validated) — a
    PENDING_VALIDATION or VALIDATION_FAILED channel is treated identically to "not configured".
  - the "lead_qualification" feature flag must be enabled for this tenant's package (this is the
    SAME flag that already gates Pro-only lead-nurturing behavior — AI Admin Pro's own product
    copy already describes "Follow-up dasar ke customer yang sempat diam" as a Pro capability, so
    this reuses that existing flag rather than adding a new tenant_features column/migration for a
    capability the product already ties to the same tier).
  - the customer must not be in HUMAN_TAKEOVER (checked by the caller via
    tenant_config_service.get_conversation_mode() immediately before generating/sending each nudge
    — state can change between when this module lists "due" customers and when the cron actually
    gets to them, so the caller re-checks per-customer right before sending, not just once).

COOLDOWN / MAX ATTEMPTS: mirrors ../app.py's own Kilas-Works-only get_customers_due_for_followup()
— a customer is only "due" after `hours` since their last message AND `hours` since their last
follow-up (never spam), and stops permanently once `followup_count` reaches `max_count` or the row
is marked `resolved` (booking/sale/explicit stop-request/any other resolution). A customer is ALSO
never "due" once >= WHATSAPP_24H_SAFETY_HOURS have passed since their last inbound message — see
that constant's comment for the Meta Cloud API 24-hour customer-service-window rationale.
"""
import db
import repo
from datetime import datetime, timedelta, timezone

DEFAULT_FOLLOWUP_GAP_HOURS = 8
DEFAULT_MAX_FOLLOWUPS = 2

# PRODUCTION MICRO-FIX — same Meta Cloud API error 131047 fix as ../app.py's
# WHATSAPP_24H_SAFETY_HOURS (see that constant's comment for the full rationale). 23 hours, not
# 24, as a safety buffer against clock drift/cron timing. No template fallback, no other-channel
# fallback — outside the window, the tenant follow-up is simply skipped for that customer.
WHATSAPP_24H_SAFETY_HOURS = 23

# Fix 4 — subscription states allowed to receive paid AI automation (follow-up included). A
# MISSING subscription row is deliberately NOT in this set: for an AI Admin tenant, "no
# subscription record" must never be read as "unrestricted/free access" — see
# is_tenant_followup_eligible()'s docstring.
_SUBSCRIPTION_STATES_ALLOWED_TO_RUN = ("ACTIVE", "GRACE")


def _now():
    return repo._now()


def _get_state(business_id, customer_phone):
    return db.query_one(
        "SELECT * FROM tenant_followup_state WHERE business_id = ? AND customer_phone = ?",
        (business_id, customer_phone),
    )


def _upsert_state(business_id, customer_phone, **fields):
    existing = _get_state(business_id, customer_phone)
    now = _now()
    if existing:
        set_clauses = ", ".join(f"{k} = ?" for k in fields)
        params = list(fields.values()) + [now, business_id, customer_phone]
        db.execute(
            f"UPDATE tenant_followup_state SET {set_clauses}, updated_at = ? "
            f"WHERE business_id = ? AND customer_phone = ?",
            params,
        )
    else:
        columns = ["business_id", "customer_phone"] + list(fields.keys())
        placeholders = ", ".join(["?"] * len(columns))
        values = [business_id, customer_phone] + list(fields.values())
        db.execute(
            f"INSERT INTO tenant_followup_state ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )


def mark_customer_activity(business_id, customer_phone):
    """Call every time this tenant's customer sends a real message — resets followup_count to 0
    (they're not 'silent' anymore) and stamps last_customer_msg_at. Mirrors
    ../app.py's mark_customer_activity() for Kilas Works' own customers, but scoped and persisted
    here instead."""
    _upsert_state(business_id, customer_phone, last_customer_msg_at=_now(), followup_count=0)


def mark_resolved(business_id, customer_phone, reason=None):
    """Stops follow-up PERMANENTLY for this (business_id, customer_phone) pair — booking
    confirmed, payment confirmed/proof sent, or the customer explicitly asked not to be contacted
    again. Mirrors ../app.py's mark_customer_converted()."""
    _upsert_state(business_id, customer_phone, resolved=True, resolved_reason=reason)


def record_followup_sent(business_id, customer_phone):
    state = _get_state(business_id, customer_phone)
    count = (state["followup_count"] if state else 0) + 1
    _upsert_state(business_id, customer_phone, last_followup_at=_now(), followup_count=count)


def is_tenant_followup_eligible(business_id):
    """Returns (eligible: bool, reason: str) — reason is always populated (even on success, for
    logging), so a caller/cron can print exactly why a tenant was skipped without needing to
    re-derive the same checks. NEVER returns True for a business this process can't positively
    confirm is ACTIVE, subscribed to a currently-operating state, feature-flagged, and
    channel-validated — any missing/ambiguous signal is treated as ineligible (fail safe), never
    as 'assume yes'.

    Fix 4 (fail-closed on a MISSING subscription row): a business with NO subscriptions row at
    all — e.g. a pre-existing tenant activated before migration 0014 shipped and not yet
    backfilled (see migrations/0014's own docstring + the deployment report's backfill
    procedure), or any other state this module can't positively verify — is now INELIGIBLE. For
    an AI Admin tenant, "we don't have a subscription record" must never be silently read as
    "no restrction applies" (the exact opposite of the intended default). Only ACTIVE and GRACE
    subscription states may run paid automation; SUSPENDED and CANCELLED are explicitly blocked;
    everything else (including "no row") is blocked by not being in the allowed set."""
    business = repo.get_business(business_id)
    if not business:
        return False, "business_not_found"
    if business["status"] != "ACTIVE":
        return False, f"business_not_active(status={business['status']})"

    try:
        import subscription_service
        sub = subscription_service.get_subscription(business_id)
    except Exception as e:
        # A subscription-plumbing failure must NEVER be treated as "no subscription, proceed
        # anyway" — fail safe and skip this tenant rather than risk sending to a possibly-lapsed
        # tenant.
        return False, f"subscription_check_failed({e})"
    if sub is None:
        # Fix 4 — missing subscription row is NOT the same as "unrestricted". Fail closed.
        return False, "subscription_missing"
    if sub["status"] not in _SUBSCRIPTION_STATES_ALLOWED_TO_RUN:
        return False, f"subscription_not_operating(status={sub['status']})"

    features = repo.get_tenant_features(business_id)
    if not features.get("lead_qualification", False):
        return False, "followup_not_in_plan(lead_qualification=False)"

    wa_config = repo.get_whatsapp_config(business_id)
    if not wa_config or not wa_config.get("phone_number_id"):
        return False, "whatsapp_not_configured"
    if wa_config.get("connection_status") != "CONNECTED":
        return False, f"whatsapp_not_validated(status={wa_config.get('connection_status')})"

    return True, "eligible"


def get_customers_due_for_followup(business_id, hours=DEFAULT_FOLLOWUP_GAP_HOURS,
                                    max_count=DEFAULT_MAX_FOLLOWUPS):
    """Tenant-scoped equivalent of ../app.py's get_customers_due_for_followup(). Does NOT itself
    check eligibility (business ACTIVE/subscription/feature/WhatsApp-validated) — callers MUST call
    is_tenant_followup_eligible() first and skip the whole tenant if ineligible, since a tenant
    that just became ineligible mid-period should never resume sending just because old rows are
    still sitting here (rows are never deleted, only stop advancing).

    PRODUCTION MICRO-FIX — same 23-hour WhatsApp customer-service-window safety gate as
    ../app.py's get_customers_due_for_followup() (see WHATSAPP_24H_SAFETY_HOURS above): a customer
    whose last inbound message was >= 23 hours ago is skipped entirely, never sent a free-text
    follow-up outside Meta's 24-hour window, and never falls back to a template or another
    channel."""
    now_dt = datetime.now(timezone.utc)
    rows = db.query_all(
        "SELECT * FROM tenant_followup_state WHERE business_id = ? AND resolved = ?",
        (business_id, False),
    )
    due = []
    for row in rows:
        if row["followup_count"] >= max_count:
            continue
        last_msg = _parse(row["last_customer_msg_at"])
        if not last_msg:
            continue
        if now_dt - last_msg < timedelta(hours=hours):
            continue
        if now_dt - last_msg >= timedelta(hours=WHATSAPP_24H_SAFETY_HOURS):
            continue  # outside WhatsApp's 24h customer-service window — skip, no fallback
        last_followup = _parse(row["last_followup_at"])
        if last_followup and (now_dt - last_followup < timedelta(hours=hours)):
            continue
        due.append(row["customer_phone"])
    return due


def _parse(ts):
    """Normalize a tenant_followup_state timestamp value into an aware `datetime`, regardless of
    whether the DB driver handed back a plain ISO string (SQLite) or an already-parsed `datetime`
    object (what a real psycopg2/PostgreSQL TIMESTAMPTZ column returns natively — see
    subscription_service._parse()'s docstring for the same fix applied there). A naive `datetime`
    (no tzinfo) is treated as UTC so it can always be safely subtracted from/compared against the
    tz-aware `now_dt` this module always uses. Returns None for anything unparseable/missing —
    callers must treat that as 'unknown', never as 'due now'."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, str):
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None
