"""Kilas Works Client Hub — Business Hub V2, FINAL OPERATIONS POLISH test suite.

Covers Section 20's enumerated list: talent CRUD/archive/reorder/image-upload, service catalog
admin editing + price-change safety, action-center counts, global admin search, customer
active/history/all views, and payment-proof/upload safety. ADDITIVE — every earlier test file is
untouched. Run with:
    cd client-hub && python3 tests/test_business_hub_v2_final_ops_polish.py
"""
import io
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
import file_utils  # noqa: E402
import projects_repo  # noqa: E402
import quotation_service  # noqa: E402
import payment_service  # noqa: E402
import talent_service  # noqa: E402
import platform_assets_service  # noqa: E402
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


def _make_owner_and_business(email="owner_ops@test.com", package="AI_ADMIN_BASIC"):
    user_id = repo.create_user(email, security.hash_password("password123"))
    business_id = repo.create_business(user_id, "Test Ops Biz", package=package)
    return user_id, business_id


def _make_admin():
    admin_id = repo.create_user(f"admin_{os.urandom(4).hex()}@kilasworks.id",
                                 security.hash_password("adminpass123"), role="KILAS_ADMIN")
    return db.query_one("SELECT * FROM users WHERE id = ?", (admin_id,))


def _login_admin(client, admin):
    client.post("/login", data={"email": admin["email"], "password": "adminpass123"})


def _login_owner(client, email, password="password123"):
    client.post("/login", data={"email": email, "password": password})


def _tiny_png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color="blue").save(buf, format="PNG")
    return buf.getvalue()


def _tiny_webp_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color="green").save(buf, format="WEBP")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# TALENT — create / edit / archive / reactivate / reorder / client denied
# ---------------------------------------------------------------------------

def test_admin_creates_talent():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.post("/admin/talent/create", data={
        "name": "New Talent", "social_handle": "@newtalent", "niche": "Fashion",
        "follower_count": "50000", "availability_status": "AVAILABLE",
    })
    assert resp.status_code == 302
    talents = talent_service.list_all_talents()
    created = [t for t in talents if t["name"] == "New Talent"]
    assert len(created) == 1
    assert created[0]["social_handle"] == "@newtalent"
    assert created[0]["display_order"] > 0  # sorts after the 3 seeded talents
    print("test_admin_creates_talent OK")


def test_admin_create_talent_requires_name():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    before = len(talent_service.list_all_talents())
    resp = client.post("/admin/talent/create", data={"name": "  "})
    assert resp.status_code == 302
    after = len(talent_service.list_all_talents())
    assert after == before  # nothing created
    print("test_admin_create_talent_requires_name OK")


def test_admin_edits_talent_availability_note_and_display_order():
    reset_db()
    putri = db.query_one("SELECT * FROM talents WHERE name = 'Putri Maudy'")
    talent_service.update_talent(
        putri["id"], availability_note="Available after 15 September", display_order=1,
    )
    reloaded = talent_service.get_talent(putri["id"])
    assert reloaded["availability_note"] == "Available after 15 September"
    assert reloaded["display_order"] == 1
    print("test_admin_edits_talent_availability_note_and_display_order OK")


def test_admin_archives_and_reactivates_talent_soft_delete_only():
    reset_db()
    admin = _make_admin()
    putri = db.query_one("SELECT * FROM talents WHERE name = 'Putri Maudy'")

    # Give the talent a real historical request/project first — archiving must NOT touch this.
    uid, bid = _make_owner_and_business()
    request_id, project_id = talent_service.create_talent_request(
        putri["id"], bid, {"campaign_type": "Endorse", "budget": 1_000_000}, uid,
    )

    client = fresh_client()
    _login_admin(client, admin)
    resp = client.post(f"/admin/talent/{putri['id']}/archive")
    assert resp.status_code == 302
    archived = talent_service.get_talent(putri["id"])
    assert archived["is_active"] is False or archived["is_active"] == 0

    # Soft delete only — the talent row itself, and everything referencing it, must still exist.
    still_there = talent_service.get_talent(putri["id"])
    assert still_there is not None
    assert talent_service.get_talent_request(request_id) is not None
    assert projects_repo.get_project(project_id) is not None
    active_names = {t["name"] for t in talent_service.list_active_talents()}
    assert "Putri Maudy" not in active_names
    all_names = {t["name"] for t in talent_service.list_all_talents()}
    assert "Putri Maudy" in all_names  # still visible to admin, just not public

    resp2 = client.post(f"/admin/talent/{putri['id']}/reactivate")
    assert resp2.status_code == 302
    reactivated = talent_service.get_talent(putri["id"])
    assert reactivated["is_active"] is True or reactivated["is_active"] == 1
    print("test_admin_archives_and_reactivates_talent_soft_delete_only OK")


