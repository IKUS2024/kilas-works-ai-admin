"""Phase 6 paired 0058/runtime validation, dedicated loopback CI database only."""
import os
import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch
if os.environ.get('KILAS_PHASE6_POSTGRES_QA') != '1':
    raise SystemExit('KILAS_PHASE6_POSTGRES_QA=1 required')
target=urlsplit(os.environ.get('DATABASE_URL',''))
if target.hostname not in ('127.0.0.1','localhost') or target.path != '/kilas_phase4':
    raise SystemExit('Only dedicated loopback kilas_phase4 CI database is allowed')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db
from kilas_core import jobs, operation_schema, attention
import kilas_jobs_cases
import kilas_operations_cases


class OperationsPostgresTests(kilas_operations_cases.Cases,unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if db.BACKEND != 'postgres': raise RuntimeError('PostgreSQL required')
        with jobs.transaction() as tx:
            if tx.one('SELECT request_text FROM kilas_order_requests WHERE id=1')['request_text'] != 'Legacy row unchanged':
                raise RuntimeError('Expected disposable Phase 4 fixture only')
            tx.execute("ALTER TABLE businesses ADD COLUMN IF NOT EXISTS package TEXT DEFAULT 'AI_ADMIN'")
            tx.execute("ALTER TABLE businesses ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'ACTIVE'")
            tx.execute('CREATE TABLE IF NOT EXISTS subscriptions(business_id BIGINT PRIMARY KEY,status TEXT)')
            tx.execute("INSERT INTO subscriptions VALUES (7,'ACTIVE'),(8,'ACTIVE') ON CONFLICT(business_id) DO UPDATE SET status='ACTIVE'")
        operation_schema.apply_schema()

    def setUp(self):
        with jobs.transaction() as tx:
            for table in ('kw_core_automation_runs','kw_core_attention','kw_core_automation_config'):
                tx.execute('DELETE FROM '+table)
        kilas_jobs_cases.Cases.seed(self)
        flag=patch.dict(os.environ,{'KILAS_OPERATIONS_V2_ENABLED':'true','KILAS_JOBS_V2_ENABLED':'true',
            'KILAS_CUSTOMERS_V2_ENABLED':'true','KILAS_WEB_CHAT_ENABLED':'true','KILAS_CORE_V2_ENABLED':'true',
            'KILAS_CORE_V2_TEST_BUSINESS_IDS':'7,8'})
        flag.start();self.addCleanup(flag.stop)
        timer=patch('kilas_core.automations.clock',side_effect=lambda now=None:1000 if now is None else now)
        timer.start();self.addCleanup(timer.stop)
        self.operational_seed()

    def test_0058_additive_idempotence_tenant_fk_and_legacy_preserved(self):
        with jobs.transaction() as tx: row=attention.ensure(tx,7,'pg-source','HUMAN_REPLY_NEEDED',conversation_id='conv')
        operation_schema.apply_schema();operation_schema.apply_schema()
        self.assertEqual(attention.listing(7)['rows'][0]['id'],row['id'])
        with self.assertRaises(Exception):
            with jobs.transaction() as tx: tx.execute("UPDATE kw_core_attention SET customer_id='other' WHERE business_id=7")
        with jobs.transaction() as tx:
            self.assertEqual(tx.one('SELECT request_text FROM kilas_order_requests WHERE id=1')['request_text'],'Legacy row unchanged')


if __name__=='__main__': unittest.main()
