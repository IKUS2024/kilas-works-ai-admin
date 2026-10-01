"""Account-scoped connector registry and exact-payload action approvals.

Google credentials are persisted separately from conversational messages. Finance and
WhatsApp are virtual connectors: their existing authorization/channel tables remain
the source of truth and no row here can turn either one on.
"""
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

import db
import repo
from . import usage


class ConnectorError(ValueError):
    pass


TOOLS = {
    "gmail.search": ("GOOGLE", "READ", "https://www.googleapis.com/auth/gmail.readonly"),
    "gmail.thread": ("GOOGLE", "READ", "https://www.googleapis.com/auth/gmail.readonly"),
    "gmail.draft": ("GOOGLE", "PREPARE", "https://www.googleapis.com/auth/gmail.compose"),
    "gmail.send": ("GOOGLE", "ACTION", "https://www.googleapis.com/auth/gmail.send"),
    "calendar.list": ("GOOGLE", "READ", "https://www.googleapis.com/auth/calendar.events.readonly"),
    "calendar.freebusy": ("GOOGLE", "READ", "https://www.googleapis.com/auth/calendar.freebusy"),
    "calendar.create": ("GOOGLE", "ACTION", "https://www.googleapis.com/auth/calendar.events"),
    "calendar.update": ("GOOGLE", "ACTION", "https://www.googleapis.com/auth/calendar.events"),
    "calendar.delete": ("GOOGLE", "ACTION", "https://www.googleapis.com/auth/calendar.events"),
    "drive.search": ("GOOGLE", "READ", "https://www.googleapis.com/auth/drive.readonly"),
    "drive.read": ("GOOGLE", "READ", "https://www.googleapis.com/auth/drive.readonly"),
    "contacts.search": ("GOOGLE", "READ", "https://www.googleapis.com/auth/contacts.readonly"),
    "whatsapp.search": ("WHATSAPP", "READ", None),
    "whatsapp.thread": ("WHATSAPP", "READ", None),
    "whatsapp.send": ("WHATSAPP", "ACTION", None),
    "finance.businesses": ("FINANCE", "READ", None),
    "finance.accounts": ("FINANCE", "READ", None),
    "finance.categories": ("FINANCE", "READ", None),
    "finance.transactions": ("FINANCE", "READ", None),
    "finance.invoices": ("FINANCE", "READ", None),
    "finance.create_transaction": ("FINANCE", "ACTION", None),
}
GOOGLE_SCOPES = {
    "gmail": ("https://www.googleapis.com/auth/gmail.readonly",
              "https://www.googleapis.com/auth/gmail.compose",
              "https://www.googleapis.com/auth/gmail.send"),
    "calendar": ("https://www.googleapis.com/auth/calendar.events.readonly",
                 "https://www.googleapis.com/auth/calendar.freebusy",
                 "https://www.googleapis.com/auth/calendar.events"),
    "drive": ("https://www.googleapis.com/auth/drive.readonly",),
    "contacts": ("https://www.googleapis.com/auth/contacts.readonly",),
}


def now():
    return datetime.now(timezone.utc)


def stamp(value=None):
    return (value or now()).isoformat()


def _row(row):
    return dict(row) if row else None


def google_connection(user_id):
    return _row(db.query_one("SELECT * FROM kilas_ai_connections WHERE user_id=? AND provider='GOOGLE'", (user_id,)))


def owned_business(user_id, business_id):
    row = db.query_one("SELECT b.id,b.business_name FROM businesses b JOIN business_memberships m "
                       "ON m.business_id=b.id WHERE b.id=? AND m.user_id=? AND b.status!='ARCHIVED'",
                       (business_id, user_id))
    if not row:
        raise ConnectorError("business_not_found")
    return _row(row)


def business_connections(user_id):
    rows = repo.list_businesses_for_user(user_id)
    result = []
    for business in rows:
        bid = business["id"]
        finance = db.query_one("SELECT 1 AS available FROM finance_entitlements WHERE business_id=?", (bid,))
        if not finance:
            finance = db.query_one("SELECT 1 AS available FROM finance_accounts WHERE business_id=? LIMIT 1", (bid,))
        if finance:
            result.append({"provider": "FINANCE", "business_id": bid,
                           "display_identity": business["business_name"], "status": "CONNECTED"})
        from kilas_core import whatsapp_access
        if whatsapp_access.channel(bid):
            result.append({"provider": "WHATSAPP", "business_id": bid,
                           "display_identity": business["business_name"], "status": "CONNECTED"})
    return result


def available_tools(user_id, business_id=None):
    """Return only actual, currently authorized tools; never trust a UI connection flag."""
    available = []
    google = google_connection(user_id)
    if google and google["status"] == "CONNECTED" and google["credential_enc"]:
        scopes = set(json.loads(google["scopes_json"]))
        available += [name for name, (provider, _, scope) in TOOLS.items()
                      if provider == "GOOGLE" and scope in scopes]
    for item in business_connections(user_id):
        if business_id is not None and item["business_id"] != business_id:
            continue
        available += [name for name, (provider, _, _) in TOOLS.items() if provider == item["provider"]]
    return sorted(set(available))


