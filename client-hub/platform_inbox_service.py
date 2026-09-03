"""Kilas Works' own WhatsApp inbox + human takeover helpers.

This is intentionally separate from tenant inbox_service.py ONLY where it has to be — see
wa_inbox_shared.py's own module docstring for exactly which pieces are now SHARED (phone
validation, datetime coercion, 24h-window math, the outgoing template payload SHAPE) versus which
pieces genuinely differ by design (row lookups by a different key shape; send TRANSPORT, since
Client Hub never holds Kilas Works' own WhatsApp token). Tenant conversations are stored as
T<business_id>:<customer_phone>; Kilas Works' own legacy bot stores plain numeric customer phones.
The admin inbox below only reads those plain-number rows, so a KILAS_ADMIN cannot accidentally mix
a client tenant's chats into the platform's own operational inbox.

The database remains an implementation detail. Humans read/reply through Client Hub or WhatsApp
Business; PostgreSQL is never presented as a chat viewer.
"""
from datetime import datetime, timezone
import os
import time
from urllib.parse import urlparse

import requests

import db
import wa_inbox_shared

WHATSAPP_24H_SAFETY_HOURS = wa_inbox_shared.WHATSAPP_24H_SAFETY_HOURS
MAX_MANUAL_MESSAGE_CHARS = wa_inbox_shared.MAX_MANUAL_MESSAGE_CHARS

normalize_customer_phone = wa_inbox_shared.normalize_customer_phone
_coerce_datetime = wa_inbox_shared.coerce_datetime


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
    return wa_inbox_shared.compute_freeform_window_status(last_inbound, now=now)


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
        timeout_seconds = float(os.environ.get("KILAS_BOT_REPLY_TIMEOUT_SECONDS") or "75")
        resp = requests.post(
            endpoint,
            json={"customer_phone": phone, "message": text},
            headers={"X-Internal-Service-Secret": secret},
            timeout=max(15.0, min(timeout_seconds, 120.0)),
        )
    except requests.exceptions.Timeout:
        print("Platform Inbox manual reply bridge timeout — bot belum merespons tepat waktu.")
        return False, "bot_internal_bridge_timeout"
    except requests.exceptions.RequestException as exc:
        print(f"Platform Inbox manual reply bridge network error: {type(exc).__name__}")
        return False, "bot_internal_bridge_network_error"
    if resp.status_code != 200:
        remote_reason = ""
        try:
            remote_reason = str((resp.json() or {}).get("reason") or "").strip()
        except (ValueError, TypeError, AttributeError):
            remote_reason = ""
        print(
            "Platform Inbox manual reply bridge rejected: "
            f"http={resp.status_code} reason={remote_reason or 'unknown'}"
        )
        suffix = f":{remote_reason}" if remote_reason else ""
        return False, f"bot_internal_bridge_http_{resp.status_code}{suffix}"
    try:
        body = resp.json()
    except ValueError:
        return False, "bot_internal_bridge_bad_response"
    if body.get("status") == "ok":
        return True, "sent"
    return False, body.get("reason") or "bot_internal_bridge_rejected"


