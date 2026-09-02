"""Auth & tenant-isolation helpers for Client Hub.

AUTH APPROACH (explained fully in the final report too): email + password.
  - Passwords hashed with werkzeug.security.generate_password_hash (PBKDF2-SHA256 by default in
    this Werkzeug version) — NEVER stored or logged in plaintext.
  - Session is Flask's built-in signed cookie session (itsdangerous under the hood), which is
    already a dependency of Flask (no new package needed). The cookie is signed with SECRET_KEY
    (env var, required — the app refuses to start with a default secret) so it cannot be forged
    without that key, and it is NOT readable/editable by the browser in a way that changes its
    contents without invalidating the signature. Cookies are set httponly + samesite=Lax, and
    secure=True when not running in local dev (see app.py).
  - This is deliberately NOT a custom-rolled crypto scheme — it's Flask's own, well-reviewed
    session implementation, which satisfies "do not invent a custom insecure authentication
    system" while adding zero new dependencies to install (important since this sandbox has no
    package-index access — see db.py's note).

TENANT ISOLATION APPROACH: every route that touches one business's data requires either
(a) role == KILAS_ADMIN (admins can see all tenants, by design — section 2/22), or
(b) a row in business_memberships linking session user_id to that business_id.
There is no code path that resolves a business by anything other than its primary key id, and
every such lookup is immediately checked against membership. This is enforced once, centrally, in
`require_business_access` — individual routes cannot forget to scope a query because they never
run the business-fetch themselves, they call this helper.
"""
import functools
import hmac
import secrets
import time
from flask import session, redirect, url_for, request, abort

import db

# ---------------------------------------------------------------------------
# CSRF protection (Phase 6 hardening) — session-bound token, checked on every
# state-changing request. Flask has no built-in CSRF, so this is a small,
# deliberately simple implementation rather than a new dependency: one random
# token generated per session, compared with constant-time comparison.
# ---------------------------------------------------------------------------

def get_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["_csrf_token"] = token
    return token


def validate_csrf_token(candidate):
    expected = session.get("_csrf_token")
    if not expected or not candidate:
        return False
    return hmac.compare_digest(expected, candidate)


# ---------------------------------------------------------------------------
# Basic login rate limiting (Phase 6 hardening) — in-memory, per-process. This
# is intentionally simple (not a distributed store) since Client Hub V1 runs
# as a single small service; if it's ever scaled to multiple workers/dynos,
# swap this for a shared store (Redis) — the call sites (login_page) would not
# need to change, only this module's internals.
# ---------------------------------------------------------------------------

_LOGIN_ATTEMPTS = {}  # key -> [timestamps of recent failed attempts]
LOGIN_MAX_ATTEMPTS = 8
LOGIN_WINDOW_SECONDS = 300  # 5 minutes


def _rate_limit_key(email):
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    return f"{ip}:{(email or '').strip().lower()}"


