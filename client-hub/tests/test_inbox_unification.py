"""Inbox / Take Human / Tenant Dashboard unification — regression suite (Tests A-M from the spec,
plus template-config-missing and tenant-credential-isolation tests).

Run with:
    cd client-hub && python3 tests/test_inbox_unification.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WHATSAPP_REENGAGEMENT_TEMPLATE_NAME", None)

import db  # noqa: E402
import repo  # noqa: E402
import security  # noqa: E402
import catalog_service  # noqa: E402
import provisioning  # noqa: E402
import subscription_service  # noqa: E402
import inbox_service  # noqa: E402
import platform_inbox_service  # noqa: E402
import wa_takeover_service  # noqa: E402
import wa_inbox_shared  # noqa: E402
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
    os.environ.pop("WHATSAPP_REENGAGEMENT_TEMPLATE_NAME", None)
    # `messages`/`customer_profiles` are owned by the BOT's own schema (../app.py), not by any
    # Client Hub migration — in production, Client Hub and the bot share ONE database, so Client
    # Hub's inbox_service.py/platform_inbox_service.py can query these tables even though Client
    # Hub itself never creates them. This test file only imports Client Hub's own app.py (not the
    # bot's), so it must create the same minimal shape itself — exact column set matches ../app.py's
    # own CREATE TABLE for these two tables.
    db.execute(
        "CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT "
        "NOT NULL, mode TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, "
        "created_at TEXT DEFAULT (datetime('now')))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS customer_profiles (number TEXT PRIMARY KEY, name TEXT, "
        "updated_at TEXT DEFAULT (datetime('now')))"
    )


def _make_admin():
    admin_id = repo.create_user(f"admin_{os.urandom(4).hex()}@kilasworks.id",
                                 security.hash_password("adminpass123"), role="KILAS_ADMIN")
    return db.query_one("SELECT * FROM users WHERE id = ?", (admin_id,))


def _login_admin(client, admin):
    client.post("/login", data={"email": admin["email"], "password": "adminpass123"})


def _login_owner(client, email, password="password123"):
    client.post("/login", data={"email": email, "password": password})


def _make_active_ai_admin_tenant(name, owner_email, package="AI_ADMIN_PRO"):
    """A fully ACTIVE, AI-Admin-package business with a CONNECTED WhatsApp config — the
    minimum setup needed for /business/<id>/inbox to be reachable and functional."""
    admin = _make_admin()
    user_id = repo.create_user(owner_email, security.hash_password("password123"))
    business_id = repo.create_business(user_id, name, package=package)
    repo.upsert_business_profile(business_id, {
        "operating_hours": "08-20", "closed_days": "Minggu", "owner_name": "Test Owner",
        "category": "Test", "primary_language": "id", "customer_salutation": "Kak",
    })
    repo.replace_business_services(business_id, ["Layanan utama"])
    repo.set_ai_status(business_id, "DONE")
    db.execute("UPDATE businesses SET status = 'ACTIVE' WHERE id = ?", (business_id,))
    credentials_ref = f"TEST_WA_TOKEN__{business_id}"
    repo.upsert_whatsapp_config(business_id, f"pnid-{business_id}", None, credentials_ref,
                                 connection_status="CONNECTED")
    os.environ[credentials_ref] = f"secret-token-{business_id}"
    subscription_service.create_subscription(
        business_id, "ai_admin_basic" if package == "AI_ADMIN_BASIC" else "ai_admin_pro",
        actor_user_id=admin["id"],
    )
    return user_id, business_id


def _seed_message(business_id, customer_phone, role, content, hours_ago=0):
    scoped = f"T{business_id}:{customer_phone}"
    created_at = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    db.execute(
        "INSERT INTO messages (number, mode, role, content, created_at) VALUES (?, 'customer', ?, ?, ?)",
        (scoped, role, content, created_at),
    )


# ---------------------------------------------------------------------------
# TEST A — tenant login sees only own business/customers.
# ---------------------------------------------------------------------------
def test_A_tenant_login_sees_only_own_business():
    reset_db()
    uid_a, bid_a = _make_active_ai_admin_tenant("Biz A", "ownera@test.com")
    uid_b, bid_b = _make_active_ai_admin_tenant("Biz B", "ownerb@test.com")
    client = fresh_client()
    _login_owner(client, "ownera@test.com")
    resp = client.get("/dashboard")
    body = resp.data.decode()
    assert "Biz A" in body
    assert "Biz B" not in body
    print("test_A_tenant_login_sees_only_own_business OK")


# ---------------------------------------------------------------------------
# TEST B — tenant A cannot open tenant B's inbox.
# ---------------------------------------------------------------------------
def test_B_tenant_A_cannot_open_tenant_B_inbox():
    reset_db()
    uid_a, bid_a = _make_active_ai_admin_tenant("Biz A", "ownera2@test.com")
    uid_b, bid_b = _make_active_ai_admin_tenant("Biz B", "ownerb2@test.com")
    client = fresh_client()
    _login_owner(client, "ownera2@test.com")
    resp = client.get(f"/business/{bid_b}/inbox")
    assert resp.status_code == 404, "tenant A must never reach tenant B's inbox (404, not 403)"
    print("test_B_tenant_A_cannot_open_tenant_B_inbox OK")


# ---------------------------------------------------------------------------
# TEST C/D — free-form allowed at 10h, blocked (template offered) at 25h.
# ---------------------------------------------------------------------------
def test_C_freeform_allowed_at_10h():
    reset_db()
    uid, bid = _make_active_ai_admin_tenant("Biz C", "ownerc@test.com")
    phone = "628990000001"
    _seed_message(bid, phone, "user", "halo", hours_ago=10)
    wa_takeover_service.start_human_takeover(bid, phone, uid)
    window = inbox_service.freeform_window_status(bid, phone)
    assert window["allowed"] is True
    print("test_C_freeform_allowed_at_10h OK")


def test_D_freeform_blocked_at_25h_template_offered():
    reset_db()
    uid, bid = _make_active_ai_admin_tenant("Biz D", "ownerd@test.com")
    phone = "628990000002"
    _seed_message(bid, phone, "user", "halo", hours_ago=25)
    wa_takeover_service.start_human_takeover(bid, phone, uid)
    window = inbox_service.freeform_window_status(bid, phone)
    assert window["allowed"] is False
    assert window["reason"] == "outside_24h_window"

    client = fresh_client()
    _login_owner(client, "ownerd@test.com")
    resp = client.get(f"/business/{bid}/inbox?customer={phone}")
    body = resp.data.decode()
    assert "Perlu kirim template" in body
    assert "Kirim Template" in body
    print("test_D_freeform_blocked_at_25h_template_offered OK")


# ---------------------------------------------------------------------------
# TEST E — Human Takeover stays active after the 24h window expires.
# ---------------------------------------------------------------------------
def test_E_human_takeover_survives_24h_expiry():
    reset_db()
    uid, bid = _make_active_ai_admin_tenant("Biz E", "ownere@test.com")
    phone = "628990000003"
    _seed_message(bid, phone, "user", "halo", hours_ago=30)
    wa_takeover_service.start_human_takeover(bid, phone, uid)
    assert wa_takeover_service.get_state(bid, phone) == "HUMAN_TAKEOVER"
    window = inbox_service.freeform_window_status(bid, phone)
    assert window["allowed"] is False
    # The mode itself is completely unaffected by window expiry.
    assert wa_takeover_service.get_state(bid, phone) == "HUMAN_TAKEOVER", \
        "BUG: Human Takeover must never auto-expire just because the 24h window did"
    print("test_E_human_takeover_survives_24h_expiry OK")


# ---------------------------------------------------------------------------
# TEST F — approved template sent -> customer replies -> free-form active again.
# ---------------------------------------------------------------------------
def test_F_template_send_then_customer_reply_reopens_freeform():
    reset_db()
    os.environ["WHATSAPP_REENGAGEMENT_TEMPLATE_NAME"] = "test_reengagement"
    uid, bid = _make_active_ai_admin_tenant("Biz F", "ownerf@test.com")
    phone = "628990000004"
    _seed_message(bid, phone, "user", "halo", hours_ago=30)
    wa_takeover_service.start_human_takeover(bid, phone, uid)
    assert inbox_service.freeform_window_status(bid, phone)["allowed"] is False

    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        ok, reason = inbox_service.send_template_reply(bid, phone)
    assert ok, reason

    # Customer replies -> a fresh inbound message updates last_customer_msg_at -> window reopens.
    _seed_message(bid, phone, "user", "oke, masih ada?", hours_ago=0)
    window_after = inbox_service.freeform_window_status(bid, phone)
    assert window_after["allowed"] is True
    print("test_F_template_send_then_customer_reply_reopens_freeform OK")


# ---------------------------------------------------------------------------
# TEST G — Resume AI restores AI_ACTIVE mode correctly.
# ---------------------------------------------------------------------------
def test_G_resume_ai_restores_correct_mode():
    reset_db()
    uid, bid = _make_active_ai_admin_tenant("Biz G", "ownerg@test.com")
    phone = "628990000005"
    _seed_message(bid, phone, "user", "halo", hours_ago=1)
    wa_takeover_service.start_human_takeover(bid, phone, uid)
    assert wa_takeover_service.get_state(bid, phone) == "HUMAN_TAKEOVER"
    wa_takeover_service.return_to_ai(bid, phone, uid)
    assert wa_takeover_service.get_state(bid, phone) == "AI_ACTIVE"
    print("test_G_resume_ai_restores_correct_mode OK")


# ---------------------------------------------------------------------------
# TEST H — same customer phone in tenant A and B never shares state.
# ---------------------------------------------------------------------------
def test_H_same_customer_phone_two_tenants_isolated():
    reset_db()
    uid_a, bid_a = _make_active_ai_admin_tenant("Biz H1", "ownerh1@test.com")
    uid_b, bid_b = _make_active_ai_admin_tenant("Biz H2", "ownerh2@test.com")
    shared_phone = "628990000099"

    _seed_message(bid_a, shared_phone, "user", "halo dari tenant A", hours_ago=1)
    wa_takeover_service.start_human_takeover(bid_a, shared_phone, uid_a)

    # Tenant B never saw this customer at all yet.
    assert wa_takeover_service.get_state(bid_b, shared_phone) == "AI_ACTIVE"
    assert not inbox_service.customer_exists(bid_b, shared_phone)
    # Tenant A's state is exactly as set.
    assert wa_takeover_service.get_state(bid_a, shared_phone) == "HUMAN_TAKEOVER"
    assert inbox_service.customer_exists(bid_a, shared_phone)

    # Thread contents never cross tenants either.
    thread_a = inbox_service.get_thread(bid_a, shared_phone)
    thread_b = inbox_service.get_thread(bid_b, shared_phone)
    assert any("tenant A" in m["content"] for m in thread_a)
    assert thread_b == []
    print("test_H_same_customer_phone_two_tenants_isolated OK")


# ---------------------------------------------------------------------------
# TEST I/J — follow-up >24h uses the template path; never targets the wrong tenant/customer.
# ---------------------------------------------------------------------------
def test_I_followup_over_24h_uses_template_path_not_freeform():
    reset_db()
    import tenant_followup_service
    uid, bid = _make_active_ai_admin_tenant("Biz I", "owneri@test.com")
    phone = "628990000006"
    now = datetime.now(timezone.utc)
    tenant_followup_service._upsert_state(
        bid, phone, last_customer_msg_at=(now - timedelta(hours=25)).isoformat(),
        followup_count=0, resolved=False,
    )
    freeform_due = tenant_followup_service.get_customers_due_for_followup(bid)
    template_due = tenant_followup_service.get_customers_due_for_template_followup(bid)
    assert phone not in freeform_due, "a customer past 24h must NOT appear in the free-form due list"
    assert phone in template_due, "a customer past 24h MUST appear in the template-due list"
    print("test_I_followup_over_24h_uses_template_path_not_freeform OK")


def test_J_followup_template_due_list_never_crosses_tenants():
    reset_db()
    import tenant_followup_service
    uid_a, bid_a = _make_active_ai_admin_tenant("Biz J1", "ownerj1@test.com")
    uid_b, bid_b = _make_active_ai_admin_tenant("Biz J2", "ownerj2@test.com")
    shared_phone = "628990000098"
    now = datetime.now(timezone.utc)
    tenant_followup_service._upsert_state(
        bid_a, shared_phone, last_customer_msg_at=(now - timedelta(hours=25)).isoformat(),
        followup_count=0, resolved=False,
    )
    due_a = tenant_followup_service.get_customers_due_for_template_followup(bid_a)
    due_b = tenant_followup_service.get_customers_due_for_template_followup(bid_b)
    assert shared_phone in due_a
    assert shared_phone not in due_b, "BUG: tenant B's due-list must never include tenant A's customer state"
    print("test_J_followup_template_due_list_never_crosses_tenants OK")


# ---------------------------------------------------------------------------
# TEST K — AI stays suppressed during Human Takeover (manual reply gate).
# ---------------------------------------------------------------------------
def test_K_ai_suppressed_during_human_takeover():
    reset_db()
    uid, bid = _make_active_ai_admin_tenant("Biz K", "ownerk@test.com")
    phone = "628990000007"
    _seed_message(bid, phone, "user", "halo", hours_ago=1)
    # AI_ACTIVE (no takeover) -> a manual reply attempt must be REJECTED (that's the AI's job).
    ok, reason = inbox_service.send_manual_reply(bid, phone, "test")
    assert not ok and reason == "human_takeover_required"
    # Now take over -> manual reply path opens up (send itself mocked, we only check the gate).
    wa_takeover_service.start_human_takeover(bid, phone, uid)
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        ok2, reason2 = inbox_service.send_manual_reply(bid, phone, "test reply")
    assert ok2, reason2
    print("test_K_ai_suppressed_during_human_takeover OK")


# ---------------------------------------------------------------------------
# TEST L — owner/global admin access still works per permission.
# ---------------------------------------------------------------------------
def test_L_kilas_admin_can_still_manage_platform_inbox():
    reset_db()
    admin = _make_admin()
    client = fresh_client()
    _login_admin(client, admin)
    resp = client.get("/admin/inbox")
    assert resp.status_code == 200
    print("test_L_kilas_admin_can_still_manage_platform_inbox OK")


def test_L_non_admin_cannot_reach_platform_inbox():
    reset_db()
    uid, bid = _make_active_ai_admin_tenant("Biz L", "ownerl@test.com")
    client = fresh_client()
    _login_owner(client, "ownerl@test.com")
    resp = client.get("/admin/inbox")
    assert resp.status_code in (302, 403), "a tenant owner must never reach the Kilas Works platform inbox"
    print("test_L_non_admin_cannot_reach_platform_inbox OK")


# ---------------------------------------------------------------------------
# TEST M — a non-AI-Admin (Foto/Video/Website-only) customer gets no AI Admin Inbox.
# ---------------------------------------------------------------------------
def test_M_non_ai_admin_business_has_no_inbox():
    reset_db()
    user_id = repo.create_user("fotoonly@test.com", security.hash_password("password123"))
    business_id = repo.create_business(user_id, "Foto Only Biz", package="NONE")
    client = fresh_client()
    _login_owner(client, "fotoonly@test.com")
    resp = client.get(f"/business/{business_id}/inbox", follow_redirects=False)
    assert resp.status_code == 302
    assert "dashboard" in resp.headers.get("Location", "").lower()
    print("test_M_non_ai_admin_business_has_no_inbox OK")


# ---------------------------------------------------------------------------
# Additional: template config missing -> fail closed; tenant template send uses ONLY that
# tenant's own credentials/config.
# ---------------------------------------------------------------------------
def test_template_config_missing_fails_closed():
    reset_db()
    os.environ.pop("WHATSAPP_REENGAGEMENT_TEMPLATE_NAME", None)
    uid, bid = _make_active_ai_admin_tenant("Biz Tmpl1", "ownertmpl1@test.com")
    phone = "628990000010"
    _seed_message(bid, phone, "user", "halo", hours_ago=30)
    wa_takeover_service.start_human_takeover(bid, phone, uid)

    name, lang = wa_inbox_shared.resolve_reengagement_template_config(os.environ.get)
    assert name is None and lang is None

    ok, reason = inbox_service.send_template_reply(bid, phone)
    assert not ok
    assert reason == "reengagement_template_not_configured"
    print("test_template_config_missing_fails_closed OK")


def test_platform_template_config_missing_fails_closed():
    reset_db()
    os.environ.pop("WHATSAPP_REENGAGEMENT_TEMPLATE_NAME", None)
    phone = "628990000011"
    db.execute(
        "INSERT INTO messages (number, mode, role, content) VALUES (?, 'customer', 'user', ?)",
        (phone, "halo"),
    )
    platform_inbox_service.start_human_takeover(phone, actor_user_id=None)
    ok, reason = platform_inbox_service.send_template_reply(phone)
    assert not ok
    assert reason == "reengagement_template_not_configured"
    print("test_platform_template_config_missing_fails_closed OK")


def test_tenant_template_send_uses_only_that_tenants_credentials():
    """A tenant's template send must use ITS OWN whatsapp_config phone_number_id/token — never a
    different tenant's, never Kilas Works' own global credentials."""
    reset_db()
    os.environ["WHATSAPP_REENGAGEMENT_TEMPLATE_NAME"] = "test_reengagement"
    uid_a, bid_a = _make_active_ai_admin_tenant("Biz CredA", "ownercreda@test.com")
    uid_b, bid_b = _make_active_ai_admin_tenant("Biz CredB", "ownercredb@test.com")
    phone = "628990000012"
    _seed_message(bid_a, phone, "user", "halo", hours_ago=30)
    wa_takeover_service.start_human_takeover(bid_a, phone, uid_a)

    captured_urls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        captured_urls.append((url, headers.get("Authorization")))
        resp = type("R", (), {})()
        resp.status_code = 200
        return resp

    with patch("requests.post", side_effect=fake_post):
        ok, reason = inbox_service.send_template_reply(bid_a, phone)
    assert ok, reason
    assert len(captured_urls) == 1
    url, auth_header = captured_urls[0]
    assert f"pnid-{bid_a}" in url, f"must use tenant A's own phone_number_id: {url}"
    assert f"pnid-{bid_b}" not in url
    assert f"secret-token-{bid_a}" in auth_header
    assert f"secret-token-{bid_b}" not in auth_header
    print("test_tenant_template_send_uses_only_that_tenants_credentials OK")


# ---------------------------------------------------------------------------
# Tenant-scoped WhatsApp re-engagement template override — Tests A-F.
# ---------------------------------------------------------------------------
def test_template_A_tenant_has_own_template_uses_it():
    reset_db()
    os.environ.pop("WHATSAPP_REENGAGEMENT_TEMPLATE_NAME", None)  # no global at all this time
    uid, bid = _make_active_ai_admin_tenant("Biz TplA", "ownertpla@test.com")
    repo.set_tenant_reengagement_template(bid, "template_a", "id")
    row = repo.get_whatsapp_config(bid)
    name, lang = wa_inbox_shared.resolve_reengagement_template_config_for_tenant(row, os.environ.get)
    assert name == "template_a"
    assert lang == "id"
    print("test_template_A_tenant_has_own_template_uses_it OK")


def test_template_B_different_tenant_has_own_different_template_uses_it():
    reset_db()
    os.environ.pop("WHATSAPP_REENGAGEMENT_TEMPLATE_NAME", None)
    uid_a, bid_a = _make_active_ai_admin_tenant("Biz TplA2", "ownertpla2@test.com")
    uid_b, bid_b = _make_active_ai_admin_tenant("Biz TplB", "ownertplb@test.com")
    repo.set_tenant_reengagement_template(bid_a, "template_a", "id")
    repo.set_tenant_reengagement_template(bid_b, "template_b", "en")

    name_a, lang_a = wa_inbox_shared.resolve_reengagement_template_config_for_tenant(
        repo.get_whatsapp_config(bid_a), os.environ.get)
    name_b, lang_b = wa_inbox_shared.resolve_reengagement_template_config_for_tenant(
        repo.get_whatsapp_config(bid_b), os.environ.get)
    assert name_a == "template_a" and lang_a == "id"
    assert name_b == "template_b" and lang_b == "en"
    print("test_template_B_different_tenant_has_own_different_template_uses_it OK")


def test_template_C_tenant_A_config_cannot_affect_tenant_B():
    reset_db()
    os.environ["WHATSAPP_REENGAGEMENT_TEMPLATE_NAME"] = "global_template"
    uid_a, bid_a = _make_active_ai_admin_tenant("Biz TplC1", "ownertplc1@test.com")
    uid_b, bid_b = _make_active_ai_admin_tenant("Biz TplC2", "ownertplc2@test.com")
    repo.set_tenant_reengagement_template(bid_a, "template_only_for_a", "id")
    # bid_b deliberately gets NO override.

    name_a, _ = wa_inbox_shared.resolve_reengagement_template_config_for_tenant(
        repo.get_whatsapp_config(bid_a), os.environ.get)
    name_b, _ = wa_inbox_shared.resolve_reengagement_template_config_for_tenant(
        repo.get_whatsapp_config(bid_b), os.environ.get)
    assert name_a == "template_only_for_a"
    assert name_b == "global_template", \
        "tenant B must fall back to global, never see tenant A's override"
    assert name_b != "template_only_for_a"

    # And end-to-end via send_template_reply(): tenant B's send must use the global template name,
    # never tenant A's, even though tenant A has an override configured in the same database.
    phone_b = "628990000020"
    _seed_message(bid_b, phone_b, "user", "halo", hours_ago=30)
    wa_takeover_service.start_human_takeover(bid_b, phone_b, uid_b)
    captured = []

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.append(json["template"]["name"])
        resp = type("R", (), {})()
        resp.status_code = 200
        return resp

    with patch("requests.post", side_effect=fake_post):
        ok, reason = inbox_service.send_template_reply(bid_b, phone_b)
    assert ok, reason
    assert captured == ["global_template"]
    print("test_template_C_tenant_A_config_cannot_affect_tenant_B OK")


def test_template_D_tenant_no_override_falls_back_to_global():
    reset_db()
    os.environ["WHATSAPP_REENGAGEMENT_TEMPLATE_NAME"] = "global_fallback_template"
    os.environ["WHATSAPP_REENGAGEMENT_TEMPLATE_LANGUAGE"] = "en"
    uid, bid = _make_active_ai_admin_tenant("Biz TplD", "ownertpld@test.com")
    # No repo.set_tenant_reengagement_template() call at all for this tenant.
    name, lang = wa_inbox_shared.resolve_reengagement_template_config_for_tenant(
        repo.get_whatsapp_config(bid), os.environ.get)
    assert name == "global_fallback_template"
    assert lang == "en"
    print("test_template_D_tenant_no_override_falls_back_to_global OK")


def test_template_E_no_tenant_and_no_global_config_fails_closed():
    reset_db()
    os.environ.pop("WHATSAPP_REENGAGEMENT_TEMPLATE_NAME", None)
    os.environ.pop("WHATSAPP_REENGAGEMENT_TEMPLATE_LANGUAGE", None)
    uid, bid = _make_active_ai_admin_tenant("Biz TplE", "ownertple@test.com")
    name, lang = wa_inbox_shared.resolve_reengagement_template_config_for_tenant(
        repo.get_whatsapp_config(bid), os.environ.get)
    assert name is None and lang is None

    phone = "628990000021"
    _seed_message(bid, phone, "user", "halo", hours_ago=30)
    wa_takeover_service.start_human_takeover(bid, phone, uid)
    ok, reason = inbox_service.send_template_reply(bid, phone)
    assert not ok
    assert reason == "reengagement_template_not_configured"
    print("test_template_E_no_tenant_and_no_global_config_fails_closed OK")


def test_template_F_kilas_platform_inbox_still_uses_global_only():
    """Kilas Works' own platform inbox has no per-business row to override from — it must keep
    using the global config exactly as before, unaffected by any tenant's override."""
    reset_db()
    os.environ["WHATSAPP_REENGAGEMENT_TEMPLATE_NAME"] = "kilas_global_template"
    uid, bid = _make_active_ai_admin_tenant("Biz TplF", "ownertplf@test.com")
    repo.set_tenant_reengagement_template(bid, "should_never_be_used_by_kilas_works", "id")

    name, lang = wa_inbox_shared.resolve_reengagement_template_config(os.environ.get)
    assert name == "kilas_global_template"
    assert name != "should_never_be_used_by_kilas_works"

    phone = "628990000022"
    db.execute(
        "INSERT INTO messages (number, mode, role, content) VALUES (?, 'customer', 'user', ?)",
        (phone, "halo"),
    )
    platform_inbox_service.start_human_takeover(phone, actor_user_id=None)
    captured = []

    def fake_bridge_post(url, json=None, headers=None, timeout=None):
        captured.append(json.get("template_name"))
        resp = type("R", (), {})()
        resp.status_code = 200
        resp.json = lambda: {"status": "ok"}
        return resp

    os.environ["INTERNAL_SERVICE_SECRET"] = "test-secret"
    os.environ["KILAS_BOT_INTERNAL_URL"] = "https://bot.example.com/internal/owner-notify"
    with patch("requests.post", side_effect=fake_bridge_post):
        ok, reason = platform_inbox_service.send_template_reply(phone)
    assert ok, reason
    assert captured == ["kilas_global_template"]
    print("test_template_F_kilas_platform_inbox_still_uses_global_only OK")


