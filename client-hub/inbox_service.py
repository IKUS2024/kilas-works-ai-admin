"""Tenant-safe CS Inbox helpers for Kilas Works Client Hub.

This module intentionally reuses the production bot's existing shared `messages` and
`customer_profiles` tables. Tenant chat history is already scoped by app.py as
`T<business_id>:<customer_phone>`, so every read/write here always includes the exact tenant
prefix and can never fall back to Kilas Works' own unscoped conversation.

Manual CS replies are only allowed while HUMAN_TAKEOVER is active and while the customer's last
inbound message is still inside a conservative 23-hour WhatsApp customer-service window. Outside
that window a message template is required; this module deliberately refuses to fake a free-text
send that Meta would reject with re-engagement error 131047.
"""
from datetime import datetime, timezone
import os

import requests

import db
import repo
import wa_takeover_service
import wa_inbox_shared

WHATSAPP_24H_SAFETY_HOURS = wa_inbox_shared.WHATSAPP_24H_SAFETY_HOURS
MAX_MANUAL_MESSAGE_CHARS = wa_inbox_shared.MAX_MANUAL_MESSAGE_CHARS

normalize_customer_phone = wa_inbox_shared.normalize_customer_phone
_coerce_datetime = wa_inbox_shared.coerce_datetime


def _scoped_number(business_id, customer_phone):
    return f"T{int(business_id)}:{customer_phone}"


def _prefix(business_id):
    return f"T{int(business_id)}:"


def list_conversations(business_id, limit_messages=1500):
    """Return one row per customer for THIS business, newest first.

    The shared bot DB can contain Kilas Works + many tenant conversations. We only query keys with
    this exact tenant prefix, then strip the prefix for display. If the bot message table has not
    been initialized yet, return an empty inbox rather than breaking Client Hub.
    """
    prefix = _prefix(business_id)
    try:
        rows = db.query_all(
            "SELECT id, number, role, content, created_at FROM messages "
            "WHERE number LIKE ? AND mode = 'customer' ORDER BY id DESC LIMIT ?",
            (prefix + "%", int(limit_messages)),
        )
    except Exception:
        return []

    try:
        profile_rows = db.query_all(
            "SELECT number, name FROM customer_profiles WHERE number LIKE ?",
            (prefix + "%",),
        )
    except Exception:
        profile_rows = []
    names = {row["number"]: row.get("name") for row in profile_rows}

    try:
        takeover_rows = wa_takeover_service.list_takeover_conversations_for_business(business_id)
    except Exception:
        takeover_rows = []
    modes = {row["customer_phone"]: row["mode"] for row in takeover_rows}

    seen = set()
    conversations = []
    for row in rows:
        scoped = row["number"]
        if not scoped.startswith(prefix):
            continue
        phone = scoped[len(prefix):]
        if phone in seen:
            continue
        seen.add(phone)
        conversations.append({
            "customer_phone": phone,
            "customer_name": names.get(scoped),
            "last_role": row.get("role"),
            "last_message": row.get("content") or "",
            "last_message_at": row.get("created_at"),
            "mode": modes.get(phone, "AI_ACTIVE"),
        })
    return conversations


def customer_exists(business_id, customer_phone):
    phone = normalize_customer_phone(customer_phone)
    if not phone:
        return False
    try:
        row = db.query_one(
            "SELECT id FROM messages WHERE number = ? AND mode = 'customer' LIMIT 1",
            (_scoped_number(business_id, phone),),
        )
        return bool(row)
    except Exception:
        return False


def get_thread(business_id, customer_phone, limit=120):
    phone = normalize_customer_phone(customer_phone)
    if not phone:
        return []
    try:
        rows = db.query_all(
            "SELECT id, role, content, created_at FROM messages "
            "WHERE number = ? AND mode = 'customer' ORDER BY id DESC LIMIT ?",
            (_scoped_number(business_id, phone), int(limit)),
        )
    except Exception:
        return []
    rows.reverse()
    return rows


def get_customer_name(business_id, customer_phone):
    phone = normalize_customer_phone(customer_phone)
    if not phone:
        return None
    try:
        row = db.query_one(
            "SELECT name FROM customer_profiles WHERE number = ?",
            (_scoped_number(business_id, phone),),
        )
        return row.get("name") if row else None
    except Exception:
        return None


def get_last_customer_inbound_at(business_id, customer_phone):
    phone = normalize_customer_phone(customer_phone)
    if not phone:
        return None
    try:
        row = db.query_one(
            "SELECT created_at FROM messages WHERE number = ? AND mode = 'customer' AND role = 'user' "
            "ORDER BY id DESC LIMIT 1",
            (_scoped_number(business_id, phone),),
        )
    except Exception:
        return None
    return _coerce_datetime(row.get("created_at")) if row else None


def freeform_window_status(business_id, customer_phone, now=None):
    last_inbound = get_last_customer_inbound_at(business_id, customer_phone)
    return wa_inbox_shared.compute_freeform_window_status(last_inbound, now=now)


def _tenant_channel(business_id):
    business = repo.get_business(business_id)
    if not business or business.get("status") != "ACTIVE":
        return None, "business_not_active"

    cfg = repo.get_whatsapp_config(business_id) or {}
    if cfg.get("connection_status") != "CONNECTED" or not cfg.get("phone_number_id"):
        return None, "whatsapp_not_connected"

    credentials_reference = (cfg.get("credentials_reference") or "").strip()
    if credentials_reference:
        access_token = (os.environ.get(credentials_reference) or "").strip()
        if not access_token:
            return None, "tenant_credentials_unavailable"
    else:
        access_token = (os.environ.get("WHATSAPP_ACCESS_TOKEN") or "").strip()
        if not access_token:
            return None, "default_whatsapp_credentials_unavailable"

    return {
        "phone_number_id": str(cfg["phone_number_id"]),
        "access_token": access_token,
    }, None