def is_login_rate_limited(email):
    key = _rate_limit_key(email)
    now = time.time()
    attempts = [t for t in _LOGIN_ATTEMPTS.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
    _LOGIN_ATTEMPTS[key] = attempts
    return len(attempts) >= LOGIN_MAX_ATTEMPTS


def record_failed_login(email):
    key = _rate_limit_key(email)
    _LOGIN_ATTEMPTS.setdefault(key, []).append(time.time())


def clear_login_attempts(email):
    _LOGIN_ATTEMPTS.pop(_rate_limit_key(email), None)


# ---------------------------------------------------------------------------
# Forgot / reset password (Business Hub V2, Phase A).
#
# Design:
#   - The raw token is a cryptographically random URL-safe string (secrets.token_urlsafe), given
#     to the user exactly once (in the reset link). It is NEVER stored anywhere.
#   - What's stored in password_reset_tokens.token_hash is SHA-256(raw_token) — a one-way hash, so
#     a DB leak alone can never be used to reset anyone's password (same principle as password
#     hashing itself, applied to the token).
#   - Expiry: RESET_TOKEN_TTL_SECONDS (30 minutes) from creation, checked in SQL comparison AND
#     re-checked in Python after fetch (belt and suspenders — see repo.get_valid_reset_token).
#   - Single-use: used_at is set the moment a token is successfully consumed; every lookup filters
#     on used_at IS NULL, so a second attempt with the same raw token always fails, even if it's
#     still within its expiry window.
#   - Rate limiting reuses the exact same in-memory (ip+email) window pattern as login, just a
#     separate counter/window, so a script can't hammer /forgot-password to enumerate emails or
#     spam reset links.
# ---------------------------------------------------------------------------
import hashlib

RESET_TOKEN_TTL_SECONDS = 30 * 60  # 30 minutes
RESET_REQUEST_MAX_ATTEMPTS = 5
RESET_REQUEST_WINDOW_SECONDS = 3600  # 1 hour

_RESET_REQUEST_ATTEMPTS = {}  # key -> [timestamps]


def generate_reset_token():
    """Returns (raw_token, token_hash). raw_token goes in the URL (once); token_hash goes in the
    DB. Never store raw_token anywhere — not in a variable that outlives this request, not logged."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return raw_token, token_hash


def hash_reset_token(raw_token):
    """Used to look up a presented token: hash it the same way and compare hashes in SQL — the
    raw token from the URL is never used directly in a query, so it never appears in a query log
    verbatim either."""
    return hashlib.sha256((raw_token or "").encode("utf-8")).hexdigest()


def is_reset_request_rate_limited(email):
    key = f"reset:{_rate_limit_key(email)}"
    now = time.time()
    attempts = [t for t in _RESET_REQUEST_ATTEMPTS.get(key, []) if now - t < RESET_REQUEST_WINDOW_SECONDS]
    _RESET_REQUEST_ATTEMPTS[key] = attempts
    return len(attempts) >= RESET_REQUEST_MAX_ATTEMPTS


def record_reset_request(email):
    key = f"reset:{_rate_limit_key(email)}"
    _RESET_REQUEST_ATTEMPTS.setdefault(key, []).append(time.time())


def hash_password(plain_password):
    from werkzeug.security import generate_password_hash
    return generate_password_hash(plain_password)


def verify_password(password_hash, plain_password):
    from werkzeug.security import check_password_hash
    return check_password_hash(password_hash, plain_password)


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def login_user(user_row):
    session.clear()
    session["user_id"] = user_row["id"]
    session["role"] = user_row["role"]
    session.permanent = True


def logout_user():
    session.clear()


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                abort(401)
            return redirect(url_for("auth.login_page"))
        # Stale-session bug fix (white-screen investigation, found while auditing the same class
        # of issue elsewhere): session.get("user_id") being truthy only proves a value is cached
        # in the signed cookie — it does NOT prove that user still exists in the database (e.g.
        # the account was deleted, or the database was reset/restored to an earlier point while a
        # browser kept an old cookie — plausible on a fresh/ephemeral dev database, and not
        # impossible in production either). Every protected view in this file eventually calls
        # current_user() itself and uses the result WITHOUT a None-check (e.g. `admin["id"]`),
        # which would otherwise crash with an unhandled TypeError. Checking here, once, means
        # every view downstream of this decorator can keep assuming current_user() is never None.
        if current_user() is None:
            session.clear()
            if request.path.startswith("/api/"):
                abort(401)
            return redirect(url_for("auth.login_page"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                abort(401)
            return redirect(url_for("auth.login_page"))
        # Same stale-session fix as login_required above — session.get("role") is also just a
        # cached cookie value from login time, not re-verified against the database on every
        # request. Use current_user()'s real DB-backed role instead, and treat a missing user the
        # same as "not logged in" rather than letting `admin["id"]` crash later in the view.
        user = current_user()
        if user is None:
            session.clear()
            if request.path.startswith("/api/"):
                abort(401)
            return redirect(url_for("auth.login_page"))
        if user["role"] != "KILAS_ADMIN":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def require_business_access(business_id, user=None):
    """Returns the business row if the current session (or explicitly-passed `user`) may access
    it, else raises 404 (NEVER 403 — a 403 would confirm the business_id exists, which is itself
    an information leak for an IDOR probe; a CLIENT_OWNER probing another tenant's id should see
    the same "not found" response as a genuinely nonexistent id).

    KILAS_ADMIN can access any business. CLIENT_OWNER must have a business_memberships row.
    """
    user = user or current_user()
    if user is None:
        abort(401)

    business = db.query_one("SELECT * FROM businesses WHERE id = ?", (business_id,))
    if business is None:
        abort(404)

    if user["role"] == "KILAS_ADMIN":
        return business

    membership = db.query_one(
        "SELECT * FROM business_memberships WHERE business_id = ? AND user_id = ?",
        (business_id, user["id"]),
    )
    if membership is None:
        abort(404)
    return business
