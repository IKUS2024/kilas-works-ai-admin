"""One-time trial and variable-cost Work quota, isolated from Kilas AI."""
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import db
from . import sql

PLANS = {"PLUS": 149000, "PRO": 299000, "MAX": 599000}
TOPUPS = {"MINI": 49000, "EXTRA": 99000, "POWER": 199000}
FORECAST_MICRO = {"CHAT_LUNA": 5000, "CHAT_SOL": 60000, "WEB": 80000,
                  "IMAGE": 80000, "PDF": 30000, "CODE": 50000, "BROWSER": 80000}
MODEL_RATES = {"gpt-6-luna": (Decimal("0.10"), Decimal("0.50")),
               "gpt-6-sol": (Decimal("2"), Decimal("10"))}


class QuotaError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc)


def utc(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _budget(amount_idr):
    fx = Decimal(os.environ.get("KILAS_WORK_USD_IDR", "17000"))
    ratio = Decimal(os.environ.get("KILAS_WORK_COST_RATIO", "0.30"))
    if fx <= 0 or not Decimal("0.1") <= ratio <= Decimal("0.35"):
        raise QuotaError("Konfigurasi Kuota Work tidak tersedia.")
    return int(Decimal(amount_idr) / fx * ratio * 1000000)


def _trial_micro():
    configured = int(os.environ.get("KILAS_WORK_TRIAL_MICRO_USD", "300000"))
    if not 10000 <= configured <= 1000000:
        raise QuotaError("Konfigurasi percobaan Work tidak tersedia.")
    return configured


def _global_daily_micro():
    configured = int(os.environ.get("KILAS_WORK_GLOBAL_DAILY_MICRO_USD", "5000000"))
    if not 100000 <= configured <= 1000000000:
        raise QuotaError("Batas harian Work tidak tersedia.")
    return configured


def ensure_account(user_id):
    conn = sql.connect()
    try:
        sql.lock_user(conn, user_id)
        sql.run(conn, "INSERT INTO kilas_work_accounts(user_id,trial_total_micro) VALUES (?,?) "
                "ON CONFLICT(user_id) DO NOTHING", (user_id, _trial_micro()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _plan(conn, user_id, at):
    row = sql.one(conn, "SELECT plan,status,period_start,period_end FROM kilas_work_subscriptions "
                  "WHERE user_id=?", (user_id,))
    if row and row[1] == "ACTIVE" and utc(row[2]) <= at < utc(row[3]):
        return row[0], utc(row[2]), utc(row[3])
    return None, None, None


def _spent(conn, user_id, source, start=None, end=None):
    statement = "SELECT COALESCE(SUM(CASE WHEN status='COMPLETE' THEN charged_micro ELSE reserved_micro END),0) "
    statement += "FROM kilas_work_usage WHERE user_id=? AND source=? AND status IN ('COMPLETE','PENDING')"
    params = [user_id, source]
    if start:
        statement += " AND created_at>=? AND created_at<?"
        params.extend((start.isoformat(), end.isoformat()))
    return int(sql.one(conn, statement, tuple(params))[0])


def _lots(conn, user_id, at):
    return sql.rows(conn, "SELECT c.id,c.total_micro,COALESCE(SUM(CASE WHEN d.status='COMPLETE' "
                    "THEN d.charged_micro WHEN d.status='PENDING' THEN d.reserved_micro ELSE 0 END),0) "
                    "FROM kilas_work_credits c LEFT JOIN kilas_work_topup_debits d ON d.credit_id=c.id "
                    "WHERE c.user_id=? AND c.expires_at>? GROUP BY c.id,c.total_micro,c.expires_at "
                    "ORDER BY c.expires_at,c.id", (user_id, at.isoformat()))


def snapshot(user_id):
    ensure_account(user_id)
    conn = sql.connect()
    try:
        at = now()
        account = sql.one(conn, "SELECT trial_total_micro FROM kilas_work_accounts WHERE user_id=?", (user_id,))
        plan, start, end = _plan(conn, user_id, at)
        trial_remaining = max(0, int(account[0]) - _spent(conn, user_id, "TRIAL"))
        base_budget = _budget(PLANS[plan]) if plan else 0
        base_remaining = max(0, base_budget - _spent(conn, user_id, "BASE", start, end)) if plan else 0
        lots = _lots(conn, user_id, at)
        topup_total = sum(int(row[1]) for row in lots)
        topup_remaining = sum(max(0, int(row[1]) - int(row[2])) for row in lots)
        conn.commit()
        fraction = trial_remaining / int(account[0])
        trial_label = ("Habis" if not trial_remaining else "Tinggal sedikit" if fraction < .25
                       else "Sekitar setengah" if fraction < .65 else "Masih tersedia")
        return {"plan": plan, "period_end": end, "trial_label": trial_label,
                "trial_percent": round(100 * fraction), "trial_available": trial_remaining > 0,
                "base_available": base_remaining > 0, "base_percent": round(100 * base_remaining / base_budget) if base_budget else 0,
                "topup_available": topup_remaining > 0,
                "topup_percent": round(100 * topup_remaining / topup_total) if topup_total else 0}
    finally:
        conn.close()


def _reserve_topup(conn, user_id, key, forecast, at):
    remaining = forecast
    for credit_id, total, spent in _lots(conn, user_id, at):
        take = min(remaining, max(0, int(total) - int(spent)))
        if take:
            sql.run(conn, "INSERT INTO kilas_work_topup_debits(user_id,credit_id,operation_key,reserved_micro,status) "
                    "VALUES (?,?,?,?,'PENDING')", (user_id, credit_id, key, take))
            remaining -= take
        if not remaining:
            return
    raise QuotaError("Kuota Work belum cukup. Pilih Paket Work atau Tambah Kuota Work untuk melanjutkan.")


def reserve(user_id, thread_id, key, operation, model="gpt-6-luna", job_id=None):
    """Lock the account, forecast cost, and reserve exactly one source before calling a provider."""
    kind = "CHAT_SOL" if operation == "CHAT" and model == "gpt-6-sol" else "CHAT_LUNA" if operation == "CHAT" else operation
    forecast = FORECAST_MICRO.get(kind)
    if not forecast:
        raise QuotaError("Jenis pekerjaan belum tersedia.")
    ensure_account(user_id)
    conn = sql.connect()
    try:
        sql.lock_user(conn, user_id)
        if sql.one(conn, "SELECT id FROM kilas_work_usage WHERE user_id=? AND operation_key=?", (user_id, key)):
            conn.commit()
            return None
        at = now()
        if db.BACKEND == "postgres":
            sql.one(conn, "SELECT pg_advisory_xact_lock(74107402)")
        day_start = at.replace(hour=0, minute=0, second=0, microsecond=0)
        global_spent = sql.one(conn, "SELECT COALESCE(SUM(CASE WHEN status='COMPLETE' THEN charged_micro "
                               "ELSE reserved_micro END),0) FROM kilas_work_usage "
                               "WHERE status IN ('COMPLETE','PENDING') AND created_at>=?",
                               (day_start.isoformat(),))[0]
        if int(global_spent) + forecast > _global_daily_micro():
            raise QuotaError("Kilas Work mencapai batas penggunaan harian. Coba lagi besok.")
        plan, start, end = _plan(conn, user_id, at)
        if plan:
            budget = _budget(PLANS[plan])
            spent = _spent(conn, user_id, "BASE", start, end)
            source = "BASE" if spent + forecast <= budget else "TOPUP"
        else:
            trial = sql.one(conn, "SELECT trial_total_micro FROM kilas_work_accounts WHERE user_id=?", (user_id,))[0]
            source = "TRIAL" if _spent(conn, user_id, "TRIAL") + forecast <= int(trial) else "TOPUP"
        if source == "TOPUP":
            _reserve_topup(conn, user_id, key, forecast, at)
        sql.run(conn, "INSERT INTO kilas_work_usage(user_id,thread_id,job_id,operation_key,operation_type,model,"
                "source,status,reserved_micro,created_at) VALUES (?,?,?,?,?,?,?,'PENDING',?,?)",
                (user_id, thread_id, job_id, key, operation, model, source, forecast, at.isoformat()))
        conn.commit()
        return source
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def estimate_micro(model, input_tokens=0, output_tokens=0, *, web_calls=0, container_minutes=0,
                   image_count=0, browser_seconds=0):
    """Conservative internal variable-cost estimate from recorded provider usage."""
    rates = MODEL_RATES.get(model)
    if not rates:
        return None
    try:
        value = ((Decimal(max(0, int(input_tokens))) * rates[0] +
                  Decimal(max(0, int(output_tokens))) * rates[1]) / 1000000)
        value += Decimal(max(0, int(web_calls))) * Decimal("0.01")
        value += Decimal(max(0, int(image_count))) * Decimal("0.04")
        value += Decimal(max(0, int(container_minutes))) * Decimal("0.006")
        value += Decimal(max(0, int(browser_seconds))) * Decimal("0.00002")
        return max(1, int(value * 1000000))
    except (ValueError, TypeError, InvalidOperation):
        return None


def finish(user_id, key, *, success, actual_micro=None, input_tokens=0, output_tokens=0, tool_calls=0):
    conn = sql.connect()
    try:
        sql.lock_user(conn, user_id)
        row = sql.one(conn, "SELECT source,reserved_micro,status FROM kilas_work_usage "
                      "WHERE user_id=? AND operation_key=?", (user_id, key))
        if not row or row[2] != "PENDING":
            conn.commit()
            return False
        charge = max(0, int(actual_micro)) if actual_micro is not None else int(row[1])
        charge = charge if success else 0
        sql.run(conn, "UPDATE kilas_work_usage SET status=?,charged_micro=?,input_tokens=?,output_tokens=?,tool_calls=? "
                "WHERE user_id=? AND operation_key=? AND status='PENDING'",
                ("COMPLETE" if success else "FAILED", charge, max(0, int(input_tokens)),
                 max(0, int(output_tokens)), max(0, int(tool_calls)), user_id, key))
        if row[0] == "TOPUP":
            debits = sql.rows(conn, "SELECT id,reserved_micro FROM kilas_work_topup_debits "
                              "WHERE user_id=? AND operation_key=? AND status='PENDING' ORDER BY id", (user_id, key))
            remaining = charge
            for index, (debit_id, reserved) in enumerate(debits):
                consumed = min(remaining, int(reserved))
                remaining -= consumed
                if index == len(debits) - 1:
                    consumed += remaining
                sql.run(conn, "UPDATE kilas_work_topup_debits SET status=?,charged_micro=? WHERE id=? AND user_id=?",
                        ("COMPLETE" if success else "FAILED", consumed, debit_id, user_id))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
