"""Client Hub Batch 2+3 — regression tests.

Covers:
  A. Knowledge file delete/replace, stale marking, visibility in edit/admin
  B. Activation checklist Template item + next_action hints
  C. 429 safe-retry on the platform template bridge
  D. Wajib/Opsional labels present in wizard

Run with:
    cd client-hub && python3 tests/test_client_hub_batch2_3.py
"""
import os
import sys
import io
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("DATABASE_URL", None)

import db  # noqa: E402
import repo  # noqa: E402
import security  # noqa: E402
import catalog_service  # noqa: E402
import payment_service  # noqa: E402
import platform_inbox_service  # noqa: E402
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
# A. KNOWLEDGE FILE MANAGEMENT
# ---------------------------------------------------------------------------
def test_delete_file_removes_only_that_file():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Del1", "del1@test.com")
    client = fresh_client()
    _login_owner(client, "del1@test.com")
    client.post(f"/business/{bid}/files/upload", data={
        "csrf_token": "x", "file": [(io.BytesIO(b"a"), "a.txt"), (io.BytesIO(b"b"), "b.txt")],
    }, content_type="multipart/form-data")
    files = repo.list_business_files(bid)
    target = next(f for f in files if f["original_filename"] == "a.txt")

    resp = client.post(f"/business/{bid}/files/{target['id']}/delete", data={"csrf_token": "x"})
    assert resp.status_code == 302
    remaining = repo.list_business_files(bid)
    names = {f["original_filename"] for f in remaining}
    assert "a.txt" not in names
    assert "b.txt" in names, "deleting one file must never affect other files"
    print("test_delete_file_removes_only_that_file OK")


def test_delete_file_does_not_affect_other_business_data():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Del2", "del2@test.com")
    repo.upsert_business_profile(bid, {"short_description": "kedai kopi enak"})
    client = fresh_client()
    _login_owner(client, "del2@test.com")
    client.post(f"/business/{bid}/files/upload", data={
        "csrf_token": "x", "file": [(io.BytesIO(b"x"), "x.txt")],
    }, content_type="multipart/form-data")
    files = repo.list_business_files(bid)
    client.post(f"/business/{bid}/files/{files[0]['id']}/delete", data={"csrf_token": "x"})
    profile = repo.get_business_profile(bid)
    assert profile["short_description"] == "kedai kopi enak", \
        "deleting a file must never touch business profile data"
    print("test_delete_file_does_not_affect_other_business_data OK")


def test_delete_wrong_business_file_404s_tenant_isolation():
    reset_db()
    uid1, bid1 = _make_owner_and_business("Biz Del3", "del3@test.com")
    uid2, bid2 = _make_owner_and_business("Biz Del4", "del4@test.com")
    client1 = fresh_client()
    _login_owner(client1, "del3@test.com")
    client1.post(f"/business/{bid1}/files/upload", data={
        "csrf_token": "x", "file": [(io.BytesIO(b"secret"), "secret.txt")],
    }, content_type="multipart/form-data")
    files = repo.list_business_files(bid1)

    client2 = fresh_client()
    _login_owner(client2, "del4@test.com")
    resp = client2.post(f"/business/{bid2}/files/{files[0]['id']}/delete", data={"csrf_token": "x"})
    assert resp.status_code == 404, "a business must never be able to delete another business's file"
    still_there = repo.list_business_files(bid1)
    assert len(still_there) == 1
    print("test_delete_wrong_business_file_404s_tenant_isolation OK")


def test_delete_marks_knowledge_stale_if_already_done():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Del5", "del5@test.com")
    repo.set_ai_status(bid, "DONE")
    client = fresh_client()
    _login_owner(client, "del5@test.com")
    client.post(f"/business/{bid}/files/upload", data={
        "csrf_token": "x", "file": [(io.BytesIO(b"menu"), "menu.txt")],
    }, content_type="multipart/form-data")
    files = repo.list_business_files(bid)
    client.post(f"/business/{bid}/files/{files[0]['id']}/delete", data={"csrf_token": "x"})
    ai_settings = repo.get_ai_settings(bid)
    assert ai_settings["ai_status"] == "STALE", \
        "removing a file after knowledge already exists must mark it STALE via the existing mechanism"
    print("test_delete_marks_knowledge_stale_if_already_done OK")


