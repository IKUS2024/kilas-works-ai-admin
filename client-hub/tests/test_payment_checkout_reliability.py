"""Payment checkout state machine reliability — Tests 1-25 from the request.

ROOT CAUSE (confirmed by source inspection, NOT re-implemented — already fixed and documented in
payment_service.checkout()'s own docstring): the checkout guard used to reject any project whose
status was not literally "APPROVED", including PAYMENT_PENDING — but PAYMENT_PENDING is a status
this SAME function itself sets, so a customer revisiting checkout (refresh, back button, clicking
"Lanjut ke Pembayaran" again) was rejected by a guard that didn't recognize its own prior output.
The fix (already in place) allows ("APPROVED", "PAYMENT_PENDING") and reuses the existing invoice
when one exists. This file's job is END-TO-END VERIFICATION with real regression coverage — no
prior test file directly exercised payment_service.checkout()'s PAYMENT_PENDING-reuse path at all.

Run with:
    cd client-hub && python3 tests/test_payment_checkout_reliability.py
"""
import os
import sys
import tempfile
from unittest.mock import patch

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
import quotation_service  # noqa: E402
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


def _make_admin():
    admin_id = repo.create_user(f"admin_{os.urandom(4).hex()}@kilasworks.id",
                                 security.hash_password("adminpass123"), role="KILAS_ADMIN")
    return db.query_one("SELECT * FROM users WHERE id = ?", (admin_id,))


def _login_admin(client, admin):
    client.post("/login", data={"email": admin["email"], "password": "adminpass123"})


def _login_owner(client, email, password="password123"):
    client.post("/login", data={"email": email, "password": password})


def _make_owner_and_business(name, email, package="AI_ADMIN_PRO"):
    uid = repo.create_user(email, security.hash_password("password123"))
    bid = repo.create_business(uid, name, package=package)
    return uid, bid


def _upload_with_extracted_fields(payment_id, business_id, invoice_amount, actor_user_id,
                                   extracted_fields=None, proof_file_hash=None):
    payment = payment_service.get_payment(payment_id)
    assessment = ai_payment_review.assess_payment_proof(
        payment_id, business_id, invoice_amount, extracted_fields=extracted_fields,
        proof_file_hash=proof_file_hash,
    )
    invoice = payment_service.get_invoice(payment["invoice_id"])
    # Create a real project_files row and link it, matching what the real upload route does — a
    # prior version of this helper never set proof_file_id at all, which silently made every
    # "does the old proof survive a request-reupload" check meaningless.
    file_id = db.insert_returning_id(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'PAYMENT_PROOF', ?, ?, ?, ?, ?)",
        (business_id, invoice["project_id"], "bukti.jpg", "image/jpeg", 10, b"fake bytes", actor_user_id),
    )
    import json
    db.execute(
        "UPDATE payments SET status = 'UNDER_REVIEW', proof_file_id = ?, ai_extracted_amount = ?, "
        "ai_extracted_date = ?, ai_extracted_bank = ?, ai_reference = ?, ai_risk_flags_json = ?, "
        "ai_match_score = ?, duplicate_candidate = ?, proof_file_hash = ? WHERE id = ?",
        (file_id, assessment["ai_extracted_amount"], assessment["ai_extracted_date"],
         assessment["ai_extracted_bank"], assessment["ai_reference"],
         json.dumps(assessment["ai_risk_flags"]), assessment["ai_match_score"],
         bool(assessment["duplicate_candidate"]), proof_file_hash, payment_id),
    )
    repo.write_audit(actor_user_id, business_id, "PAYMENT_PROOF_UPLOADED", f"payment_id={payment_id}",
                      project_id=invoice["project_id"])
    return assessment


