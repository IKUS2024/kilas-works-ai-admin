"""Shared WhatsApp Inbox / Human Takeover logic — Inbox unification (Section 2 of the request:
"JANGAN bikin sistem terpisah untuk owner dan tenant kalau logic-nya bisa dishare").

WHY THIS MODULE EXISTS: platform_inbox_service.py (Kilas Works' own inbox) and inbox_service.py
(every tenant's inbox) used to independently re-implement the exact same phone validation,
datetime coercion, and 24-hour customer-service-window math — genuinely identical logic that had
already drifted slightly out of sync (platform_inbox_service.py's freeform_window_status() returned
"ok" for the allowed reason, inbox_service.py's returned "inside_customer_service_window" — same
meaning, different string, a real source of confusion for anything comparing the two). This module
is the single source of truth for that shared logic.

WHAT STAYS SEPARATE, ON PURPOSE (this is the "ROLE + PERMISSION + TENANT SCOPE" distinction the
request asks for, not "two implementations"):
  - Kilas Works' own conversations are stored as a plain numeric phone key; tenant conversations
    are stored as "T<business_id>:<customer_phone>" (see ../app.py's own scoping). Row lookups
    still live in each module because the SQL WHERE clause differs by exactly that key shape —
    but every module now calls INTO this file for the parsing/validation/window-math it used to
    duplicate.
  - Sending a message differs by CREDENTIALS, not by logic: a tenant's own WhatsApp token lives in
    Client Hub's own tenant_whatsapp_config table (Client Hub can call the Graph API directly).
    Kilas Works' own token lives in the separate bot process (../app.py) — Client Hub deliberately
    never holds it, so a Kilas-Works-own send goes through the existing internal HTTP bridge
    instead. Both send paths now build their OUTGOING TEMPLATE PAYLOAD the same way (see
    build_template_message_payload() below) — only the transport (direct Graph API call vs.
    internal bridge call) differs.
"""
from datetime import datetime, timezone
import re

WHATSAPP_24H_SAFETY_HOURS = 23
MAX_MANUAL_MESSAGE_CHARS = 4096
_PHONE_RE = re.compile(r"^\d{6,20}$")


def normalize_customer_phone(raw):
    """Digits-only WhatsApp phone number, or None if it doesn't look like a real number. Shared by
    every module that accepts a customer_phone from a form/URL — never trust an un-normalized
    value in a SQL WHERE clause or an outbound Meta API call."""
    digits = re.sub(r"\D", "", raw or "")
    return digits if _PHONE_RE.match(digits) else None


def coerce_datetime(value):
    """Normalizes a timestamp value (a Python datetime already, OR an ISO-ish string as SQLite/
    Postgres drivers can each hand back) into an aware, UTC datetime. Returns None for anything
    unparseable — callers must treat that as 'unknown', never as 'now'/'already expired'."""
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


def compute_freeform_window_status(last_inbound_at, now=None):
    """The actual 23-hour customer-service-window math (Meta's real limit is 24h; 23h is this
    codebase's existing, deliberate safety buffer against clock drift — see app.py's
    WHATSAPP_24H_SAFETY_HOURS, which this constant intentionally matches). Pure function — the
    caller resolves `last_inbound_at` (a datetime or None) from whichever table/scope applies,
    this function only does the age arithmetic + allowed/blocked decision, identically for Kilas
    Works' own conversations and every tenant's.

    IMPORTANT — Human Takeover itself NEVER expires because of this window (Section 3 of the
    request): this function only decides whether a FREE-FORM message may be sent right now. It
    says nothing about whether Human Takeover mode is still active — that is a completely separate,
    time-independent flag (wa_takeover_service.py / platform_inbox_service.py's own mode column),
    checked separately by every send path. A conversation can be in HUMAN_TAKEOVER with this
    window reporting "not allowed" at the same time — the inbox stays fully open and readable
    either way; only a free-form SEND is blocked until a template re-opens the window."""
    if last_inbound_at is None:
        return {"allowed": False, "reason": "no_customer_inbound", "last_inbound_at": None, "age_hours": None}
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now.astimezone(timezone.utc) - last_inbound_at).total_seconds() / 3600.0)
    allowed = age_hours < WHATSAPP_24H_SAFETY_HOURS
    return {
        "allowed": allowed,
        "reason": "inside_customer_service_window" if allowed else "outside_24h_window",
        "last_inbound_at": last_inbound_at,
        "age_hours": age_hours,
    }


