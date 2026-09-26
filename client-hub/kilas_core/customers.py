"""Tenant-scoped Kilas Core Customers foundation.

Business-first CRM identity. WEB visitors are represented by server-derived hashes; raw visitor
tokens are never stored here. Owner-entered phone/email are profile fields only in Phase 3 and are
NOT automatically promoted to verified cross-channel identities.
"""
from contextlib import contextmanager
import hashlib
import os
import re
import sqlite3
import time
import uuid

import db


AI_PACKAGES = ("AI_ADMIN", "AI_ADMIN_BASIC", "AI_ADMIN_PRO")
STAGES = ("LEAD", "CUSTOMER")


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


def _stage(value, *, allow_none=False):
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise CustomerError("invalid_stage")
    value = value.strip().upper()
    if value not in STAGES:
        raise CustomerError("invalid_stage")
    return value


def ensure_whatsapp_lead(business_id, phone, display_name=None, *, now=None):
    """Resolve/create a tenant-scoped WhatsApp lead without requiring a Core conversation row.

    Used by the privacy-scoped Demo WhatsApp mirror, which intentionally does not create
    kw_web_conversations rows. The verified phone identity is identical to the official
    WhatsApp adapter identity, so a future official conversation reuses this customer instead
    of creating a duplicate.
    """
    if not enabled():
        return None
    if not isinstance(phone, str) or not re.fullmatch(r"[1-9][0-9]{5,19}", phone):
        raise CustomerError("invalid_identity")
    now = int(time.time()) if now is None else int(now)
    identity_hash = hashlib.sha256(phone.encode()).hexdigest()
    name = _clean_text(display_name, 160) or phone
    with transaction() as tx:
        identity = tx.one(
            "SELECT customer_id FROM kw_core_customer_identities "
            "WHERE business_id=? AND identity_type='WHATSAPP_PHONE' AND identity_hash=?",
            (business_id, identity_hash),
        )
        if identity:
            customer_id = identity["customer_id"]
            customer = tx.one(
                "SELECT c.*,COALESCE(s.stage,'CUSTOMER') AS stage "
                "FROM kw_core_customers c LEFT JOIN kw_core_customer_stages s "
                "ON s.business_id=c.business_id AND s.customer_id=c.id "
                "WHERE c.business_id=? AND c.id=?",
                (business_id, customer_id),
            )
            if not customer:
                raise CustomerError("customer_identity_conflict", 409)
            return customer

        customer_id = uuid.uuid4().hex
        tx.execute(
            "INSERT INTO kw_core_customers"
            "(business_id,id,display_name,phone,source_channel,created_at,updated_at,last_activity_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (business_id, customer_id, name, phone, "WHATSAPP", now, now, now),
        )
        tx.execute(
            "INSERT INTO kw_core_customer_identities"
            "(business_id,customer_id,identity_type,identity_hash,verified,created_at) "
            "VALUES (?,?,'WHATSAPP_PHONE',?,1,?)",
            (business_id, customer_id, identity_hash, now),
        )
        tx.execute(
            "INSERT INTO kw_core_customer_stages"
            "(business_id,customer_id,stage,created_at,updated_at) VALUES (?,?,'LEAD',?,?)",
            (business_id, customer_id, now, now),
        )
        return tx.one(
            "SELECT c.*,s.stage FROM kw_core_customers c "
            "JOIN kw_core_customer_stages s ON s.business_id=c.business_id AND s.customer_id=c.id "
            "WHERE c.business_id=? AND c.id=?",
            (business_id, customer_id),
        )


def ensure_web_customer(tx, business_id, conversation_id, visitor_hash, now=None):
    """Resolve/create one Core customer for one strong tenant-scoped WEB visitor identity.

    Accepts the caller transaction so conversation creation + identity/linking stay atomic.
    """
    return ensure_channel_customer(tx, business_id, conversation_id, "WEB_VISITOR", visitor_hash, "WEB", now=now)


def ensure_channel_customer(tx, business_id, conversation_id, identity_type, identity_hash, channel, *, now=None):
    """Trusted adapters only; verified identities never match editable profile fields."""
    if (identity_type, channel) not in (("WEB_VISITOR", "WEB"), ("WHATSAPP_PHONE", "WHATSAPP")):
        raise CustomerError("invalid_identity")
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
        "WHERE business_id=? AND identity_type=? AND identity_hash=?",
        (business_id, identity_type, identity_hash),
    )
    if identity:
        customer_id = identity["customer_id"]
    else:
        customer_id = uuid.uuid4().hex
        tx.execute(
            "INSERT INTO kw_core_customers"
            "(business_id,id,display_name,source_channel,created_at,updated_at,last_activity_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (business_id, customer_id, _placeholder(customer_id), channel, now, now, now),
        )
        tx.execute(
            "INSERT INTO kw_core_customer_identities"
            "(business_id,customer_id,identity_type,identity_hash,verified,created_at) "
            "VALUES (?,?,?,?,1,?)",
            (business_id, customer_id, identity_type, identity_hash, now),
        )
        tx.execute(
            "INSERT INTO kw_core_customer_stages"
            "(business_id,customer_id,stage,created_at,updated_at) VALUES (?,?,?,?,?)",
            (business_id, customer_id, "LEAD", now, now),
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
            "SELECT c.*,COALESCE(s.stage,'CUSTOMER') AS stage "
            "FROM kw_core_customers c LEFT JOIN kw_core_customer_stages s "
            "ON s.business_id=c.business_id AND s.customer_id=c.id "
            "WHERE c.business_id=? AND c.id=?",
            (business_id, customer_id),
        )
        if not row:
            raise CustomerError("customer_not_found", 404)
        return row


