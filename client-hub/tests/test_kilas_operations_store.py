"""Phase 6 isolated SQLite fixtures. Prior unittest classes never imported by name."""
import os
import unittest
from unittest.mock import patch
import test_kilas_jobs_store as phase4
import kilas_jobs_cases
from kilas_core import jobs, attention, operation_schema
from kilas_core.operation_contracts import OperationError


class OperationsTests(unittest.TestCase):
    seed=kilas_jobs_cases.Cases.seed

    def setUp(self):
        phase4.JobsTests.setUp(self)
        with jobs.transaction() as tx:
            tx.execute("ALTER TABLE businesses ADD COLUMN package TEXT DEFAULT 'AI_ADMIN'")
            tx.execute("ALTER TABLE businesses ADD COLUMN status TEXT DEFAULT 'ACTIVE'")
            tx.execute('CREATE TABLE subscriptions(business_id INTEGER PRIMARY KEY,status TEXT)')
            tx.execute("INSERT INTO subscriptions VALUES (7,'ACTIVE'),(8,'ACTIVE')")
        operation_schema.apply_schema()
        flag=patch.dict(os.environ,{'KILAS_OPERATIONS_V2_ENABLED':'true','KILAS_JOBS_V2_ENABLED':'true',
            'KILAS_CUSTOMERS_V2_ENABLED':'true','KILAS_WEB_CHAT_ENABLED':'true','KILAS_CORE_V2_ENABLED':'true',
            'KILAS_CORE_V2_TEST_BUSINESS_IDS':'7,8'})
        flag.start();self.addCleanup(flag.stop)

    def test_attention_dedupe_resolution_and_references(self):
        with jobs.transaction() as tx:
            first=attention.ensure(tx,7,'human:conv','HUMAN_REPLY_NEEDED',conversation_id='conv')
            again=attention.ensure(tx,7,'human:conv','HUMAN_REPLY_NEEDED',conversation_id='conv')
            self.assertEqual(first,again)
            self.assertEqual(first['customer_id'],'alice')
        attention.resolve(7,first['id'],1)
        with jobs.transaction() as tx:
            self.assertEqual(attention.ensure(tx,7,'human:conv','HUMAN_REPLY_NEEDED',conversation_id='conv')['status'],'RESOLVED')
        self.assertEqual(attention.listing(7)['total'],0)
        self.assertEqual(attention.listing(7,status='RESOLVED')['total'],1)
        with self.assertRaises(OperationError): attention.resolve(8,first['id'],2)
        for kwargs in ({'conversation_id':'foreign'},{'customer_id':'other','conversation_id':'conv'}):
            with self.assertRaises((OperationError,jobs.JobError)):
                with jobs.transaction() as tx: attention.ensure(tx,7,'forged','HUMAN_REPLY_NEEDED',**kwargs)

    def test_schema_idempotent_and_foreign_fk(self):
        with jobs.transaction() as tx: row=attention.ensure(tx,7,'source','READY_FOR_QUOTE',customer_id='alice')
        operation_schema.apply_schema();operation_schema.apply_schema()
        self.assertEqual(attention.listing(7)['rows'][0]['id'],row['id'])
        with self.assertRaises(Exception):
            with jobs.transaction() as tx:
                tx.execute("UPDATE kw_core_attention SET customer_id='other' WHERE business_id=7")
        with patch.dict(os.environ,{'KILAS_OPERATIONS_V2_ENABLED':'false'}):
            with self.assertRaises(OperationError): attention.listing(7)
        with jobs.transaction() as tx: tx.execute("UPDATE subscriptions SET status='SUSPENDED' WHERE business_id=7")
        with self.assertRaises(OperationError): attention.listing(7)


if __name__=='__main__': unittest.main()
