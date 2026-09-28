"""Independent account-level manual-transfer billing for Kilas AI."""
import secrets
from datetime import timedelta

import db
import file_utils
from . import usage


class BillingError(ValueError):
    pass


def _lock_user(conn, user_id):
    if db.BACKEND == "postgres":
        usage._query(conn, "SELECT id FROM users WHERE id=? FOR UPDATE", (user_id,), one=True)


def create_invoice(user_id, plan):
    plan = (plan or "").upper()
    if plan not in ("PLUS", "PRO", "MAX"):
        raise BillingError("Pilih paket Plus, Pro, atau Max.")
    conn = usage._connect()
    try:
        _lock_user(conn, user_id)
        existing = usage._query(conn, "SELECT id FROM kilas_ai_invoices WHERE user_id=? AND plan=? "
            "AND status IN ('PAYMENT_PENDING','UNDER_REVIEW') ORDER BY id DESC LIMIT 1", (user_id, plan), one=True)
        if existing:
            conn.commit()
            return existing[0]
        number = "KAI-" + str(usage._now().year) + "-" + secrets.token_hex(8).upper()
        if db.BACKEND == "postgres":
            inserted = usage._query(conn, "INSERT INTO kilas_ai_invoices(user_id,invoice_number,plan,amount_idr) "
                "VALUES (?,?,?,?) RETURNING id", (user_id, number, plan, usage.PLANS[plan]["price"]), one=True)
            invoice_id = inserted[0]
        else:
            cursor = conn.execute("INSERT INTO kilas_ai_invoices(user_id,invoice_number,plan,amount_idr) "
                                  "VALUES (?,?,?,?)", (user_id, number, plan, usage.PLANS[plan]["price"]))
            invoice_id = cursor.lastrowid
        conn.commit()
        return invoice_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def invoice(user_id, invoice_id):
    return db.query_one("SELECT id,invoice_number,plan,amount_idr,status,created_at,updated_at "
                        "FROM kilas_ai_invoices WHERE id=? AND user_id=?", (invoice_id, user_id))


