"""Phase 5 actions/concurrency in the dedicated loopback CI PostgreSQL fixture.

Run AFTER Phase 4 PostgreSQL QA. No production endpoint/database accepted.
"""
import os
import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit
if os.environ.get('KILAS_PHASE5_POSTGRES_QA') != '1':
    raise SystemExit('KILAS_PHASE5_POSTGRES_QA=1 required')
target = urlsplit(os.environ.get('DATABASE_URL',''))
if target.hostname not in ('127.0.0.1','localhost') or target.path != '/kilas_phase4':
    raise SystemExit('Only dedicated loopback kilas_phase4 CI database is allowed')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db
from kilas_core import jobs, job_schema
import kilas_jobs_cases
import kilas_playbook_cases


class PlaybookPostgresTests(kilas_playbook_cases.ActionCases, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if db.BACKEND != 'postgres': raise RuntimeError('PostgreSQL required')
        with jobs.transaction() as tx:
            if tx.one('SELECT request_text FROM kilas_order_requests WHERE id=1')['request_text'] != 'Legacy row unchanged':
                raise RuntimeError('Expected disposable Phase 4 fixture only')
        job_schema.apply_schema()

    def setUp(self):
        kilas_jobs_cases.Cases.seed(self)
        self.reset_web()

    def test_additive_existing_schema_and_legacy_preserved(self):
        row, _ = self.apply({'item':'baju'})
        job_schema.apply_schema()
        self.assertEqual(jobs.get_job(7,row['id']),row)
        with jobs.transaction() as tx:
            self.assertEqual(tx.one('SELECT request_text FROM kilas_order_requests')['request_text'],'Legacy row unchanged')


if __name__ == '__main__': unittest.main()
