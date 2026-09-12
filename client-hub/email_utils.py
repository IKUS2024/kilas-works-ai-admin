"""Password-reset delivery. Configure SMTP_HOST/PORT/USERNAME/PASSWORD and RESET_EMAIL_FROM.
Production (APP_ENV or CLIENT_HUB_ENV, or Render) uses a bounded background queue so SMTP
latency does not reveal account existence. PUBLIC_APP_BASE_URL must be an HTTPS origin.
Delivery is best effort; missing config, queue saturation and provider failure never expose a
recipient or reset token in logs, and never mean successful delivery to the user.
"""
import os
from runtime_environment import is_production
import smtplib
import ssl
import queue
import threading
from urllib.parse import urlsplit
from email.message import EmailMessage


def _is_production():
    return is_production()


def build_reset_url(fallback_external_url, token):
    """Business Hub V2 Production Integration requirement: the reset link must always point at
    https://app.kilasworks.id in production, not whatever Host header a proxy happened to forward
    for this particular request. If PUBLIC_APP_BASE_URL is set (do this in Render), it always wins.
    If it's unset (local dev, or this sandbox), fall back to the Flask-computed external URL
    (`fallback_external_url`, e.g. from `url_for(..., _external=True)`) so local testing keeps
    working exactly as before this change without needing the env var set."""
    base_url = (os.environ.get("PUBLIC_APP_BASE_URL") or "").strip().rstrip("/")
    if _is_production():
        parsed = urlsplit(base_url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('production_reset_base_url_required')
    if not base_url:
        return fallback_external_url
    return f"{base_url}/reset-password/{token}"


def _send_password_reset_email(to_email, reset_url):
    """Returns True if a real email was handed off to an SMTP server, False otherwise (dev-mode
    missing configuration or production queueing both return False — callers must NOT treat False
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
            server.starttls(context=ssl.create_default_context())
            server.login(username, password)
            server.send_message(msg)
        return True

    if _is_production():
        print("EMAIL: SMTP not configured — password reset link could not be emailed. "
              "Set SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD/RESET_EMAIL_FROM to enable delivery.")
        return False

    print("EMAIL: SMTP not configured — password reset delivery unavailable.")
    return False


def _deliver_password_reset_email(to_email, reset_url):
    try:
        return _send_password_reset_email(to_email, reset_url)
    except Exception as exc:
        # SMTP exceptions can embed addresses, credentials and message text.
        print("EMAIL: password reset delivery failed; exception_type=" + type(exc).__name__)
        return False


_mail_queue = queue.Queue(maxsize=64)
_mail_worker_lock = threading.Lock()
_mail_workers_started = False

def _mail_worker():
    while True:
        recipient, link = _mail_queue.get()
        try:
            _deliver_password_reset_email(recipient, link)
        finally:
            _mail_queue.task_done()

def send_password_reset_email(to_email, reset_url):
    if not _is_production():
        return _deliver_password_reset_email(to_email, reset_url)
    if not all(os.environ.get(k) for k in ('SMTP_HOST', 'SMTP_USERNAME', 'SMTP_PASSWORD')):
        print('EMAIL: password reset delivery unavailable; SMTP not configured')
        return False
    # SMTP latency/outages must not expose account existence through HTTP response timing.
    global _mail_workers_started
    with _mail_worker_lock:
        if not _mail_workers_started:
            for _ in range(2):
                threading.Thread(target=_mail_worker, daemon=True).start()
            _mail_workers_started = True
    try:
        _mail_queue.put_nowait((to_email, reset_url))
    except queue.Full:
        print('EMAIL: password reset delivery unavailable; queue full')
    # Queuing is never represented as successful delivery.
    return False
