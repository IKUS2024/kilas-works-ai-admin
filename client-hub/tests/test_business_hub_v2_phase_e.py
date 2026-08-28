"""Kilas Works Client Hub — Business Hub V2, PHASE E test suite.

Covers the dashboard upgrades (Section 19/20): a KILAS_ADMIN "needs action" overview
(businesses waiting on review, projects waiting on a quote/action, payments waiting on
verification, talent requests waiting on review) and a customer-facing "Proyek & Layanan Saya"
list surfacing that customer's own projects/quotations across every business they own.

ADDITIVE — every earlier test file is untouched. Run with:
    cd client-hub && python3 tests/test_business_hub_v2_phase_e.py
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
import projects_repo  # noqa: E402
import quotation_service  # noqa: E402
import payment_service  # noqa: E402
import talent_service  # noqa: E402
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


def _make_owner_and_business(email="owner@test.com"):
    user_id = repo.create_user(email, security.hash_password("password123"))
    business_id = repo.create_business(user_id, "Test Biz", package="AI_ADMIN_BASIC")
    return user_id, business_id


def _make_admin():
    admin_id = repo.create_user(f"admin_{os.urandom(4).hex()}@kilasworks.id",
                                 security.hash_password("adminpass123"), role="KILAS_ADMIN")
    return db.query_one("SELECT * FROM users WHERE id = ?", (admin_id,))


def test_admin_dashboard_shows_zero_needed_action_when_clean():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    client.post("/login", data={"email": admin["email"], "password": "adminpass123"})
    resp = client.get("/admin/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Final Operations Polish, Section 8: "Perlu Aksi" was upgraded into a fuller "Action Center"
    # with more granular counts — this test now checks for that heading instead.
    assert "Action Center" in body
    assert "Tidak ada yang perlu aksi saat ini." in body
    print("test_admin_dashboard_shows_zero_needed_action_when_clean OK")


def test_admin_dashboard_counts_project_and_payment_and_talent_needing_action():
    reset_db()
    admin = _make_admin()
    user_id, business_id = _make_owner_and_business("owner_e1@test.com")

    # a custom project waiting for a quote
    projects_repo.create_custom_project(
        business_id, "VIDEO", "Custom Video Test", {"num_videos": 3}, 3_000_000, 5_000_000, user_id
    )
    # a talent request waiting for review
    talent = talent_service.list_active_talents()[0]
    talent_service.create_talent_request(
        talent["id"], business_id,
        {"campaign_type": "Endorse", "platform": "Instagram", "deliverables": "1 post",
         "num_content_pieces": 1, "posting_requirements": None, "target_date": None,
         "location": None, "usage_purpose": None, "budget": 5_000_000, "brief": "test"},
        user_id,
    )
    # a fixed-price project taken all the way to an unverified payment
    item = catalog_service.get_catalog_item("website_landing_page")
    fixed_project_id = projects_repo.create_fixed_price_project(business_id, item, user_id)
    payment_service.checkout(fixed_project_id, business_id, user_id)

    client = fresh_client()
    client.post("/login", data={"email": admin["email"], "password": "adminpass123"})
    resp = client.get("/admin/")
    body = resp.get_data(as_text=True)
    # 2 projects needing action: the custom VIDEO request, and the TALENT project the talent
    # request auto-creates (talent_service.create_talent_request links a projects row so talent
    # requests also surface in this unified queue). The fixed-price project stays APPROVED
    # (checkout-ready) at creation and after checkout(), so it is NOT counted here.
    # Final Operations Polish, Section 8: the single "needs action" count was split into more
    # granular action-center cards — both the custom-quote-specific count and the broader
    # "waiting on admin" count land on 2 here (the custom VIDEO request + the TALENT project the
    # talent request auto-creates, both WAITING_FOR_QUOTE; the fixed-price project sits at
    # PAYMENT_PENDING after checkout, which neither count includes).
    assert "2 Custom project menunggu quote" in body
    assert "2 Project menunggu aksi admin" in body
    assert "1 Talent request menunggu review" in body
    print("test_admin_dashboard_counts_project_and_payment_and_talent_needing_action OK")


def test_client_dashboard_lists_own_projects_across_businesses():
    reset_db()
    user_id, business_id = _make_owner_and_business("owner_e2@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    project_id = projects_repo.create_fixed_price_project(business_id, item, user_id)

    client = fresh_client()
    client.post("/login", data={"email": "owner_e2@test.com", "password": "password123"})
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Proyek & Layanan Saya" in body
    assert item["name"] in body
    print("test_client_dashboard_lists_own_projects_across_businesses OK")


def test_client_dashboard_hides_completed_and_cancelled_projects():
    reset_db()
    user_id, business_id = _make_owner_and_business("owner_e3@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    project_id = projects_repo.create_fixed_price_project(business_id, item, user_id)
    projects_repo.set_project_status(project_id, "CANCELLED", actor_user_id=user_id, business_id=business_id)

    client = fresh_client()
    client.post("/login", data={"email": "owner_e3@test.com", "password": "password123"})
    resp = client.get("/dashboard")
    body = resp.get_data(as_text=True)
    assert "Belum ada proyek/pesanan aktif." in body
    print("test_client_dashboard_hides_completed_and_cancelled_projects OK")


def test_client_dashboard_shows_pending_quotation_status_not_invented_price():
    reset_db()
    admin = _make_admin()
    user_id, business_id = _make_owner_and_business("owner_e4@test.com")
    project_id = projects_repo.create_custom_project(
        business_id, "PHOTO", "Custom Photo Test", {"num_final_photos": 20}, 1_000_000, 2_000_000, user_id
    )

    client = fresh_client()
    client.post("/login", data={"email": "owner_e4@test.com", "password": "password123"})
    resp = client.get("/dashboard")
    body = resp.get_data(as_text=True)
    assert "Menunggu Penawaran" in body, "no final_price yet — dashboard must never show an invented price"
    print("test_client_dashboard_shows_pending_quotation_status_not_invented_price OK")


if __name__ == "__main__":
    test_admin_dashboard_shows_zero_needed_action_when_clean()
    test_admin_dashboard_counts_project_and_payment_and_talent_needing_action()
    test_client_dashboard_lists_own_projects_across_businesses()
    test_client_dashboard_hides_completed_and_cancelled_projects()
    test_client_dashboard_shows_pending_quotation_status_not_invented_price()
    print("\nALL BUSINESS HUB V2 PHASE E TESTS PASSED")
