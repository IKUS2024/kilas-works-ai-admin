"""Kilas Works' own WhatsApp inbox + human takeover helpers.

This is intentionally separate from tenant inbox_service.py.  Tenant conversations are stored as
T<business_id>:<customer_phone>; Kilas Works' own legacy bot stores plain numeric customer phones.
The admin inbox below only reads those plain-number rows, so a KILAS_ADMIN cannot accidentally mix a
client tenant's chats into the platform's own operational inbox.

The database remains an implementation detail. Humans read/reply through Client Hub or WhatsApp
Business; PostgreSQL is never presented as a chat viewer.
"""
from datetime import datetime, timezone
import os
import re
from urllib.parse import urlparse

import requests

import db

WHATSAPP_24H_SAFETY_HOURS = 23
MAX_MANUAL_MESSAGE_CHARS = 4096
_PHONE_RE = re.compile(r"^\d{6,20}$")


def normalize_customer_phone(raw):
    digits = re.sub(r"\D", "", raw or "")
    return digits if _PHONE_RE.match(digits) else None


def _coerce_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_platform_number_key(value):
    # Customer phone keys in the live bot are digits. Tenant keys are T<id>:<digits>.
    return bool(normalize_customer_phone(value)) and ":" not in str(value)


def get_state(customer_phone):
    phone = normalize_customer_phone(customer_phone)
    if not phone:
        raise ValueError("invalid_customer_phone")
    row = db.query_one(
        "SELECT mode FROM platform_wa_conversation_state WHERE customer_phone = ?",
        (phone,),
    )
    return row["mode"] if row else "AI_ACTIVE"


def _set_state(customer_phone, mode, actor_user_id=None):
    if mode not in ("AI_ACTIVE", "HUMAN_TAKEOVER"):
        raise ValueError("invalid_mode")
    phone = normalize_customer_phone(customer_phone)
    if not phone:
        raise ValueError("invalid_customer_phone")
    existing = db.query_one(
        "SELECT id FROM platform_wa_conversation_state WHERE customer_phone = ?",
        (phone,),
    )
    if existing is None:
        db.execute(
            "INSERT INTO platform_wa_conversation_state (customer_phone, mode, updated_by_user_id) VALUES (?, ?, ?)",
            (phone, mode, actor_user_id),
        )
    else:
        db.execute(
            (
                "UPDATE platform_wa_conversation_state SET mode = ?, updated_by_user_id = ?, updated_at = datetime('now') WHERE id = ?"
                if db.BACKEND == "sqlite" else
                "UPDATE platform_wa_conversation_state SET mode = ?, updated_by_user_id = ?, updated_at = now() WHERE id = ?"
            ),
            (mode, actor_user_id, existing["id"]),
        )


def start_human_takeover(customer_phone, actor_user_id=None):
    _set_state(customer_phone, "HUMAN_TAKEOVER", actor_user_id)


def return_to_ai(customer_phone, actor_user_id=None):
    _set_state(customer_phone, "AI_ACTIVE", actor_user_id)


def list_conversations(search=None, mode_filter=None, limit_messages=2000):
    """Newest-first Kilas Works conversations only; tenant-prefixed rows are excluded."""
    try:
        rows = db.query_all(
            "SELECT id, number, role, content, created_at FROM messages "
            "WHERE mode = 'customer' ORDER BY id DESC LIMIT ?",
            (int(limit_messages),),
        )
    except Exception:
        return []

    try:
        profile_rows = db.query_all("SELECT number, name FROM customer_profiles")
    except Exception:
        profile_rows = []
    names = {r["number"]: r.get("name") for r in profile_rows if _is_platform_number_key(r.get("number"))}

    try:
        state_rows = db.query_all("SELECT customer_phone, mode FROM platform_wa_conversation_state")
    except Exception:
        state_rows = []
    modes = {r["customer_phone"]: r["mode"] for r in state_rows}

    needle = (search or "").strip().lower()
    seen = set()
    out = []
    for row in rows:
        phone = str(row.get("number") or "")
        if not _is_platform_number_key(phone) or phone in seen:
            continue
        seen.add(phone)
        name = names.get(phone)
        mode = modes.get(phone, "AI_ACTIVE")
        if mode_filter in ("AI_ACTIVE", "HUMAN_TAKEOVER") and mode != mode_filter:
            continue
        if needle and needle not in phone.lower() and needle not in (name or "").lower() and needle not in (row.get("content") or "").lower():
            continue
        out.append({
            "customer_phone": phone,
            "customer_name": name,
            "last_role": row.get("role"),
            "last_message": row.get("content") or "",
            "last_message_at": row.get("created_at"),
            "mode": mode,
        })
    return out


