import io
import os
import re
import secrets
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, send_file, abort

import repo
import security
import email_utils
import file_utils
import account_profile_service as account_profiles

auth_bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()



_OAUTH_STATE_TTL_SECONDS = 10 * 60
_OAUTH_PROVIDERS = ("google",)


def _oauth_config(provider):
    """Return public OAuth metadata without ever exposing provider secrets to templates/logs."""
    if provider == "google":
        return {
            "label": "Google",
            "client_id": (os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or "").strip(),
            "client_secret": (os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip(),
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        }
    return None\n\n\ndef _oauth_ready(provider):
    config = _oauth_config(provider)
    return bool(config and config["client_id"] and config["client_secret"])


def _oauth_callback_url(provider):
    path = url_for("auth.oauth_callback", provider=provider)
    base = (os.environ.get("PUBLIC_APP_BASE_URL") or "").strip().rstrip("/")
    return base + path if base else url_for("auth.oauth_callback", provider=provider, _external=True)


def _oauth_finish_login(email, full_name, provider):
    """Login/create a CLIENT_OWNER by provider-verified email without touching tenant/business data."""
    email = (email or "").strip().lower()
    full_name = (full_name or "").strip()[:100]
    if not EMAIL_RE.match(email):
        raise ValueError("oauth_email_missing")

    user = repo.get_user_by_email(email)
    created = False
    if user is None:
        # Social-login accounts still receive a random unusable password hash so the legacy
        # NOT-NULL users.password_hash contract remains untouched. The owner can later use the
        # existing Forgot Password flow to set a password if they want one.
        random_password = secrets.token_urlsafe(48)
        repo.create_user(
            email,
            security.hash_password(random_password),
            role="CLIENT_OWNER",
            full_name=full_name or email.split("@", 1)[0],
        )
        user = repo.get_user_by_email(email)
        created = True

    # Keep admin access on the stricter password-only path. Social OAuth is customer-facing.
    if user["role"] == "KILAS_ADMIN":
        raise PermissionError("admin_oauth_disabled")

    security.login_user(user)
    repo.write_audit_no_business(
        user["id"],
        "OAUTH_ACCOUNT_CREATED" if created else "OAUTH_LOGIN",
        f"provider={provider}",
    )
    if __import__("product_flow").intent(session.get("product_intent")):
        return redirect(url_for("products.continue_product"))
    return redirect(url_for("client.dashboard"))


@auth_bp.route("/oauth/<provider>")
def oauth_start(provider):
    provider = (provider or "").strip().lower()
    if provider not in _OAUTH_PROVIDERS:
        abort(404)
    config = _oauth_config(provider)
    if not _oauth_ready(provider):
        flash(
            f"Login dengan {config['label']} belum aktif. Gunakan email & password dulu.",
            "info",
        )
        return redirect(url_for("auth.login_page"))

    state = secrets.token_urlsafe(32)
    session[f"oauth_state_{provider}"] = {
        "value": state,
        "issued_at": int(time.time()),
    }
    redirect_uri = _oauth_callback_url(provider)

    query = urllib.parse.urlencode({
        "client_id": config["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        # Always show the Google account chooser, matching the expected mobile app flow.
        "prompt": "select_account",
    })
    return redirect(config["authorize_url"] + "?" + query)


@auth_bp.route("/oauth/<provider>/callback")
def oauth_callback(provider):
    provider = (provider or "").strip().lower()
    if provider not in _OAUTH_PROVIDERS:
        abort(404)
    config = _oauth_config(provider)
    saved = session.pop(f"oauth_state_{provider}", None) or {}
    supplied_state = request.args.get("state") or ""
    issued_at = int(saved.get("issued_at") or 0)
    if (
        not saved.get("value")
        or not supplied_state
        or not secrets.compare_digest(str(saved["value"]), supplied_state)
        or time.time() - issued_at > _OAUTH_STATE_TTL_SECONDS
    ):
        flash("Sesi login sosial tidak valid atau sudah kedaluwarsa. Coba lagi.", "error")
        return redirect(url_for("auth.login_page"))

    if request.args.get("error"):
        flash(f"Login dengan {config['label']} dibatalkan atau tidak disetujui.", "info")
        return redirect(url_for("auth.login_page"))

    code = request.args.get("code") or ""
    if not code or not _oauth_ready(provider):
        flash(f"Login dengan {config['label']} belum dapat diproses.", "error")
        return redirect(url_for("auth.login_page"))

    redirect_uri = _oauth_callback_url(provider)
    try:
        token_response = requests.post(
            config["token_url"],
            data={
                "code": code,
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=(5, 12),
            allow_redirects=False,
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        access_token = (token_payload.get("access_token") or "").strip()
        if not access_token:
            raise ValueError("oauth_access_token_missing")

        profile_response = requests.get(
            config["userinfo_url"],
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=(5, 12),
            allow_redirects=False,
        )
        profile_response.raise_for_status()
        profile = profile_response.json()
        if profile.get("email_verified") is not True:
            raise ValueError("google_email_not_verified")
        email = profile.get("email")
        name = profile.get("name")

        return _oauth_finish_login(email, name, provider)
    except PermissionError:
        flash("Akun admin Kilas tetap harus login menggunakan email & password.", "error")
    except Exception as exc:
        # Never log auth code, access token, provider response body, email, or client secret.
        print(f"OAUTH_LOGIN_FAILED provider={provider} error_type={type(exc).__name__}")
        flash(
            f"Login dengan {config['label']} belum berhasil. Coba lagi atau gunakan email & password.",
            "error",
        )
    return redirect(url_for("auth.login_page"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register_page():
    if request.method == "GET":
        return render_template("register.html")

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    full_name = (request.form.get("full_name") or "").strip()

    if not full_name:
        flash("Nama pemilik wajib diisi.", "error")
        return render_template("register.html", email=email, full_name=full_name)
    if len(full_name) > 100:
        flash("Nama pemilik terlalu panjang.", "error")
        return render_template("register.html", email=email, full_name=full_name)
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
    user_id = repo.create_user(email, password_hash, role="CLIENT_OWNER", full_name=full_name)
    user = repo.get_user_by_email(email)
    security.login_user(user)
    return redirect(url_for("products.continue_product") if __import__("product_flow").intent(session.get("product_intent")) else url_for("client.dashboard"))


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
    return redirect(url_for("products.continue_product") if __import__("product_flow").intent(session.get("product_intent")) else url_for("client.dashboard"))


@auth_bp.route("/logout")
def logout_page():
    security.logout_user()
    return redirect(url_for("auth.login_page"))


def _account_businesses(user):
    """Account-page projection only; never creates Finance businesses/branches or touches ledgers."""
    if user["role"] == "KILAS_ADMIN":
        return []
    import finance_branches as branches
    import finance_invoice_editor as invoice_editor

    result = []
    for raw in repo.list_businesses_for_user(user["id"]):
        business = dict(raw)
        business["business_email"] = repo.get_business_owner_email(business["id"]) or user["email"]
        business["profile"] = dict(repo.get_business_profile(business["id"]) or {})
        business["profile_photo"] = account_profiles.profile_asset_meta("BUSINESS", business["id"])
        finance_rows = []
        for raw_branch in branches.list_branches(
                business["id"], user["id"], workspace_type="BUSINESS"):
            if not raw_branch["is_active"]:
                continue
            branch = dict(raw_branch)
            with branches.scope(business["id"], branch["id"], user["id"]):
                defaults = invoice_editor.defaults(business["id"], user["id"])
            sender = dict(defaults.get("sender") or {})
            sender["email"] = business["business_email"]
            branch["invoice_sender"] = sender
            branch["invoice_payment"] = dict(defaults.get("payment") or {})
            finance_rows.append(branch)
        business["finance_branches"] = finance_rows
        result.append(business)
    return result


def _account_business_redirect():
    return redirect(url_for("auth.account_page") + "#business", code=303)


def _account_personal_redirect():
    return redirect(url_for("auth.account_page") + "#personal", code=303)


def _account_context(user):
    return {
        "user": user,
        "businesses": _account_businesses(user),
        "personal_profile": account_profiles.get_personal_profile(user["id"]),
        "personal_photo": account_profiles.profile_asset_meta("USER", user["id"]),
    }


def _serve_profile_asset(asset):
    if asset is None:
        abort(404)
    response = send_file(
        io.BytesIO(asset["content"]),
        mimetype=asset.get("mime_type") or "application/octet-stream",
    )
    response.headers["Cache-Control"] = "private, max-age=3600"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@auth_bp.route("/account/photo")
@security.login_required
def account_personal_photo():
    user = security.current_user()
    return _serve_profile_asset(account_profiles.profile_asset("USER", user["id"]))


@auth_bp.route("/account/business/<int:business_id>/photo")
@security.login_required
def account_business_photo(business_id):
    user = security.current_user()
    security.require_business_access(business_id, user=user)
    return _serve_profile_asset(account_profiles.profile_asset("BUSINESS", business_id))


@auth_bp.route("/account", methods=["GET", "POST"])
@security.login_required
def account_page():
    """Self-service personal/business identity, invoice metadata, photos and security."""
    user = security.current_user()
    context = _account_context(user)
    businesses = context["businesses"]
    if request.method == "GET":
        return render_template("account.html", **context, password_open=False)

    action = (request.form.get("action") or "").strip()
    if action == "profile":
        full_name = (request.form.get("full_name") or "").strip()
        if len(full_name) > 100:
            flash("Nama terlalu panjang.", "error")
            return render_template("account.html", **context, password_open=False), 400
        repo.update_user_profile(user["id"], full_name)
        repo.write_audit_no_business(user["id"], "ACCOUNT_PROFILE_UPDATED", "self-service profile name updated")
        flash("Nama akun berhasil diperbarui.", "success")
        return _account_personal_redirect()

    if action == "personal_profile":
        full_name = (request.form.get("full_name") or "").strip()
        if not full_name or len(full_name) > 100:
            flash("Nama pribadi wajib diisi dan maksimal 100 karakter.", "error")
            return _account_personal_redirect()
        try:
            account_profiles.save_personal_profile(user["id"], {
                "phone": request.form.get("phone"),
                "address": request.form.get("address"),
                "tax_id": request.form.get("tax_id"),
                "website": request.form.get("website"),
                "payment_method": request.form.get("payment_method"),
                "payment_bank_name": request.form.get("payment_bank_name"),
                "payment_account_number": request.form.get("payment_account_number"),
                "payment_account_name": request.form.get("payment_account_name"),
                "payment_instructions": request.form.get("payment_instructions"),
            })
        except ValueError:
            flash("Data pribadi belum valid. Periksa panjang isian lalu coba lagi.", "error")
            return _account_personal_redirect()
        repo.update_user_profile(user["id"], full_name)
        repo.write_audit_no_business(
            user["id"], "ACCOUNT_PERSONAL_INVOICE_PROFILE_UPDATED",
            "personal invoice profile updated; existing invoice snapshots unchanged")
        flash("Data invoice Pribadi diperbarui. Invoice baru akan memakai data terbaru.", "success")
        return _account_personal_redirect()

    if action in ("personal_photo", "business_photo"):
        upload = request.files.get("photo")
        if not upload or not upload.filename:
            flash("Pilih foto dulu.", "error")
            return _account_personal_redirect() if action == "personal_photo" else _account_business_redirect()
        raw = upload.stream.read(file_utils.MAX_IMAGE_UPLOAD_BYTES + 1)
        try:
            safe_name, mime_type = file_utils.validate_image_upload(upload.filename, raw)
        except file_utils.UploadRejected as error:
            flash(str(error), "error")
            return _account_personal_redirect() if action == "personal_photo" else _account_business_redirect()
        if action == "personal_photo":
            account_profiles.save_profile_photo(
                "USER", user["id"], safe_name, mime_type, raw, user["id"])
            repo.write_audit_no_business(
                user["id"], "ACCOUNT_PERSONAL_PHOTO_UPDATED", "personal profile photo updated")
            flash("Foto profil Pribadi diperbarui.", "success")
            return _account_personal_redirect()
        try:
            business_id = int(request.form.get("business_id") or "")
        except (TypeError, ValueError):
            flash("Bisnis tidak valid.", "error")
            return _account_business_redirect()
        security.require_business_access(business_id, user=user)
        account_profiles.save_profile_photo(
            "BUSINESS", business_id, safe_name, mime_type, raw, user["id"])
        repo.write_audit(
            user["id"], business_id, "ACCOUNT_BUSINESS_PHOTO_UPDATED",
            "business profile photo updated")
        flash("Foto profil bisnis diperbarui.", "success")
        return _account_business_redirect()

    if action == "business_identity":
        try:
            business_id = int(request.form.get("business_id") or "")
        except (TypeError, ValueError):
            flash("Bisnis tidak valid.", "error")
            return _account_business_redirect()
        business = security.require_business_access(business_id, user=user)
        name = (request.form.get("business_name") or "").strip()
        if not name or len(name) > 160:
            flash("Nama bisnis wajib diisi dan maksimal 160 karakter.", "error")
            return _account_business_redirect()
        repo.update_business_identity(business_id, name, user["id"])
        import finance_invoice_editor as invoice_editor
        import finance_service as finance
        invoice_sync_ok = True
        try:
            invoice_editor.sync_sender_identity(business_id, name, user["id"])
        except finance.FinanceError:
            # Renaming the account identity is still valid while Finance is read-only.
            # Existing issued invoices are snapshots and are intentionally untouched.
            invoice_sync_ok = False
        if business.get("package") != "NONE":
            repo.set_business_stale_if_done(business_id)
        flash(
            "Nama bisnis diperbarui. Invoice lama tetap memakai data saat diterbitkan."
            if invoice_sync_ok else
            "Nama bisnis diperbarui. Default invoice belum diubah karena Finance sedang read-only.",
            "success" if invoice_sync_ok else "info")
        return _account_business_redirect()

    if action == "business_branch":
        try:
            business_id = int(request.form.get("business_id") or "")
            branch_id = int(request.form.get("branch_id") or "")
        except (TypeError, ValueError):
            flash("Bisnis atau cabang tidak valid.", "error")
            return _account_business_redirect()
        business = security.require_business_access(business_id, user=user)

        import finance_branches as branches
        import finance_invoice_editor as invoice_editor
        import finance_service as finance

        try:
            branch = branches.get(business_id, branch_id, active=True, actor_user_id=user["id"])
        except finance.FinanceError:
            flash("Cabang Finance tidak tersedia.", "error")
            return _account_business_redirect()
        if branch.get("workspace_type") != "BUSINESS":
            flash("Data bisnis hanya dapat diubah pada cabang bisnis.", "error")
            return _account_business_redirect()

        branch_name = (request.form.get("branch_name") or "").strip()
        if not branch_name or len(branch_name) > 160:
            flash("Nama cabang wajib diisi dan maksimal 160 karakter.", "error")
            return _account_business_redirect()

        sender = {
            "name": business["business_name"],
            "address": (request.form.get("address") or "").strip(),
            "phone": (request.form.get("business_phone") or "").strip(),
            # Never trust a submitted email: business owner login email is canonical.
            "email": repo.get_business_owner_email(business_id) or user["email"],
            "tax_id": (request.form.get("tax_id") or "").strip(),
            "website": (request.form.get("website") or "").strip(),
        }
        payment = {
            "method": (request.form.get("payment_method") or "").strip(),
            "bank": (request.form.get("payment_bank_name") or "").strip(),
            "account_number": (request.form.get("payment_account_number") or "").strip(),
            "account_holder": (request.form.get("payment_account_name") or "").strip(),
            "instructions": (request.form.get("payment_instructions") or "").strip(),
        }
        if not sender["address"] or not sender["phone"]:
            flash("Alamat dan nomor telepon bisnis wajib diisi untuk data invoice.", "error")
            return _account_business_redirect()
        try:
            # Validate all lengths/shape before the first write.
            invoice_editor.clean_document(dict(
                sender=sender, payment=payment, recipient={"name": "-"}))
            with branches.scope(business_id, branch_id, user["id"]):
                branches.update_record(
                    business_id, "branch", branch_id, name=branch_name,
                    actor_user_id=user["id"])
                invoice_editor.save_defaults(
                    business_id, {"sender": sender, "payment": payment}, user["id"])
        except finance.FinanceError as error:
            message = {
                "branch_exists": "Nama cabang sudah digunakan.",
                "invoice_sender_required": "Alamat dan nomor telepon bisnis wajib diisi.",
            }.get(str(error), "Data bisnis belum valid. Periksa isian dan coba lagi.")
            flash(message, "error")
            return _account_business_redirect()

        # Preserve the legacy business-profile fallback from the default Finance branch.
        if branch["is_default"]:
            repo.upsert_business_profile(business_id, {
                "address": sender["address"],
                "business_phone": sender["phone"],
                "payment_bank_name": payment["bank"],
                "payment_account_number": payment["account_number"],
                "payment_account_name": payment["account_holder"],
                "payment_instructions": payment["instructions"],
            })
            if business.get("package") != "NONE":
                repo.set_business_stale_if_done(business_id)

        repo.write_audit(
            user["id"], business_id, "FINANCE_BUSINESS_PROFILE_UPDATED",
            "customer account business/invoice profile updated; ledger unchanged")
        flash("Data cabang dan invoice diperbarui. Invoice lama tidak berubah.", "success")
        return _account_business_redirect()

    if action == "password":
        current_password = request.form.get("current_password") or ""
        new_password = request.form.get("new_password") or ""
        confirm_password = request.form.get("confirm_password") or ""
        if not security.verify_password(user["password_hash"], current_password):
            flash("Password saat ini tidak cocok.", "error")
            return render_template("account.html", **_account_context(user), password_open=True), 400
        if len(new_password) < 8:
            flash("Password baru minimal 8 karakter.", "error")
            return render_template("account.html", user=user, businesses=businesses, password_open=True), 400
        if new_password == current_password:
            flash("Password baru harus berbeda dari password saat ini.", "error")
            return render_template("account.html", user=user, businesses=businesses, password_open=True), 400
        if new_password != confirm_password:
            flash("Konfirmasi password baru tidak cocok.", "error")
            return render_template("account.html", user=user, businesses=businesses, password_open=True), 400

        new_hash = security.hash_password(new_password)
        repo.update_user_password(user["id"], new_hash)

        # Read-after-write verification: success is shown only after the persisted DB hash really
        # authenticates the new password. This catches a storage/transaction regression instead of
        # telling the customer the password changed when it did not.
        saved_user = repo.get_user_by_id(user["id"])
        if not saved_user or not security.verify_password(saved_user["password_hash"], new_password):
            flash("Password belum berhasil disimpan. Coba lagi.", "error")
            return render_template("account.html", **_account_context(user), password_open=True), 500

        repo.invalidate_all_reset_tokens_for_user(user["id"], _now_iso())
        security.clear_login_attempts(user["email"])
        repo.write_audit_no_business(user["id"], "PASSWORD_CHANGED", "password changed and persistence verified")
        flash("Password berhasil diubah dan sudah aktif untuk login berikutnya.", "success")
        return redirect(url_for("auth.account_page"))

    flash("Aksi akun tidak dikenali.", "error")
    return redirect(url_for("auth.account_page"))


# ---------------------------------------------------------------------------
# Forgot / reset password (Business Hub V2, Phase A — see security.py's docstring above the
# reset-token helpers for the full design rationale: hashed tokens, 30-minute expiry, single use,
# rate limited, and the response is IDENTICAL whether or not the email exists.)
# ---------------------------------------------------------------------------

_GENERIC_RESET_MESSAGE = (
    "Kalau email itu terdaftar di Kilas Works Business Hub, permintaan link reset "
    "password akan diproses. Cek email dan folder spam; jika belum masuk, coba lagi nanti."
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
        return render_template("forgot_password.html", email="")

    security.record_reset_request(email)

    if EMAIL_RE.match(email):
        user = repo.get_user_by_email(email)
        if user is not None:
            raw_token, token_hash = security.generate_reset_token()
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=security.RESET_TOKEN_TTL_SECONDS)).isoformat()
            requested_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
            repo.create_password_reset_token(user["id"], token_hash, expires_at, requested_ip)
            try:
                reset_url = email_utils.build_reset_url(
                    url_for("auth.reset_password_page", token=raw_token, _external=True), raw_token,
                )
                email_utils.send_password_reset_email(user["email"], reset_url)
            except Exception as exc:
                print("EMAIL: reset delivery unavailable; exception_type=" + type(exc).__name__)
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
