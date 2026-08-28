"""Kilas Works Client Hub — Business Hub V2, PHASES B, C, D test suite.

Covers: service catalog + custom project/request model (B), quotation + checkout + invoice +
payment workflow (C), and Talent Management V1 (D). ADDITIVE — every earlier test file is
untouched. Run with:
    cd client-hub && python3 tests/test_business_hub_v2_phase_bcd.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("DATABASE_URL", None)

import db  # noqa: E402
import repo  # noqa: E402
import security  # noqa: E402
import catalog_service  # noqa: E402
import pricing_config  # noqa: E402
import projects_repo  # noqa: E402
import quotation_service  # noqa: E402
import payment_service  # noqa: E402
import talent_service  # noqa: E402
import provisioning  # noqa: E402
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
    talent_service.seed_talents_if_needed()


def _make_owner_and_business(email="owner@test.com", package="AI_ADMIN_BASIC"):
    user_id = repo.create_user(email, security.hash_password("password123"))
    business_id = repo.create_business(user_id, "Test Biz", package=package)
    return user_id, business_id


def _make_admin():
    admin_id = repo.create_user(f"admin_{os.urandom(4).hex()}@kilasworks.id",
                                 security.hash_password("adminpass123"), role="KILAS_ADMIN")
    return db.query_one("SELECT * FROM users WHERE id = ?", (admin_id,))


# ---------------------------------------------------------------------------
# PHASE B — service catalog
# ---------------------------------------------------------------------------

def test_catalog_seeded_matches_pricing_config():
    reset_db()
    items = catalog_service.list_active_catalog()
    keys = {i["catalog_key"] for i in items}
    expected_keys = {i["key"] for i in pricing_config.CATALOG_ITEMS}
    assert keys == expected_keys
    ai_basic = catalog_service.get_catalog_item("ai_admin_basic")
    assert ai_basic["price_amount"] == 499_000
    ai_pro = catalog_service.get_catalog_item("ai_admin_pro")
    assert ai_pro["price_amount"] == 999_000
    print("test_catalog_seeded_matches_pricing_config OK")


def test_catalog_seed_is_idempotent_and_preserves_admin_edits():
    reset_db()
    item = catalog_service.get_catalog_item("website_landing_page")
    catalog_service.update_catalog_item(item["id"], price_amount=850_000)
    catalog_service.seed_catalog_if_needed()  # simulate a second app boot
    reloaded = catalog_service.get_catalog_item("website_landing_page")
    assert reloaded["price_amount"] == 850_000, "re-seeding must not clobber an admin price edit"
    print("test_catalog_seed_is_idempotent_and_preserves_admin_edits OK")


def test_custom_quote_items_have_no_public_price():
    reset_db()
    for key in ("custom_video", "custom_photo", "custom_website_app", "talent_management"):
        item = catalog_service.get_catalog_item(key)
        assert item["pricing_mode"] == "CUSTOM_QUOTE"
        assert item["price_amount"] is None
    print("test_custom_quote_items_have_no_public_price OK")


def test_fixed_price_checkout_creates_approved_project_immediately():
    reset_db()
    uid, bid = _make_owner_and_business()
    item = catalog_service.get_catalog_item("website_landing_page")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    project = projects_repo.get_project(project_id)
    assert project["status"] == "APPROVED"
    assert project["final_price"] == item["price_amount"]
    print("test_fixed_price_checkout_creates_approved_project_immediately OK")


def test_custom_video_request_saves_quantity_and_budget_no_invented_price():
    reset_db()
    uid, bid = _make_owner_and_business()
    project_id = projects_repo.create_custom_project(
        bid, "VIDEO", "5 Video Project", {"num_videos": 5, "platform": "TikTok"}, 2_000_000, 4_000_000, uid,
    )
    project = projects_repo.get_project(project_id)
    assert project["status"] == "WAITING_FOR_QUOTE"
    assert project["final_price"] is None, "system must NEVER invent a price for a custom project"
    assert project["requirements"]["num_videos"] == 5
    assert project["budget_min"] == 2_000_000 and project["budget_max"] == 4_000_000
    print("test_custom_video_request_saves_quantity_and_budget_no_invented_price OK")


def test_photo_request_saves_requirements_correctly():
    reset_db()
    uid, bid = _make_owner_and_business()
    project_id = projects_repo.create_custom_project(
        bid, "PHOTO", "Produk Photoshoot", {"photoshoot_type": "produk", "num_final_photos": 20}, 500_000, 1_500_000, uid,
    )
    project = projects_repo.get_project(project_id)
    assert project["requirements"]["photoshoot_type"] == "produk"
    assert project["requirements"]["num_final_photos"] == 20
    print("test_photo_request_saves_requirements_correctly OK")


def test_website_request_fixed_vs_custom_handling():
    reset_db()
    uid, bid = _make_owner_and_business()
    fixed_item = catalog_service.get_catalog_item("website_company_profile")
    fixed_id = projects_repo.create_fixed_price_project(bid, fixed_item, uid)
    custom_id = projects_repo.create_custom_project(bid, "APPLICATION", "Custom App", {"goal": "booking system"}, 5_000_000, 15_000_000, uid)
    fixed = projects_repo.get_project(fixed_id)
    custom = projects_repo.get_project(custom_id)
    assert fixed["pricing_mode"] == "FIXED_PRICE" and fixed["status"] == "APPROVED"
    assert custom["pricing_mode"] == "CUSTOM_QUOTE" and custom["status"] == "WAITING_FOR_QUOTE"
    print("test_website_request_fixed_vs_custom_handling OK")


def test_projects_are_tenant_isolated():
    reset_db()
    uid_a, bid_a = _make_owner_and_business("a@test.com")
    uid_b, bid_b = _make_owner_and_business("b@test.com")
    projects_repo.create_custom_project(bid_a, "VIDEO", "A's video", {}, None, None, uid_a)
    a_projects = projects_repo.list_projects_for_business(bid_a)
    b_projects = projects_repo.list_projects_for_business(bid_b)
    assert len(a_projects) == 1 and len(b_projects) == 0
    print("test_projects_are_tenant_isolated OK")


# ---------------------------------------------------------------------------
# PHASE C — quotation, checkout lock, payment
# ---------------------------------------------------------------------------

def test_checkout_locked_before_quotation_approved():
    reset_db()
    uid, bid = _make_owner_and_business()
    project_id = projects_repo.create_custom_project(bid, "VIDEO", "5 Video", {}, 2_000_000, 4_000_000, uid)
    try:
        payment_service.checkout(project_id, bid, uid)
        assert False, "checkout must be locked before quotation is approved"
    except ValueError as e:
        assert "checkout_locked" in str(e)
    print("test_checkout_locked_before_quotation_approved OK")


def test_checkout_unlocked_after_quotation_approved():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business()
    project_id = projects_repo.create_custom_project(bid, "VIDEO", "5 Video", {}, 2_000_000, 4_000_000, uid)
    quotation_id = quotation_service.create_quotation(
        project_id, bid, scope="5 video produk", deliverables="5 video final",
        quantity=5, final_price=4_200_000, notes="shooting 1 hari", created_by_user_id=admin["id"],
    )
    project = projects_repo.get_project(project_id)
    assert project["status"] == "QUOTED"

    quotation_service.approve_quotation(quotation_id, bid, uid)
    project = projects_repo.get_project(project_id)
    assert project["status"] == "APPROVED" and project["final_price"] == 4_200_000

    invoice_id = payment_service.checkout(project_id, bid, uid)
    invoice = payment_service.get_invoice(invoice_id)
    assert invoice["amount"] == 4_200_000
    print("test_checkout_unlocked_after_quotation_approved OK")


def test_quotation_reject_sends_project_back_to_waiting_for_quote():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business()
    project_id = projects_repo.create_custom_project(bid, "PHOTO", "Photo", {}, 500_000, 1_000_000, uid)
    quotation_id = quotation_service.create_quotation(project_id, bid, "scope", "deliverables", 1, 800_000, None, admin["id"])
    quotation_service.reject_quotation(quotation_id, bid, uid, note="terlalu mahal")
    project = projects_repo.get_project(project_id)
    assert project["status"] == "WAITING_FOR_QUOTE"
    q = quotation_service.get_quotation(quotation_id)
    assert q["status"] == "REJECTED"
    try:
        payment_service.checkout(project_id, bid, uid)
        assert False
    except ValueError:
        pass
    print("test_quotation_reject_sends_project_back_to_waiting_for_quote OK")


def test_full_payment_flow_verify():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business()
    item = catalog_service.get_catalog_item("website_landing_page")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    assert payment["status"] == "PAYMENT_PENDING"

    file_id = db.insert_returning_id(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'PAYMENT_PROOF', 'proof.png', "
        "'image/png', 10, ?, ?)",
        (bid, project_id, b"fakebytes", uid),
    )
    payment_service.upload_payment_proof(payment["id"], bid, file_id, uid)
    payment = payment_service.get_payment(payment["id"])
    assert payment["status"] == "UNDER_REVIEW"

    payment_service.verify_payment(payment["id"], bid, admin["id"])
    payment = payment_service.get_payment(payment["id"])
    invoice = payment_service.get_invoice(invoice_id)
    project = projects_repo.get_project(project_id)
    assert payment["status"] == "VERIFIED"
    assert invoice["status"] == "PAID"
    assert project["status"] == "PAID"
    print("test_full_payment_flow_verify OK")


def test_payment_reject_keeps_it_unverified():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business()
    item = catalog_service.get_catalog_item("event_standard")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    file_id = db.insert_returning_id(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'PAYMENT_PROOF', 'p.png', "
        "'image/png', 3, ?, ?)",
        (bid, project_id, b"abc", uid),
    )
    payment_service.upload_payment_proof(payment["id"], bid, file_id, uid)
    payment_service.reject_payment(payment["id"], bid, admin["id"], admin_notes="jumlah tidak sesuai")
    payment = payment_service.get_payment(payment["id"])
    assert payment["status"] == "REJECTED"
    print("test_payment_reject_keeps_it_unverified OK")


def test_ai_payment_review_never_claims_authentic_and_flags_mismatch():
    reset_db()
    import ai_payment_review
    assessment = ai_payment_review.assess_payment_proof(
        999, 1, invoice_amount=1_000_000, extracted_fields={
            "ai_extracted_amount": 500_000, "ai_extracted_date": None,
            "ai_extracted_bank": None, "ai_reference": "REF123",
        },
    )
    assert "AMOUNT_MISMATCH" in assessment["ai_risk_flags"]
    assert "authentic" not in str(assessment).lower()
    assert "verified" not in {k.lower() for k in assessment.keys()}
    print("test_ai_payment_review_never_claims_authentic_and_flags_mismatch OK")


def test_ai_payment_review_detects_duplicate_reference():
    reset_db()
    import ai_payment_review
    uid, bid = _make_owner_and_business()
    item = catalog_service.get_catalog_item("event_standard")
    p1 = projects_repo.create_fixed_price_project(bid, item, uid)
    inv1 = payment_service.checkout(p1, bid, uid)
    pay1 = payment_service.get_payment_for_invoice(inv1)
    db.execute("UPDATE payments SET ai_reference = ? WHERE id = ?", ("DUPREF", pay1["id"]))

    p2 = projects_repo.create_fixed_price_project(bid, item, uid)
    inv2 = payment_service.checkout(p2, bid, uid)
    pay2 = payment_service.get_payment_for_invoice(inv2)
    assessment = ai_payment_review.assess_payment_proof(
        pay2["id"], bid, invoice_amount=1_200_000,
        extracted_fields={"ai_extracted_amount": 1_200_000, "ai_extracted_date": None,
                           "ai_extracted_bank": None, "ai_reference": "DUPREF"},
    )
    assert assessment["duplicate_candidate"] is True
    print("test_ai_payment_review_detects_duplicate_reference OK")


def test_payment_detail_route_exists_and_is_admin_only():
    """Bug fix: the PAYMENT_PROOF_UPLOADED owner notification links to /admin/payments/<id> — that
    route must actually exist, show the right payment/business, embed the proof image, and be
    admin-only (a non-admin customer must get a clean access-denied result, never a broken page)."""
    reset_db()
    c = fresh_client()
    repo.create_user("padmin@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN")
    owner_id = repo.create_user("watcher@test.com", security.hash_password("password123"))
    bid = repo.create_business(owner_id, "Detail Route Biz", package="NONE")
    item = catalog_service.get_catalog_item("website_landing_page")
    project_id = projects_repo.create_fixed_price_project(bid, item, owner_id)
    invoice_id = payment_service.checkout(project_id, bid, owner_id)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    file_id = db.insert_returning_id(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'PAYMENT_PROOF', 'proof.png', "
        "'image/png', 10, ?, ?)",
        (bid, project_id, b"fakebytes", owner_id),
    )
    payment_service.upload_payment_proof(payment["id"], bid, file_id, owner_id)

    # As a logged-in admin: the page exists, loads OK, and shows the right business/payment.
    c.post("/login", data={"email": "padmin@kilasworks.id", "password": "adminpass123"})
    r = c.get(f"/admin/payments/{payment['id']}")
    assert r.status_code == 200
    assert b"Detail Route Biz" in r.data
    c.get("/logout")

    # As a logged-in non-admin customer: clean access-denied, never a broken/missing-page result.
    c.post("/login", data={"email": "watcher@test.com", "password": "password123"})
    r = c.get(f"/admin/payments/{payment['id']}")
    assert r.status_code in (302, 403)
    print("test_payment_detail_route_exists_and_is_admin_only OK")


def test_activate_tenant_blocked_when_ai_admin_invoice_unverified():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business(package="AI_ADMIN_BASIC")
    # Mirror the minimum setup provisioning.activate_tenant needs (business ready, WA connected,
    # tenant provisioned) — same helper pattern as test_production_foundation.py.
    repo.upsert_business_profile(bid, {"business_name": "Test Biz", "category": "Test", "owner_name": "X",
                                        "primary_language": "id", "customer_salutation": "Kak"})
    repo.replace_business_services(bid, ["Layanan A - 10rb"])
    repo.replace_business_faqs(bid, ["FAQ? Jawaban."])
    repo.save_ai_normalized_config(bid, "summary", {"description": "desc"}, [])
    provisioning.approve_and_provision(bid, admin)
    provisioning.connect_whatsapp_credentials(bid, admin, "555", None, "WHATSAPP_TOKEN__TEST")
    db.execute("UPDATE businesses SET whatsapp_connected = ? WHERE id = ?", (True, bid))

    ai_item = catalog_service.get_catalog_item("ai_admin_basic")
    project_id = projects_repo.create_fixed_price_project(bid, ai_item, uid)
    payment_service.checkout(project_id, bid, uid)  # unpaid invoice now exists for AI Admin

    try:
        provisioning.activate_tenant(bid, admin)
        assert False, "must not activate a tenant with an unpaid AI Admin invoice"
    except provisioning.ProvisioningError as e:
        assert "payment_not_verified" in str(e)
    print("test_activate_tenant_blocked_when_ai_admin_invoice_unverified OK")


def test_activate_tenant_blocked_with_no_invoice_at_all():
    """Bug fix (Section 22 gate): a business with LITERALLY NO invoice/payment row on record at all
    must be BLOCKED from activating as an AI Admin tenant — "no invoice" must never be treated the
    same as "already paid". This replaces the old (buggy) "backward compat" expectation that used
    to let a business activate for free simply because it had never gone through checkout."""
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business()
    repo.upsert_business_profile(bid, {"business_name": "Test Biz", "category": "Test", "owner_name": "X",
                                        "primary_language": "id", "customer_salutation": "Kak"})
    repo.replace_business_services(bid, ["Layanan A - 10rb"])
    repo.replace_business_faqs(bid, ["FAQ? Jawaban."])
    repo.save_ai_normalized_config(bid, "summary", {"description": "desc"}, [])
    provisioning.approve_and_provision(bid, admin)
    provisioning.connect_whatsapp_credentials(bid, admin, "555", None, "WHATSAPP_TOKEN__TEST")
    db.execute("UPDATE businesses SET whatsapp_connected = ? WHERE id = ?", (True, bid))
    try:
        provisioning.activate_tenant(bid, admin)
        assert False, "must not activate a tenant with no AI Admin payment record at all"
    except provisioning.ProvisioningError as e:
        assert "payment_not_verified" in str(e)
    print("test_activate_tenant_blocked_with_no_invoice_at_all OK")


def test_activate_tenant_blocked_with_rejected_payment():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business(package="AI_ADMIN_BASIC")
    repo.upsert_business_profile(bid, {"business_name": "Test Biz", "category": "Test", "owner_name": "X",
                                        "primary_language": "id", "customer_salutation": "Kak"})
    repo.replace_business_services(bid, ["Layanan A - 10rb"])
    repo.replace_business_faqs(bid, ["FAQ? Jawaban."])
    repo.save_ai_normalized_config(bid, "summary", {"description": "desc"}, [])
    provisioning.approve_and_provision(bid, admin)
    provisioning.connect_whatsapp_credentials(bid, admin, "555", None, "WHATSAPP_TOKEN__TEST")
    db.execute("UPDATE businesses SET whatsapp_connected = ? WHERE id = ?", (True, bid))

    ai_item = catalog_service.get_catalog_item("ai_admin_basic")
    project_id = projects_repo.create_fixed_price_project(bid, ai_item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    file_id = db.insert_returning_id(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'PAYMENT_PROOF', 'p.png', "
        "'image/png', 3, ?, ?)",
        (bid, project_id, b"abc", uid),
    )
    payment_service.upload_payment_proof(payment["id"], bid, file_id, uid)
    payment_service.reject_payment(payment["id"], bid, admin["id"], admin_notes="jumlah gak cocok")

    try:
        provisioning.activate_tenant(bid, admin)
        assert False, "must not activate a tenant whose only AI Admin payment was rejected"
    except provisioning.ProvisioningError as e:
        assert "payment_not_verified" in str(e)
    print("test_activate_tenant_blocked_with_rejected_payment OK")


def test_activate_tenant_blocked_with_proof_uploaded_but_not_verified():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business(package="AI_ADMIN_PRO")
    repo.upsert_business_profile(bid, {"business_name": "Test Biz", "category": "Test", "owner_name": "X",
                                        "primary_language": "id", "customer_salutation": "Kak"})
    repo.replace_business_services(bid, ["Layanan A - 10rb"])
    repo.replace_business_faqs(bid, ["FAQ? Jawaban."])
    repo.save_ai_normalized_config(bid, "summary", {"description": "desc"}, [])
    provisioning.approve_and_provision(bid, admin)
    provisioning.connect_whatsapp_credentials(bid, admin, "555", None, "WHATSAPP_TOKEN__TEST")
    db.execute("UPDATE businesses SET whatsapp_connected = ? WHERE id = ?", (True, bid))

    ai_item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, ai_item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    file_id = db.insert_returning_id(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'PAYMENT_PROOF', 'p.png', "
        "'image/png', 3, ?, ?)",
        (bid, project_id, b"abc", uid),
    )
    payment_service.upload_payment_proof(payment["id"], bid, file_id, uid)  # status -> UNDER_REVIEW, not VERIFIED

    try:
        provisioning.activate_tenant(bid, admin)
        assert False, "must not activate a tenant whose AI Admin payment proof isn't verified yet"
    except provisioning.ProvisioningError as e:
        assert "payment_not_verified" in str(e)
    print("test_activate_tenant_blocked_with_proof_uploaded_but_not_verified OK")


def test_activate_tenant_blocked_when_only_unrelated_service_payment_verified():
    """A VERIFIED payment for a different, unrelated service (e.g. a website package) must NOT
    unlock AI Admin activation."""
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business(package="AI_ADMIN_BASIC")
    repo.upsert_business_profile(bid, {"business_name": "Test Biz", "category": "Test", "owner_name": "X",
                                        "primary_language": "id", "customer_salutation": "Kak"})
    repo.replace_business_services(bid, ["Layanan A - 10rb"])
    repo.replace_business_faqs(bid, ["FAQ? Jawaban."])
    repo.save_ai_normalized_config(bid, "summary", {"description": "desc"}, [])
    provisioning.approve_and_provision(bid, admin)
    provisioning.connect_whatsapp_credentials(bid, admin, "555", None, "WHATSAPP_TOKEN__TEST")
    db.execute("UPDATE businesses SET whatsapp_connected = ? WHERE id = ?", (True, bid))

    website_item = catalog_service.get_catalog_item("website_landing_page")
    project_id = projects_repo.create_fixed_price_project(bid, website_item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    file_id = db.insert_returning_id(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'PAYMENT_PROOF', 'p.png', "
        "'image/png', 3, ?, ?)",
        (bid, project_id, b"abc", uid),
    )
    payment_service.upload_payment_proof(payment["id"], bid, file_id, uid)
    payment_service.verify_payment(payment["id"], bid, admin["id"])

    try:
        provisioning.activate_tenant(bid, admin)
        assert False, "a verified payment for an unrelated (non-AI-Admin) service must not unlock activation"
    except provisioning.ProvisioningError as e:
        assert "payment_not_verified" in str(e)
    print("test_activate_tenant_blocked_when_only_unrelated_service_payment_verified OK")


def test_already_active_ai_admin_tenant_from_before_fix_still_works():
    """A tenant that was already ACTIVE before this fix (e.g. activated back when the gate had the
    'no invoice = OK' bug, or any other pre-existing ACTIVE tenant) must not be regressed:
    activate_tenant() must stay a safe idempotent no-op for it, never re-checking payment state."""
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business()
    repo.upsert_business_profile(bid, {"business_name": "Test Biz", "category": "Test", "owner_name": "X",
                                        "primary_language": "id", "customer_salutation": "Kak"})
    repo.replace_business_services(bid, ["Layanan A - 10rb"])
    repo.replace_business_faqs(bid, ["FAQ? Jawaban."])
    repo.save_ai_normalized_config(bid, "summary", {"description": "desc"}, [])
    provisioning.approve_and_provision(bid, admin)
    provisioning.connect_whatsapp_credentials(bid, admin, "555", None, "WHATSAPP_TOKEN__TEST")
    db.execute("UPDATE businesses SET whatsapp_connected = ? WHERE id = ?", (True, bid))
    # Force ACTIVE directly, simulating a tenant that reached ACTIVE before this fix existed
    # (bypassing activate_tenant() entirely, same as a raw pre-fix DB row would look like).
    repo.activate_business(bid, admin["id"])

    result = provisioning.activate_tenant(bid, admin)
    assert result["changed"] is False and result["status"] == "ACTIVE"
    print("test_already_active_ai_admin_tenant_from_before_fix_still_works OK")


def test_activate_tenant_allowed_once_ai_admin_payment_verified():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business()
    repo.upsert_business_profile(bid, {"business_name": "Test Biz", "category": "Test", "owner_name": "X",
                                        "primary_language": "id", "customer_salutation": "Kak"})
    repo.replace_business_services(bid, ["Layanan A - 10rb"])
    repo.replace_business_faqs(bid, ["FAQ? Jawaban."])
    repo.save_ai_normalized_config(bid, "summary", {"description": "desc"}, [])
    provisioning.approve_and_provision(bid, admin)
    provisioning.connect_whatsapp_credentials(bid, admin, "555", None, "WHATSAPP_TOKEN__TEST")
    db.execute("UPDATE businesses SET whatsapp_connected = ? WHERE id = ?", (True, bid))

    ai_item = catalog_service.get_catalog_item("ai_admin_basic")
    project_id = projects_repo.create_fixed_price_project(bid, ai_item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    file_id = db.insert_returning_id(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'PAYMENT_PROOF', 'p.png', "
        "'image/png', 3, ?, ?)",
        (bid, project_id, b"abc", uid),
    )
    payment_service.upload_payment_proof(payment["id"], bid, file_id, uid)
    payment_service.verify_payment(payment["id"], bid, admin["id"])

    result = provisioning.activate_tenant(bid, admin)
    assert result["changed"] is True and result["status"] == "ACTIVE"
    print("test_activate_tenant_allowed_once_ai_admin_payment_verified OK")


def test_activate_tenant_allowed_once_ai_admin_pro_payment_verified():
    """Same as the Basic case above, for the Pro plan — a business that starts at package='NONE',
    buys AI Admin Pro, and gets a VERIFIED payment must be recognized as active-eligible."""
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business(package="NONE")
    repo.upgrade_business_package(bid, "AI_ADMIN_PRO", uid)
    assert repo.get_business(bid)["package"] == "AI_ADMIN_PRO"  # plan updates off of NONE immediately

    repo.upsert_business_profile(bid, {"business_name": "Test Biz Pro", "category": "Test", "owner_name": "X",
                                        "primary_language": "id", "customer_salutation": "Kak"})
    repo.replace_business_services(bid, ["Layanan A - 10rb"])
    repo.replace_business_faqs(bid, ["FAQ? Jawaban."])
    repo.save_ai_normalized_config(bid, "summary", {"description": "desc"}, [])
    provisioning.approve_and_provision(bid, admin)
    provisioning.connect_whatsapp_credentials(bid, admin, "556", None, "WHATSAPP_TOKEN__TEST_PRO")
    db.execute("UPDATE businesses SET whatsapp_connected = ? WHERE id = ?", (True, bid))

    ai_item = catalog_service.get_catalog_item("ai_admin_pro")
    project_id = projects_repo.create_fixed_price_project(bid, ai_item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    file_id = db.insert_returning_id(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'PAYMENT_PROOF', 'p.png', "
        "'image/png', 3, ?, ?)",
        (bid, project_id, b"abc", uid),
    )
    payment_service.upload_payment_proof(payment["id"], bid, file_id, uid)
    payment_service.verify_payment(payment["id"], bid, admin["id"])

    result = provisioning.activate_tenant(bid, admin)
    assert result["changed"] is True and result["status"] == "ACTIVE"
    print("test_activate_tenant_allowed_once_ai_admin_pro_payment_verified OK")


def test_package_stays_none_while_payment_pending_and_activation_stays_blocked():
    """Section 22 lifecycle: package='NONE' -> customer picks Basic -> order created -> payment
    PENDING (no proof yet) -> activation must be blocked (package already flipped off of NONE, but
    that alone must never be enough to activate)."""
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business(package="NONE")
    repo.upgrade_business_package(bid, "AI_ADMIN_BASIC", uid)

    repo.upsert_business_profile(bid, {"business_name": "Test Biz", "category": "Test", "owner_name": "X",
                                        "primary_language": "id", "customer_salutation": "Kak"})
    repo.replace_business_services(bid, ["Layanan A - 10rb"])
    repo.replace_business_faqs(bid, ["FAQ? Jawaban."])
    repo.save_ai_normalized_config(bid, "summary", {"description": "desc"}, [])
    provisioning.approve_and_provision(bid, admin)
    provisioning.connect_whatsapp_credentials(bid, admin, "557", None, "WHATSAPP_TOKEN__TEST_NONE_TO_BASIC")
    db.execute("UPDATE businesses SET whatsapp_connected = ? WHERE id = ?", (True, bid))

    ai_item = catalog_service.get_catalog_item("ai_admin_basic")
    project_id = projects_repo.create_fixed_price_project(bid, ai_item, uid)
    payment_service.checkout(project_id, bid, uid)  # PAYMENT_PENDING, no proof uploaded yet

    assert repo.get_business(bid)["package"] == "AI_ADMIN_BASIC"
    try:
        provisioning.activate_tenant(bid, admin)
        assert False, "must not activate while payment is still PAYMENT_PENDING"
    except provisioning.ProvisioningError as e:
        assert "payment_not_verified" in str(e)
    print("test_package_stays_none_while_payment_pending_and_activation_stays_blocked OK")


# ---------------------------------------------------------------------------
# PHASE D — Talent Management
# ---------------------------------------------------------------------------

def test_three_seed_talents_visible():
    reset_db()
    talents = talent_service.list_active_talents()
    names = {t["name"] for t in talents}
    assert names == {"Putri Maudy", "Irene Agustine Moire", "Bimo Putra Dwitya"}
    for t in talents:
        assert t["pricing_mode"] == "CUSTOM_QUOTE"
    print("test_three_seed_talents_visible OK")


def test_admin_edits_follower_count_persist_and_not_realtime():
    reset_db()
    putri = db.query_one("SELECT * FROM talents WHERE name = 'Putri Maudy'")
    assert putri["follower_count"] == 186_000
    talent_service.update_talent(putri["id"], follower_count=200_000)
    talent_service.seed_talents_if_needed()  # simulate reboot — must not reset the admin's edit
    reloaded = talent_service.get_talent(putri["id"])
    assert reloaded["follower_count"] == 200_000
    print("test_admin_edits_follower_count_persist_and_not_realtime OK")


def test_admin_edits_handle_niche_and_profile_photo_url_persist():
    """Business Hub V2 Production Integration, Section 6 gap-fix: the spec explicitly lists
    'handle, niche, ... profile photo' among the fields KILAS_ADMIN can edit. These previously
    existed only in talent_service.update_talent()'s whitelist but were never wired up through the
    admin route/template — covering that here so a regression can't silently reopen the gap."""
    reset_db()
    putri = db.query_one("SELECT * FROM talents WHERE name = 'Putri Maudy'")
    assert putri["profile_photo_url"] is None  # column is new and starts empty for seeded talents
    talent_service.update_talent(
        putri["id"],
        social_handle="@pm_new_handle",
        niche="Fashion & Beauty",
        profile_photo_url="https://example.com/putri.jpg",
    )
    reloaded = talent_service.get_talent(putri["id"])
    assert reloaded["social_handle"] == "@pm_new_handle"
    assert reloaded["niche"] == "Fashion & Beauty"
    assert reloaded["profile_photo_url"] == "https://example.com/putri.jpg"
    print("test_admin_edits_handle_niche_and_profile_photo_url_persist OK")