def build_template_message_payload(to_phone, template_name, language_code, params=None):
    """Builds the WhatsApp Cloud API 'template' message body — the ONE shared shape both the
    tenant direct-Graph-API send path and the Kilas-Works-own internal-bridge send path use, so a
    template message always has the exact same structure regardless of which credentials/transport
    end up sending it. `params` is an optional list of plain strings for the template's body
    variables ({{1}}, {{2}}, ...); omitted entirely (no "components" key) when there are none, since
    Meta rejects an empty components array for some template configurations."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
        },
    }
    if params:
        payload["template"]["components"] = [{
            "type": "body",
            "parameters": [{"type": "text", "text": str(p)} for p in params],
        }]
    return payload


def resolve_reengagement_template_config(env_get):
    """Reads the GLOBAL approved WhatsApp re-engagement template configuration. `env_get` is
    injected (normally os.environ.get) so this stays trivially testable without patching
    os.environ globally. Returns (template_name, language_code) or (None, None) if not configured
    — every caller MUST treat "not configured" as "cannot send a template right now", never invent
    a template name.

    This is Kilas Works' OWN platform-inbox configuration (platform_inbox_service.py always uses
    this directly, per the explicit requirement that Kilas Works' own inbox keeps using the global
    config). For a TENANT conversation, use resolve_reengagement_template_config_for_tenant()
    below instead — it checks the tenant's own override FIRST, only falling back to this global
    config, never the reverse."""
    name = (env_get("WHATSAPP_REENGAGEMENT_TEMPLATE_NAME") or "").strip()
    if not name:
        return None, None
    language_code = (env_get("WHATSAPP_REENGAGEMENT_TEMPLATE_LANGUAGE") or "id").strip() or "id"
    return name, language_code


def resolve_reengagement_template_config_for_tenant(tenant_whatsapp_config_row, env_get):
    """Tenant-scoped re-engagement template resolution hierarchy (Inbox unification follow-up
    fix): a tenant business does not necessarily have the same Meta-approved template as Kilas
    Works or as any other tenant, so forcing one shared global template on every tenant is wrong.
    Resolution order, stopping at the first hit:
      1. This tenant's OWN override — tenant_whatsapp_config.reengagement_template_name/
         reengagement_template_language (see migration 0018 + repo.set_tenant_reengagement_
         template()). NULL/blank means "no override for this tenant".
      2. The GLOBAL fallback — same WHATSAPP_REENGAGEMENT_TEMPLATE_NAME/_LANGUAGE env vars
         platform_inbox_service.py uses for Kilas Works' own inbox. A tenant with no override of
         its own is allowed to use this shared default (Section 3 of the request: "optionally fall
         back to the global config") — this is a deliberate, permitted fallback, not a forced
         requirement that every tenant configure their own template.
      3. Neither exists -> (None, None). The caller MUST fail closed: never send free-form outside
         the 24h window, never fabricate a template name.

    `tenant_whatsapp_config_row` is the dict/Row already returned by repo.get_whatsapp_config(
    business_id) (or None if the tenant has no WhatsApp config row at all yet) — passed in rather
    than looked up here so this function has no direct DB dependency and stays trivially testable
    with a plain dict."""
    row = tenant_whatsapp_config_row or {}
    tenant_name = (row.get("reengagement_template_name") or "").strip() if hasattr(row, "get") else ""
    if tenant_name:
        tenant_language = (row.get("reengagement_template_language") or "").strip()
        return tenant_name, (tenant_language or "id")
    return resolve_reengagement_template_config(env_get)
