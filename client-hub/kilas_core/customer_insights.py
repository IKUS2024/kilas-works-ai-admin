"""AI Customer Insight derived only from the conversations shown in Kilas Inbox."""
from datetime import datetime
import hashlib
import json
import time

import ai_onboarding
import ai_usage
import db
import inbox_service
from kilas_core import customers


SYSTEM_PROMPT = """Kamu menganalisis percakapan customer untuk pemilik bisnis.
Buat Customer Insight berdasarkan HANYA fakta yang benar-benar tertulis dalam percakapan Inbox.
JANGAN menebak nama, bisnis, lokasi, budget, kebutuhan, niat beli, atau fakta lain.
Jika belum diketahui gunakan null atau masukkan ke unknowns.
Pesan berlabel CUSTOMER adalah ucapan customer. Pesan BUSINESS adalah balasan bisnis/AI dan bukan fakta tentang customer kecuali customer sendiri mengonfirmasinya.
Abaikan pesan handshake/demo teknis yang hanya dipakai untuk menghubungkan percakapan.
Ringkas dalam Bahasa Indonesia, singkat dan berguna untuk sales/admin.
Balas HANYA JSON valid dengan struktur:
{
 "summary": string|null,
 "known_name": string|null,
 "business_name": string|null,
 "location": string|null,
 "needs": string|null,
 "budget": string|null,
 "intent": string|null,
 "important_questions": [string],
 "buying_signals": [string],
 "unknowns": [string],
 "follow_up": string|null
}
Array maksimal 5 item. Jangan sertakan markdown."""


def _json_list(value):
    if not isinstance(value, list):
        return []
    return [str(x).strip()[:300] for x in value[:5] if str(x).strip()]


def _clean(value, maximum=1000):
    if value is None:
        return None
    value = str(value).strip()
    return value[:maximum] if value else None


def _to_epoch(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str):
        raw = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(raw).timestamp()
        except ValueError:
            try:
                return float(raw)
            except ValueError:
                return 0.0
    return 0.0


def _demo_binding(bid, phone):
    if not phone:
        return None
    try:
        row = db.query_one(
            "SELECT detail FROM audit_log WHERE business_id=? AND action='demo_whatsapp_bound' "
            "ORDER BY id DESC LIMIT 1",
            (bid,),
        )
        detail = json.loads(row["detail"]) if row and row.get("detail") else {}
    except Exception:
        return None
    if not isinstance(detail, dict) or detail.get("phone") != phone:
        return None
    try:
        start_id = int(detail.get("start_message_id") or 0)
    except (TypeError, ValueError):
        return None
    return start_id if start_id > 0 else None


def _demo_inbox_messages(bid, phone):
    """Exact durable Demo Inbox thread. No Web Chat source is read here."""
    start = _demo_binding(bid, phone)
    if not start:
        return []
    try:
        rows = db.query_all(
            "SELECT id,role,content,created_at FROM messages "
            "WHERE number=? AND mode IN ('customer','owner') AND id>=? "
            "ORDER BY id DESC LIMIT 300",
            (phone, start),
        )
    except Exception:
        return []
    rows = list(reversed(rows))
    result = []
    for row in rows:
        text = str(row.get("content") or "")
        # Do not let the demo handshake become a fake customer preference/intent.
        if int(row.get("id") or 0) == start and row.get("role") == "user":
            if "Demo ID:" in text or "KWDEMO-" in text or "coba Kilas Assist" in text:
                continue
        if row.get("role") == "assistant" and (
            "Demo aktif" in text or "kode demo" in text.lower()
        ):
            continue
        result.append({
            "source": "DEMO_WHATSAPP",
            "conversation_key": "demo:" + phone,
            "id": int(row.get("id") or 0),
            "role": row.get("role"),
            "content": text,
            "created_at": row.get("created_at"),
        })
    return result