def test_admin_talent_update_route_accepts_handle_niche_photo_url():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    client.post("/login", data={"email": admin["email"], "password": "adminpass123"})
    putri = db.query_one("SELECT * FROM talents WHERE name = 'Putri Maudy'")
    resp = client.post(f"/admin/talent/{putri['id']}/update", data={
        "social_handle": "@pm_via_route",
        "niche": "Automotive",
        "profile_photo_url": "https://example.com/pm_via_route.png",
        "follower_count": "190000",
        "availability_status": "AVAILABLE",
    })
    assert resp.status_code == 302
    reloaded = talent_service.get_talent(putri["id"])
    assert reloaded["social_handle"] == "@pm_via_route"
    assert reloaded["niche"] == "Automotive"
    assert reloaded["profile_photo_url"] == "https://example.com/pm_via_route.png"
    assert reloaded["follower_count"] == 190000
    print("test_admin_talent_update_route_accepts_handle_niche_photo_url OK")


def test_client_cannot_edit_talent_route_requires_admin():
    reset_db()
    client = fresh_client()
    repo.create_user("client_talent@test.com", security.hash_password("password123"))
    client.post("/login", data={"email": "client_talent@test.com", "password": "password123"})
    putri = db.query_one("SELECT * FROM talents WHERE name = 'Putri Maudy'")
    resp = client.post(f"/admin/talent/{putri['id']}/update", data={"follower_count": "999999"})
    assert resp.status_code == 403
    reloaded = talent_service.get_talent(putri["id"])
    assert reloaded["follower_count"] == 186_000
    print("test_client_cannot_edit_talent_route_requires_admin OK")


