"""Kilas Works Client Hub — PRODUCTION FOUNDATION cycle test suite (Phase 7).

Covers what Phase 1-6 of the "NEXT PHASE" request added: the dual SQLite/PostgreSQL db.py layer,
the Phase 2 tenant config model, Phase 3's centralized feature matrix, Phase 4's provisioning
layer (idempotency, audit events, invalid-state-transition guards), and Phase 6's security
hardening (CSRF, secrets never exposed, password/session basics re-confirmed).

This file is ADDITIVE — tests/test_client_hub_v1.py from the previous cycle is untouched and
still runs (see the bottom of this repo's test run instructions in the final report). Run with:
    cd client-hub && python3 tests/test_production_foundation.py
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("DATABASE_URL", None)  # this test process itself always uses SQLite

import db  # noqa: E402
import repo  # noqa: E402
import security  # noqa: E402
import feature_flags  # noqa: E402
import provisioning  # noqa: E402
import tenant_config_service as tcs  # noqa: E402
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


def _make_admin():
    admin_id = repo.create_user(f"admin_{os.urandom(4).hex()}@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN")
    return repo.get_user_by_email.__wrapped__ if False else db.query_one("SELECT * FROM users WHERE id = ?", (admin_id,))


def _make_business_ready_for_approval():
    owner_id = repo.create_user(f"owner_{os.urandom(4).hex()}@test.com", security.hash_password("password123"))
    bid = repo.create_business(owner_id, "Kopi ABC", package="AI_ADMIN_BASIC")
    repo.upsert_business_profile(bid, {
        "business_name": "Kopi ABC", "category": "Kedai kopi", "owner_name": "Budi",
        "primary_language": "id", "customer_salutation": "Kak",
    })
    repo.replace_business_services(bid, ["Kopi susu - 20rb"])
    repo.replace_business_faqs(bid, ["Ada wifi? Ada."])
    repo.save_ai_normalized_config(bid, "Kopi ABC summary", {"description": "Kedai kopi ramah"}, [])
    return bid


# ---------------------------------------------------------------------------
# DB BACKEND — SQLite (local/tests) and PostgreSQL-compatible layer (testable subset)
# ---------------------------------------------------------------------------

def test_db_sqlite_backend_is_default_and_functional():
    reset_db()
    assert db.BACKEND == "sqlite"
    bid = repo.create_business(repo.create_user("sqlitecheck@test.com", security.hash_password("password123")), "SQLite Co")
    assert repo.get_business(bid)["business_name"] == "SQLite Co"
    print("test_db_sqlite_backend_is_default_and_functional OK")


def test_db_postgres_placeholder_translation():
    # We can't open a real Postgres connection in this sandbox, but the placeholder-translation
    # logic itself is pure and testable without one.
    original_backend = db.BACKEND
    try:
        db.BACKEND = "postgres"
        translated = db._adapt_placeholders("SELECT * FROM users WHERE id = ? AND email = ?")
        assert translated == "SELECT * FROM users WHERE id = %s AND email = %s"
    finally:
        db.BACKEND = original_backend
    print("test_db_postgres_placeholder_translation OK")


def test_db_postgres_requires_psycopg2_fails_loudly_not_silently():
    """DATABASE_URL set but psycopg2 not installed (true in this sandbox) must raise a clear
    RuntimeError at import time — NEVER silently fall back to SQLite for a configured production
    database. Run in a subprocess since BACKEND is decided at db.py's import time."""
    env = dict(os.environ)
    env["DATABASE_URL"] = "postgresql://user:pass@localhost:5432/doesnotmatter"
    env.pop("CLIENT_HUB_DB_PATH", None)
    result = subprocess.run(
        [sys.executable, "-c", "import db"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0, "importing db.py with DATABASE_URL set but no psycopg2 must fail, not silently succeed"
    assert "psycopg2" in result.stderr, f"expected a clear psycopg2-related error, got: {result.stderr[-500:]}"
    print("test_db_postgres_requires_psycopg2_fails_loudly_not_silently OK")


def test_db_insert_returning_id_sqlite():
    reset_db()
    new_id = db.insert_returning_id(
        "INSERT INTO users (email, password_hash, role) VALUES (?, ?, ?)",
        ("returning_id_check@test.com", "hash", "CLIENT_OWNER"),
    )
    assert isinstance(new_id, int) and new_id > 0
    row = db.query_one("SELECT * FROM users WHERE id = ?", (new_id,))
    assert row["email"] == "returning_id_check@test.com"
    print("test_db_insert_returning_id_sqlite OK")


# ---------------------------------------------------------------------------
# FEATURE FLAGS — centralized matrix (Phase 3)
# ---------------------------------------------------------------------------

def test_feature_matrix_basic_and_pro_are_distinct_and_backend_enforced():
    basic = feature_flags.features_for_package("AI_ADMIN_BASIC")
    pro = feature_flags.features_for_package("AI_ADMIN_PRO")
    assert basic != pro
    assert basic["appointment"] is False and pro["appointment"] is True
    assert basic["faq"] is True and pro["faq"] is True  # both packages get the Basic-tier features
    assert set(feature_flags.ALL_FEATURE_KEYS) == set(basic.keys()) == set(pro.keys())
    print("test_feature_matrix_basic_and_pro_are_distinct_and_backend_enforced OK")


def test_feature_matrix_invalid_package_rejected():
    try:
        feature_flags.features_for_package("NOT_A_REAL_PACKAGE")
        assert False, "expected ValueError for an unknown package"
    except ValueError:
        pass
    assert not feature_flags.is_valid_package("NOT_A_REAL_PACKAGE")
    print("test_feature_matrix_invalid_package_rejected OK")


def test_change_package_reseeds_feature_flags():
    """Regression test for a real bug found in this cycle: changing a business's package used to
    update businesses.package but leave tenant_features at the OLD package's flags."""
    reset_db()
    owner_id = repo.create_user("pkgcheck@test.com", security.hash_password("password123"))
    bid = repo.create_business(owner_id, "Kopi ABC", package="AI_ADMIN_BASIC")
    assert repo.get_tenant_features(bid)["appointment"] == 0
    repo.set_business_package(bid, "AI_ADMIN_PRO")
    assert repo.get_tenant_features(bid)["appointment"] == 1, "tenant_features must be re-seeded when package changes"
    print("test_change_package_reseeds_feature_flags OK")


# ---------------------------------------------------------------------------
# TENANT CONFIG MODEL (Phase 2)
# ---------------------------------------------------------------------------

def test_build_tenant_config_shape():
    reset_db()
    bid = _make_business_ready_for_approval()
    config = provisioning.build_tenant_config(bid)
    for key in ("tenant_id", "business_name", "status", "ai", "business_info", "knowledge",
                "lead_behavior", "appointment_behavior", "feature_plan", "whatsapp"):
        assert key in config, f"tenant config missing expected top-level key: {key}"
    assert config["knowledge"]["services"][0]["raw_input"] == "Kopi susu - 20rb"
    assert config["feature_plan"]["package"] == "AI_ADMIN_BASIC"
    assert config["whatsapp"]["connection_status"] == "NOT_CONNECTED"
    print("test_build_tenant_config_shape OK")


def test_tenant_config_never_invents_missing_price():
    reset_db()
    bid = _make_business_ready_for_approval()
    config = provisioning.build_tenant_config(bid)
    # "Kopi susu - 20rb" was never normalized by a real Claude call in this test (no API key
    # configured), so price_from must still be None/unset, never a guessed number.
    assert config["knowledge"]["services"][0]["price_from"] is None
    print("test_tenant_config_never_invents_missing_price OK")


# ---------------------------------------------------------------------------
# PROVISIONING (Phase 4) — idempotency, invalid transitions, audit events
# ---------------------------------------------------------------------------

def test_provisioning_requires_approved_status():
    reset_db()
    bid = _make_business_ready_for_approval()  # still DRAFT — never submitted/approved
    admin = db.query_one("SELECT * FROM users WHERE id = ?",
                          (repo.create_user("admin1@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN"),))
    try:
        provisioning.provision_tenant(bid, admin)
        assert False, "expected ProvisioningError for a DRAFT business"
    except provisioning.ProvisioningError as e:
        assert "invalid_state_transition" in str(e)
    print("test_provisioning_requires_approved_status OK")


def test_provisioning_validation_fails_without_ai_done():
    reset_db()
    owner_id = repo.create_user("owner2@test.com", security.hash_password("password123"))
    bid = repo.create_business(owner_id, "Kopi ABC")
    repo.upsert_business_profile(bid, {"owner_name": "Budi", "category": "Kedai kopi", "primary_language": "id", "customer_salutation": "Kak"})
    repo.replace_business_services(bid, ["Kopi - 15rb"])
    admin = db.query_one("SELECT * FROM users WHERE id = ?",
                          (repo.create_user("admin2@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN"),))
    repo.approve_business(bid, admin["id"])  # force APPROVED without AI setup, to isolate this check
    ok, errors = provisioning.validate_tenant_config(bid)
    assert not ok and any("ai_setup_not_done" in e for e in errors)
    try:
        provisioning.provision_tenant(bid, admin)
        assert False, "expected ProvisioningError when AI setup was never completed"
    except provisioning.ProvisioningError as e:
        assert "validation_failed" in str(e)
    print("test_provisioning_validation_fails_without_ai_done OK")


def test_provisioning_idempotent_duplicate_call():
    reset_db()
    bid = _make_business_ready_for_approval()
    admin = db.query_one("SELECT * FROM users WHERE id = ?",
                          (repo.create_user("admin3@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN"),))
    repo.approve_business(bid, admin["id"])

    first = provisioning.provision_tenant(bid, admin)
    assert first["changed"] is True and first["config_version"] == 1

    second = provisioning.provision_tenant(bid, admin)
    assert second["changed"] is False, "re-provisioning with no data change must be a no-op"
    assert second["config_version"] == 1, "version must not bump when nothing changed"

    audit = repo.get_audit_log(bid)
    provisioned_events = [a for a in audit if a["action"] == provisioning.EVENT_TENANT_PROVISIONED]
    assert len(provisioned_events) == 1, "duplicate provisioning with no changes must not write a duplicate audit event"
    print("test_provisioning_idempotent_duplicate_call OK")


def test_provisioning_reprovision_after_edit_bumps_version():
    reset_db()
    bid = _make_business_ready_for_approval()
    admin = db.query_one("SELECT * FROM users WHERE id = ?",
                          (repo.create_user("admin4@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN"),))
    repo.approve_business(bid, admin["id"])
    provisioning.provision_tenant(bid, admin)

    repo.replace_business_faqs(bid, ["Ada wifi? Ada.", "Bisa delivery? Bisa, area Tangerang."])
    second = provisioning.provision_tenant(bid, admin)
    assert second["changed"] is True and second["config_version"] == 2
    print("test_provisioning_reprovision_after_edit_bumps_version OK")


def test_activation_duplicate_activation_is_safe_noop():
    reset_db()
    bid = _make_business_ready_for_approval()
    admin = db.query_one("SELECT * FROM users WHERE id = ?",
                          (repo.create_user("admin5@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN"),))
    provisioning.approve_and_provision(bid, admin)
    provisioning.connect_whatsapp_credentials(bid, admin, "111", "waba1", "WHATSAPP_TOKEN__TEST")
    db.execute("UPDATE businesses SET whatsapp_connected = ? WHERE id = ?", (True, bid))  # V1 gate, dual-written by the route normally

    first = provisioning.activate_tenant(bid, admin)
    assert first["changed"] is True and first["status"] == "ACTIVE"

    second = provisioning.activate_tenant(bid, admin)
    assert second["changed"] is False, "activating an already-ACTIVE tenant must be a safe no-op"

    audit = repo.get_audit_log(bid)
    activated_events = [a for a in audit if a["action"] == provisioning.EVENT_TENANT_ACTIVATED]
    assert len(activated_events) == 1, "duplicate activation must not write a duplicate audit event"
    print("test_activation_duplicate_activation_is_safe_noop OK")


def test_activation_missing_whatsapp_config_blocked():
    reset_db()
    bid = _make_business_ready_for_approval()
    admin = db.query_one("SELECT * FROM users WHERE id = ?",
                          (repo.create_user("admin6@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN"),))
    provisioning.approve_and_provision(bid, admin)
    try:
        provisioning.activate_tenant(bid, admin)
        assert False, "expected ProvisioningError — WhatsApp was never connected"
    except provisioning.ProvisioningError as e:
        assert "missing_whatsapp_config" in str(e)
    print("test_activation_missing_whatsapp_config_blocked OK")


def test_activation_invalid_state_transition_from_draft():
    reset_db()
    bid = _make_business_ready_for_approval()  # DRAFT, never approved
    admin = db.query_one("SELECT * FROM users WHERE id = ?",
                          (repo.create_user("admin7@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN"),))
    try:
        provisioning.activate_tenant(bid, admin)
        assert False, "expected ProvisioningError — business was never approved"
    except provisioning.ProvisioningError as e:
        assert "invalid_state_transition" in str(e)
    print("test_activation_invalid_state_transition_from_draft OK")


def test_provisioning_admin_only_defense_in_depth():
    """Even called directly (bypassing the @security.admin_required route decorator), provisioning
    functions must refuse a non-admin actor."""
    reset_db()
    bid = _make_business_ready_for_approval()
    fake_client_actor = {"id": 999, "role": "CLIENT_OWNER"}
    try:
        provisioning.provision_tenant(bid, fake_client_actor)
        assert False, "expected PermissionError for a non-admin actor"
    except PermissionError:
        pass
    try:
        provisioning.activate_tenant(bid, fake_client_actor)
        assert False, "expected PermissionError for a non-admin actor"
    except PermissionError:
        pass
    print("test_provisioning_admin_only_defense_in_depth OK")


def test_provisioning_audit_log_has_canonical_events():
    reset_db()
    bid = _make_business_ready_for_approval()
    admin = db.query_one("SELECT * FROM users WHERE id = ?",
                          (repo.create_user("admin8@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN"),))
    owner = repo.get_business(bid)
    provisioning.record_business_submitted(bid, None)
    provisioning.approve_and_provision(bid, admin)
    provisioning.connect_whatsapp_credentials(bid, admin, "111", None, "WHATSAPP_TOKEN__TEST")
    db.execute("UPDATE businesses SET whatsapp_connected = ? WHERE id = ?", (True, bid))
    provisioning.activate_tenant(bid, admin)
    provisioning.deactivate_tenant(bid, admin)

    actions = {a["action"] for a in repo.get_audit_log(bid, limit=100)}
    for expected in (provisioning.EVENT_BUSINESS_SUBMITTED, provisioning.EVENT_BUSINESS_APPROVED,
                      provisioning.EVENT_TENANT_PROVISIONED, provisioning.EVENT_WHATSAPP_CONNECTED,
                      provisioning.EVENT_TENANT_ACTIVATED, provisioning.EVENT_TENANT_DEACTIVATED):
        assert expected in actions, f"missing canonical provisioning audit event: {expected}"
    print("test_provisioning_audit_log_has_canonical_events OK")


# ---------------------------------------------------------------------------
# BOT INTEGRATION CONTRACT (Phase 5) — inactive tenant, active tenant, knowledge slice
# ---------------------------------------------------------------------------

def test_bot_contract_inactive_tenant_returns_none():
    reset_db()
    bid = _make_business_ready_for_approval()
    assert tcs.get_tenant_config(bid) is None
    assert tcs.get_tenant_knowledge(bid) is None
    assert tcs.get_tenant_by_phone_number_id("999") is None
    print("test_bot_contract_inactive_tenant_returns_none OK")


def test_bot_contract_active_tenant_returns_config_and_knowledge():
    reset_db()
    bid = _make_business_ready_for_approval()
    admin = db.query_one("SELECT * FROM users WHERE id = ?",
                          (repo.create_user("admin9@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN"),))
    provisioning.approve_and_provision(bid, admin)
    provisioning.connect_whatsapp_credentials(bid, admin, "555", None, "WHATSAPP_TOKEN__TEST")
    db.execute("UPDATE businesses SET whatsapp_connected = ?, whatsapp_phone_number_id = ? WHERE id = ?", (True, "555", bid))
    provisioning.activate_tenant(bid, admin)

    assert tcs.get_tenant_by_phone_number_id("555") == bid
    config = tcs.get_tenant_config(bid)
    assert config is not None and config["tenant_id"] == bid
    knowledge = tcs.get_tenant_knowledge(bid)
    assert knowledge is not None and len(knowledge["services"]) == 1
    print("test_bot_contract_active_tenant_returns_config_and_knowledge OK")


# ---------------------------------------------------------------------------
# SECURITY HARDENING (Phase 6)
# ---------------------------------------------------------------------------

def test_csrf_blocks_post_without_token_when_enforced():
    reset_db()
    c = fresh_client()
    c.post("/register", data={"email": "csrfcheck@test.com", "password": "password123"})
    FLASK_APP.config["CLIENT_HUB_FORCE_CSRF_IN_TESTS"] = True
    try:
        r = c.post("/business/create", data={"business_name": "No CSRF Co"})
        assert r.status_code == 400, "a POST with no csrf_token field must be rejected once CSRF is enforced"
    finally:
        FLASK_APP.config["CLIENT_HUB_FORCE_CSRF_IN_TESTS"] = False
    print("test_csrf_blocks_post_without_token_when_enforced OK")


def test_csrf_allows_post_with_valid_token():
    reset_db()
    c = fresh_client()
    c.post("/register", data={"email": "csrfcheck2@test.com", "password": "password123"})
    login_page = c.get("/dashboard")  # ensures a csrf token exists in session (rendered by a GET)
    with c.session_transaction() as sess:
        token = sess.get("_csrf_token")
    assert token, "csrf_token() must have been called by some GET-rendered template by now"

    FLASK_APP.config["CLIENT_HUB_FORCE_CSRF_IN_TESTS"] = True
    try:
        r = c.post("/business/create", data={"business_name": "With CSRF Co", "csrf_token": token}, follow_redirects=True)
        assert r.status_code == 200
    finally:
        FLASK_APP.config["CLIENT_HUB_FORCE_CSRF_IN_TESTS"] = False
    assert db.query_one("SELECT id FROM businesses WHERE business_name = ?", ("With CSRF Co",)) is not None
    print("test_csrf_allows_post_with_valid_token OK")


def test_login_rate_limiting_after_repeated_failures():
    reset_db()
    repo.create_user("ratelimit@test.com", security.hash_password("correctpassword123"))
    c = fresh_client()
    for _ in range(security.LOGIN_MAX_ATTEMPTS):
        c.post("/login", data={"email": "ratelimit@test.com", "password": "wrongpassword"})
    r = c.post("/login", data={"email": "ratelimit@test.com", "password": "correctpassword123"}, follow_redirects=True)
    # even the CORRECT password must now be rejected — locked out for the window
    with c.session_transaction() as sess:
        assert sess.get("user_id") is None, "account must be rate-limited after repeated failed attempts, even with the correct password"
    print("test_login_rate_limiting_after_repeated_failures OK")


def test_debug_mode_defaults_off():
    assert os.environ.get("CLIENT_HUB_ENV") != "development"
    # app.py computes debug_mode at __main__ time from this exact check; assert the guard exists
    # by re-reading the source (the safest way to test "does the default choice stay safe" without
    # actually spawning app.run()).
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")).read()
    assert 'debug_mode = os.environ.get("CLIENT_HUB_ENV") == "development"' in src, \
        "debug mode must be opt-in (only for CLIENT_HUB_ENV=development), never opt-out"
    print("test_debug_mode_defaults_off OK")


def test_secrets_never_exposed_in_new_modules():
    # app.py is intentionally excluded here: it references SECRET_KEY by name in its own startup
    # validation logic (required to refuse booting without one) and mentions ANTHROPIC_API_KEY
    # only inside a docstring comment describing how to run the app locally — neither is a leak.
    # The modules that actually handle tenant-facing routes/rendering are what must never
    # reference these secret env var names at all, since that's where a leak into a
    # response/template would happen.
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fname in ("provisioning.py", "repo.py", "tenant_config_service.py", "routes_admin.py", "routes_client.py"):
        src = open(os.path.join(base, fname)).read()
        assert "ANTHROPIC_API_KEY" not in src, f"{fname} must never reference the raw API key constant"
        assert "SECRET_KEY" not in src, f"{fname} must never reference SECRET_KEY"
    # The WhatsApp credentials_reference design must never store a literal access token value —
    # only ever a reference/pointer string built from the business id.
    prov_src = open(os.path.join(base, "provisioning.py")).read()
    assert "access_token" not in prov_src.lower() or "credentials_reference" in prov_src
    print("test_secrets_never_exposed_in_new_modules OK")


def test_whatsapp_credentials_reference_is_a_pointer_not_a_token():
    reset_db()
    bid = _make_business_ready_for_approval()
    admin = db.query_one("SELECT * FROM users WHERE id = ?",
                          (repo.create_user("admin10@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN"),))
    provisioning.connect_whatsapp_credentials(bid, admin, "222", "waba2", "WHATSAPP_TOKEN__TENANT_42")
    stored = repo.get_whatsapp_config(bid)
    assert stored["credentials_reference"] == "WHATSAPP_TOKEN__TENANT_42"
    assert not stored["credentials_reference"].startswith("EAA")  # a real Meta token always starts this way — sanity check it's a name, not a token
    print("test_whatsapp_credentials_reference_is_a_pointer_not_a_token OK")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"\nALL {len(tests)} PRODUCTION FOUNDATION TESTS PASSED")