def send_template_reply(customer_phone, params=None):
    """Approved WhatsApp template send — the "Kirim Template & Lanjutkan" action for a
    conversation whose 24h customer-service window has expired (Section 4 of the request). Unlike
    send_manual_reply(), this path is deliberately allowed to fire EVEN WHEN freeform_window_status()
    reports "not allowed" — that is exactly the situation an approved template exists to handle
    (WhatsApp explicitly permits a template message outside the free-form window; that is the
    entire reason templates exist). Still requires HUMAN_TAKEOVER to be active, for the same reason
    a free-form reply does: a human, not the AI, is the one re-engaging this customer.

    Uses the SAME internal bridge/transport as send_manual_reply() (Client Hub never holds Kilas
    Works' own WhatsApp token) — only the outgoing payload shape differs (a template payload, built
    by the shared wa_inbox_shared.build_template_message_payload(), instead of a free-text one).
    Returns (False, "reengagement_template_not_configured") if no approved template name has been
    set — see wa_inbox_shared.resolve_reengagement_template_config()'s own docstring for exactly
    what needs to be created/approved in Meta Business Manager first; this function never invents a
    template name to "make it work" anyway."""
    phone = normalize_customer_phone(customer_phone)
    if not phone:
        return False, "invalid_customer_phone"
    if not customer_exists(phone):
        return False, "customer_not_found"
    try:
        if get_state(phone) != "HUMAN_TAKEOVER":
            return False, "human_takeover_required"
    except Exception:
        return False, "takeover_state_unavailable"

    template_name, language_code = wa_inbox_shared.resolve_reengagement_template_config(os.environ.get)
    if not template_name:
        return False, "reengagement_template_not_configured"

    endpoint = _bot_platform_reply_url()
    secret = (os.environ.get("INTERNAL_SERVICE_SECRET") or "").strip()
    if not endpoint or not secret:
        return False, "bot_internal_bridge_unavailable"
    template_endpoint = endpoint.replace("/internal/platform-cs-reply", "/internal/platform-cs-template-reply")
    payload = {
        "customer_phone": phone, "template_name": template_name,
        "language_code": language_code, "params": params or [],
    }
    return _post_to_bot_bridge(template_endpoint, payload, secret)


def _post_to_bot_bridge(endpoint, payload, secret):
    """Production fix (Batch 2/3, Section C — real incident: Client Hub -> AI Admin internal
    bridge occasionally returns HTTP 429 on a template send). Root cause, established by
    exhaustive source-level tracing rather than guessed:
      - NEITHER Client Hub NOR the bot application code contains any rate-limiting logic on this
        internal, shared-secret-authenticated bridge route (confirmed by exhaustive search —
        ruled out by direct evidence, not assumed).
      - The bot's own send_whatsapp_template_message() already correctly catches any Meta Graph
        API error (including a 429 FROM Meta) and converts it to a clean 502, never passing a raw
        429 through as the route's own response (confirmed by reading that function directly —
        also ruled out by direct evidence).
    These two are the only sources that could exist WITHIN this codebase's own code, and both are
    ruled out. The remaining source is therefore infrastructure OUTSIDE this codebase — something
    no code change here can eliminate at the source, since it isn't application code at all. This
    fix does NOT identify or assume which specific piece of infrastructure (hosting platform,
    proxy, CDN, or otherwise) is responsible — no direct evidence was available from within this
    codebase to determine that, and none is claimed here.

    NO automatic retry: since the unidentified infrastructure component's exact behavior is
    unknown, it would be an unverified ASSUMPTION to treat a 429 from it as guaranteed "rejected
    before being acted upon" the way a 429 from a conventional rate limiter normally would be.
    This bridge has no persistent idempotency/deduplication mechanism for outgoing template sends
    (confirmed by exhaustive search — the only dedup logic in this codebase is
    is_duplicate_event()/PROCESSED_MESSAGE_IDS for INCOMING webhook messages, which does not apply
    here) — so a blind retry could duplicate a real WhatsApp template send to the customer, which
    is worse than a manual retry. The failure is surfaced as a clean, human-readable error instead
    (see routes_admin.py's platform_inbox_send_template()); the admin can safely press "Kirim
    Template & Lanjutkan" again manually — Human Takeover stays active and no state is lost by not
    retrying automatically."""
    timeout_seconds = float(os.environ.get("KILAS_BOT_REPLY_TIMEOUT_SECONDS") or "75")
    request_timeout = max(15.0, min(timeout_seconds, 120.0))
    try:
        resp = requests.post(
            endpoint, json=payload, headers={"X-Internal-Service-Secret": secret},
            timeout=request_timeout,
        )
    except requests.exceptions.Timeout:
        print("Platform Inbox template reply bridge timeout — bot belum merespons tepat waktu.")
        return False, "bot_internal_bridge_timeout"
    except requests.exceptions.RequestException as exc:
        print(f"Platform Inbox template reply bridge network error: {type(exc).__name__}")
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
