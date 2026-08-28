import re
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, session

import repo
import security
import email_utils

auth_bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


@auth_bp.route("/register", methods=["GET", "POST"])
def register_page():
    if request.method == "GET":
        return render_template("register.html")

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    full_name = (request.form.get("full_name") or "").strip()

    if not EMAIL_RE.match(email):
        flash("Email tidak valid.", "error")
        return render_template("register.html", email=email, full_name=full_name)
    if len(password) < 8:
        flash("Password minimal 8 karakter.", "error")
        return render_template("register.html", email=email, full_name=full_name)
    if repo.get_user_by_email(email):
        flash("Email sudah terdaftar. Coba login.", "error")
        return render_template("register.html", email=email, full_name=full_name)

    password_hash = security.hash_password(password)
    user_id = repo.create_user(email, password_hash, role="CLIENT_OWNER", full_name=full_name or None)
    user = repo.get_user_by_email(email)
    security.login_user(user)
    return redirect(url_for("client.dashboard"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "GET":
        return render_template("login.html")

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    if security.is_login_rate_limited(email):
        flash("Terlalu banyak percobaan login gagal. Coba lagi dalam beberapa menit.", "error")
        return render_template("login.html", email=email)

    user = repo.get_user_by_email(email)

    if not user or not security.verify_password(user["password_hash"], password):
        security.record_failed_login(email)
        flash("Email atau password salah.", "error")
        return render_template("login.html", email=email)

    security.clear_login_attempts(email)
    security.login_user(user)
    if user["role"] == "KILAS_ADMIN":
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("client.dashboard"))


@auth_bp.route("/logout")
def logout_page():
    security.logout_user()
    return redirect(url_for("auth.login_page"))


# ---------------------------------------------------------------------------
# Forgot / reset password (Business Hub V2, Phase A — see security.py's docstring above the
# reset-token helpers for the full design rationale: hashed tokens, 30-minute expiry, single use,
# rate limited, and the response is IDENTICAL whether or not the email exists.)
# ---------------------------------------------------------------------------

_GENERIC_RESET_MESSAGE = (
    "Kalau email itu terdaftar di Kilas Works Business Hub, kami sudah mengirim link reset "
    "password ke email tersebut. Cek juga folder spam kalau belum masuk dalam beberapa menit."
)


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password_page():
    if request.method == "GET":
        return render_template("forgot_password.html")

    email = (request.form.get("email") or "").strip().lower()

    if security.is_reset_request_rate_limited(email):
        # Deliberately still the generic message — a rate-limit-specific message would itself leak
        # information (confirms *something* about that email being requested a lot).
        flash(_GENERIC_RESET_MESSAGE, "success")
        return render_template("forgot_password.html", email=email)

    security.record_reset_request(email)

    if EMAIL_RE.match(email):
        user = repo.get_user_by_email(email)
        if user is not None:
            raw_token, token_hash = security.generate_reset_token()
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=security.RESET_TOKEN_TTL_SECONDS)).isoformat()
            requested_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
            repo.create_password_reset_token(user["id"], token_hash, expires_at, requested_ip)
            reset_url = email_utils.build_reset_url(
                url_for("auth.reset_password_page", token=raw_token, _external=True), raw_token,
            )
            email_utils.send_password_reset_email(user["email"], reset_url)
            repo.write_audit_no_business(user["id"], "PASSWORD_RESET_REQUESTED", f"ip={requested_ip}")
        # else: user is None — say nothing different. Same generic message either way, below.

    # ALWAYS the same message, same status code, same template, regardless of whether the email
    # matched a real account — this is the "do not expose whether an email exists" requirement.
    flash(_GENERIC_RESET_MESSAGE, "success")
    return render_template("forgot_password.html", email="")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password_page(token):
    token_hash = security.hash_reset_token(token)
    reset_row = repo.get_valid_reset_token(token_hash, _now_iso())

    if reset_row is None:
        # Same wording whether the token never existed, already expired, or was already used —
        # no need to distinguish for the user, and distinguishing would leak state to anyone who
        # found/guessed a stale link.
        flash("Link reset password ini tidak valid atau sudah kedaluwarsa. Silakan minta link baru.", "error")
        return redirect(url_for("auth.forgot_password_page"))

    if request.method == "GET":
        return render_template("reset_password.html", token=token)

    new_password = request.form.get("password") or ""
    confirm_password = request.form.get("confirm_password") or ""

    if len(new_password) < 8:
        flash("Password minimal 8 karakter.", "error")
        return render_template("reset_password.html", token=token)
    if new_password != confirm_password:
        flash("Konfirmasi password tidak cocok.", "error")
        return render_template("reset_password.html", token=token)

    now = _now_iso()
    user = repo.get_user_by_id(reset_row["user_id"])
    repo.update_user_password(user["id"], security.hash_password(new_password))
    repo.mark_reset_token_used(reset_row["id"], now)
    # Burn any other still-valid reset links for this user too (e.g. requested twice) so an old
    # email in an inbox can't be used after the password has already changed.
    repo.invalidate_all_reset_tokens_for_user(user["id"], now)
    repo.write_audit_no_business(user["id"], "PASSWORD_RESET_COMPLETED", "password reset via emailed link")

    flash("Password berhasil diubah. Silakan login dengan password baru.", "success")
    return redirect(url_for("auth.login_page"))
