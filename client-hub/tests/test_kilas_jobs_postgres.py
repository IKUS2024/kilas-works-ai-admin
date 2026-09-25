"""Jobs runtime/concurrency certification: dedicated local disposable PostgreSQL only."""
import os
import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit

if os.environ.get('KILAS_PHASE4_POSTGRES_QA') != '1':
    raise SystemExit('KILAS_PHASE4_POSTGRES_QA=1 required')
target=urlsplit(os.environ.get('DATABASE_URL',''))
if target.hostname not in ('127.0.0.1','localhost') or target.path != '/kilas_phase4':
    raise SystemExit('Only the dedicated loopback kilas_phase4 QA database is allowed')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db
from public_chat import schema
from kilas_core import customer_schema,job_schema,jobs
import kilas_jobs_cases


class JobsPostgresTests(kilas_jobs_cases.Cases,unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if db.BACKEND != 'postgres': raise RuntimeError('PostgreSQL required')
        # Empty disposable CI database after previous phase suites clean up.
        with jobs.transaction() as tx:
            tx.execute('CREATE TABLE businesses(id INTEGER PRIMARY KEY)')
            tx.execute('INSERT INTO businesses VALUES (7),(8)')
            tx.execute('CREATE TABLE audit_log(actor_user_id INTEGER,business_id INTEGER,action TEXT,detail TEXT)')
            tx.execute('CREATE TABLE kilas_order_requests(id INTEGER PRIMARY KEY,request_text TEXT)')
            tx.execute("INSERT INTO kilas_order_requests VALUES (1,'Legacy row unchanged')")
        schema.apply_schema();customer_schema.apply_schema();job_schema.apply_schema()

    def setUp(self): self.seed()

    def test_legacy_row_preserved(self):
        self.create();job_schema.apply_schema()
        with jobs.transaction() as tx:
            self.assertEqual(tx.one('SELECT request_text FROM kilas_order_requests')['request_text'],'Legacy row unchanged')

    def test_concurrent_tenants_never_cross_link(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier=Barrier(2)
        def run(bid):
            barrier.wait()
            return self.create(business_id=bid,customer_id='alice' if bid==7 else 'other',
                               conversation_id='conv' if bid==7 else 'foreign',actor_id=1 if bid==7 else 2)
        with ThreadPoolExecutor(max_workers=2) as pool: rows=list(pool.map(run,(7,8)))
        self.assertNotEqual(rows[0]['id'],rows[1]['id'])
        for row in rows:
            self.assertEqual(jobs.get_job(row['business_id'],row['id'])['customer_id'],row['customer_id'])


if __name__=='__main__': unittest.main()
