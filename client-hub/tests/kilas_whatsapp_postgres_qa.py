"""Dedicated empty loopback PostgreSQL fixture only; never production."""
import os
import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit
if os.environ.get('KILAS_PHASE8_POSTGRES_QA')!='1': raise SystemExit('Explicit disposable QA flag required')
u=urlsplit(os.environ.get('DATABASE_URL',''))
if u.hostname not in ('127.0.0.1','localhost') or u.path!='/kilas_phase8': raise SystemExit('Dedicated loopback database only')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db
from kilas_whatsapp_runtime_cases import RuntimeCases

class RuntimePostgresTests(RuntimeCases,unittest.TestCase):
    def setUp(self):
        if db.BACKEND!='postgres': raise RuntimeError('PostgreSQL required')
        self.setup_runtime()

if __name__=='__main__': unittest.main()