def test_talent_request_creates_request_and_linked_project():
    reset_db()
    uid, bid = _make_owner_and_business()
    putri = db.query_one("SELECT * FROM talents WHERE name = 'Putri Maudy'")
    request_id, project_id = talent_service.create_talent_request(
        putri["id"], bid, {"campaign_type": "Product launch", "budget": 5_000_000}, uid,
    )
    req = talent_service.get_talent_request(request_id)
    assert req["status"] == "WAITING_FOR_REVIEW"
    project = projects_repo.get_project(project_id)
    assert project["project_type"] == "TALENT" and project["pricing_mode"] == "CUSTOM_QUOTE"
    assert project["final_price"] is None
    print("test_talent_request_creates_request_and_linked_project OK")


def test_talent_request_then_quotation_then_checkout_flow():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business()
    putri = db.query_one("SELECT * FROM talents WHERE name = 'Putri Maudy'")
    _, project_id = talent_service.create_talent_request(putri["id"], bid, {"budget": 5_000_000}, uid)
    quotation_id = quotation_service.create_quotation(project_id, bid, "1x collab post", "1 feed + 1 story", 1, 5_500_000, None, admin["id"])
    quotation_service.approve_quotation(quotation_id, bid, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    invoice = payment_service.get_invoice(invoice_id)
    assert invoice["amount"] == 5_500_000
    print("test_talent_request_then_quotation_then_checkout_flow OK")


if __name__ == "__main__":
    test_catalog_seeded_matches_pricing_config()
    test_catalog_seed_is_idempotent_and_preserves_admin_edits()
    test_custom_quote_items_have_no_public_price()
    test_fixed_price_checkout_creates_approved_project_immediately()
    test_custom_video_request_saves_quantity_and_budget_no_invented_price()
    test_photo_request_saves_requirements_correctly()
    test_website_request_fixed_vs_custom_handling()
    test_projects_are_tenant_isolated()
    test_checkout_locked_before_quotation_approved()
    test_checkout_unlocked_after_quotation_approved()
    test_quotation_reject_sends_project_back_to_waiting_for_quote()
    test_full_payment_flow_verify()
    test_payment_reject_keeps_it_unverified()
    test_ai_payment_review_never_claims_authentic_and_flags_mismatch()
    test_ai_payment_review_detects_duplicate_reference()
    test_payment_detail_route_exists_and_is_admin_only()
    test_activate_tenant_blocked_when_ai_admin_invoice_unverified()
    test_activate_tenant_blocked_with_no_invoice_at_all()
    test_activate_tenant_blocked_with_rejected_payment()
    test_activate_tenant_blocked_with_proof_uploaded_but_not_verified()
    test_activate_tenant_blocked_when_only_unrelated_service_payment_verified()
    test_already_active_ai_admin_tenant_from_before_fix_still_works()
    test_activate_tenant_allowed_once_ai_admin_payment_verified()
    test_activate_tenant_allowed_once_ai_admin_pro_payment_verified()
    test_package_stays_none_while_payment_pending_and_activation_stays_blocked()
    test_three_seed_talents_visible()
    test_admin_edits_follower_count_persist_and_not_realtime()
    test_admin_edits_handle_niche_and_profile_photo_url_persist()
    test_admin_talent_update_route_accepts_handle_niche_photo_url()
    test_client_cannot_edit_talent_route_requires_admin()
    test_talent_request_creates_request_and_linked_project()
    test_talent_request_then_quotation_then_checkout_flow()
    print("\nALL BUSINESS HUB V2 PHASE B/C/D TESTS PASSED")