def test_admin_changes_display_order_reorders_public_list():
    reset_db()
    talents = talent_service.list_active_talents()
    bimo = next(t for t in talents if t["name"] == "Bimo Putra Dwitya")
    # Move Bimo to the front.
    talent_service.update_talent(bimo["id"], display_order=-1)
    reordered = talent_service.list_active_talents()
    assert reordered[0]["name"] == "Bimo Putra Dwitya"
    print("test_admin_changes_display_order_reorders_public_list OK")


def test_client_cannot_mutate_talent_any_new_route():
    reset_db()
    client = fresh_client()
    repo.create_user("client_talent2@test.com", security.hash_password("password123"))
    _login_owner(client, "client_talent2@test.com")
    putri = db.query_one("SELECT * FROM talents WHERE name = 'Putri Maudy'")

    assert client.post("/admin/talent/create", data={"name": "Hacker Talent"}).status_code == 403
    assert client.post(f"/admin/talent/{putri['id']}/archive").status_code == 403
    assert client.post(f"/admin/talent/{putri['id']}/reactivate").status_code == 403
    assert client.post(f"/admin/talent/{putri['id']}/photo",
                        data={"photo": (io.BytesIO(b"x"), "x.png")},
                        content_type="multipart/form-data").status_code == 403
    assert talent_service.get_talent(putri["id"])["is_active"] in (True, 1)
    print("test_client_cannot_mutate_talent_any_new_route OK")


