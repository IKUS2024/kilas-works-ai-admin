"""K7 KOPI legacy AI Admin payment fix + UI cleanup regression suite.

K7 KOPI FINDING: has_verified_ai_admin_payment() previously matched a VERIFIED payment against
EITHER catalog_key ('ai_admin_basic' OR 'ai_admin_pro'), regardless of the business's CURRENT
`package` column. Confirmed reachable via routes_admin.py's admin-only
POST /business/<id>/package -> repo.set_business_package(), which changes a business's package
freely without touching any existing projects/invoices/payments (by design — those stay as
historical records). A business currently on AI_ADMIN_BASIC with an OLD VERIFIED payment against
an ai_admin_pro project would have incorrectly passed the activation gate on the strength of a
payment for a DIFFERENT tier. Fixed to require a VERIFIED payment matching the CURRENT package
specifically — see payment_service.has_verified_ai_admin_payment()'s own docstring.

Run with:
    cd client-hub && python3 tests/test_k7_kopi_legacy_payment_and_ui_cleanup.py
"""
import os
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
import catalog_service  # noqa: E402
import projects_repo  # noqa: E402
import payment_service  # noqa: E402
import display_labels  # noqa: E402
import app as client_hub_app  # noqa: E402

FLASK_APP = client_hub_app.app
FLASK_APP.testing = True


def fresh_client():
    return FLASK_APP.test_client()


def reset_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    db._local.conn = None
    db.init_schema()
    catalog_service.seed_catalog_if_needed()


def _make_admin():
    admin_id = repo.create_user(f"admin_{os.urandom(4).hex()}@kilasworks.id",
                                 security.hash_password("adminpass123"), role="KILAS_ADMIN")
    return db.query_one("SELECT * FROM users WHERE id = ?", (admin_id,))


def _login_admin(client, admin):
    client.post("/login", data={"email": admin["email"], "password": "adminpass123"})


def _login_owner(client, email, password="password123"):
    client.post("/login", data={"email": email, "password": password})


def _make_owner_and_business(name, email, package="AI_ADMIN_BASIC"):
    uid = repo.create_user(email, security.hash_password("password123"))
    bid = repo.create_business(uid, name, package=package)
    return uid, bid


def _create_verified_payment(business_id, catalog_key, actor_user_id):
    """Directly builds a project -> invoice -> VERIFIED payment chain for catalog_key, bypassing
    the full upload/review workflow (already covered by other test files) — this test is
    specifically about has_verified_ai_admin_payment()'s own matching logic."""
    item = catalog_service.get_catalog_item(catalog_key)
    project_id = projects_repo.create_fixed_price_project(business_id, item, actor_user_id)
    invoice_id = payment_service.checkout(project_id, business_id, actor_user_id)
    payment_row = db.query_one("SELECT id FROM payments WHERE invoice_id = ?", (invoice_id,))
    db.execute(
        "UPDATE payments SET status = 'VERIFIED', verified_by_user_id = ? WHERE id = ?",
        (actor_user_id, payment_row["id"]),
    )
    db.execute("UPDATE invoices SET status = 'PAID' WHERE id = ?", (invoice_id,))
    return project_id, invoice_id, payment_row["id"]


# ---------------------------------------------------------------------------
# K7 KOPI — the actual bug scenario, proven fixed.
# ---------------------------------------------------------------------------
def test_k7_current_basic_with_only_historical_pro_payment_does_not_satisfy_gate():
    """Current package = BASIC. Historical VERIFIED PRO payment exists. No valid current BASIC
    payment. Expected: has_verified_ai_admin_payment() returns False — the historical PRO payment
    must NEVER incorrectly satisfy the current BASIC activation/payment gate."""
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("K7 Kopi", "k7kopi@test.com", package="AI_ADMIN_PRO")

    # Historical: business was Pro, paid for Pro, payment verified.
    _create_verified_payment(bid, "ai_admin_pro", admin["id"])

    # Admin later corrects/changes the package to Basic (the exact reachable path: POST
    # /business/<id>/package -> repo.set_business_package() — never touches the old payment).
    repo.set_business_package(bid, "AI_ADMIN_BASIC", actor_user_id=admin["id"])

    business = repo.get_business(bid)
    assert business["package"] == "AI_ADMIN_BASIC"

    # The historical projects/payments/audit rows are untouched — proving nothing was deleted.
    old_project_still_exists = db.query_one(
        "SELECT id FROM projects WHERE business_id = ? AND catalog_key = 'ai_admin_pro'", (bid,))
    assert old_project_still_exists is not None, "historical project must never be deleted"

    result = payment_service.has_verified_ai_admin_payment(bid)
    assert result is False, \
        "BUG: a historical PRO payment incorrectly satisfies the current BASIC activation gate"
    print("test_k7_current_basic_with_only_historical_pro_payment_does_not_satisfy_gate OK")


