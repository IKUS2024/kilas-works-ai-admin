"""Incremental, tenant-scoped Customer Insight for Kilas Assist CRM.

Customer chat delivery never waits on this module. Insight reads WhatsApp Inbox only; retired Web Chat is excluded. The owner/detail surface calls refresh(),
which compares immutable message cursors and only sends new chat messages plus the previous
structured insight to the model. Demo WhatsApp is read through its durable, privacy-scoped
binding; no platform-wide inbox is ever exposed to a tenant.
"""
import json
import time

import ai_onboarding
import ai_usage
import db
import platform_inbox_service
import platform_workspace
from kilas_core import customers


MAX_NEW_MESSAGES = 120
MAX_MESSAGE_CHARS = 1200
MAX_TRANSCRIPT_CHARS = 24000

SYSTEM_PROMPT = """Kamu adalah analis CRM internal Kilas Assist.
Tugasmu memperbarui Customer Insight dari percakapan customer.

ATURAN MUTLAK:
1. Gunakan HANYA fakta yang customer sendiri nyatakan atau konfirmasi dalam chat.
2. Pesan Bisnis/AI hanya konteks percakapan, BUKAN sumber fakta tentang identitas customer.
3. JANGAN menebak nama, jenis bisnis, lokasi, budget, umur, gender, pekerjaan, karakter,
   kondisi finansial, atau atribut pribadi lain.
4. Jangan menilai kepribadian. communication_notes hanya boleh mendeskripsikan pola komunikasi
   yang terlihat, mis. "sering bertanya harga" atau "jawaban singkat".
5. Kalau fakta belum ada, isi null atau array kosong. Jangan mengisi dari asumsi.
6. buying_stage harus salah satu:
   "BELUM_JELAS", "MENCARI_INFORMASI", "MEMBANDINGKAN", "BERMINAT", "SIAP_MEMBELI", "CUSTOMER_AKTIF".
7. follow_up harus berupa saran praktis untuk admin, bukan pesan yang otomatis dikirim.
8. action HANYA diisi jika CUSTOMER SENDIRI sudah menyatakan tindakan/permintaan konkret yang perlu
   dikerjakan, misalnya mau booking, mau order/beli, minta dibuatkan sesuatu, minta dikirim proposal,
   minta dijadwalkan konsultasi, atau menyatakan layanan spesifik yang ingin dilanjutkan.
   Pertanyaan informasi/FAQ/harga/paket, sekadar minat, membandingkan, atau bisnis menawarkan sesuatu
   BUKAN action. Untuk kasus itu action wajib null.
9. action harus sangat singkat (maksimal satu kalimat), faktual, dan tidak boleh berisi strategi admin.
10. job_status HANYA berdasarkan pernyataan customer:
   - "PERLU_TINDAKAN" jika customer menyatakan mau sesuatu / mau booking / mau order / minta dibuatkan
     tetapi BELUM secara eksplisit deal atau setuju lanjut.
   - "DIKERJAKAN" jika customer secara eksplisit sudah deal, setuju, oke lanjut, fix lanjut,
     mengonfirmasi booking/pesanan, atau menyatakan keputusan final untuk melanjutkan.
   - "BATAL" jika customer secara eksplisit mengatakan tidak jadi, batal, cancel, atau tidak lanjut.
   - null jika tidak ada sinyal yang cukup jelas. Jangan menebak dari pesan Bisnis/AI.
11. Balas HANYA satu JSON valid dengan schema persis:
{
  "summary": string,
  "name": string|null,
  "business_name": string|null,
  "business_type": string|null,
  "location": string|null,
  "budget": string|null,
  "interests": [string],
  "needs": [string],
  "buying_stage": string,
  "buying_signal_reason": string|null,
  "communication_notes": string|null,
  "missing_info": [string],
  "follow_up": string|null,
  "action": string|null,
  "job_status": "PERLU_TINDAKAN"|"DIKERJAKAN"|"BATAL"|null
}
"""


def _default():
    return {
        "summary": "Belum cukup percakapan untuk membuat insight.",
        "name": None,
        "business_name": None,
        "business_type": None,
        "location": None,
        "budget": None,
        "interests": [],
        "needs": [],
        "buying_stage": "BELUM_JELAS",
        "buying_signal_reason": None,
        "communication_notes": None,
        "missing_info": [],
        "follow_up": None,
        "action": None,
        "job_status": None,
    }


