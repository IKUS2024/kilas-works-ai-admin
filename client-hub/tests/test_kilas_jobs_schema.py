"""Additive Jobs schema on isolated SQLite; no legacy migration runner."""
import os
import sys
import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop('DATABASE_URL', None)
import db
from public_chat import schema
from kilas_core import customer_schema, job_schema, customers


class SchemaTests(unittest.TestCase):
    def test_additive_idempotent_schema_and_tenant_link_constraints(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(db,'SQLITE_PATH',str(Path(directory)/'jobs.db')):
            with customers.transaction() as tx:
                tx.execute('CREATE TABLE businesses(id INTEGER PRIMARY KEY)')
                tx.execute('INSERT INTO businesses VALUES (7),(8)')
                tx.execute('CREATE TABLE kilas_order_requests(id INTEGER PRIMARY KEY,request_text TEXT)')
                tx.execute("INSERT INTO kilas_order_requests VALUES (1,'Preserve legacy')")
            schema.apply_schema(); customer_schema.apply_schema()
            job_schema.apply_schema(); job_schema.apply_schema()
            with customers.transaction() as tx:
                for bid, cid in ((7,'a'),(7,'b'),(8,'c')):
                    tx.execute("INSERT INTO kw_core_customers VALUES (?,?,?,NULL,NULL,NULL,'WEB',1,1,1)",(bid,cid,cid))
                tx.execute("INSERT INTO kw_web_channels(business_id,slug) VALUES (7,'seven')")
                tx.execute("INSERT INTO kw_web_conversations(business_id,id,visitor_hash,expires_at,created_at,updated_at) VALUES (7,'conv','hash',100,1,1)")
                tx.execute("INSERT INTO kw_web_customer_links VALUES (7,'conv','a',1)")
            insert = "INSERT INTO kw_core_jobs(business_id,id,customer_id,conversation_id,kind,title,created_at,updated_at) VALUES (7,?,?,?,?,?,1,1)"
            for cust, conv in [('c',None),('b','conv'),('a','foreign')]:
                with self.assertRaises(sqlite3.IntegrityError), customers.transaction() as tx:
                    tx.execute(insert,('bad',cust,conv,'GENERIC','Title'))
            with customers.transaction() as tx:
                tx.execute(insert,('valid','a','conv','GENERIC','Title'))
                self.assertEqual(tx.one('SELECT request_text FROM kilas_order_requests')['request_text'],'Preserve legacy')
                self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM kw_core_jobs')['n'],1)


if __name__ == '__main__':
    unittest.main()
