"""Minimal direct Meta Embedded Signup launcher for Kilas Works' own WhatsApp number.

This intentionally bypasses the tenant/business onboarding pipeline. It only:
1) opens Meta Embedded Signup in WhatsApp Business App / Coexistence mode,
2) verifies the one-time OAuth code server-side,
3) verifies the selected WABA + phone number belong to that grant,
4) subscribes this Meta app to the WABA webhook.

No access token, OAuth code, PIN, message content, or customer data is persisted.
"""
import hashlib
import hmac
import os
import re
import secrets
import time

from flask import Blueprint, jsonify, render_template, request, session

import security
import whatsapp_signup

meta_direct_bp = Blueprint("meta_direct", __name__, url_prefix="/admin/meta-whatsapp-direct")

_STATE_KEY = "_meta_direct_state"
_RESULT_KEY = "_meta_direct_result"
_STATE_TTL_SECONDS = 15 * 60


def _expected_phone_digits():
    value = (os.environ.get("META_DIRECT_EXPECTED_PHONE") or "").strip()
    return whatsapp_signup.normalize_phone_digits(value)


def _masked_phone(value):
    digits = whatsapp_signup.normalize_phone_digits(value)
    if not digits:
        return None
    return "***" + digits[-4:]


@meta_direct_bp.route("/")
@security.admin_required
def launcher():
    config = whatsapp_signup.platform_settings()
    state = secrets.token_urlsafe(32)
    session[_STATE_KEY] = {
        "state_hash": hashlib.sha256(state.encode()).hexdigest(),
        "expires_at": int(time.time()) + _STATE_TTL_SECONDS,
    }

    result = session.get(_RESULT_KEY)
    signup_config = {
        "appId": config["META_APP_ID"],
        "configId": config["META_EMBEDDED_SIGNUP_CONFIG_ID"],
        "version": config["version"],
        "state": state,
    }
    return render_template(
        "meta_whatsapp_direct.html",
        signup_config=signup_config,
        result=result,
        expected_masked=_masked_phone(os.environ.get("META_DIRECT_EXPECTED_PHONE")),
    )


@meta_direct_bp.route("/complete", methods=["POST"])
@security.admin_required
def complete():
    if not request.is_json or not request.content_length or request.content_length > 8192:
        return jsonify(error="Payload koneksi tidak valid."), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Payload koneksi tidak valid."), 400

    required = {"state", "code", "waba_id", "phone_number_id"}
    if set(data) != required:
        return jsonify(error="Payload koneksi tidak valid."), 400

    saved = session.pop(_STATE_KEY, None)
    state = data.get("state")
    if (
        not isinstance(saved, dict)
        or not isinstance(state, str)
        or len(state) > 128
        or int(saved.get("expires_at") or 0) <= int(time.time())
        or not hmac.compare_digest(
            saved.get("state_hash") or "",
            hashlib.sha256(state.encode()).hexdigest(),
        )
    ):
        return jsonify(error="Sesi Meta sudah kedaluwarsa. Muat ulang halaman dan coba lagi."), 400

    code = data.get("code")
    waba_id = str(data.get("waba_id") or "").strip()
    phone_number_id = data.get("phone_number_id")
    if phone_number_id is not None:
        phone_number_id = str(phone_number_id).strip()

    if (
        not isinstance(code, str)
        or not 1 <= len(code) <= 4096
        or not re.fullmatch(r"\d{1,32}", waba_id)
        or (phone_number_id is not None and not re.fullmatch(r"\d{1,32}", phone_number_id))
    ):
        return jsonify(error="Data Meta tidak valid."), 400

    config = whatsapp_signup.platform_settings()
    graph = whatsapp_signup.Graph(config)

    try:
        exchanged = graph.call(
            "GET",
            "oauth/access_token",
            params={
                "client_id": config["META_APP_ID"],
                "client_secret": config["WHATSAPP_APP_SECRET"],
                "code": code,
            },
        )
        customer_token = exchanged.get("access_token")
        if not isinstance(customer_token, str) or not customer_token:
            raise whatsapp_signup.SignupError("meta_token_missing")

        debug = graph.call(
            "GET",
            "debug_token",
            config["META_APP_ID"] + "|" + config["WHATSAPP_APP_SECRET"],
            params={"input_token": customer_token},
        ).get("data", {})

        targets = {
            str(target)
            for scope in debug.get("granular_scopes", [])
            if scope.get("scope") == "whatsapp_business_management"
            for target in scope.get("target_ids", [])
        }
        if (
            debug.get("is_valid") is not True
            or str(debug.get("app_id")) != config["META_APP_ID"]
            or waba_id not in targets
        ):
            raise whatsapp_signup.SignupError("customer_grant_mismatch")

        rows = graph.list_rows(
            waba_id + "/phone_numbers",
            customer_token,
            "id,display_phone_number,status,is_on_biz_app,platform_type",
        )

        expected = _expected_phone_digits()
        matches = []
        for row in rows:
            candidate_id = str((row or {}).get("id") or "")
            if not re.fullmatch(r"\d{1,32}", candidate_id):
                continue
            if phone_number_id and candidate_id != phone_number_id:
                continue
            digits = whatsapp_signup.normalize_phone_digits((row or {}).get("display_phone_number"))
            if expected and digits != expected:
                continue
            if (row or {}).get("is_on_biz_app") is not True:
                continue
            matches.append(row)

        if len(matches) != 1:
            raise whatsapp_signup.SignupError(
                "coexistence_phone_ambiguous" if len(matches) > 1 else "coexistence_phone_missing"
            )

        selected = matches[0]
        selected_id = str(selected["id"])
        if selected.get("status") != "CONNECTED":
            raise whatsapp_signup.SignupError("coexistence_not_ready")

        # Required for webhook delivery. This is the only Meta mutation in the direct launcher.
        graph.success(waba_id + "/subscribed_apps", customer_token, {})

        safe_result = {
            "waba_id": waba_id,
            "phone_number_id": selected_id,
            "display_phone_masked": _masked_phone(selected.get("display_phone_number")),
            "status": selected.get("status"),
            "platform_type": selected.get("platform_type"),
        }
        session[_RESULT_KEY] = safe_result
        print(
            "META_DIRECT_COEXISTENCE_READY "
            f"waba_id={waba_id} phone_number_id={selected_id} status={selected.get('status')}"
        )
        return jsonify(status="ready", result=safe_result), 200

    except whatsapp_signup.SignupError as exc:
        reason = str(exc)
        print("META_DIRECT_COEXISTENCE_FAILED reason=" + reason)
        messages = {
            "customer_grant_mismatch": "Izin Meta belum mencakup WABA yang dipilih.",
            "coexistence_phone_missing": (
                "Meta belum mengembalikan nomor WhatsApp Business App yang cocok. "
                "Pastikan flow Coexistence diselesaikan sampai akhir."
            ),
            "coexistence_phone_ambiguous": "Ada lebih dari satu nomor yang cocok. Pilih satu nomor saja di Meta.",
            "coexistence_not_ready": "Nomor belum berstatus CONNECTED di Coexistence. Selesaikan pairing di Meta/HP.",
            "meta_token_missing": "Meta tidak mengembalikan token onboarding yang valid.",
        }
        return jsonify(error=messages.get(reason, "Meta belum menyelesaikan Coexistence."), reason=reason), 400