def _clean_string(value, maximum=600):
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:maximum] if value else None


def _clean_list(value, maximum_items=12):
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:maximum_items]:
        text = _clean_string(item, 180)
        if text and text not in result:
            result.append(text)
    return result


def _normalize(value):
    if not isinstance(value, dict):
        return _default()
    stage = value.get("buying_stage")
    allowed = {
        "BELUM_JELAS", "MENCARI_INFORMASI", "MEMBANDINGKAN",
        "BERMINAT", "SIAP_MEMBELI", "CUSTOMER_AKTIF",
    }
    result = _default()
    result.update({
        "summary": _clean_string(value.get("summary"), 900) or result["summary"],
        "name": _clean_string(value.get("name"), 160),
        "business_name": _clean_string(value.get("business_name"), 160),
        "business_type": _clean_string(value.get("business_type"), 160),
        "location": _clean_string(value.get("location"), 160),
        "budget": _clean_string(value.get("budget"), 160),
        "interests": _clean_list(value.get("interests")),
        "needs": _clean_list(value.get("needs")),
        "buying_stage": stage if stage in allowed else "BELUM_JELAS",
        "buying_signal_reason": _clean_string(value.get("buying_signal_reason"), 500),
        "communication_notes": _clean_string(value.get("communication_notes"), 500),
        "missing_info": _clean_list(value.get("missing_info")),
        "follow_up": _clean_string(value.get("follow_up"), 700),
        "action": _clean_string(value.get("action"), 240),
        "job_status": value.get("job_status") if value.get("job_status") in
                      ("PERLU_TINDAKAN", "DIKERJAKAN", "BATAL") else None,
    })
    return result


def _stored(business_id, customer_id):
    try:
        with customers.transaction() as tx:
            row = tx.one(
                "SELECT * FROM kw_core_customer_insights WHERE business_id=? AND customer_id=?",
                (business_id, customer_id),
            )
    except Exception:
        return None
    if not row:
        return None
    try:
        insight = _normalize(json.loads(row["insight_json"]))
    except (TypeError, ValueError):
        insight = _default()
    return {
        "insight": insight,
        "core_cursor": int(row.get("core_message_cursor") or 0),
        "demo_cursor": int(row.get("demo_message_cursor") or 0),
        "message_count": int(row.get("analyzed_message_count") or 0),
        "updated_at": int(row.get("updated_at") or 0),
    }


def _demo_binding(business_id, phone):
    if not phone:
        return None
    try:
        with customers.transaction() as tx:
            row = tx.one(
                "SELECT detail FROM audit_log WHERE business_id=? AND action='demo_whatsapp_bound' "
                "ORDER BY id DESC LIMIT 1",
                (business_id,),
            )
    except Exception:
        return None
    if not row or not row.get("detail"):
        return None
    try:
        detail = json.loads(row["detail"])
    except (TypeError, ValueError):
        return None
    if not isinstance(detail, dict) or detail.get("phone") != phone:
        return None
    try:
        start = int(detail.get("start_message_id") or 0)
    except (TypeError, ValueError):
        return None
    return {"phone": phone, "start_message_id": start} if start > 0 else None


def _core_messages(business_id, customer_id, after):
    try:
        with customers.transaction() as tx:
            return tx.execute(
                "SELECT m.id,m.role,m.content,m.created_at,w.id AS conversation_id "
                "FROM kw_web_customer_links l "
                "JOIN kw_web_conversations w ON w.business_id=l.business_id AND w.id=l.conversation_id "
                "JOIN kw_core_wa_conversations wa ON wa.business_id=w.business_id AND wa.conversation_id=w.id "
                "JOIN kw_web_messages m ON m.business_id=w.business_id AND m.conversation_id=w.id "
                "WHERE l.business_id=? AND l.customer_id=? AND w.id LIKE 'wa_%' AND m.id>? "
                "ORDER BY m.id ASC LIMIT ?",
                (business_id, customer_id, int(after), MAX_NEW_MESSAGES),
            )
    except Exception:
        return []


