"""Client Hub new-customer service selection + purchase flow — regression tests.

Run with:
    cd client-hub && python3 tests/test_service_selection_purchase_flow.py
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


def _make_owner_and_business(name, email, package="NONE"):
    uid = repo.create_user(email, security.hash_password("password123"))
    bid = repo.create_business(uid, name, package=package)
    return uid, bid


def _login_owner(client, email, password="password123"):
    client.post("/login", data={"email": email, "password": password})


# ---------------------------------------------------------------------------
# 1/2. New customer selects a fixed-price non-AI service -> reaches checkout.
# ---------------------------------------------------------------------------
def test_new_customer_can_select_fixed_price_service_and_reach_checkout():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Fixed", "fixed@test.com")
    client = fresh_client()
    _login_owner(client, "fixed@test.com")
    body_before = client.get("/services").data.decode()
    assert "Pilih Layanan" in body_before

    item = catalog_service.get_catalog_item("website_landing_page")
    resp = client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    assert resp.status_code == 302
    assert "/checkout" in resp.headers["Location"] or "/projects/" in resp.headers["Location"]
    projects = projects_repo.list_projects_for_business(bid)
    assert len(projects) == 1
    assert projects[0]["status"] == "APPROVED"
    assert projects[0]["catalog_key"] == item["catalog_key"]
    print("test_new_customer_can_select_fixed_price_service_and_reach_checkout OK")


# ---------------------------------------------------------------------------
# 3. AI Admin still routes to onboarding, not generic checkout.
# ---------------------------------------------------------------------------
def test_ai_admin_never_uses_generic_checkout_route():
    reset_db()
    uid, bid = _make_owner_and_business("Biz AIAdmin", "aiadmin@test.com")
    client = fresh_client()
    _login_owner(client, "aiadmin@test.com")
    body = client.get("/services").data.decode()
    ai_idx = body.find("AI Admin Basic")
    assert ai_idx != -1
    section = body[ai_idx:ai_idx + 400]
    assert "Mulai di Dashboard" in section
    assert 'action="/services/ai_admin_basic/checkout-fixed"' not in section

    ai_item = catalog_service.get_catalog_item("ai_admin_basic")
    resp = client.post(f"/services/{ai_item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"], \
        "even a direct POST to the generic checkout route must redirect AI Admin to the dashboard, never create a project"
    projects = projects_repo.list_projects_for_business(bid)
    assert len(projects) == 0, "AI Admin must never get a project via the generic instant-checkout path"
    print("test_ai_admin_never_uses_generic_checkout_route OK")


# ---------------------------------------------------------------------------
# 4. CUSTOM_QUOTE creates a quote/request flow without an invented price.
# ---------------------------------------------------------------------------
def test_custom_quote_generic_route_creates_request_without_price():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Quote", "quote@test.com")
    client = fresh_client()
    _login_owner(client, "quote@test.com")

    # No existing seeded CUSTOM_QUOTE item falls outside the whitelisted categories today — create
    # one via the same admin catalog-creation path a real admin would use, to genuinely exercise
    # the new generic route rather than one already covered by a dedicated flow.
    new_id = catalog_service.create_catalog_item("EVENT", "Dokumentasi Event Custom", "CUSTOM_QUOTE")
    item = catalog_service.get_catalog_item_by_id(new_id)

    body = client.get("/services").data.decode()
    assert "Minta Penawaran" in body

    resp = client.post(f"/services/{item['catalog_key']}/request-quote", data={
        "csrf_token": "x", "business_id": str(bid), "notes": "Butuh dokumentasi untuk gathering kantor",
    })
    assert resp.status_code == 302
    projects = projects_repo.list_projects_for_business(bid)
    assert len(projects) == 1
    assert projects[0]["status"] == "WAITING_FOR_QUOTE"
    assert projects[0]["final_price"] is None, "a CUSTOM_QUOTE request must never have an invented price"
    print("test_custom_quote_generic_route_creates_request_without_price OK")


def test_custom_quote_talent_and_content_still_use_dedicated_flows():
    """Regression lock: TALENT/CONTENT/VIDEO/PHOTO/WEBSITE/APPLICATION must keep using their own
    dedicated, more detailed request flow — the new generic route must never intercept those."""
    reset_db()
    uid, bid = _make_owner_and_business("Biz Dedicated", "dedicated@test.com")
    client = fresh_client()
    _login_owner(client, "dedicated@test.com")
    talent_item = catalog_service.get_catalog_item("talent_management")
    resp = client.post(f"/services/{talent_item['catalog_key']}/request-quote", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    assert resp.status_code == 404, "TALENT must never be reachable via the generic quote route"
    custom_video_item = catalog_service.get_catalog_item("custom_video")
    resp2 = client.post(f"/services/{custom_video_item['catalog_key']}/request-quote", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    assert resp2.status_code == 404, "VIDEO must never be reachable via the generic quote route either"
    print("test_custom_quote_talent_and_content_still_use_dedicated_flows OK")


# ---------------------------------------------------------------------------
# 5. Inactive service cannot be selected.
# ---------------------------------------------------------------------------
def test_inactive_service_cannot_be_selected():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Inactive", "inactive@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    catalog_service.update_catalog_item(item["id"], is_active=False)
    client = fresh_client()
    _login_owner(client, "inactive@test.com")
    body = client.get("/services").data.decode()
    assert f">{item['name']}<" not in body, "an inactive service must not even be listed"

    resp = client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    assert resp.status_code == 404, "a direct POST to an inactive service's checkout must be rejected"
    print("test_inactive_service_cannot_be_selected OK")


# ---------------------------------------------------------------------------
# 6/7. Repeated click does not duplicate; unfinished project uses Continue.
# ---------------------------------------------------------------------------
def test_repeated_click_reuses_existing_project_not_duplicate():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Repeat", "repeat@test.com")
    client = fresh_client()
    _login_owner(client, "repeat@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")

    resp1 = client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    resp2 = client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    projects = projects_repo.list_projects_for_business(bid)
    assert len(projects) == 1, f"repeated click must reuse the same project, got {len(projects)}"
    # The two redirects don't have to be byte-identical URLs (the first click can go straight to
    # checkout; a repeat click reasonably lands on the project detail page instead) — what matters
    # is that both point at the SAME underlying project, never a second one.
    assert str(projects[0]["id"]) in resp1.headers["Location"] or "/checkout" in resp1.headers["Location"]
    assert str(projects[0]["id"]) in resp2.headers["Location"]
    print("test_repeated_click_reuses_existing_project_not_duplicate OK")


def test_unfinished_project_shows_lanjutkan_on_catalog_page():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Continue", "continue@test.com")
    client = fresh_client()
    _login_owner(client, "continue@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    body = client.get("/services").data.decode()
    assert "Lanjutkan" in body
    idx = body.find(f">{item['name']}<")
    assert idx != -1
    section = body[idx:idx + 800]
    assert "Lanjutkan" in section
    print("test_unfinished_project_shows_lanjutkan_on_catalog_page OK")


def test_cancelled_project_does_not_block_new_selection():
    """A CANCELLED project must never count as "unfinished" — the customer should be able to
    start a fresh selection for the same service after cancelling."""
    reset_db()
    uid, bid = _make_owner_and_business("Biz Cancelled", "cancelled@test.com")
    client = fresh_client()
    _login_owner(client, "cancelled@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    project = projects_repo.list_projects_for_business(bid)[0]
    client.post(f"/business/{bid}/projects/{project['id']}/cancel", data={"csrf_token": "x"})

    resp2 = client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    assert resp2.status_code == 302
    projects = projects_repo.list_projects_for_business(bid)
    assert len(projects) == 2, "a cancelled project must not block a fresh new selection"
    print("test_cancelled_project_does_not_block_new_selection OK")


# ---------------------------------------------------------------------------
# 8. Canonical live price is used.
# ---------------------------------------------------------------------------
def test_checkout_uses_canonical_live_price():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Price", "price@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    catalog_service.update_catalog_item(item["id"], price_amount=888000)
    client = fresh_client()
    _login_owner(client, "price@test.com")
    client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    project = projects_repo.list_projects_for_business(bid)[0]
    assert project["final_price"] == 888000, "the project must lock in the CURRENT canonical price at selection time"
    print("test_checkout_uses_canonical_live_price OK")


if __name__ == "__main__":
    test_new_customer_can_select_fixed_price_service_and_reach_checkout()
    test_ai_admin_never_uses_generic_checkout_route()
    test_custom_quote_generic_route_creates_request_without_price()
    test_custom_quote_talent_and_content_still_use_dedicated_flows()
    test_inactive_service_cannot_be_selected()
    test_repeated_click_reuses_existing_project_not_duplicate()
    test_unfinished_project_shows_lanjutkan_on_catalog_page()
    test_cancelled_project_does_not_block_new_selection()
    test_checkout_uses_canonical_live_price()
    print("ALL SERVICE SELECTION PURCHASE FLOW TESTS PASSED")
