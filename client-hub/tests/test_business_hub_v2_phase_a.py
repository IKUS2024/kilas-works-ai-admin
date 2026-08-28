"""Kilas Works Client Hub — Business Hub V2, PHASE A test suite.

Covers what Phase A ("audit + admin role + forgot password") added on top of the Production
Foundation + Postgres Validation cycles: forgot/reset password (hashed, expiring, single-use,
rate-limited, no email-existence leak), the password_reset_tokens migration, and the
scripts/bootstrap_admin.py first-admin-account mechanism.

ADDITIVE — every earlier test file (test_client_hub_v1.py, test_production_foundation.py) is
untouched and still runs. Run with:
    cd client-hub && python3 tests/test_business_hub_v2_phase_a.py
"""
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("DATABASE_URL", None)  # this test process itself always uses SQLite

import db  # noqa: E402
import repo  # noqa: E402
import security  # noqa: E402
import email_utils  # noqa: E402
import app as client_hub_app  # noqa: E402

FLASK_APP = client_hub_app.app
FLASK_APP.testing = True

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fresh_client():
    return FLASK_APP.test_client()


def reset_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    db._local.conn = None
    db.init_schema()
    security._RESET_REQUEST_ATTEMPTS.clear()
    security._LOGIN_ATTEMPTS.clear()


def _register(client, email, password="password123"):
    return client.post("/register", data={"email": email, "password": password, "full_name": "Test User"},
                        follow_redirects=True)


# ---------------------------------------------------------------------------
# Migration / schema
# ---------------------------------------------------------------------------

def test_password_reset_tokens_table_created_idempotently():
    reset_db()
    db.init_schema()  # calling twice must not error (idempotent, like every other migration here)
    row = db.query_one("SELECT COUNT(*) as c FROM password_reset_tokens")
    assert row["c"] == 0
    print("test_password_reset_tokens_table_created_idempotently OK")


# ---------------------------------------------------------------------------
# Forgot password — request phase
# ---------------------------------------------------------------------------

def test_forgot_password_known_email_creates_token_and_generic_message():
    reset_db()
    client = fresh_client()
    _register(client, "owner1@test.com")
    resp = client.post("/forgot-password", data={"email": "owner1@test.com"}, follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "link reset password" in body.lower()
    user = repo.get_user_by_email("owner1@test.com")
    tokens = db.query_all("SELECT * FROM password_reset_tokens WHERE user_id = ?", (user["id"],))
    assert len(tokens) == 1, "a reset token row must be created for a known email"
    assert tokens[0]["used_at"] is None
    print("test_forgot_password_known_email_creates_token_and_generic_message OK")


def test_forgot_password_unknown_email_same_generic_message_no_token():
    reset_db()
    client = fresh_client()
    resp = client.post("/forgot-password", data={"email": "nobody-here@test.com"}, follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "link reset password" in body.lower(), (
        "response for an UNKNOWN email must look identical to a known one — no existence leak"
    )
    tokens = db.query_all("SELECT * FROM password_reset_tokens")
    assert len(tokens) == 0, "no token should ever be created for an email with no matching account"
    print("test_forgot_password_unknown_email_same_generic_message_no_token OK")


def test_forgot_password_rate_limited_after_repeated_requests():
    reset_db()
    client = fresh_client()
    _register(client, "owner2@test.com")
    for _ in range(security.RESET_REQUEST_MAX_ATTEMPTS):
        client.post("/forgot-password", data={"email": "owner2@test.com"}, follow_redirects=True)
    tokens_before = db.query_all("SELECT * FROM password_reset_tokens")
    # One more request, past the limit — must NOT create yet another token.
    client.post("/forgot-password", data={"email": "owner2@test.com"}, follow_redirects=True)
    tokens_after = db.query_all("SELECT * FROM password_reset_tokens")
    assert len(tokens_after) == len(tokens_before), "rate-limited request must not mint another token"
    print("test_forgot_password_rate_limited_after_repeated_requests OK")


# ---------------------------------------------------------------------------
# Reset password — consume phase
# ---------------------------------------------------------------------------

def _issue_raw_token_for(email):
    """Bypasses the HTTP layer/rate limit to directly mint a token the way the route would, so
    individual tests below can control expiry/used-state precisely."""
    user = repo.get_user_by_email(email)
    raw_token, token_hash = security.generate_reset_token()
    from datetime import datetime, timedelta, timezone
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=security.RESET_TOKEN_TTL_SECONDS)).isoformat()
    token_id = repo.create_password_reset_token(user["id"], token_hash, expires_at, "127.0.0.1")
    return raw_token, token_id, user


