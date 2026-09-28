"""Account-scoped Kilas AI quotas, reservations and provider cost records."""
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import db

PLANS = {
    "FREE": {"price": 0, "FAST": 30, "SMART": 5, "EXPERT": 0, "WEB_SEARCH": 20, "IMAGES": 3},
    "PLUS": {"price": 69000, "FAST": None, "SMART": 600, "EXPERT": 50, "WEB_SEARCH": 200, "IMAGES": 50},
    "PRO": {"price": 149000, "FAST": None, "SMART": None, "EXPERT": 250, "WEB_SEARCH": 1000, "IMAGES": 150},
    "MAX": {"price": 299000, "FAST": None, "SMART": None, "EXPERT": 1000, "WEB_SEARCH": 5000, "IMAGES": 500},
}


class UsageLimit(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc)


def _as_utc(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _connect():
    if db.BACKEND == "postgres":
        return db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs())
    conn = sqlite3.connect(db.SQLITE_PATH, timeout=5)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("BEGIN IMMEDIATE")
    return conn


def _query(conn, sql, params=(), one=False):
    if db.BACKEND == "postgres":
        cur = conn.cursor()
        try:
            cur.execute(db._adapt_placeholders(sql), params)
            return cur.fetchone() if one else None
        finally:
            cur.close()
    cur = conn.execute(sql, params)
    return cur.fetchone() if one else None


def _plan(conn, user_id, now):
    row = _query(conn, "SELECT plan,status,period_start,period_end FROM kilas_ai_subscriptions WHERE user_id=?",
                 (user_id,), one=True)
    if row and row[1] == "ACTIVE" and _as_utc(row[2]) <= now < _as_utc(row[3]):
        return row[0], _as_utc(row[2]), _as_utc(row[3])
    return "FREE", None, None


def effective_plan(user_id):
    row = db.query_one("SELECT plan,status,period_start,period_end FROM kilas_ai_subscriptions WHERE user_id=?",
                       (user_id,))
    now = _now()
    if row and row["status"] == "ACTIVE" and _as_utc(row["period_start"]) <= now < _as_utc(row["period_end"]):
        return {"plan": row["plan"], "status": "ACTIVE", "period_start": _as_utc(row["period_start"]),
                "period_end": _as_utc(row["period_end"])}
    return {"plan": "FREE", "status": "FREE", "period_start": None, "period_end": None}


def _period(plan, paid_start, paid_end, operation, now):
    if plan != "FREE":
        cycle = max(0, (now - paid_start).days // 30)
        start = paid_start + timedelta(days=30 * cycle)
        return start, min(start + timedelta(days=30), paid_end)
    if operation == "CHAT":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start.replace(year=start.year + 1, month=1) if start.month == 12
           else start.replace(month=start.month + 1))
    return start, end


def _operations(mode, tool):
    if tool == "WEB":
        return ("CHAT", "WEB_SEARCH")
    if tool == "IMAGE_GENERATE":
        return ("IMAGE_GENERATION",)
    if tool == "IMAGE_EDIT":
        return ("IMAGE_EDIT",)
    return ("CHAT",)


def _limit(plan, mode, operation):
    key = mode if operation == "CHAT" else "WEB_SEARCH" if operation == "WEB_SEARCH" else "IMAGES"
    return PLANS[plan][key]


