"""Convert Customer Insight into one clean owner action Job per customer.

This is intentionally downstream of Customer Insight: chat delivery never waits on Jobs,
and raw chat text never writes a Job directly. The structured Insight decides whether there is
an actionable next step. Existing manual/playbook Jobs always win to avoid duplicate work.
"""
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
    r"\\b(mau|ingin|booking|reservasi|pesan|order|beli|payment|bayar|invoice|"
    r"lanjut|deal|fix|setuju|butuh|minta|pakai|bisa\\s+bantu)\\b",
    re.IGNORECASE,
)
_PLATFORM_SYSTEM_MARKERS = ("[FOLLOW-UP OTOMATIS SISTEM]",)

def _clean(value, maximum=700):
    if not isinstance(value, str):
        return ""
    return value.strip()[:maximum]


def _list(value):
    if not isinstance(value, list):
        return []
    return [_clean(item, 180) for item in value[:8] if _clean(item, 180)]


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
    }
    return hashlib.sha256(
        json.dumps(basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:20]

def _payload(insight):
    action = _clean(insight.get("action"), 240)
    if not action:
        return None
    title, kind = _title_kind(action)
    summary = _clean(insight.get("summary"), 420)
    ref = "insight:" + _fingerprint(insight)
    fields = {
        "action": action,
        "source": "Customer Insight",
        "source_key": ref,
    }
    if summary:
        fields["details"] = summary[:420]
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
    """Promote only the hidden Kilas Works platform Lead when Insight proves concrete intent.

    No keyword directly changes CRM stage. The existing Customer Insight contract must provide
    both a concrete action and a positive owner-facing job signal. Informational questions,
    comparisons, vague interest, and cancellations remain Lead.
    """
    if not business or not customer or not isinstance(insight, dict):
        return customer
    try:
        import platform_workspace
        if not platform_workspace.is_scope_business(business["id"]):
            return customer
    except Exception:
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


def sync_from_insight(business, customer, insight):
    """Keep one Customer Job aligned with the customer's concrete action and explicit deal/cancel signal."""
    if not jobs.enabled() or not business or not customer or not isinstance(insight, dict):
        return None
    if customer.get("stage") != "CUSTOMER":
        return None
    meta = insight.get("_meta") or {}
    if not meta.get("has_history"):
        return None

    signal = insight.get("job_status")
    target_status = SIGNAL_TO_STATUS.get(signal)
    payload = _payload(insight)
    if payload is None and target_status not in ("IN_PROGRESS", "CANCELLED"):
        return None

    if payload is not None:
        title, kind, summary, fields, ref = payload
    else:
        title = kind = summary = fields = None
        ref = "insight:" + _fingerprint(insight)

    bid, cid = business["id"], customer["id"]
    with jobs.transaction() as tx:
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

        if active_manual:
            return apply_status(active_manual[0])

        if active_auto:
            current = active_auto[0]
            status_arg = None
            if target_status in ("IN_PROGRESS", "CANCELLED") and current["owner_status"] != target_status:
                status_arg = target_status
            content_changed = bool(payload) and (
                current["fields"].get("source_key") != ref
                or current["fields"].get("action") != fields.get("action")
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