def send_manual_reply(business_id, customer_phone, message_text):
    """Send one human-CS free-text message through THIS tenant's validated WA channel.

    Returns (ok, reason). It never logs or returns an access token and never falls back to Kilas
    Works' own phone-number-id if this tenant channel cannot be resolved.
    """
    phone = normalize_customer_phone(customer_phone)
    text = (message_text or "").strip()
    if not phone:
        return False, "invalid_customer_phone"
    if not text:
        return False, "empty_message"
    if len(text) > MAX_MANUAL_MESSAGE_CHARS:
        return False, "message_too_long"
    if not customer_exists(business_id, phone):
        return False, "customer_not_found"

    try:
        mode = wa_takeover_service.get_state(business_id, phone)
    except Exception:
        # Fail safe: if takeover state cannot be verified, do not send from the human inbox.
        return False, "takeover_state_unavailable"
    if mode != "HUMAN_TAKEOVER":
        return False, "human_takeover_required"

    window = freeform_window_status(business_id, phone)
    if not window["allowed"]:
        return False, window["reason"]

    channel, channel_err = _tenant_channel(business_id)
    if not channel:
        return False, channel_err

    graph_version = (os.environ.get("META_GRAPH_API_VERSION") or "v21.0").strip()
    url = f"https://graph.facebook.com/{graph_version}/{channel['phone_number_id']}/messages"
    headers = {
        "Authorization": f"Bearer {channel['access_token']}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": text},
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
    except Exception:
        return False, "meta_request_failed"
    if not (200 <= resp.status_code < 300):
        return False, f"meta_http_{resp.status_code}"

    # Keep AI context honest: a human reply is still what the customer saw from the business, so
    # store the exact visible text as an assistant-side message in the same tenant-scoped history.
    try:
        db.execute(
            "INSERT INTO messages (number, mode, role, content) VALUES (?, 'customer', 'assistant', ?)",
            (_scoped_number(business_id, phone), text),
        )
    except Exception:
        # The WhatsApp send already succeeded. Do not report the send as failed merely because the
        # history write failed; return a distinct success reason so the route can audit it.
        return True, "sent_history_write_failed"
    return True, "sent"


def send_template_reply(business_id, customer_phone, params=None):
    """Approved WhatsApp template send — the "Kirim Template & Lanjutkan" action for a
    conversation whose 24h customer-service window has expired (Section 4/5 of the request).
    Deliberately allowed to fire EVEN WHEN freeform_window_status() reports "not allowed" — that is
    exactly the situation an approved template exists to handle. Still requires HUMAN_TAKEOVER to
    be active, same as send_manual_reply().

    TEMPLATE-SCOPED PER TENANT: the approved template name/language is resolved via
    wa_inbox_shared.resolve_reengagement_template_config_for_tenant() — THIS tenant's own override
    (repo.get_whatsapp_config(business_id).reengagement_template_name/_language, see migration
    0018) first, falling back to the global WHATSAPP_REENGAGEMENT_TEMPLATE_NAME/_LANGUAGE env vars
    only if this tenant has none configured. A tenant is never forced to share the same approved
    template name as any other tenant or as Kilas Works' own platform inbox.

    Uses the SAME direct-Graph-API transport as send_manual_reply() (Client Hub already holds this
    tenant's own token) — only the payload shape differs (built by
    wa_inbox_shared.build_template_message_payload() instead of a free-text body)."""
    phone = normalize_customer_phone(customer_phone)
    if not phone:
        return False, "invalid_customer_phone"
    if not customer_exists(business_id, phone):
        return False, "customer_not_found"

    try:
        mode = wa_takeover_service.get_state(business_id, phone)
    except Exception:
        return False, "takeover_state_unavailable"
    if mode != "HUMAN_TAKEOVER":
        return False, "human_takeover_required"

    tenant_config_row = repo.get_whatsapp_config(business_id)
    template_name, language_code = wa_inbox_shared.resolve_reengagement_template_config_for_tenant(
        tenant_config_row, os.environ.get,
    )
    if not template_name:
        return False, "reengagement_template_not_configured"

    channel, channel_err = _tenant_channel(business_id)
    if not channel:
        return False, channel_err

    graph_version = (os.environ.get("META_GRAPH_API_VERSION") or "v21.0").strip()
    url = f"https://graph.facebook.com/{graph_version}/{channel['phone_number_id']}/messages"
    headers = {
        "Authorization": f"Bearer {channel['access_token']}",
        "Content-Type": "application/json",
    }
    payload = wa_inbox_shared.build_template_message_payload(phone, template_name, language_code, params)
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
    except Exception:
        return False, "meta_request_failed"
    if not (200 <= resp.status_code < 300):
        return False, f"meta_http_{resp.status_code}"

    try:
        db.execute(
            "INSERT INTO messages (number, mode, role, content) VALUES (?, 'customer', 'assistant', ?)",
            (_scoped_number(business_id, phone), f"[Template: {template_name}]"),
        )
    except Exception:
        return True, "sent_history_write_failed"
    return True, "sent"
