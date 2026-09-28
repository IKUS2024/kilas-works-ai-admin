"""Convert Customer Insight into one clean owner action Job per customer.

This is intentionally downstream of Customer Insight: chat delivery never waits on Jobs,
and raw chat text never writes a Job directly. The structured Insight decides whether there is
an actionable next step. Existing manual/playbook Jobs always win to avoid duplicate work.
"""
from contextlib import nullcontext
import hashlib
import json
import re

import db
from kilas_core import customer_insights, customers, jobs


TERMINAL = {"COMPLETED", "CANCELLED"}
SIGNAL_TO_STATUS = {
    "PERLU_TINDAKAN": "NEW",
    "DIKERJAKAN": "IN_PROGRESS",
    "BATAL": "CANCELLED",
}

# High-recall prefilter only. It NEVER promotes by itself; it only decides whether a Lead's
# platform WhatsApp history is worth sending through the existing Customer Insight classifier.
# Customer Insight remains the authority for whether the customer actually requested a concrete
# action, so "mau tanya harga" / FAQ / comparison can safely stay Lead.
_PLATFORM_ACTION_HINT = re.compile(
    r"\b(mau|ingin|booking|reservasi|pesan|order|beli|payment|bayar|invoice|"
    r"lanjut|deal|fix|setuju|butuh|minta|pakai|bisa\s+bantu)\b",
    re.IGNORECASE,
)
_PLATFORM_SYSTEM_MARKERS = ("[FOLLOW-UP OTOMATIS SISTEM]",)
_CONTINUATION_WORDS = {
    "iya", "ya", "oke", "ok", "baik", "boleh", "gas", "deal", "fix", "jadi",
    "setuju", "mau", "ingin", "lanjut", "lanjutkan", "melanjutkan", "dong",
    "saya", "aku", "kami", "saja", "ambil",
}
_CONTINUATION_RE = re.compile(
    r"^(?:(?:iya|ya|oke|ok|baik|boleh|gas|deal|fix|jadi|setuju)\s+)*(?:saya\s+|aku\s+|kami\s+)?"
    r"(?:(?:mau|ingin|siap)\s+)?(?:(?:menggunakan layanan|ambil|melanjutkan|lanjutkan|lanjut)\s*)?(?:dong)?$",
    re.IGNORECASE,
)

# "Dikerjakan" is the commercial handoff state: invoice/payment has started.
# Meeting/booking/scheduling/deal language alone must remain "Perlu tindakan".
_PAYMENT_STEP_HINT = re.compile(
    r"\b(bayar|pembayaran|payment|pay|paid|invoice|tagihan|billing|payment\s+link|"
    r"transfer|dp|down\s+payment|deposit|pelunasan|lunas|rekening|"
    r"bukti\s+(?:bayar|pembayaran))\b",
    re.IGNORECASE,
)
_PAYMENT_STEP_META = "payment_step_reached"


def _payment_step_text(*values):
    text = " ".join(_clean(value, 900) for value in values if _clean(value, 900))
    # Negative / hypothetical clauses do not establish a payment stage.
    clauses = re.split(r'[,;.!?\n]|\btapi\b|\btetapi\b', text.lower())
    return any(_PAYMENT_STEP_HINT.search(clause) and not re.search(
        r'\b(belum|tidak|jangan|nggak|enggak|gak|ga|bukan|tanpa|nanti kalau|jika|kalau|apakah)\b', clause)
        for clause in clauses)


def _insight_payment_step(insight):
    if not isinstance(insight, dict):
        return False
    if '_payment_evidence' in insight:
        return bool(insight['_payment_evidence']) and _payment_step_text(insight['_payment_evidence'])
    return _payment_step_text(
        insight.get("action"),
        insight.get("summary"),
        insight.get("buying_signal_reason"),
    )


def _job_payment_step(job):
    fields = (job or {}).get("fields") or {}
    if fields.get(_PAYMENT_STEP_META) == "true":
        return True
    return _payment_step_text(
        fields.get("action"),
        fields.get("details"),
        (job or {}).get("summary"),
    )

def _clean(value, maximum=700):
    if not isinstance(value, str):
        return ""
    return value.strip()[:maximum]