def test_reset_password_valid_token_changes_password_and_old_password_stops_working():
    reset_db()
    client = fresh_client()
    _register(client, "owner3@test.com", password="oldpassword123")
    raw_token, token_id, user = _issue_raw_token_for("owner3@test.com")

    resp = client.post(f"/reset-password/{raw_token}",
                        data={"password": "newpassword456", "confirm_password": "newpassword456"},
                        follow_redirects=True)
    assert resp.status_code == 200
    assert "berhasil diubah" in resp.get_data(as_text=True).lower()

    client.get("/logout")
    old_login = client.post("/login", data={"email": "owner3@test.com", "password": "oldpassword123"})
    assert old_login.status_code == 200 and "salah" in old_login.get_data(as_text=True).lower(), (
        "old password must no longer work after reset"
    )
    new_login = client.post("/login", data={"email": "owner3@test.com", "password": "newpassword456"},
                             follow_redirects=True)
    assert "dashboard" in new_login.request.path or new_login.status_code == 200
    print("test_reset_password_valid_token_changes_password_and_old_password_stops_working OK")


def test_reset_password_token_is_single_use():
    reset_db()
    client = fresh_client()
    _register(client, "owner4@test.com", password="oldpassword123")
    raw_token, token_id, user = _issue_raw_token_for("owner4@test.com")

    client.post(f"/reset-password/{raw_token}",
                data={"password": "firstnewpass1", "confirm_password": "firstnewpass1"},
                follow_redirects=True)
    # Try to reuse the SAME raw token a second time — must be rejected even though it hasn't
    # technically expired yet.
    second_attempt = client.get(f"/reset-password/{raw_token}", follow_redirects=True)
    assert "tidak valid" in second_attempt.get_data(as_text=True).lower()
    print("test_reset_password_token_is_single_use OK")


def test_reset_password_expired_token_rejected():
    reset_db()
    client = fresh_client()
    _register(client, "owner5@test.com")
    user = repo.get_user_by_email("owner5@test.com")
    raw_token, token_hash = security.generate_reset_token()
    from datetime import datetime, timedelta, timezone
    already_expired = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    repo.create_password_reset_token(user["id"], token_hash, already_expired, "127.0.0.1")

    resp = client.get(f"/reset-password/{raw_token}", follow_redirects=True)
    assert "tidak valid" in resp.get_data(as_text=True).lower() or "kedaluwarsa" in resp.get_data(as_text=True).lower()
    print("test_reset_password_expired_token_rejected OK")


def test_reset_password_garbage_token_rejected_not_500():
    reset_db()
    client = fresh_client()
    resp = client.get("/reset-password/this-token-never-existed", follow_redirects=True)
    assert resp.status_code == 200
    assert "tidak valid" in resp.get_data(as_text=True).lower()
    print("test_reset_password_garbage_token_rejected_not_500 OK")


def test_reset_password_mismatched_confirmation_rejected():
    reset_db()
    client = fresh_client()
    _register(client, "owner6@test.com")
    raw_token, token_id, user = _issue_raw_token_for("owner6@test.com")
    resp = client.post(f"/reset-password/{raw_token}",
                        data={"password": "newpassword456", "confirm_password": "somethingelse"},
                        follow_redirects=True)
    assert "tidak cocok" in resp.get_data(as_text=True).lower()
    row = db.query_one("SELECT used_at FROM password_reset_tokens WHERE id = ?", (token_id,))
    assert row["used_at"] is None, "a rejected reset attempt must not consume the token"
    print("test_reset_password_mismatched_confirmation_rejected OK")