def _tenant_inbox_messages(bid, phone):
    """Legacy/tenant WhatsApp thread from the exact inbox_service source."""
    if not phone:
        return []
    try:
        rows = inbox_service.get_thread(bid, phone, limit=300)
    except Exception:
        return []
    return [{
        "source": "TENANT_WHATSAPP",
        "conversation_key": "tenant:" + phone,
        "id": int(row.get("id") or 0),
        "role": row.get("role"),
        "content": str(row.get("content") or ""),
        "created_at": row.get("created_at"),
    } for row in rows]


def _official_inbox_messages(bid, customer_id):
    """Current Core WhatsApp Inbox only. Explicitly excludes historical Web Chat conversations."""
    try:
        with customers.transaction() as tx:
            rows = tx.execute(
                "SELECT m.id,m.role,m.content,m.created_at,w.id AS conversation_id,"
                "wa.customer_phone FROM kw_web_customer_links l "
                "JOIN kw_web_conversations w ON w.business_id=l.business_id AND w.id=l.conversation_id "
                "JOIN kw_core_wa_conversations wa ON wa.business_id=w.business_id AND wa.conversation_id=w.id "
                "JOIN kw_web_messages m ON m.business_id=w.business_id AND m.conversation_id=w.id "
                "WHERE l.business_id=? AND l.customer_id=? AND w.id LIKE 'wa_%' "
                "ORDER BY m.id DESC LIMIT 300",
                (bid, customer_id),
            )
        rows = list(reversed(rows))
    except Exception:
        # Older/partial fixtures may not have the official WhatsApp adapter schema yet.
        return []
    return [{
        "source": "OFFICIAL_WHATSAPP",
        "conversation_key": "official:" + str(row["conversation_id"]),
        "id": int(row.get("id") or 0),
        "role": row.get("role"),
        "content": str(row.get("content") or ""),
        "created_at": row.get("created_at"),
        "phone": row.get("customer_phone"),
    } for row in rows]


def inbox_snapshot(bid, customer_id):
    """Return only what this customer has in Kilas Inbox, never Web Chat."""
    customer = customers.get_customer(bid, customer_id)
    phone = customer.get("phone")
    official = _official_inbox_messages(bid, customer_id)
    if not phone and official:
        phone = official[-1].get("phone")
    rows = official
    rows += _tenant_inbox_messages(bid, phone)
    rows += _demo_inbox_messages(bid, phone)
    rows.sort(key=lambda row: (_to_epoch(row.get("created_at")), row["source"], row["id"]))

    conversation_keys = {row["conversation_key"] for row in rows}
    signature = hashlib.sha256()
    for row in rows:
        signature.update(
            (row["source"] + "|" + row["conversation_key"] + "|" + str(row["id"]) + "|" +
             str(row.get("role") or "") + "|" + str(row.get("content") or "")).encode("utf-8")
        )
    source_version = int.from_bytes(signature.digest()[:8], "big") & ((1 << 63) - 1) if rows else 0
    return {
        "phone": phone,
        "messages": rows,
        "conversation_count": len(conversation_keys),
        "message_count": len(rows),
        "source_version": source_version,
    }


def get(bid, customer_id):
    with customers.transaction() as tx:
        row = tx.one(
            "SELECT * FROM kw_core_customer_insights WHERE business_id=? AND customer_id=?",
            (bid, customer_id),
        )
    if not row:
        return None
    for key in ("important_questions", "buying_signals", "unknowns"):
        try:
            row[key] = json.loads(row.get(key) or "[]")
        except Exception:
            row[key] = []
    return row


def _store_failed(bid, customer_id, now, message_count, source_version):
    with customers.transaction() as tx:
        tx.execute(
            "INSERT INTO kw_core_customer_insights"
            "(business_id,customer_id,source_message_count,source_version,status,updated_at) "
            "VALUES (?,?,?,?, 'FAILED',?) "
            "ON CONFLICT(business_id,customer_id) DO UPDATE SET "
            "source_message_count=excluded.source_message_count,source_version=excluded.source_version,"
            "status='FAILED',updated_at=excluded.updated_at",
            (bid, customer_id, message_count, source_version, now),
        )


