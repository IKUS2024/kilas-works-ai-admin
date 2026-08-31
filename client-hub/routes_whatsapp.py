"""WhatsApp Embedded Signup entry/callback foundation for Kilas Works Client Hub.

This module intentionally does NOT exchange OAuth codes or persist Meta tokens yet.  It creates a
stable, HTTPS callback endpoint that can be registered in Meta while Tech Provider/App Review is
still pending, without ever logging OAuth query parameters or app secrets.  The actual token
exchange + WABA/phone binding will be enabled only after the Meta configuration ID/permissions are
approved and the post-signup flow is wired end-to-end.
"""
from flask import Blueprint, flash, redirect, request, url_for

import security

whatsapp_bp = Blueprint("whatsapp", __name__)


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

    if error:
        # Keep the user-facing message useful but bounded; never echo arbitrary long query text.
        detail = error_description[:240] if error_description else error[:120]
        flash(f"Koneksi WhatsApp dibatalkan atau gagal di Meta. {detail}", "error")
        return redirect(url_for("client.dashboard"))

    if code_present:
        # IMPORTANT: do not claim CONNECTED. The code exchange/binding step is not wired yet.
        flash(
            "Meta berhasil kembali ke Kilas Works. Endpoint callback sudah aktif; penyambungan "
            "WhatsApp akan diselesaikan setelah konfigurasi Embedded Signup disetujui Meta.",
            "success",
        )
    else:
        flash("Kembali dari Meta. Belum ada data koneksi WhatsApp yang dapat diproses.", "error")

    return redirect(url_for("client.dashboard"))
