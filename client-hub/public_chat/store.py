"""Strictly tenant-scoped WEB storage with short DB transactions, never model IO in a lock."""
from contextlib import contextmanager
import hashlib
import secrets
import sqlite3
import time
import uuid
import db


class ChatError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


class Transaction:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, args=()):
        cursor = self.connection.cursor()
        cursor.execute(db._adapt_placeholders(sql), args)
        rows = []
        if cursor.description:
            names = [c[0] for c in cursor.description]
            rows = [dict(zip(names, row)) for row in cursor.fetchall()]
        cursor.close()
        return rows

    def one(self, sql, args=()):
        rows = self.execute(sql, args)
        return rows[0] if rows else None


@contextmanager
def transaction():
    # Dedicated connection: do not commit/rollback an unrelated hub/Finance transaction.
    if db.BACKEND == "sqlite":
        conn = sqlite3.connect(db.SQLITE_PATH, timeout=10)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
    else:
        conn = db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs())
    try:
        yield Transaction(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _locked(tx, bid, cid):
    suffix = " FOR UPDATE" if db.BACKEND == "postgres" else ""
    row = tx.one("SELECT * FROM kw_web_conversations WHERE business_id=? AND id=?" + suffix, (bid, cid))
    if not row:
        raise ChatError("not_found", 404)
    return row


def limit(tx, scope, seconds, maximum, now=None):
    now = int(time.time()) if now is None else now
    bucket = now // seconds
    row = tx.one("INSERT INTO kw_web_limits(scope,bucket,count) VALUES (?,?,1) "
                 "ON CONFLICT(scope,bucket) DO UPDATE SET count=kw_web_limits.count+1 RETURNING count",
                 (scope, bucket))
    if row["count"] > maximum:
        raise ChatError("rate_limited", 429)
    # Keep a bounded time horizon; hashed subjects contain no raw network addresses.
    tx.execute("DELETE FROM kw_web_limits WHERE scope=? AND bucket<?", (scope, bucket - 2))


def channel(bid=None, slug=None):
    if (bid is None) == (slug is None):
        raise ChatError("invalid_scope")
    with transaction() as tx:
        return tx.one("SELECT * FROM kw_web_channels WHERE " + ("business_id=?" if bid is not None else "slug=?"),
                      (bid if bid is not None else slug,))


def ensure_channel(bid):
    with transaction() as tx:
        slug = "bisnis-" + secrets.token_hex(12)
        tx.execute("INSERT INTO kw_web_channels(business_id,slug) VALUES (?,?) "
                   "ON CONFLICT(business_id) DO NOTHING", (bid, slug))
        return tx.one("SELECT * FROM kw_web_channels WHERE business_id=?", (bid,))


def visitor(bid, token, ip_key):
    now = int(time.time())
    with transaction() as tx:
        limit(tx, "open:" + ip_key, 60, 30)
        if token:
            row = tx.one("SELECT * FROM kw_web_conversations WHERE business_id=? AND visitor_hash=? AND expires_at>?",
                         (bid, digest(token), now))
            if row:
                return row, token
        limit(tx, "new:" + str(bid), 86400, 1000)
        token, cid = secrets.token_urlsafe(32), uuid.uuid4().hex
        tx.execute("INSERT INTO kw_web_conversations(id,business_id,visitor_hash,expires_at,created_at,updated_at) "
                   "VALUES (?,?,?,?,?,?)", (cid, bid, digest(token), now + 7 * 86400, now, now))
        return tx.one("SELECT * FROM kw_web_conversations WHERE business_id=? AND id=?", (bid, cid)), token


def authorized(bid, cid, token):
    if not isinstance(token, str) or not 32 <= len(token) <= 128:
        raise ChatError("not_found", 404)
    with transaction() as tx:
        row = tx.one("SELECT * FROM kw_web_conversations WHERE business_id=? AND id=? AND visitor_hash=? AND expires_at>?",
                     (bid, cid, digest(token), int(time.time())))
        if not row:
            raise ChatError("not_found", 404)
        return row


def thread(bid, cid, after=0):
    with transaction() as tx:
        _locked(tx, bid, cid)
        return tx.execute("SELECT id,role,content,created_at FROM kw_web_messages "
                          "WHERE business_id=? AND conversation_id=? AND id>? ORDER BY id LIMIT 100",
                          (bid, cid, after))


def _message(tx, bid, cid, event_id, role, text):
    tx.execute("INSERT INTO kw_web_messages(business_id,conversation_id,event_id,role,content,created_at) "
               "VALUES (?,?,?,?,?,?)", (bid, cid, event_id, role, text, int(time.time())))
    tx.execute("UPDATE kw_web_conversations SET updated_at=? WHERE business_id=? AND id=?",
               (int(time.time()), bid, cid))


def claim(bid, cid, event_id, text, ip_key):
    now, fingerprint = int(time.time()), digest(text)
    with transaction() as tx:
        conv = _locked(tx, bid, cid)
        event = tx.one("SELECT * FROM kw_web_events WHERE business_id=? AND conversation_id=? AND event_id=?",
                       (bid, cid, event_id))
        if event:
            if event["payload_hash"] != fingerprint:
                raise ChatError("event_conflict", 409)
            if event["status"] != "processing" or event["lease_until"] > now:
                return event, None
            if event["attempts"] >= 2:
                tx.execute("UPDATE kw_web_events SET status='failed',error='interrupted' "
                           "WHERE business_id=? AND conversation_id=? AND event_id=?", (bid, cid, event_id))
                return dict(event, status="failed", error="interrupted"), None
        busy = tx.one("SELECT event_id FROM kw_web_events WHERE business_id=? AND conversation_id=? "
                      "AND status='processing' AND lease_until>? AND event_id<>?", (bid, cid, now, event_id))
        if busy:
            raise ChatError("conversation_busy", 409)
        limit(tx, "send-ip:" + ip_key, 60, 30)
        limit(tx, "send-visitor:" + cid, 60, 10)
        limit(tx, "send-business:" + str(bid), 86400, 500)
        if not event:
            _message(tx, bid, cid, event_id, "user", text)
        token = secrets.token_hex(16)
        status = "done" if conv["mode"] == "HUMAN_TAKEOVER" else "processing"
        tx.execute("INSERT INTO kw_web_events(business_id,conversation_id,event_id,payload_hash,status,claim_token,"
                   "lease_until,version) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(business_id,conversation_id,event_id) "
                   "DO UPDATE SET claim_token=excluded.claim_token,lease_until=excluded.lease_until,"
                   "version=excluded.version,status=excluded.status,attempts=kw_web_events.attempts+1",
                   (bid, cid, event_id, fingerprint, status, token, now + 90, conv["version"]))
        current = tx.one("SELECT * FROM kw_web_events WHERE business_id=? AND conversation_id=? AND event_id=?",
                         (bid, cid, event_id))
        history = tx.execute("SELECT role,content FROM kw_web_messages WHERE business_id=? AND conversation_id=? "
                             "AND NOT (event_id=? AND role='user') ORDER BY id DESC LIMIT 10", (bid, cid, event_id))
        return current, list(reversed(history)) if status == "processing" else None


def finish(event, reply=None, error=None):
    bid, cid, eid = event["business_id"], event["conversation_id"], event["event_id"]
    with transaction() as tx:
        conv = _locked(tx, bid, cid)
        current = tx.one("SELECT * FROM kw_web_events WHERE business_id=? AND conversation_id=? AND event_id=?",
                         (bid, cid, eid))
        if current["claim_token"] != event["claim_token"] or current["status"] != "processing":
            return current
        if conv["mode"] != "AI_ACTIVE" or conv["version"] != event["version"]:
            error, reply = None, None  # human takeover fences in-flight model responses
        if reply is not None and error is None:
            _message(tx, bid, cid, eid, "assistant", reply)
        status = "failed" if error else "done"
        tx.execute("UPDATE kw_web_events SET status=?,error=? WHERE business_id=? AND conversation_id=? AND event_id=?",
                   (status, error, bid, cid, eid))
        return dict(current, status=status, error=error)


def inbox(bid, page=1):
    with transaction() as tx:
        where = "c.business_id=? AND EXISTS(SELECT 1 FROM kw_web_messages m WHERE m.business_id=c.business_id AND m.conversation_id=c.id)"
        total = tx.one("SELECT COUNT(*) AS n FROM kw_web_conversations c WHERE " + where,(bid,))['n']
        pages=max(1,(total+9)//10);page=min(max(1,page),pages)
        rows=tx.execute("SELECT c.*, (SELECT content FROM kw_web_messages m WHERE m.business_id=c.business_id "
                        "AND m.conversation_id=c.id ORDER BY m.id DESC LIMIT 1) AS preview "
                        "FROM kw_web_conversations c WHERE " + where + " ORDER BY c.updated_at DESC,c.id LIMIT 10 OFFSET ?",
                        (bid,(page-1)*10))
        return rows,total,page,pages


def conversation(bid,cid):
    with transaction() as tx:
        return _locked(tx,bid,cid)
