"""Convert Customer Insight into one clean owner action Job per customer.

This is intentionally downstream of Customer Insight: chat delivery never waits on Jobs,
and raw chat text never writes a Job directly. The structured Insight decides whether there is
an actionable next step. Existing manual/playbook Jobs always win to avoid duplicate work.
"""
import hashlib
import json

from kilas_core import customer_insights, customers, jobs


ACTIONABLE_STAGES = {
    "MENCARI_INFORMASI": "Mencari informasi",
    "MEMBANDINGKAN": "Membandingkan pilihan",
    "BERMINAT": "Berminat",
    "SIAP_MEMBELI": "Siap membeli",
    "CUSTOMER_AKTIF": "Customer aktif",
}
TERMINAL = {"COMPLETED", "CANCELLED"}
AUTO_EDITABLE = {"NEW", "NEEDS_INFORMATION"}


def _clean(value, maximum=700):
    if not isinstance(value, str):
        return ""
    return value.strip()[:maximum]


def _list(value):
    if not isinstance(value, list):
        return []
    return [_clean(item, 180) for item in value[:8] if _clean(item, 180)]


def _title_kind(insight):
    text = " ".join(
        _list(insight.get("needs"))
        + _list(insight.get("interests"))
        + [_clean(insight.get("follow_up"), 500)]
    ).lower()
    if any(word in text for word in ("booking", "jadwal", "appointment", "reservasi", "janji")):
        return "Tindak lanjut booking", "BOOKING"
    if any(word in text for word in ("foto", "photo", "video", "reels", "konten", "content", "website", "landing page")):
        return "Tindak lanjut kebutuhan project", "PROJECT"
    if any(word in text for word in ("harga", "price", "paket", "biaya", "quote", "quotation", "penawaran")):
        return "Tindak lanjut penawaran", "SERVICE"
    if any(word in text for word in ("konsultasi", "meeting", "diskusi", "call", "telepon")):
        return "Jadwalkan konsultasi", "BOOKING"
    if any(word in text for word in ("beli", "pembelian", "order", "pesan", "ambil")):
        return "Tindak lanjut pembelian", "ORDER"
    needs = _list(insight.get("needs"))
    if needs:
        return "Tindak lanjut: " + needs[0][:110], "SERVICE"
    return "Tindak lanjut customer", "GENERIC"


def _priority(stage):
    if stage == "SIAP_MEMBELI":
        return "Tinggi"
    if stage in ("BERMINAT", "MEMBANDINGKAN"):
        return "Sedang"
    return "Normal"


def _fingerprint(insight):
    basis = {
        "stage": insight.get("buying_stage"),
        "needs": _list(insight.get("needs")),
        "interests": _list(insight.get("interests")),
        "follow_up": _clean(insight.get("follow_up"), 700),
    }
    return hashlib.sha256(
        json.dumps(basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:20]


def _payload(insight):
    stage = insight.get("buying_stage")
    action = _clean(insight.get("follow_up"), 700)
    needs = _list(insight.get("needs"))
    interests = _list(insight.get("interests"))
    if not action:
        if needs:
            action = "Tindak lanjuti kebutuhan customer: " + ", ".join(needs[:3])
        elif interests:
            action = "Tindak lanjuti minat customer: " + ", ".join(interests[:3])
    title, kind = _title_kind(insight)
    summary = _clean(insight.get("summary"), 1300)
    if action:
        summary = (summary + ("\n\n" if summary else "") + "Tindakan: " + action)[:2000]
    missing = ", ".join(_list(insight.get("missing_info")))
    ref = "insight:" + _fingerprint(insight)
    fields = {
        "action": action,
        "intent": ACTIONABLE_STAGES.get(stage, stage or ""),
        "priority": _priority(stage),
        "source": "Customer Insight",
        "reference": ref,
    }
    if summary:
        fields["details"] = summary[:1000]
    if missing:
        fields["missing_information"] = missing[:1000]
    return title, kind, summary, fields, ref


def sync_from_insight(business, customer, insight):
    """Create/update a single actionable Job without overriding owner-controlled work."""
    if not jobs.enabled() or not business or not customer or not isinstance(insight, dict):
        return None
    meta = insight.get("_meta") or {}
    if not meta.get("has_history"):
        return None
    stage = insight.get("buying_stage")
    if stage not in ACTIONABLE_STAGES:
        return None

    title, kind, summary, fields, ref = _payload(insight)
    if not fields.get("action") and not _list(insight.get("needs")) and not _list(insight.get("interests")):
        return None

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

        # A manual/playbook Job already represents the customer action. Never duplicate it.
        if active_manual:
            return active_manual[0]

        if active_auto:
            current = active_auto[0]
            if current["status"] not in AUTO_EDITABLE:
                return current
            if (
                current["fields"].get("reference") == ref
                and current["fields"].get("action") == fields.get("action")
                and current["title"] == title
            ):
                return current
            op = "customer_insight_" + hashlib.sha256(
                f"{cid}:{ref}:{current['version']}".encode()
            ).hexdigest()
            return jobs._update_job(
                tx, bid, current["id"], expected_version=current["version"],
                actor_id=jobs._CUSTOMER_INSIGHT_ACTOR, operation_key=op,
                title=title, summary=summary, fields=fields,
            )

        # Do not recreate the exact same action immediately after owner completed/cancelled it.
        if auto and auto[0]["fields"].get("reference") == ref:
            return auto[0]

        op = "customer_insight_" + hashlib.sha256(f"{cid}:{ref}:create".encode()).hexdigest()
        return jobs._create_job(
            tx, bid, cid, title=title, actor_id=jobs._CUSTOMER_INSIGHT_ACTOR,
            operation_key=op, kind=kind, summary=summary, fields=fields,
        )


def refresh_and_sync(business, customer):
    insight = customer_insights.safe_refresh(business, customer)
    try:
        job = sync_from_insight(business, customer, insight)
    except Exception:
        job = None
    return insight, job


def reconcile_business(business, limit=10):
    """Bounded recent-customer reconciliation when owner opens Jobs.

    This gives Demo WhatsApp the same practical monitoring behavior as official channel playbooks
    without a background worker or an unbounded model sweep.
    """
    if not jobs.enabled() or not business:
        return 0
    try:
        rows, _, _, _ = customers.list_customers(business["id"], page=1, stage="ALL")
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