def list_customers(business_id, search="", page=1, stage="ALL"):
    search = (search or "").strip()[:120]
    page = max(1, int(page or 1))
    stage = (stage or "ALL").strip().upper()
    if stage not in ("ALL",) + STAGES:
        stage = "ALL"
    where = "c.business_id=?"
    args = [business_id]
    if stage != "ALL":
        where += " AND COALESCE(s.stage,'CUSTOMER')=?"
        args.append(stage)
    if search:
        where += " AND (LOWER(c.display_name) LIKE LOWER(?) OR LOWER(COALESCE(c.phone,'')) LIKE LOWER(?) OR LOWER(COALESCE(c.email,'')) LIKE LOWER(?))"
        like = "%" + search + "%"
        args += [like, like, like]
    base = (
        " FROM kw_core_customers c LEFT JOIN kw_core_customer_stages s "
        "ON s.business_id=c.business_id AND s.customer_id=c.id WHERE " + where
    )
    with transaction() as tx:
        total = tx.one("SELECT COUNT(*) AS n" + base, tuple(args))["n"]
        pages = max(1, (total + 9) // 10)
        page = min(page, pages)
        rows = tx.execute(
            "SELECT c.*,COALESCE(s.stage,'CUSTOMER') AS stage, "
            "(SELECT COUNT(*) FROM kw_web_customer_links l WHERE l.business_id=c.business_id AND l.customer_id=c.id) AS conversation_count" +
            base + " ORDER BY c.last_activity_at DESC,c.id LIMIT 10 OFFSET ?",
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


def update_customer(business_id, customer_id, *, display_name, phone=None, email=None, notes=None,
                    stage=None, actor_id=None):
    display_name = _clean_text(display_name, 160, allow_blank=False)
    phone = _clean_text(phone, 40)
    email = _clean_text(email, 254)
    notes = _clean_text(notes, 2000)
    stage = _stage(stage, allow_none=True)
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise CustomerError("invalid_email")
    now = int(time.time())
    with transaction() as tx:
        existing = tx.one(
            "SELECT c.id,COALESCE(s.stage,'CUSTOMER') AS stage "
            "FROM kw_core_customers c LEFT JOIN kw_core_customer_stages s "
            "ON s.business_id=c.business_id AND s.customer_id=c.id "
            "WHERE c.business_id=? AND c.id=?",
            (business_id, customer_id),
        )
        if not existing:
            raise CustomerError("customer_not_found", 404)
        tx.execute(
            "UPDATE kw_core_customers SET display_name=?,phone=?,email=?,notes=?,updated_at=? "
            "WHERE business_id=? AND id=?",
            (display_name, phone, email, notes, now, business_id, customer_id),
        )
        if stage is not None:
            tx.execute(
                "INSERT INTO kw_core_customer_stages(business_id,customer_id,stage,created_at,updated_at) "
                "VALUES (?,?,?,?,?) ON CONFLICT(business_id,customer_id) DO UPDATE SET "
                "stage=excluded.stage,updated_at=excluded.updated_at",
                (business_id, customer_id, stage, now, now),
            )
        if actor_id is not None:
            tx.execute(
                "INSERT INTO audit_log(actor_user_id,business_id,action,detail) VALUES (?,?,?,?)",
                (actor_id, business_id, "CUSTOMER_UPDATED", customer_id),
            )
            if stage is not None and stage != existing["stage"]:
                tx.execute(
                    "INSERT INTO audit_log(actor_user_id,business_id,action,detail) VALUES (?,?,?,?)",
                    (actor_id, business_id, "CUSTOMER_STAGE_CHANGED",
                     customer_id + ":" + existing["stage"] + "->" + stage),
                )
        return tx.one(
            "SELECT c.*,COALESCE(s.stage,'CUSTOMER') AS stage "
            "FROM kw_core_customers c LEFT JOIN kw_core_customer_stages s "
            "ON s.business_id=c.business_id AND s.customer_id=c.id "
            "WHERE c.business_id=? AND c.id=?",
            (business_id, customer_id),
        )