def _list(value):
    if not isinstance(value, list):
        return []
    return [_clean(item, 180) for item in value[:8] if _clean(item, 180)]


def _is_continuation(value):
    text = _clean(value, 240).strip(" .,!?").casefold()
    if not text:
        return False
    if _CONTINUATION_RE.fullmatch(text):
        return True
    words = re.findall(r"[\w]+", text)
    return bool(words) and all(word in _CONTINUATION_WORDS for word in words)


def _request_action(insight, current=None):
    """Return a semantic request, carrying the prior request through short confirmations."""
    action = _clean(insight.get("action"), 240)
    if action and not _is_continuation(action):
        return action
    previous = ((current or {}).get("fields") or {}).get("action")
    if previous and not _is_continuation(previous):
        return _clean(previous, 240)
    # A verified topic may repair an older AI Job whose stored action is only a
    # continuation phrase. Do not use Insight needs/interests to create a fresh Job.
    if current:
        for value in [*_list(insight.get("needs")), *_list(insight.get("interests"))]:
            if not _is_continuation(value):
                return value
    return ""


def _operational_title(action):
    """Turn a verified request into a short work title; reject conversational replies."""
    action = _clean(action, 240).strip(" .,!?")
    if not action or _is_continuation(action):
        return ""
    action = re.sub(r"^(?:(?:iya|ya|oke|ok|baik|boleh|gas|deal|fix|jadi)\s+)*", "", action, flags=re.I)
    action = re.sub(r"^(?:saya|aku|kami)\s+(?:(?:mau|ingin|butuh)\s+)?", "", action, flags=re.I)
    match = re.match(r"^(?:mau|ingin|butuh|tolong)\s+(.+)$", action, flags=re.I)
    if match:
        action = match.group(1).strip()
    transforms = (
        (r"^urus(?:kan)?\s+(.+)$", r"Proses pengurusan \1"),
        (r"^cari(?:kan)?\s+(.+)$", r"Carikan \1"),
        (r"^(?:pesan|memesan)\s+(.+)$", r"Siapkan pesanan \1"),
        (r"^(?:beli|membeli|order)\s+(.+)$", r"Proses pesanan \1"),
        (r"^booking\s+(.+)$", r"Atur booking \1"),
        (r"^(?:ambil|gunakan|menggunakan)\s+(.+)$", r"Proses pesanan \1"),
        (r"^jadwalkan\s+(.+)$", r"Jadwalkan \1"),
        (r"^(?:buatkan|buat)\s+(.+)$", r"Siapkan \1"),
        (r"^kirim(?:kan)?\s+(?:proposal|penawaran)\s+(.+)$", r"Siapkan proposal \1"),
        (r"^perbaiki\s+(.+)$", r"Jadwalkan perbaikan \1"),
    )
    transformed = False
    for pattern, replacement in transforms:
        normalized = re.sub(pattern, replacement, action, count=1, flags=re.I)
        if normalized != action:
            action = normalized
            transformed = True
            break
    if not transformed:
        action = "Tindak lanjuti permintaan " + action
    action = action[:1].upper() + action[1:]
    return action[:160]


def _customer_summary(insight, action, *, continuing=False):
    topic = action[:1].lower() + action[1:] if action else ""
    topic = re.sub(r"^(?:(?:iya|ya|oke|ok|baik|boleh|gas|deal|fix|jadi)\s+)*(?:saya|aku|kami)\s+(?:(?:mau|ingin|butuh)\s+)?", "", topic, flags=re.I)
    topic = re.sub(r"^(?:mau|ingin|butuh|tolong)\s+", "", topic, flags=re.I)
    for pattern, replacement in (
        (r"^urus(?:kan)?\s+(.+)$", r"pengurusan \1"),
        (r"^cari(?:kan)?\s+(.+)$", r"mencari \1"),
        (r"^(?:pesan|memesan)\s+(.+)$", r"pesanan \1"),
        (r"^(?:beli|membeli|order)\s+(.+)$", r"pesanan \1"),
        (r"^buatkan\s+(.+)$", r"pembuatan \1"),
        (r"^jadwalkan\s+(.+)$", r"penjadwalan \1"),
    ):
        normalized = re.sub(pattern, replacement, topic, count=1, flags=re.I)
        if normalized != topic:
            topic = normalized
            break
    if not topic:
        topic = next(iter(_list(insight.get("needs"))), "") or next(iter(_list(insight.get("interests"))), "")
    if not topic:
        return _clean(insight.get("summary"), 420)
    if continuing:
        parts = [f"Customer ingin melanjutkan {topic}."]
    else:
        parts = [f"Customer meminta {topic}."]
    details = []
    for value in _list(insight.get("needs")):
        if value.casefold() not in topic.casefold() and value.casefold() not in " ".join(details).casefold():
            details.append(value)
    for value in (insight.get("schedule"), insight.get("budget")):
        if value and value.casefold() not in topic.casefold() and value.casefold() not in " ".join(details).casefold():
            details.append(value)
    if details:
        parts.append("Detail yang sudah dikonfirmasi: " + "; ".join(details) + ".")
    return " ".join(parts)[:420]


