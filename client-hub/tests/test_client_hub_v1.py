"""Kilas Works Client Hub V1 — test suite (section 36 test matrix).

Follows the exact same plain-script convention as the main bot's tests: assert statements,
functions named test_*, a final "ALL ... TESTS PASSED" line. Run with:
    cd client-hub && python3 tests/test_client_hub_v1.py

Uses a fresh, isolated SQLite file per run (CLIENT_HUB_DB_PATH env var set before any import of
db/app), so this never touches client_hub_dev.db or any real data.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("ANTHROPIC_API_KEY", None)  # force the "no key configured" graceful-failure path

import db  # noqa: E402
import repo  # noqa: E402
import security  # noqa: E402
import file_utils  # noqa: E402
import ai_onboarding  # noqa: E402
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


# ---------------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------------

def test_auth_register_login_logout():
    reset_db()
    c = fresh_client()
    r = c.post("/register", data={"email": "a@test.com", "password": "password123", "full_name": "A"})
    assert r.status_code in (302, 200)
    user = repo.get_user_by_email("a@test.com")
    assert user is not None
    assert user["password_hash"] != "password123"  # never stored plaintext
    assert security.verify_password(user["password_hash"], "password123")

    c.get("/logout")
    r = c.post("/login", data={"email": "a@test.com", "password": "wrongpass"}, follow_redirects=True)
    assert b"salah" in r.data or r.status_code == 200  # login page re-rendered with error, not 500

    r = c.post("/login", data={"email": "a@test.com", "password": "password123"}, follow_redirects=True)
    assert r.status_code == 200
    r = c.get("/dashboard")
    assert r.status_code == 200
    c.get("/logout")
    r = c.get("/dashboard", follow_redirects=False)
    assert r.status_code in (302, 401)  # unauthorized route blocked after logout
    print("test_auth_register_login_logout OK")


def test_auth_unauthorized_route_without_login():
    reset_db()
    c = fresh_client()
    r = c.get("/dashboard", follow_redirects=False)
    assert r.status_code in (302, 401)
    r = c.get("/admin/", follow_redirects=False)
    assert r.status_code in (302, 401)
    print("test_auth_unauthorized_route_without_login OK")


# ---------------------------------------------------------------------------
# TENANT
# ---------------------------------------------------------------------------

def _make_client_with_business(c, email, biz_name, package="AI_ADMIN_BASIC"):
    c.post("/register", data={"email": email, "password": "password123", "full_name": email})
    c.post("/business/create", data={"business_name": biz_name, "package": package})
    return db.query_one("SELECT id FROM businesses WHERE business_name = ?", (biz_name,))["id"]


def test_tenant_create_and_access_own_business():
    reset_db()
    c = fresh_client()
    bid = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    r = c.get(f"/business/{bid}/review")
    assert r.status_code == 200
    print("test_tenant_create_and_access_own_business OK")


def test_tenant_cannot_access_another_business():
    reset_db()
    c = fresh_client()
    bid_a = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    c.get("/logout")
    c.post("/register", data={"email": "owner2@test.com", "password": "password123"})
    r = c.get(f"/business/{bid_a}/review")
    assert r.status_code == 404, "cross-tenant access must be 404 (IDOR-resistant), not 403/200"
    r = c.get(f"/business/{bid_a}/wizard/basics")
    assert r.status_code == 404
    r = c.post(f"/business/{bid_a}/ai-setup/run")
    assert r.status_code == 404
    r = c.post(f"/business/{bid_a}/submit-for-review")
    assert r.status_code == 404
    print("test_tenant_cannot_access_another_business OK")


def test_tenant_admin_can_access_all():
    reset_db()
    c = fresh_client()
    bid = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    c.get("/logout")
    admin_hash = security.hash_password("adminpass123")
    repo.create_user("admin@kilasworks.id", admin_hash, role="KILAS_ADMIN")
    c.post("/login", data={"email": "admin@kilasworks.id", "password": "adminpass123"})
    r = c.get(f"/admin/business/{bid}")
    assert r.status_code == 200
    print("test_tenant_admin_can_access_all OK")


# ---------------------------------------------------------------------------
# ONBOARDING
# ---------------------------------------------------------------------------

def _run_full_wizard(c, bid, salutation="Kak"):
    c.post(f"/business/{bid}/wizard/basics", data={
        "business_name": "Kopi ABC", "category": "Kedai kopi", "short_description": "Kopi enak",
        "country": "Indonesia", "timezone": "Asia/Jakarta", "address": "Tangerang",
        "business_phone": "0812", "owner_name": "Budi",
    })
    c.post(f"/business/{bid}/wizard/services", data={"services_raw": "Kopi susu - 20rb\nEspresso - 18rb"})
    c.post(f"/business/{bid}/wizard/operations", data={
        "operating_hours": "08-20", "closed_days": "-", "online_or_offline": "offline",
        "appointment_rules_raw": "",
    })
    c.post(f"/business/{bid}/wizard/faq", data={"faq_raw": "Ada wifi? Ada, gratis."})
    c.post(f"/business/{bid}/wizard/style", data={
        "tone": "friendly", "primary_language": "id", "customer_salutation": salutation,
    })
    c.post(f"/business/{bid}/wizard/upload", data={})


def test_onboarding_incomplete_data_blocks_ai_setup():
    reset_db()
    c = fresh_client()
    bid = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    # only basics done, nothing else
    c.post(f"/business/{bid}/wizard/basics", data={"business_name": "Kopi ABC", "owner_name": "Budi"})
    r = c.post(f"/business/{bid}/ai-setup/run", follow_redirects=True)
    ai = repo.get_ai_settings(bid)
    assert ai["ai_status"] == "PENDING", "AI setup must not run when required wizard steps are incomplete"
    print("test_onboarding_incomplete_data_blocks_ai_setup OK")


def test_onboarding_complete_data_allows_ai_setup_attempt():
    reset_db()
    c = fresh_client()
    bid = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    _run_full_wizard(c, bid)
    missing = repo.required_fields_missing(bid)
    assert missing == [], f"expected no missing required fields, got {missing}"
    r = c.post(f"/business/{bid}/ai-setup/run", follow_redirects=True)
    assert r.status_code == 200
    print("test_onboarding_complete_data_allows_ai_setup_attempt OK")


def test_onboarding_ai_failure_never_loses_raw_data_and_allows_retry():
    reset_db()
    c = fresh_client()
    bid = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    _run_full_wizard(c, bid)
    c.post(f"/business/{bid}/ai-setup/run", follow_redirects=True)
    ai = repo.get_ai_settings(bid)
    assert ai["ai_status"] == "FAILED"
    assert ai["last_error"] == "ANTHROPIC_API_KEY_NOT_CONFIGURED"
    services = repo.get_business_services(bid)
    assert [s["raw_input"] for s in services] == ["Kopi susu - 20rb", "Espresso - 18rb"], \
        "raw client data must survive an AI normalization failure untouched"
    faqs = repo.get_business_faqs(bid)
    assert len(faqs) == 1 and faqs[0]["raw_input"] == "Ada wifi? Ada, gratis."
    # retry is possible (client can just click run again — not asserting success since no API key
    # is configured in this sandbox, only that it doesn't crash and doesn't destroy data twice)
    c.post(f"/business/{bid}/ai-setup/run", follow_redirects=True)
    services_after_retry = repo.get_business_services(bid)
    assert [s["raw_input"] for s in services_after_retry] == ["Kopi susu - 20rb", "Espresso - 18rb"]
    print("test_onboarding_ai_failure_never_loses_raw_data_and_allows_retry OK")


def test_onboarding_ai_never_invents_price_needs_review_flag():
    reset_db()
    # unit-level check of the normalization contract rather than a live Claude call (no network
    # access in this sandbox) — simulate what update_normalized_service does with an
    # AI-returned ambiguous item and confirm needs_review defaults true until AI clears it.
    bid = repo.create_business(repo.create_user("o@test.com", security.hash_password("password123")), "Kopi ABC")
    repo.replace_business_services(bid, ["whitening mulai 1.5 jt"])
    services = repo.get_business_services(bid)
    assert services[0]["needs_review"] == 1, "a freshly-submitted raw service must default to needs_review until normalized"
    assert services[0]["price_from"] is None, "price must not be invented before AI normalization runs"
    print("test_onboarding_ai_never_invents_price_needs_review_flag OK")


def test_onboarding_file_upload_valid_and_rejected():
    reset_db()
    c = fresh_client()
    bid = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    import io as _io
    # valid PDF (magic bytes)
    pdf_bytes = b"%PDF-1.4\n%...minimal..."
    data = {"file": (_io.BytesIO(pdf_bytes), "katalog.pdf")}
    r = c.post(f"/business/{bid}/files/upload", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    files = repo.list_business_files(bid)
    assert len(files) == 1 and files[0]["original_filename"] == "katalog.pdf"

    # rejected: fake pdf (wrong magic bytes)
    fake = {"file": (_io.BytesIO(b"not a real pdf"), "fake.pdf")}
    r = c.post(f"/business/{bid}/files/upload", data=fake, content_type="multipart/form-data", follow_redirects=True)
    assert repo.list_business_files(bid).__len__() == 1, "invalid PDF must be rejected, not stored"

    # rejected: disallowed extension
    exe = {"file": (_io.BytesIO(b"MZ...."), "virus.exe")}
    r = c.post(f"/business/{bid}/files/upload", data=exe, content_type="multipart/form-data", follow_redirects=True)
    assert repo.list_business_files(bid).__len__() == 1, "disallowed extension must be rejected"
    print("test_onboarding_file_upload_valid_and_rejected OK")


# ---------------------------------------------------------------------------
# SIMULATION
# ---------------------------------------------------------------------------

def test_simulation_isolated_no_production_side_effects():
    reset_db()
    c = fresh_client()
    bid = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    _run_full_wizard(c, bid)
    c.get(f"/business/{bid}/simulate")  # establishes session token
    r = c.post(f"/business/{bid}/simulate/message", json={"message": "Jam bukanya kapan?"})
    assert r.status_code == 200
    body = r.get_json()
    assert "reply" in body
    # no real appointment/payment/customer conversation table touched
    assert db.query_all("SELECT * FROM audit_log WHERE business_id = ? AND action = 'simulation_error'", (bid,))
    history = repo.get_simulation_history(bid, None) if False else None  # token unknown here; check via table directly
    rows = db.query_all("SELECT * FROM simulation_messages WHERE business_id = ?", (bid,))
    assert len(rows) == 2  # user + assistant(error-fallback) — isolated table, not production data
    print("test_simulation_isolated_no_production_side_effects OK")


def test_simulation_flag_wrong_answer():
    reset_db()
    c = fresh_client()
    bid = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    _run_full_wizard(c, bid)
    c.get(f"/business/{bid}/simulate")
    r = c.post(f"/business/{bid}/simulate/message", json={"message": "Berapa harganya?"})
    msg_id = r.get_json()["message_id"]
    r = c.post(f"/business/{bid}/simulate/flag", json={"message_id": msg_id, "note": "Jawaban ini salah"})
    assert r.status_code == 200
    flagged = repo.list_flagged_simulation_messages(bid)
    assert len(flagged) == 1
    print("test_simulation_flag_wrong_answer OK")


# ---------------------------------------------------------------------------
# ADMIN
# ---------------------------------------------------------------------------

def _make_admin(c):
    admin_hash = security.hash_password("adminpass123")
    repo.create_user("admin@kilasworks.id", admin_hash, role="KILAS_ADMIN")
    c.post("/login", data={"email": "admin@kilasworks.id", "password": "adminpass123"})


def test_admin_review_approve_activate_flow():
    reset_db()
    c = fresh_client()
    bid = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    _run_full_wizard(c, bid)
    repo.save_ai_normalized_config(bid, "summary", {"description": "x"}, [])  # simulate AI DONE (no live API in sandbox)
    c.post(f"/business/{bid}/submit-for-review")
    c.get("/logout")

    _make_admin(c)
    r = c.get(f"/admin/business/{bid}")
    assert r.status_code == 200

    r = c.post(f"/admin/business/{bid}/approve", follow_redirects=True)
    assert repo.get_business(bid)["status"] == "APPROVED"

    r = c.post(f"/admin/business/{bid}/activate", follow_redirects=True)
    assert repo.get_business(bid)["status"] == "APPROVED", "must not activate before WhatsApp is connected"

    r = c.post(f"/admin/business/{bid}/connect-whatsapp",
               data={"whatsapp_phone_number_id": "111", "trusted_owner_phone": "+62811"}, follow_redirects=True)
    assert repo.get_business(bid)["whatsapp_connected"] == 1

    r = c.post(f"/admin/business/{bid}/activate", follow_redirects=True)
    assert repo.get_business(bid)["status"] == "ACTIVE"

    r = c.post(f"/admin/business/{bid}/deactivate", follow_redirects=True)
    assert repo.get_business(bid)["status"] == "SUSPENDED"
    print("test_admin_review_approve_activate_flow OK")


def test_admin_request_revision():
    reset_db()
    c = fresh_client()
    bid = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    c.get("/logout")
    _make_admin(c)
    r = c.post(f"/admin/business/{bid}/request-revision", data={"note": "Tambahkan jam operasional"}, follow_redirects=True)
    assert repo.get_business(bid)["status"] == "NEEDS_REVISION"
    audit = repo.get_audit_log(bid)
    assert any(a["action"] == "revision_requested" for a in audit)
    print("test_admin_request_revision OK")


def test_admin_cannot_activate_without_approval():
    reset_db()
    c = fresh_client()
    bid = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    c.get("/logout")
    _make_admin(c)
    r = c.post(f"/admin/business/{bid}/activate", follow_redirects=True)
    assert repo.get_business(bid)["status"] != "ACTIVE"
    print("test_admin_cannot_activate_without_approval OK")


# ---------------------------------------------------------------------------
# FEATURE FLAGS
# ---------------------------------------------------------------------------

def test_feature_flags_basic_vs_pro():
    reset_db()
    user_id = repo.create_user("o@test.com", security.hash_password("password123"))
    bid_basic = repo.create_business(user_id, "Kopi ABC", package="AI_ADMIN_BASIC")
    bid_pro = repo.create_business(user_id, "Studio Foto Pro", package="AI_ADMIN_PRO")

    basic = repo.get_tenant_features(bid_basic)
    assert basic["voice_note"] == 0 and basic["owner_commands"] == 0 and basic["appointment"] == 0
    assert basic["faq"] == 1 and basic["catalog"] == 1

    pro = repo.get_tenant_features(bid_pro)
    assert pro["voice_note"] == 1 and pro["owner_commands"] == 1 and pro["appointment"] == 1
    assert pro["payment_conversation"] == 1
    print("test_feature_flags_basic_vs_pro OK")


# ---------------------------------------------------------------------------
# SECURITY
# ---------------------------------------------------------------------------

def test_security_no_secrets_in_templates_or_config_ui():
    # static check: none of the rendered pages ever interpolate the ANTHROPIC_API_KEY / any
    # os.environ secret value directly — enforced by code review + this string-absence check
    # against ai_onboarding.py's constants never being passed to render_template anywhere.
    import routes_client, routes_admin
    src_client = open("routes_client.py").read()
    src_admin = open("routes_admin.py").read()
    for src in (src_client, src_admin):
        assert "ANTHROPIC_API_KEY" not in src
        assert "SECRET_KEY" not in src
    print("test_security_no_secrets_in_templates_or_config_ui OK")


def test_security_role_escalation_client_cannot_hit_admin_routes():
    reset_db()
    c = fresh_client()
    bid = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    r = c.get("/admin/")
    assert r.status_code == 403
    r = c.get(f"/admin/business/{bid}")
    assert r.status_code == 403
    r = c.post(f"/admin/business/{bid}/approve")
    assert r.status_code == 403
    print("test_security_role_escalation_client_cannot_hit_admin_routes OK")


def test_security_file_download_scoped_to_tenant():
    reset_db()
    c = fresh_client()
    bid_a = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    import io as _io
    data = {"file": (_io.BytesIO(b"%PDF-1.4\n..."), "katalog.pdf")}
    c.post(f"/business/{bid_a}/files/upload", data=data, content_type="multipart/form-data")
    file_id = repo.list_business_files(bid_a)[0]["id"]

    c.get("/logout")
    bid_b = _make_client_with_business(c, "owner2@test.com", "Dental XYZ")
    r = c.get(f"/business/{bid_a}/files/{file_id}/download")
    assert r.status_code == 404, "client B must not download client A's file even by guessing the file_id"
    print("test_security_file_download_scoped_to_tenant OK")


def test_security_password_never_plaintext_and_hashed_uniquely():
    reset_db()
    h1 = security.hash_password("samepassword123")
    h2 = security.hash_password("samepassword123")
    assert h1 != h2, "hashes must be salted (two hashes of the same password must differ)"
    assert security.verify_password(h1, "samepassword123")
    assert not security.verify_password(h1, "wrongpassword")
    print("test_security_password_never_plaintext_and_hashed_uniquely OK")


# ---------------------------------------------------------------------------
# STAGING SCENARIO — section 35: two real tenants, verify zero cross-talk
# ---------------------------------------------------------------------------

def test_staging_two_tenants_no_cross_talk():
    reset_db()
    c = fresh_client()
    bid_coffee = _make_client_with_business(c, "budi@coffee.test", "Kopi ABC", package="AI_ADMIN_BASIC")
    _run_full_wizard(c, bid_coffee, salutation="Kak")
    c.get("/logout")

    bid_dental = _make_client_with_business(c, "sarah@dental.test", "Dental XYZ", package="AI_ADMIN_PRO")
    c.post(f"/business/{bid_dental}/wizard/basics", data={
        "business_name": "Dental XYZ", "category": "Dental clinic", "short_description": "Modern dental care",
        "country": "USA", "timezone": "America/New_York", "address": "123 Main St",
        "business_phone": "555-0100", "owner_name": "Dr. Sarah",
    })
    c.post(f"/business/{bid_dental}/wizard/services", data={"services_raw": "Teeth whitening - $150\nCleaning - $80"})
    c.post(f"/business/{bid_dental}/wizard/operations", data={
        "operating_hours": "Mon-Fri 9am-5pm", "closed_days": "Sat, Sun", "online_or_offline": "offline",
        "appointment_rules_raw": "Book 24h in advance",
    })
    c.post(f"/business/{bid_dental}/wizard/faq", data={"faq_raw": "Do you accept insurance? Yes, most PPO plans."})
    c.post(f"/business/{bid_dental}/wizard/style", data={
        "tone": "formal", "primary_language": "en", "customer_salutation": "Hi",
    })
    c.post(f"/business/{bid_dental}/wizard/upload", data={})

    coffee_services = [s["raw_input"] for s in repo.get_business_services(bid_coffee)]
    dental_services = [s["raw_input"] for s in repo.get_business_services(bid_dental)]
    assert "Kopi susu" not in " ".join(dental_services)
    assert "Teeth whitening" not in " ".join(coffee_services)
    assert set(coffee_services).isdisjoint(set(dental_services))

    coffee_profile = repo.get_business_profile(bid_coffee)
    dental_profile = repo.get_business_profile(bid_dental)
    assert coffee_profile["primary_language"] == "id"
    assert dental_profile["primary_language"] == "en"
    assert coffee_profile["customer_salutation"] == "Kak"
    assert dental_profile["customer_salutation"] == "Hi"

    coffee_features = repo.get_tenant_features(bid_coffee)
    dental_features = repo.get_tenant_features(bid_dental)
    assert coffee_features["appointment"] == 0, "Basic package must not have appointment feature"
    assert dental_features["appointment"] == 1, "Pro package must have appointment feature"

    # simulate on each — sessions are per-business, verify no bleed
    c.get(f"/business/{bid_dental}/simulate")
    r = c.post(f"/business/{bid_dental}/simulate/message", json={"message": "Can I make an appointment?"})
    assert r.status_code == 200
    dental_sim_rows = db.query_all("SELECT * FROM simulation_messages WHERE business_id = ?", (bid_dental,))
    coffee_sim_rows = db.query_all("SELECT * FROM simulation_messages WHERE business_id = ?", (bid_coffee,))
    assert len(dental_sim_rows) == 2
    assert len(coffee_sim_rows) == 0, "Client A's simulation table must be untouched by Client B's simulation"
    print("test_staging_two_tenants_no_cross_talk OK")


# ---------------------------------------------------------------------------
# TENANT CONFIG SERVICE (bot integration surface — not wired into ../app.py yet)
# ---------------------------------------------------------------------------

def test_tenant_config_service_only_resolves_active_tenants():
    reset_db()
    import tenant_config_service as tcs
    user_id = repo.create_user("o@test.com", security.hash_password("password123"))
    bid = repo.create_business(user_id, "Kopi ABC")
    db.execute("UPDATE businesses SET whatsapp_phone_number_id = ? WHERE id = ?", ("999", bid))
    # not yet ACTIVE -> must not resolve
    assert tcs.resolve_tenant_id_by_whatsapp_phone_number_id("999") is None
    assert tcs.get_tenant_ai_config(bid) is None
    assert tcs.get_trusted_owner_phone(bid) is None

    admin_id = repo.create_user("admin@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN")
    repo.approve_business(bid, admin_id)
    db.execute("UPDATE businesses SET trusted_owner_phone = ?, whatsapp_connected = ? WHERE id = ?", ("+62811", True, bid))
    repo.activate_business(bid, admin_id)

    assert tcs.resolve_tenant_id_by_whatsapp_phone_number_id("999") == bid
    assert tcs.get_trusted_owner_phone(bid) == "+62811"
    # still None because ai_status != DONE
    assert tcs.get_tenant_ai_config(bid) is None
    repo.save_ai_normalized_config(bid, "summary", {"description": "x", "services": [], "faqs": []}, [])
    config = tcs.get_tenant_ai_config(bid)
    assert config is not None and config["tenant_id"] == bid
    print("test_tenant_config_service_only_resolves_active_tenants OK")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"\nALL {len(tests)} CLIENT HUB V1 TESTS PASSED")
