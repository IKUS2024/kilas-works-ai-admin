"""Safe diagnostics; isolated SQLite fixtures and mocked PostgreSQL, no network."""
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
import test_single_plan_release as f
import routes_admin

usage, db, repo, hub = f.ai_usage, f.db, f.repo, f.app

class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        fixture=f.SinglePlanTests();fixture.setUp()
        self.client=fixture.client;self.uid=fixture.uid
        db.execute("UPDATE users SET role='KILAS_ADMIN' WHERE id=?",(self.uid,))
        self.network=patch('requests.sessions.Session.request',side_effect=AssertionError('no external calls'))
        self.network.start();self.addCleanup(self.network.stop)

    def test_valid_schema_dashboard_200(self):
        before=db.query_all('SELECT * FROM sqlite_master ORDER BY name')
        usage.check_monthly_schema()
        self.assertEqual(self.client.get('/admin/ai-usage').status_code,200)
        self.assertEqual(before,db.query_all('SELECT * FROM sqlite_master ORDER BY name'))
        self.assertEqual(db.query_one('SELECT COUNT(*) n FROM ai_usage_ledger')['n'],0)

    def test_missing_table_503_and_safe_root_cause(self):
        db.execute('DROP TABLE ai_usage_ledger')
        with self.assertLogs('ai_usage',level='ERROR') as logs:
            response=self.client.get('/admin/ai-usage')
        self.assertEqual(response.status_code,503)
        self.assertIn('request_schema',logs.output[0])
        self.assertIn('exception_type=OperationalError',logs.output[0])
        self.assertIn('required_relation_missing',logs.output[0])
        self.assertNotIn('OperationalError',response.get_data(as_text=True))
        self.assertIsNone(db.query_one("SELECT name FROM sqlite_master WHERE name='ai_usage_ledger'"))

    def test_missing_column_detected_before_monthly(self):
        db.execute('ALTER TABLE ai_usage_ledger RENAME COLUMN is_reply TO missing_test_column')
        with patch.object(usage,'monthly') as monthly,self.assertLogs('ai_usage',level='ERROR') as logs:
            response=self.client.get('/admin/ai-usage')
        self.assertEqual(response.status_code,503);monthly.assert_not_called()
        self.assertIn('required_column_missing:is_reply',logs.output[0])

    def test_calculation_failure_message_is_allowlisted_not_raw(self):
        secret='postgres://alice:password@private.example/db?token=abcdef person@example.test 628999001122'
        error=TypeError('unsupported operand type(s) '+secret)
        with patch.object(usage,'monthly',side_effect=error),self.assertLogs('ai_usage',level='ERROR') as logs:
            response=self.client.get('/admin/ai-usage')
        self.assertEqual(response.status_code,503)
        text=' '.join(logs.output)+response.get_data(as_text=True)
        self.assertIn('exception_type=TypeError',text);self.assertIn('incompatible_calculation_types',text)
        for token in ('postgres://','alice','password','private.example','abcdef','person@example.test','628999001122'):
            self.assertNotIn(token,text)
        self.assertIn('phase=monthly',text)

    def test_unknown_error_does_not_log_sql_parameters_or_pii(self):
        with patch.object(repo,'list_all_businesses',side_effect=ValueError("SELECT secret FROM x: Irvan customer@example.test DATABASE_URL=private token=abc")),self.assertLogs('ai_usage',level='ERROR') as logs:
            response=self.client.get('/admin/ai-usage')
        self.assertEqual(response.status_code,503)
        text=' '.join(logs.output)
        self.assertIn('phase=businesses exception_type=ValueError message=details_redacted',text)
        for value in ('Irvan','customer@example.test','DATABASE_URL','token=abc','SELECT'):
            self.assertNotIn(value,text)

    def test_postgres_error_classification_without_credentials(self):
        for code,expected in [('42P01','required_relation_missing'),('42703','required_column_missing'),('42501','database_permission_denied'),('57014','database_timeout'),('28P01','database_authentication_failed')]:
            error=sqlite3.OperationalError('PRIVATE_NAME SECRET_TOKEN URL');error.pgcode=code
            with self.assertLogs('ai_usage',level='ERROR') as logs:usage.log_dashboard_failure(error,'request_schema')
            self.assertIn(expected,logs.output[0]);self.assertNotIn('SECRET',logs.output[0]);self.assertNotIn('PRIVATE',logs.output[0])

    def test_postgres_probe_readonly_bounded_and_closes(self):
        conn=Mock();cursor=conn.cursor.return_value
        driver=Mock();driver.connect.return_value=conn
        with patch.object(db,'BACKEND','postgres'),patch.object(db,'psycopg2',driver,create=True):
            usage.check_monthly_schema()
        connect=driver.connect
        conn.set_session.assert_called_once_with(readonly=True,autocommit=True)
        sql=cursor.execute.call_args.args[0]
        self.assertTrue(sql.startswith('SELECT '));self.assertTrue(sql.endswith('WHERE 1=0'))
        for col in usage.MONTHLY_COLUMNS:self.assertIn(col,sql)
        self.assertLessEqual(connect.call_args.kwargs['connect_timeout'],2)
        self.assertIn('statement_timeout=1500',connect.call_args.kwargs['options'])
        conn.commit.assert_not_called();conn.rollback.assert_not_called();conn.close.assert_called_once();cursor.close.assert_called_once()

    def test_probe_failure_does_not_commit_or_rollback_caller(self):
        caller=db.get_connection();caller.execute('BEGIN')
        try:
            self.assertTrue(caller.in_transaction)
            usage.check_monthly_schema()
            self.assertTrue(caller.in_transaction)
        finally:caller.rollback()

    def test_missing_sqlite_file_not_created(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'absent.db'
            with patch.object(db,'SQLITE_PATH',str(path)):
                with self.assertRaises(sqlite3.OperationalError):usage.check_monthly_schema()
            self.assertFalse(path.exists())

    def test_startup_schema_failure_is_nonfatal_and_logged(self):
        with patch.object(usage,'check_monthly_schema',side_effect=sqlite3.OperationalError('no such table: ai_usage_ledger')),self.assertLogs('ai_usage',level='ERROR') as logs:
            app=hub.create_app()
        self.assertIsNotNone(app)
        self.assertTrue(any('phase=startup_schema' in line for line in logs.output))

    def test_nonadmin_never_runs_probe(self):
        db.execute("UPDATE users SET role='CLIENT_OWNER' WHERE id=?",(self.uid,))
        with patch.object(usage,'check_monthly_schema') as probe:
            self.assertEqual(self.client.get('/admin/ai-usage').status_code,403)
            self.assertEqual(hub.app.test_client().get('/admin/ai-usage').status_code,302)
        probe.assert_not_called()

    def test_broken_template_still_503_no_raw_error(self):
        with patch.object(routes_admin,'render_template',side_effect=RuntimeError('SECRET_TEMPLATE_DATA')),self.assertLogs('ai_usage',level='ERROR') as logs:
            response=self.client.get('/admin/ai-usage')
        self.assertEqual(response.status_code,503)
        self.assertNotIn('SECRET_TEMPLATE_DATA',response.get_data(as_text=True)+' '.join(logs.output))
        self.assertTrue(any('phase=fallback_render' in line for line in logs.output))

if __name__=='__main__':unittest.main()
