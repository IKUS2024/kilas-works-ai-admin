"""Jobs service and concurrency on disposable SQLite."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.pop('DATABASE_URL',None)
import db
from public_chat import schema
from kilas_core import customer_schema,job_schema,jobs
import kilas_jobs_cases


class JobsTests(kilas_jobs_cases.Cases,unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=patch.object(db,'SQLITE_PATH',str(Path(temp.name)/'jobs.db'))
        self.path.start();self.addCleanup(self.path.stop)
        with jobs.transaction() as tx:
            tx.execute('CREATE TABLE businesses(id INTEGER PRIMARY KEY)')
            tx.execute('INSERT INTO businesses VALUES (7),(8)')
            tx.execute('CREATE TABLE audit_log(actor_user_id INTEGER,business_id INTEGER,action TEXT,detail TEXT)')
        schema.apply_schema();customer_schema.apply_schema();job_schema.apply_schema()
        self.seed()


if __name__=='__main__': unittest.main()