def test_deleted_file_visible_neither_in_wizard_nor_admin():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz Del6", "del6@test.com")
    client = fresh_client()
    _login_owner(client, "del6@test.com")
    client.post(f"/business/{bid}/files/upload", data={
        "csrf_token": "x", "file": [(io.BytesIO(b"x"), "gone.txt")],
    }, content_type="multipart/form-data")
    files = repo.list_business_files(bid)
    client.post(f"/business/{bid}/files/{files[0]['id']}/delete", data={"csrf_token": "x"})
    client.get(f"/business/{bid}/wizard/upload")  # consume the delete's own flash message first
    wizard_body = client.get(f"/business/{bid}/wizard/upload").data.decode()
    assert "gone.txt" not in wizard_body

    admin_client = fresh_client()
    _login_admin(admin_client, admin)
    admin_body = admin_client.get(f"/admin/business/{bid}").data.decode()
    # The audit log legitimately/correctly still mentions "gone.txt" as historical record of the
    # upload event (audit history must never be deleted) — check the FILES section specifically,
    # not the whole page, since that section is the one that must no longer list it as a current
    # file.
    files_section_start = admin_body.find("<h2>Files</h2>")
    files_section_end = admin_body.find("</div>", files_section_start)
    files_section = admin_body[files_section_start:files_section_end]
    assert "gone.txt" not in files_section
    print("test_deleted_file_visible_neither_in_wizard_nor_admin OK")


def test_delete_confirmation_present_in_ui():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Del7", "del7@test.com")
    client = fresh_client()
    _login_owner(client, "del7@test.com")
    client.post(f"/business/{bid}/files/upload", data={
        "csrf_token": "x", "file": [(io.BytesIO(b"x"), "confirm.txt")],
    }, content_type="multipart/form-data")
    body = client.get(f"/business/{bid}/wizard/upload").data.decode()
    assert "confirm(" in body, "delete action must have a confirmation prompt"
    print("test_delete_confirmation_present_in_ui OK")


# ---------------------------------------------------------------------------
# B. ACTIVATION CHECKLIST — Template health + next_action
# ---------------------------------------------------------------------------
def test_checklist_includes_template_item():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Health1", "health1@test.com", package="AI_ADMIN_PRO")
    checklist = payment_service.build_activation_checklist(bid)
    keys = [c["key"] for c in checklist]
    assert "template" in keys
    print("test_checklist_includes_template_item OK")


def test_checklist_next_action_present_for_incomplete_items():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Health2", "health2@test.com", package="AI_ADMIN_PRO")
    checklist = payment_service.build_activation_checklist(bid)
    for item in checklist:
        if not item["done"]:
            assert item["next_action"], f"{item['key']} must have a human next_action when not done"
        else:
            assert item["next_action"] is None
    print("test_checklist_next_action_present_for_incomplete_items OK")


def test_checklist_template_done_when_global_env_configured():
    reset_db()
    os.environ["WHATSAPP_REENGAGEMENT_TEMPLATE_NAME"] = "test_template"
    uid, bid = _make_owner_and_business("Biz Health3", "health3@test.com", package="AI_ADMIN_PRO")
    checklist = payment_service.build_activation_checklist(bid)
    template_item = next(c for c in checklist if c["key"] == "template")
    assert template_item["done"] is True
    os.environ.pop("WHATSAPP_REENGAGEMENT_TEMPLATE_NAME", None)
    print("test_checklist_template_done_when_global_env_configured OK")


# ---------------------------------------------------------------------------
# C. 429 HANDLING — NO automatic retry (safety correction: the unidentified infra component's
# behavior is unknown, and no persistent idempotency/dedup mechanism exists for outgoing template
# sends, so retrying could duplicate a real WhatsApp message — a manual retry by the admin is the
# safe path instead).
# ---------------------------------------------------------------------------
def test_429_never_automatically_retried():
    reset_db()
    call_count = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        call_count["n"] += 1
        resp = MagicMock()
        resp.status_code = 429
        resp.headers = {}
        return resp

    with patch.object(platform_inbox_service.requests, "post", side_effect=fake_post):
        ok, reason = platform_inbox_service._post_to_bot_bridge(
            "https://example.com/internal/platform-cs-template-reply", {"a": 1}, "secret",
        )
    assert call_count["n"] == 1, "a 429 must NOT be automatically retried — exactly one attempt only"
    assert ok is False
    assert reason == "bot_internal_bridge_http_429"
    print("test_429_never_automatically_retried OK")


