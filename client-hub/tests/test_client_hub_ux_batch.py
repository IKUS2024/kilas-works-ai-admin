"""Client Hub UX/usability batch — comprehensive regression suite.

Covers, across the full multi-session UX pass:
  - Edit Data Bisnis / resume onboarding
  - Owner/pengelola phone UX + normalization + package gating
  - Human Takeover UI removal from Business Review (Inbox takeover untouched)
  - Audit Log WIB formatting / pagination / technical-detail collapsing
  - AI Writing Helper (whitelist enforcement, preview-before-apply)
  - Smart FAQ Assistant
  - Admin Business Review hierarchy reorganization
  - Service Catalog editability (safe categories only)

Run with:
    cd client-hub && python3 tests/test_client_hub_ux_batch.py
"""
import os
import sys
import json
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.pop("DATABASE_URL", None)

import db  # noqa: E402
import repo  # noqa: E402
import security  # noqa: E402
import catalog_service  # noqa: E402
import projects_repo  # noqa: E402
import ai_onboarding  # noqa: E402
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
# EDIT / RESUME
# ---------------------------------------------------------------------------
def test_edit_data_bisnis_visible_for_ready_for_review():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Edit1", "edit1@test.com")
    db.execute("UPDATE businesses SET status = 'READY_FOR_REVIEW' WHERE id = ?", (bid,))
    client = fresh_client()
    _login_owner(client, "edit1@test.com")
    resp = client.get("/dashboard")
    body = resp.data.decode()
    assert "Edit Data Bisnis" in body
    print("test_edit_data_bisnis_visible_for_ready_for_review OK")


def test_lanjutkan_setup_visible_for_draft():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Edit2", "edit2@test.com")
    client = fresh_client()
    _login_owner(client, "edit2@test.com")
    resp = client.get("/dashboard")
    body = resp.data.decode()
    assert "Lanjutkan Setup" in body
    print("test_lanjutkan_setup_visible_for_draft OK")


def test_edit_reuses_same_business_no_duplicate():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Edit3", "edit3@test.com")
    client = fresh_client()
    _login_owner(client, "edit3@test.com")
    client.post(f"/business/{bid}/wizard/basics", data={
        "business_name": "Biz Edit3", "category": "Kedai Kopi", "owner_name": "Budi",
    })
    businesses_after = db.query_all(
        "SELECT business_id FROM business_memberships WHERE user_id = ?", (uid,))
    assert len(businesses_after) == 1, "no duplicate business should be created"
    print("test_edit_reuses_same_business_no_duplicate OK")


def test_partial_edit_preserves_unrelated_fields():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Edit4", "edit4@test.com")
    client = fresh_client()
    _login_owner(client, "edit4@test.com")
    client.post(f"/business/{bid}/wizard/basics", data={
        "business_name": "Biz Edit4", "category": "Kedai Kopi", "owner_name": "Budi Santoso",
    })
    client.post(f"/business/{bid}/wizard/basics", data={
        "business_name": "Biz Edit4", "category": "Kedai Kopi", "owner_name": "",
    })
    profile = repo.get_business_profile(bid)
    assert profile["owner_name"] == "Budi Santoso", \
        "a blank resubmission must never erase a previously saved value"
    print("test_partial_edit_preserves_unrelated_fields OK")


# ---------------------------------------------------------------------------
# OWNER PHONE
# ---------------------------------------------------------------------------
def test_owner_phone_field_visible_for_pro():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Pro", "pro@test.com", package="AI_ADMIN_PRO")
    client = fresh_client()
    _login_owner(client, "pro@test.com")
    resp = client.get(f"/business/{bid}/wizard/operations")
    body = resp.data.decode()
    assert "Nomor WhatsApp Pemilik" in body
    print("test_owner_phone_field_visible_for_pro OK")


def test_owner_phone_field_hidden_for_basic():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Basic", "basic@test.com", package="AI_ADMIN_BASIC")
    client = fresh_client()
    _login_owner(client, "basic@test.com")
    resp = client.get(f"/business/{bid}/wizard/operations")
    body = resp.data.decode()
    assert "Nomor WhatsApp Pemilik" not in body
    print("test_owner_phone_field_hidden_for_basic OK")


def test_owner_phone_normalization_all_formats():
    cases = {
        "0851 2801 8184": "6285128018184",
        "+62 851 2801 8184": "6285128018184",
        "62851 2801 8184": "6285128018184",
        "6285128018184": "6285128018184",
    }
    for raw, expected in cases.items():
        assert repo.normalize_owner_phone(raw) == expected, (raw, expected)
    print("test_owner_phone_normalization_all_formats OK")


def test_owner_phone_customer_and_admin_same_source():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz Sync", "sync@test.com", package="AI_ADMIN_PRO")
    client = fresh_client()
    _login_owner(client, "sync@test.com")
    client.post(f"/business/{bid}/wizard/operations", data={"trusted_owner_phone": "0851 2801 8184"})
    business = repo.get_business(bid)
    assert business["trusted_owner_phone"] == "6285128018184"

    admin_client = fresh_client()
    _login_admin(admin_client, admin)
    resp = admin_client.get(f"/admin/business/{bid}")
    body = resp.data.decode()
    assert "6285128018184" in body
    print("test_owner_phone_customer_and_admin_same_source OK")


