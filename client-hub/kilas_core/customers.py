"""Tenant-scoped Kilas Core Customers foundation.

Business-first CRM identity. WEB visitors are represented by server-derived hashes; raw visitor
tokens are never stored here. Owner-entered phone/email are profile fields only in Phase 3 and are
NOT automatically promoted to verified cross-channel identities.
"""
from contextlib import contextmanager
import os
import re
import sqlite3
import time
import uuid

import db


AI_PACKAGES = ("AI_ADMIN", "AI_ADMIN_BASIC", "AI_ADMIN_PRO")


def enabled():
    return os.environ.get("KILAS_CUSTOMERS_V2_ENABLED", "").strip().lower() == "true"


class CustomerError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


class Tx:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, args=()):
        cur = self.connection.cursor()
        cur.execute(db._adapt_placeholders(sql), args)
        rows = []
        if cur.description:
            names = [item[0] for item in cur.description]
            rows = [dict(zip(names, row)) for row in cur.fetchall()]
        cur.close()
        return rows

    def one(self, sql, args=()):
        rows = self.execute(sql, args)
        return rows[0] if rows else None


@contextmanager
def transaction():
    if db.BACKEND == "sqlite":
        conn = sqlite3.connect(db.SQLITE_PATH, timeout=10)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
    else:
        conn = db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs())
    try:
        yield Tx(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _placeholder(customer_id):
    return "Pengunjung " + customer_id[:6]


def _clean_text(value, maximum, *, allow_blank=True):
    if value is None:
        return None
    if not isinstance(value, str):
        raise CustomerError("invalid_customer")
    value = value.strip()
    if not value and allow_blank:
        return None
    if not value or len(value) > maximum:
        raise CustomerError("invalid_customer")
    return value


def ensure_web_customer(tx, business_id, conversation_id, visitor_hash, now=None):
    """Resolve/create one Core customer for one strong tenant-scoped WEB visitor identity.

    Accepts the caller transaction so conversation creation + identity/linking stay atomic.
    """
    now = int(time.time()) if now is None else int(now)
    linked = tx.one(
        "SELECT c.* FROM kw_web_customer_links l "
        "JOIN kw_core_customers c ON c.business_id=l.business_id AND c.id=l.customer_id "
        "WHERE l.business_id=? AND l.conversation_id=?",
        (business_id, conversation_id),
    )
    if linked:
        return linked

    identity = tx.one(
        "SELECT customer_id FROM kw_core_customer_identities "
        "WHERE business_id=? AND identity_type='WEB_VISITOR' AND identity_hash=?",
        (business_id, visitor_hash),
    )
    if identity:
        customer_id = identity["customer_id"]
    else:
        customer_id = uuid.uuid4().hex
        tx.execute(
            "INSERT INTO kw_core_customers"
            "(business_id,id,display_name,source_channel,created_at,updated_at,last_activity_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (business_id, customer_id, _placeholder(customer_id), "WEB", now, now, now),
        )
        tx.execute(
            "INSERT INTO kw_core_customer_identities"
            "(business_id,customer_id,identity_type,identity_hash,verified,created_at) "
            "VALUES (?,?,?,?,1,?)",
            (business_id, customer_id, "WEB_VISITOR", visitor_hash, now),
        )

    tx.execute(
        "INSERT INTO kw_web_customer_links(business_id,conversation_id,customer_id,created_at) "
        "VALUES (?,?,?,?) ON CONFLICT(business_id,conversation_id) DO NOTHING",
        (business_id, conversation_id, customer_id, now),
    )
    customer = tx.one(
        "SELECT * FROM kw_core_customers WHERE business_id=? AND id=?",
        (business_id, customer_id),
    )
    if not customer:
        raise CustomerError("customer_identity_conflict", 409)
    return customer


def touch_from_conversation(tx, business_id, conversation_id, now=None):
    if not enabled():
        return
    now = int(time.time()) if now is None else int(now)
    tx.execute(
        "UPDATE kw_core_customers SET last_activity_at=?,updated_at=? "
        "WHERE business_id=? AND id=(SELECT customer_id FROM kw_web_customer_links "
        "WHERE business_id=? AND conversation_id=?)",
        (now, now, business_id, business_id, conversation_id),
    )


def customer_for_conversation(business_id, conversation_id):
    if not enabled():
        return None
    with transaction() as tx:
        return tx.one(
            "SELECT c.* FROM kw_web_customer_links l "
            "JOIN kw_core_customers c ON c.business_id=l.business_id AND c.id=l.customer_id "
            "WHERE l.business_id=? AND l.conversation_id=?",
            (business_id, conversation_id),
        )


def get_customer(business_id, customer_id):
    with transaction() as tx:
        row = tx.one(
            "SELECT * FROM kw_core_customers WHERE business_id=? AND id=?",
            (business_id, customer_id),
        )
        if not row:
            raise CustomerError("customer_not_found", 404)
        return row


def list_customers(business_id, search="", page=1):
    search = (search or "").strip()[:120]
    page = max(1, int(page or 1))
    where = "business_id=?"
    args = [business_id]
    if search:
        where += " AND (LOWER(display_name) LIKE LOWER(?) OR LOWER(COALESCE(phone,'')) LIKE LOWER(?) OR LOWER(COALESCE(email,'')) LIKE LOWER(?))"
        like = "%" + search + "%"
        args += [like, like, like]
    with transaction() as tx:
        total = tx.one("SELECT COUNT(*) AS n FROM kw_core_customers WHERE " + where, tuple(args))["n"]
        pages = max(1, (total + 9) // 10)
        page = min(page, pages)
        rows = tx.execute(
            "SELECT c.*, "
            "(SELECT COUNT(*) FROM kw_web_customer_links l WHERE l.business_id=c.business_id AND l.customer_id=c.id) AS conversation_count "
            "FROM kw_core_customers c WHERE " + where +
            " ORDER BY last_activity_at DESC,id LIMIT 10 OFFSET ?",
            tuple(args + [(page - 1) * 10]),
        )
        return rows, total, page, pages


def customer_conversations(business_id, customer_id):
    get_customer(business_id, customer_id)
    with transaction() as tx:
        return tx.execute(
            "SELECT w.id,w.mode,w.created_at,w.updated_at,"
            "(SELECT content FROM kw_web_messages m WHERE m.business_id=w.business_id "
            "AND m.conversation_id=w.id ORDER BY m.id DESC LIMIT 1) AS preview "
            "FROM kw_web_customer_links l "
            "JOIN kw_web_conversations w ON w.business_id=l.business_id AND w.id=l.conversation_id "
            "WHERE l.business_id=? AND l.customer_id=? ORDER BY w.updated_at DESC",
            (business_id, customer_id),
        )


def update_customer(business_id, customer_id, *, display_name, phone=None, email=None, notes=None, actor_id=None):
    display_name = _clean_text(display_name, 160, allow_blank=False)
    phone = _clean_text(phone, 40)
    email = _clean_text(email, 254)
    notes = _clean_text(notes, 2000)
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise CustomerError("invalid_email")
    now = int(time.time())
    with transaction() as tx:
        existing = tx.one(
            "SELECT id FROM kw_core_customers WHERE business_id=? AND id=?",
            (business_id, customer_id),
        )
        if not existing:
            raise CustomerError("customer_not_found", 404)
        tx.execute(
            "UPDATE kw_core_customers SET display_name=?,phone=?,email=?,notes=?,updated_at=? "
            "WHERE business_id=? AND id=?",
            (display_name, phone, email, notes, now, business_id, customer_id),
        )
        if actor_id is not None:
            tx.execute(
                "INSERT INTO audit_log(actor_user_id,business_id,action,detail) VALUES (?,?,?,?)",
                (actor_id, business_id, "CUSTOMER_UPDATED", customer_id),
            )
        return tx.one(
            "SELECT * FROM kw_core_customers WHERE business_id=? AND id=?",
            (business_id, customer_id),
        )