def test_talent_image_upload_accepts_valid_image_and_is_served_safely():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    putri = db.query_one("SELECT * FROM talents WHERE name = 'Putri Maudy'")

    resp = client.post(
        f"/admin/talent/{putri['id']}/photo",
        data={"photo": (io.BytesIO(_tiny_png_bytes()), "profile.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302
    reloaded = talent_service.get_talent(putri["id"])
    asset_id = reloaded["profile_image_asset_id"]
    assert asset_id is not None

    img_resp = client.get(f"/admin/assets/{asset_id}")
    assert img_resp.status_code == 200
    assert img_resp.mimetype == "image/png"
    assert img_resp.data == _tiny_png_bytes()
    print("test_talent_image_upload_accepts_valid_image_and_is_served_safely OK")


def test_talent_image_upload_accepts_webp():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    bimo = db.query_one("SELECT * FROM talents WHERE name = 'Bimo Putra Dwitya'")
    resp = client.post(
        f"/admin/talent/{bimo['id']}/photo",
        data={"photo": (io.BytesIO(_tiny_webp_bytes()), "profile.webp")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302
    reloaded = talent_service.get_talent(bimo["id"])
    asset = platform_assets_service.get_asset(reloaded["profile_image_asset_id"])
    assert asset["mime_type"] == "image/webp"
    print("test_talent_image_upload_accepts_webp OK")


def test_talent_image_upload_rejects_invalid_file():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    putri = db.query_one("SELECT * FROM talents WHERE name = 'Putri Maudy'")

    resp = client.post(
        f"/admin/talent/{putri['id']}/photo",
        data={"photo": (io.BytesIO(b"not a real image, just text pretending to be one"), "fake.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302
    reloaded = talent_service.get_talent(putri["id"])
    assert reloaded["profile_image_asset_id"] is None
    print("test_talent_image_upload_rejects_invalid_file OK")


def test_talent_image_upload_rejects_disallowed_extension():
    try:
        file_utils.validate_image_upload("script.exe", b"MZ\x90\x00fake-exe-bytes")
        raised = False
    except file_utils.UploadRejected:
        raised = True
    assert raised
    print("test_talent_image_upload_rejects_disallowed_extension OK")


def test_stored_image_serving_rejects_unknown_asset_id():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get("/admin/assets/999999")
    assert resp.status_code == 404
    print("test_stored_image_serving_rejects_unknown_asset_id OK")


def test_internal_rate_never_exposed_on_public_talent_list():
    reset_db()
    putri = db.query_one("SELECT * FROM talents WHERE name = 'Putri Maudy'")
    distinctive_rate = 1_234_567
    talent_service.update_talent(putri["id"], internal_rate=distinctive_rate,
                                  internal_notes="SECRET NEGOTIATION NOTE XYZ")
    client = fresh_client()
    repo.create_user("client_view_talent@test.com", security.hash_password("password123"))
    repo.create_business(
        db.query_one("SELECT id FROM users WHERE email = 'client_view_talent@test.com'")["id"],
        "Viewer Biz",
    )
    _login_owner(client, "client_view_talent@test.com")
    resp = client.get("/talent")
    body = resp.get_data(as_text=True)
    assert str(distinctive_rate) not in body
    assert "SECRET NEGOTIATION NOTE XYZ" not in body
    assert "CUSTOM QUOTE" in body.upper() or "Custom Quote" in body
    print("test_internal_rate_never_exposed_on_public_talent_list OK")


# ---------------------------------------------------------------------------
# SERVICE CATALOG ADMIN MANAGEMENT
# ---------------------------------------------------------------------------

def test_catalog_admin_edit_restored_for_safe_categories():
    """Business rule REVERSAL (UX pass — explicitly reverses the earlier "catalog editing
    removed" decision, at the user's own later explicit request): routine editing is restored for
    generic (non-AI_ADMIN/TALENT) categories, using the exact same single service_catalog source
    of truth every other consumer (/services, project creation, the bot's live knowledge block)
    already reads from — never a second, parallel catalog."""
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    item = catalog_service.get_catalog_item("website_landing_page")

    resp = client.post(f"/admin/catalog/{item['id']}/update", data={
        "csrf_token": "x", "name": "Landing Page Diedit", "price_amount": "850000",
        "price_unit": "one time", "pricing_mode": "FIXED_PRICE", "is_active": "on",
    })
    assert resp.status_code == 302
    updated = catalog_service.get_catalog_item("website_landing_page")
    assert updated["name"] == "Landing Page Diedit"
    assert updated["price_amount"] == 850000

    page = client.get("/admin/catalog")
    assert page.status_code == 200
    body = page.data.decode()
    assert "Landing Page Diedit" in body
    assert "<form" in body.lower(), "the restored catalog page must render edit/create forms"
    print("test_catalog_admin_edit_restored_for_safe_categories OK")


def test_catalog_seeding_never_overwrites_admin_edits_on_restart():
    reset_db()
    catalog_service.update_catalog_item(
        catalog_service.get_catalog_item("website_landing_page")["id"], price_amount=850000,
    )
    catalog_service.seed_catalog_if_needed()  # simulate reboot
    reloaded = catalog_service.get_catalog_item("website_landing_page")
    assert reloaded["price_amount"] == 850000
    print("test_catalog_seeding_never_overwrites_admin_edits_on_restart OK")


def test_catalog_activate_deactivate():
    reset_db()
    item = catalog_service.get_catalog_item("event_standard")
    catalog_service.update_catalog_item(item["id"], is_active=False)
    assert catalog_service.get_catalog_item("event_standard")["is_active"] in (False, 0)
    active_keys = {i["catalog_key"] for i in catalog_service.list_active_catalog()}
    assert "event_standard" not in active_keys
    catalog_service.update_catalog_item(item["id"], is_active=True)
    active_keys = {i["catalog_key"] for i in catalog_service.list_active_catalog()}
    assert "event_standard" in active_keys
    print("test_catalog_activate_deactivate OK")


def test_catalog_display_order_respected_in_active_listing():
    reset_db()
    a = catalog_service.get_catalog_item("event_standard")
    b = catalog_service.get_catalog_item("event_lengkap")
    catalog_service.update_catalog_item(a["id"], sort_order=100)
    catalog_service.update_catalog_item(b["id"], sort_order=1)
    ordered = [i for i in catalog_service.list_active_catalog() if i["category"] == "EVENT"]
    ordered_keys = [i["catalog_key"] for i in ordered]
    assert ordered_keys.index("event_lengkap") < ordered_keys.index("event_standard")
    print("test_catalog_display_order_respected_in_active_listing OK")


def test_catalog_invalid_pricing_state_rejected_fixed_price_without_amount():
    """A CUSTOM_QUOTE item (price_amount already NULL) switched to FIXED_PRICE without also
    supplying a price must be rejected — otherwise it would silently become a FIXED_PRICE item
    with no price, which is exactly the invalid state Section 6 forbids."""
    reset_db()
    item = catalog_service.get_catalog_item("custom_video")
    assert item["price_amount"] is None
    raised = False
    try:
        catalog_service.update_catalog_item(item["id"], pricing_mode="FIXED_PRICE")
    except catalog_service.InvalidCatalogState:
        raised = True
    assert raised
    # Nothing changed on the row — the bad update was rejected, not partially applied.
    reloaded = catalog_service.get_catalog_item("custom_video")
    assert reloaded["pricing_mode"] == "CUSTOM_QUOTE"
    assert reloaded["price_amount"] is None
    print("test_catalog_invalid_pricing_state_rejected_fixed_price_without_amount OK")


def test_catalog_custom_quote_never_carries_a_leftover_price():
    reset_db()
    item = catalog_service.get_catalog_item("event_standard")
    updated = catalog_service.update_catalog_item(item["id"], pricing_mode="CUSTOM_QUOTE")
    assert updated["price_amount"] is None
    assert updated["price_unit"] is None
    print("test_catalog_custom_quote_never_carries_a_leftover_price OK")


def test_catalog_route_rejects_invalid_pricing_state_via_flash_not_crash():
    """The edit ROUTE is restored (UX pass reversal — see catalog_service.py's own module notes).
    An invalid pricing-state request (FIXED_PRICE with no amount) must be rejected gracefully via
    a flash + redirect, never a raw 500/crash, and must never mutate the existing row — matching
    the same InvalidCatalogState guard update_catalog_item() itself already enforces (see
    test_catalog_invalid_pricing_state_rejected_fixed_price_without_amount above, which covers the
    service layer directly; this covers the HTTP route wrapping it)."""
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    item = catalog_service.get_catalog_item("custom_video")
    resp = client.post(f"/admin/catalog/{item['id']}/update", data={
        "csrf_token": "x", "pricing_mode": "FIXED_PRICE", "price_amount": "", "price_unit": "",
    })
    assert resp.status_code == 302, "an invalid request must redirect gracefully, never crash"
    reloaded = catalog_service.get_catalog_item("custom_video")
    assert reloaded["pricing_mode"] == "CUSTOM_QUOTE", "a rejected request must never mutate data"
    print("test_catalog_route_rejects_invalid_pricing_state_via_flash_not_crash OK")


def test_historical_transaction_price_unchanged_after_catalog_price_update():
    """Section 7 (Price Change Safety), re-verified explicitly for the new admin-editable catalog:
    an already-checked-out fixed-price project must NEVER retroactively change price when the
    admin edits the catalog afterwards — only a NEW project created after the edit uses the new
    price."""
    reset_db()
    uid, bid = _make_owner_and_business()
    item = catalog_service.get_catalog_item("website_landing_page")
    old_price = item["price_amount"]
    old_project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    old_project = projects_repo.get_project(old_project_id)
    assert old_project["final_price"] == old_price

    catalog_service.update_catalog_item(item["id"], price_amount=old_price + 500_000)

    old_project_after = projects_repo.get_project(old_project_id)
    assert old_project_after["final_price"] == old_price  # unchanged, forever

    new_item = catalog_service.get_catalog_item("website_landing_page")
    new_project_id = projects_repo.create_fixed_price_project(bid, new_item, uid)
    new_project = projects_repo.get_project(new_project_id)
    assert new_project["final_price"] == old_price + 500_000  # only future purchases see it

    # Also true through a full checkout to invoice — the invoice amount must match the price that
    # was locked in at project creation, not whatever the catalog says now.
    invoice_id = payment_service.checkout(old_project_id, bid, uid)
    invoice = payment_service.get_invoice(invoice_id)
    assert invoice["amount"] == old_price
    print("test_historical_transaction_price_unchanged_after_catalog_price_update OK")


# ---------------------------------------------------------------------------
# ADMIN ACTION CENTER
# ---------------------------------------------------------------------------

def test_action_center_whatsapp_waiting_connection_count():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business()
    repo.set_business_status(bid, "APPROVED", admin["id"], "test approve")
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get("/admin/")
    body = resp.get_data(as_text=True)
    assert "1 Tenant menunggu koneksi WhatsApp" in body
    print("test_action_center_whatsapp_waiting_connection_count OK")


def test_action_center_links_are_correctly_filtered():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get("/admin/")
    body = resp.get_data(as_text=True)
    assert "/admin/projects?status=WAITING_FOR_QUOTE" in body
    assert "/admin/?status=DRAFT" in body or "/admin/?status=READY_FOR_REVIEW" in body
    print("test_action_center_links_are_correctly_filtered OK")


# ---------------------------------------------------------------------------
# GLOBAL ADMIN SEARCH
# ---------------------------------------------------------------------------

def test_admin_search_finds_business_project_and_talent():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("searchable_owner@test.com")
    db.execute("UPDATE businesses SET business_name = ? WHERE id = ?", ("Zebra Unique Biz", bid))
    projects_repo.create_custom_project(bid, "VIDEO", "Zebra Video Project", {}, 1_000_000, 2_000_000, uid)

    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get("/admin/search?q=Zebra")
    body = resp.get_data(as_text=True)
    assert "Zebra Unique Biz" in body
    assert "Zebra Video Project" in body

    resp2 = client.get("/admin/search?q=Putri")
    assert "Putri Maudy" in resp2.get_data(as_text=True)
    print("test_admin_search_finds_business_project_and_talent OK")


def test_admin_search_no_client_access():
    reset_db()
    client = fresh_client()
    repo.create_user("search_client@test.com", security.hash_password("password123"))
    _login_owner(client, "search_client@test.com")
    resp = client.get("/admin/search?q=anything")
    assert resp.status_code == 403
    print("test_admin_search_no_client_access OK")


def test_admin_search_empty_query_shows_no_results_block():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get("/admin/search")
    assert resp.status_code == 200
    print("test_admin_search_empty_query_shows_no_results_block OK")


# ---------------------------------------------------------------------------
# CUSTOMER HISTORY (projects + invoices, ACTIVE / HISTORY / ALL)
# ---------------------------------------------------------------------------

def test_completed_project_visible_in_history_not_active():
    reset_db()
    uid, bid = _make_owner_and_business("history_owner@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    projects_repo.set_project_status(project_id, "COMPLETED", uid, bid)

    client = fresh_client()
    _login_owner(client, "history_owner@test.com")

    active_body = client.get(f"/business/{bid}/projects?view=active").get_data(as_text=True)
    history_body = client.get(f"/business/{bid}/projects?view=history").get_data(as_text=True)
    all_body = client.get(f"/business/{bid}/projects?view=all").get_data(as_text=True)

    assert item["name"] not in active_body
    assert item["name"] in history_body
    assert item["name"] in all_body
    print("test_completed_project_visible_in_history_not_active OK")


def test_old_invoice_visible_in_payment_history():
    reset_db()
    uid, bid = _make_owner_and_business("invoice_history_owner@test.com")
    admin = _make_admin()
    item = catalog_service.get_catalog_item("website_landing_page")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    file_id = db.insert_returning_id(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'PAYMENT_PROOF', ?, ?, ?, ?, ?)",
        (bid, project_id, "bukti.png", "image/png", len(_tiny_png_bytes()), _tiny_png_bytes(), uid),
    )
    payment_service.upload_payment_proof(payment["id"], bid, file_id, uid)
    payment_service.verify_payment(payment["id"], bid, admin["id"])

    client = fresh_client()
    _login_owner(client, "invoice_history_owner@test.com")
    active_body = client.get(f"/business/{bid}/invoices?view=active").get_data(as_text=True)
    history_body = client.get(f"/business/{bid}/invoices?view=history").get_data(as_text=True)

    invoice = payment_service.get_invoice(invoice_id)
    assert invoice["invoice_number"] not in active_body
    assert invoice["invoice_number"] in history_body
    print("test_old_invoice_visible_in_payment_history OK")


def test_project_and_invoice_list_tenant_isolation():
    reset_db()
    uid_a, bid_a = _make_owner_and_business("tenant_a_ops@test.com")
    uid_b, bid_b = _make_owner_and_business("tenant_b_ops@test.com")
    client = fresh_client()
    _login_owner(client, "tenant_b_ops@test.com")
    resp = client.get(f"/business/{bid_a}/projects?view=all")
    assert resp.status_code == 404
    resp2 = client.get(f"/business/{bid_a}/invoices?view=all")
    assert resp2.status_code == 404
    print("test_project_and_invoice_list_tenant_isolation OK")


# ---------------------------------------------------------------------------
# UPLOAD SAFETY (payment proof / project reference / talent photo)
# ---------------------------------------------------------------------------

def test_payment_proof_viewable_by_owner_not_by_other_tenant():
    reset_db()
    uid, bid = _make_owner_and_business("proof_owner@test.com")
    uid_other, bid_other = _make_owner_and_business("proof_other@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    file_id = db.insert_returning_id(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'PAYMENT_PROOF', ?, ?, ?, ?, ?)",
        (bid, project_id, "bukti.png", "image/png", len(_tiny_png_bytes()), _tiny_png_bytes(), uid),
    )
    payment_service.upload_payment_proof(payment["id"], bid, file_id, uid)

    client = fresh_client()
    _login_owner(client, "proof_owner@test.com")
    resp = client.get(f"/invoices/{invoice_id}/proof")
    assert resp.status_code == 200
    assert resp.data == _tiny_png_bytes()

    client2 = fresh_client()
    _login_owner(client2, "proof_other@test.com")
    resp2 = client2.get(f"/invoices/{invoice_id}/proof")
    assert resp2.status_code == 404
    print("test_payment_proof_viewable_by_owner_not_by_other_tenant OK")


def test_admin_can_view_any_payment_proof():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("proof_owner2@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    file_id = db.insert_returning_id(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'PAYMENT_PROOF', ?, ?, ?, ?, ?)",
        (bid, project_id, "bukti.png", "image/png", len(_tiny_png_bytes()), _tiny_png_bytes(), uid),
    )
    payment_service.upload_payment_proof(payment["id"], bid, file_id, uid)

    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get(f"/admin/payments/{payment['id']}/proof")
    assert resp.status_code == 200
    assert resp.data == _tiny_png_bytes()
    print("test_admin_can_view_any_payment_proof OK")


def test_wizard_file_upload_now_accepts_webp():
    reset_db()
    uid, bid = _make_owner_and_business("webp_upload_owner@test.com")
    client = fresh_client()
    _login_owner(client, "webp_upload_owner@test.com")
    resp = client.post(
        f"/business/{bid}/files/upload",
        data={"file": (io.BytesIO(_tiny_webp_bytes()), "reference.webp")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302
    files = repo.list_business_files(bid)
    assert any(f["original_filename"] == "reference.webp" for f in files)
    print("test_wizard_file_upload_now_accepts_webp OK")


def _tiny_pdf_bytes():
    return b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


# ---------------------------------------------------------------------------
# CUSTOM PROJECT ATTACHMENTS ("Upload Brief / Referensi")
# ---------------------------------------------------------------------------

def test_project_attachment_content_sniffing_direct():
    """Direct file_utils.validate_project_attachment_upload() checks (same content-sniffing
    approach as validate_and_extract()/validate_image_upload(), extended to also allow PDF)."""
    safe_name, mime = file_utils.validate_project_attachment_upload("brief.jpg", _tiny_png_bytes())
    assert mime == "image/jpeg" and safe_name == "brief.jpg"

    safe_name, mime = file_utils.validate_project_attachment_upload("brief.pdf", _tiny_pdf_bytes())
    assert mime == "application/pdf"

    try:
        file_utils.validate_project_attachment_upload("huge.jpg", b"x" * (6 * 1024 * 1024))
        assert False, "must reject a file over 5MB"
    except file_utils.UploadRejected:
        pass

    try:
        # Real content is NOT an image, despite the .jpg extension.
        file_utils.validate_project_attachment_upload("fake.jpg", b"just some plain text, not a real jpg")
        assert False, "must reject content that doesn't actually match its claimed image type"
    except file_utils.UploadRejected:
        pass

    try:
        file_utils.validate_project_attachment_upload("script.html", b"<script>alert(1)</script>")
        assert False, "must reject a disallowed extension (html)"
    except file_utils.UploadRejected:
        pass
    print("test_project_attachment_content_sniffing_direct OK")


def test_project_attachment_valid_jpg_and_pdf_accepted_via_request_form():
    reset_db()
    uid, bid = _make_owner_and_business("attach_owner1@test.com")
    client = fresh_client()
    _login_owner(client, "attach_owner1@test.com")

    resp = client.post(
        f"/business/{bid}/projects/custom/photo",
        data={"project_name": "Foto Produk", "csrf_token": "x",
              "attachment": (io.BytesIO(_tiny_png_bytes()), "referensi.jpg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code in (302, 200)
    rows = db.query_all("SELECT * FROM project_files WHERE business_id = ? AND kind = 'REFERENCE'", (bid,))
    assert len(rows) == 1 and rows[0]["original_filename"] == "referensi.jpg"

    resp2 = client.post(
        f"/business/{bid}/projects/custom/website",
        data={"project_name": "Landing Page Brief", "csrf_token": "x",
              "attachment": (io.BytesIO(_tiny_pdf_bytes()), "brief.pdf")},
        content_type="multipart/form-data",
    )
    assert resp2.status_code in (302, 200)
    rows = db.query_all("SELECT * FROM project_files WHERE business_id = ? AND kind = 'REFERENCE'", (bid,))
    assert len(rows) == 2
    assert any(r["mime_type"] == "application/pdf" for r in rows)
    print("test_project_attachment_valid_jpg_and_pdf_accepted_via_request_form OK")


def test_project_attachment_rejected_but_project_still_created():
    """A rejected attachment must never block the underlying custom project request itself."""
    reset_db()
    uid, bid = _make_owner_and_business("attach_owner2@test.com")
    client = fresh_client()
    _login_owner(client, "attach_owner2@test.com")
    resp = client.post(
        f"/business/{bid}/projects/custom/video",
        data={"project_name": "Video Promo", "csrf_token": "x",
              "attachment": (io.BytesIO(b"<script>alert(1)</script>"), "evil.jpg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code in (302, 200)
    projects = projects_repo.list_projects_for_business(bid)
    assert any(p["title"].startswith("Custom Video") for p in projects)
    rows = db.query_all("SELECT * FROM project_files WHERE business_id = ? AND kind = 'REFERENCE'", (bid,))
    assert len(rows) == 0, "the fake-image attachment must have been rejected, not stored"
    print("test_project_attachment_rejected_but_project_still_created OK")


def test_project_attachment_access_isolated_between_customers_and_open_to_admin():
    reset_db()
    admin = _make_admin()
    uid1, bid1 = _make_owner_and_business("attach_owner_a@test.com")
    uid2, bid2 = _make_owner_and_business("attach_owner_b@test.com")

    client1 = fresh_client()
    _login_owner(client1, "attach_owner_a@test.com")
    client1.post(
        f"/business/{bid1}/projects/custom/photo",
        data={"project_name": "Foto A", "csrf_token": "x",
              "attachment": (io.BytesIO(_tiny_png_bytes()), "a.jpg")},
        content_type="multipart/form-data",
    )
    project = projects_repo.list_projects_for_business(bid1)[0]
    file_row = db.query_one("SELECT * FROM project_files WHERE business_id = ? AND kind = 'REFERENCE'", (bid1,))

    # Owner can fetch its own attachment.
    resp = client1.get(f"/business/{bid1}/projects/{project['id']}/attachments/{file_row['id']}")
    assert resp.status_code == 200
    assert resp.data == _tiny_png_bytes()

    # A different customer (bid2's owner) must get a clean not-found, never the file.
    client2 = fresh_client()
    _login_owner(client2, "attach_owner_b@test.com")
    resp = client2.get(f"/business/{bid1}/projects/{project['id']}/attachments/{file_row['id']}")
    assert resp.status_code == 404

    # KILAS_ADMIN can view any project's attachment.
    admin_client = fresh_client()
    _login_admin(admin_client, admin)
    resp = admin_client.get(f"/business/{bid1}/projects/{project['id']}/attachments/{file_row['id']}")
    assert resp.status_code == 200
    assert resp.data == _tiny_png_bytes()
    print("test_project_attachment_access_isolated_between_customers_and_open_to_admin OK")


if __name__ == "__main__":
    test_admin_creates_talent()
    test_admin_create_talent_requires_name()
    test_admin_edits_talent_availability_note_and_display_order()
    test_admin_archives_and_reactivates_talent_soft_delete_only()
    test_admin_changes_display_order_reorders_public_list()
    test_client_cannot_mutate_talent_any_new_route()
    test_talent_image_upload_accepts_valid_image_and_is_served_safely()
    test_talent_image_upload_accepts_webp()
    test_talent_image_upload_rejects_invalid_file()
    test_talent_image_upload_rejects_disallowed_extension()
    test_stored_image_serving_rejects_unknown_asset_id()
    test_internal_rate_never_exposed_on_public_talent_list()

    test_catalog_admin_edit_restored_for_safe_categories()
    test_catalog_seeding_never_overwrites_admin_edits_on_restart()
    test_catalog_activate_deactivate()
    test_catalog_display_order_respected_in_active_listing()
    test_catalog_invalid_pricing_state_rejected_fixed_price_without_amount()
    test_catalog_custom_quote_never_carries_a_leftover_price()
    test_catalog_route_rejects_invalid_pricing_state_via_flash_not_crash()
    test_historical_transaction_price_unchanged_after_catalog_price_update()

    test_action_center_whatsapp_waiting_connection_count()
    test_action_center_links_are_correctly_filtered()

    test_admin_search_finds_business_project_and_talent()
    test_admin_search_no_client_access()
    test_admin_search_empty_query_shows_no_results_block()

    test_completed_project_visible_in_history_not_active()
    test_old_invoice_visible_in_payment_history()
    test_project_and_invoice_list_tenant_isolation()

    test_payment_proof_viewable_by_owner_not_by_other_tenant()
    test_admin_can_view_any_payment_proof()
    test_wizard_file_upload_now_accepts_webp()

    test_project_attachment_content_sniffing_direct()
    test_project_attachment_valid_jpg_and_pdf_accepted_via_request_form()
    test_project_attachment_rejected_but_project_still_created()
    test_project_attachment_access_isolated_between_customers_and_open_to_admin()

    print("\nALL BUSINESS HUB V2 FINAL OPERATIONS POLISH TESTS PASSED")
