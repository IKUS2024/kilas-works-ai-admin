"""Account-scoped Kilas AI quotas, reservations and provider cost records."""
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import db

PLANS = {
    "FREE": {"price": 0, "CHAT": 100, "CHAT_DAILY": 10, "WEB_SEARCH": 3, "IMAGES": 2, "PDF": 10},
    "PLUS": {"price": 99000, "CHAT": 600, "WEB_SEARCH": 120, "IMAGES": 40, "PDF": 150},
    "PRO": {"price": 149000, "CHAT": 1500, "WEB_SEARCH": 40, "IMAGES": 50, "PDF": 180},
    "MAX": {"price": 299000, "CHAT": 3000, "WEB_SEARCH": 80, "IMAGES": 100, "PDF": 350},
}
MODEL_RATES = {
    "gpt-6-luna": ("0.10", "0.50"), "gpt-6-sol": ("2.00", "10.00"),
    "gpt-6.1-sol": ("2.00", "10.00"),
    "claude-haiku-4-5-20251001": ("1.00", "5.00"), "claude-sonnet-5": ("2.00", "10.00"),
}
GUARD_UNIT_USD = {"FAST": Decimal("0.00035"), "SMART": Decimal("0.012"),
                  "EXPERT": Decimal("0.03"), "WEB_SEARCH": Decimal("0.015"),
                  "IMAGE_GENERATION": Decimal("0.04"), "IMAGE_EDIT": Decimal("0.04"),
                  "PDF": Decimal("0.001")}


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


def _rows(conn, sql, params=()):
    if db.BACKEND == "postgres":
        cur = conn.cursor()
        try:
            cur.execute(db._adapt_placeholders(sql), params)
            return cur.fetchall()
        finally:
            cur.close()
    return conn.execute(sql, params).fetchall()


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


def _period(plan, paid_start, paid_end, operation, now, mode=None):
    if plan != "FREE":
        cycle = max(0, (now - paid_start).days // 30)
        start = paid_start + timedelta(days=30 * cycle)
        return start, min(start + timedelta(days=30), paid_end)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start.replace(year=start.year + 1, month=1) if start.month == 12
           else start.replace(month=start.month + 1))
    return start, end


def _operations(mode, tool):
    if tool == "WEB":
        return ("WEB_SEARCH",)
    if tool == "IMAGE_GENERATE":
        return ("IMAGE_GENERATION",)
    if tool == "IMAGE_EDIT":
        return ("IMAGE_EDIT",)
    if tool == "PDF":
        return ("PDF",)
    return ("CHAT",)


def _chat_only_sql():
    # Earlier releases wrote a CHAT row alongside each Search/PDF row.
    return (" AND NOT EXISTS (SELECT 1 FROM kilas_ai_usage AS paired WHERE paired.user_id=u.user_id "
            "AND paired.operation_key=u.operation_key AND paired.operation_type IN ('WEB_SEARCH','PDF'))")


def _limit(plan, mode, operation):
    key = operation if operation in ("CHAT", "WEB_SEARCH", "PDF") else "IMAGES"
    if key == "CHAT" and mode == "FAST" and plan != "FREE":
        return 10000  # Hidden, generous ceiling for economical chat; burst/hourly gates still apply.
    if key in ("IMAGES", "PDF"):
        try:
            overrides = json.loads(os.environ.get("KILAS_AI_FAIR_USE_JSON", "{}"))
            configured = overrides.get(plan, {}).get(key)
            if isinstance(configured, int) and 1 <= configured <= 10000:
                return configured
        except (ValueError, TypeError, AttributeError):
            pass
    return PLANS[plan][key]


def _guard_unit(operation, mode):
    return GUARD_UNIT_USD[mode if operation == "CHAT" else operation]


def _cost_guard(conn, user_id, plan, paid_start, paid_end, operations, mode, now):
    if plan == "FREE":
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        hard = Decimal(os.environ.get("KILAS_AI_FREE_COST_CAP_USD", "0.15"))
    else:
        period_start = _period(plan, paid_start, paid_end, "PDF", now)[0]
        hard = Decimal(PLANS[plan]["price"]) / Decimal(os.environ.get("KILAS_AI_USD_IDR", "17000")) * Decimal(os.environ.get("KILAS_AI_COST_HARD_RATIO", "0.35"))
    rows = _rows(conn, "SELECT operation_type,mode,estimated_cost_usd FROM kilas_ai_usage WHERE user_id=? "
                 "AND created_at>=? AND status IN ('COMPLETE','PENDING')", (user_id, period_start.isoformat()))
    spent = Decimal(0)
    for operation, recorded_mode, cost in rows:
        try:
            spent += Decimal(str(cost)) if cost is not None else _guard_unit(operation, recorded_mode)
        except (InvalidOperation, KeyError):
            spent += Decimal("0.05")
    forecast = sum((_guard_unit(operation, mode) for operation in operations), Decimal(0))
    if spent + forecast > hard and not (mode == "FAST" and operations == ("CHAT",)):
        raise UsageLimit("Batas penggunaan fitur ini tercapai untuk periode ini. Chat biasa masih dapat digunakan.")
    warning = (Decimal(PLANS[plan]["price"]) / Decimal(os.environ.get("KILAS_AI_USD_IDR", "17000"))
               * Decimal("0.25")) if plan != "FREE" else hard * Decimal("0.7")
    if spent + forecast > warning:
        logging.getLogger(__name__).warning("Kilas AI internal cost warning for account %s", user_id)