def whatsapp_conversation_rows(business_id, customer_id):
    """Conversation cards that belong to the active WhatsApp Inbox only."""
    try:
        with customers.transaction() as tx:
            return tx.execute(
                "SELECT w.id,w.mode,w.created_at,w.updated_at,"
                "(SELECT content FROM kw_web_messages m WHERE m.business_id=w.business_id "
                "AND m.conversation_id=w.id ORDER BY m.id DESC LIMIT 1) AS preview "
                "FROM kw_web_customer_links l "
                "JOIN kw_web_conversations w ON w.business_id=l.business_id AND w.id=l.conversation_id "
                "JOIN kw_core_wa_conversations wa ON wa.business_id=w.business_id AND wa.conversation_id=w.id "
                "WHERE l.business_id=? AND l.customer_id=? AND w.id LIKE 'wa_%' "
                "ORDER BY w.updated_at DESC",
                (business_id, customer_id),
            )
    except Exception:
        return []


def _platform_messages(business_id, customer, after):
    if not platform_workspace.is_scope_business(business_id):
        return []
    phone = platform_inbox_service.normalize_customer_phone(customer.get("phone"))
    if not phone:
        return []
    try:
        rows = db.query_all(
            "SELECT id,role,content,created_at FROM messages "
            "WHERE number=? AND mode='customer' AND id>? "
            "ORDER BY id ASC LIMIT ?",
            (phone, int(after), MAX_NEW_MESSAGES),
        )
    except Exception:
        return []
    cleaned = []
    for raw in rows:
        row = dict(raw)
        row["_source"] = "PLATFORM_WHATSAPP"
        cleaned.append(row)
    return cleaned


def platform_conversation_row(business_id, customer):
    if not platform_workspace.is_scope_business(business_id):
        return None
    phone = platform_inbox_service.normalize_customer_phone(customer.get("phone"))
    if not phone:
        return None
    try:
        row = db.query_one(
            "SELECT id,role,content,created_at FROM messages "
            "WHERE number=? AND mode='customer' ORDER BY id DESC LIMIT 1",
            (phone,),
        )
    except Exception:
        return None
    if not row:
        return None
    try:
        mode = platform_inbox_service.get_state(phone) if platform_inbox_service.customer_exists(phone) else "AI_ACTIVE"
    except Exception:
        mode = "STATE_UNAVAILABLE"
    return {
        "id": "platform:" + phone,
        "mode": mode,
        "created_at": row.get("created_at"),
        "updated_at": row.get("created_at"),
        "preview": row.get("content") or "",
        "is_platform": True,
        "phone": phone,
    }


def _demo_messages(business_id, customer, after):
    binding = _demo_binding(business_id, customer.get("phone"))
    if not binding:
        return []
    minimum = max(binding["start_message_id"], int(after) + 1)
    try:
        rows = db.query_all(
            "SELECT id,role,content,created_at FROM messages "
            "WHERE number=? AND mode IN ('customer','owner') AND id>=? "
            "ORDER BY id ASC LIMIT ?",
            (binding["phone"], minimum, MAX_NEW_MESSAGES),
        )
    except Exception:
        return []
    cleaned = []
    for raw in rows:
        row = dict(raw)
        content = str(row.get("content") or "")
        lowered = content.lower()
        # Binding handshake proves ownership of this one thread but should not influence CRM intent.
        if row.get("role") == "user" and ("demo id:" in lowered or "kwdemo-" in lowered):
            continue
        if row.get("role") == "assistant" and (
            "demo aktif" in lowered or "demo.kilasworks.id" in lowered or "kode demo" in lowered
        ):
            continue
        row["_source"] = "DEMO_WHATSAPP"
        cleaned.append(row)
    return cleaned


def source_state(business_id, customer_id):
    customer = customers.get_customer(business_id, customer_id)
    stored = _stored(business_id, customer_id)
    core_cursor = stored["core_cursor"] if stored else 0
    demo_cursor = stored["demo_cursor"] if stored else 0
    core = _core_messages(business_id, customer_id, core_cursor)
    legacy = (
        _platform_messages(business_id, customer, demo_cursor)
        if platform_workspace.is_scope_business(business_id)
        else _demo_messages(business_id, customer, demo_cursor)
    )
    return customer, stored, core, legacy


def _transcript(core, demo):
    # Each source is already in durable ascending message order. Do not parse created_at here:
    # the legacy platform message table can use a datetime string while Core uses epoch seconds.
    rows = []
    for row in core:
        who = "CUSTOMER" if row.get("role") == "user" else "BUSINESS"
        rows.append(f"[{who}][WHATSAPP] {str(row.get('content') or '')[:MAX_MESSAGE_CHARS]}")
    for row in demo:
        who = "CUSTOMER" if row.get("role") == "user" else "BUSINESS"
        source = row.get("_source") or "DEMO_WHATSAPP"
        rows.append(f"[{who}][{source}] {str(row.get('content') or '')[:MAX_MESSAGE_CHARS]}")
    text = "\n".join(rows)
    return text[-MAX_TRANSCRIPT_CHARS:]


