"""Kilas Works Client Hub — self-service multi-tenant AI Admin onboarding, V1.

This is a FULLY SEPARATE Flask application from ../app.py (the production WhatsApp bot). It has
its own entrypoint, own database file, own requirements, and is meant to be deployed as its own
Render service (or run standalone) at app.kilasworks.id. The production bot runs completely
unmodified and unaffected by anything in this folder — see the final report for exactly how the
two would eventually connect (tenant_config_service.py), which is NOT wired up yet in this cycle.

Run locally:
    cd client-hub
    export SECRET_KEY="dev-only-change-me"
    export ANTHROPIC_API_KEY="..."   # optional locally; AI features degrade gracefully without it
    python3 app.py

Run locally against Postgres instead of SQLite:
    export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
    python3 app.py
"""
import os

from flask import Flask, redirect, url_for, session, request, abort, current_app

import db
import security
from routes_auth import auth_bp
from routes_client import client_bp
from routes_admin import admin_bp

# Requests that carry state-changing verbs but are never form/browser submissions (JSON APIs) are
# exempted from the form-field CSRF check below and instead must carry an X-CSRF-Token header —
# see templates/simulate.html for the one place in this app that does so.
_CSRF_EXEMPT_JSON_PATHS_PREFIXES = ("/business/",)  # simulate/message + simulate/flag are under here


def create_app():
    app = Flask(__name__)

    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        if os.environ.get("CLIENT_HUB_ENV") == "production":
            raise RuntimeError(
                "SECRET_KEY environment variable is required in production — refusing to start "
                "with an insecure default session-signing key."
            )
        secret_key = "dev-only-insecure-secret-key-do-not-use-in-production"
        print("WARNING: SECRET_KEY not set — using an insecure dev-only default. Set SECRET_KEY before deploying.")
    app.secret_key = secret_key

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("CLIENT_HUB_ENV") == "production",
        MAX_CONTENT_LENGTH=12 * 1024 * 1024,  # slightly above per-file cap, covers small multi-field posts
    )

    with app.app_context():
        # Startup diagnostics (Postgres production validation phase): print ONLY the backend name
        # and pass/fail status — never DATABASE_URL, never a username/password/host, never an API
        # key or token. This is deliberately the only place in the app that logs anything about the
        # DB connection at boot, so it's the one spot to audit for a leak.
        backend_label = "PostgreSQL" if db.BACKEND == "postgres" else "SQLite"
        print(f"Database backend: {backend_label}")
        try:
            db.get_connection()
            print("Database connection: OK")
        except Exception as e:
            # str(e) here is already sanitized by db.get_connection()'s own RuntimeError wrapping
            # for the Postgres path — see db.py. Re-raise so the app fails to boot rather than
            # silently serving with no working database.
            print(f"Database connection: FAILED ({e})")
            raise
        db.init_schema()
        print("Schema initialization: OK")

    app.register_blueprint(auth_bp)
    app.register_blueprint(client_bp)
    app.register_blueprint(admin_bp)

    # Make csrf_token() callable from any Jinja template without every route needing to pass it.
    app.jinja_env.globals["csrf_token"] = security.get_csrf_token

    @app.after_request
    def _set_security_headers(response):
        # Cheap, standard hardening headers (Phase 6) — no new dependency needed for this subset.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.before_request
    def _csrf_protect():
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None
        if current_app.config.get("TESTING") and not current_app.config.get("CLIENT_HUB_FORCE_CSRF_IN_TESTS"):
            # CSRF is exercised by dedicated tests (test_production_foundation.py) that flip
            # CLIENT_HUB_FORCE_CSRF_IN_TESTS on for that one check — every other test (including
            # the full V1 suite from the previous cycle, which predates CSRF and is not being
            # edited) keeps working unchanged, matching the "keep all existing tests passing"
            # instruction for this phase.
            return None
        if request.is_json:
            token = request.headers.get("X-CSRF-Token")
        else:
            token = request.form.get("csrf_token")
        if not security.validate_csrf_token(token):
            abort(400, description="Invalid or missing CSRF token. Reload the page and try again.")
        return None

    @app.route("/")
    def index():
        if session.get("user_id"):
            if session.get("role") == "KILAS_ADMIN":
                return redirect(url_for("admin.dashboard"))
            return redirect(url_for("client.dashboard"))
        return redirect(url_for("auth.login_page"))

    @app.route("/healthz")
    def healthz():
        return {"status": "ok", "service": "kilas-works-client-hub", "db_backend": db.BACKEND}, 200

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    # SECURITY (Phase 6): debug mode now defaults to OFF and must be explicitly opted into with
    # CLIENT_HUB_ENV=development — the previous default ("on unless CLIENT_HUB_ENV=='production'")
    # meant any deploy that forgot to set CLIENT_HUB_ENV at all would silently run with Flask's
    # interactive debugger (arbitrary code execution via the debugger console) exposed to the
    # internet. Opt-in is the safe default; opt-out was not.
    debug_mode = os.environ.get("CLIENT_HUB_ENV") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