if __name__ == "__main__":
    test_A_tenant_login_sees_only_own_business()
    test_B_tenant_A_cannot_open_tenant_B_inbox()
    test_C_freeform_allowed_at_10h()
    test_D_freeform_blocked_at_25h_template_offered()
    test_E_human_takeover_survives_24h_expiry()
    test_F_template_send_then_customer_reply_reopens_freeform()
    test_G_resume_ai_restores_correct_mode()
    test_H_same_customer_phone_two_tenants_isolated()
    test_I_followup_over_24h_uses_template_path_not_freeform()
    test_J_followup_template_due_list_never_crosses_tenants()
    test_K_ai_suppressed_during_human_takeover()
    test_L_kilas_admin_can_still_manage_platform_inbox()
    test_L_non_admin_cannot_reach_platform_inbox()
    test_M_non_ai_admin_business_has_no_inbox()
    test_template_config_missing_fails_closed()
    test_platform_template_config_missing_fails_closed()
    test_tenant_template_send_uses_only_that_tenants_credentials()
    test_template_A_tenant_has_own_template_uses_it()
    test_template_B_different_tenant_has_own_different_template_uses_it()
    test_template_C_tenant_A_config_cannot_affect_tenant_B()
    test_template_D_tenant_no_override_falls_back_to_global()
    test_template_E_no_tenant_and_no_global_config_fails_closed()
    test_template_F_kilas_platform_inbox_still_uses_global_only()
    print("ALL INBOX UNIFICATION TESTS PASSED")
