"""AI Admin monthly SUBSCRIPTION lifecycle — Business Hub V2, Gap-fix Area E.

Scope: applies ONLY to the recurring AI Admin subscription (plan_key 'ai_admin_basic' /
'ai_admin_pro', matching businesses.package 'AI_ADMIN_BASIC' / 'AI_ADMIN_PRO' — pricing itself is
UNCHANGED, still Rp499.000/Rp999.000 per PRICING_CONFIG/pricing_config.py, this module never
invents or redefines a price). It is COMPLETELY INDEPENDENT of creative-service projects
(PHOTO/VIDEO/CONTENT/TALENT/EVENT rows in projects_repo.py) — those stay project-based and keep
progressing through their own REQUESTED->...->COMPLETED lifecycle regardless of what this module
does to a business's subscription status. Nothing in this module ever touches the `projects` table.

STATE MACHINE (one row per business_id, businesses.subscriptions.business_id UNIQUE):

    ACTIVE --(period_end approaching)--> ACTIVE, reminder_stage advances H7 -> H3 -> H1
    ACTIVE --(period_end passed, no renewal)------------> GRACE (grace_started_at = now)
    GRACE  --(grace_days elapsed, no renewal)------------> SUSPENDED
    SUSPENDED --(renewal payment recorded)----------------> ACTIVE (reactivated_at = now)

REMINDER STAGES: three one-time reminder checkpoints before the due date — H7 (period_end is <= 7
days away), H3 (<= 3 days away), H1 (<= 1 day away). Each stage fires at most once per billing
period (tracked in `reminder_stage`, which only ever advances forward — H7 -> H3 -> H1 — and is
reset to NULL on every renewal so the next period gets its own fresh set of reminders). A sweep
that hasn't run in a while (e.g. daily cron skipped a day) safely jumps straight to whichever stage
is currently due rather than trying to "catch up" on an already-passed stage.

SUSPENSION IS NON-DESTRUCTIVE: the only side effect `run_lifecycle_sweep()` has when a
subscription flips to SUSPENDED is calling `repo.deactivate_business()`, which does exactly two
things — sets `businesses.status = 'SUSPENDED'` and stamps `tenant_activation.deactivated_at`.
Every other tenant table is untouched and nothing is deleted:
  - tenant_configs / tenant_whatsapp_config (WhatsApp phone_number_id mapping) — untouched
  - ai_settings / normalized_config (the tenant's AI knowledge) — untouched
  - business_profiles / business_services / business_faqs — untouched
  - tenant_appointments, tenant_payment_reviews (that tenant's own customer data/history) —
    untouched
  - projects, quotations, payments (creative-service history, Kilas-Works-billing history) —
    untouched
A SUSPENDED business simply stops resolving as an ACTIVE tenant for the WhatsApp bot (every
tenant_config_service.py function already refuses to serve a non-ACTIVE business — see that
module's "only serve ACTIVE tenants" rule repeated in every function there), which is exactly how
the AI Admin service is meant to pause. `renew_subscription()` reactivating a SUSPENDED business
calls `repo.activate_business()` — the exact inverse, single-column flip — so nothing about
onboarding/AI setup/simulation ever needs to run again.

NOTIFICATIONS: every reminder/grace/suspension/reactivation event in this module is OWNER-FACING
ONLY, surfaced via `get_subscription_banner()` on that business's OWN Client Hub dashboard (the
tenant/business owner's own login) — this is a DIFFERENT concern from
../owner_notifications.py, which notifies KILAS WORKS' OWN platform admin (Irvan) about onboarding/
quotation/payment events via WhatsApp. Nothing in this module ever sends a WhatsApp message to a
tenant's own end-customers, and nothing here touches ../app.py's customer-facing chat flow.
"""
from datetime import datetime, timedelta, timezone

import db
import repo

PLAN_KEYS = ("ai_admin_basic", "ai_admin_pro")
STATUSES = ("ACTIVE", "GRACE", "SUSPENDED", "CANCELLED")
DEFAULT_GRACE_DAYS = 3
DEFAULT_PERIOD_DAYS = 30

# Reminder checkpoints, ordered farthest-from-due to nearest-to-due. A stage fires when
# days_remaining <= its threshold AND no later (more urgent) stage has already fired this period.
REMINDER_STAGES = (("H7", 7), ("H3", 3), ("H1", 1))
REMINDER_STAGE_RANK = {stage: rank for rank, (stage, _) in enumerate(REMINDER_STAGES, start=1)}