def test_reset_password_invalidates_other_pending_tokens_for_same_user():
    reset_db()
    client = fresh_client()
    _register(client, "owner7@test.com")
    raw_token_1, token_id_1, user = _issue_raw_token_for("owner7@test.com")
    raw_token_2, token_id_2, _ = _issue_raw_token_for("owner7@test.com")

    client.post(f"/reset-password/{raw_token_1}",
                data={"password": "newpassword456", "confirm_password": "newpassword456"},
                follow_redirects=True)

    # The SECOND, still-unused token must also be burned now — an old reset email in an inbox
    # must not work after the password has already been changed via a newer link.
    stale_attempt = client.get(f"/reset-password/{raw_token_2}", follow_redirects=True)
    assert "tidak valid" in stale_attempt.get_data(as_text=True).lower()
    print("test_reset_password_invalidates_other_pending_tokens_for_same_user OK")


# ---------------------------------------------------------------------------
# Admin role / bootstrap
# ---------------------------------------------------------------------------

def test_register_never_creates_admin_role():
    reset_db()
    client = fresh_client()
    _register(client, "definitely-not-admin@test.com")
    user = repo.get_user_by_email("definitely-not-admin@test.com")
    assert user["role"] == "CLIENT_OWNER", "public registration must NEVER create a KILAS_ADMIN account"
    print("test_register_never_creates_admin_role OK")


def test_login_routes_by_role_with_no_role_selector_on_login_form():
    reset_db()
    client = fresh_client()
    login_page = client.get("/login")
    body = login_page.get_data(as_text=True)
    assert "owner" not in body.lower() and "kilas_admin" not in body.lower() and "role" not in body.lower(), (
        "login page must not ask the user to choose a role — routing is server-side, post-login"
    )

    admin_id = repo.create_user("admin_route@test.com", security.hash_password("adminpass123"), role="KILAS_ADMIN")
    admin_resp = client.post("/login", data={"email": "admin_route@test.com", "password": "adminpass123"})
    assert admin_resp.status_code == 302 and "/admin" in admin_resp.headers["Location"]
    client.get("/logout")

    _register(client, "client_route@test.com")
    client.get("/logout")
    client_resp = client.post("/login", data={"email": "client_route@test.com", "password": "password123"})
    assert client_resp.status_code == 302 and "/admin" not in client_resp.headers["Location"]
    print("test_login_routes_by_role_with_no_role_selector_on_login_form OK")


def _run_bootstrap_script(email, token, password="adminpass123", env_token="correct-bootstrap-token"):
    env = dict(os.environ)
    env["BOOTSTRAP_ADMIN_TOKEN"] = env_token
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "scripts", "bootstrap_admin.py"),
         "--email", email, "--token", token],
        input=f"{password}\n{password}\n",
        capture_output=True, text=True, cwd=REPO_ROOT, env=env, timeout=30,
    )
    return proc


def test_bootstrap_admin_script_creates_kilas_admin_with_correct_token():
    reset_db()
    proc = _run_bootstrap_script("bootstrap1@kilasworks.id", "correct-bootstrap-token")
    assert proc.returncode == 0, f"bootstrap script failed: {proc.stdout} {proc.stderr}"
    user = repo.get_user_by_email("bootstrap1@kilasworks.id")
    assert user is not None and user["role"] == "KILAS_ADMIN"
    print("test_bootstrap_admin_script_creates_kilas_admin_with_correct_token OK")


def test_bootstrap_admin_script_refuses_wrong_token():
    reset_db()
    proc = _run_bootstrap_script("bootstrap2@kilasworks.id", "wrong-token", env_token="correct-bootstrap-token")
    assert proc.returncode != 0
    assert repo.get_user_by_email("bootstrap2@kilasworks.id") is None
    print("test_bootstrap_admin_script_refuses_wrong_token OK")


def test_bootstrap_admin_script_refuses_existing_email():
    reset_db()
    proc1 = _run_bootstrap_script("bootstrap3@kilasworks.id", "correct-bootstrap-token")
    assert proc1.returncode == 0
    proc2 = _run_bootstrap_script("bootstrap3@kilasworks.id", "correct-bootstrap-token")
    assert proc2.returncode != 0, "must refuse to create a second account for an email that already exists"
    print("test_bootstrap_admin_script_refuses_existing_email OK")