def test_non_429_status_also_never_retried():
    reset_db()
    call_count = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        call_count["n"] += 1
        resp = MagicMock()
        resp.status_code = 502
        return resp

    with patch.object(platform_inbox_service.requests, "post", side_effect=fake_post):
        ok, reason = platform_inbox_service._post_to_bot_bridge(
            "https://example.com/internal/platform-cs-template-reply", {"a": 1}, "secret",
        )
    assert call_count["n"] == 1, "a non-429 status must never trigger a retry either"
    assert reason == "bot_internal_bridge_http_502"
    print("test_non_429_status_also_never_retried OK")


def test_successful_send_still_works_single_attempt():
    reset_db()
    call_count = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        call_count["n"] += 1
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"status": "ok"}
        return resp

    with patch.object(platform_inbox_service.requests, "post", side_effect=fake_post):
        ok, reason = platform_inbox_service._post_to_bot_bridge(
            "https://example.com/internal/platform-cs-template-reply", {"a": 1}, "secret",
        )
    assert call_count["n"] == 1
    assert ok is True
    assert reason == "sent"
    print("test_successful_send_still_works_single_attempt OK")


def test_ui_error_wording_human_readable_for_429():
    reset_db()
    admin = _make_admin()
    uid, bid = _make_owner_and_business("Biz 429UI", "ui429@test.com", package="AI_ADMIN_PRO")
    phone = "628990002222"
    db.execute(
        "CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT, "
        "mode TEXT, role TEXT, content TEXT, created_at TEXT DEFAULT (datetime('now')))"
    )
    db.execute("INSERT INTO messages (number, mode, role, content) VALUES (?, 'customer', 'user', 'halo')", (phone,))
    platform_inbox_service.start_human_takeover(phone, admin["id"])

    with patch.object(platform_inbox_service, "_post_to_bot_bridge",
                       return_value=(False, "bot_internal_bridge_http_429")), \
         patch.object(platform_inbox_service, "_bot_platform_reply_url", return_value="https://example.com/internal/platform-cs-reply"):
        os.environ["INTERNAL_SERVICE_SECRET"] = "test-secret"
        os.environ["WHATSAPP_REENGAGEMENT_TEMPLATE_NAME"] = "test_template"
        client = fresh_client()
        _login_admin(client, admin)
        resp = client.post("/admin/inbox/send-template", data={
            "csrf_token": "x", "customer_phone": phone,
        }, follow_redirects=True)
    body = resp.data.decode()
    assert "Traceback" not in body
    assert "sempat sibuk" in body or "coba lagi" in body.lower()
    os.environ.pop("WHATSAPP_REENGAGEMENT_TEMPLATE_NAME", None)
    print("test_ui_error_wording_human_readable_for_429 OK")


# ---------------------------------------------------------------------------
# D. WAJIB/OPSIONAL LABELS
# ---------------------------------------------------------------------------
def test_wajib_opsional_labels_present_in_wizard():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Labels", "labels@test.com")
    client = fresh_client()
    _login_owner(client, "labels@test.com")
    basics_body = client.get(f"/business/{bid}/wizard/basics").data.decode()
    assert "(Wajib)" in basics_body
    assert "(Opsional)" in basics_body
    style_body = client.get(f"/business/{bid}/wizard/style").data.decode()
    assert "(Wajib)" in style_body
    print("test_wajib_opsional_labels_present_in_wizard OK")


if __name__ == "__main__":
    test_delete_file_removes_only_that_file()
    test_delete_file_does_not_affect_other_business_data()
    test_delete_wrong_business_file_404s_tenant_isolation()
    test_delete_marks_knowledge_stale_if_already_done()
    test_deleted_file_visible_neither_in_wizard_nor_admin()
    test_delete_confirmation_present_in_ui()
    test_checklist_includes_template_item()
    test_checklist_next_action_present_for_incomplete_items()
    test_checklist_template_done_when_global_env_configured()
    test_429_never_automatically_retried()
    test_non_429_status_also_never_retried()
    test_successful_send_still_works_single_attempt()
    test_ui_error_wording_human_readable_for_429()
    test_wajib_opsional_labels_present_in_wizard()
    print("ALL BATCH 2+3 TESTS PASSED")
