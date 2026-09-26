"""Owner-visible, bounded explanation metadata for AI replies.

This module never stores or exposes chain-of-thought, hidden prompts, provider internals, tokens,
or raw model reasoning. It records only product-level decision metadata that is already safe for
the business owner: detected intent, workflow, evidence-backed fields, missing/uncertain fields,
source categories, guardrails and system action/result.
"""
import json

import db
from kilas_core.playbook_definitions import FIELD_LABELS

ACTION = "AI_REPLY_EXPLANATION"
VERSION = 1
_MAX_DETAIL = 10000
_INTENTS = {
    "REQUEST": "Permintaan customer",
    "CONTINUE": "Melengkapi permintaan",
    "NEW_REQUEST": "Permintaan baru",
    "BUSINESS_QUESTION": "Pertanyaan bisnis",
    "UNRELATED": "Di luar konteks bisnis",
    "HUMAN": "Minta bantuan manusia",
    "UNSUPPORTED": "Perlu ditinjau tim",
}


def _text(value, limit=300):
    value = str(value or "").strip()
    return value[:limit]


def _list(values, limit=12):
    out = []
    for value in values or ():
        item = _text(value, 220)
        if item and item not in out:
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _facts(fields):
    out = []
    for key, value in dict(fields or {}).items():
        label = FIELD_LABELS.get(key, key)
        out.append({"label": _text(label, 120), "value": _text(value, 300)})
        if len(out) >= 12:
            break
    return out


def _trace(title, *, summary="", intent="", workflow="", basis=(), facts=(), missing=(), uncertain=(),
           guardrails=(), action="", result="", route=""):
    payload = {
        "title": _text(title, 180),
        "summary": _text(summary, 600),
        "intent": _text(intent, 180),
        "workflow": _text(workflow, 180),
        "basis": _list(basis),
        "facts": list(facts)[:12],
        "missing": _list(missing),
        "uncertain": _list(uncertain),
        "guardrails": _list(guardrails),
        "action": _text(action, 500),
        "result": _text(result, 500),
        "route": _text(route, 80),
        "note": "Ini jejak keputusan produk, bukan chain-of-thought internal model.",
    }
    return payload


def simple_greeting():
    return _trace(
        "Sapaan sederhana",
        summary="AI mengenali pesan sebagai sapaan singkat, jadi tidak membuat Job atau mengubah data dan hanya membuka percakapan.",
        intent="Sapaan",
        basis=("Pesan customer hanya berupa sapaan/test singkat.",),
        guardrails=("Sapaan tidak boleh membuat Job atau mengubah data customer.",),
        action="Tidak ada perubahan data.",
        result="AI mengarahkan customer kembali ke produk atau layanan bisnis.",
        route="simple_greeting",
    )


def blocked_workflow():
    return _trace(
        "Perlu ditinjau tim",
        summary="AI tidak melanjutkan otomatis karena state pekerjaan yang ada berisiko tertimpa atau menjadi duplikat, jadi percakapan diarahkan ke tim.",
        intent="Permintaan operasional",
        basis=("Percakapan sudah memiliki state pekerjaan yang tidak aman untuk diubah otomatis.",),
        guardrails=("AI tidak boleh membuat pekerjaan ganda atau menimpa perubahan owner.",),
        action="Tidak ada perubahan otomatis.",
        result="Customer diarahkan agar tim meninjau permintaan.",
        route="workflow_guard",
    )


def stale_update():
    return _trace(
        "Data baru saja diperbarui owner",
        summary="AI membatalkan update karena owner sudah mengubah rincian setelah proses AI dimulai. Perubahan owner diprioritaskan agar tidak tertimpa.",
        intent="Konflik versi",
        basis=("Rincian pekerjaan berubah setelah AI mulai memproses pesan.",),
        guardrails=("Perubahan owner tidak boleh ditimpa oleh hasil AI yang lebih lama.",),
        action="Update AI dibatalkan.",
        result="Customer diminta mengonfirmasi perubahan yang masih dibutuhkan.",
        route="stale_version",
    )


