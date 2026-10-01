"""Natural Agent requests routed through verified, account-scoped connector tools."""
import json
import re

from . import connector_planner, connectors, google_tools, internal_tools

SCHEDULE_WORDS = re.compile(r"\b(?:setiap|tiap|every|besok|tomorrow|lusa|next|minggu depan)\b", re.I)


def _business(user_id, provider, proposed):
    matches = [item for item in connectors.business_connections(user_id) if item["provider"] == provider]
    if proposed:
        chosen = next((item for item in matches if item["business_id"] == proposed), None)
        if not chosen:
            raise connectors.ConnectorError("business_not_connected")
        return proposed
    if len(matches) == 1:
        return matches[0]["business_id"]
    raise connectors.ConnectorError("choose_business")


def scheduled_read(user_id, instruction, timezone_name):
    """Cron may read a connected provider; it can never create an approval or send."""
    available = connectors.available_tools(user_id)
    businesses = connectors.business_connections(user_id)
    plan = connector_planner.propose(user_id, instruction, [], available, businesses,
                                     timezone_name, scheduled=True)
    tool = plan["tool"]
    if tool not in available or connectors.TOOLS[tool][1] != "READ" or plan["intent"] != "READ":
        raise connectors.ConnectorError("scheduled_read_only")
    provider = connectors.TOOLS[tool][0]
    bid = (_business(user_id, provider, plan["business_id"])
           if provider != "GOOGLE" and tool != "finance.businesses" else None)
    connectors.authorize(user_id, tool, business_id=bid) if tool != "finance.businesses" else None
    return _read(user_id, tool, plan["arguments"], bid)


def _read(user_id, tool, args, business_id):
    if tool == "gmail.search":
        rows = google_tools.gmail_search(user_id, args.get("query"))
        return "\n".join(f"• {row['subject'] or '(tanpa subjek)'} — {row['from']} — {row['date']}\n  {row['snippet']}\n  Thread: {row['thread_id']}" for row in rows) or "Tidak ada email yang cocok."
    if tool == "gmail.thread":
        rows = google_tools.gmail_thread(user_id, args.get("thread_id"))
        return "\n".join(f"• {row['from']} — {row['date']}\n  {row['snippet']}" for row in rows) or "Thread kosong."
    if tool == "calendar.list":
        rows = google_tools.calendar_events(user_id, args.get("start"), args.get("end"))
        return "\n".join(f"• {row.get('summary','(tanpa judul)')} — {(row.get('start') or {}).get('dateTime') or (row.get('start') or {}).get('date')}" for row in rows) or "Tidak ada acara pada rentang itu."
    if tool == "calendar.freebusy":
        rows = google_tools.calendar_freebusy(user_id, args.get("start"), args.get("end"))
        return "Waktu sibuk:\n" + "\n".join(f"• {row.get('start')}–{row.get('end')}" for row in rows) if rows else "Tidak ada waktu sibuk pada rentang itu."
    if tool == "drive.search":
        rows = google_tools.drive_search(user_id, args.get("query"))
        return "\n".join(f"• {row.get('name')} ({row.get('mimeType')}) — ID {row.get('id')}" for row in rows) or "Tidak ada file yang cocok."
    if tool == "drive.read":
        result = google_tools.drive_read(user_id, args.get("file_id"))
        return f"{result['file'].get('name')}:\n{result['content'][:1700]}"
    if tool == "contacts.search":
        rows = google_tools.contacts_search(user_id, args.get("query"))
        return "\n".join(f"• {row['name']} — {', '.join(row['emails'] + row['phones'])}" for row in rows) or "Tidak ada kontak yang cocok."
    if tool == "whatsapp.search":
        rows = internal_tools.whatsapp_search(user_id, business_id, args.get("query"))
        return "\n".join(f"• {row.get('display_name') or row['customer_phone']} — {row['customer_phone']} — Percakapan {row['conversation_id']}" for row in rows) or "Tidak ada percakapan yang cocok."
    if tool == "whatsapp.thread":
        result = internal_tools.whatsapp_thread(user_id, business_id, args.get("conversation_id"))
        return "\n".join(f"• {row['role']}: {row['content'][:350]}" for row in result["messages"][-8:]) or "Percakapan belum berisi pesan."
    if tool == "finance.businesses":
        rows = internal_tools.finance_businesses(user_id)
        return "\n".join(f"• {row['display_identity']} — bisnis {row['business_id']}" for row in rows) or "Tidak ada bisnis Finance pada akun ini."
    if tool.startswith("finance."):
        rows = internal_tools.finance_read(user_id, business_id, tool,
                    branch_id=args.get("branch_id"), limit=args.get("limit", 20))
        return "\n".join("• " + ", ".join(f"{k}: {v}" for k, v in row.items() if v is not None)
                         for row in rows[:20]) or "Tidak ada data pada lingkup itu."
    raise connectors.ConnectorError("unknown_tool")


