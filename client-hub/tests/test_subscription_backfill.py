"""Fix 5 (production-safety patch) — backfill mechanism test suite for pre-existing ACTIVE AI
Admin tenants missing a subscriptions row (predating migration 0014).

Run with:
    cd client-hub && python3 tests/test_subscription_backfill.py
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("DATABASE_URL", None)

import db  # noqa: E402
import repo  # noqa: E402
import security  # noqa: E402
import subscription_service  # noqa: E402

CLIENT_HUB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(CLIENT_HUB_DIR, "scripts", "backfill_subscriptions.py")


def reset_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    db._local.conn = None
    db.init_schema()


def _make_admin():
    admin_id = repo.create_user(f"admin_{os.urandom(4).hex()}@kilasworks.id",
                                 security.hash_password("adminpass123"), role="KILAS_ADMIN")
    return db.query_one("SELECT * FROM users WHERE id = ?", (admin_id,))


def _make_active_business(package, name="Legacy Biz"):
    """Simulates a PRE-EXISTING tenant that was activated before migration 0014 — ACTIVE status,
    no subscriptions row at all, exactly the scenario Fix 5 backfills."""
    user_id = repo.create_user(f"owner_{os.urandom(4).hex()}@test.com", security.hash_password("password123"))
    business_id = repo.create_business(user_id, name, package=package)
    db.execute("UPDATE businesses SET status = 'ACTIVE' WHERE id = ?", (business_id,))
    return business_id


def _run_script(*args):
    result = subprocess.run(
        [sys.executable, SCRIPT_PATH, *args],
        cwd=CLIENT_HUB_DIR, capture_output=True, text=True, timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# 1. Dry-run / list finds exactly the eligible businesses, nothing else.
# ---------------------------------------------------------------------------
def test_list_finds_eligible_missing_subscription_tenants():
    reset_db()
    bid_basic = _make_active_business("AI_ADMIN_BASIC", "Kopi Legacy Basic")
    bid_pro = _make_active_business("AI_ADMIN_PRO", "Salon Legacy Pro")
    rows = subscription_service.list_active_ai_admin_businesses_missing_subscription()
    ids = [r["business_id"] for r in rows]
    assert bid_basic in ids and bid_pro in ids
    print("test_list_finds_eligible_missing_subscription_tenants OK")


def test_list_ignores_businesses_that_already_have_subscription_rows():
    reset_db()
    admin = _make_admin()
    bid_has_sub = _make_active_business("AI_ADMIN_BASIC", "Already Backfilled")
    subscription_service.create_subscription(bid_has_sub, "ai_admin_basic", actor_user_id=admin["id"])
    bid_missing = _make_active_business("AI_ADMIN_PRO", "Still Missing")

    rows = subscription_service.list_active_ai_admin_businesses_missing_subscription()
    ids = [r["business_id"] for r in rows]
    assert bid_has_sub not in ids, "a business that already has a subscription row must not be listed"
    assert bid_missing in ids
    print("test_list_ignores_businesses_that_already_have_subscription_rows OK")


def test_list_ignores_non_ai_admin_and_non_active_businesses():
    reset_db()
    bid_none_pkg = _make_active_business("NONE", "Creative Only Biz")
    user_id = repo.create_user(f"owner_{os.urandom(4).hex()}@test.com", security.hash_password("password123"))
    bid_not_active = repo.create_business(user_id, "Still Onboarding", package="AI_ADMIN_PRO")
    # bid_not_active stays in its default (non-ACTIVE) status — never touched.

    rows = subscription_service.list_active_ai_admin_businesses_missing_subscription()
    ids = [r["business_id"] for r in rows]
    assert bid_none_pkg not in ids, "a creative-only (package=NONE) business must never be listed"
    assert bid_not_active not in ids, "a non-ACTIVE business must never be listed"
    print("test_list_ignores_non_ai_admin_and_non_active_businesses OK")


# ---------------------------------------------------------------------------
# 2. Explicit write only happens with a real plan + explicit dates; dry-run never writes.
# ---------------------------------------------------------------------------
def test_explicit_backfill_creates_correct_subscription():
    reset_db()
    admin = _make_admin()
    bid = _make_active_business("AI_ADMIN_PRO", "Legacy Tenant")
    sub = subscription_service.create_subscription_with_explicit_period(
        bid, "ai_admin_pro", "2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00",
        actor_user_id=admin["id"], grace_days=3,
    )
    assert sub["plan_key"] == "ai_admin_pro"
    assert sub["status"] == "ACTIVE"
    assert sub["period_start"].startswith("2026-01-01")
    assert sub["period_end"].startswith("2026-02-01")
    audit = db.query_all("SELECT * FROM audit_log WHERE business_id = ? AND action = 'SUBSCRIPTION_BACKFILLED'", (bid,))
    assert len(audit) == 1
    print("test_explicit_backfill_creates_correct_subscription OK")


def test_explicit_backfill_is_idempotent_no_overwrite():
    reset_db()
    admin = _make_admin()
    bid = _make_active_business("AI_ADMIN_BASIC", "Legacy Tenant 2")
    first = subscription_service.create_subscription_with_explicit_period(
        bid, "ai_admin_basic", "2026-01-01", "2026-02-01", actor_user_id=admin["id"],
    )
    second = subscription_service.create_subscription_with_explicit_period(
        bid, "ai_admin_basic", "2099-01-01", "2099-02-01", actor_user_id=admin["id"],
    )
    assert second["period_start"] == first["period_start"], \
        "a second backfill attempt must NOT overwrite an already-existing subscription row"
    print("test_explicit_backfill_is_idempotent_no_overwrite OK")


def test_explicit_backfill_requires_parseable_dates():
    reset_db()
    admin = _make_admin()
    bid = _make_active_business("AI_ADMIN_BASIC", "Bad Dates Biz")
    try:
        subscription_service.create_subscription_with_explicit_period(
            bid, "ai_admin_basic", "not-a-date", "also-not-a-date", actor_user_id=admin["id"],
        )
        assert False, "must raise on unparseable dates, never silently guess"
    except ValueError as e:
        assert "invalid_period" in str(e)
    assert subscription_service.get_subscription(bid) is None
    print("test_explicit_backfill_requires_parseable_dates OK")


# ---------------------------------------------------------------------------
# Micro-patch — period ordering / grace_days validation
# ---------------------------------------------------------------------------
def test_explicit_backfill_rejects_reversed_period():
    reset_db()
    admin = _make_admin()
    bid = _make_active_business("AI_ADMIN_BASIC", "Reversed Period Biz")
    try:
        subscription_service.create_subscription_with_explicit_period(
            bid, "ai_admin_basic", "2026-02-01", "2026-01-01", actor_user_id=admin["id"],
        )
        assert False, "must reject period_end before period_start"
    except ValueError as e:
        assert "invalid_period" in str(e)
    assert subscription_service.get_subscription(bid) is None
    print("test_explicit_backfill_rejects_reversed_period OK")


def test_explicit_backfill_rejects_equal_period():
    reset_db()
    admin = _make_admin()
    bid = _make_active_business("AI_ADMIN_BASIC", "Equal Period Biz")
    try:
        subscription_service.create_subscription_with_explicit_period(
            bid, "ai_admin_basic", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
            actor_user_id=admin["id"],
        )
        assert False, "must reject period_end equal to period_start"
    except ValueError as e:
        assert "invalid_period" in str(e)
    assert subscription_service.get_subscription(bid) is None
    print("test_explicit_backfill_rejects_equal_period OK")


def test_explicit_backfill_accepts_valid_forward_period():
    reset_db()
    admin = _make_admin()
    bid = _make_active_business("AI_ADMIN_BASIC", "Valid Period Biz")
    sub = subscription_service.create_subscription_with_explicit_period(
        bid, "ai_admin_basic", "2026-01-01", "2026-02-01", actor_user_id=admin["id"],
    )
    assert sub["status"] == "ACTIVE"
    assert sub["period_end"] > sub["period_start"]
    print("test_explicit_backfill_accepts_valid_forward_period OK")


def test_explicit_backfill_rejects_negative_grace_days():
    reset_db()
    admin = _make_admin()
    bid = _make_active_business("AI_ADMIN_BASIC", "Negative Grace Biz")
    try:
        subscription_service.create_subscription_with_explicit_period(
            bid, "ai_admin_basic", "2026-01-01", "2026-02-01", actor_user_id=admin["id"],
            grace_days=-1,
        )
        assert False, "must reject negative grace_days"
    except ValueError as e:
        assert "invalid_grace_days" in str(e)
    assert subscription_service.get_subscription(bid) is None
    print("test_explicit_backfill_rejects_negative_grace_days OK")



# 3. CLI script itself — dry-run vs --confirm, end to end via subprocess (real script invocation).
# ---------------------------------------------------------------------------
def test_cli_list_mode_is_read_only():
    reset_db()
    bid = _make_active_business("AI_ADMIN_PRO", "CLI List Test Biz")
    rc, stdout, stderr = _run_script("--list")
    assert rc == 0, stderr
    assert "CLI List Test Biz" in stdout
    assert str(bid) in stdout
    # No secret/token-looking content should ever appear.
    assert "TOKEN" not in stdout.upper() or "TEST_WA_TOKEN" not in stdout
    assert subscription_service.get_subscription(bid) is None, "--list must never write"
    print("test_cli_list_mode_is_read_only OK")


def test_cli_without_confirm_does_not_write():
    reset_db()
    bid = _make_active_business("AI_ADMIN_BASIC", "CLI Dry Run Biz")
    rc, stdout, stderr = _run_script(
        "--business-id", str(bid), "--period-start", "2026-01-01", "--period-end", "2026-02-01",
    )
    assert rc == 0, stderr
    assert "DRY RUN" in stdout
    assert subscription_service.get_subscription(bid) is None, "without --confirm, nothing must be written"
    print("test_cli_without_confirm_does_not_write OK")


def test_cli_with_confirm_writes_correct_subscription():
    reset_db()
    bid = _make_active_business("AI_ADMIN_PRO", "CLI Confirm Biz")
    rc, stdout, stderr = _run_script(
        "--business-id", str(bid), "--period-start", "2026-03-01", "--period-end", "2026-04-01",
        "--confirm",
    )
    assert rc == 0, stderr
    assert "OK" in stdout
    sub = subscription_service.get_subscription(bid)
    assert sub is not None
    assert sub["plan_key"] == "ai_admin_pro"
    assert sub["period_start"].startswith("2026-03-01")
    print("test_cli_with_confirm_writes_correct_subscription OK")


def test_cli_refuses_non_active_business():
    reset_db()
    user_id = repo.create_user(f"owner_{os.urandom(4).hex()}@test.com", security.hash_password("password123"))
    bid = repo.create_business(user_id, "Not Active Biz", package="AI_ADMIN_PRO")
    rc, stdout, stderr = _run_script(
        "--business-id", str(bid), "--period-start", "2026-01-01", "--period-end", "2026-02-01",
        "--confirm",
    )
    assert rc != 0
    assert "ACTIVE" in stdout
    assert subscription_service.get_subscription(bid) is None
    print("test_cli_refuses_non_active_business OK")


def test_cli_refuses_non_ai_admin_package():
    reset_db()
    bid = _make_active_business("NONE", "Creative Only CLI Biz")
    rc, stdout, stderr = _run_script(
        "--business-id", str(bid), "--period-start", "2026-01-01", "--period-end", "2026-02-01",
        "--confirm",
    )
    assert rc != 0
    assert subscription_service.get_subscription(bid) is None
    print("test_cli_refuses_non_ai_admin_package OK")


def test_repeated_cli_run_is_safe():
    reset_db()
    bid = _make_active_business("AI_ADMIN_BASIC", "Repeat Run Biz")
    rc1, stdout1, _ = _run_script(
        "--business-id", str(bid), "--period-start", "2026-01-01", "--period-end", "2026-02-01",
        "--confirm",
    )
    assert rc1 == 0
    sub_after_first = subscription_service.get_subscription(bid)

    rc2, stdout2, _ = _run_script(
        "--business-id", str(bid), "--period-start", "2099-01-01", "--period-end", "2099-02-01",
        "--confirm",
    )
    assert rc2 == 0
    assert "already has a subscription row" in stdout2
    sub_after_second = subscription_service.get_subscription(bid)
    assert sub_after_second == sub_after_first, "re-running the backfill must never overwrite an existing row"
    print("test_repeated_cli_run_is_safe OK")


if __name__ == "__main__":
    test_list_finds_eligible_missing_subscription_tenants()
    test_list_ignores_businesses_that_already_have_subscription_rows()
    test_list_ignores_non_ai_admin_and_non_active_businesses()
    test_explicit_backfill_creates_correct_subscription()
    test_explicit_backfill_is_idempotent_no_overwrite()
    test_explicit_backfill_requires_parseable_dates()
    test_explicit_backfill_rejects_reversed_period()
    test_explicit_backfill_rejects_equal_period()
    test_explicit_backfill_accepts_valid_forward_period()
    test_explicit_backfill_rejects_negative_grace_days()
    test_cli_list_mode_is_read_only()
    test_cli_without_confirm_does_not_write()
    test_cli_with_confirm_writes_correct_subscription()
    test_cli_refuses_non_active_business()
    test_cli_refuses_non_ai_admin_package()
    test_repeated_cli_run_is_safe()
    print("ALL SUBSCRIPTION BACKFILL TESTS PASSED")
