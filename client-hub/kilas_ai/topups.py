"""Verified, account-owned Kuota Kilas orders and earliest-expiry cost credits."""
import os
import secrets
from datetime import timedelta
from decimal import Decimal

import db
import file_utils
from . import usage

PACKS = {"MINI": 19000, "EXTRA": 39000, "POWER": 79000}
FORECAST_MICRO = {"FAST": 5000, "SMART": 50000, "EXPERT": 80000,
                  "WEB_SEARCH": 80000, "IMAGE_GENERATION": 80000, "IMAGE_EDIT": 80000,
                  "PDF": 20000}


class TopupError(ValueError):
    pass


def _lock_user(conn, user_id):
    if db.BACKEND == "postgres":
        usage._query(conn, "SELECT id FROM users WHERE id=? FOR UPDATE", (user_id,), one=True)


def _budget_micro(amount_idr):
    fx = Decimal(os.environ.get("KILAS_AI_USD_IDR", "17000"))
    ratio = Decimal(os.environ.get("KILAS_AI_TOPUP_COST_RATIO", "0.30"))
    if fx <= 0 or not Decimal("0.05") <= ratio <= Decimal("0.40"):
        raise TopupError("Konfigurasi kuota tidak tersedia.")
    return int(Decimal(amount_idr) / fx * ratio * Decimal(1000000))


def create_order(user_id, pack):
    pack = (pack or "").upper()
    if pack not in PACKS:
        raise TopupError("Pilih paket Kuota Kilas yang tersedia.")
    conn = usage._connect()
    try:
        _lock_user(conn, user_id)
        existing = usage._query(conn, "SELECT id FROM kilas_ai_topup_orders WHERE user_id=? AND pack=? "
            "AND status IN ('PAYMENT_PENDING','UNDER_REVIEW') ORDER BY id DESC LIMIT 1", (user_id, pack), one=True)
        if existing:
            conn.commit()
            return existing[0]
        number = "KAI-Q-" + str(usage._now().year) + "-" + secrets.token_hex(8).upper()
        sql = "INSERT INTO kilas_ai_topup_orders(user_id,invoice_number,pack,amount_idr) VALUES (?,?,?,?)"
        params = (user_id, number, pack, PACKS[pack])
        if db.BACKEND == "postgres":
            order_id = usage._query(conn, sql + " RETURNING id", params, one=True)[0]
        else:
            order_id = conn.execute(sql, params).lastrowid
        conn.commit()
        return order_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def order(user_id, order_id):
    return db.query_one("SELECT id,invoice_number,pack,amount_idr,status,admin_note,created_at "
                        "FROM kilas_ai_topup_orders WHERE id=? AND user_id=?", (order_id, user_id))


