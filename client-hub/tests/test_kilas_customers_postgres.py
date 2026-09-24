"""PostgreSQL-only Phase 3 customer identity validation on a disposable database."""
import os
import sys
import unittest
from pathlib import Path

if os.environ.get("KILAS_PHASE3_POSTGRES_QA") != "1":
    raise SystemExit("KILAS_PHASE3_POSTGRES_QA=1 is required")

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB))

import db
from public_chat import schema as web_schema, store
from kilas_core import customer_schema, customers


class CustomerPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if db.BACKEND != "postgres":
            raise RuntimeError("PostgreSQL backend required")
        conn = db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs())
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            DROP TABLE IF EXISTS kw_web_customer_links, kw_core_customer_identities, kw_core_customers,
                kw_web_messages, kw_web_events, kw_web_conversations, kw_web_channels, kw_web_limits,
                audit_log, businesses CASCADE;
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
            VALUES (7,'Kedai Demo','AI_ADMIN_PRO','ACTIVE'),
                   (8,'Bisnis Dua','AI_ADMIN_PRO','ACTIVE');
        """)
        cur.close(); conn.close()
        web_schema.apply_schema()
        customer_schema.apply_schema()

    @classmethod
    def tearDownClass(cls):
        conn = db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs())
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            DROP TABLE IF EXISTS kw_web_customer_links, kw_core_customer_identities, kw_core_customers,
                kw_web_messages, kw_web_events, kw_web_conversations, kw_web_channels, kw_web_limits,
                audit_log, businesses CASCADE;
        """)
        cur.close(); conn.close()

    def setUp(self):
        with store.transaction() as tx:
            for table in ("kw_web_customer_links","kw_core_customer_identities","kw_core_customers",
                          "kw_web_messages","kw_web_events","kw_web_conversations","kw_web_channels","kw_web_limits"):
                tx.execute("DELETE FROM " + table)
        store.ensure_channel(7)
        store.ensure_channel(8)

    def test_web_identity_reuse_and_tenant_isolation(self):
        with customers.transaction() as tx:
            one = customers.ensure_web_customer(tx, 7, self._conversation(tx,7,"conv-a","hash-a"), "hash-a")
            same = customers.ensure_web_customer(tx, 7, "conv-a", "hash-a")
            other = customers.ensure_web_customer(tx, 8, self._conversation(tx,8,"conv-b","hash-a"), "hash-a")
        self.assertEqual(one["id"], same["id"])
        self.assertNotEqual(one["id"], other["id"])

    def _conversation(self, tx, bid, cid, visitor_hash):
        now = 1_800_000_000
        tx.execute(
            "INSERT INTO kw_web_conversations(id,business_id,visitor_hash,expires_at,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (cid,bid,visitor_hash,now+1000,now,now),
        )
        return cid

    def test_name_only_never_merges_and_profile_contact_stays_unverified(self):
        with customers.transaction() as tx:
            self._conversation(tx,7,"conv-c","hash-c")
            self._conversation(tx,7,"conv-d","hash-d")
            one=customers.ensure_web_customer(tx,7,"conv-c","hash-c")
            two=customers.ensure_web_customer(tx,7,"conv-d","hash-d")
        customers.update_customer(7,one["id"],display_name="Budi",phone="0811")
        customers.update_customer(7,two["id"],display_name="Budi",phone="0811")
        self.assertNotEqual(one["id"],two["id"])
        with customers.transaction() as tx:
            identities=tx.execute("SELECT identity_type FROM kw_core_customer_identities WHERE business_id=7")
        self.assertEqual([r["identity_type"] for r in identities],["WEB_VISITOR","WEB_VISITOR"])


if __name__ == "__main__":
    unittest.main()