def _parse(text):
    try:
        return _normalize(ai_onboarding._extract_json_object(text))
    except Exception:
        return None


def refresh(business, customer):
    business_id, customer_id = business["id"], customer["id"]
    customer, stored, core, demo = source_state(business_id, customer_id)
    previous = stored["insight"] if stored else _default()
    if not core and not demo:
        result = dict(previous)
        result["_meta"] = {
            "updated_at": stored["updated_at"] if stored else None,
            "message_count": stored["message_count"] if stored else 0,
            "fresh": True,
            "has_history": bool(stored and stored["message_count"]),
        }
        return result

    transcript = _transcript(core, demo)
    payload = (
        "INSIGHT SEBELUMNYA:\n" + json.dumps(previous, ensure_ascii=False) +
        "\n\nPESAN BARU SEJAK ANALISIS TERAKHIR:\n" + transcript
    )
    with ai_usage.scope(business_id, "customer_insight"):
        raw, stop_reason, error = ai_onboarding._call_claude(
            SYSTEM_PROMPT,
            [{"role": "user", "content": payload}],
            max_tokens=1200,
            model=ai_onboarding.CLIENT_HUB_SIMULATION_MODEL,
        )
    if error or stop_reason == "max_tokens":
        result = dict(previous)
        result["_meta"] = {
            "updated_at": stored["updated_at"] if stored else None,
            "message_count": stored["message_count"] if stored else 0,
            "fresh": False,
            "has_history": bool(core or demo or (stored and stored["message_count"])),
            "error": True,
        }
        return result

    insight = _parse(raw)
    if insight is None:
        result = dict(previous)
        result["_meta"] = {
            "updated_at": stored["updated_at"] if stored else None,
            "message_count": stored["message_count"] if stored else 0,
            "fresh": False,
            "has_history": True,
            "error": True,
        }
        return result

    core_cursor = max([stored["core_cursor"] if stored else 0] + [int(r["id"]) for r in core])
    demo_cursor = max([stored["demo_cursor"] if stored else 0] + [int(r["id"]) for r in demo])
    count = (stored["message_count"] if stored else 0) + len(core) + len(demo)
    now = int(time.time())
    with customers.transaction() as tx:
        tx.execute(
            "INSERT INTO kw_core_customer_insights"
            "(business_id,customer_id,insight_json,core_message_cursor,demo_message_cursor,"
            "analyzed_message_count,updated_at) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(business_id,customer_id) DO UPDATE SET "
            "insight_json=excluded.insight_json,core_message_cursor=excluded.core_message_cursor,"
            "demo_message_cursor=excluded.demo_message_cursor,"
            "analyzed_message_count=excluded.analyzed_message_count,updated_at=excluded.updated_at",
            (business_id, customer_id, json.dumps(insight, ensure_ascii=False),
             core_cursor, demo_cursor, count, now),
        )
    result = dict(insight)
    result["_meta"] = {
        "updated_at": now,
        "message_count": count,
        "fresh": True,
        "has_history": True,
    }
    return result


def demo_conversation_row(business_id, customer):
    binding = _demo_binding(business_id, customer.get("phone"))
    if not binding:
        return None
    try:
        rows = db.query_all(
            "SELECT id,role,content,created_at FROM messages "
            "WHERE number=? AND mode IN ('customer','owner') AND id>=? "
            "ORDER BY id DESC LIMIT 1",
            (binding["phone"], binding["start_message_id"]),
        )
    except Exception:
        return None
    if not rows:
        return None
    latest = dict(rows[0])
    return {
        "id": "demo:" + binding["phone"],
        "mode": "AI_ACTIVE",
        "created_at": latest.get("created_at"),
        "updated_at": latest.get("created_at"),
        "preview": latest.get("content") or "",
        "is_demo": True,
        "phone": binding["phone"],
    }


def safe_refresh(business, customer):
    """Never let Customer Insight availability break the CRM detail page."""
    try:
        return refresh(business, customer)
    except Exception:
        result = _default()
        result["_meta"] = {
            "updated_at": None,
            "message_count": 0,
            "fresh": False,
            "has_history": False,
            "error": True,
        }
        return result