def owner_invoices(user_id, limit=30):
    return db.query_all("SELECT id,invoice_number,plan,amount_idr,status,created_at FROM kilas_ai_invoices "
                        "WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, min(max(int(limit), 1), 50)))


def proof_status(user_id, invoice_id):
    return db.query_one("SELECT id,status,verified_at,admin_note FROM kilas_ai_payments "
                        "WHERE user_id=? AND invoice_id=?", (user_id, invoice_id))


def submit_proof(user_id, invoice_id, upload):
    if not upload or not upload.filename:
        raise BillingError("Pilih bukti transfer berupa gambar atau PDF.")
    raw = upload.stream.read(5 * 1024 * 1024 + 1)
    if not raw or len(raw) > 5 * 1024 * 1024:
        raise BillingError("Bukti transfer maksimal 5 MB.")
    try:
        filename, mime = file_utils.validate_project_attachment_upload(upload.filename, raw)
    except file_utils.UploadRejected:
        raise BillingError("Bukti transfer tidak valid. Gunakan gambar atau PDF yang dapat dibaca.") from None
    claimed = (upload.mimetype or "").lower()
    if claimed not in (mime, "application/octet-stream"):
        raise BillingError("Jenis file bukti transfer tidak sesuai.")
    conn = usage._connect()
    try:
        _lock_user(conn, user_id)
        row = usage._query(conn, "SELECT status FROM kilas_ai_invoices WHERE id=? AND user_id=?",
                           (invoice_id, user_id), one=True)
        if not row:
            raise BillingError("Tagihan tidak ditemukan.")
        if row[0] not in ("PAYMENT_PENDING", "REJECTED"):
            raise BillingError("Bukti untuk tagihan ini sudah dalam proses review.")
        existing = usage._query(conn, "SELECT id FROM kilas_ai_payments WHERE invoice_id=? AND user_id=?",
                                (invoice_id, user_id), one=True)
        if existing:
            usage._query(conn, "UPDATE kilas_ai_payments SET status='UNDER_REVIEW',proof_filename=?,proof_mime_type=?,"
                "proof_content=?,verified_by=NULL,verified_at=NULL,admin_note=NULL,updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND user_id=?", (filename, mime, raw, existing[0], user_id))
        else:
            usage._query(conn, "INSERT INTO kilas_ai_payments(invoice_id,user_id,status,proof_filename,proof_mime_type,proof_content) "
                "VALUES (?,?,'UNDER_REVIEW',?,?,?)", (invoice_id, user_id, filename, mime, raw))
        usage._query(conn, "UPDATE kilas_ai_invoices SET status='UNDER_REVIEW',updated_at=CURRENT_TIMESTAMP "
                     "WHERE id=? AND user_id=?", (invoice_id, user_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def pending_payments(limit=50):
    return db.query_all("SELECT p.id,p.invoice_id,p.user_id,p.status,p.proof_filename,p.created_at,"
        "i.invoice_number,i.plan,i.amount_idr,u.email,u.full_name FROM kilas_ai_payments p "
        "JOIN kilas_ai_invoices i ON i.id=p.invoice_id JOIN users u ON u.id=p.user_id "
        "WHERE p.status='UNDER_REVIEW' ORDER BY p.created_at,p.id LIMIT ?", (min(max(int(limit), 1), 100),))


def admin_proof(payment_id):
    return db.query_one("SELECT proof_filename,proof_mime_type,proof_content FROM kilas_ai_payments WHERE id=?",
                        (payment_id,))


def review(payment_id, admin_id, decision, note=""):
    if decision not in ("VERIFIED", "REJECTED"):
        raise BillingError("Keputusan pembayaran tidak valid.")
    admin = db.query_one("SELECT role FROM users WHERE id=?", (admin_id,))
    if not admin or admin["role"] != "KILAS_ADMIN":
        raise BillingError("Hanya admin Kilas yang dapat memverifikasi pembayaran.")
    note = (note or "").strip()[:1000]
    conn = usage._connect()
    try:
        seed = usage._query(conn, "SELECT user_id FROM kilas_ai_payments WHERE id=?", (payment_id,), one=True)
        if not seed:
            raise BillingError("Pembayaran tidak ditemukan.")
        user_id = seed[0]
        _lock_user(conn, user_id)
        suffix = " FOR UPDATE" if db.BACKEND == "postgres" else ""
        payment = usage._query(conn, "SELECT invoice_id,status FROM kilas_ai_payments WHERE id=? AND user_id=?" + suffix,
                               (payment_id, user_id), one=True)
        if payment[1] == decision:
            conn.commit()
            return True
        if payment[1] != "UNDER_REVIEW":
            raise BillingError("Pembayaran ini sudah diputuskan.")
        invoice_row = usage._query(conn, "SELECT plan,status FROM kilas_ai_invoices WHERE id=? AND user_id=?" + suffix,
                                   (payment[0], user_id), one=True)
        if not invoice_row or invoice_row[1] != "UNDER_REVIEW":
            raise BillingError("Tagihan tidak siap diverifikasi.")
        now = usage._now()
        usage._query(conn, "UPDATE kilas_ai_payments SET status=?,verified_by=?,verified_at=?,admin_note=?,"
                     "updated_at=CURRENT_TIMESTAMP WHERE id=?", (decision, admin_id, now.isoformat(), note, payment_id))
        usage._query(conn, "UPDATE kilas_ai_invoices SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (decision, payment[0]))
        if decision == "VERIFIED":
            current = usage._query(conn, "SELECT plan,status,period_start,period_end FROM kilas_ai_subscriptions "
                                   "WHERE user_id=?" + suffix, (user_id,), one=True)
            if current and current[0] == invoice_row[0] and current[1] == "ACTIVE" and usage._as_utc(current[3]) > now:
                start = usage._as_utc(current[2])
                end = usage._as_utc(current[3]) + timedelta(days=30)
            else:
                start, end = now, now + timedelta(days=30)
            usage._query(conn, "INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) "
                "VALUES (?,?,'ACTIVE',?,?) ON CONFLICT(user_id) DO UPDATE SET plan=excluded.plan,status='ACTIVE',"
                "period_start=excluded.period_start,period_end=excluded.period_end,updated_at=CURRENT_TIMESTAMP",
                (user_id, invoice_row[0], start.isoformat(), end.isoformat()))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
