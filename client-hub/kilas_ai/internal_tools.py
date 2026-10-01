"""Thin, server-authorized adapters over existing WhatsApp and Finance services."""
import hashlib
from datetime import date

import db
import finance_branches
import finance_service
from kilas_core import whatsapp_access, whatsapp_transport
from . import connectors


def whatsapp_search(user_id, business_id, query=""):
    connectors.authorize(user_id, "whatsapp.search", business_id=business_id)
    if not whatsapp_access.channel(business_id):
        raise connectors.ConnectorError("not_connected")
    term = str(query or "").strip().casefold()[:100]
    rows = db.query_all("SELECT c.conversation_id,c.customer_phone,w.updated_at,k.display_name "
                        "FROM kw_core_wa_conversations c JOIN kw_web_conversations w "
                        "ON w.business_id=c.business_id AND w.id=c.conversation_id "
                        "LEFT JOIN kw_web_customer_links l ON l.business_id=c.business_id AND l.conversation_id=c.conversation_id "
                        "LEFT JOIN kw_core_customers k ON k.business_id=l.business_id AND k.id=l.customer_id "
                        "WHERE c.business_id=? ORDER BY w.updated_at DESC LIMIT 100", (business_id,))
    contacts = [dict(row) for row in rows]
    return [row for row in contacts if not term or term in (
        str(row["customer_phone"]) + " " + str(row.get("display_name") or "")).casefold()][:20]


def whatsapp_thread(user_id, business_id, conversation_id):
    connectors.authorize(user_id, "whatsapp.thread", business_id=business_id)
    if not whatsapp_access.channel(business_id):
        raise connectors.ConnectorError("not_connected")
    link = db.query_one("SELECT customer_phone FROM kw_core_wa_conversations "
                        "WHERE business_id=? AND conversation_id=?", (business_id, conversation_id))
    if not link:
        raise connectors.ConnectorError("invalid_target")
    rows = db.query_all("SELECT role,content,created_at FROM kw_web_messages "
                        "WHERE business_id=? AND conversation_id=? ORDER BY id DESC LIMIT 30",
                        (business_id, conversation_id))
    return {"customer_phone": link["customer_phone"],
            "messages": [dict(row) for row in reversed(rows)]}


def whatsapp_send(user_id, business_id, conversation_id, text, approval_id):
    connectors.authorize(user_id, "whatsapp.send", business_id=business_id)
    if not whatsapp_access.channel(business_id):
        raise connectors.ConnectorError("not_connected")
    link = db.query_one("SELECT customer_phone FROM kw_core_wa_conversations "
                        "WHERE business_id=? AND conversation_id=?", (business_id, conversation_id))
    if not link or not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
        raise connectors.ConnectorError("invalid_target")
    event_id = "agent-approved-" + str(approval_id)
    result = whatsapp_transport.manual(business_id, conversation_id, event_id, text.strip(), user_id)
    if result.get("status") not in ("accepted", "sent", "delivered", "read"):
        raise connectors.ConnectorError("action_failed")
    return {"id": result.get("provider_id") or event_id, "status": result["status"]}


def finance_businesses(user_id):
    return [item for item in connectors.business_connections(user_id) if item["provider"] == "FINANCE"]


def finance_read(user_id, business_id, tool, *, branch_id=None, limit=20):
    connectors.authorize(user_id, tool, business_id=business_id)
    if tool not in ("finance.accounts", "finance.categories", "finance.transactions", "finance.invoices"):
        raise connectors.ConnectorError("invalid_tool")
    if branch_id is not None:
        branch_id = int(branch_id)
    with finance_branches.scope(business_id, branch_id, user_id):
        if tool == "finance.accounts":
            rows = finance_service.get_account_balance_report(business_id, date.today().isoformat(), actor_user_id=user_id)
            return [{key: row.get(key) for key in ("id", "name", "currency", "account_type", "balance_minor", "branch_id")}
                    for row in rows[:50]]
        if tool == "finance.categories":
            rows = finance_service.list_categories(business_id, actor_user_id=user_id)
            return [{key: row.get(key) for key in ("id", "name", "direction")}
                    for row in rows[:100]]
        if tool == "finance.transactions":
            rows = finance_service.list_transactions(business_id, actor_user_id=user_id, limit=min(50, max(1, int(limit))))
            return [{key: row.get(key) for key in ("id", "occurred_on", "direction", "amount_minor", "currency",
                                                   "description", "account_id", "category_id", "branch_id", "status")}
                    for row in rows]
        rows = db.query_all("SELECT id,invoice_number,status,customer_id,currency,due_date,branch_id "
                            "FROM finance_invoices WHERE business_id=?" + finance_branches.predicate() +
                            " ORDER BY id DESC LIMIT ?", (business_id, min(50, max(1, int(limit)))))
        return [dict(row) for row in rows]


def finance_create_transaction(user_id, business_id, payload, approval_id):
    connectors.authorize(user_id, "finance.create_transaction", business_id=business_id)
    if not isinstance(payload, dict) or payload.get("branch_id") is None:
        raise connectors.ConnectorError("branch_required")
    branch_id = int(payload["branch_id"])
    if branch_id <= 0:  # Never write into the aggregate/all-branch view.
        raise connectors.ConnectorError("branch_required")
    with finance_branches.scope(business_id, branch_id, user_id):
        return finance_service.create_transaction(
            business_id, payload.get("direction"), payload.get("amount_minor"),
            payload.get("account_id"), payload.get("category_id"), payload.get("occurred_on"),
            currency=payload.get("currency", "IDR"), description=payload.get("description"),
            source_type="FINANCE_OPERATOR", source_ref=hashlib.sha256(
                ("kilas-agent:" + str(approval_id)).encode()).hexdigest()[:32], actor_user_id=user_id)
