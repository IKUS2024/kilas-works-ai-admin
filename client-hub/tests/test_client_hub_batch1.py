"""Client Hub Batch 1 — regression tests.

Covers:
  1. Multi-file business knowledge upload
  2. Global status/WIB formatting (spot checks on newly-fixed pages)
  3. Customer order actions (Draft/Payment pending/Under review/Paid gating)
  4. Activation checklist

Run with:
    cd client-hub && python3 tests/test_client_hub_batch1.py
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


# ---------------------------------------------------------------------------
# 1. MULTI-FILE UPLOAD
# ---------------------------------------------------------------------------
def test_multi_file_upload_saves_all_files_in_one_submission():
    import io
    reset_db()
    uid, bid = _make_owner_and_business("Biz Multi", "multi@test.com")
    client = fresh_client()
    _login_owner(client, "multi@test.com")
    resp = client.post(f"/business/{bid}/files/upload", data={
        "csrf_token": "x",
        "file": [
            (io.BytesIO(b"katalog produk isi 1"), "katalog1.txt"),
            (io.BytesIO(b"katalog produk isi 2"), "katalog2.txt"),
        ],
    }, content_type="multipart/form-data")
    assert resp.status_code == 302
    files = repo.list_business_files(bid)
    assert len(files) == 2, f"both files must be saved, got {len(files)}"
    names = {f["original_filename"] for f in files}
    assert "katalog1.txt" in names and "katalog2.txt" in names
    print("test_multi_file_upload_saves_all_files_in_one_submission OK")


def test_old_files_remain_after_new_upload():
    import io
    reset_db()
    uid, bid = _make_owner_and_business("Biz Multi2", "multi2@test.com")
    client = fresh_client()
    _login_owner(client, "multi2@test.com")
    client.post(f"/business/{bid}/files/upload", data={
        "csrf_token": "x", "file": [(io.BytesIO(b"file lama"), "lama.txt")],
    }, content_type="multipart/form-data")
    client.post(f"/business/{bid}/files/upload", data={
        "csrf_token": "x", "file": [(io.BytesIO(b"file baru"), "baru.txt")],
    }, content_type="multipart/form-data")
    files = repo.list_business_files(bid)
    names = {f["original_filename"] for f in files}
    assert "lama.txt" in names and "baru.txt" in names, "old files must remain after a new upload"
    print("test_old_files_remain_after_new_upload OK")


def test_files_persist_through_ai_setup_failure():
    import io
    from unittest.mock import patch
    import ai_onboarding
    reset_db()
    uid, bid = _make_owner_and_business("Biz Multi3", "multi3@test.com")
    client = fresh_client()
    _login_owner(client, "multi3@test.com")
    client.post(f"/business/{bid}/wizard/basics", data={
        "business_name": "Biz Multi3", "category": "Kedai Kopi", "owner_name": "Budi",
    })
    client.post(f"/business/{bid}/wizard/services", data={"services_raw": "Kopi susu: 20rb"})
    client.post(f"/business/{bid}/files/upload", data={
        "csrf_token": "x", "file": [(io.BytesIO(b"menu lengkap"), "menu.txt")],
    }, content_type="multipart/form-data")

    with patch.object(ai_onboarding, "_call_claude", return_value=(None, None, "SIMULATED_API_FAILURE")):
        client.post(f"/business/{bid}/ai-setup/run")

    files = repo.list_business_files(bid)
    assert len(files) == 1 and files[0]["original_filename"] == "menu.txt", \
        "an uploaded file must never be deleted merely because AI Setup failed"
    print("test_files_persist_through_ai_setup_failure OK")


def test_admin_review_shows_all_uploaded_files():
    import io
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz Multi4", "multi4@test.com")
    client = fresh_client()
    _login_owner(client, "multi4@test.com")
    client.post(f"/business/{bid}/files/upload", data={
        "csrf_token": "x",
        "file": [(io.BytesIO(b"a"), "a.txt"), (io.BytesIO(b"b"), "b.txt")],
    }, content_type="multipart/form-data")

    admin_client = fresh_client()
    _login_admin(admin_client, admin)
    resp = admin_client.get(f"/admin/business/{bid}")
    body = resp.data.decode()
    assert "a.txt" in body and "b.txt" in body
    print("test_admin_review_shows_all_uploaded_files OK")


# ---------------------------------------------------------------------------
# 2. GLOBAL STATUS / WIB SPOT CHECKS
# ---------------------------------------------------------------------------
def test_admin_dashboard_no_raw_timestamp():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz WIB", "wib@test.com")
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get("/admin/")
    body = resp.data.decode()
    assert "WIB" in body
    import re
    assert not re.search(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\.\d+", body)
    print("test_admin_dashboard_no_raw_timestamp OK")


def test_subscription_status_humanized_on_review_page():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz Sub", "sub@test.com", package="AI_ADMIN_PRO")
    import subscription_service
    subscription_service.create_subscription(bid, "ai_admin_pro", actor_user_id=admin["id"])
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get(f"/admin/business/{bid}")
    body = resp.data.decode()
    assert "Aktif" in body
    print("test_subscription_status_humanized_on_review_page OK")


# ---------------------------------------------------------------------------
# 3. CUSTOMER ORDER ACTIONS
# ---------------------------------------------------------------------------
def test_waiting_for_quote_shows_cancel():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Order1", "order1@test.com", package="NONE")
    pid = projects_repo.create_custom_project(bid, "PHOTO", "Foto Produk", {}, None, None, uid)
    client = fresh_client()
    _login_owner(client, "order1@test.com")
    resp = client.get(f"/business/{bid}/projects/{pid}")
    body = resp.data.decode()
    assert "Batalkan" in body
    print("test_waiting_for_quote_shows_cancel OK")


def test_approved_project_shows_edit_and_cancel():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Order2", "order2@test.com", package="NONE")
    item = catalog_service.get_catalog_item("website_landing_page")
    pid = projects_repo.create_fixed_price_project(bid, item, uid)
    client = fresh_client()
    _login_owner(client, "order2@test.com")
    resp = client.get(f"/business/{bid}/projects/{pid}")
    body = resp.data.decode()
    assert "Lanjut ke Checkout" in body
    assert "Batalkan" in body
    print("test_approved_project_shows_edit_and_cancel OK")


def test_payment_pending_shows_lanjut_bayar_and_cancel():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Order3", "order3@test.com", package="NONE")
    item = catalog_service.get_catalog_item("website_landing_page")
    pid = projects_repo.create_fixed_price_project(bid, item, uid)
    payment_service.checkout(pid, bid, uid)
    client = fresh_client()
    _login_owner(client, "order3@test.com")
    resp = client.get(f"/business/{bid}/projects/{pid}")
    body = resp.data.decode()
    assert "Lanjut Bayar" in body
    assert "Batalkan Pesanan" in body
    print("test_payment_pending_shows_lanjut_bayar_and_cancel OK")


def test_proof_under_review_no_self_cancel():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Order4", "order4@test.com", package="NONE")
    item = catalog_service.get_catalog_item("website_landing_page")
    pid = projects_repo.create_fixed_price_project(bid, item, uid)
    inv_id = payment_service.checkout(pid, bid, uid)
    payment = payment_service.get_payment_for_invoice(inv_id)
    db.execute("UPDATE payments SET status = 'UNDER_REVIEW' WHERE id = ?", (payment["id"],))
    client = fresh_client()
    _login_owner(client, "order4@test.com")
    resp = client.get(f"/business/{bid}/projects/{pid}")
    body = resp.data.decode()
    assert "sedang direview" in body
    assert "Batalkan Pesanan" not in body
    print("test_proof_under_review_no_self_cancel OK")


def test_cancel_blocked_at_route_level_even_if_ui_bypassed():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Order5", "order5@test.com", package="NONE")
    item = catalog_service.get_catalog_item("website_landing_page")
    pid = projects_repo.create_fixed_price_project(bid, item, uid)
    inv_id = payment_service.checkout(pid, bid, uid)
    payment = payment_service.get_payment_for_invoice(inv_id)
    db.execute("UPDATE payments SET status = 'UNDER_REVIEW' WHERE id = ?", (payment["id"],))
    client = fresh_client()
    _login_owner(client, "order5@test.com")
    client.post(f"/business/{bid}/projects/{pid}/cancel", data={"csrf_token": "x"})
    project = projects_repo.get_project(pid)
    assert project["status"] != "CANCELLED", "cancel must be rejected server-side, not just hidden in UI"
    print("test_cancel_blocked_at_route_level_even_if_ui_bypassed OK")


def test_paid_project_no_cancel_button_view_only():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz Order6", "order6@test.com", package="NONE")
    item = catalog_service.get_catalog_item("website_landing_page")
    pid = projects_repo.create_fixed_price_project(bid, item, uid)
    inv_id = payment_service.checkout(pid, bid, uid)
    payment = payment_service.get_payment_for_invoice(inv_id)
    db.execute("UPDATE payments SET status = 'UNDER_REVIEW' WHERE id = ?", (payment["id"],))
    payment_service.verify_payment(payment["id"], bid, admin["id"])
    client = fresh_client()
    _login_owner(client, "order6@test.com")
    resp = client.get(f"/business/{bid}/projects/{pid}")
    body = resp.data.decode()
    assert "Batalkan" not in body
    print("test_paid_project_no_cancel_button_view_only OK")


def test_cancel_never_hard_deletes_historical_record():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Order7", "order7@test.com", package="NONE")
    item = catalog_service.get_catalog_item("website_landing_page")
    pid = projects_repo.create_fixed_price_project(bid, item, uid)
    client = fresh_client()
    _login_owner(client, "order7@test.com")
    client.post(f"/business/{bid}/projects/{pid}/cancel", data={"csrf_token": "x"})
    project = projects_repo.get_project(pid)
    assert project is not None, "the project row must never be hard-deleted"
    assert project["status"] == "CANCELLED"
    audit = repo.get_audit_log(bid)
    assert any(a["action"] == "PROJECT_STATUS_CHANGED" for a in audit)
    print("test_cancel_never_hard_deletes_historical_record OK")


# ---------------------------------------------------------------------------
# 4. ACTIVATION CHECKLIST
# ---------------------------------------------------------------------------
def test_activation_checklist_has_six_items_in_order():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Checklist", "checklist@test.com", package="AI_ADMIN_PRO")
    checklist = payment_service.build_activation_checklist(bid)
    keys = [c["key"] for c in checklist]
    assert keys == ["data_bisnis", "knowledge", "payment", "whatsapp", "test_ai", "active"]
    print("test_activation_checklist_has_six_items_in_order OK")


def test_activation_checklist_reflects_real_state():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz Checklist2", "checklist2@test.com", package="AI_ADMIN_PRO")
    checklist = payment_service.build_activation_checklist(bid)
    assert all(c["done"] is False for c in checklist), "a brand-new business must have nothing done yet"

    client = fresh_client()
    _login_owner(client, "checklist2@test.com")
    client.post(f"/business/{bid}/wizard/basics", data={
        "business_name": "Biz Checklist2", "category": "Kedai Kopi", "owner_name": "Budi",
    })
    client.post(f"/business/{bid}/wizard/services", data={"services_raw": "Kopi: 20rb"})
    client.post(f"/business/{bid}/wizard/operations", data={"operating_hours": "09-17"})
    client.post(f"/business/{bid}/wizard/faq", data={"faq_raw": "Bisa COD? Bisa."})
    client.post(f"/business/{bid}/wizard/style", data={"tone": "friendly", "primary_language": "id"})

    checklist2 = payment_service.build_activation_checklist(bid)
    data_bisnis = next(c for c in checklist2 if c["key"] == "data_bisnis")
    assert data_bisnis["done"] is True
    print("test_activation_checklist_reflects_real_state OK")


def test_activation_checklist_visible_on_review_page():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz Checklist3", "checklist3@test.com", package="AI_ADMIN_PRO")
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get(f"/admin/business/{bid}")
    body = resp.data.decode()
    assert "Progres Aktivasi" in body
    assert "Data Bisnis" in body
    assert "WhatsApp" in body
    print("test_activation_checklist_visible_on_review_page OK")


if __name__ == "__main__":
    test_multi_file_upload_saves_all_files_in_one_submission()
    test_old_files_remain_after_new_upload()
    test_files_persist_through_ai_setup_failure()
    test_admin_review_shows_all_uploaded_files()
    test_admin_dashboard_no_raw_timestamp()
    test_subscription_status_humanized_on_review_page()
    test_waiting_for_quote_shows_cancel()
    test_approved_project_shows_edit_and_cancel()
    test_payment_pending_shows_lanjut_bayar_and_cancel()
    test_proof_under_review_no_self_cancel()
    test_cancel_blocked_at_route_level_even_if_ui_bypassed()
    test_paid_project_no_cancel_button_view_only()
    test_cancel_never_hard_deletes_historical_record()
    test_activation_checklist_has_six_items_in_order()
    test_activation_checklist_reflects_real_state()
    test_activation_checklist_visible_on_review_page()
    print("ALL BATCH 1 TESTS PASSED")