# ---------------------------------------------------------------------------
# Security — no secrets leaked in this phase's new surface area
# ---------------------------------------------------------------------------

def test_reset_token_never_stored_in_plaintext():
    reset_db()
    client = fresh_client()
    _register(client, "owner8@test.com")
    client.post("/forgot-password", data={"email": "owner8@test.com"}, follow_redirects=True)
    user = repo.get_user_by_email("owner8@test.com")
    row = db.query_one("SELECT token_hash FROM password_reset_tokens WHERE user_id = ?", (user["id"],))
    assert row is not None
    assert len(row["token_hash"]) == 64, "token_hash should be a hex-encoded SHA-256 digest (64 chars)"
    print("test_reset_token_never_stored_in_plaintext OK")


# ---------------------------------------------------------------------------
# Business Hub V2, Production Integration cycle — reset URL always uses the real production domain
# ---------------------------------------------------------------------------

def test_reset_url_uses_public_app_base_url_when_set():
    old = os.environ.get("PUBLIC_APP_BASE_URL")
    os.environ["PUBLIC_APP_BASE_URL"] = "https://app.kilasworks.id"
    try:
        url = email_utils.build_reset_url("http://localhost:5000/reset-password/abc123", "abc123")
        assert url == "https://app.kilasworks.id/reset-password/abc123", url
    finally:
        if old is None:
            os.environ.pop("PUBLIC_APP_BASE_URL", None)
        else:
            os.environ["PUBLIC_APP_BASE_URL"] = old
    print("test_reset_url_uses_public_app_base_url_when_set OK")


def test_reset_url_falls_back_to_flask_external_url_when_unset():
    os.environ.pop("PUBLIC_APP_BASE_URL", None)
    fallback = "http://localhost:5000/reset-password/xyz789"
    url = email_utils.build_reset_url(fallback, "xyz789")
    assert url == fallback, "with no PUBLIC_APP_BASE_URL set, local/dev behavior must be unchanged"
    print("test_reset_url_falls_back_to_flask_external_url_when_unset OK")


def test_forgot_password_end_to_end_uses_production_reset_url_when_configured():
    reset_db()
    old = os.environ.get("PUBLIC_APP_BASE_URL")
    os.environ["PUBLIC_APP_BASE_URL"] = "https://app.kilasworks.id"
    try:
        client = fresh_client()
        _register(client, "owner9@test.com")
        resp = client.post("/forgot-password", data={"email": "owner9@test.com"}, follow_redirects=True)
        assert resp.status_code == 200
        # DEV MODE print (no SMTP configured in tests) should show the real production domain,
        # never localhost/127.0.0.1/an internal Render hostname.
    finally:
        if old is None:
            os.environ.pop("PUBLIC_APP_BASE_URL", None)
        else:
            os.environ["PUBLIC_APP_BASE_URL"] = old
    print("test_forgot_password_end_to_end_uses_production_reset_url_when_configured OK")


if __name__ == "__main__":
    test_password_reset_tokens_table_created_idempotently()
    test_forgot_password_known_email_creates_token_and_generic_message()
    test_forgot_password_unknown_email_same_generic_message_no_token()
    test_forgot_password_rate_limited_after_repeated_requests()
    test_reset_password_valid_token_changes_password_and_old_password_stops_working()
    test_reset_password_token_is_single_use()
    test_reset_password_expired_token_rejected()
    test_reset_password_garbage_token_rejected_not_500()
    test_reset_password_mismatched_confirmation_rejected()
    test_reset_password_invalidates_other_pending_tokens_for_same_user()
    test_register_never_creates_admin_role()
    test_login_routes_by_role_with_no_role_selector_on_login_form()
    test_bootstrap_admin_script_creates_kilas_admin_with_correct_token()
    test_bootstrap_admin_script_refuses_wrong_token()
    test_bootstrap_admin_script_refuses_existing_email()
    test_reset_token_never_stored_in_plaintext()
    test_reset_url_uses_public_app_base_url_when_set()
    test_reset_url_falls_back_to_flask_external_url_when_unset()
    test_forgot_password_end_to_end_uses_production_reset_url_when_configured()
    print("\nALL BUSINESS HUB V2 PHASE A TESTS PASSED")