PACKAGE_TO_PLAN_KEY = {
    "AI_ADMIN_BASIC": "ai_admin_basic",
    "AI_ADMIN_PRO": "ai_admin_pro",
}


def _now_dt():
    return datetime.now(timezone.utc)


def _now():
    return _now_dt().isoformat()


def _parse(ts):
    """Normalize a subscriptions-table timestamp value into an aware `datetime`, regardless of
    whether the DB driver handed back a plain ISO string (SQLite, this module's own `_now()`/
    `_add_days()` outputs) or an already-parsed `datetime` object (what a real psycopg2/PostgreSQL
    TIMESTAMPTZ column typically returns — psycopg2 decodes TIMESTAMPTZ columns into native Python
    `datetime` objects, NOT strings, so any code that assumes `.replace("Z", ...)` works on every
    row value will TypeError against real Postgres even though it works fine against SQLite's
    text-only storage). A naive `datetime` (no tzinfo — shouldn't normally happen since every
    timestamp this module writes is UTC-aware, but handled defensively for a value written by
    something else) is treated as UTC. Returns None for anything unparseable/missing — callers
    must treat None as 'unknown', never silently as 'now' or 'already passed'."""
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


def _lte(a, b):
    """Safe `a <= b` between two timestamp-ish values (ISO string OR datetime OR None — see
    _parse()). Deliberately NEVER falls back to comparing the raw values directly (no
    lexicographic string comparison, no cross-type comparison that could TypeError) — always goes
    through _parse() first. If either side can't be parsed, returns False ('not due/not passed
    yet') rather than guessing True, since a missing/corrupt timestamp must never be treated as
    already elapsed."""
    a_dt, b_dt = _parse(a), _parse(b)
    if a_dt is None or b_dt is None:
        return False
    return a_dt <= b_dt


def _gt(a, b):
    """Safe `a > b` — see _lte()'s docstring for the same rules (parse-first, fail to False)."""
    a_dt, b_dt = _parse(a), _parse(b)
    if a_dt is None or b_dt is None:
        return False
    return a_dt > b_dt


def _add_days(ts, days):
    """Returns an ISO-format string `days` after `ts` (which may itself be an ISO string OR a
    datetime object — see _parse()). Always returns a plain string, since this is used to build
    values handed to db.execute()'s `?` params for storage, and a plain ISO string is accepted by
    both the SQLite and PostgreSQL drivers this codebase supports for a TEXT/TIMESTAMPTZ column."""
    dt = _parse(ts) or _now_dt()
    return (dt + timedelta(days=days)).isoformat()


def plan_key_for_package(package):
    """Never guesses — returns None for any package this module doesn't recognize (e.g. 'NONE'),
    so callers must handle 'no subscription applicable' explicitly rather than defaulting to a
    guessed plan."""
    return PACKAGE_TO_PLAN_KEY.get(package)


def create_subscription_with_explicit_period(business_id, plan_key, period_start, period_end,
                                              actor_user_id, grace_days=DEFAULT_GRACE_DAYS):
    """Fix 5 (production-safety patch) — backfill entrypoint for a PRE-EXISTING ACTIVE tenant that
    predates migration 0014 and therefore has no subscription row yet. Deliberately SEPARATE from
    create_subscription() (which always computes period_end as "now + period_days", appropriate
    for a FRESH activation happening right now) — this function NEVER invents/guesses a billing
    date on its own; the caller (scripts/backfill_subscriptions.py) MUST supply period_start/
    period_end explicitly, sourced from Kilas Admin's own verified knowledge of that tenant's real
    billing history. Idempotent the same way create_subscription() is: a no-op returning the
    existing row if one already exists, rather than overwriting it."""
    assert plan_key in PLAN_KEYS, f"unknown plan_key {plan_key!r}"
    existing = get_subscription(business_id)
    if existing:
        return existing
    period_start_iso = _parse(period_start)
    period_end_iso = _parse(period_end)
    if period_start_iso is None or period_end_iso is None:
        raise ValueError("invalid_period: period_start/period_end must be parseable dates")
    if period_end_iso <= period_start_iso:
        raise ValueError("invalid_period: period_end must be strictly after period_start (reversed or equal periods are rejected)")
    if grace_days < 0:
        raise ValueError("invalid_grace_days: grace_days must be >= 0")
    db.insert_returning_id(
        "INSERT INTO subscriptions (business_id, plan_key, status, period_start, period_end, "
        "grace_days) VALUES (?, ?, 'ACTIVE', ?, ?, ?)",
        (business_id, plan_key, period_start_iso.isoformat(), period_end_iso.isoformat(), grace_days),
    )
    repo.write_audit(actor_user_id, business_id, "SUBSCRIPTION_BACKFILLED",
                      f"plan={plan_key} period_start={period_start_iso.isoformat()} "
                      f"period_end={period_end_iso.isoformat()} grace_days={grace_days}")
    return get_subscription(business_id)