def _proposal(user_id, tool, args, business_id):
    if tool == "gmail.send":
        to = str(args.get("to") or "").strip()
        subject = str(args.get("subject") or "").strip()
        body = str(args.get("body") or "").strip()
        google_tools._raw_email(to, subject, body)
        payload = {"to": to, "subject": subject, "body": body}
        for key in ("thread_id", "reply_to"):
            if args.get(key):
                payload[key] = str(args[key])[:180]
        return connectors.propose_action(user_id, tool, to, payload)
    if tool in ("calendar.create", "calendar.update", "calendar.delete"):
        target = str(args.get("event_id") or "primary") if tool != "calendar.create" else "primary"
        payload = google_tools._event_payload(args) if tool != "calendar.delete" else {}
        if tool != "calendar.create":
            google_tools._id(target)
        return connectors.propose_action(user_id, tool, target, payload)
    if tool == "whatsapp.send":
        cid = str(args.get("conversation_id") or "")
        text = str(args.get("text") or "").strip()
        if not 1 <= len(text) <= 4000:
            raise connectors.ConnectorError("invalid_message")
        internal_tools.whatsapp_thread(user_id, business_id, cid)
        return connectors.propose_action(user_id, tool, cid, {"text": text}, business_id=business_id)
    if tool == "finance.create_transaction":
        required = ("branch_id", "direction", "amount_minor", "account_id", "category_id", "occurred_on")
        if not all(args.get(key) is not None for key in required):
            raise connectors.ConnectorError("finance_fields_missing")
        payload = {key: args[key] for key in required}
        payload["currency"] = args.get("currency", "IDR")
        payload["description"] = str(args.get("description") or "")[:500]
        # Existing Finance validation remains authoritative during execution; preview binds
        # the complete branch/account/category/amount before the owner confirms.
        return connectors.propose_action(user_id, tool, str(args["branch_id"]), payload, business_id=business_id)
    raise connectors.ConnectorError("action_not_supported")


def handle(user_id, text, history, timezone_name):
    available = connectors.available_tools(user_id)
    businesses = connectors.business_connections(user_id)
    plan = connector_planner.propose(user_id, text, history, available, businesses, timezone_name)
    tool = plan["tool"]
    intent = plan["intent"]
    if tool == "none" or intent in ("NONE", "CLARIFY"):
        return {"message": str(plan.get("reply") or "Sebutkan layanan dan tujuan yang ingin dipakai.")[:1000]}
    provider, permission, _ = connectors.TOOLS[tool]
    bid = (_business(user_id, provider, plan["business_id"])
           if provider != "GOOGLE" and tool != "finance.businesses" else None)
    if tool != "finance.businesses":
        connectors.authorize(user_id, tool, business_id=bid)
    args = plan["arguments"]
    if permission == "READ" and intent == "READ":
        return {"message": _read(user_id, tool, args, bid)[:1900]}
    if permission == "ACTION" and intent in ("PREPARE", "ACTION"):
        approval_id = _proposal(user_id, tool, args, bid)
        return {"message": "Aku siapkan tindakan ini. Periksa tujuan dan isinya sebelum menekan Konfirmasi.",
                "approval_id": approval_id}
    if tool == "gmail.draft" and intent in ("PREPARE", "ACTION"):
        # A requested draft remains a local proposal until the owner explicitly sends it.
        approval_id = _proposal(user_id, "gmail.send", args, None)
        return {"message": "Draf siap ditinjau. Email belum dikirim.", "approval_id": approval_id}
    return {"message": "Aku belum bisa menjalankan permintaan itu dengan izin yang tersedia."}