# ---------------------------------------------------------------------------
# TESTS 1-3 — FIXED_PRICE APPROVED -> checkout succeeds, invoice created, PAYMENT_PENDING.
# ---------------------------------------------------------------------------
def test_1_fixed_price_approved_checkout_succeeds():
    reset_db()
    uid, bid = _make_owner_and_business("Biz T1", "t1@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    assert projects_repo.get_project(project_id)["status"] == "APPROVED"
    invoice_id = payment_service.checkout(project_id, bid, uid)
    assert invoice_id is not None
    print("test_1_fixed_price_approved_checkout_succeeds OK")


def test_2_checkout_creates_exactly_one_invoice():
    reset_db()
    uid, bid = _make_owner_and_business("Biz T2", "t2@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    payment_service.checkout(project_id, bid, uid)
    invoices = db.query_all("SELECT id FROM invoices WHERE project_id = ?", (project_id,))
    assert len(invoices) == 1
    print("test_2_checkout_creates_exactly_one_invoice OK")


def test_3_project_becomes_payment_pending():
    reset_db()
    uid, bid = _make_owner_and_business("Biz T3", "t3@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    payment_service.checkout(project_id, bid, uid)
    assert projects_repo.get_project(project_id)["status"] == "PAYMENT_PENDING"
    print("test_3_project_becomes_payment_pending OK")


# ---------------------------------------------------------------------------
# TESTS 4-8 — the exact reported bug scenario.
# ---------------------------------------------------------------------------
def test_4_payment_pending_existing_project_checkout_page_opens():
    reset_db()
    uid, bid = _make_owner_and_business("Biz T4", "t4@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    client = fresh_client()
    _login_owner(client, "t4@test.com")
    resp = client.get(f"/invoices/{invoice_id}")
    assert resp.status_code == 200
    print("test_4_payment_pending_existing_project_checkout_page_opens OK")


def test_5_payment_pending_with_existing_invoice_same_invoice_reused():
    reset_db()
    uid, bid = _make_owner_and_business("Biz T5", "t5@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id_1 = payment_service.checkout(project_id, bid, uid)
    invoice_id_2 = payment_service.checkout(project_id, bid, uid)  # simulates re-clicking checkout
    assert invoice_id_1 == invoice_id_2
    print("test_5_payment_pending_with_existing_invoice_same_invoice_reused OK")


def test_6_repeated_checkout_3x_no_duplicate_invoice_or_payment():
    reset_db()
    uid, bid = _make_owner_and_business("Biz T6", "t6@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    for _ in range(3):
        payment_service.checkout(project_id, bid, uid)
    invoices = db.query_all("SELECT id FROM invoices WHERE project_id = ?", (project_id,))
    payments = db.query_all("SELECT id FROM payments WHERE business_id = ?", (bid,))
    assert len(invoices) == 1, f"BUG: repeated checkout created duplicate invoices: {invoices}"
    assert len(payments) == 1, f"BUG: repeated checkout created duplicate payments: {payments}"
    print("test_6_repeated_checkout_3x_no_duplicate_invoice_or_payment OK")


def test_7_refresh_relogin_reopen_same_payment_state():
    reset_db()
    uid, bid = _make_owner_and_business("Biz T7", "t7@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment_before = payment_service.get_payment_for_invoice(invoice_id)

    # Simulate logout/login (new client session) + reopening via ai_admin_checkout again.
    client = fresh_client()
    _login_owner(client, "t7@test.com")
    resp = client.get(f"/business/{bid}/ai-admin/checkout", follow_redirects=False)
    assert resp.status_code == 302
    assert f"/invoices/" in resp.headers.get("Location", "") or "/payments/" in resp.headers.get("Location", "").lower() \
        or str(invoice_id) in resp.headers.get("Location", "")

    payment_after = payment_service.get_payment_for_invoice(invoice_id)
    assert payment_before["id"] == payment_after["id"]
    print("test_7_refresh_relogin_reopen_same_payment_state OK")


def test_8_real_reported_pattern_ai_admin_pro_999k_payment_pending_not_locked():
    """The EXACT reported production pattern: AI Admin Pro, Rp999.000, already PAYMENT_PENDING —
    must NOT raise checkout_locked."""
    reset_db()
    uid, bid = _make_owner_and_business("Biz T8 (real pattern)", "t8@test.com", package="AI_ADMIN_PRO")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    assert item["price_amount"] == 999000, f"expected Rp999.000 catalog price, got {item['price_amount']}"
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    payment_service.checkout(project_id, bid, uid)  # first checkout -> PAYMENT_PENDING
    assert projects_repo.get_project(project_id)["status"] == "PAYMENT_PENDING"

    try:
        payment_service.checkout(project_id, bid, uid)  # customer revisits checkout
        raised = False
    except ValueError as e:
        raised = True
        error_msg = str(e)
    assert not raised, f"BUG: checkout_locked raised for a legitimate PAYMENT_PENDING revisit"
    print("test_8_real_reported_pattern_ai_admin_pro_999k_payment_pending_not_locked OK")


# ---------------------------------------------------------------------------
# TESTS 9-10 — CUSTOM_QUOTE safety preserved.
# ---------------------------------------------------------------------------
def test_9_custom_quote_without_approved_quotation_remains_blocked():
    reset_db()
    uid, bid = _make_owner_and_business("Biz T9", "t9@test.com", package="NONE")
    project_id = projects_repo.create_custom_project(
        bid, "VIDEO", "Video Custom", {"notes": "test"}, None, None, uid, catalog_key="custom_video",
    )
    project = projects_repo.get_project(project_id)
    assert project["status"] == "WAITING_FOR_QUOTE"
    try:
        payment_service.checkout(project_id, bid, uid)
        raised = False
    except ValueError:
        raised = True
    assert raised, "BUG: checkout must still be blocked for an unapproved custom quote"
    print("test_9_custom_quote_without_approved_quotation_remains_blocked OK")


def test_10_custom_quote_approved_payment_flow_still_works():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz T10", "t10@test.com", package="NONE")
    project_id = projects_repo.create_custom_project(
        bid, "VIDEO", "Video Custom", {"notes": "test"}, None, None, uid, catalog_key="custom_video",
    )
    quotation_id = quotation_service.create_quotation(
        project_id, bid, "test scope", "test deliverables", "1x", 2000000, None, admin["id"],
    )
    quotation_service.approve_quotation(quotation_id, bid, uid)
    project = projects_repo.get_project(project_id)
    assert project["status"] == "APPROVED"
    invoice_id = payment_service.checkout(project_id, bid, uid)
    assert invoice_id is not None
    print("test_10_custom_quote_approved_payment_flow_still_works OK")


# ---------------------------------------------------------------------------
# TEST 11 — proof upload persists.
# ---------------------------------------------------------------------------
def test_11_proof_upload_persists():
    reset_db()
    uid, bid = _make_owner_and_business("Biz T11", "t11@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    _upload_with_extracted_fields(payment["id"], bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": item["price_amount"]})
    reloaded = payment_service.get_payment(payment["id"])
    assert reloaded["status"] == "UNDER_REVIEW"
    print("test_11_proof_upload_persists OK")


# ---------------------------------------------------------------------------
# TESTS 12-14 — amount comparison.
# ---------------------------------------------------------------------------
def test_12_detected_matches_invoice_difference_zero():
    reset_db()
    uid, bid = _make_owner_and_business("Biz T12", "t12@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    _upload_with_extracted_fields(payment["id"], bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": 999000})
    reloaded = payment_service.get_payment(payment["id"])
    difference = reloaded["ai_extracted_amount"] - item["price_amount"]
    assert difference == 0
    assert payment_service.derive_review_status(reloaded) == "AUTO_CHECK_PASSED"
    print("test_12_detected_matches_invoice_difference_zero OK")


def test_13_detected_mismatch_flagged():
    reset_db()
    uid, bid = _make_owner_and_business("Biz T13", "t13@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    _upload_with_extracted_fields(payment["id"], bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": 990000})
    reloaded = payment_service.get_payment(payment["id"])
    difference = reloaded["ai_extracted_amount"] - item["price_amount"]
    assert difference == -9000
    assert payment_service.derive_review_status(reloaded) == "AMOUNT_MISMATCH"
    print("test_13_detected_mismatch_flagged OK")


def test_14_unreadable_amount_manual_review_required():
    reset_db()
    uid, bid = _make_owner_and_business("Biz T14", "t14@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    _upload_with_extracted_fields(payment["id"], bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": None})
    reloaded = payment_service.get_payment(payment["id"])
    assert payment_service.derive_review_status(reloaded) == "UNREADABLE"
    print("test_14_unreadable_amount_manual_review_required OK")


# ---------------------------------------------------------------------------
# TEST 15 — bank/date/reference extraction fields survive parsing.
# ---------------------------------------------------------------------------
def test_15_extraction_fields_survive_parsing():
    reset_db()
    uid, bid = _make_owner_and_business("Biz T15", "t15@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    _upload_with_extracted_fields(payment["id"], bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": 999000, "ai_extracted_date": "2026-09-02",
                                                      "ai_extracted_bank": "BCA", "ai_reference": "REF12345"})
    reloaded = payment_service.get_payment(payment["id"])
    assert reloaded["ai_extracted_bank"] == "BCA"
    assert reloaded["ai_extracted_date"] == "2026-09-02"
    assert reloaded["ai_reference"] == "REF12345"
    print("test_15_extraction_fields_survive_parsing OK")


# ---------------------------------------------------------------------------
# TESTS 16-17 — duplicate detection.
# ---------------------------------------------------------------------------
def test_16_duplicate_proof_hash_flagged():
    reset_db()
    uid1, bid1 = _make_owner_and_business("Biz T16a", "t16a@test.com")
    uid2, bid2 = _make_owner_and_business("Biz T16b", "t16b@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    pid1 = projects_repo.create_fixed_price_project(bid1, item, uid1)
    pid2 = projects_repo.create_fixed_price_project(bid2, item, uid2)
    inv1 = payment_service.checkout(pid1, bid1, uid1)
    inv2 = payment_service.checkout(pid2, bid2, uid2)
    pay1 = payment_service.get_payment_for_invoice(inv1)
    pay2 = payment_service.get_payment_for_invoice(inv2)
    shared_hash = ai_payment_review.compute_file_hash(b"same screenshot bytes")
    _upload_with_extracted_fields(pay1["id"], bid1, item["price_amount"], uid1, proof_file_hash=shared_hash)
    result2 = _upload_with_extracted_fields(pay2["id"], bid2, item["price_amount"], uid2, proof_file_hash=shared_hash)
    assert result2["duplicate_candidate"] is True
    print("test_16_duplicate_proof_hash_flagged OK")


def test_17_duplicate_reference_candidate_flagged():
    reset_db()
    uid1, bid1 = _make_owner_and_business("Biz T17a", "t17a@test.com")
    uid2, bid2 = _make_owner_and_business("Biz T17b", "t17b@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    pid1 = projects_repo.create_fixed_price_project(bid1, item, uid1)
    pid2 = projects_repo.create_fixed_price_project(bid2, item, uid2)
    inv1 = payment_service.checkout(pid1, bid1, uid1)
    inv2 = payment_service.checkout(pid2, bid2, uid2)
    pay1 = payment_service.get_payment_for_invoice(inv1)
    pay2 = payment_service.get_payment_for_invoice(inv2)
    _upload_with_extracted_fields(pay1["id"], bid1, item["price_amount"], uid1,
                                   extracted_fields={"ai_reference": "REF-SHARED"})
    result2 = _upload_with_extracted_fields(pay2["id"], bid2, item["price_amount"], uid2,
                                             extracted_fields={"ai_reference": "REF-SHARED"})
    assert "DUPLICATE_REFERENCE_CANDIDATE" in result2["ai_risk_flags"]
    print("test_17_duplicate_reference_candidate_flagged OK")


# ---------------------------------------------------------------------------
# TEST 18 — AI never claims authentic/fake.
# ---------------------------------------------------------------------------
def test_18_ai_never_labels_authentic_or_fake():
    """Checks the module's own module-level docstring is EXCLUDED from this scan — it legitimately
    quotes the forbidden phrases (in quotes, explaining the rule itself), which is not the same as
    the module instructing the model to actually say them. Scans everything AFTER the docstring
    (the real prompt/logic code) instead.

    Real vision extraction (Part B of the payment-proof-vision-extraction request) added an
    explicit VISION_EXTRACTION_SYSTEM_PROMPT that legitimately LISTS these exact phrases as
    FORBIDDEN examples ("JANGAN PERNAH bilang bukti ini asli... 100% valid...") — this is the
    CORRECT, safe way to instruct the model never to say them, so the phrase's mere presence in
    the source is not itself a violation. The real check is: every occurrence must appear as part
    of a prohibition (preceded by a negation marker like "JANGAN"/"never"/"tidak boleh" within the
    same nearby text), never as a bare positive claim the code would actually output."""
    import inspect
    source = inspect.getsource(ai_payment_review)
    # Skip past the module's own top-of-file docstring (delimited by the first pair of \"\"\").
    first_quote = source.find('"""')
    second_quote = source.find('"""', first_quote + 3)
    code_only = source[second_quote + 3:] if second_quote != -1 else source
    negation_markers = ("jangan", "never", "tidak boleh", "tidak pernah")
    for forbidden in ("bukti asli", "100% valid", "bukti palsu", "asli 100%", "PASTI ASLI"):
        idx = code_only.lower().find(forbidden.lower())
        while idx != -1:
            preceding_context = code_only[max(0, idx - 80):idx].lower()
            assert any(marker in preceding_context for marker in negation_markers), (
                f"forbidden authenticity claim '{forbidden}' found WITHOUT a nearby prohibition "
                f"marker (i.e. used as a positive claim, not listed as forbidden): "
                f"...{code_only[max(0,idx-80):idx+40]!r}..."
            )
            idx = code_only.lower().find(forbidden.lower(), idx + 1)
    print("test_18_ai_never_labels_authentic_or_fake OK")


# ---------------------------------------------------------------------------
# TEST 19 — AUTO_CHECK_PASSED cannot activate.
# ---------------------------------------------------------------------------
def test_19_auto_check_passed_cannot_activate():
    reset_db()
    uid, bid = _make_owner_and_business("Biz T19", "t19@test.com", package="AI_ADMIN_PRO")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    _upload_with_extracted_fields(payment["id"], bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": item["price_amount"]})
    assert payment_service.has_verified_ai_admin_payment(bid) is False
    print("test_19_auto_check_passed_cannot_activate OK")


# ---------------------------------------------------------------------------
# TESTS 20-22 — admin approve/reject/request-reupload.
# ---------------------------------------------------------------------------
def test_20_admin_approve_verified_activates():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz T20", "t20@test.com", package="AI_ADMIN_PRO")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    _upload_with_extracted_fields(payment["id"], bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": item["price_amount"]})
    payment_service.verify_payment(payment["id"], bid, admin["id"])
    assert payment_service.has_verified_ai_admin_payment(bid) is True
    print("test_20_admin_approve_verified_activates OK")


def test_21_reject_does_not_activate():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz T21", "t21@test.com", package="AI_ADMIN_PRO")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    _upload_with_extracted_fields(payment["id"], bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": 500000})
    payment_service.reject_payment(payment["id"], bid, admin["id"], admin_notes="mismatch")
    assert payment_service.has_verified_ai_admin_payment(bid) is False
    print("test_21_reject_does_not_activate OK")


def test_22_request_reupload_retains_old_proof_allows_new():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz T22", "t22@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    _upload_with_extracted_fields(payment["id"], bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": None})
    old_proof_file_id = payment_service.get_payment(payment["id"])["proof_file_id"]
    payment_service.request_reupload(payment["id"], bid, admin["id"], admin_notes="blur")
    reloaded = payment_service.get_payment(payment["id"])
    assert reloaded["status"] == "PAYMENT_PENDING"
    old_file_still_exists = db.query_one("SELECT id FROM project_files WHERE id = ?", (old_proof_file_id,))
    assert old_file_still_exists is not None, "old proof must remain for audit"
    # New proof allowed:
    _upload_with_extracted_fields(payment["id"], bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": item["price_amount"]})
    assert payment_service.get_payment(payment["id"])["status"] == "UNDER_REVIEW"
    print("test_22_request_reupload_retains_old_proof_allows_new OK")


# ---------------------------------------------------------------------------
# TEST 23 — historical payment for wrong tier cannot activate current tier (K7 KOPI, re-confirmed).
# ---------------------------------------------------------------------------
def test_23_historical_wrong_tier_payment_cannot_activate_current_tier():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz T23", "t23@test.com", package="AI_ADMIN_PRO")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    _upload_with_extracted_fields(payment["id"], bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": item["price_amount"]})
    payment_service.verify_payment(payment["id"], bid, admin["id"])
    assert payment_service.has_verified_ai_admin_payment(bid) is True

    repo.set_business_package(bid, "AI_ADMIN_BASIC", actor_user_id=admin["id"])
    assert payment_service.has_verified_ai_admin_payment(bid) is False
    print("test_23_historical_wrong_tier_payment_cannot_activate_current_tier OK")


# ---------------------------------------------------------------------------
# TEST 24 — customer UI contains no raw checkout_locked/enum/debug message.
# ---------------------------------------------------------------------------
def test_24_customer_ui_no_raw_checkout_locked_or_enums():
    reset_db()
    uid, bid = _make_owner_and_business("Biz T24", "t24@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    client = fresh_client()
    _login_owner(client, "t24@test.com")
    resp = client.get(f"/invoices/{invoice_id}")
    body = resp.data.decode()
    for raw in ("checkout_locked", ">PAYMENT_PENDING<", "must be APPROVED"):
        assert raw not in body, f"raw backend text leaked to customer: {raw}"
    print("test_24_customer_ui_no_raw_checkout_locked_or_enums OK")


# ---------------------------------------------------------------------------
# TEST 25 — admin UI shows clear invoice/detected/difference/risk summary.
# ---------------------------------------------------------------------------
def test_25_admin_ui_shows_clear_amount_and_risk_summary():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz T25", "t25@test.com")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    _upload_with_extracted_fields(payment["id"], bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": item["price_amount"], "ai_extracted_bank": "BCA"})
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get(f"/admin/payments/{payment['id']}")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Selisih" in body
    assert "Nominal terbaca" in body
    assert "Duplicate risk" in body
    print("test_25_admin_ui_shows_clear_amount_and_risk_summary OK")


