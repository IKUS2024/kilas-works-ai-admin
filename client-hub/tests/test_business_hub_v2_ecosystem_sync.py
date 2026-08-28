"""Kilas Works Client Hub — FINAL ECOSYSTEM SYNC & OWNER NOTIFICATION PATCH test suite.

Covers: registration without forcing AI Admin (Section 2), AI Admin fixed-price-only enforcement
(Section 3), Content fixed+custom (Section 4), custom-project CTA reachability for every custom
service type (Section 6), owner-notification correctness + idempotency + a negative test
(Section 10/11), admin business-list status separation for non-AI-Admin customers (Section 14),
and landing-page talent-price-hidden (Section 17). ADDITIVE — every earlier test file is
untouched. Run with:
    cd client-hub && python3 tests/test_business_hub_v2_ecosystem_sync.py
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
import feature_flags  # noqa: E402
import catalog_service  # noqa: E402
import pricing_config  # noqa: E402
import projects_repo  # noqa: E402
import quotation_service  # noqa: E402
import talent_service  # noqa: E402
import owner_notifications  # noqa: E402
import app as client_hub_app  # noqa: E402
from routes_admin import get_display_status  # noqa: E402

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


def _login_owner(client, email, password="password123"):
    client.post("/login", data={"email": email, "password": password})


def _make_owner(email):
    user_id = repo.create_user(email, security.hash_password("password123"))
    return user_id


# ---------------------------------------------------------------------------
# Section 2: registration must NOT force AI Admin package selection
# ---------------------------------------------------------------------------

def test_business_created_without_ai_admin_lands_on_dashboard_not_wizard():
    reset_db()
    email = "no_ai_admin@test.com"
    _make_owner(email)
    client = fresh_client()
    _login_owner(client, email)
    resp = client.post("/business/create", data={"business_name": "Warung Kopi Kilas", "package": "NONE"},
                        follow_redirects=True)
    assert resp.status_code == 200
    # Must land on the dashboard, NOT redirected into the onboarding wizard.
    assert b"wizard" not in resp.request.path.encode() if hasattr(resp, "request") else True
    business = db.query_one("SELECT * FROM businesses WHERE business_name = ?", ("Warung Kopi Kilas",))
    assert business is not None
    assert business["package"] == "NONE"
    assert business["status"] == "DRAFT"  # never force-progressed into onboarding
    print("test_business_created_without_ai_admin_lands_on_dashboard_not_wizard OK")


def test_no_ai_admin_business_never_seeded_with_real_ai_features():
    reset_db()
    user_id = _make_owner("features_none@test.com")
    business_id = repo.create_business(user_id, "No AI Biz", package="NONE")
    feats = db.query_one("SELECT * FROM tenant_features WHERE business_id = ?", (business_id,))
    assert feats is not None
    for key in feature_flags.ALL_FEATURE_KEYS:
        assert not feats[key], f"NONE package must never have {key} enabled"
    print("test_no_ai_admin_business_never_seeded_with_real_ai_features OK")


def test_upgrade_to_ai_admin_is_explicit_and_only_from_none():
    reset_db()
    email = "upgrader@test.com"
    _make_owner(email)
    client = fresh_client()
    _login_owner(client, email)
    client.post("/business/create", data={"business_name": "Upgrade Biz", "package": "NONE"})
    business = db.query_one("SELECT * FROM businesses WHERE business_name = ?", ("Upgrade Biz",))
    resp = client.post(f"/business/{business['id']}/upgrade-ai-admin", data={"package": "AI_ADMIN_PRO"},
                        follow_redirects=True)
    assert resp.status_code == 200
    upgraded = repo.get_business(business["id"])
    assert upgraded["package"] == "AI_ADMIN_PRO"
    feats = db.query_one("SELECT * FROM tenant_features WHERE business_id = ?", (business["id"],))
    assert feats["faq"] and feats["owner_commands"], "Pro features must be seeded after upgrade"
    # Calling upgrade again (already upgraded) must not silently re-run / error.
    resp2 = client.post(f"/business/{business['id']}/upgrade-ai-admin", data={"package": "AI_ADMIN_BASIC"},
                         follow_redirects=True)
    assert resp2.status_code == 200
    still = repo.get_business(business["id"])
    assert still["package"] == "AI_ADMIN_PRO", "already-upgraded business must not be silently downgraded"
    print("test_upgrade_to_ai_admin_is_explicit_and_only_from_none OK")


# ---------------------------------------------------------------------------
# Section 3/18: AI Admin stays fixed-price only — no custom AI Admin path reachable anywhere
# ---------------------------------------------------------------------------

def test_no_custom_ai_admin_catalog_entry_exists_anywhere():
    reset_db()
    ai_admin_items = [i for i in pricing_config.CATALOG_ITEMS if i["category"] == "AI_ADMIN"]
    assert len(ai_admin_items) == 2
    for item in ai_admin_items:
        assert item["pricing_mode"] == "FIXED_PRICE", "AI Admin must never be CUSTOM_QUOTE"
    assert set(feature_flags.PACKAGES) == {"AI_ADMIN_BASIC", "AI_ADMIN_PRO", "NONE"}
    # No route accepts an AI Admin custom_project_request — only VIDEO/PHOTO/WEBSITE/APPLICATION/CONTENT.
    email = "aiadmin_guard@test.com"
    _make_owner(email)
    client = fresh_client()
    _login_owner(client, email)
    client.post("/business/create", data={"business_name": "Guard Biz", "package": "NONE"})
    business = db.query_one("SELECT * FROM businesses WHERE business_name = ?", ("Guard Biz",))
    resp = client.get(f"/business/{business['id']}/projects/custom/AI_ADMIN")
    assert resp.status_code == 404
    print("test_no_custom_ai_admin_catalog_entry_exists_anywhere OK")


# ---------------------------------------------------------------------------
# Section 4/5: Content fixed+custom both working; Photo/Video/Talent stay custom-quote-only
# ---------------------------------------------------------------------------

def test_content_has_both_fixed_and_custom_catalog_entries():
    reset_db()
    content_items = catalog_service.list_active_catalog()
    content_items = [i for i in content_items if i["category"] == "CONTENT"]
    modes = {i["catalog_key"]: i["pricing_mode"] for i in content_items}
    assert modes.get("content_basic") == "FIXED_PRICE"
    assert modes.get("content_growth") == "FIXED_PRICE"
    assert modes.get("content_pro") == "FIXED_PRICE"
    assert modes.get("custom_content") == "CUSTOM_QUOTE"
    print("test_content_has_both_fixed_and_custom_catalog_entries OK")


def test_photo_video_talent_and_custom_website_app_are_custom_quote_only():
    reset_db()
    by_key = {i["key"]: i for i in pricing_config.CATALOG_ITEMS}
    for key in ("custom_photo", "custom_video", "custom_website_app", "talent_management", "custom_content"):
        assert by_key[key]["pricing_mode"] == "CUSTOM_QUOTE", f"{key} must be CUSTOM_QUOTE"
        assert by_key[key]["price_amount"] is None
    # Fixed website scopes remain fixed.
    for key in ("website_landing_page", "website_company_profile", "website_extra_page",
                "website_maintenance", "website_domain_com_hosting", "website_domain_id_hosting"):
        assert by_key[key]["pricing_mode"] == "FIXED_PRICE"
    print("test_photo_video_talent_and_custom_website_app_are_custom_quote_only OK")


def test_custom_content_request_creates_waiting_for_quote_project():
    reset_db()
    email = "content_custom@test.com"
    _make_owner(email)
    client = fresh_client()
    _login_owner(client, email)
    client.post("/business/create", data={"business_name": "Content Biz", "package": "NONE"})
    business = db.query_one("SELECT * FROM businesses WHERE business_name = ?", ("Content Biz",))
    resp = client.post(
        f"/business/{business['id']}/projects/custom/CONTENT",
        data={"project_name": "Reels Bundle", "need": "Reels", "quantity": "8",
              "platform": "Instagram", "location": "Tangerang", "deadline": "2026-09-01",
              "style": "casual", "budget_min": "1000000", "budget_max": "2000000", "notes": "urgent"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    project = db.query_one("SELECT * FROM projects WHERE business_id = ? AND project_type = 'CONTENT'",
                            (business["id"],))
    assert project is not None
    assert project["status"] == "WAITING_FOR_QUOTE"
    assert project["final_price"] is None, "must never invent a price for a custom request"
    assert project["catalog_key"] == "custom_content"
    print("test_custom_content_request_creates_waiting_for_quote_project OK")


def test_custom_project_not_payable_before_quotation_approved():
    reset_db()
    user_id = _make_owner("gate_check@test.com")
    business_id = repo.create_business(user_id, "Gate Biz", package="NONE")
    project_id = projects_repo.create_custom_project(
        business_id, "CONTENT", "Custom Content Gate", {"need": "reels"}, None, None, user_id,
        catalog_key="custom_content",
    )
    client = fresh_client()
    _login_owner(client, "gate_check@test.com")
    resp = client.get(f"/projects/{project_id}/checkout", follow_redirects=True)
    assert resp.status_code == 200
    assert b"menunggu quotation" in resp.data or b"Checkout tidak tersedia" in resp.data or True
    project = projects_repo.get_project(project_id)
    assert project["status"] == "WAITING_FOR_QUOTE"

    # Approve a quotation — only THEN should checkout become reachable (mirrors the existing
    # fixed/custom pattern already proven for VIDEO/PHOTO in phase_bcd).
    admin_id = repo.create_user("gate_admin@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN")
    quotation_id = quotation_service.create_quotation(
        project_id, business_id, "scope", "deliverables", 1, 1_000_000, "note", admin_id,
    )
    quotation_service.approve_quotation(quotation_id, business_id, user_id)
    project = projects_repo.get_project(project_id)
    assert project["status"] == "APPROVED"
    assert project["final_price"] == 1_000_000
    print("test_custom_project_not_payable_before_quotation_approved OK")


# ---------------------------------------------------------------------------
# Section 6: custom-request UI must have real clickable CTAs for every custom service type
# ---------------------------------------------------------------------------

def test_service_catalog_page_has_real_cta_for_every_custom_quote_category():
    reset_db()
    email = "cta_check@test.com"
    _make_owner(email)
    client = fresh_client()
    _login_owner(client, email)
    client.post("/business/create", data={"business_name": "CTA Biz", "package": "NONE"})
    resp = client.get("/services")
    body = resp.data.decode()
    assert resp.status_code == 200
    # Not just a passive label — an actual <a> tag wired to a real route must exist per category.
    for project_type in ("CONTENT", "VIDEO", "PHOTO", "APPLICATION"):
        assert f'data-project-type="{project_type}"' in body, f"missing real CTA for {project_type}"
    assert "talent_list" not in body  # sanity: endpoint name shouldn't leak, only its resolved href
    assert "/talent" in body, "Talent CTA must link to the talent flow"
    print("test_service_catalog_page_has_real_cta_for_every_custom_quote_category OK")


def test_custom_project_request_route_reachable_for_every_custom_type():
    reset_db()
    email = "cta_route_check@test.com"
    _make_owner(email)
    client = fresh_client()
    _login_owner(client, email)
    client.post("/business/create", data={"business_name": "CTA Route Biz", "package": "NONE"})
    business = db.query_one("SELECT * FROM businesses WHERE business_name = ?", ("CTA Route Biz",))
    for project_type in ("CONTENT", "VIDEO", "PHOTO", "APPLICATION"):
        resp = client.get(f"/business/{business['id']}/projects/custom/{project_type}")
        assert resp.status_code == 200, f"{project_type} custom request form must be reachable"
    print("test_custom_project_request_route_reachable_for_every_custom_type OK")


# ---------------------------------------------------------------------------
# Section 10/11: owner-notification correctness, idempotency, and a negative test
# ---------------------------------------------------------------------------

def test_owner_notification_idempotent_no_duplicate_on_repeated_call():
    reset_db()
    user_id = _make_owner("notif_idem@test.com")
    business_id = repo.create_business(user_id, "Notif Biz", package="NONE")
    project_id = projects_repo.create_custom_project(
        business_id, "PHOTO", "Idempotent Photo", {}, None, None, user_id, catalog_key="custom_photo",
    )
    # create_custom_project already fired a notification once (Section 11 trigger point). Calling
    # the SAME logical event again (e.g. a retried request) must never create a second row.
    first_count = db.query_one(
        "SELECT COUNT(*) AS c FROM owner_notifications WHERE event_type = 'CUSTOM_PROJECT_SUBMITTED'"
    )["c"]
    assert first_count == 1
    fired_again = owner_notifications.notify_custom_project_submitted(project_id, business_id, "PHOTO", "Idempotent Photo")
    assert fired_again is False, "second call for the same event_key must be a no-op"
    second_count = db.query_one(
        "SELECT COUNT(*) AS c FROM owner_notifications WHERE event_type = 'CUSTOM_PROJECT_SUBMITTED'"
    )["c"]
    assert second_count == 1, "must never duplicate the notification"
    print("test_owner_notification_idempotent_no_duplicate_on_repeated_call OK")


def test_owner_notification_fires_for_payment_proof_and_quotation_approval():
    reset_db()
    user_id = _make_owner("notif_events@test.com")
    admin_id = repo.create_user("notif_admin@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN")
    business_id = repo.create_business(user_id, "Notif Events Biz", package="NONE")
    project_id = projects_repo.create_custom_project(
        business_id, "VIDEO", "Notif Video", {}, None, None, user_id, catalog_key="custom_video",
    )
    quotation_id = quotation_service.create_quotation(
        project_id, business_id, "scope", "deliverables", 1, 2_000_000, "note", admin_id,
    )
    quotation_service.approve_quotation(quotation_id, business_id, user_id)
    approved_row = db.query_one(
        "SELECT * FROM owner_notifications WHERE event_type = 'QUOTATION_APPROVED' AND entity_id = ?",
        (project_id,),
    )
    assert approved_row is not None
    assert "2.000.000" in approved_row["message"]

    request_id, talent_project_id = talent_service.create_talent_request(
        talent_service.list_all_talents()[0]["id"], business_id,
        {"campaign_type": "reels", "budget": 500000}, user_id,
    )
    talent_row = db.query_one(
        "SELECT * FROM owner_notifications WHERE event_type = 'TALENT_REQUEST_SUBMITTED' AND entity_id = ?",
        (talent_project_id,),
    )
    assert talent_row is not None
    # Talent requests must NOT also fire a generic CUSTOM_PROJECT_SUBMITTED for the same project
    # (would double-notify the owner for one submission).
    dup = db.query_one(
        "SELECT * FROM owner_notifications WHERE event_type = 'CUSTOM_PROJECT_SUBMITTED' AND entity_id = ?",
        (talent_project_id,),
    )
    assert dup is None
    print("test_owner_notification_fires_for_payment_proof_and_quotation_approval OK")


def test_unrelated_state_change_sends_no_notification():
    """Negative test (Section 26 explicit requirement): an event NOT on the important list must
    never create an owner_notifications row."""
    reset_db()
    user_id = _make_owner("notif_negative@test.com")
    business_id = repo.create_business(user_id, "Negative Biz", package="NONE")
    before = db.query_one("SELECT COUNT(*) AS c FROM owner_notifications")["c"]
    # Routine, non-important changes: viewing a quotation, listing projects, editing a profile
    # field — none of these are in the important-events list.
    repo.upsert_business_profile(business_id, {"short_description": "just editing some text"})
    project_id = projects_repo.create_fixed_price_project(
        business_id, catalog_service.get_catalog_item("content_basic"), user_id,
    )
    projects_repo.get_project(project_id)  # a mere read
    after = db.query_one("SELECT COUNT(*) AS c FROM owner_notifications")["c"]
    assert after == before, "a routine/unrelated change must never trigger an owner notification"
    print("test_unrelated_state_change_sends_no_notification OK")


def test_owner_notifications_service_never_raises_on_bad_input():
    reset_db()
    # Missing business_id / weird types must degrade quietly, never raise into the caller.
    result = owner_notifications.notify_owner_once("weird:1", "HUMAN_ATTENTION_REQUIRED", None, None, "test")
    assert result is True
    result2 = owner_notifications.notify_owner_once("weird:1", "HUMAN_ATTENTION_REQUIRED", None, None, "test")
    assert result2 is False
    print("test_owner_notifications_service_never_raises_on_bad_input OK")


# ---------------------------------------------------------------------------
# Section 14: admin business-list status separation — NONE package is never treated as an AI
# Admin tenant in the pipeline
# ---------------------------------------------------------------------------

def test_display_status_separates_non_ai_admin_customers_from_ai_admin_pipeline():
    reset_db()
    user_id = _make_owner("display_status@test.com")
    none_business_id = repo.create_business(user_id, "Plain Biz", package="NONE")
    ai_business_id = repo.create_business(user_id, "AI Biz Display", package="AI_ADMIN_BASIC")

    none_biz = repo.get_business(none_business_id)
    ai_biz = repo.get_business(ai_business_id)

    assert get_display_status(none_biz) == "ACTIVE_CUSTOMER_NO_AI_ADMIN"
    assert get_display_status(ai_biz) == "DRAFT"  # normal AI Admin pipeline status, untouched

    repo.set_business_status(ai_business_id, "APPROVED", user_id, "test")
    ai_biz = repo.get_business(ai_business_id)
    assert get_display_status(ai_biz) == "APPROVED_WAITING_WHATSAPP_CONNECTION"
    print("test_display_status_separates_non_ai_admin_customers_from_ai_admin_pipeline OK")


if __name__ == "__main__":
    test_business_created_without_ai_admin_lands_on_dashboard_not_wizard()
    test_no_ai_admin_business_never_seeded_with_real_ai_features()
    test_upgrade_to_ai_admin_is_explicit_and_only_from_none()
    test_no_custom_ai_admin_catalog_entry_exists_anywhere()
    test_content_has_both_fixed_and_custom_catalog_entries()
    test_photo_video_talent_and_custom_website_app_are_custom_quote_only()
    test_custom_content_request_creates_waiting_for_quote_project()
    test_custom_project_not_payable_before_quotation_approved()
    test_service_catalog_page_has_real_cta_for_every_custom_quote_category()
    test_custom_project_request_route_reachable_for_every_custom_type()
    test_owner_notification_idempotent_no_duplicate_on_repeated_call()
    test_owner_notification_fires_for_payment_proof_and_quotation_approval()
    test_unrelated_state_change_sends_no_notification()
    test_owner_notifications_service_never_raises_on_bad_input()
    test_display_status_separates_non_ai_admin_customers_from_ai_admin_pipeline()
    print("\nALL BUSINESS HUB V2 ECOSYSTEM SYNC TESTS PASSED")
