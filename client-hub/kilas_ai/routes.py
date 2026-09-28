"""Kilas AI account routes; the flag and role gate apply to every private action."""
import os
from flask import Blueprint, abort, redirect, render_template, session, url_for

import security

ai_bp = Blueprint("kilas_ai", __name__, url_prefix="/kilas-ai")


def enabled():
    return os.environ.get("KILAS_AI_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


@ai_bp.before_request
def require_access():
    if not enabled():
        abort(404)
    if not session.get("user_id"):
        return redirect(url_for("auth.login_page"))
    user = security.current_user()
    if not user or user["role"] != "CLIENT_OWNER":
        abort(404)


@ai_bp.get("")
def home():
    from . import store
    return render_template("kilas_ai/home.html", threads=store.list_threads(session["user_id"]))