def list_active_ai_admin_businesses_missing_subscription():
    """Fix 5 — read-only lookup for the backfill script's dry-run/list mode. Returns businesses
    that are ACTIVE, on an AI Admin package (AI_ADMIN_BASIC/AI_ADMIN_PRO), and have NO row in
    `subscriptions` at all — i.e. exactly the set migration 0014 could not retroactively populate
    (it only creates the empty table). Never touches a creative-only ("NONE" package) business —
    those have no subscription concept at all."""
    return db.query_all(
        "SELECT b.id AS business_id, b.business_name, b.package, b.status, b.created_at "
        "FROM businesses b "
        "LEFT JOIN subscriptions s ON s.business_id = b.id "
        "WHERE b.status = 'ACTIVE' AND b.package IN ('AI_ADMIN_BASIC', 'AI_ADMIN_PRO') "
        "AND s.id IS NULL "
        "ORDER BY b.created_at ASC"
    )


def get_subscription(business_id):
    return db.query_one("SELECT * FROM subscriptions WHERE business_id = ?", (business_id,))


def create_subscription(business_id, plan_key, actor_user_id=None,
                         period_days=DEFAULT_PERIOD_DAYS, grace_days=DEFAULT_GRACE_DAYS):
    """Idempotent: if a subscription row already exists for this business, returns it unchanged
    rather than creating a duplicate or silently resetting its period. Intended to be called
    exactly once, right after a tenant's FIRST verified AI Admin payment/activation (see
    provisioning.activate_tenant()'s hook) — never invents a plan_key; the caller must pass the
    exact package actually paid for."""
    assert plan_key in PLAN_KEYS, f"unknown plan_key {plan_key!r}"
    existing = get_subscription(business_id)
    if existing:
        return existing
    now = _now()
    period_end = _add_days(now, period_days)
    db.insert_returning_id(
        "INSERT INTO subscriptions (business_id, plan_key, status, period_start, period_end, "
        "grace_days) VALUES (?, ?, 'ACTIVE', ?, ?, ?)",
        (business_id, plan_key, now, period_end, grace_days),
    )
    repo.write_audit(actor_user_id, business_id, "SUBSCRIPTION_CREATED",
                      f"plan={plan_key} period_end={period_end} grace_days={grace_days}")
    return get_subscription(business_id)


def renew_subscription(business_id, actor_user_id, period_days=DEFAULT_PERIOD_DAYS, plan_key=None):
    """Records a verified renewal payment. Extends the subscription period and, if the business
    had been SUSPENDED, reactivates it via repo.activate_business() alone — no onboarding, no AI
    Setup re-run, no re-provisioning. Raises ValueError if no subscription row exists yet (caller
    should create_subscription() first — this function never fabricates one, to avoid silently
    starting a billing period the tenant never actually had)."""
    sub = get_subscription(business_id)
    if not sub:
        raise ValueError("subscription_not_found")
    now = _now()
    # Renewing on-time/early keeps whatever time is left on the current period (extend from
    # period_end); renewing late (e.g. after SUSPENDED) starts the fresh period from today instead
    # of compounding a backdated debt. Postgres-safe: sub["period_end"] may be a datetime object
    # (real TIMESTAMPTZ column) or an ISO string (SQLite) — _gt() normalizes both before comparing,
    # never compares a datetime to a string directly.
    base = sub["period_end"] if sub["period_end"] and _gt(sub["period_end"], now) else now
    new_period_end = _add_days(base, period_days)
    new_plan = plan_key or sub["plan_key"]
    was_suspended = sub["status"] == "SUSPENDED"
    reactivated_at = now if was_suspended else sub["reactivated_at"]
    db.execute(
        "UPDATE subscriptions SET status = 'ACTIVE', plan_key = ?, period_end = ?, "
        "grace_started_at = NULL, reminder_stage = NULL, reactivated_at = ?, "
        "suspended_at = suspended_at, updated_at = ? WHERE business_id = ?",
        (new_plan, new_period_end, reactivated_at, now, business_id),
    )
    repo.write_audit(actor_user_id, business_id, "SUBSCRIPTION_RENEWED",
                      f"plan={new_plan} new_period_end={new_period_end} was_suspended={was_suspended}")
    if was_suspended:
        business = repo.get_business(business_id)
        if business and business["status"] == "SUSPENDED":
            repo.activate_business(business_id, actor_user_id)
    return get_subscription(business_id)


