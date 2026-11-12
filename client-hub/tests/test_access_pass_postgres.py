"""Run the same integration matrix against a disposable loopback PostgreSQL schema.

No production hostname is admitted. The random schema is created and removed by
this runner; every application and billing connection uses only that schema.
"""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4


def main():
    url = os.environ.get('DATABASE_URL', '')
    if (os.environ.get('KILAS_AI_POSTGRES_QA') != '1'
            or urlsplit(url).hostname not in ('localhost', '127.0.0.1')):
        raise SystemExit('Explicit disposable loopback PostgreSQL required')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import db
    if db.BACKEND != 'postgres':
        raise SystemExit('PostgreSQL backend required')
    isolated = 'access_pass_qa_' + uuid4().hex
    control = db.psycopg2.connect(url)
    control.autocommit = True
    with control.cursor() as cursor:
        cursor.execute('CREATE SCHEMA ' + isolated)
    original = db._postgres_connect_kwargs
    def options():
        values = original()
        return dict(values, options=values.get('options', '') + ' -c search_path=' + isolated + ' -c timezone=UTC')
    try:
        with patch.object(db, '_postgres_connect_kwargs', side_effect=options):
            # Clear any cached connection before applying the schema isolation.
            db._discard_cached_connection()
            db.init_schema()
            assert db.query_one('SELECT current_schema() AS name')['name'] == isolated
            db._platform_payments_qa_schema = isolated
            import test_access_pass as suite
            assert suite.db.BACKEND == 'postgres'
            tests = unittest.defaultTestLoader.loadTestsFromTestCase(suite.AccessPassTests)
            result = unittest.TextTestRunner(verbosity=2).run(tests)
            return 0 if result.wasSuccessful() else 1
    finally:
        db._discard_cached_connection()
        if hasattr(db, '_platform_payments_qa_schema'):
            del db._platform_payments_qa_schema
        with control.cursor() as cursor:
            cursor.execute('DROP SCHEMA ' + isolated + ' CASCADE')
        control.close()


if __name__ == '__main__':
    raise SystemExit(main())
