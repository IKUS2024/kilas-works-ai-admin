"""Outbound email — currently used only for password-reset links (Business Hub V2, Phase A).

HONESTY NOTE: this sandbox cannot send real email (no network access to any SMTP host), so this
module has been written carefully but never actually delivered a message from here. It is designed
so that plugging in a real provider later (Render supports outbound SMTP; SendGrid/Mailgun/SES are
all reachable via smtplib or their HTTP APIs) requires touching ONLY this file — every caller goes
through send_password_reset_email(), never smtplib directly.

CONFIGURATION: set these env vars to enable real delivery —
    SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, RESET_EMAIL_FROM
Also set PUBLIC_APP_BASE_URL=https://app.kilasworks.id in production (see build_reset_url() below)
so the reset link is always the real production domain, regardless of what Host header Render's
proxy happens to pass through for a given request.
If any of SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD is missing, this module does NOT attempt to send
mail (an unconfigured SMTP_HOST with no credentials would either crash or silently fail against a
real host) — instead:
  - in a non-production environment (CLIENT_HUB_ENV != "production"), it prints the reset link to
    stdout so a developer/admin can copy it manually during testing (clearly labeled DEV MODE).
  - in production, it logs (without the raw token) that email delivery is not configured, and
    returns False so the caller can decide how to surface that — see routes_auth.py.

SECURITY: the raw token appears in exactly one place outside of this call: the URL handed to the
user. It is never logged in production mode. In dev mode it is printed locally only, which is
already true of everything else than passes through a developer's own terminal during local runs.
"""
import os
import smtplib
from email.message import EmailMessage


def _is_production():
    return os.environ.get("CLIENT_HUB_ENV") == "production"


def build_reset_url(fallback_external_url, token):
    """Business Hub V2 Production Integration requirement: the reset link must always point at
    https://app.kilasworks.id in production, not whatever Host header a proxy happened to forward
    for this particular request. If PUBLIC_APP_BASE_URL is set (do this in Render), it always wins.
    If it's unset (local dev, or this sandbox), fall back to the Flask-computed external URL
    (`fallback_external_url`, e.g. from `url_for(..., _external=True)`) so local testing keeps
    working exactly as before this change without needing the env var set."""
    base_url = (os.environ.get("PUBLIC_APP_BASE_URL") or "").strip().rstrip("/")
    if not base_url:
        return fallback_external_url
    return f"{base_url}/reset-password/{token}"


def send_password_reset_email(to_email, reset_url):
    """Returns True if a real email was handed off to an SMTP server, False otherwise (dev-mode
    console print or production-without-config both return False — callers must NOT treat False
    as an error to show the user, since "do not reveal whether an email exists" already means the
    user-facing response is identical regardless of what happens here)."""
    host = os.environ.get("SMTP_HOST")
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    port = int(os.environ.get("SMTP_PORT", "587"))
    sender = os.environ.get("RESET_EMAIL_FROM") or username

    if host and username and password:
        msg = EmailMessage()
        msg["Subject"] = "Reset Password — Kilas Works Business Hub"
        msg["From"] = sender
        msg["To"] = to_email
        msg.set_content(
            "Halo,\n\n"
            "Kami menerima permintaan untuk mereset password akun Kilas Works Business Hub kamu.\n\n"
            "Klik link di bawah ini untuk membuat password baru. Link ini berlaku selama 30 menit "
            "dan hanya bisa digunakan satu kali:\n\n"
            f"{reset_url}\n\n"
            "Kalau kamu tidak merasa meminta reset password ini, kamu bisa abaikan email ini dengan "
            "aman — password akun kamu tidak akan berubah.\n\n"
            "Terima kasih,\n"
            "Tim Kilas Works\n"
            "app.kilasworks.id"
        )
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)
        return True

    if _is_production():
        print("EMAIL: SMTP not configured — password reset link could not be emailed. "
              "Set SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD/RESET_EMAIL_FROM to enable delivery.")
        return False

    # Dev/local mode only — never reached in production (see _is_production() branch above).
    print(f"DEV MODE — no SMTP configured. Password reset link for {to_email}:\n{reset_url}")
    return False