def customer_exists(customer_phone):
    phone = normalize_customer_phone(customer_phone)
    if not phone:
        return False
    try:
        row = db.query_one(
            "SELECT id FROM messages WHERE number = ? AND mode = 'customer' LIMIT 1", (phone,)
        )
        return bool(row)
    except Exception:
        return False


def get_thread(customer_phone, limit=160):
    phone = normalize_customer_phone(customer_phone)
    if not phone:
        return []
    try:
        rows = db.query_all(
            "SELECT id, role, content, created_at FROM messages "
            "WHERE number = ? AND mode = 'customer' ORDER BY id DESC LIMIT ?",
            (phone, int(limit)),
        )
    except Exception:
        return []
    rows.reverse()
    return rows


def get_customer_name(customer_phone):
    phone = normalize_customer_phone(customer_phone)
    if not phone:
        return None
    try:
        row = db.query_one("SELECT name FROM customer_profiles WHERE number = ?", (phone,))
    except Exception:
        return None
    return row.get("name") if row else None


def get_last_customer_inbound_at(customer_phone):
    phone = normalize_customer_phone(customer_phone)
    if not phone:
        return None
    try:
        row = db.query_one(
            "SELECT created_at FROM messages WHERE number = ? AND mode = 'customer' AND role = 'user' "
            "ORDER BY id DESC LIMIT 1",
            (phone,),
        )
    except Exception:
        return None
    return _coerce_datetime(row.get("created_at")) if row else None


def freeform_window_status(customer_phone, now=None):
    last_inbound = get_last_customer_inbound_at(customer_phone)
    if last_inbound is None:
        return {"allowed": False, "reason": "no_customer_inbound", "last_inbound_at": None, "age_hours": None}
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age_hours = (now.astimezone(timezone.utc) - last_inbound).total_seconds() / 3600.0
    return {
        "allowed": age_hours < WHATSAPP_24H_SAFETY_HOURS,
        "reason": "ok" if age_hours < WHATSAPP_24H_SAFETY_HOURS else "outside_24h_window",
        "last_inbound_at": last_inbound,
        "age_hours": age_hours,
    }


def _bot_platform_reply_url():
    explicit = (os.environ.get("KILAS_BOT_PLATFORM_REPLY_URL") or "").strip()
    if explicit:
        return explicit
    owner_notify_url = (os.environ.get("KILAS_BOT_INTERNAL_URL") or "").strip()
    if not owner_notify_url:
        return None
    try:
        parsed = urlparse(owner_notify_url)
    except Exception:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}/internal/platform-cs-reply"


def send_manual_reply(customer_phone, message_text):
    """Ask the WhatsApp bot service to send a manual Kilas Works reply.

    Client Hub deliberately does NOT need WHATSAPP_ACCESS_TOKEN / Phone Number ID. The production
    bot already owns those secrets, so we reuse the existing INTERNAL_SERVICE_SECRET bridge rather
    than duplicating Meta credentials across services.
    """
    phone = normalize_customer_phone(customer_phone)
    text = (message_text or "").strip()
    if not phone:
        return False, "invalid_customer_phone"
    if not text:
        return False, "empty_message"
    if len(text) > MAX_MANUAL_MESSAGE_CHARS:
        return False, "message_too_long"
    if not customer_exists(phone):
        return False, "customer_not_found"
    try:
        if get_state(phone) != "HUMAN_TAKEOVER":
            return False, "human_takeover_required"
    except Exception:
        return False, "takeover_state_unavailable"

    window = freeform_window_status(phone)
    if not window["allowed"]:
        return False, window["reason"]

    endpoint = _bot_platform_reply_url()
    secret = (os.environ.get("INTERNAL_SERVICE_SECRET") or "").strip()
    if not endpoint or not secret:
        return False, "bot_internal_bridge_unavailable"
    try:
        resp = requests.post(
            endpoint,
            json={"customer_phone": phone, "message": text},
            headers={"X-Internal-Service-Secret": secret},
            timeout=12,
        )
    except requests.exceptions.RequestException:
        return False, "bot_internal_bridge_network_error"
    if resp.status_code != 200:
        return False, f"bot_internal_bridge_http_{resp.status_code}"
    try:
        body = resp.json()
    except ValueError:
        return False, "bot_internal_bridge_bad_response"
    if body.get("status") == "ok":
        return True, "sent"
    return False, body.get("reason") or "bot_internal_bridge_rejected"