def refresh(bid, customer_id, *, force=False, snapshot=None):
    """Refresh only when Inbox changed. AI never runs inside the inbound-message transaction."""
    snapshot = snapshot or inbox_snapshot(bid, customer_id)
    rows = snapshot["messages"]
    current = get(bid, customer_id)
    if not rows:
        return current
    if (current and not force
            and int(current.get("source_message_count") or 0) == snapshot["message_count"]
            and int(current.get("source_version") or 0) == snapshot["source_version"]):
        return current

    # First analysis reads a bounded recent Inbox history. Later updates use the previous
    # structured memory + newest Inbox messages, so context stays longitudinal without
    # resending an ever-growing transcript on every update.
    recent = rows[-120:] if not current or current.get("status") != "READY" else rows[-50:]
    transcript = []
    for row in recent:
        role = "CUSTOMER" if row["role"] in ("user", "customer") else "BUSINESS"
        transcript.append(f"{role}: {(row['content'] or '')[:1000]}")
    prior = ""
    if current and current.get("status") == "READY":
        prior = "\nINSIGHT SEBELUMNYA:\n" + json.dumps(
            {k: current.get(k) for k in (
                "summary", "known_name", "business_name", "location", "needs", "budget", "intent",
                "important_questions", "buying_signals", "unknowns", "follow_up"
            )},
            ensure_ascii=False,
        )
    prompt = prior + "\nPERCAKAPAN INBOX:\n" + "\n".join(transcript)

    with ai_usage.scope(bid, "customer_insight"):
        raw, stop, error = ai_onboarding._call_claude(
            SYSTEM_PROMPT,
            [{"role": "user", "content": prompt}],
            max_tokens=1200,
            model=ai_onboarding.CLIENT_HUB_SIMULATION_MODEL,
        )
    now = int(time.time())
    if error or stop == "max_tokens":
        _store_failed(
            bid, customer_id, now, snapshot["message_count"], snapshot["source_version"]
        )
        return get(bid, customer_id)
    try:
        data = ai_onboarding._extract_json_object(raw)
        if not isinstance(data, dict):
            raise ValueError("shape")
    except Exception:
        _store_failed(
            bid, customer_id, now, snapshot["message_count"], snapshot["source_version"]
        )
        return get(bid, customer_id)

    clean = {
        "summary": _clean(data.get("summary"), 1500),
        "known_name": _clean(data.get("known_name"), 160),
        "business_name": _clean(data.get("business_name"), 200),
        "location": _clean(data.get("location"), 300),
        "needs": _clean(data.get("needs"), 1000),
        "budget": _clean(data.get("budget"), 300),
        "intent": _clean(data.get("intent"), 700),
        "important_questions": _json_list(data.get("important_questions")),
        "buying_signals": _json_list(data.get("buying_signals")),
        "unknowns": _json_list(data.get("unknowns")),
        "follow_up": _clean(data.get("follow_up"), 1000),
    }
    with customers.transaction() as tx:
        tx.execute(
            "INSERT INTO kw_core_customer_insights"
            "(business_id,customer_id,summary,known_name,business_name,location,needs,budget,intent,"
            "important_questions,buying_signals,unknowns,follow_up,source_message_count,source_version,status,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'READY',?) "
            "ON CONFLICT(business_id,customer_id) DO UPDATE SET "
            "summary=excluded.summary,known_name=excluded.known_name,business_name=excluded.business_name,"
            "location=excluded.location,needs=excluded.needs,budget=excluded.budget,intent=excluded.intent,"
            "important_questions=excluded.important_questions,buying_signals=excluded.buying_signals,"
            "unknowns=excluded.unknowns,follow_up=excluded.follow_up,"
            "source_message_count=excluded.source_message_count,source_version=excluded.source_version,"
            "status='READY',updated_at=excluded.updated_at",
            (
                bid, customer_id, clean["summary"], clean["known_name"], clean["business_name"],
                clean["location"], clean["needs"], clean["budget"], clean["intent"],
                json.dumps(clean["important_questions"], ensure_ascii=False),
                json.dumps(clean["buying_signals"], ensure_ascii=False),
                json.dumps(clean["unknowns"], ensure_ascii=False),
                clean["follow_up"], snapshot["message_count"], snapshot["source_version"], now,
            ),
        )
    return get(bid, customer_id)
