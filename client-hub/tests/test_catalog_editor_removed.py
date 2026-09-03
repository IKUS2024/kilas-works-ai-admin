"""Service Catalog editability — regression suite.

Business rule REVERSAL (UX pass — explicitly reverses the earlier "catalog editing removed, manual
file only" decision, at the user's own later explicit request): routine service/package management
is restored to the Admin Dashboard, but strictly scoped to categories with a purely generic
FIXED_PRICE/STARTING_FROM/CUSTOM_QUOTE workflow (never AI_ADMIN or TALENT, which each have their
own special-workflow-only creation paths, untouched by this). This file proves:
  G. The edit/create/toggle-active routes work correctly, scoped to safe categories only, and
     never let a new item accidentally gain the AI_ADMIN special workflow by category selection.
  H. Nothing about reading the catalog changed — every existing consumer (/services page, the
     price-sync note, the bot's live "DAFTAR KATEGORI LAYANAN AKTIF" knowledge block) still reads
     from the exact same single service_catalog source of truth, never a second one.

Run with:
    cd client-hub && python3 tests/test_catalog_editor_removed.py
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


# ---------------------------------------------------------------------------
# TEST G — editing restored, scoped correctly, AI_ADMIN category never invented via this form.
# ---------------------------------------------------------------------------
def test_G_new_edit_route_works_for_safe_category():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    item = catalog_service.get_catalog_item("website_landing_page")
    resp = client.post(f"/admin/catalog/{item['id']}/update", data={
        "csrf_token": "x", "name": "Landing Page Baru", "price_amount": "899000",
        "price_unit": "one time", "pricing_mode": "FIXED_PRICE", "is_active": "on",
    })
    assert resp.status_code == 302, f"edit route must work now, got {resp.status_code}"
    updated = catalog_service.get_catalog_item("website_landing_page")
    assert updated["name"] == "Landing Page Baru"
    assert updated["price_amount"] == 899000
    print("test_G_new_edit_route_works_for_safe_category OK")


def test_G_create_new_safe_category_item_works():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.post("/admin/catalog/create", data={
        "csrf_token": "x", "name": "Foto Produk Express", "category": "PHOTO",
        "pricing_mode": "FIXED_PRICE", "price_amount": "500000",
    })
    assert resp.status_code == 302
    all_items = catalog_service.list_all_catalog()
    created = next((i for i in all_items if i["name"] == "Foto Produk Express"), None)
    assert created is not None, "the new item must actually be created"
    assert created["category"] == "PHOTO"
    assert created["is_active"] is True or created["is_active"] == 1
    print("test_G_create_new_safe_category_item_works OK")


def test_G_cannot_create_ai_admin_category_via_dashboard_form():
    """The generic "Tambah Layanan" form must never be able to invent a new AI_ADMIN-category
    item — that category has its own special onboarding/payment/activation workflow, and
    accidentally creating one here (even if separately blocked at checkout time) would be
    confusing, broken UX at best. Enforced at the service layer, not just by omitting it from the
    dropdown — a direct POST with category=AI_ADMIN must also be rejected."""
    reset_db()
    try:
        catalog_service.create_catalog_item("AI_ADMIN", "Sneaky AI Admin Plan", "FIXED_PRICE",
                                             price_amount=100000)
        raised = False
    except catalog_service.InvalidCatalogState:
        raised = True
    assert raised, "creating an AI_ADMIN category item via the generic form must be rejected"
    print("test_G_cannot_create_ai_admin_category_via_dashboard_form OK")


def test_G_cannot_create_talent_category_via_dashboard_form():
    reset_db()
    try:
        catalog_service.create_catalog_item("TALENT", "Sneaky Talent Slot", "CUSTOM_QUOTE")
        raised = False
    except catalog_service.InvalidCatalogState:
        raised = True
    assert raised
    print("test_G_cannot_create_talent_category_via_dashboard_form OK")


def test_G_toggle_active_deactivates_and_reactivates():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    item = catalog_service.get_catalog_item("website_landing_page")
    assert item["is_active"] in (True, 1)

    resp = client.post(f"/admin/catalog/{item['id']}/toggle-active", data={"csrf_token": "x"})
    assert resp.status_code == 302
    after = catalog_service.get_catalog_item("website_landing_page")
    assert after["is_active"] in (False, 0)

    # Deactivated item disappears from the SAME list_active_catalog() every consumer uses —
    # confirms no separate sync step is needed, since there's only one source of truth.
    active_keys = [i["catalog_key"] for i in catalog_service.list_active_catalog()]
    assert "website_landing_page" not in active_keys

    client.post(f"/admin/catalog/{item['id']}/toggle-active", data={"csrf_token": "x"})
    reactivated = catalog_service.get_catalog_item("website_landing_page")
    assert reactivated["is_active"] in (True, 1)
    print("test_G_toggle_active_deactivates_and_reactivates OK")


def test_G_catalog_admin_page_renders_forms_now():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get("/admin/catalog")
    assert resp.status_code == 200
    body = resp.data.decode().lower()
    assert "<form" in body, "the restored catalog page must render create/edit forms"
    assert "tambah layanan" in body
    print("test_G_catalog_admin_page_renders_forms_now OK")


# ---------------------------------------------------------------------------
# TEST H — catalog still readable via the same single service layer (unchanged).
# ---------------------------------------------------------------------------
def test_H_catalog_still_readable_via_service_layer():
    reset_db()
    items = catalog_service.list_active_catalog()
    assert len(items) > 0, "catalog reading must still work"
    talent_item = catalog_service.get_catalog_item("talent_management")
    assert talent_item is not None
    assert talent_item["is_active"]
    print("test_H_catalog_still_readable_via_service_layer OK")


def test_H_services_page_still_renders_full_catalog():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get("/services")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "AI Admin Basic" in body
    assert "Landing Page" in body
    print("test_H_services_page_still_renders_full_catalog OK")


def test_H_deactivated_service_disappears_from_services_page():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    item = catalog_service.get_catalog_item("website_landing_page")
    # Confirm the standalone item's exact row (name AND its own distinguishing price) is present
    # BEFORE deactivation — a bundle item legitimately named "Ads + Landing Page" ALSO contains
    # the substring "Landing Page" but at a different price, so a bare substring check on the
    # name alone would false-positive against that unrelated bundle; pairing name+price
    # disambiguates the exact standalone item this test is about.
    before = client.get("/services").data.decode()
    assert ">Landing Page<" in before and "Rp799.000" in before

    client.post(f"/admin/catalog/{item['id']}/toggle-active", data={"csrf_token": "x"})
    client.get("/services")  # consume the one-shot flash message before the real check
    resp = client.get("/services")
    body = resp.data.decode()
    assert ">Landing Page<" not in body, "a deactivated service must disappear from customer browsing"
    print("test_H_deactivated_service_disappears_from_services_page OK")


def test_H_deactivation_never_touches_historical_projects():
    """Historical orders reference the catalog by catalog_key at creation time, never a live join
    — deactivating a service must never affect an existing project/order."""
    reset_db()
    admin = _make_admin()
    uid = repo.create_user("cust@test.com", security.hash_password("password123"))
    bid = repo.create_business(uid, "Test Biz", package="NONE")
    import projects_repo
    item = catalog_service.get_catalog_item("website_landing_page")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)

    client = fresh_client()
    _login_admin(client, admin)
    client.post(f"/admin/catalog/{item['id']}/toggle-active", data={"csrf_token": "x"})

    project = projects_repo.get_project(project_id)
    assert project is not None, "the historical project must still exist"
    assert project["final_price"] == item["price_amount"], "the historical price must be unchanged"
    print("test_H_deactivation_never_touches_historical_projects OK")


if __name__ == "__main__":
    test_G_new_edit_route_works_for_safe_category()
    test_G_create_new_safe_category_item_works()
    test_G_cannot_create_ai_admin_category_via_dashboard_form()
    test_G_cannot_create_talent_category_via_dashboard_form()
    test_G_toggle_active_deactivates_and_reactivates()
    test_G_catalog_admin_page_renders_forms_now()
    test_H_catalog_still_readable_via_service_layer()
    test_H_services_page_still_renders_full_catalog()
    test_H_deactivated_service_disappears_from_services_page()
    test_H_deactivation_never_touches_historical_projects()
    print("ALL SERVICE CATALOG EDITABILITY TESTS PASSED")
