"""Same acceptance suite on disposable loopback PostgreSQL; additive/rollback rehearsal."""
import os
import sys
import uuid
import unittest
from pathlib import Path
from urllib.parse import urlsplit

if os.environ.get('TRADING_POSTGRES_QA')!='1' or urlsplit(os.environ.get('DATABASE_URL','')).hostname not in ('127.0.0.1','localhost'):
    raise SystemExit('Explicit disposable loopback PostgreSQL required')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db


def main():
    isolated='trading_qa_'+uuid.uuid4().hex
    control=db.psycopg2.connect(db.DATABASE_URL);control.autocommit=True
    with control.cursor() as cur:cur.execute('CREATE SCHEMA '+isolated)
    original=db._postgres_connect_kwargs
    db._postgres_connect_kwargs=lambda:dict(original(),options=original()['options']+' -c search_path='+isolated)
    try:
        db.init_schema()
        before={r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
        from kilas_trading import schema
        assert schema.apply_release()==[schema.NAME]
        assert schema.apply_release()==[]
        after={r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
        assert after-before=={'kilas_trading_accounts','kilas_trading_positions','kilas_trading_events','kilas_trading_releases'}
        import test_kilas_trading as f
        import test_kilas_trading_analysis as analyst
        import test_kilas_trading_observation as observation
        suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(f.TradingTests),unittest.defaultTestLoader.loadTestsFromTestCase(analyst.AnalysisTests),unittest.defaultTestLoader.loadTestsFromTestCase(observation.ObservationTests)])
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful():raise SystemExit(1)
        # Old application can read its original tables after Trader installation.
        assert db.query_one('SELECT count(*) AS n FROM users')['n']==3
        print('PostgreSQL PASS: additive four-table boundary/idempotence, concurrent operations, old users readback.')
    finally:
        db.get_connection().close()
        with control.cursor() as cur:cur.execute('DROP SCHEMA '+isolated+' CASCADE')
        control.close()


if __name__=='__main__':main()