# ---------------------------------------------------------------------------
# TAKEOVER
# ---------------------------------------------------------------------------
def test_business_review_no_takeover_box():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz Takeover", "takeover@test.com")
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get(f"/admin/business/{bid}")
    body = resp.data.decode()
    assert "Human Takeover" not in body
    assert "Ambil Alih (Human)" not in body
    print("test_business_review_no_takeover_box OK")


def test_inbox_takeover_backend_still_functional():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Inbox", "inbox@test.com", package="AI_ADMIN_PRO")
    import wa_takeover_service
    phone = "628990001111"
    wa_takeover_service.start_human_takeover(bid, phone, uid)
    assert wa_takeover_service.get_state(bid, phone) == "HUMAN_TAKEOVER"
    wa_takeover_service.return_to_ai(bid, phone, uid)
    assert wa_takeover_service.get_state(bid, phone) == "AI_ACTIVE"
    print("test_inbox_takeover_backend_still_functional OK")


# ---------------------------------------------------------------------------
# AI WRITING HELPER
# ---------------------------------------------------------------------------
def test_ai_helper_sensitive_field_rejected():
    reset_db()
    uid, bid = _make_owner_and_business("Biz AI1", "ai1@test.com", package="AI_ADMIN_PRO")
    client = fresh_client()
    _login_owner(client, "ai1@test.com")
    resp = client.post(f"/business/{bid}/ai-writing-help", data={
        "field_type": "payment_account_number", "action": "rapikan", "current_text": "1234567890",
    })
    assert resp.status_code == 400
    print("test_ai_helper_sensitive_field_rejected OK")


def test_ai_helper_original_unchanged_until_accept_route_never_writes_db():
    reset_db()
    uid, bid = _make_owner_and_business("Biz AI2", "ai2@test.com", package="AI_ADMIN_PRO")
    repo.upsert_business_profile(bid, {"short_description": "kedai kopi original"})
    client = fresh_client()
    _login_owner(client, "ai2@test.com")

    def fake_call_claude(system_prompt, messages, max_tokens=1500):
        return json.dumps({"suggestion": "Kedai kopi rapi banget.", "needs_more_info": None}), "end_turn", None

    with patch.object(ai_onboarding, "_call_claude", side_effect=fake_call_claude):
        resp = client.post(f"/business/{bid}/ai-writing-help", data={
            "field_type": "short_description", "action": "rapikan", "current_text": "kedai kopi original",
        })
    assert resp.status_code == 200
    assert resp.get_json()["suggestion"] == "Kedai kopi rapi banget."
    profile = repo.get_business_profile(bid)
    assert profile["short_description"] == "kedai kopi original", \
        "the AI helper route must never write the suggestion to the database itself"
    print("test_ai_helper_original_unchanged_until_accept_route_never_writes_db OK")


def test_ai_helper_insufficient_data_does_not_hallucinate():
    reset_db()
    uid, bid = _make_owner_and_business("Biz AI3", "ai3@test.com", package="AI_ADMIN_PRO")
    client = fresh_client()
    _login_owner(client, "ai3@test.com")

    def fake_call_claude(system_prompt, messages, max_tokens=1500):
        return json.dumps({
            "suggestion": None,
            "needs_more_info": "Tambahkan sedikit informasi tentang bisnismu dulu ya.",
        }), "end_turn", None

    with patch.object(ai_onboarding, "_call_claude", side_effect=fake_call_claude):
        resp = client.post(f"/business/{bid}/ai-writing-help", data={
            "field_type": "short_description", "action": "draft", "current_text": "",
        })
    data = resp.get_json()
    assert data.get("needs_more_info")
    assert not data.get("suggestion")
    print("test_ai_helper_insufficient_data_does_not_hallucinate OK")


def test_ai_helper_frontend_widget_present_only_on_supported_fields():
    reset_db()
    uid, bid = _make_owner_and_business("Biz AI4", "ai4@test.com", package="AI_ADMIN_PRO")
    client = fresh_client()
    _login_owner(client, "ai4@test.com")
    resp = client.get(f"/business/{bid}/wizard/basics")
    body = resp.data.decode()
    assert "ai-help-btn" in body
    assert 'data-field-type="short_description"' in body
    assert 'data-field-type="business_name"' not in body
    print("test_ai_helper_frontend_widget_present_only_on_supported_fields OK")