def test_k7_reverse_current_pro_with_only_historical_basic_payment_does_not_satisfy_gate():
    """The reverse case: current package = PRO, only a historical BASIC payment exists."""
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Reverse Biz", "reversebiz@test.com", package="AI_ADMIN_BASIC")
    _create_verified_payment(bid, "ai_admin_basic", admin["id"])
    repo.set_business_package(bid, "AI_ADMIN_PRO", actor_user_id=admin["id"])

    result = payment_service.has_verified_ai_admin_payment(bid)
    assert result is False, \
        "BUG: a historical BASIC payment incorrectly satisfies the current PRO activation gate"
    print("test_k7_reverse_current_pro_with_only_historical_basic_payment_does_not_satisfy_gate OK")


def test_k7_current_package_with_matching_verified_payment_still_works():
    """Regression guard for the NORMAL case: a business that paid for its CURRENT package tier
    must still correctly pass the gate — the fix must not break the common, correct case."""
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Normal Biz", "normalbiz@test.com", package="AI_ADMIN_PRO")
    _create_verified_payment(bid, "ai_admin_pro", admin["id"])

    assert payment_service.has_verified_ai_admin_payment(bid) is True
    print("test_k7_current_package_with_matching_verified_payment_still_works OK")


def test_k7_package_changed_then_new_matching_payment_satisfies_gate():
    """A business whose package changed AND who then paid for the NEW tier correctly passes —
    proving the fix requires a NEW payment, not that it's impossible to ever activate after a
    package change."""
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Upgraded Biz", "upgradedbiz@test.com", package="AI_ADMIN_BASIC")
    _create_verified_payment(bid, "ai_admin_basic", admin["id"])
    repo.set_business_package(bid, "AI_ADMIN_PRO", actor_user_id=admin["id"])
    assert payment_service.has_verified_ai_admin_payment(bid) is False  # old Basic payment insufficient

    _create_verified_payment(bid, "ai_admin_pro", admin["id"])
    assert payment_service.has_verified_ai_admin_payment(bid) is True  # new Pro payment satisfies it
    print("test_k7_package_changed_then_new_matching_payment_satisfies_gate OK")


def test_k7_package_none_never_satisfies_gate_even_with_stray_project():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("None Biz", "nonebiz@test.com", package="AI_ADMIN_BASIC")
    _create_verified_payment(bid, "ai_admin_basic", admin["id"])
    repo.set_business_package(bid, "NONE", actor_user_id=admin["id"])
    assert payment_service.has_verified_ai_admin_payment(bid) is False
    print("test_k7_package_none_never_satisfies_gate_even_with_stray_project OK")


def test_k7_audit_history_not_rewritten_by_the_fix():
    """The fix must never touch audit_log rows — only change what a READ function returns."""
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Audit Biz", "auditbiz@test.com", package="AI_ADMIN_PRO")
    _create_verified_payment(bid, "ai_admin_pro", admin["id"])
    audit_before = repo.get_audit_log(bid)
    repo.set_business_package(bid, "AI_ADMIN_BASIC", actor_user_id=admin["id"])
    payment_service.has_verified_ai_admin_payment(bid)  # calling the (fixed) read function
    audit_after = repo.get_audit_log(bid)
    # Every row present before is still present after (package_changed adds ONE new row; nothing
    # is deleted or rewritten).
    before_ids = {a["id"] for a in audit_before}
    after_ids = {a["id"] for a in audit_after}
    assert before_ids.issubset(after_ids), "BUG: an existing audit row was removed/altered"
    print("test_k7_audit_history_not_rewritten_by_the_fix OK")


# ---------------------------------------------------------------------------
# UI cleanup — Tests A-F.
# ---------------------------------------------------------------------------
def test_A_none_field_renders_belum_diisi():
    reset_db()
    uid, bid = _make_owner_and_business("Biz A", "uia@test.com")
    # No business_profiles row at all yet -> every field is genuinely missing.
    client = fresh_client()
    _login_owner(client, "uia@test.com")
    resp = client.get(f"/business/{bid}/review")
    body = resp.data.decode()
    assert "None" not in body, "raw Python None must never render on the review page"
    assert "Belum diisi" in body
    print("test_A_none_field_renders_belum_diisi OK")


def test_B_missing_fields_warning_uses_human_labels():
    reset_db()
    uid, bid = _make_owner_and_business("Biz B", "uib@test.com")
    client = fresh_client()
    _login_owner(client, "uib@test.com")
    resp = client.get(f"/business/{bid}/review")
    body = resp.data.decode()
    assert "primary_language" not in body
    assert "customer_salutation" not in body
    assert "Bahasa utama" in body
    assert "Sapaan untuk pelanggan" in body
    assert "Lengkapi" in body  # the natural full-sentence format
    print("test_B_missing_fields_warning_uses_human_labels OK")