def _next_action(insight, *, continuing=False):
    missing = _list(insight.get("missing_info"))
    suggestion = _clean(insight.get("follow_up"), 300)
    confirmed = continuing or insight.get("buying_stage") == "SIAP_MEMBELI" \
        or insight.get("job_status") in ("PERLU_TINDAKAN", "DIKERJAKAN")
    if confirmed and missing:
        return "Konfirmasi " + ", ".join(missing[:3]) + " untuk melanjutkan permintaan customer."
    if confirmed and (not suggestion or re.search(r"(apakah|ingin|mau|akan).*\b(?:melanjutkan|lanjut)\b", suggestion, re.I)):
        return "Lanjutkan penanganan permintaan customer."
    if suggestion and not _is_continuation(suggestion):
        return suggestion
    if missing:
        return "Konfirmasi " + ", ".join(missing[:3]) + " kepada customer."
    return "Tindak lanjuti permintaan customer."


def _title_kind(action):
    text = _clean(action, 240).lower()
    if any(word in text for word in ("booking", "jadwal", "appointment", "reservasi", "janji")):
        return "Booking", "BOOKING"
    if any(word in text for word in ("foto", "photo", "video", "reels", "konten", "content", "website", "landing page")):
        return "Kebutuhan project", "PROJECT"
    if any(word in text for word in ("konsultasi", "meeting", "diskusi", "call", "telepon")):
        return "Konsultasi", "BOOKING"
    if any(word in text for word in ("beli", "pembelian", "order", "pesan")):
        return "Pembelian / pesanan", "ORDER"
    if any(word in text for word in ("proposal", "quotation", "penawaran")):
        return "Kirim penawaran", "SERVICE"
    return "Tindakan customer", "GENERIC"

