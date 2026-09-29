"""Account-scoped manual-transfer billing for Kilas Work."""
import secrets
from datetime import timedelta

import db
import file_utils
from . import quota, sql


class BillingError(ValueError):
    pass


def create_order(user_id, kind, sku):
    kind, sku = str(kind).upper(), str(sku).upper()
    catalog = quota.PLANS if kind == "PLAN" else quota.TOPUPS if kind == "TOPUP" else {}
    if sku not in catalog:
        raise BillingError("Pilih paket Work yang tersedia.")
    conn = sql.connect()
    try:
        sql.lock_user(conn, user_id)
        prior = sql.one(conn, "SELECT id FROM kilas_work_orders WHERE user_id=? AND kind=? AND sku=? "
                        "AND status IN ('PAYMENT_PENDING','UNDER_REVIEW') ORDER BY id DESC LIMIT 1",
                        (user_id, kind, sku))
        if prior:
            conn.commit()
            return prior[0]
        number = "KWR-" + str(quota.now().year) + "-" + secrets.token_hex(8).upper()
        order_id = sql.insert_id(conn, "INSERT INTO kilas_work_orders "
                                "(user_id,invoice_number,kind,sku,amount_idr) VALUES (?,?,?,?,?)",
                                (user_id, number, kind, sku, catalog[sku]))
        conn.commit()
        return order_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def order(user_id, order_id):
    return db.query_one("SELECT id,invoice_number,kind,sku,amount_idr,status,admin_note,created_at "
                        "FROM kilas_work_orders WHERE user_id=? AND id=?", (user_id, order_id))


def owner_orders(user_id):
    return db.query_all("SELECT id,invoice_number,kind,sku,amount_idr,status,created_at "
                        "FROM kilas_work_orders WHERE user_id=? ORDER BY id DESC LIMIT 30", (user_id,))


def submit_proof(user_id, order_id, upload):
    if not upload or not upload.filename:
        raise BillingError("Pilih bukti transfer berupa gambar atau PDF.")
    raw = upload.stream.read(5 * 1024 * 1024 + 1)
    if not raw or len(raw) > 5 * 1024 * 1024:
        raise BillingError("Bukti transfer maksimal 5 MB.")
    try:
        filename, mime = file_utils.validate_project_attachment_upload(upload.filename, raw)
    except file_utils.UploadRejected:
        raise BillingError("Bukti transfer tidak valid.") from None
    if (upload.mimetype or "").lower() not in (mime, "application/octet-stream"):
        raise BillingError("Jenis file bukti transfer tidak sesuai.")
    conn = sql.connect()
    try:
        sql.lock_user(conn, user_id)
        found = sql.one(conn, "SELECT status FROM kilas_work_orders WHERE id=? AND user_id=?",
                        (order_id, user_id))
        if not found:
            raise BillingError("Tagihan tidak ditemukan.")
        if found[0] not in ("PAYMENT_PENDING", "REJECTED"):
            raise BillingError("Bukti pembayaran sedang atau sudah ditinjau.")
        sql.run(conn, "UPDATE kilas_work_orders SET proof_filename=?,proof_mime_type=?,proof_content=?,"
                "status='UNDER_REVIEW',admin_note=NULL,verified_by=NULL,verified_at=NULL,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
                (filename, mime, raw, order_id, user_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def review_queue():
    return db.query_all("SELECT o.id,o.invoice_number,o.kind,o.sku,o.amount_idr,o.created_at,"
                        "u.email,u.full_name FROM kilas_work_orders o JOIN users u ON u.id=o.user_id "
                        "WHERE o.status='UNDER_REVIEW' ORDER BY o.created_at,o.id LIMIT 100")


def admin_order(order_id):
    return db.query_one("SELECT o.id,o.user_id,o.invoice_number,o.kind,o.sku,o.amount_idr,o.status,"
                        "o.proof_filename,o.proof_mime_type,o.admin_note,u.email FROM kilas_work_orders o "
                        "JOIN users u ON u.id=o.user_id WHERE o.id=?", (order_id,))


def admin_proof(order_id):
    return db.query_one("SELECT proof_filename,proof_mime_type,proof_content FROM kilas_work_orders "
                        "WHERE id=? AND status IN ('UNDER_REVIEW','VERIFIED','REJECTED')", (order_id,))


def review(order_id, admin_id, decision, note=""):
    if decision not in ("VERIFIED", "REJECTED"):
        raise BillingError("Keputusan pembayaran tidak valid.")
    admin = db.query_one("SELECT role FROM users WHERE id=?", (admin_id,))
    if not admin or admin["role"] != "KILAS_ADMIN":
        raise BillingError("Hanya admin Kilas dapat memverifikasi pembayaran.")
    conn = sql.connect()
    try:
        seed = sql.one(conn, "SELECT user_id FROM kilas_work_orders WHERE id=?", (order_id,))
        if not seed:
            raise BillingError("Tagihan tidak ditemukan.")
        user_id = seed[0]
        sql.lock_user(conn, user_id)
        found = sql.one(conn, "SELECT kind,sku,status FROM kilas_work_orders WHERE id=? AND user_id=?",
                        (order_id, user_id))
        if found[2] == decision:
            conn.commit()
            return False
        if found[2] != "UNDER_REVIEW":
            raise BillingError("Tagihan belum siap ditinjau atau sudah diputuskan.")
        at = quota.now()
        sql.run(conn, "UPDATE kilas_work_orders SET status=?,verified_by=?,verified_at=?,admin_note=?,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
                (decision, admin_id, at.isoformat(), str(note or "").strip()[:1000], order_id, user_id))
        if decision == "VERIFIED" and found[0] == "PLAN":
            current = sql.one(conn, "SELECT plan,status,period_start,period_end FROM kilas_work_subscriptions "
                              "WHERE user_id=?", (user_id,))
            if current and current[0] == found[1] and current[1] == "ACTIVE" and quota.utc(current[3]) > at:
                start, end = quota.utc(current[2]), quota.utc(current[3]) + timedelta(days=30)
            else:
                start, end = at, at + timedelta(days=30)
            sql.run(conn, "INSERT INTO kilas_work_subscriptions(user_id,plan,status,period_start,period_end) "
                    "VALUES (?,?,'ACTIVE',?,?) ON CONFLICT(user_id) DO UPDATE SET plan=excluded.plan,"
                    "status='ACTIVE',period_start=excluded.period_start,period_end=excluded.period_end,"
                    "updated_at=CURRENT_TIMESTAMP", (user_id, found[1], start.isoformat(), end.isoformat()))
        elif decision == "VERIFIED":
            sql.run(conn, "INSERT INTO kilas_work_credits(order_id,user_id,total_micro,expires_at) "
                    "VALUES (?,?,?,?) ON CONFLICT(order_id) DO NOTHING",
                    (order_id, user_id, quota._budget(quota.TOPUPS[found[1]]),
                     (at + timedelta(days=90)).isoformat()))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
