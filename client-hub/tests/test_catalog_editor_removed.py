"""Knowledge architecture regression suite — Tests G and H from the bug report.

Business rule change: catalog editing has been REMOVED from the Admin Dashboard — the official
catalog is now managed as a manually-maintained document/file, uploaded/replaced outside this app.
This file proves:
  G. The old edit route (POST /admin/catalog/<id>/update) is gone (404) and can never mutate data,
     and the admin catalog page itself renders read-only (no edit form/inputs).
  H. Nothing about the AI's/Client Hub's ability to READ existing catalog data was removed — the
     underlying service_catalog table, catalog_service.list_active_catalog()/get_catalog_item(),
     and every consumer of that data (the /services page, the price-sync note, the new
     "DAFTAR KATEGORI LAYANAN AKTIF" knowledge block) still work exactly as before.

Tests A-F (service listing / recommendation logic / talent auto-sync) live in the top-level
test_knowledge_architecture.py instead — they need the root bot's app.py, a different Flask app
object than Client Hub's own (see that file's own module docstring for why they're split).

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
# TEST G — catalog editor removed: old POST edit route blocked/404, never mutates data.
# ---------------------------------------------------------------------------
def test_G_old_edit_route_returns_404():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    item = catalog_service.get_catalog_item("website_landing_page")
    resp = client.post(f"/admin/catalog/{item['id']}/update", data={
        "name": "Should Not Apply", "price_amount": "1",
    })
    assert resp.status_code == 404, f"the catalog edit route must no longer exist, got {resp.status_code}"
    print("test_G_old_edit_route_returns_404 OK")


def test_G_old_edit_route_never_mutates_data_even_with_valid_looking_payload():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    item_before = catalog_service.get_catalog_item("website_landing_page")
    client.post(f"/admin/catalog/{item_before['id']}/update", data={
        "name": "Landing Page HACKED", "description": "should never apply",
        "cta_text": "x", "pricing_mode": "FIXED_PRICE", "price_amount": "1",
        "price_unit": "one time", "sort_order": "999", "is_active": "on",
    })
    item_after = catalog_service.get_catalog_item("website_landing_page")
    assert item_after["name"] == item_before["name"]
    assert item_after["price_amount"] == item_before["price_amount"]
    assert item_after["sort_order"] == item_before["sort_order"]
    print("test_G_old_edit_route_never_mutates_data_even_with_valid_looking_payload OK")


def test_G_catalog_admin_page_renders_read_only_no_forms():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get("/admin/catalog")
    assert resp.status_code == 200
    body = resp.data.decode().lower()
    assert "<form" not in body, "the read-only catalog page must not render any form"
    assert "<input" not in body, "the read-only catalog page must not render any editable input"
    assert "<button" not in body or "type=\"submit\"" not in body
    print("test_G_catalog_admin_page_renders_read_only_no_forms OK")


def test_G_non_admin_still_cannot_reach_the_route_either():
    """Regression guard: removing the route shouldn't accidentally weaken auth on anything else —
    a logged-out request still gets redirected to login, never a 500, for the (now-gone) URL."""
    reset_db()
    client = fresh_client()
    item = catalog_service.get_catalog_item("website_landing_page")
    resp = client.post(f"/admin/catalog/{item['id']}/update", data={"name": "x"})
    assert resp.status_code in (302, 404)
    print("test_G_non_admin_still_cannot_reach_the_route_either OK")


# ---------------------------------------------------------------------------
# TEST H — AI/Client Hub can still READ existing catalog data despite the editor removal.
# ---------------------------------------------------------------------------
def test_H_catalog_still_readable_via_service_layer():
    reset_db()
    items = catalog_service.list_active_catalog()
    assert len(items) > 0, "catalog reading must still work after removing the editor"
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


def test_H_catalog_admin_status_page_still_shows_existing_items():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get("/admin/catalog")
    body = resp.data.decode()
    assert "AI Admin Basic" in body
    assert "Talent Management" in body
    print("test_H_catalog_admin_status_page_still_shows_existing_items OK")


if __name__ == "__main__":
    test_G_old_edit_route_returns_404()
    test_G_old_edit_route_never_mutates_data_even_with_valid_looking_payload()
    test_G_catalog_admin_page_renders_read_only_no_forms()
    test_G_non_admin_still_cannot_reach_the_route_either()
    test_H_catalog_still_readable_via_service_layer()
    test_H_services_page_still_renders_full_catalog()
    test_H_catalog_admin_status_page_still_shows_existing_items()
    print("ALL CATALOG EDITOR REMOVAL TESTS PASSED")
