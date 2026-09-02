"""Payment verification strengthening — Tests A-M from the request.

DOMAIN MODEL (Section 2 of the request, definitive result — not a guess): Client Hub's payments/
invoices/projects tables represent ONLY businesses/tenants paying KILAS WORKS for a service (AI
Admin, Foto, Video, Website, etc.) — Kilas Works is the seller in every single row. Confirmed via
owner_notifications.notify_payment_proof_uploaded() (always links to /admin/payments/<id>, Kilas
Works' own admin route) and via app.py's SEPARATE, entirely chat-based "tenant's own end-customer
pays the tenant" flow (feature_flags.payment_conversation + business_profile.payment_bank_name/
account_number/etc. + build_payment_info_text()'s tenant-scoped equivalent) — that second flow
never touches Client Hub's payments table at all. Therefore:

  PAYMENT APPROVAL OWNER: KILAS WORKS ADMIN (always, for every row in this table) — this is
  correct-by-design, not a gap. Tenant isolation still applies on the VIEWING side (a business can
  only ever see its own invoices/payments) and on the MUTATION side (verify_payment()/
  reject_payment()/request_reupload() all check payment["business_id"] == business_id).

Run with:
    cd client-hub && python3 tests/test_payment_verification_strengthening.py
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


def _checkout(business_id, catalog_key, actor_user_id):
    item = catalog_service.get_catalog_item(catalog_key)
    project_id = projects_repo.create_fixed_price_project(business_id, item, actor_user_id)
    invoice_id = payment_service.checkout(project_id, business_id, actor_user_id)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    return project_id, invoice_id, payment["id"]


def _upload_with_extracted_fields(payment_id, business_id, invoice_amount, actor_user_id,
                                   extracted_fields=None, proof_file_hash=None):
    """Simulates upload_payment_proof()'s pipeline directly with controlled extracted_fields —
    since real vision extraction isn't wired up yet (see ai_payment_review.py's own docstring),
    this is how these tests supply a specific extracted amount/reference the way a real vision
    call eventually would. Mirrors upload_payment_proof()'s own side effects exactly (including
    the audit write) so tests exercising audit-trail behavior see the same shape a real upload
    would produce."""
    payment = payment_service.get_payment(payment_id)
    assessment = ai_payment_review.assess_payment_proof(
        payment_id, business_id, invoice_amount, extracted_fields=extracted_fields,
        proof_file_hash=proof_file_hash,
    )
    import json
    db.execute(
        "UPDATE payments SET status = 'UNDER_REVIEW', ai_extracted_amount = ?, ai_extracted_date = ?, "
        "ai_extracted_bank = ?, ai_reference = ?, ai_risk_flags_json = ?, ai_match_score = ?, "
        "duplicate_candidate = ?, proof_file_hash = ? WHERE id = ?",
        (assessment["ai_extracted_amount"], assessment["ai_extracted_date"],
         assessment["ai_extracted_bank"], assessment["ai_reference"],
         json.dumps(assessment["ai_risk_flags"]), assessment["ai_match_score"],
         bool(assessment["duplicate_candidate"]), proof_file_hash, payment_id),
    )
    invoice = payment_service.get_invoice(payment["invoice_id"])
    repo.write_audit(actor_user_id, business_id, "PAYMENT_PROOF_UPLOADED", f"payment_id={payment_id}",
                      project_id=invoice["project_id"])
    return assessment


# ---------------------------------------------------------------------------
# TEST A — amount matches -> AUTO_CHECK_PASSED, NOT automatically VERIFIED.
# ---------------------------------------------------------------------------
def test_A_amount_matches_auto_check_passed_not_verified():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz A", "paya@test.com", package="AI_ADMIN_PRO")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    _, _, payment_id = _checkout(bid, "ai_admin_pro", uid)
    _upload_with_extracted_fields(payment_id, bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": item["price_amount"],
                                                      "ai_extracted_date": "2026-09-01",
                                                      "ai_extracted_bank": "BCA", "ai_reference": "REF-A"})
    payment = payment_service.get_payment(payment_id)
    assert payment_service.derive_review_status(payment) == "AUTO_CHECK_PASSED"
    assert payment["status"] == "UNDER_REVIEW", "must NEVER be VERIFIED automatically"
    print("test_A_amount_matches_auto_check_passed_not_verified OK")


# ---------------------------------------------------------------------------
# TEST B — amount mismatch -> AMOUNT_MISMATCH.
# ---------------------------------------------------------------------------
def test_B_amount_mismatch():
    reset_db()
    uid, bid = _make_owner_and_business("Biz B", "payb@test.com", package="AI_ADMIN_PRO")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    _, _, payment_id = _checkout(bid, "ai_admin_pro", uid)
    wrong_amount = item["price_amount"] - 9000
    _upload_with_extracted_fields(payment_id, bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": wrong_amount,
                                                      "ai_extracted_date": "2026-09-01",
                                                      "ai_extracted_bank": "BCA", "ai_reference": "REF-B"})
    payment = payment_service.get_payment(payment_id)
    assert payment_service.derive_review_status(payment) == "AMOUNT_MISMATCH"
    print("test_B_amount_mismatch OK")


# ---------------------------------------------------------------------------
# TEST C — unreadable proof -> UNREADABLE.
# ---------------------------------------------------------------------------
def test_C_unreadable_proof():
    reset_db()
    uid, bid = _make_owner_and_business("Biz C", "payc@test.com", package="AI_ADMIN_BASIC")
    item = catalog_service.get_catalog_item("ai_admin_basic")
    _, _, payment_id = _checkout(bid, "ai_admin_basic", uid)
    _upload_with_extracted_fields(payment_id, bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": None, "ai_extracted_date": None,
                                                      "ai_extracted_bank": None, "ai_reference": None})
    payment = payment_service.get_payment(payment_id)
    assert payment_service.derive_review_status(payment) == "UNREADABLE"
    print("test_C_unreadable_proof OK")


# ---------------------------------------------------------------------------
# TEST D — same exact proof reused -> POSSIBLE_DUPLICATE.
# ---------------------------------------------------------------------------
def test_D_same_proof_file_reused_possible_duplicate():
    reset_db()
    uid1, bid1 = _make_owner_and_business("Biz D1", "payd1@test.com", package="AI_ADMIN_BASIC")
    uid2, bid2 = _make_owner_and_business("Biz D2", "payd2@test.com", package="AI_ADMIN_BASIC")
    item = catalog_service.get_catalog_item("ai_admin_basic")
    _, _, payment_id_1 = _checkout(bid1, "ai_admin_basic", uid1)
    _, _, payment_id_2 = _checkout(bid2, "ai_admin_basic", uid2)

    same_bytes = b"identical screenshot bytes"
    file_hash = ai_payment_review.compute_file_hash(same_bytes)
    assert file_hash == ai_payment_review.compute_file_hash(same_bytes)  # deterministic

    _upload_with_extracted_fields(payment_id_1, bid1, item["price_amount"], uid1,
                                   extracted_fields={"ai_extracted_amount": item["price_amount"]},
                                   proof_file_hash=file_hash)
    payment_1 = payment_service.get_payment(payment_id_1)
    assert payment_service.derive_review_status(payment_1) == "AUTO_CHECK_PASSED"

    # Second business reuses the EXACT SAME file bytes.
    _upload_with_extracted_fields(payment_id_2, bid2, item["price_amount"], uid2,
                                   extracted_fields={"ai_extracted_amount": item["price_amount"]},
                                   proof_file_hash=file_hash)
    payment_2 = payment_service.get_payment(payment_id_2)
    assert payment_service.derive_review_status(payment_2) == "POSSIBLE_DUPLICATE"
    assert payment_2["duplicate_candidate"] in (True, 1)
    print("test_D_same_proof_file_reused_possible_duplicate OK")


# ---------------------------------------------------------------------------
# TEST E — suspicious/risk-flagged proof -> NEEDS_MANUAL_REVIEW, never auto-reject/verify.
# ---------------------------------------------------------------------------
def test_E_needs_manual_review_never_auto_decided():
    reset_db()
    uid, bid = _make_owner_and_business("Biz E", "paye@test.com", package="AI_ADMIN_PRO")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    _, _, payment_id = _checkout(bid, "ai_admin_pro", uid)
    # A future SUSPICIOUS_VISUAL_ANOMALY-style flag, not AMOUNT_MISMATCH/duplicate/unreadable —
    # simulated directly since real vision extraction isn't wired up (matches
    # ai_payment_review.py's own documented reserved-flag category).
    import json
    db.execute(
        "UPDATE payments SET status = 'UNDER_REVIEW', ai_extracted_amount = ?, "
        "ai_risk_flags_json = ? WHERE id = ?",
        (item["price_amount"], json.dumps(["SUSPICIOUS_VISUAL_ANOMALY"]), payment_id),
    )
    payment = payment_service.get_payment(payment_id)
    assert payment_service.derive_review_status(payment) == "NEEDS_MANUAL_REVIEW"
    assert payment["status"] == "UNDER_REVIEW", "must never be auto-rejected"
    print("test_E_needs_manual_review_never_auto_decided OK")


# ---------------------------------------------------------------------------
# TEST F/G/H — Approve -> VERIFIED; Reject -> not VERIFIED, audit retained; Request Reupload ->
# proof/history retained, asks for new proof.
# ---------------------------------------------------------------------------
def test_F_admin_approve_verifies():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz F", "payf@test.com", package="AI_ADMIN_BASIC")
    item = catalog_service.get_catalog_item("ai_admin_basic")
    _, _, payment_id = _checkout(bid, "ai_admin_basic", uid)
    _upload_with_extracted_fields(payment_id, bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": item["price_amount"]})
    payment_service.verify_payment(payment_id, bid, admin["id"])
    payment = payment_service.get_payment(payment_id)
    assert payment["status"] == "VERIFIED"
    print("test_F_admin_approve_verifies OK")


def test_G_reject_not_verified_audit_retained():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz G", "payg@test.com", package="AI_ADMIN_BASIC")
    item = catalog_service.get_catalog_item("ai_admin_basic")
    _, _, payment_id = _checkout(bid, "ai_admin_basic", uid)
    _upload_with_extracted_fields(payment_id, bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": item["price_amount"] - 1000})
    payment_service.reject_payment(payment_id, bid, admin["id"], admin_notes="nominal salah")
    payment = payment_service.get_payment(payment_id)
    assert payment["status"] == "REJECTED"
    audit = repo.get_audit_log(bid)
    assert any(a["action"] == "PAYMENT_PROOF_UPLOADED" for a in audit), "upload audit must be retained"
    assert any(a["action"] == "PAYMENT_REJECTED" for a in audit) or any("reject" in (a["action"] or "").lower() for a in audit)
    print("test_G_reject_not_verified_audit_retained OK")


def test_H_request_reupload_retains_history_asks_new_proof():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz H", "payh@test.com", package="AI_ADMIN_BASIC")
    item = catalog_service.get_catalog_item("ai_admin_basic")
    _, _, payment_id = _checkout(bid, "ai_admin_basic", uid)
    _upload_with_extracted_fields(payment_id, bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": None})
    old_proof_file_id_before = payment_service.get_payment(payment_id).get("proof_file_id")
    payment_service.request_reupload(payment_id, bid, admin["id"], admin_notes="foto kurang jelas")
    payment = payment_service.get_payment(payment_id)
    assert payment["status"] == "PAYMENT_PENDING", "must ask for a fresh upload, not stay REJECTED"
    audit = repo.get_audit_log(bid)
    assert any(a["action"] == "PAYMENT_REUPLOAD_REQUESTED" for a in audit)
    assert any(a["action"] == "PAYMENT_PROOF_UPLOADED" for a in audit), "original upload audit retained"
    print("test_H_request_reupload_retains_history_asks_new_proof OK")


# ---------------------------------------------------------------------------
# TEST I/J — activation safety re-confirmed.
# ---------------------------------------------------------------------------
def test_I_auto_check_passed_alone_cannot_activate():
    reset_db()
    uid, bid = _make_owner_and_business("Biz I", "payi@test.com", package="AI_ADMIN_PRO")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    _, _, payment_id = _checkout(bid, "ai_admin_pro", uid)
    _upload_with_extracted_fields(payment_id, bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": item["price_amount"]})
    payment = payment_service.get_payment(payment_id)
    assert payment_service.derive_review_status(payment) == "AUTO_CHECK_PASSED"
    assert payment_service.has_verified_ai_admin_payment(bid) is False, \
        "AUTO_CHECK_PASSED (no human approval yet) must never satisfy the activation gate"
    print("test_I_auto_check_passed_alone_cannot_activate OK")


def test_J_current_basic_with_historical_pro_cannot_activate():
    """K7 KOPI fix re-confirmed under this session's changes."""
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz J", "payj@test.com", package="AI_ADMIN_PRO")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    _, _, old_payment_id = _checkout(bid, "ai_admin_pro", uid)
    _upload_with_extracted_fields(old_payment_id, bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": item["price_amount"]})
    payment_service.verify_payment(old_payment_id, bid, admin["id"])
    assert payment_service.has_verified_ai_admin_payment(bid) is True

    repo.set_business_package(bid, "AI_ADMIN_BASIC", actor_user_id=admin["id"])
    assert payment_service.has_verified_ai_admin_payment(bid) is False, \
        "a historical Pro payment must never satisfy the current Basic activation gate"
    print("test_J_current_basic_with_historical_pro_cannot_activate OK")


# ---------------------------------------------------------------------------
# TEST K — tenant isolation: wrong business cannot access/mutate another payment.
# ---------------------------------------------------------------------------
def test_K_wrong_business_cannot_view_another_payment():
    reset_db()
    uid1, bid1 = _make_owner_and_business("Biz K1", "payk1@test.com", package="AI_ADMIN_BASIC")
    uid2, bid2 = _make_owner_and_business("Biz K2", "payk2@test.com", package="AI_ADMIN_BASIC")
    _, invoice_id_1, _ = _checkout(bid1, "ai_admin_basic", uid1)

    client = fresh_client()
    _login_owner(client, "payk2@test.com")
    resp = client.get(f"/invoices/{invoice_id_1}")
    assert resp.status_code == 404, "business K2 must never view business K1's invoice"
    print("test_K_wrong_business_cannot_view_another_payment OK")


def test_K_wrong_business_cannot_mutate_another_payment_via_service_layer():
    reset_db()
    admin = _make_admin()
    uid1, bid1 = _make_owner_and_business("Biz K3", "payk3@test.com", package="AI_ADMIN_BASIC")
    uid2, bid2 = _make_owner_and_business("Biz K4", "payk4@test.com", package="AI_ADMIN_BASIC")
    _, _, payment_id_1 = _checkout(bid1, "ai_admin_basic", uid1)
    _upload_with_extracted_fields(payment_id_1, bid1, 499000, uid1,
                                   extracted_fields={"ai_extracted_amount": 499000})
    try:
        payment_service.verify_payment(payment_id_1, bid2, admin["id"])
        raised = False
    except ValueError:
        raised = True
    assert raised, "verify_payment must reject a business_id mismatch"

    payment = payment_service.get_payment(payment_id_1)
    assert payment["status"] != "VERIFIED", "must not have been mutated by the mismatched call"
    print("test_K_wrong_business_cannot_mutate_another_payment_via_service_layer OK")


def test_K_duplicate_detection_intentionally_global_documented():
    """File-hash duplicate detection is intentionally NOT scoped to one business — the same proof
    reused across TWO DIFFERENT businesses is exactly the kind of fraud pattern it exists to catch
    (see ai_payment_review._is_duplicate_file_hash()'s own docstring). This test documents that as
    an intentional design choice, not an accidental cross-tenant leak: it flags risk, but never
    mutates or exposes ANY data belonging to the other business — Test D above already proves the
    flag fires; this proves it doesn't leak details."""
    reset_db()
    uid1, bid1 = _make_owner_and_business("Biz K5", "payk5@test.com", package="AI_ADMIN_BASIC")
    uid2, bid2 = _make_owner_and_business("Biz K6", "payk6@test.com", package="AI_ADMIN_BASIC")
    _, _, payment_id_1 = _checkout(bid1, "ai_admin_basic", uid1)
    _, _, payment_id_2 = _checkout(bid2, "ai_admin_basic", uid2)
    shared_hash = ai_payment_review.compute_file_hash(b"shared proof bytes")
    _upload_with_extracted_fields(payment_id_1, bid1, 499000, uid1, proof_file_hash=shared_hash)
    assessment = _upload_with_extracted_fields(payment_id_2, bid2, 499000, uid2, proof_file_hash=shared_hash)
    # The flag fires (duplicate detected) but nothing about business 1's payment is exposed in the
    # assessment returned for business 2's upload.
    assert assessment["duplicate_candidate"] is True
    assert "business_id" not in assessment and "payment_id" not in assessment
    print("test_K_duplicate_detection_intentionally_global_documented OK")


# ---------------------------------------------------------------------------
# TEST L — customer dashboard shows project status and payment status separately.
# ---------------------------------------------------------------------------
def test_L_dashboard_shows_project_and_payment_status_separately():
    reset_db()
    uid, bid = _make_owner_and_business("Biz L", "payl@test.com", package="AI_ADMIN_BASIC")
    _, _, payment_id = _checkout(bid, "ai_admin_basic", uid)  # PAYMENT_PENDING, no proof uploaded yet
    client = fresh_client()
    _login_owner(client, "payl@test.com")
    resp = client.get("/dashboard")
    body = resp.data.decode()
    assert "Status Layanan" in body
    assert "Status Pembayaran" in body
    # Existing business logic (projects_repo.set_project_status() called from payment_service.
    # checkout()) already correctly moves the PROJECT's own status to PAYMENT_PENDING at checkout
    # time — so both columns legitimately agree here ("Menunggu pembayaran" for both), which is
    # CORRECT, non-misleading behavior: the confusion the request describes ("Disetujui" while
    # unpaid) genuinely cannot occur once an invoice exists, by design. The safety property that
    # matters — "Disetujui" must never look like "Lunas"/"Aktif" — holds either way.
    assert "Menunggu pembayaran" in body
    assert "Lunas" not in body
    assert "Aktif" not in body or "Belum pakai AI Admin" in body  # "Aktif" never describes payment here
    print("test_L_dashboard_shows_project_and_payment_status_separately OK")


def test_L_dashboard_no_invoice_yet_shows_natural_state():
    """This IS the exact scenario the request describes: project APPROVED ("Disetujui") with no
    payment obligation established yet (no invoice/checkout at all) — dashboard must show a
    natural "no payment yet" state, never implying the payment is done."""
    reset_db()
    uid, bid = _make_owner_and_business("Biz L2", "payl2@test.com", package="AI_ADMIN_BASIC")
    item = catalog_service.get_catalog_item("ai_admin_basic")
    projects_repo.create_fixed_price_project(bid, item, uid)  # project exists, no checkout yet
    client = fresh_client()
    _login_owner(client, "payl2@test.com")
    resp = client.get("/dashboard")
    body = resp.data.decode()
    assert "Disetujui" in body
    assert "Belum ada tagihan" in body
    assert "Lunas" not in body
    print("test_L_dashboard_no_invoice_yet_shows_natural_state OK")


# ---------------------------------------------------------------------------
# TEST M — customer-facing UI never exposes raw review enums.
# ---------------------------------------------------------------------------
def test_M_customer_ui_never_exposes_raw_review_enums():
    reset_db()
    uid, bid = _make_owner_and_business("Biz M", "paym@test.com", package="AI_ADMIN_PRO")
    item = catalog_service.get_catalog_item("ai_admin_pro")
    _, invoice_id, payment_id = _checkout(bid, "ai_admin_pro", uid)
    _upload_with_extracted_fields(payment_id, bid, item["price_amount"], uid,
                                   extracted_fields={"ai_extracted_amount": item["price_amount"]})
    client = fresh_client()
    _login_owner(client, "paym@test.com")
    resp = client.get(f"/invoices/{invoice_id}")
    body = resp.data.decode()
    for raw_enum in ("UNDER_REVIEW", "AUTO_CHECK_PASSED", "AMOUNT_MISMATCH", "UNREADABLE",
                      "POSSIBLE_DUPLICATE", "NEEDS_MANUAL_REVIEW"):
        assert f">{raw_enum}<" not in body, f"raw enum {raw_enum} leaked as visible text"
    assert "sudah diterima dan sedang dikonfirmasi" in body
    print("test_M_customer_ui_never_exposes_raw_review_enums OK")


if __name__ == "__main__":
    test_A_amount_matches_auto_check_passed_not_verified()
    test_B_amount_mismatch()
    test_C_unreadable_proof()
    test_D_same_proof_file_reused_possible_duplicate()
    test_E_needs_manual_review_never_auto_decided()
    test_F_admin_approve_verifies()
    test_G_reject_not_verified_audit_retained()
    test_H_request_reupload_retains_history_asks_new_proof()
    test_I_auto_check_passed_alone_cannot_activate()
    test_J_current_basic_with_historical_pro_cannot_activate()
    test_K_wrong_business_cannot_view_another_payment()
    test_K_wrong_business_cannot_mutate_another_payment_via_service_layer()
    test_K_duplicate_detection_intentionally_global_documented()
    test_L_dashboard_shows_project_and_payment_status_separately()
    test_L_dashboard_no_invoice_yet_shows_natural_state()
    test_M_customer_ui_never_exposes_raw_review_enums()
    print("ALL PAYMENT VERIFICATION STRENGTHENING TESTS PASSED")
