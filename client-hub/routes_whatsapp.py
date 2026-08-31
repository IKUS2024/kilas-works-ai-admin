"""WhatsApp Embedded Signup entry/callback foundation for Kilas Works Client Hub.

This module intentionally does NOT exchange OAuth codes or persist Meta tokens yet.  It creates a
stable, HTTPS callback endpoint that can be registered in Meta while Tech Provider/App Review is
still pending, without ever logging OAuth query parameters or app secrets.  The actual token
exchange + WABA/phone binding will be enabled only after the Meta configuration ID/permissions are
approved and the post-signup flow is wired end-to-end.
"""
import os
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, request, session, url_for

import security

whatsapp_bp = Blueprint("whatsapp", __name__)


def _safe_meta_signup_url():
    """Return the configured Meta-hosted Embedded Signup URL only if it is HTTPS on facebook.com."""
    raw = (os.environ.get("META_EMBEDDED_SIGNUP_URL") or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "facebook.com" or host.endswith(".facebook.com")):
        return None
    return raw


@whatsapp_bp.route("/business/<int:business_id>/whatsapp/connect", methods=["GET"])
@security.login_required
def embedded_signup_start(business_id):
    """Owner-facing entry point for Meta-hosted Embedded Signup.

    The hosted URL itself lives in Render Environment rather than source control.  We remember the
    selected business in the signed Flask session so the callback can later bind the Meta result to
    the correct tenant once server-side code exchange is enabled.
    """
    user = security.current_user()
    business = security.require_business_access(business_id, user=user)

    if business.get("package") == "NONE":
        flash("Business ini belum menggunakan AI Admin.", "error")
        return redirect(url_for("client.dashboard"))
    if business.get("status") not in ("APPROVED", "ACTIVE", "SUSPENDED"):
        flash("Selesaikan onboarding dan approval sebelum menghubungkan WhatsApp.", "error")
        return redirect(url_for("client.dashboard"))

    signup_url = _safe_meta_signup_url()
    if not signup_url:
        flash("Konfigurasi Hubungkan WhatsApp belum tersedia. Hubungi Kilas Works.", "error")
        return redirect(url_for("client.dashboard"))

    session["wa_embedded_signup_business_id"] = int(business_id)
    return redirect(signup_url)


@whatsapp_bp.route("/whatsapp/embedded-signup/callback", methods=["GET"])
@security.login_required
def embedded_signup_callback():
    """Stable OAuth redirect URI for Meta Embedded Signup.

    Security notes:
    - Never prints/logs request.args because it can contain a short-lived OAuth code.
    - Does not accept or persist access tokens in the browser callback.
    - Until the server-side code exchange is implemented, an OAuth code is deliberately NOT used.
      This keeps the endpoint safe to register now without pretending onboarding is complete.
    """
    error = (request.args.get("error") or "").strip()
    error_description = (request.args.get("error_description") or "").strip()
    code_present = bool((request.args.get("code") or "").strip())
    pending_business_id = session.pop("wa_embedded_signup_business_id", None)

    if error:
        # Keep the user-facing message useful but bounded; never echo arbitrary long query text.
        detail = error_description[:240] if error_description else error[:120]
        flash(f"Koneksi WhatsApp dibatalkan atau gagal di Meta. {detail}", "error")
        return redirect(url_for("client.dashboard"))

    if code_present:
        # IMPORTANT: do not claim CONNECTED. The code exchange/binding step is not wired yet.
        if pending_business_id:
            # Re-check access so a stale/tampered session can never bind a Meta result to another tenant.
            security.require_business_access(int(pending_business_id), user=security.current_user())
        flash(
            "Meta berhasil kembali ke Kilas Works. Tahap login/izin selesai; penyambungan final "
            "akan aktif setelah pertukaran kode Meta dan binding nomor selesai di server.",
            "success",
        )
    else:
        flash("Kembali dari Meta. Belum ada data koneksi WhatsApp yang dapat diproses.", "error")

    return redirect(url_for("client.dashboard"))
