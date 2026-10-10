"""Run one isolated offline control/analyst suite on disposable loopback PG."""
import importlib
import os
import sys
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit

SUITES={
    'control':('test_kilas_trading_control','ControlTests'),
    'btc-analysis':('test_kilas_trading_btc_analysis','BTCAnalysisTests'),
    'btc-sources':('test_kilas_trading_btc_sources','SourceTests'),
    'gold':('test_kilas_trading_gold','GoldTests'),
}

def main():
    if (len(sys.argv)!=2 or sys.argv[1] not in SUITES
            or os.environ.get('TRADING_POSTGRES_QA')!='1'
            or urlsplit(os.environ.get('DATABASE_URL','')).hostname not in ('127.0.0.1','localhost')):
        raise SystemExit('Named suite and explicit disposable loopback PostgreSQL required')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    import db
    isolated='trading_session_qa_'+uuid.uuid4().hex
    admin=db.psycopg2.connect(db.DATABASE_URL);admin.autocommit=True
    with admin.cursor() as cur:cur.execute('CREATE SCHEMA '+isolated)
    original=db._postgres_connect_kwargs
    db._postgres_connect_kwargs=lambda:dict(original(),options=original()['options']+' -c search_path='+isolated)
    try:
        db.init_schema()
        # The disposable schema is already initialized. Avoid a second global
        # startup migration pass when the test fixture imports the Flask app.
        os.environ['RUN_MIGRATIONS_ON_BOOT']='false'
        module,klass=SUITES[sys.argv[1]]
        suite=unittest.defaultTestLoader.loadTestsFromTestCase(getattr(importlib.import_module(module),klass))
        if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():raise SystemExit(1)
    finally:
        db.get_connection().close()
        with admin.cursor() as cur:cur.execute('DROP SCHEMA '+isolated+' CASCADE')
        admin.close()

if __name__=='__main__':main()
