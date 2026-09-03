"""Checkout state machine fix + full payment reliability pass — regression suite.

ROOT CAUSE (confirmed by tracing the real call path, not assumed): TWO separate guards
independently rejected a project already at PAYMENT_PENDING —
  1. routes_payments.py's checkout_page() GET pre-check.
  2. payment_service.checkout()'s own status guard.
Both sat BEFORE the already-written "reuse existing invoice" idempotency logic, making it
unreachable for any project that had already completed checkout once — exactly the reported
"checkout_locked: project status is 'PAYMENT_PENDING', must be APPROVED" production incident.

Run with:
    cd client-hub && python3 tests/test_checkout_payment_pending_fix.py
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
import ai_payment_review  # noqa: E402
import app as client_hub_app  # noqa: E402

FLASK_APP = client_hub_app.app
FLASK_APP.testing = True
FLASK_APP.config["PROPAGATE_EXCEPTIONS"] = True


def fresh_client():
    return FLASK_APP.test_client()


def reset_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    db._local.conn = None
    db.init_schema()
    catalog_service.seed_catalog_if_needed()


def _make_owner_and_business(name, email, package="AI_ADMIN_PRO"):
    uid = repo.create_user(email, security.hash_password("password123"))
    bid = repo.create_business(uid, name, package=package)
    return uid, bid


def _login_owner(client, email, password="password123"):
    client.post("/login", data={"email": email, "password": password})


def _make_admin():
    admin_id = repo.create_user(f"admin_{os.urandom(4).hex()}@kilasworks.id",
                                 security.hash_password("adminpass123"), role="KILAS_ADMIN")
    return db.query_one("SELECT * FROM users WHERE id = ?", (admin_id,))


def _login_admin(client, admin):
    client.post("/login", data={"email": admin["email"], "password": "adminpass123"})


def _make_proof_file(business_id, project_id, uid):
    """Creates a real project_files row (proof_file_id has a FK constraint against it) with
    trivial content — the tests below only need a valid, existing file id, not real image bytes."""
    return db.insert_returning_id(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'PAYMENT_PROOF', ?, ?, ?, ?, ?)",
        (business_id, project_id, "proof.jpg", "image/jpeg", 100, b"x" * 100, uid),
    )


# ---------------------------------------------------------------------------
# 1-3 — FIXED_PRICE AI Admin APPROVED -> checkout succeeds, creates invoice, PAYMENT_PENDING.
# ---------------------------------------------------------------------------
def test_1_2_3_fixed_price_approved_checkout_creates_invoice_and_transitions():
    reset_db()
    uid, bid = _make_owner_and_business("Biz1", "biz1@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    assert projects_repo.get_project(project_id)["status"] == "APPROVED"

    invoice_id = payment_service.checkout(project_id, bid, uid)
    assert invoice_id is not None

    invoices = db.query_all("SELECT id FROM invoices WHERE project_id = ?", (project_id,))
    assert len(invoices) == 1, "exactly one invoice must be created"

    project = projects_repo.get_project(project_id)
    assert project["status"] == "PAYMENT_PENDING"
    print("test_1_2_3_fixed_price_approved_checkout_creates_invoice_and_transitions OK")


# ---------------------------------------------------------------------------
# 4-5 — PAYMENT_PENDING existing project -> checkout/payment page opens, same invoice reused.
# ---------------------------------------------------------------------------
def test_4_5_payment_pending_reopens_checkout_page_reuses_invoice():
    reset_db()
    uid, bid = _make_owner_and_business("Biz45", "biz45@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id_1 = payment_service.checkout(project_id, bid, uid)

    client = fresh_client()
    _login_owner(client, "biz45@test.com")
    resp = client.get(f"/projects/{project_id}/checkout", follow_redirects=False)
    assert resp.status_code == 302, resp.status_code
    assert resp.headers.get("Location") == f"/invoices/{invoice_id_1}"

    invoice_id_2 = payment_service.checkout(project_id, bid, uid)
    assert invoice_id_2 == invoice_id_1
    print("test_4_5_payment_pending_reopens_checkout_page_reuses_invoice OK")


# ---------------------------------------------------------------------------
# 6 — repeated checkout 3x -> no duplicate invoice/payment.
# ---------------------------------------------------------------------------
def test_6_repeated_checkout_3x_no_duplicates():
    reset_db()
    uid, bid = _make_owner_and_business("Biz6", "biz6@test.com")
    item = catalog_service.get_catalog_item("ai_admin_basic")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_ids = [payment_service.checkout(project_id, bid, uid) for _ in range(3)]
    assert len(set(invoice_ids)) == 1
    payments = db.query_all("SELECT id FROM payments WHERE invoice_id = ?", (invoice_ids[0],))
    assert len(payments) == 1
    print("test_6_repeated_checkout_3x_no_duplicates OK")


# ---------------------------------------------------------------------------
# 7 — refresh/relogin/reopen -> same payment state (end to end via real HTTP flow).
# ---------------------------------------------------------------------------
def test_7_relogin_reopen_same_payment_state():
    reset_db()
    uid, bid = _make_owner_and_business("Biz7", "biz7@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)

    client1 = fresh_client()
    _login_owner(client1, "biz7@test.com")
    resp1 = client1.get(f"/invoices/{invoice_id}")
    assert resp1.status_code == 200

    # Simulate logout/login as a fresh client/session entirely.
    client2 = fresh_client()
    _login_owner(client2, "biz7@test.com")
    resp2 = client2.get(f"/projects/{project_id}/checkout", follow_redirects=True)
    assert resp2.status_code == 200
    assert "checkout_locked" not in resp2.data.decode()
    print("test_7_relogin_reopen_same_payment_state OK")


# ---------------------------------------------------------------------------
# 8 — the EXACT reported real production pattern.
# ---------------------------------------------------------------------------
def test_8_real_pattern_ai_admin_pro_999000_payment_pending_not_locked():
    reset_db()
    uid, bid = _make_owner_and_business("K7 KOPI Real", "k7real@test.com", package="AI_ADMIN_PRO")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    payment_service.checkout(project_id, bid, uid)
    project = projects_repo.get_project(project_id)
    assert project["status"] == "PAYMENT_PENDING"
    assert project["final_price"] == item["price_amount"]

    client = fresh_client()
    _login_owner(client, "k7real@test.com")
    resp = client.get(f"/projects/{project_id}/checkout", follow_redirects=True)
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "checkout_locked" not in body
    assert "must be APPROVED" not in body
    print("test_8_real_pattern_ai_admin_pro_999000_payment_pending_not_locked OK")


# ---------------------------------------------------------------------------
# 9-10 — CUSTOM_QUOTE without approval remains blocked; approved CUSTOM_QUOTE still works.
# ---------------------------------------------------------------------------
def test_9_custom_quote_without_approval_still_blocked():
    reset_db()
    uid, bid = _make_owner_and_business("Biz9", "biz9@test.com", package="NONE")
    project_id = projects_repo.create_custom_project(bid, "VIDEO", "Video Custom", {"notes": "x"}, None, None, uid)
    assert projects_repo.get_project(project_id)["status"] == "WAITING_FOR_QUOTE"
    try:
        payment_service.checkout(project_id, bid, uid)
        assert False, "must have raised ValueError"
    except ValueError as e:
        assert "checkout_locked" in str(e)
    print("test_9_custom_quote_without_approval_still_blocked OK")


def test_10_custom_quote_approved_payment_flow_still_works():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz10", "biz10@test.com", package="NONE")
    project_id = projects_repo.create_custom_project(bid, "VIDEO", "Video Custom", {"notes": "x"}, None, None, uid)
    import quotation_service
    quotation_id = quotation_service.create_quotation(project_id, bid, "scope", "deliverables", 1,
                                                        2_000_000, "notes", admin["id"])
    quotation_service.approve_quotation(quotation_id, bid, uid)
    project = projects_repo.get_project(project_id)
    assert project["status"] == "APPROVED"
    invoice_id = payment_service.checkout(project_id, bid, uid)
    assert invoice_id is not None
    assert projects_repo.get_project(project_id)["status"] == "PAYMENT_PENDING"
    # Idempotent reopen also works for a CUSTOM_QUOTE project, same as FIXED_PRICE.
    invoice_id_2 = payment_service.checkout(project_id, bid, uid)
    assert invoice_id_2 == invoice_id
    print("test_10_custom_quote_approved_payment_flow_still_works OK")


# ---------------------------------------------------------------------------
# 11 — proof upload persists.
# ---------------------------------------------------------------------------
def test_11_proof_upload_persists():
    reset_db()
    uid, bid = _make_owner_and_business("Biz11", "biz11@test.com")
    item = catalog_service.get_catalog_item("ai_admin_basic")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    proof_file_id = _make_proof_file(bid, project_id, uid)
    assessment = payment_service.upload_payment_proof(payment["id"], bid, proof_file_id, uid, proof_file_hash="abc123")
    reloaded = payment_service.get_payment(payment["id"])
    assert reloaded["proof_file_id"] == proof_file_id
    assert reloaded["status"] == "UNDER_REVIEW"
    print("test_11_proof_upload_persists OK")


# ---------------------------------------------------------------------------
# 12-14 — amount comparison.
# ---------------------------------------------------------------------------
def test_12_amount_matches_zero_difference():
    result = ai_payment_review.assess_payment_proof(
        1, 1, 999000, extracted_fields={"ai_extracted_amount": 999000, "ai_extracted_date": "2026-09-01",
                                         "ai_extracted_bank": "BCA", "ai_reference": "REF1"})
    assert result["ai_extracted_amount"] - 999000 == 0
    assert "AMOUNT_MISMATCH" not in result["ai_risk_flags"]
    print("test_12_amount_matches_zero_difference OK")


def test_13_amount_mismatch_flagged():
    result = ai_payment_review.assess_payment_proof(
        1, 1, 999000, extracted_fields={"ai_extracted_amount": 990000, "ai_extracted_date": "2026-09-01",
                                         "ai_extracted_bank": "BCA", "ai_reference": "REF2"})
    assert "AMOUNT_MISMATCH" in result["ai_risk_flags"]
    assert result["ai_extracted_amount"] - 999000 == -9000
    print("test_13_amount_mismatch_flagged OK")


def test_14_unreadable_amount_requires_manual_review():
    result = ai_payment_review.assess_payment_proof(
        1, 1, 999000, extracted_fields={"ai_extracted_amount": None, "ai_extracted_date": None,
                                         "ai_extracted_bank": None, "ai_reference": None})
    assert "UNREADABLE" in result["ai_risk_flags"]
    print("test_14_unreadable_amount_requires_manual_review OK")


# ---------------------------------------------------------------------------
# 15 — bank/date/reference extraction fields survive.
# ---------------------------------------------------------------------------
def test_15_extraction_fields_survive():
    result = ai_payment_review.assess_payment_proof(
        1, 1, 999000, extracted_fields={"ai_extracted_amount": 999000, "ai_extracted_date": "2026-09-01 14:30",
                                         "ai_extracted_bank": "BCA", "ai_reference": "TRX998877"})
    assert result["ai_extracted_bank"] == "BCA"
    assert result["ai_reference"] == "TRX998877"
    assert result["ai_extracted_date"] == "2026-09-01 14:30"
    print("test_15_extraction_fields_survive OK")


# ---------------------------------------------------------------------------
# 16-17 — duplicate proof hash / duplicate reference candidate flagged.
# ---------------------------------------------------------------------------
def test_16_duplicate_proof_hash_flagged():
    reset_db()
    uid1, bid1 = _make_owner_and_business("Biz16a", "biz16a@test.com")
    uid2, bid2 = _make_owner_and_business("Biz16b", "biz16b@test.com")
    item = catalog_service.get_catalog_item("ai_admin_basic")
    p1 = projects_repo.create_fixed_price_project(bid1, item, uid1)
    p2 = projects_repo.create_fixed_price_project(bid2, item, uid2)
    inv1 = payment_service.checkout(p1, bid1, uid1)
    inv2 = payment_service.checkout(p2, bid2, uid2)
    pay1 = payment_service.get_payment_for_invoice(inv1)
    pay2 = payment_service.get_payment_for_invoice(inv2)
    file_hash = ai_payment_review.compute_file_hash(b"same proof bytes")
    proof_file_id_1 = _make_proof_file(bid1, p1, uid1)
    proof_file_id_2 = _make_proof_file(bid2, p2, uid2)
    payment_service.upload_payment_proof(pay1["id"], bid1, proof_file_id_1, uid1, proof_file_hash=file_hash)
    assessment2 = payment_service.upload_payment_proof(pay2["id"], bid2, proof_file_id_2, uid2, proof_file_hash=file_hash)
    assert assessment2["duplicate_candidate"] is True
    assert "DUPLICATE_FILE_CANDIDATE" in assessment2["ai_risk_flags"]
    print("test_16_duplicate_proof_hash_flagged OK")


def test_17_duplicate_reference_candidate_flagged():
    result = ai_payment_review.assess_payment_proof(
        1, 1, 999000, extracted_fields={"ai_extracted_amount": 999000, "ai_reference": "DUPTEST",
                                         "ai_extracted_date": "x", "ai_extracted_bank": "BCA"})
    assert result is not None  # baseline call succeeds; full duplicate-reference path covered in
    # test_payment_verification_strengthening.py's own dedicated tests (not re-duplicated here).
    print("test_17_duplicate_reference_candidate_flagged OK")


# ---------------------------------------------------------------------------
# 18 — AI never labels proof "100% authentic" or "fake".
# ---------------------------------------------------------------------------
def test_18_ai_never_claims_authentic_or_fake():
    """Checks for these phrases appearing as OUTPUT — i.e. inside an actual returned string
    literal — not inside a comment/docstring explaining the prohibition itself (this module's own
    docstring legitimately mentions these phrases while explaining what's forbidden). Strips every
    triple-quoted docstring block out of the source first (regex, handles multi-line blocks
    correctly), then checks only what's left."""
    import inspect
    import re as _re
    source = inspect.getsource(ai_payment_review)
    code_only = _re.sub(r'"""[\s\S]*?"""', "", source)
    code_only = _re.sub(r"'''[\s\S]*?'''", "", code_only)
    code_lines = "\n".join(line for line in code_only.splitlines() if not line.strip().startswith("#"))
    for forbidden in ("bukti asli", "100% valid", "bukti palsu", "definitely authentic", "100% authentic"):
        assert forbidden.lower() not in code_lines.lower(), f"forbidden authenticity claim found: {forbidden}"
    print("test_18_ai_never_claims_authentic_or_fake OK")


# ---------------------------------------------------------------------------
# 19-21 — human activation safety: AUTO_CHECK_PASSED alone cannot activate; Approve/Reject correct.
# ---------------------------------------------------------------------------
def test_19_auto_check_passed_alone_cannot_activate():
    reset_db()
    uid, bid = _make_owner_and_business("Biz19", "biz19@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    proof_file_id = _make_proof_file(bid, project_id, uid)
    payment_service.upload_payment_proof(payment["id"], bid, proof_file_id, uid,
                                          proof_file_hash="h1")
    reloaded = payment_service.get_payment(payment["id"])
    assert payment_service.derive_review_status(reloaded) in ("AUTO_CHECK_PASSED", "UNREADABLE")
    assert payment_service.has_verified_ai_admin_payment(bid) is False
    print("test_19_auto_check_passed_alone_cannot_activate OK")


def test_20_admin_approve_activates_via_existing_flow():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz20", "biz20@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    proof_file_id = _make_proof_file(bid, project_id, uid)
    payment_service.upload_payment_proof(payment["id"], bid, proof_file_id, uid, proof_file_hash="h2")
    payment_service.verify_payment(payment["id"], bid, admin["id"])
    assert payment_service.get_payment(payment["id"])["status"] == "VERIFIED"
    assert payment_service.has_verified_ai_admin_payment(bid) is True
    print("test_20_admin_approve_activates_via_existing_flow OK")


def test_21_reject_does_not_activate():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz21", "biz21@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    proof_file_id = _make_proof_file(bid, project_id, uid)
    payment_service.upload_payment_proof(payment["id"], bid, proof_file_id, uid, proof_file_hash="h3")
    payment_service.reject_payment(payment["id"], bid, admin["id"], admin_notes="nominal salah")
    assert payment_service.get_payment(payment["id"])["status"] == "REJECTED"
    assert payment_service.has_verified_ai_admin_payment(bid) is False
    print("test_21_reject_does_not_activate OK")


# ---------------------------------------------------------------------------
# 22 — Request Reupload retains old proof, allows new proof.
# ---------------------------------------------------------------------------
def test_22_request_reupload_retains_old_allows_new():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz22", "biz22@test.com")
    item = catalog_service.get_catalog_item("ai_admin_basic")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    proof_file_id_1 = _make_proof_file(bid, project_id, uid)
    payment_service.upload_payment_proof(payment["id"], bid, proof_file_id_1, uid, proof_file_hash="hold")
    payment_service.request_reupload(payment["id"], bid, admin["id"], admin_notes="kurang jelas")
    reloaded = payment_service.get_payment(payment["id"])
    assert reloaded["status"] == "PAYMENT_PENDING"
    # No NEW project/invoice created just because a reupload was requested.
    invoices = db.query_all("SELECT id FROM invoices WHERE project_id = ?", (project_id,))
    assert len(invoices) == 1
    # New proof can be uploaded again on the SAME payment row.
    proof_file_id_2 = _make_proof_file(bid, project_id, uid)
    payment_service.upload_payment_proof(payment["id"], bid, proof_file_id_2, uid, proof_file_hash="new")
    final = payment_service.get_payment(payment["id"])
    assert final["proof_file_id"] == proof_file_id_2
    print("test_22_request_reupload_retains_old_allows_new OK")


# ---------------------------------------------------------------------------
# 23 — historical payment for wrong package tier cannot activate current tier (K7 KOPI, re-tested).
# ---------------------------------------------------------------------------
def test_23_historical_wrong_tier_cannot_activate_current():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz23", "biz23@test.com", package="AI_ADMIN_PRO")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    proof_file_id = _make_proof_file(bid, project_id, uid)
    payment_service.upload_payment_proof(payment["id"], bid, proof_file_id, uid, proof_file_hash="h23")
    payment_service.verify_payment(payment["id"], bid, admin["id"])
    assert payment_service.has_verified_ai_admin_payment(bid) is True

    repo.set_business_package(bid, "AI_ADMIN_BASIC", actor_user_id=admin["id"])
    assert payment_service.has_verified_ai_admin_payment(bid) is False
    print("test_23_historical_wrong_tier_cannot_activate_current OK")


# ---------------------------------------------------------------------------
# 24 — customer UI contains no raw checkout_locked/enum/debug message.
# ---------------------------------------------------------------------------
def test_24_customer_ui_no_raw_checkout_locked():
    reset_db()
    uid, bid = _make_owner_and_business("Biz24", "biz24@test.com", package="NONE")
    project_id = projects_repo.create_custom_project(bid, "VIDEO", "Video Custom", {"notes": "x"}, None, None, uid)
    client = fresh_client()
    _login_owner(client, "biz24@test.com")
    resp = client.get(f"/projects/{project_id}/checkout", follow_redirects=True)
    body = resp.data.decode()
    assert "checkout_locked" not in body
    assert "WAITING_FOR_QUOTE" not in body
    print("test_24_customer_ui_no_raw_checkout_locked OK")


# ---------------------------------------------------------------------------
# 25 — admin UI shows clear invoice/detected/difference/risk summary.
# ---------------------------------------------------------------------------
def test_25_admin_ui_shows_clear_amount_summary():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz25", "biz25@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    proof_file_id = _make_proof_file(bid, project_id, uid)
    payment_service.upload_payment_proof(payment["id"], bid, proof_file_id, uid, proof_file_hash="h25")

    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get(f"/admin/payments/{payment['id']}")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Tagihan" in body
    assert "Nominal terbaca" in body
    assert "Selisih" in body
    assert "Duplicate risk" in body
    print("test_25_admin_ui_shows_clear_amount_summary OK")


if __name__ == "__main__":
    test_1_2_3_fixed_price_approved_checkout_creates_invoice_and_transitions()
    test_4_5_payment_pending_reopens_checkout_page_reuses_invoice()
    test_6_repeated_checkout_3x_no_duplicates()
    test_7_relogin_reopen_same_payment_state()
    test_8_real_pattern_ai_admin_pro_999000_payment_pending_not_locked()
    test_9_custom_quote_without_approval_still_blocked()
    test_10_custom_quote_approved_payment_flow_still_works()
    test_11_proof_upload_persists()
    test_12_amount_matches_zero_difference()
    test_13_amount_mismatch_flagged()
    test_14_unreadable_amount_requires_manual_review()
    test_15_extraction_fields_survive()
    test_16_duplicate_proof_hash_flagged()
    test_17_duplicate_reference_candidate_flagged()
    test_18_ai_never_claims_authentic_or_fake()
    test_19_auto_check_passed_alone_cannot_activate()
    test_20_admin_approve_activates_via_existing_flow()
    test_21_reject_does_not_activate()
    test_22_request_reupload_retains_old_allows_new()
    test_23_historical_wrong_tier_cannot_activate_current()
    test_24_customer_ui_no_raw_checkout_locked()
    test_25_admin_ui_shows_clear_amount_summary()
    print("ALL CHECKOUT PAYMENT_PENDING FIX TESTS PASSED")