def cancel_subscription(business_id, actor_user_id, reason=None):
    """Explicit, admin/owner-initiated cancellation (distinct from an automatic SUSPENDED-for-
    nonpayment state) — does NOT touch businesses.status by itself; a Kilas Admin decides
    separately whether/when to also deactivate the tenant."""
    sub = get_subscription(business_id)
    if not sub:
        raise ValueError("subscription_not_found")
    now = _now()
    db.execute(
        "UPDATE subscriptions SET status = 'CANCELLED', cancelled_at = ?, updated_at = ? "
        "WHERE business_id = ?",
        (now, now, business_id),
    )
    repo.write_audit(actor_user_id, business_id, "SUBSCRIPTION_CANCELLED", reason)
    return get_subscription(business_id)


def run_lifecycle_sweep(now_override=None):
    """Cron-callable, idempotent, safe to call as often as desired (see routes_admin.py's
    /admin/subscriptions/sweep or an equivalent cron-secured trigger — mirrors the existing
    /cron/followups and /cron/owner-notifications pattern in ../app.py). Iterates every
    non-CANCELLED subscription and advances it at most one lifecycle step per call:

      ACTIVE, period_end within a reminder checkpoint (H7/H3/H1) not yet REACHED this period ->
        stays ACTIVE, reminder_stage advances (owner sees this on their dashboard banner — no
        WhatsApp/email is sent by this function; see module docstring's NOTIFICATIONS section).
      ACTIVE, period_end already passed -> GRACE (grace_started_at=now). businesses.status is
        NOT touched here — the tenant keeps working normally through the whole grace window.
      GRACE, grace_days elapsed since grace_started_at -> SUSPENDED +
        repo.deactivate_business() (see module docstring for exactly what that does and does
        NOT touch).

    Returns {"reminded": [(business_id, stage), ...], "graced": [...], "suspended": [...]} — never
    raises for an individual row's failure (one broken row must never stop the sweep from
    processing the rest)."""
    now = now_override or _now()
    reminded, graced, suspended = [], [], []
    rows = db.query_all("SELECT * FROM subscriptions WHERE status IN ('ACTIVE', 'GRACE')")
    for sub in rows:
        try:
            business_id = sub["business_id"]
            if sub["status"] == "ACTIVE":
                # Postgres-safe: sub["period_end"] may be a datetime (real TIMESTAMPTZ column) or
                # an ISO string (SQLite) — _lte() normalizes both, never compares raw values.
                if sub["period_end"] and _lte(sub["period_end"], now):
                    db.execute(
                        "UPDATE subscriptions SET status = 'GRACE', grace_started_at = ?, "
                        "reminder_stage = 'DUE', updated_at = ? WHERE business_id = ?",
                        (now, now, business_id),
                    )
                    repo.write_audit(None, business_id, "SUBSCRIPTION_GRACE_STARTED",
                                      f"period_end={sub['period_end']} grace_days={sub['grace_days']}")
                    graced.append(business_id)
                    continue
                days_remaining = _days_remaining(sub["period_end"], now)
                target_stage = _target_reminder_stage(days_remaining)
                current_rank = REMINDER_STAGE_RANK.get(sub["reminder_stage"] or "", 0)
                target_rank = REMINDER_STAGE_RANK.get(target_stage or "", 0)
                if target_stage and target_rank > current_rank:
                    db.execute(
                        "UPDATE subscriptions SET reminder_stage = ?, "
                        "last_reminder_stage_at = ?, updated_at = ? WHERE business_id = ?",
                        (target_stage, now, now, business_id),
                    )
                    # Fix 6 (accuracy): this event means the reminder STAGE was reached/advanced,
                    # NOT that a WhatsApp/email message was actually delivered — no outbound
                    # notification is sent anywhere in this module today (see module docstring's
                    # NOTIFICATIONS section and get_subscription_banner()'s docstring). Naming this
                    # "...SENT" would misrepresent dashboard-only behavior as delivered messaging.
                    repo.write_audit(None, business_id, "SUBSCRIPTION_REMINDER_STAGE_REACHED",
                                      f"stage={target_stage} period_end={sub['period_end']} "
                                      f"days_remaining={days_remaining}")
                    reminded.append((business_id, target_stage))
            elif sub["status"] == "GRACE":
                grace_deadline = _add_days(sub["grace_started_at"], sub["grace_days"])
                if _lte(grace_deadline, now):
                    db.execute(
                        "UPDATE subscriptions SET status = 'SUSPENDED', suspended_at = ?, "
                        "updated_at = ? WHERE business_id = ?",
                        (now, now, business_id),
                    )
                    repo.write_audit(None, business_id, "SUBSCRIPTION_SUSPENDED",
                                      f"grace_started_at={sub['grace_started_at']} grace_days={sub['grace_days']}")
                    business = repo.get_business(business_id)
                    if business and business["status"] != "SUSPENDED":
                        repo.deactivate_business(business_id, None)
                    suspended.append(business_id)
        except Exception as e:
            print(f"subscription_service.run_lifecycle_sweep: gagal proses business_id={sub.get('business_id')}: {e}")
    return {"reminded": reminded, "graced": graced, "suspended": suspended}