def core_decision(book, interpretation, decision, *, category="", write_applied=False):
    missing = []
    for group in decision.missing:
        missing.append(" atau ".join(FIELD_LABELS.get(key, key) for key in group.split("|")))
    uncertain = [FIELD_LABELS.get(key, key) for key in decision.uncertain]
    basis = [
        "Pesan customer terakhir.",
        "Riwayat percakapan yang relevan untuk memahami jawaban singkat.",
        "Kategori bisnis menentukan workflow: " + _text(category or "umum", 100) + ".",
    ]
    guardrails = [
        "Field hanya diterima bila tervalidasi dari pesan customer; nilai ambigu tidak ditebak.",
        "AI tidak boleh mengarang harga, stok, slot booking, pembayaran, saldo, atau status transaksi.",
        "Perubahan owner dan versi Job yang lebih baru tidak boleh ditimpa.",
    ]
    if decision.reason == "business_question":
        result = "AI meminta kebutuhan yang lebih spesifik agar informasi dapat dikonfirmasi dengan benar."
    elif decision.uncertain:
        result = "AI meminta klarifikasi pada informasi yang masih ambigu."
    elif decision.missing:
        result = "AI meminta informasi yang masih diperlukan sebelum permintaan dianggap lengkap."
    elif decision.reason in ("human", "unsupported", "needs_owner"):
        result = "AI mengarahkan percakapan ke tim manusia."
    elif decision.reason == "unrelated":
        result = "AI mengembalikan percakapan ke konteks produk atau layanan bisnis."
    else:
        result = "AI memberi balasan berdasarkan state permintaan yang tervalidasi."
    summary = (
        "AI memahami pesan sebagai " + _INTENTS.get(interpretation.intent, interpretation.intent).lower() + ". "
        + result
    )
    return _trace(
        "Dasar balasan AI",
        summary=summary,
        intent=_INTENTS.get(interpretation.intent, interpretation.intent),
        workflow=getattr(book, "label", "") or getattr(book, "code", ""),
        basis=basis,
        facts=_facts(interpretation.fields),
        missing=missing,
        uncertain=uncertain,
        guardrails=guardrails,
        action=("Job dibuat/diperbarui dari fakta yang tervalidasi."
                if write_applied else "Tidak ada perubahan Job pada balasan ini."),
        result=result,
        route="core_playbook",
    )


def generic_model(*, has_business_data=False, has_image=False):
    basis = ["Pesan customer terakhir.", "Riwayat percakapan yang relevan."]
    if has_business_data:
        basis.append("Profil/knowledge bisnis yang tersimpan.")
    if has_image:
        basis.append("Gambar yang dikirim customer.")
    return _trace(
        "Dasar balasan AI",
        summary="AI menjawab sebagai customer service dari pesan terakhir, riwayat yang relevan, dan data bisnis yang tersedia. Jika detail belum cukup, AI harus meminta klarifikasi daripada mengarang.",
        intent="Jawaban customer service",
        basis=basis,
        guardrails=(
            "AI tidak boleh mengarang harga atau informasi bisnis yang tidak tersedia.",
            "AI tidak boleh mengaku pesanan, booking, invoice, pembayaran, atau pengiriman sudah terjadi tanpa aksi sistem yang sah.",
        ),
        action="Balasan percakapan saja; tidak otomatis mengubah transaksi.",
        result="AI menjawab dari konteks yang tersedia dan meminta klarifikasi bila informasi belum cukup.",
        route="generic_model",
    )