def authorize(user_id, tool, *, business_id=None):
    if tool not in TOOLS:
        raise ConnectorError("unknown_tool")
    provider, permission, scope = TOOLS[tool]
    if provider == "GOOGLE":
        if business_id is not None:
            raise ConnectorError("invalid_business_scope")
        row = google_connection(user_id)
        if not row or row["status"] != "CONNECTED":
            raise ConnectorError("not_connected")
        if scope not in json.loads(row["scopes_json"]):
            raise ConnectorError("permission_missing")
        return {"provider": provider, "permission": permission, "connection_id": row["id"]}
    if not business_id:
        raise ConnectorError("business_required")
    owned_business(user_id, business_id)
    if tool not in available_tools(user_id, business_id):
        raise ConnectorError("not_connected")
    return {"provider": provider, "permission": permission, "connection_id": None}


def _canonical(payload):
    if not isinstance(payload, dict) or len(json.dumps(payload, ensure_ascii=False)) > 12000:
        raise ConnectorError("invalid_payload")
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def propose_action(user_id, tool, target, payload, *, business_id=None):
    gate = authorize(user_id, tool, business_id=business_id)
    if gate["permission"] != "ACTION":
        raise ConnectorError("approval_not_required")
    target = str(target or "").strip()
    if not 1 <= len(target) <= 500:
        raise ConnectorError("invalid_target")
    canonical = _canonical(payload)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    key = secrets.token_hex(24)
    t = now()
    approval_id = db.insert_returning_id("INSERT INTO kilas_ai_action_approvals "
        "(user_id,business_id,connection_id,tool,target,payload_json,payload_hash,status,idempotency_key,expires_at,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, business_id, gate["connection_id"], tool, target, canonical, digest,
         "PENDING", key, stamp(t + timedelta(minutes=15)), stamp(t), stamp(t)))
    db.execute("INSERT INTO kilas_ai_action_audit(approval_id,user_id,event,created_at) VALUES (?,?,?,?)",
               (approval_id, user_id, "PROPOSED", stamp(t)))
    return approval_id


def approval(user_id, approval_id):
    return _row(db.query_one("SELECT * FROM kilas_ai_action_approvals WHERE id=? AND user_id=?",
                             (approval_id, user_id)))


def claim_action(user_id, approval_id):
    """Single-use, durable claim before a remote side effect. Unknown outcomes are terminal."""
    conn = usage._connect()
    try:
        lock = " FOR UPDATE" if db.BACKEND == "postgres" else ""
        row = usage._query(conn, "SELECT user_id,business_id,connection_id,tool,target,payload_json,payload_hash,status,expires_at "
                           "FROM kilas_ai_action_approvals WHERE id=? AND user_id=?" + lock,
                           (approval_id, user_id), one=True)
        if not row:
            raise ConnectorError("approval_not_found")
        owner, bid, connection_id, tool, target, payload_json, digest, status, expires_at = row
        if status != "PENDING":
            raise ConnectorError("approval_already_used")
        if usage._as_utc(expires_at) <= now():
            usage._query(conn, "UPDATE kilas_ai_action_approvals SET status='EXPIRED',updated_at=? WHERE id=?",
                         (stamp(), approval_id))
            conn.commit()
            raise ConnectorError("approval_expired")
        if hashlib.sha256(payload_json.encode("utf-8")).hexdigest() != digest:
            raise ConnectorError("approval_payload_changed")
        gate = authorize(user_id, tool, business_id=bid)
        if gate["permission"] != "ACTION" or gate["connection_id"] != connection_id:
            raise ConnectorError("permission_changed")
        usage._query(conn, "UPDATE kilas_ai_action_approvals SET status='CLAIMED',updated_at=? WHERE id=?",
                     (stamp(), approval_id))
        usage._query(conn, "INSERT INTO kilas_ai_action_audit(approval_id,user_id,event,created_at) VALUES (?,?,?,?)",
                     (approval_id, user_id, "CLAIMED", stamp()))
        conn.commit()
        return {"id": approval_id, "user_id": owner, "business_id": bid,
                "connection_id": connection_id, "tool": tool, "target": target,
                "payload": json.loads(payload_json)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def finish_action(user_id, approval_id, status, *, provider_result_id=None, error_code=""):
    if status not in ("SUCCEEDED", "FAILED", "UNKNOWN"):
        raise ConnectorError("invalid_action_status")
    db.execute("UPDATE kilas_ai_action_approvals SET status=?,provider_result_id=?,error_code=?,updated_at=? "
               "WHERE id=? AND user_id=? AND status='CLAIMED'",
               (status, str(provider_result_id or "")[:256] or None, str(error_code or "")[:80],
                stamp(), approval_id, user_id))
    db.execute("INSERT INTO kilas_ai_action_audit(approval_id,user_id,event,detail_code,created_at) "
               "VALUES (?,?,?,?,?)", (approval_id, user_id, status, str(error_code or "")[:80], stamp()))


def cancel_action(user_id, approval_id):
    db.execute("UPDATE kilas_ai_action_approvals SET status='CANCELLED',updated_at=? "
               "WHERE id=? AND user_id=? AND status='PENDING'", (stamp(), approval_id, user_id))
