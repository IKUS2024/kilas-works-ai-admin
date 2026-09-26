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


def _short_action(insight):
    """One short owner-facing sentence: what this Customer wants."""
    needs = _list(insight.get("needs"))
    interests = _list(insight.get("interests"))
    candidate = needs[0] if needs else (interests[0] if interests else "")
    candidate = _clean(candidate, 150)
    low = candidate.lower()
    if low.startswith("informasi "):
        return "Mau tahu " + candidate[10:].strip()
    if low.startswith("info "):
        return "Mau tahu " + candidate[5:].strip()
    if low.startswith(("booking ", "konsultasi ", "foto ", "photo ", "video ", "website ", "paket ", "harga ", "penawaran ")):
        return "Mau " + candidate
    if candidate:
        return ("Mau " + candidate)[:160]

    summary = _clean(insight.get("summary"), 180)
    if summary:
        first = summary.split(".")[0].strip()
        if first:
            return first[:160]
    return ""


def _title_kind(insight):
    action = _short_action(insight)
    text = action.lower()
    if any(word in text for word in ("booking", "jadwal", "appointment", "reservasi", "janji", "konsultasi")):
        return action or "Tindak lanjut booking", "BOOKING"
    if any(word in text for word in ("foto", "photo", "video", "reels", "konten", "content", "website", "landing page")):
        return action or "Tindak lanjut project", "PROJECT"
    if any(word in text for word in ("beli", "pembelian", "order", "pesan", "ambil")):
        return action or "Tindak lanjut pembelian", "ORDER"
    if any(word in text for word in ("harga", "price", "paket", "biaya", "quote", "quotation", "penawaran")):
        return action or "Tindak lanjut penawaran", "SERVICE"
    return action or "Tindak lanjut customer", "GENERIC"
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
    title, kind = _title_kind(insight)
    action = title
    ref = "insight:" + _fingerprint(insight)
    fields = {
        "action": action,
        "intent": ACTIONABLE_STAGES.get(stage, stage or ""),
        "priority": _priority(stage),
        "source": "Customer Insight",
        "source_key": ref,
    }
    # Keep details intentionally short. Jobs is an action queue, not a second analysis screen.
    summary = action
    return title, kind, summary, fields, ref

def sync_from_insight(business, customer, insight):
    """Create/update a single actionable Job without overriding owner-controlled work."""
    if not jobs.enabled() or not business or not customer or not isinstance(insight, dict):
        return None
    # Jobs belongs to real Customers only. Leads stay in Customers/Lead + Customer Insight.
    if customer.get("stage") != "CUSTOMER":
        return None
    meta = insight.get("_meta") or {}
    if not meta.get("has_history"):
        return None
    stage = insight.get("buying_stage")
    if stage not in ACTIONABLE_STAGES:
        return None

    title, kind, summary, fields, ref = _payload(insight)
    if not fields.get("action"):
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
                current["fields"].get("source_key") == ref
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
        if auto and auto[0]["fields"].get("source_key") == ref:
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