def _fingerprint(insight):
    basis = {
        "action": _clean(insight.get("action"), 240),
        "summary": _clean(insight.get("summary"), 500),
        "job_status": insight.get("job_status"),
        "request_key": insight.get('_request_key'),
        "missing_info": insight.get('missing_info'),
        "schedule": insight.get('schedule'),
    }
    return hashlib.sha256(
        json.dumps(basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:20]

def _payload(insight, current=None):
    action = _request_action(insight, current=current)
    if not action:
        return None
    title = _operational_title(action)
    if not title:
        return None
    _, kind = _title_kind(action)
    continuing = _is_continuation(insight.get("action")) or bool(insight.get('_continuation_confirmed'))
    summary = _customer_summary(insight, action, continuing=continuing)
    ref = "insight:" + _fingerprint(insight)
    fields = {
        "action": action,
        "next_action": _next_action(insight, continuing=continuing),
        "source": "Customer Insight",
        "source_key": ref,
    }
    if insight.get('_request_key'):
        fields['request_key'] = insight['_request_key']
    if summary:
        fields["details"] = summary[:900]
    if insight.get('missing_info'):
        fields['missing_information'] = '; '.join(_list(insight['missing_info']))[:1000]
    if insight.get('schedule'):
        fields['scheduled_at'] = insight['schedule']
    if _insight_payment_step(insight):
        fields[_PAYMENT_STEP_META] = "true"
    return title, kind, summary, fields, ref

def _platform_candidate_needs_analysis(customer):
    """True only when a platform Lead has new customer text that may contain a concrete request."""
    phone = (customer or {}).get("phone")
    if not phone:
        return False
    try:
        stored = db.query_one(
            "SELECT demo_message_cursor,insight_json FROM kw_core_customer_insights "
            "WHERE business_id=? AND customer_id=?",
            (customer["business_id"], customer["id"]),
        )
        if stored and stored.get("insight_json"):
            try:
                previous = json.loads(stored["insight_json"])
            except (TypeError, ValueError):
                previous = {}
            if (
                isinstance(previous, dict)
                and _clean(previous.get("action"), 240)
                and previous.get("job_status") in ("PERLU_TINDAKAN", "DIKERJAKAN")
            ):
                # Old Insight may already prove intent even if no message is new. Let the
                # promotion step consume it without another model call.
                return True

        cursor = int((stored or {}).get("demo_message_cursor") or 0)
        rows = db.query_all(
            "SELECT id,content FROM messages WHERE number=? AND mode='customer' AND role='user' "
            "AND id>? ORDER BY id DESC LIMIT 80",
            (phone, cursor),
        )
    except Exception:
        return False
    for row in rows:
        text = str(row.get("content") or "").strip()
        if not text or any(marker in text for marker in _PLATFORM_SYSTEM_MARKERS):
            continue
        if _PLATFORM_ACTION_HINT.search(text):
            return True
    return False


def promote_lead_if_actionable(business, customer, insight, actor_id=None):
    """Promote a tenant-scoped Lead when Insight proves concrete intent.

    No keyword directly changes CRM stage. The existing Customer Insight contract must provide
    both a concrete action and a positive owner-facing job signal. Informational questions,
    comparisons, vague interest, and cancellations remain Lead.
    """
    if not business or not customer or not isinstance(insight, dict):
        return customer
    if customer.get("stage") != "LEAD":
        return customer
    meta = insight.get("_meta") or {}
    if not meta.get("has_history") or not meta.get("fresh"):
        return customer
    if not _clean(insight.get("action"), 240):
        return customer
    if insight.get("job_status") not in ("PERLU_TINDAKAN", "DIKERJAKAN"):
        return customer
    return customers.update_customer(
        business["id"], customer["id"],
        display_name=customer.get("display_name"),
        phone=customer.get("phone"),
        email=customer.get("email"),
        notes=customer.get("notes"),
        stage="CUSTOMER",
        actor_id=actor_id,
    )


def reconcile_actionable_platform_leads(business, actor_id=None, limit=3):
    """Bounded semantic reconciliation for platform Inbox Leads.

    The broad text prefilter only reduces model calls. Customer Insight makes the final decision.
    Once an informational Lead is analyzed, its message cursor advances, so later page loads move
    on to newer/unanalysed Leads instead of repeatedly analyzing the same contact.
    """
    if not business:
        return 0
    try:
        import platform_workspace
        if not platform_workspace.is_scope_business(business["id"]):
            return 0
    except Exception:
        return 0
    try:
        limit = max(1, min(int(limit or 3), 50))
    except (TypeError, ValueError):
        limit = 3
    try:
        with customers.transaction() as tx:
            leads = tx.execute(
                "SELECT c.*,COALESCE(s.stage,'CUSTOMER') AS stage "
                "FROM kw_core_customers c LEFT JOIN kw_core_customer_stages s "
                "ON s.business_id=c.business_id AND s.customer_id=c.id "
                "WHERE c.business_id=? AND COALESCE(s.stage,'CUSTOMER')='LEAD' "
                "ORDER BY c.last_activity_at DESC,c.id LIMIT 200",
                (business["id"],),
            )
    except Exception:
        return 0

    promoted_count = 0
    analyzed = 0
    for customer in leads:
        if analyzed >= limit:
            break
        if customer.get("source_channel") != "WHATSAPP":
            continue
        if not _platform_candidate_needs_analysis(customer):
            continue
        analyzed += 1
        insight = customer_insights.safe_refresh(business, customer)
        promoted = promote_lead_if_actionable(business, customer, insight, actor_id=actor_id)
        if not promoted or promoted.get("stage") != "CUSTOMER":
            continue
        promoted_count += 1
        try:
            sync_from_insight(business, promoted, insight)
        except Exception:
            pass
    return promoted_count


def sync_from_insight(business, customer, insight, *, transaction=None):
    """Keep one Customer Job aligned with the customer's concrete action and explicit deal/cancel signal."""
    if not jobs.enabled() or not business or not customer or not isinstance(insight, dict):
        return None
    if customer.get("stage") != "CUSTOMER":
        return None
    meta = insight.get("_meta") or {}
    if not meta.get("has_history") or meta.get("fresh") is False:
        return None

    signal = insight.get("job_status")
    # Deterministic safety gate: a model saying "DIKERJAKAN" is not enough. The
    # structured Customer Insight must also contain explicit payment/invoice evidence.
    if signal == "DIKERJAKAN" and not _insight_payment_step(insight):
        signal = "PERLU_TINDAKAN"
    target_status = SIGNAL_TO_STATUS.get(signal)
    payload = _payload(insight)
    continuation = _is_continuation(insight.get("action"))
    if payload is None and target_status not in ("IN_PROGRESS", "CANCELLED") and not continuation:
        return None

    if payload is not None:
        title, kind, summary, fields, ref = payload
    else:
        title = kind = summary = fields = None
        ref = "insight:" + _fingerprint(insight)

    bid, cid = business["id"], customer["id"]
    with (nullcontext(transaction) if transaction is not None else jobs.transaction()) as tx:
        jobs._lock(tx, bid)
        jobs._references(tx, bid, cid, None)
        rows = tx.execute(
            "SELECT * FROM kw_core_jobs WHERE business_id=? AND customer_id=? "
            "ORDER BY updated_at DESC,id DESC LIMIT 20",
            (bid, cid),
        )
        parsed = [jobs._row(row) for row in rows]
        active = [row for row in parsed if row["status"] not in TERMINAL]
        auto = [row for row in parsed if row["fields"].get("source") == "Customer Insight"]
        active_auto = [row for row in auto if row["status"] not in TERMINAL]
        active_manual = [row for row in active if row["fields"].get("source") != "Customer Insight"]

        def apply_status(current):
            if target_status not in ("IN_PROGRESS", "CANCELLED"):
                return current
            if current["owner_status"] == target_status:
                return current
            op = "customer_signal_" + hashlib.sha256(
                f"{cid}:{signal}:{ref}:{current['version']}".encode()
            ).hexdigest()
            return jobs._update_job(
                tx, bid, current["id"], expected_version=current["version"],
                actor_id=jobs._CUSTOMER_INSIGHT_ACTOR, operation_key=op,
                status=target_status,
            )

        request_key = insight.get('_request_key')
        separate = bool(insight.get('_separate_request'))
        matched = [row for row in auto if request_key and row['fields'].get('request_key') == request_key]
        if matched:
            if matched[0]['status'] in TERMINAL:
                return matched[0]  # Never resurrect a completed/cancelled request on a new detail.
            active_auto = [matched[0]]
        elif request_key:
            # Adopt a single historical auto Job, but never overwrite another identified request.
            if separate:
                active_auto = []
            elif len(active_auto) > 1:
                return None  # Ambiguous request: preserve all jobs for owner review.
            elif active_auto and active_auto[0]['fields'].get('request_key'):
                fields['request_key'] = active_auto[0]['fields']['request_key']
        if active_manual and not separate and not active_auto:
            return active_manual[0]

        if active_auto:
            current = active_auto[0]
            # A short confirmation inherits the existing semantic request; its wording
            # must never replace the operational title or create a second Job.
            if continuation:
                payload = _payload(insight, current=current)
                if payload:
                    title, kind, summary, fields, ref = payload
            if payload:
                # Retain owner-confirmed operational fields absent from a chat delta.
                fields = {**current['fields'], **fields}
                overrides = set(filter(None, current['fields'].get('owner_overrides', '').split(',')))
                if 'title' in overrides:
                    title = current['title']
                if 'summary' in overrides:
                    summary = current['summary']
                for key in jobs.FIELD_LABELS:
                    if key in overrides:
                        fields[key] = current['fields'].get(key, '')
                fields['missing_information'] = '; '.join(_list(insight.get('missing_info')))[:1000]
            current_payment_step = _job_payment_step(current)
            if payload and current_payment_step and fields.get(_PAYMENT_STEP_META) != "true":
                # Once a real payment/invoice step was reached, keep that fact durable even
                # when later chat moves on to scheduling or delivery details.
                fields = dict(fields)
                fields[_PAYMENT_STEP_META] = "true"
            status_arg = None
            if target_status in ("IN_PROGRESS", "CANCELLED") and current["owner_status"] != target_status:
                status_arg = target_status
            elif (target_status == "NEW" and current["status"] == "IN_PROGRESS"
                  and not current_payment_step):
                # Repair historical false positives where a meeting/booking/deal was
                # incorrectly promoted to Dikerjakan before any payment/invoice signal.
                status_arg = "NEW"
            content_changed = bool(payload) and (
                current["fields"].get("source_key") != ref
                or current["fields"].get("action") != fields.get("action")
                or current["fields"].get(_PAYMENT_STEP_META) != fields.get(_PAYMENT_STEP_META)
                or current["title"] != title
                or current["kind"] != kind
                or current["summary"] != summary
            )
            if not content_changed and status_arg is None:
                return current
            op = "customer_insight_" + hashlib.sha256(
                f"{cid}:{ref}:{signal}:{current['version']}".encode()
            ).hexdigest()
            return jobs._update_job(
                tx, bid, current["id"], expected_version=current["version"],
                actor_id=jobs._CUSTOMER_INSIGHT_ACTOR, operation_key=op,
                title=title if payload else None,
                summary=summary if payload else None,
                fields=fields if payload else None,
                kind=kind if payload else None,
                status=status_arg,
            )

        if payload is None or target_status == "CANCELLED":
            return None
        if auto and auto[0]["fields"].get("source_key") == ref:
            return auto[0]

        op = "customer_insight_" + hashlib.sha256(f"{cid}:{ref}:create".encode()).hexdigest()
        created = jobs._create_job(
            tx, bid, cid, title=title, actor_id=jobs._CUSTOMER_INSIGHT_ACTOR,
            operation_key=op, kind=kind, summary=summary, fields=fields,
        )
        if target_status == "IN_PROGRESS":
            op2 = "customer_signal_" + hashlib.sha256(
                f"{cid}:{ref}:deal:{created['version']}".encode()
            ).hexdigest()
            return jobs._update_job(
                tx, bid, created["id"], expected_version=created["version"],
                actor_id=jobs._CUSTOMER_INSIGHT_ACTOR, operation_key=op2,
                status="IN_PROGRESS",
            )
        return created

def refresh_and_sync(business, customer, actor_id=None):
    insight = customer_insights.safe_refresh(business, customer)
    try:
        customer = promote_lead_if_actionable(
            business, customer, insight, actor_id=actor_id
        ) or customer
        job = sync_from_insight(business, customer, insight)
    except Exception:
        job = None
    return insight, job


def repair_prepayment_in_progress_jobs(business_id, limit=200):
    """Repair old AI Jobs that reached Dikerjakan before invoice/payment intent.

    This is local database work only: no model call, Inbox rescan, or external request.
    Manual/playbook Jobs are excluded by the Customer Insight source marker.
    """
    if not jobs.enabled():
        return 0
    try:
        limit = max(1, min(int(limit or 200), 500))
    except (TypeError, ValueError):
        limit = 200
    with jobs.transaction() as tx:
        jobs._lock(tx, business_id)
        rows = tx.execute(
            "SELECT * FROM kw_core_jobs WHERE business_id=? AND status='IN_PROGRESS' "
            "AND fields_json LIKE ? ORDER BY updated_at DESC,id DESC LIMIT ?",
            (business_id, '%\"source\":\"Customer Insight\"%', limit),
        )
        repaired = 0
        for raw in rows:
            current = jobs._row(raw)
            if _job_payment_step(current):
                continue
            op = "customer_insight_payment_gate_repair_" + hashlib.sha256(
                f"{business_id}:{current['id']}:{current['version']}".encode()
            ).hexdigest()
            jobs._update_job(
                tx, business_id, current["id"], expected_version=current["version"],
                actor_id=jobs._CUSTOMER_INSIGHT_ACTOR, operation_key=op,
                status="NEW",
            )
            repaired += 1
        return repaired


def _table_exists(tx, table):
    if db.BACKEND == "postgres":
        row = tx.one("SELECT to_regclass(?) AS name", ("public." + table,))
        return bool(row and row.get("name"))
    row = tx.one("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return bool(row)


def _delete_job_dependencies(tx, business_id, job_id):
    # These tables reference Jobs without ON DELETE CASCADE in 0057/0058.
    # Older test/dev schemas may not have 0058 yet, so probe before touching optional tables.
    for table in ("kw_core_automation_runs", "kw_core_attention", "kw_core_job_operations"):
        if _table_exists(tx, table):
            tx.execute(f"DELETE FROM {table} WHERE business_id=? AND job_id=?",
                       (business_id, job_id))


def prune_invalid_lead_jobs(business_id):
    """Remove only AI-generated Customer Insight Jobs whose CRM owner is still a Lead.

    This repairs records created by the short-lived broad-intent implementation. Manual and
    playbook Jobs are never touched.
    """
    if not jobs.enabled():
        return 0
    with jobs.transaction() as tx:
        jobs._lock(tx, business_id)
        rows = tx.execute(
            "SELECT j.id FROM kw_core_jobs j "
            "JOIN kw_core_customer_stages s ON s.business_id=j.business_id AND s.customer_id=j.customer_id "
            "WHERE j.business_id=? AND s.stage='LEAD' "
            "AND j.fields_json LIKE ?",
            (business_id, '%"source":"Customer Insight"%'),
        )
        removed = 0
        for row in rows:
            _delete_job_dependencies(tx, business_id, row["id"])
            tx.execute("DELETE FROM kw_core_jobs WHERE business_id=? AND id=?",
                       (business_id, row["id"]))
            removed += 1
        return removed


def force_prune_invalid_lead_jobs_all():
    """One-shot production repair independent of feature flags.

    Narrow scope: only Customer Insight Jobs whose linked CRM stage is still LEAD.
    Manual/playbook Jobs are excluded by the source marker.
    """
    with jobs.transaction() as tx:
        rows = tx.execute(
            "SELECT j.business_id,j.id FROM kw_core_jobs j "
            "JOIN kw_core_customer_stages s ON s.business_id=j.business_id AND s.customer_id=j.customer_id "
            "WHERE s.stage='LEAD' AND j.fields_json LIKE ? "
            "ORDER BY j.business_id,j.id LIMIT 500",
            ('%"source":"Customer Insight"%',)
        )
        removed = 0
        for row in rows:
            # Customer Insight auto-Jobs created by this retired path have a Job operation row
            # but no owner/manual semantics. Remove the exact operation first to satisfy 0057 FK.
            tx.execute("DELETE FROM kw_core_job_operations WHERE business_id=? AND job_id=?",
                       (row["business_id"], row["id"]))
            tx.execute("DELETE FROM kw_core_jobs WHERE business_id=? AND id=?",
                       (row["business_id"], row["id"]))
            removed += 1
        return removed


def prune_invalid_lead_jobs_all():
    """Bounded startup reconciliation across only businesses that currently have invalid AI Lead Jobs."""
    if not jobs.enabled():
        return 0
    with jobs.transaction() as tx:
        rows = tx.execute(
            "SELECT DISTINCT j.business_id FROM kw_core_jobs j "
            "JOIN kw_core_customer_stages s ON s.business_id=j.business_id AND s.customer_id=j.customer_id "
            "WHERE s.stage='LEAD' AND j.fields_json LIKE ? "
            "ORDER BY j.business_id LIMIT 200",
            ('%"source":"Customer Insight"%',)
        )
    return sum(prune_invalid_lead_jobs(int(row["business_id"])) for row in rows)


def reconcile_business(business, limit=10):
    """Reconcile only confirmed Customers; Leads never create Jobs."""
    if not jobs.enabled() or not business:
        return 0
    try:
        rows, _, _, _ = customers.list_customers(business["id"], page=1, stage="CUSTOMER")
    except Exception:
        return 0
    synced = 0
    for customer in rows[:max(1, min(int(limit or 10), 10))]:
        if customer.get("source_channel") != "WHATSAPP":
            continue
        try:
            insight = customer_insights.safe_refresh(business, customer)
            if sync_from_insight(business, customer, insight):
                synced += 1
        except Exception:
            continue
    return synced