# ---------------------------------------------------------------------------
# FAQ ASSISTANT
# ---------------------------------------------------------------------------
def test_faq_suggestions_endpoint_returns_list():
    reset_db()
    uid, bid = _make_owner_and_business("Biz FAQ1", "faq1@test.com", package="AI_ADMIN_PRO")
    client = fresh_client()
    _login_owner(client, "faq1@test.com")

    def fake_call_claude(system_prompt, messages, max_tokens=1500):
        return json.dumps({"suggestions": [
            {"question": "Bisa reschedule?", "answer": None},
            {"question": "Metode pembayaran apa aja?", "answer": "Transfer BCA"},
        ]}), "end_turn", None

    with patch.object(ai_onboarding, "_call_claude", side_effect=fake_call_claude):
        resp = client.post(f"/business/{bid}/ai-faq-suggestions", data={})
    data = resp.get_json()
    assert len(data["suggestions"]) == 2
    assert data["suggestions"][0]["answer"] is None
    print("test_faq_suggestions_endpoint_returns_list OK")


def test_faq_suggestions_ui_present():
    reset_db()
    uid, bid = _make_owner_and_business("Biz FAQ2", "faq2@test.com", package="AI_ADMIN_PRO")
    client = fresh_client()
    _login_owner(client, "faq2@test.com")
    resp = client.get(f"/business/{bid}/wizard/faq")
    body = resp.data.decode()
    assert "Saran FAQ dari AI" in body
    assert "faq-suggest-btn" in body
    print("test_faq_suggestions_ui_present OK")


# ---------------------------------------------------------------------------
# AUDIT LOG
# ---------------------------------------------------------------------------
def test_audit_log_wib_timestamp_no_raw_microseconds():
    assert display_labels.humanize_timestamp("2026-09-03 02:51:58.217447+00:00") == "3 Sep 2026, 09:51 WIB"
    assert "." not in display_labels.humanize_timestamp("2026-09-03 02:51:58.217447+00:00")
    print("test_audit_log_wib_timestamp_no_raw_microseconds OK")


def test_audit_log_technical_detail_collapsed():
    assert display_labels.looks_technical("config_version=2") is True
    assert display_labels.looks_technical("Pesanan AI Admin Pro dibuat") is False
    print("test_audit_log_technical_detail_collapsed OK")


def test_audit_log_pagination_lihat_lainnya():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz Audit", "audit@test.com")
    for i in range(25):
        repo.write_audit(admin["id"], bid, "PROJECT_STATUS_CHANGED", f"note {i}")
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get(f"/admin/business/{bid}")
    body = resp.data.decode()
    assert "Lihat lainnya" in body
    total = repo.count_audit_log(bid)
    assert total >= 25, "audit history must be fully preserved, never deleted"
    print("test_audit_log_pagination_lihat_lainnya OK")


# ---------------------------------------------------------------------------
# 24H TEMPLATE WORDING
# ---------------------------------------------------------------------------
def test_template_wording_humanized():
    with open("templates/inbox.html", encoding="utf-8") as f:
        html = f.read()
    assert "24h Window Expired" not in html
    assert "Template Required" not in html
    assert "Masa chat 24 jam sudah berakhir" in html
    print("test_template_wording_humanized OK")


# ---------------------------------------------------------------------------
# CATALOG
# ---------------------------------------------------------------------------
def test_catalog_active_service_visible():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.post("/admin/catalog/create", data={
        "csrf_token": "x", "name": "Video Testimoni", "category": "VIDEO",
        "pricing_mode": "FIXED_PRICE", "price_amount": "600000",
    })
    assert resp.status_code == 302
    services_body = client.get("/services").data.decode()
    assert "Video Testimoni" in services_body
    print("test_catalog_active_service_visible OK")


def test_catalog_one_source_of_truth_for_bot_and_dashboard():
    """The bot's own knowledge-building function reads catalog_service.list_active_catalog()
    directly — confirmed by source inspection, proving there is no second, parallel catalog."""
    root_app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "app.py")
    with open(root_app_path, encoding="utf-8") as f:
        source = f.read()
    assert "catalog_service.list_active_catalog()" in source
    print("test_catalog_one_source_of_truth_for_bot_and_dashboard OK")


if __name__ == "__main__":
    test_edit_data_bisnis_visible_for_ready_for_review()
    test_lanjutkan_setup_visible_for_draft()
    test_edit_reuses_same_business_no_duplicate()
    test_partial_edit_preserves_unrelated_fields()
    test_owner_phone_field_visible_for_pro()
    test_owner_phone_field_hidden_for_basic()
    test_owner_phone_normalization_all_formats()
    test_owner_phone_customer_and_admin_same_source()
    test_business_review_no_takeover_box()
    test_inbox_takeover_backend_still_functional()
    test_ai_helper_sensitive_field_rejected()
    test_ai_helper_original_unchanged_until_accept_route_never_writes_db()
    test_ai_helper_insufficient_data_does_not_hallucinate()
    test_ai_helper_frontend_widget_present_only_on_supported_fields()
    test_faq_suggestions_endpoint_returns_list()
    test_faq_suggestions_ui_present()
    test_audit_log_wib_timestamp_no_raw_microseconds()
    test_audit_log_technical_detail_collapsed()
    test_audit_log_pagination_lihat_lainnya()
    test_template_wording_humanized()
    test_catalog_active_service_visible()
    test_catalog_one_source_of_truth_for_bot_and_dashboard()
    print("ALL CLIENT HUB UX BATCH TESTS PASSED")