def owner_orders(user_id, limit=30):
    return db.query_all("SELECT id,invoice_number,pack,amount_idr,status,created_at "
        "FROM kilas_ai_topup_orders WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, min(max(int(limit), 1), 50)))


def submit_proof(user_id, order_id, upload):
    if not upload or not upload.filename:
        raise TopupError("Pilih bukti transfer berupa gambar atau PDF.")
    raw = upload.stream.read(5 * 1024 * 1024 + 1)
    if not raw or len(raw) > 5 * 1024 * 1024:
        raise TopupError("Bukti transfer maksimal 5 MB.")
    try:
        filename, mime = file_utils.validate_project_attachment_upload(upload.filename, raw)
    except file_utils.UploadRejected:
        raise TopupError("Bukti transfer tidak valid. Gunakan gambar atau PDF yang dapat dibaca.") from None
    if (upload.mimetype or "").lower() not in (mime, "application/octet-stream"):
        raise TopupError("Jenis file bukti transfer tidak sesuai.")
    conn = usage._connect()
    try:
        _lock_user(conn, user_id)
        row = usage._query(conn, "SELECT status FROM kilas_ai_topup_orders WHERE id=? AND user_id=?",
                           (order_id, user_id), one=True)
        if not row:
            raise TopupError("Tagihan tidak ditemukan.")
        if row[0] not in ("PAYMENT_PENDING", "REJECTED"):
            raise TopupError("Bukti untuk tagihan ini sudah dalam proses review.")
        usage._query(conn, "UPDATE kilas_ai_topup_orders SET status='UNDER_REVIEW',proof_filename=?,"
            "proof_mime_type=?,proof_content=?,verified_by=NULL,verified_at=NULL,admin_note=NULL,"
            "updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
            (filename, mime, raw, order_id, user_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def pending_orders(limit=50):
    return db.query_all("SELECT o.id,o.user_id,o.invoice_number,o.pack,o.amount_idr,o.proof_filename,"
        "o.created_at,u.email,u.full_name FROM kilas_ai_topup_orders o "
        "JOIN users u ON u.id=o.user_id WHERE o.status='UNDER_REVIEW' "
        "ORDER BY o.created_at,o.id LIMIT ?", (min(max(int(limit), 1), 100),))


def admin_proof(order_id):
    return db.query_one("SELECT proof_filename,proof_mime_type,proof_content "
                        "FROM kilas_ai_topup_orders WHERE id=? AND status='UNDER_REVIEW'", (order_id,))


def review(order_id, admin_id, decision, note=""):
    if decision not in ("VERIFIED", "REJECTED"):
        raise TopupError("Keputusan pembayaran tidak valid.")
    admin = db.query_one("SELECT role FROM users WHERE id=?", (admin_id,))
    if not admin or admin["role"] != "KILAS_ADMIN":
        raise TopupError("Hanya admin Kilas yang dapat memverifikasi pembayaran.")
    conn = usage._connect()
    try:
        seed = usage._query(conn, "SELECT user_id FROM kilas_ai_topup_orders WHERE id=?", (order_id,), one=True)
        if not seed:
            raise TopupError("Pembayaran tidak ditemukan.")
        user_id = seed[0]
        _lock_user(conn, user_id)
        suffix = " FOR UPDATE" if db.BACKEND == "postgres" else ""
        row = usage._query(conn, "SELECT status,amount_idr FROM kilas_ai_topup_orders WHERE id=? AND user_id=?" + suffix,
                           (order_id, user_id), one=True)
        if row[0] == decision:
            conn.commit()
            return True
        if row[0] != "UNDER_REVIEW":
            raise TopupError("Pembayaran ini sudah diputuskan.")
        now = usage._now()
        usage._query(conn, "UPDATE kilas_ai_topup_orders SET status=?,verified_by=?,verified_at=?,admin_note=?,"
            "updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
            (decision, admin_id, now.isoformat(), (note or "").strip()[:1000], order_id, user_id))
        if decision == "VERIFIED":
            usage._query(conn, "INSERT INTO kilas_ai_topup_credits(order_id,user_id,total_micro,expires_at) "
                "VALUES (?,?,?,?) ON CONFLICT(order_id) DO NOTHING",
                (order_id, user_id, _budget_micro(row[1]), (now + timedelta(days=90)).isoformat()))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _lots(conn, user_id, now):
    return usage._rows(conn, "SELECT c.id,c.total_micro,COALESCE(SUM(CASE WHEN d.status='COMPLETE' "
        "THEN d.charged_micro WHEN d.status='PENDING' THEN d.reserved_micro ELSE 0 END),0) "
        "FROM kilas_ai_topup_credits c LEFT JOIN kilas_ai_topup_debits d ON d.credit_id=c.id "
        "WHERE c.user_id=? AND c.expires_at>? GROUP BY c.id,c.total_micro,c.expires_at "
        "ORDER BY c.expires_at,c.id", (user_id, now.isoformat()))


def reserve(conn, user_id, key, operation, mode, now):
    forecast = FORECAST_MICRO[mode if operation == "CHAT" else operation]
    remaining = forecast
    for credit_id, total, spent in _lots(conn, user_id, now):
        available = max(0, int(total) - int(spent))
        take = min(remaining, available)
        if take:
            usage._query(conn, "INSERT INTO kilas_ai_topup_debits(credit_id,user_id,operation_key,operation_type,"
                         "reserved_micro,status) VALUES (?,?,?,?,?,'PENDING')",
                         (credit_id, user_id, key, operation, take))
            remaining -= take
        if remaining == 0:
            return True
    raise TopupError("Kuota Kilas tambahan belum cukup. Tambah Kuota untuk melanjutkan fitur ini.")


def settle(conn, user_id, key, success, actual_micro):
    rows = usage._rows(conn, "SELECT id,reserved_micro FROM kilas_ai_topup_debits "
                       "WHERE user_id=? AND operation_key=? AND status='PENDING' ORDER BY id", (user_id, key))
    remaining = max(0, int(actual_micro)) if success else 0
    for index, (debit_id, reserved) in enumerate(rows):
        charged = min(remaining, int(reserved))
        remaining -= charged
        if success and index == len(rows) - 1 and remaining:
            charged += remaining  # Record an unexpectedly high real cost instead of hiding it.
            remaining = 0
        usage._query(conn, "UPDATE kilas_ai_topup_debits SET status=?,charged_micro=? WHERE id=? AND user_id=?",
                     ("COMPLETE" if success else "FAILED", charged, debit_id, user_id))


def balance(user_id):
    conn = usage._connect()
    try:
        lots = _lots(conn, user_id, usage._now())
        conn.commit()
        total = sum(int(row[1]) for row in lots)
        remaining = sum(max(0, int(row[1]) - int(row[2])) for row in lots)
        return {"available": remaining > 0, "percent": round(100 * remaining / total) if total else 0}
    finally:
        conn.close()