def _days_remaining(period_end, now):
    end_dt = _parse(period_end)
    now_dt = _parse(now)
    if not end_dt or not now_dt:
        return None
    return (end_dt - now_dt).days


def _target_reminder_stage(days_remaining):
    """Returns the MOST URGENT stage ('H1' > 'H3' > 'H7') whose threshold days_remaining has
    reached, or None if not within any reminder window yet. REMINDER_STAGES is ordered
    farthest-to-nearest, so scanning in reverse gives us nearest-first (most urgent first)."""
    if days_remaining is None:
        return None
    for stage, threshold_days in reversed(REMINDER_STAGES):
        if days_remaining <= threshold_days:
            return stage
    return None


def get_subscription_banner(business_id):
    """Owner-facing summary for THIS business's own Client Hub dashboard — the only delivery
    surface this module uses (see module docstring). Returns None if there's no subscription yet
    (e.g. business never reached ACTIVE with an AI Admin package) so templates can skip rendering
    the banner entirely rather than showing a confusing empty state."""
    sub = get_subscription(business_id)
    if not sub:
        return None
    now = _now()
    days_remaining = None
    if sub["period_end"]:
        end_dt = _parse(sub["period_end"])
        now_dt = _parse(now)
        if end_dt and now_dt:
            days_remaining = (end_dt - now_dt).days
    if sub["status"] == "SUSPENDED":
        level, message = "danger", (
            "AI Admin kamu sedang SUSPENDED karena belum ada perpanjangan langganan. "
            "Data, riwayat chat, dan konfigurasi kamu tetap aman — hubungi Kilas Works untuk "
            "aktivasi ulang begitu pembayaran perpanjangan diverifikasi."
        )
    elif sub["status"] == "GRACE":
        level, message = "warning", (
            f"Langganan AI Admin kamu sudah lewat jatuh tempo dan sedang masa tenggang "
            f"({sub['grace_days']} hari) — segera perpanjang supaya AI Admin gak berhenti."
        )
    elif sub["status"] == "ACTIVE" and sub["reminder_stage"] in ("H7", "H3", "H1"):
        level, message = "info", (
            f"Langganan AI Admin kamu ({sub['plan_key']}) akan jatuh tempo dalam "
            f"{max(days_remaining, 0) if days_remaining is not None else '-'} hari."
        )
    else:
        level, message = "ok", None
    return {
        "status": sub["status"],
        "plan_key": sub["plan_key"],
        "period_end": sub["period_end"],
        "days_remaining": days_remaining,
        "level": level,
        "message": message,
    }