def legacy(route, *, has_image=False, has_business_data=True, customer_text="", reply_text=""):
    labels = {
        "demo_handshake": ("Aktivasi demo", "Sistem mengenali kode Demo WhatsApp yang valid."),
        "order_rule": ("Alur order terstruktur", "Permintaan cocok dengan aturan order/checkout yang tersedia."),
        "deterministic_rule": ("Aturan deterministik", "Pesan cocok dengan aturan produk yang tidak memerlukan model bebas."),
        "catalog_exact": ("Katalog resmi", "Pertanyaan dijawab dari data katalog yang tersedia."),
        "vision_model": ("Analisis gambar", "AI memakai gambar customer bersama konteks percakapan."),
        "model_reply": ("Jawaban AI", "AI memakai konteks percakapan dan data bisnis yang tersedia."),
    }
    title, result = labels.get(route, labels["model_reply"])
    customer_text = _text(customer_text, 240)
    reply_text = _text(reply_text, 240)
    lower_reply = reply_text.casefold()
    asks_clarification = "?" in reply_text or any(
        token in lower_reply for token in ("mau ", "boleh ", "apa nih", "yang mana", "bisa kasih", "mohon ")
    )
    if route == "vision_model":
        summary = "AI memakai gambar customer bersama konteks chat untuk menyusun balasan, tanpa menganggap isi gambar sebagai transaksi yang sudah terjadi."
    elif route in ("catalog_exact", "deterministic_rule", "order_rule"):
        summary = result
    elif asks_clarification and customer_text:
        summary = (
            "Customer baru memberi konteks: “" + customer_text + "”. "
            "Balasan AI meminta kebutuhan/detail berikutnya karena informasi yang terlihat belum cukup spesifik untuk mengambil tindakan yang lebih jauh."
        )
    elif customer_text:
        summary = (
            "AI merespons pesan customer “" + customer_text + "” menggunakan konteks percakapan dan data bisnis yang tersedia."
        )
    else:
        summary = result
    basis = ["Pesan customer terakhir.", "Riwayat percakapan yang relevan."]
    if has_business_data:
        basis.append("Profil/katalog/knowledge bisnis yang tersedia.")
    if has_image:
        basis.append("Gambar customer yang diproses oleh model vision.")
    return _trace(
        title,
        summary=summary,
        intent="Customer service",
        basis=basis,
        guardrails=(
            "Tidak boleh mengarang harga, ketersediaan, booking, pembayaran, atau status transaksi.",
            "Jika informasi belum cukup, balasan harus meminta klarifikasi atau menyatakan perlu dicek.",
        ),
        action="Tidak ada aksi keuangan hanya karena AI menulis balasan.",
        result=result,
        route=route,
    )