def web_call_budget(user_id, plan):
    """Bound optional research calls by the remaining internal account cost guard."""
    now = _now()
    state = effective_plan(user_id)
    if plan != state["plan"]:
        return 1
    if plan == "FREE":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        hard = Decimal(os.environ.get("KILAS_AI_FREE_COST_CAP_USD", "0.15"))
    else:
        start = _period(plan, state["period_start"], state["period_end"], "WEB_SEARCH", now)[0]
        hard = (Decimal(PLANS[plan]["price"]) / Decimal(os.environ.get("KILAS_AI_USD_IDR", "17000"))
                * Decimal(os.environ.get("KILAS_AI_COST_HARD_RATIO", "0.35")))
    rows = db.query_all("SELECT operation_type,mode,estimated_cost_usd FROM kilas_ai_usage "
                        "WHERE user_id=? AND created_at>=? AND status IN ('COMPLETE','PENDING')",
                        (user_id, start.isoformat()))
    spent = Decimal(0)
    for row in rows:
        try:
            spent += (Decimal(str(row["estimated_cost_usd"])) if row["estimated_cost_usd"] is not None
                      else _guard_unit(row["operation_type"], row["mode"]))
        except (InvalidOperation, KeyError):
            spent += Decimal("0.05")
    extra = max(0, int((hard - spent) / Decimal("0.01")))
    return min({"FREE": 1, "PLUS": 3, "PRO": 4, "MAX": 5}.get(plan, 1), 1 + extra)


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
        needs_topup = False
        for operation in operations:
            limit = _limit(plan, mode, operation)
            if limit is None:
                continue
            start, end = _period(plan, paid_start, paid_end, operation, now, mode)
            type_filter = ("u.operation_type IN ('IMAGE_GENERATION','IMAGE_EDIT')" if operation in ("IMAGE_GENERATION", "IMAGE_EDIT")
                           else "u.operation_type=?")
            count = _query(conn, "SELECT COUNT(*) FROM kilas_ai_usage AS u WHERE u.user_id=? AND " + type_filter + " "
                "AND u.quota_source='BASE' AND u.created_at>=? AND u.created_at<? "
                "AND (u.status='COMPLETE' OR (u.status='PENDING' AND u.created_at>=?))"
                + (_chat_only_sql() if operation == "CHAT" else ""),
                ((user_id,) if operation in ("IMAGE_GENERATION", "IMAGE_EDIT") else (user_id, operation))
                + (start.isoformat(), end.isoformat(), (now - timedelta(minutes=10)).isoformat()), one=True)[0]
            if count >= limit:
                needs_topup = True
            if plan == "FREE" and operation == "CHAT":
                day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                daily = _query(conn, "SELECT COUNT(*) FROM kilas_ai_usage AS u WHERE u.user_id=? AND u.operation_type='CHAT' "
                    "AND u.quota_source='BASE' AND u.created_at>=? AND u.created_at<? AND (u.status='COMPLETE' OR "
                    "(u.status='PENDING' AND u.created_at>=?))" + _chat_only_sql(),
                    (user_id, day_start.isoformat(), (day_start + timedelta(days=1)).isoformat(),
                     (now - timedelta(minutes=10)).isoformat()), one=True)[0]
                if daily >= PLANS[plan]["CHAT_DAILY"]:
                    needs_topup = True
        try:
            _cost_guard(conn, user_id, plan, paid_start, paid_end, operations, mode, now)
        except UsageLimit:
            needs_topup = True
        if needs_topup:
            from . import topups
            try:
                topups.reserve(conn, user_id, key, operations[0], mode, now)
            except topups.TopupError as error:
                raise UsageLimit(str(error)) from None
        for operation in operations:
            _query(conn, "INSERT INTO kilas_ai_usage(user_id,thread_id,operation_key,operation_type,mode,status,quota_source,created_at) "
                   "VALUES (?,?,?,?,?,'PENDING',?,?)", (user_id, thread_id, key, operation, mode,
                       "TOPUP" if needs_topup else "BASE", now.isoformat()))
        conn.commit()
        return plan, operations
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def estimate(model, input_tokens, output_tokens, operation, web_search_calls=1):
    """Only explicit verified server price maps produce an estimate."""
    try:
        rates = json.loads(os.environ.get("KILAS_AI_MODEL_PRICING_JSON", "{}"))
        rate = rates.get(model)
        if operation in ("IMAGE_GENERATION", "IMAGE_EDIT"):
            value = Decimal(str(rate["per_image_usd"])) if isinstance(rate, dict) and "per_image_usd" in rate else Decimal("0.04") if model == "gpt-image-2" else None
        else:
            if not isinstance(rate, dict):
                prices = MODEL_RATES.get(model)
                if prices is None:
                    return None
                rate = {"input_per_million_usd": prices[0], "output_per_million_usd": prices[1]}
            value = ((Decimal(str(input_tokens)) * Decimal(str(rate["input_per_million_usd"])) +
                      Decimal(str(output_tokens)) * Decimal(str(rate["output_per_million_usd"]))) / Decimal(1000000))
            if operation == "WEB_SEARCH":
                value += Decimal("0.01") * max(1, min(5, int(web_search_calls)))
            elif operation == "PDF":
                value += Decimal("0.001")
        if value is None or value < 0 or not value.is_finite():
            return None
        return str(value.quantize(Decimal("0.000001")))
    except (ValueError, TypeError, KeyError, InvalidOperation, AttributeError):
        return None


