"""PostgreSQL-only Phase 2 validation on a disposable database.

Never point this test at production. It creates and drops a minimal schema fixture and applies
ONLY the additive 0055 public-web-chat migration.
"""
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

if os.environ.get("KILAS_PHASE2_POSTGRES_QA") != "1":
    raise SystemExit("KILAS_PHASE2_POSTGRES_QA=1 is required")

import db
from public_chat import schema, store


class PublicChatPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if db.BACKEND != "postgres":
            raise RuntimeError("PostgreSQL backend required")
        conn = db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs())
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            DROP TABLE IF EXISTS kw_web_messages, kw_web_events, kw_web_conversations,
                kw_web_channels, kw_web_limits, audit_log, businesses CASCADE;
            CREATE TABLE businesses (
                id INTEGER PRIMARY KEY,
                business_name TEXT,
                package TEXT,
                status TEXT
            );
            CREATE TABLE audit_log (
                id BIGSERIAL PRIMARY KEY,
                actor_user_id INTEGER,
                business_id INTEGER,
                action TEXT,
                detail TEXT,
                project_id INTEGER
            );
            INSERT INTO businesses(id,business_name,package,status)
            VALUES (7,'Kedai Demo','AI_ADMIN','ACTIVE'),
                   (8,'Bisnis Kedua','AI_ADMIN','ACTIVE');
        """)
        cur.close()
        conn.close()
        schema.apply_schema()

    @classmethod
    def tearDownClass(cls):
        conn = db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs())
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            DROP TABLE IF EXISTS kw_web_messages, kw_web_events, kw_web_conversations,
                kw_web_channels, kw_web_limits, audit_log, businesses CASCADE;
        """)
        cur.close()
        conn.close()

    def setUp(self):
        with store.transaction() as tx:
            for table in ("kw_web_messages","kw_web_events","kw_web_conversations",
                          "kw_web_channels","kw_web_limits","audit_log"):
                tx.execute("DELETE FROM " + table)

    def test_0055_foreign_keys_and_tenant_scope(self):
        seven = store.ensure_channel(7)
        eight = store.ensure_channel(8)
        self.assertNotEqual(seven["slug"], eight["slug"])
        conv, token = store.visitor(7, None, "ip-seven")
        self.assertEqual(store.authorized(7, conv["id"], token)["business_id"], 7)
        with self.assertRaises(store.ChatError):
            store.authorized(8, conv["id"], token)

        with self.assertRaises(Exception):
            with store.transaction() as tx:
                tx.execute(
                    "INSERT INTO kw_web_conversations"
                    "(id,business_id,visitor_hash,expires_at,created_at,updated_at)"
                    " VALUES (?,?,?,?,?,?)",
                    ("bad", 999, "x", 9999999999, 1, 1),
                )

    def test_concurrent_rate_limit_is_atomic(self):
        barrier = threading.Barrier(2)
        def hit(_):
            try:
                barrier.wait(timeout=5)
                with store.transaction() as tx:
                    store.limit(tx, "pg-concurrent", 60, 1, now=1_800_000_000)
                return "ok"
            except store.ChatError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(hit, range(2)))
        self.assertEqual(sorted(results), ["ok", "rate_limited"])

    def test_duplicate_claim_and_retry_fencing(self):
        store.ensure_channel(7)
        conv, _ = store.visitor(7, None, "claim-ip")
        cid = conv["id"]
        first, history = store.claim(7, cid, "event-00000000001", "Halo", "claim-ip")
        self.assertEqual(first["status"], "processing")
        self.assertEqual(history, [])
        second, history2 = store.claim(7, cid, "event-00000000001", "Halo", "claim-ip")
        self.assertIsNone(history2)
        self.assertEqual(second["claim_token"], first["claim_token"])
        store.finish(first, reply="Balasan")
        self.assertEqual([m["role"] for m in store.thread(7, cid)], ["user", "assistant"])

    def test_human_takeover_fences_ai_and_manual_reply(self):
        store.ensure_channel(7)
        conv, _ = store.visitor(7, None, "takeover-ip")
        cid = conv["id"]
        event, _ = store.claim(7, cid, "event-00000000002", "Butuh bantuan", "takeover-ip")
        store.set_mode(7, cid, "HUMAN_TAKEOVER", 1)
        store.finish(event, reply="STILL_AI")
        self.assertEqual([m["role"] for m in store.thread(7, cid)], ["user"])
        mid = store.human_reply(7, cid, "human-00000000001", "Balasan tim", 1)
        self.assertIsInstance(mid, int)
        self.assertEqual([m["role"] for m in store.thread(7, cid)], ["user", "human"])


if __name__ == "__main__":
    unittest.main()