def _encode(scope, analysis, **identity):
    detail = {"v": VERSION, "scope": scope, **identity, "analysis": analysis}
    raw = json.dumps(detail, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > _MAX_DETAIL:
        raise ValueError("explanation_too_large")
    return raw


def save_core(tx, business_id, conversation_id, event_id, analysis):
    """Best-effort audit metadata: never make the customer reply depend on this write."""
    try:
        raw = _encode("core", analysis, conversation_id=conversation_id, event_id=event_id)
        tx.execute(
            "INSERT INTO audit_log(actor_user_id,business_id,action,detail) VALUES (NULL,?,?,?)",
            (business_id, ACTION, raw),
        )
        return True
    except Exception:
        return False


def load_core(business_id, conversation_id, event_ids):
    wanted = {str(value) for value in event_ids if value}
    if not wanted:
        return {}
    try:
        rows = db.query_all(
            "SELECT detail FROM audit_log WHERE business_id=? AND action=? ORDER BY id DESC LIMIT 500",
            (business_id, ACTION),
        )
    except Exception:
        return {}
    out = {}
    for row in rows:
        try:
            item = json.loads(row.get("detail") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if item.get("scope") != "core" or item.get("conversation_id") != conversation_id:
            continue
        event_id = str(item.get("event_id") or "")
        if event_id in wanted and event_id not in out and isinstance(item.get("analysis"), dict):
            out[event_id] = item["analysis"]
            if len(out) == len(wanted):
                break
    return out


def record_latest_legacy(business_id, number, analysis):
    """Attach a safe trace to the latest assistant message for this scoped legacy/demo thread."""
    try:
        row = db.query_one(
            "SELECT id FROM messages WHERE number=? AND mode='customer' AND role='assistant' "
            "ORDER BY id DESC LIMIT 1",
            (number,),
        )
        if not row:
            return False
        message_id = int(row["id"])
        recent = db.query_all(
            "SELECT detail FROM audit_log WHERE business_id=? AND action=? ORDER BY id DESC LIMIT 80",
            (business_id, ACTION),
        )
        for audit in recent:
            try:
                item = json.loads(audit.get("detail") or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if item.get("scope") == "legacy" and int(item.get("message_id") or 0) == message_id:
                return True
        raw = _encode("legacy", analysis, message_id=message_id)
        db.execute(
            "INSERT INTO audit_log(actor_user_id,business_id,action,detail) VALUES (NULL,?,?,?)",
            (business_id, ACTION, raw),
        )
        return True
    except Exception:
        return False


def _legacy_visible_fallback(customer_text, reply_text):
    """Honest fallback for old messages that predate explanation audit metadata."""
    customer_text = _text(customer_text, 240)
    reply_text = _text(reply_text, 240)
    lower_reply = reply_text.casefold()
    asks_clarification = "?" in reply_text or any(
        token in lower_reply for token in ("mau ", "boleh ", "apa nih", "yang mana", "bisa kasih", "mohon ")
    )
    if asks_clarification and customer_text:
        summary = (
            "Customer memberi konteks: “" + customer_text + "”. "
            "Balasan AI terlihat meminta kebutuhan/detail berikutnya karena pesan tersebut belum cukup spesifik untuk menentukan tindakan."
        )
    elif customer_text:
        summary = (
            "Balasan AI terlihat menanggapi pesan customer “" + customer_text + "” berdasarkan konteks chat yang tersedia."
        )
    else:
        summary = "Pesan ini dibuat sebelum fitur jejak keputusan aktif, jadi hanya hubungan isi chat yang dapat diringkas."
    return _trace(
        "Ringkasan pesan lama",
        summary=summary,
        intent="Ringkasan dari isi chat",
        basis=("Pesan customer yang terlihat sebelum balasan ini.", "Isi balasan AI yang terlihat."),
        guardrails=("Ini bukan jejak keputusan asli karena pesan dibuat sebelum fitur Analisa aktif.",),
        action="Tidak dapat dipastikan dari audit lama.",
        result="Ringkasan ini hanya menjelaskan hubungan isi percakapan yang terlihat.",
        route="legacy_visible_fallback",
    )


def attach_demo(rows, business_id, *, allow_visible_fallback=False):
    ids = {int(row.get("id") or 0) for row in rows if row.get("role") == "assistant" and row.get("id")}
    if not ids:
        return rows
    try:
        audits = db.query_all(
            "SELECT detail FROM audit_log WHERE business_id=? AND action=? ORDER BY id DESC LIMIT 500",
            (business_id, ACTION),
        )
    except Exception:
        audits = []
    found = {}
    for audit in audits:
        try:
            item = json.loads(audit.get("detail") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if item.get("scope") != "legacy":
            continue
        mid = int(item.get("message_id") or 0)
        if mid in ids and mid not in found and isinstance(item.get("analysis"), dict):
            found[mid] = item["analysis"]
    last_customer = ""
    for row in rows:
        if row.get("role") == "user":
            last_customer = str(row.get("content") or "")
            continue
        if row.get("role") != "assistant":
            continue
        mid = int(row.get("id") or 0)
        if mid in found:
            row["analysis"] = found[mid]
        elif allow_visible_fallback:
            row["analysis"] = _legacy_visible_fallback(last_customer, row.get("content") or "")
    return rows