def finish(user_id, key, operations, *, success, provider=None, model=None, usage=None):
    usage = usage or {}
    input_tokens = max(0, int(usage.get("input_tokens") or 0))
    output_tokens = max(0, int(usage.get("output_tokens") or 0))
    conn = _connect()
    try:
        if db.BACKEND == "postgres":
            _query(conn, "SELECT id FROM users WHERE id=? FOR UPDATE", (user_id,), one=True)
        first_cost = None
        for index, operation in enumerate(operations):
            billable = index == 0
            cost = (estimate(model, input_tokens if billable else 0, output_tokens if billable else 0,
                             operation, usage.get("web_search_calls", 1)) if model else None)
            if billable:
                first_cost = cost
            _query(conn, "UPDATE kilas_ai_usage SET status=?,provider=?,model=?,input_tokens=?,output_tokens=?,estimated_cost_usd=? "
                   "WHERE user_id=? AND operation_key=? AND operation_type=? AND status='PENDING'",
                   ("COMPLETE" if success else "FAILED", provider if billable else None,
                    model if billable else None, input_tokens if billable else 0,
                    output_tokens if billable else 0, cost, user_id, key, operation))
        from . import topups
        pending = (_query(conn, "SELECT mode FROM kilas_ai_usage WHERE user_id=? AND operation_key=? "
                          "AND operation_type=? LIMIT 1", (user_id, key, operations[0]), one=True)
                   if operations else None)
        fallback_key = (pending[0] if pending and operations[0] == "CHAT" else operations[0]) if operations else None
        fallback = 1000 if fallback_key == "PDF" else topups.FORECAST_MICRO.get(fallback_key, 80000)
        actual_micro = int(Decimal(first_cost) * Decimal(1000000)) if first_cost else fallback
        topups.settle(conn, user_id, key, success, actual_micro)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def snapshot(user_id):
    state = effective_plan(user_id)
    now = _now()
    summary = {}
    for operation, label in (("CHAT", "Chat"), ("WEB_SEARCH", "Search"),
                             ("IMAGE_GENERATION", "Gambar"), ("PDF", "PDF")):
        start, end = _period(state["plan"], state["period_start"], state["period_end"], operation, now)
        if operation == "IMAGE_GENERATION":
            sql = "SELECT COUNT(*) AS n FROM kilas_ai_usage WHERE user_id=? AND operation_type IN ('IMAGE_GENERATION','IMAGE_EDIT') AND quota_source='BASE' AND status='COMPLETE' AND created_at>=? AND created_at<?"
            params = (user_id, start.isoformat(), end.isoformat())
        else:
            sql = "SELECT COUNT(*) AS n FROM kilas_ai_usage AS u WHERE u.user_id=? AND u.operation_type=? AND u.quota_source='BASE' AND u.status='COMPLETE' AND u.created_at>=? AND u.created_at<?"
            params = (user_id, operation, start.isoformat(), end.isoformat())
            if operation == "CHAT":
                sql += _chat_only_sql()
        used = db.query_one(sql, params)["n"]
        key = operation if operation in ("CHAT", "WEB_SEARCH", "PDF") else "IMAGES"
        summary[label] = {"used": used, "limit": _limit(state["plan"], "FAST", operation)}
    state["reset_at"] = _period(state["plan"], state["period_start"], state["period_end"], "CHAT", now)[1]
    if state["plan"] == "FREE":
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        state["chat_today"] = db.query_one("SELECT COUNT(*) AS n FROM kilas_ai_usage AS u WHERE u.user_id=? "
            "AND u.operation_type='CHAT' AND u.quota_source='BASE' AND u.status='COMPLETE' AND u.created_at>=? AND u.created_at<?" + _chat_only_sql(),
            (user_id, day_start.isoformat(), (day_start + timedelta(days=1)).isoformat()))["n"]
    state["usage"] = summary
    state["creative_high"] = any(summary[name]["used"] >= summary[name]["limit"] for name in ("Gambar", "PDF"))
    from . import topups
    state["topup"] = topups.balance(user_id)
    return state
