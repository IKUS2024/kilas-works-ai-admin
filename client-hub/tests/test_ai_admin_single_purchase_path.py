"""Business flow cleanup regression suite — AI Admin must have exactly ONE purchase path.

ROOT CAUSE (confirmed by source inspection): pricing_config.py's catalog seeded `ai_admin_basic`/
`ai_admin_pro` as ordinary FIXED_PRICE items. service_catalog.html rendered a "Checkout" button for
every FIXED_PRICE item including these, posting to start_fixed_checkout() — which created a project
and sent the customer STRAIGHT to payment, completely bypassing the business-info onboarding wizard
(routes_client.py's wizard_step/review_page/submit_for_review). Meanwhile the PROPER AI Admin path
(dashboard "Buat Business"/"+ Tambah AI Admin" -> wizard -> review -> submit) had NO payment step of
its own at all — submit_for_review() just flashed a message and sent the customer back to the
dashboard. Two independent, disconnected paths to "buy" the same product — exactly the "two AI
Admin products" confusion reported.

THE FIX:
  - service_catalog.html no longer renders instant-checkout for the AI_ADMIN category — its CTA
    links to the dashboard instead, where the existing "Buat Business"/"+ Tambah AI Admin" actions
    correctly lead into the wizard.
  - start_fixed_checkout() rejects an AI_ADMIN category item outright (defense in depth against a
    stale cached page or a direct POST).
  - A new route, client.ai_admin_checkout, is the ONE place that creates/reuses the AI Admin
    project and hands off to the existing shared payments.checkout_page — reached from
    submit_for_review()'s own redirect (Review -> Pembayaran) and a "Lanjut ke Pembayaran" link on
    review.html for anyone revisiting later. Idempotent — never creates a duplicate project.

Foto/Video/Website custom-quote flows (custom_project_request) were never part of this bug (they
already require a brief before any payment) and are asserted here to remain unaffected.

Run with:
    cd client-hub && python3 tests/test_ai_admin_single_purchase_path.py
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
import projects_repo  # noqa: E402
import catalog_service  # noqa: E402
import app as client_hub_app  # noqa: E402

FLASK_APP = client_hub_app.app
FLASK_APP.testing = True
FLASK_APP.config["PROPAGATE_EXCEPTIONS"] = True


def reset_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    db._local.conn = None
    db.init_schema()
    # Catalog seeding only runs once, at app.py's own module-import time (see app.py's startup
    # sequence) — NOT re-triggered by db.init_schema() alone, so a wipe-and-recreate reset needs to
    # explicitly re-seed it, or every catalog-dependent page (e.g. /services) renders empty.
    catalog_service.seed_catalog_if_needed()


def _make_owner_and_business(package="AI_ADMIN_PRO"):
    uid = repo.create_user(f"owner_{os.urandom(4).hex()}@test.com", security.hash_password("password123"))
    bid = repo.create_business(uid, "Test Biz", package=package)
    return uid, bid


def _complete_wizard(client, bid):
    steps = [
        ("basics", {"business_name": "Test Biz", "category": "Kedai kopi", "owner_name": "Budi"}),
        ("services", {"services_raw": "Kopi susu - 20rb"}),
        ("operations", {"operating_hours": "08-20", "closed_days": "Minggu",
                         "online_or_offline": "offline", "appointment_rules_raw": ""}),
        ("faq", {"faqs_raw": "Buka jam berapa? - 08.00"}),
        ("style", {"tone": "friendly", "primary_language": "id", "customer_salutation": "Kak"}),
    ]
    for step_name, data in steps:
        client.post(f"/business/{bid}/wizard/{step_name}", data=data, follow_redirects=True)
    repo.save_ai_normalized_config(bid, "summary", {"description": "x", "services": [], "faqs": []}, [])


# ---------------------------------------------------------------------------
# 1. Catalog page no longer offers instant checkout for AI_ADMIN.
# ---------------------------------------------------------------------------
def test_catalog_page_has_no_instant_checkout_for_ai_admin():
    reset_db()
    uid, bid = _make_owner_and_business(package="NONE")
    with FLASK_APP.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = uid
            sess["role"] = "CLIENT_OWNER"
        resp = c.get("/services")
    assert resp.status_code == 200
    body = resp.data.decode()
    idx = body.find("AI Admin Basic")
    assert idx != -1
    snippet = body[idx:idx + 600]
    assert "checkout-fixed" not in snippet
    assert "Mulai di Dashboard" in snippet
    print("test_catalog_page_has_no_instant_checkout_for_ai_admin OK")


def test_other_fixed_price_categories_still_instant_checkout():
    """Regression guard: only AI_ADMIN is excluded — Website/Event/Content fixed-price items keep
    working exactly as before (not part of this bug, must not be touched)."""
    reset_db()
    uid, bid = _make_owner_and_business(package="NONE")
    with FLASK_APP.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = uid
            sess["role"] = "CLIENT_OWNER"
        resp = c.get("/services")
    body = resp.data.decode()
    idx = body.find("Landing Page")
    assert idx != -1
    snippet = body[idx:idx + 400]
    assert "checkout-fixed" in snippet
    print("test_other_fixed_price_categories_still_instant_checkout OK")


# ---------------------------------------------------------------------------
# 2. Direct POST bypass attempt is rejected (defense in depth).
# ---------------------------------------------------------------------------
def test_direct_post_to_ai_admin_checkout_fixed_is_rejected():
    reset_db()
    uid, bid = _make_owner_and_business(package="NONE")
    with FLASK_APP.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = uid
            sess["role"] = "CLIENT_OWNER"
        resp = c.post("/services/ai_admin_basic/checkout-fixed", data={"business_id": bid}, follow_redirects=False)
    assert resp.status_code == 302
    assert "dashboard" in resp.headers.get("Location", "").lower()
    assert projects_repo.list_projects_for_business(bid) == []
    print("test_direct_post_to_ai_admin_checkout_fixed_is_rejected OK")


def test_direct_post_to_ai_admin_pro_checkout_fixed_also_rejected():
    reset_db()
    uid, bid = _make_owner_and_business(package="NONE")
    with FLASK_APP.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = uid
            sess["role"] = "CLIENT_OWNER"
        resp = c.post("/services/ai_admin_pro/checkout-fixed", data={"business_id": bid}, follow_redirects=False)
    assert resp.status_code == 302
    assert projects_repo.list_projects_for_business(bid) == []
    print("test_direct_post_to_ai_admin_pro_checkout_fixed_also_rejected OK")


# ---------------------------------------------------------------------------
# 3. Full wizard -> submit -> payment flow (the ONE true path).
# ---------------------------------------------------------------------------
def test_full_wizard_to_payment_flow_end_to_end():
    reset_db()
    uid, bid = _make_owner_and_business(package="AI_ADMIN_PRO")
    with FLASK_APP.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = uid
            sess["role"] = "CLIENT_OWNER"
        _complete_wizard(c, bid)

        resp = c.post(f"/business/{bid}/submit-for-review", follow_redirects=False)
        assert resp.status_code == 302
        assert "/ai-admin/checkout" in resp.headers.get("Location", ""), resp.headers.get("Location")

        resp2 = c.get(resp.headers.get("Location"), follow_redirects=False)
        assert resp2.status_code == 302
        assert "/checkout" in resp2.headers.get("Location", "")

        resp3 = c.get(resp2.headers.get("Location"), follow_redirects=True)
        assert resp3.status_code == 200
    print("test_full_wizard_to_payment_flow_end_to_end OK")


def test_ai_admin_checkout_is_idempotent_no_duplicate_project():
    reset_db()
    uid, bid = _make_owner_and_business(package="AI_ADMIN_BASIC")
    with FLASK_APP.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = uid
            sess["role"] = "CLIENT_OWNER"
        c.get(f"/business/{bid}/ai-admin/checkout")
        projects_first = projects_repo.list_projects_for_business(bid)
        c.get(f"/business/{bid}/ai-admin/checkout")
        projects_second = projects_repo.list_projects_for_business(bid)
    assert len(projects_first) == 1
    assert len(projects_second) == 1, \
        f"BUG: revisiting the checkout route created a duplicate project: {projects_second}"
    assert projects_first[0]["id"] == projects_second[0]["id"]
    print("test_ai_admin_checkout_is_idempotent_no_duplicate_project OK")


def test_ai_admin_checkout_rejects_none_package_business():
    reset_db()
    uid, bid = _make_owner_and_business(package="NONE")
    with FLASK_APP.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = uid
            sess["role"] = "CLIENT_OWNER"
        resp = c.get(f"/business/{bid}/ai-admin/checkout", follow_redirects=False)
    assert resp.status_code == 302
    assert "dashboard" in resp.headers.get("Location", "").lower()
    assert projects_repo.list_projects_for_business(bid) == []
    print("test_ai_admin_checkout_rejects_none_package_business OK")


def test_review_page_shows_payment_link_when_not_yet_paid():
    reset_db()
    uid, bid = _make_owner_and_business(package="AI_ADMIN_PRO")
    with FLASK_APP.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = uid
            sess["role"] = "CLIENT_OWNER"
        _complete_wizard(c, bid)
        resp = c.get(f"/business/{bid}/review")
    assert resp.status_code == 200
    assert "Lanjut ke Pembayaran" in resp.data.decode()
    print("test_review_page_shows_payment_link_when_not_yet_paid OK")


# ---------------------------------------------------------------------------
# 4. Foto/Video/Website custom-quote flows are unaffected (never routed into the AI Admin wizard).
# ---------------------------------------------------------------------------
def test_photo_flow_never_touches_ai_admin_wizard():
    reset_db()
    uid, bid = _make_owner_and_business(package="NONE")
    with FLASK_APP.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = uid
            sess["role"] = "CLIENT_OWNER"
        resp = c.post(f"/business/{bid}/projects/custom/PHOTO", data={
            "photoshoot_type": "produk", "num_final_photos": "10", "location": "Tangerang",
            "preferred_date": "", "usage": "sosmed", "style": "natural", "notes": "",
            "project_name": "Foto A",
        }, follow_redirects=False)
    assert resp.status_code == 302
    assert "/wizard/" not in resp.headers.get("Location", "")
    assert "/projects/" in resp.headers.get("Location", "")
    print("test_photo_flow_never_touches_ai_admin_wizard OK")


def test_video_flow_never_touches_ai_admin_wizard():
    reset_db()
    uid, bid = _make_owner_and_business(package="NONE")
    with FLASK_APP.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = uid
            sess["role"] = "CLIENT_OWNER"
        resp = c.post(f"/business/{bid}/projects/custom/VIDEO", data={
            "num_videos": "3", "duration": "30s", "platform": "instagram", "location": "Tangerang",
            "preferred_date": "", "style": "cinematic", "reference": "", "notes": "",
            "project_name": "Video A",
        }, follow_redirects=False)
    assert resp.status_code == 302
    assert "/wizard/" not in resp.headers.get("Location", "")
    print("test_video_flow_never_touches_ai_admin_wizard OK")


def test_business_created_without_ai_admin_lands_on_dashboard_not_wizard():
    """package='NONE' business creation must still skip the wizard entirely (pre-existing
    behavior, must remain unaffected by this change)."""
    reset_db()
    uid = repo.create_user(f"owner_{os.urandom(4).hex()}@test.com", security.hash_password("password123"))
    with FLASK_APP.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = uid
            sess["role"] = "CLIENT_OWNER"
        resp = c.post("/business/create", data={"business_name": "No AI Biz", "package": "NONE"},
                       follow_redirects=False)
    assert resp.status_code == 302
    assert "/wizard/" not in resp.headers.get("Location", "")
    assert resp.headers.get("Location", "").endswith("/dashboard")
    print("test_business_created_without_ai_admin_lands_on_dashboard_not_wizard OK")


def test_business_created_with_ai_admin_lands_on_wizard():
    reset_db()
    uid = repo.create_user(f"owner_{os.urandom(4).hex()}@test.com", security.hash_password("password123"))
    with FLASK_APP.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = uid
            sess["role"] = "CLIENT_OWNER"
        resp = c.post("/business/create", data={"business_name": "AI Biz", "package": "AI_ADMIN_BASIC"},
                       follow_redirects=False)
    assert resp.status_code == 302
    assert "/wizard/basics" in resp.headers.get("Location", "")
    print("test_business_created_with_ai_admin_lands_on_wizard OK")


if __name__ == "__main__":
    test_catalog_page_has_no_instant_checkout_for_ai_admin()
    test_other_fixed_price_categories_still_instant_checkout()
    test_direct_post_to_ai_admin_checkout_fixed_is_rejected()
    test_direct_post_to_ai_admin_pro_checkout_fixed_also_rejected()
    test_full_wizard_to_payment_flow_end_to_end()
    test_ai_admin_checkout_is_idempotent_no_duplicate_project()
    test_ai_admin_checkout_rejects_none_package_business()
    test_review_page_shows_payment_link_when_not_yet_paid()
    test_photo_flow_never_touches_ai_admin_wizard()
    test_video_flow_never_touches_ai_admin_wizard()
    test_business_created_without_ai_admin_lands_on_dashboard_not_wizard()
    test_business_created_with_ai_admin_lands_on_wizard()
    print("ALL AI ADMIN SINGLE-PURCHASE-PATH TESTS PASSED")