if __name__ == "__main__":
    test_1_fixed_price_approved_checkout_succeeds()
    test_2_checkout_creates_exactly_one_invoice()
    test_3_project_becomes_payment_pending()
    test_4_payment_pending_existing_project_checkout_page_opens()
    test_5_payment_pending_with_existing_invoice_same_invoice_reused()
    test_6_repeated_checkout_3x_no_duplicate_invoice_or_payment()
    test_7_refresh_relogin_reopen_same_payment_state()
    test_8_real_reported_pattern_ai_admin_pro_999k_payment_pending_not_locked()
    test_9_custom_quote_without_approved_quotation_remains_blocked()
    test_10_custom_quote_approved_payment_flow_still_works()
    test_11_proof_upload_persists()
    test_12_detected_matches_invoice_difference_zero()
    test_13_detected_mismatch_flagged()
    test_14_unreadable_amount_manual_review_required()
    test_15_extraction_fields_survive_parsing()
    test_16_duplicate_proof_hash_flagged()
    test_17_duplicate_reference_candidate_flagged()
    test_18_ai_never_labels_authentic_or_fake()
    test_19_auto_check_passed_cannot_activate()
    test_20_admin_approve_verified_activates()
    test_21_reject_does_not_activate()
    test_22_request_reupload_retains_old_proof_allows_new()
    test_23_historical_wrong_tier_payment_cannot_activate_current_tier()
    test_24_customer_ui_no_raw_checkout_locked_or_enums()
    test_25_admin_ui_shows_clear_amount_and_risk_summary()
    print("ALL 25 PAYMENT CHECKOUT RELIABILITY TESTS PASSED")