def test_C_customer_dashboard_no_raw_enum_codes():
    reset_db()
    uid, bid = _make_owner_and_business("Biz C", "uic@test.com", package="AI_ADMIN_PRO")
    db.execute("UPDATE businesses SET status = 'ONBOARDING' WHERE id = ?", (bid,))
    client = fresh_client()
    _login_owner(client, "uic@test.com")
    resp = client.get("/dashboard")
    body = resp.data.decode()
    # Check the raw code never appears as VISIBLE element text (">AI_ADMIN_PRO<") — an HTML
    # value="AI_ADMIN_PRO" form attribute (needed for the "Buat Business Baru" package dropdown to
    # actually submit correctly) is expected and fine; that dropdown's VISIBLE text already reads
    # "AI Admin Pro — Rp499.000/bulan" etc., which is what a real user sees.
    assert ">AI_ADMIN_PRO<" not in body
    assert ">ONBOARDING<" not in body
    assert "AI Admin Pro" in body
    assert "Sedang setup" in body
    print("test_C_customer_dashboard_no_raw_enum_codes OK")


def test_D_audit_actions_render_human_friendly():
    assert display_labels.humanize_audit_action("PROJECT_CREATED") == "Pesanan dibuat"
    assert display_labels.humanize_audit_action("PROJECT_STATUS_CHANGED") == "Status pesanan diperbarui"
    assert display_labels.humanize_audit_action("business_upgraded_to_ai_admin") == "Paket AI Admin diaktifkan"
    assert display_labels.humanize_audit_detail("fixed-price: AI Admin Pro (project_id=1)") == "Pesanan AI Admin Pro dibuat"
    assert display_labels.humanize_audit_detail("checkout: INV-2026-000001") == "Invoice INV-2026-000001 dibuat"
    assert display_labels.humanize_audit_detail("package=NONE") == "Belum memiliki paket AI Admin"
    print("test_D_audit_actions_render_human_friendly OK")


def test_D_admin_review_page_humanizes_audit_log():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz D", "uid@test.com", package="AI_ADMIN_BASIC")
    _create_verified_payment(bid, "ai_admin_basic", admin["id"])
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get(f"/admin/business/{bid}")
    body = resp.data.decode()
    assert "PROJECT_CREATED" not in body
    assert "Pesanan dibuat" in body
    print("test_D_admin_review_page_humanizes_audit_log OK")


def test_E_wizard_and_review_no_raw_field_names():
    reset_db()
    uid, bid = _make_owner_and_business("Biz E", "uie@test.com")
    client = fresh_client()
    _login_owner(client, "uie@test.com")
    resp1 = client.get(f"/business/{bid}/wizard/style")
    body1 = resp1.data.decode()
    assert "primary_language</label>" not in body1 and ">primary_language<" not in body1
    assert "customer_salutation</label>" not in body1 and ">customer_salutation<" not in body1
    assert "Bahasa utama" in body1
    assert "Sapaan untuk pelanggan" in body1

    resp2 = client.get(f"/business/{bid}/review")
    body2 = resp2.data.decode()
    assert ">primary_language<" not in body2
    assert ">customer_salutation<" not in body2
    print("test_E_wizard_and_review_no_raw_field_names OK")


def test_F_unknown_code_falls_back_to_readable_text():
    assert display_labels.humanize_status("SOME_NEW_STATUS_NOT_YET_MAPPED", "project") == "Some New Status Not Yet Mapped"
    assert display_labels.humanize_package("SOME_FUTURE_PACKAGE") == "Some Future Package"
    assert display_labels.humanize_audit_action("some_new_event_type") == "Some new event type"
    # Never silently disappears (empty string) for a genuinely unmapped code.
    assert display_labels.humanize_status("X", "project") != ""
    print("test_F_unknown_code_falls_back_to_readable_text OK")


if __name__ == "__main__":
    test_k7_current_basic_with_only_historical_pro_payment_does_not_satisfy_gate()
    test_k7_reverse_current_pro_with_only_historical_basic_payment_does_not_satisfy_gate()
    test_k7_current_package_with_matching_verified_payment_still_works()
    test_k7_package_changed_then_new_matching_payment_satisfies_gate()
    test_k7_package_none_never_satisfies_gate_even_with_stray_project()
    test_k7_audit_history_not_rewritten_by_the_fix()
    test_A_none_field_renders_belum_diisi()
    test_B_missing_fields_warning_uses_human_labels()
    test_C_customer_dashboard_no_raw_enum_codes()
    test_D_audit_actions_render_human_friendly()
    test_D_admin_review_page_humanizes_audit_log()
    test_E_wizard_and_review_no_raw_field_names()
    test_F_unknown_code_falls_back_to_readable_text()
    print("ALL K7 KOPI + UI CLEANUP TESTS PASSED")