def reserve(user_id, thread_id, key, mode, tool):
    """Atomically check and reserve all requested units before any provider call."""
    now = _now()
    conn = _connect()
    try:
        if db.BACKEND == "postgres":
            _query(conn, "SELECT id FROM users WHERE id=? FOR UPDATE", (user_id,), one=True)
        existing = _query(conn, "SELECT 1 FROM kilas_ai_usage WHERE user_id=? AND operation_key=? LIMIT 1",
                          (user_id, key), one=True)
        if existing:
            conn.commit()
            return None, ()
        plan, paid_start, paid_end = _plan(conn, user_id, now)
        burst = max(1, int(os.environ.get("KILAS_AI_BURST_PER_MINUTE", "30")))
        hourly = max(burst, int(os.environ.get("KILAS_AI_MAX_PER_HOUR", "300")))
        for seconds, ceiling in ((60, burst), (3600, hourly)):
            cutoff = now - timedelta(seconds=seconds)
            count = _query(conn, "SELECT COUNT(DISTINCT operation_key) FROM kilas_ai_usage WHERE user_id=? "
                "AND (status='COMPLETE' OR (status='PENDING' AND created_at>=?)) AND created_at>=?",
                (user_id, (now - timedelta(minutes=10)).isoformat(), cutoff.isoformat()), one=True)[0]
            if count >= ceiling:
                raise UsageLimit("Terlalu banyak permintaan dalam waktu singkat. Coba lagi sebentar.")
        operations = _operations(mode, tool)
        for operation in operations:
            limit = _limit(plan, mode, operation)
            if limit is None:
                continue
            if limit == 0:
                raise UsageLimit("Mode Expert tersedia pada paket berbayar. Pilih Fast atau Smart.")
            start, end = _period(plan, paid_start, paid_end, operation, now)
            column = " AND mode=?" if operation == "CHAT" else ""
            params = [user_id, operation, start.isoformat(), end.isoformat(), (now - timedelta(minutes=10)).isoformat()]
            if operation == "CHAT":
                params.append(mode)
            count = _query(conn, "SELECT COUNT(*) FROM kilas_ai_usage WHERE user_id=? AND operation_type=? "
                "AND created_at>=? AND created_at<? AND (status='COMPLETE' OR (status='PENDING' AND created_at>=?))" + column,
                tuple(params), one=True)[0]
            if count >= limit:
                label = mode.title() if operation == "CHAT" else "Web" if operation == "WEB_SEARCH" else "Gambar"
                raise UsageLimit("Kuota " + label + " periode ini sudah habis. Gunakan mode lain atau upgrade paket.")
        for operation in operations:
            _query(conn, "INSERT INTO kilas_ai_usage(user_id,thread_id,operation_key,operation_type,mode,status,created_at) "
                   "VALUES (?,?,?,?,?,'PENDING',?)", (user_id, thread_id, key, operation, mode, now.isoformat()))
        conn.commit()
        return plan, operations
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def estimate(model, input_tokens, output_tokens, operation):
    """Only explicit verified server price maps produce an estimate."""
    try:
        rates = json.loads(os.environ.get("KILAS_AI_MODEL_PRICING_JSON", "{}"))
        rate = rates.get(model)
        if not isinstance(rate, dict):
            return None
        if operation in ("IMAGE_GENERATION", "IMAGE_EDIT"):
            value = Decimal(str(rate["per_image_usd"]))
        else:
            value = ((Decimal(str(input_tokens)) * Decimal(str(rate["input_per_million_usd"])) +
                      Decimal(str(output_tokens)) * Decimal(str(rate["output_per_million_usd"]))) / Decimal(1000000))
        if value < 0 or not value.is_finite():
            return None
        return str(value.quantize(Decimal("0.000001")))
    except (ValueError, TypeError, KeyError, InvalidOperation, AttributeError):
        return None


def finish(user_id, key, operations, *, success, provider=None, model=None, usage=None):
    usage = usage or {}
    input_tokens = max(0, int(usage.get("input_tokens") or 0))
    output_tokens = max(0, int(usage.get("output_tokens") or 0))
    for index, operation in enumerate(operations):
        billable = index == 0
        cost = estimate(model, input_tokens, output_tokens, operation) if billable and model else None
        db.execute("UPDATE kilas_ai_usage SET status=?,provider=?,model=?,input_tokens=?,output_tokens=?,estimated_cost_usd=? "
                   "WHERE user_id=? AND operation_key=? AND operation_type=? AND status='PENDING'",
                   ("COMPLETE" if success else "FAILED", provider if billable else None,
                    model if billable else None, input_tokens if billable else 0,
                    output_tokens if billable else 0, cost, user_id, key, operation))


def snapshot(user_id):
    state = effective_plan(user_id)
    now = _now()
    summary = {}
    for operation, mode, label in (("CHAT", "FAST", "Fast"), ("CHAT", "SMART", "Smart"),
                                   ("CHAT", "EXPERT", "Expert"), ("WEB_SEARCH", None, "Web"),
                                   ("IMAGE_GENERATION", None, "Images")):
        start, end = _period(state["plan"], state["period_start"], state["period_end"], operation, now)
        if operation == "IMAGE_GENERATION":
            sql = "SELECT COUNT(*) AS n FROM kilas_ai_usage WHERE user_id=? AND operation_type IN ('IMAGE_GENERATION','IMAGE_EDIT') AND status='COMPLETE' AND created_at>=? AND created_at<?"
            params = (user_id, start.isoformat(), end.isoformat())
        else:
            sql = "SELECT COUNT(*) AS n FROM kilas_ai_usage WHERE user_id=? AND operation_type=? AND status='COMPLETE' AND created_at>=? AND created_at<?"
            params = (user_id, operation, start.isoformat(), end.isoformat())
            if mode:
                sql += " AND mode=?"
                params += (mode,)
        used = db.query_one(sql, params)["n"]
        summary[label] = {"used": used, "limit": PLANS[state["plan"]][mode or ("WEB_SEARCH" if operation == "WEB_SEARCH" else "IMAGES")]}
    state["usage"] = summary
    return state
