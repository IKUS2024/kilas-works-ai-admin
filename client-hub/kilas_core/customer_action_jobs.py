"""Convert Customer Insight into one clean owner action Job per customer.

This is intentionally downstream of Customer Insight: chat delivery never waits on Jobs,
and raw chat text never writes a Job directly. The structured Insight decides whether there is
an actionable next step. Existing manual/playbook Jobs always win to avoid duplicate work.
"""
import hashlib
import json

import db
from kilas_core import customer_insights, customers, jobs


TERMINAL = {"COMPLETED", "CANCELLED"}
SIGNAL_TO_STATUS = {
    "PERLU_TINDAKAN": "NEW",
    "DIKERJAKAN": "IN_PROGRESS",
    "BATAL": "CANCELLED",
}

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

def refresh_and_sync(business, customer):
    insight = customer_insights.safe_refresh(business, customer)
    try:
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
