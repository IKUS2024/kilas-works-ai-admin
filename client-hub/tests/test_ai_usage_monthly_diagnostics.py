"""Monthly phase diagnosis; safe PostgreSQL SQLSTATE/types, no real provider or PG call."""
import unittest
from unittest.mock import Mock, patch
import test_single_plan_release as f

usage,db,repo,hub=f.ai_usage,f.db,f.repo,f.app

class UndefinedFunction(Exception):
    __module__='psycopg2.errors'
    pgcode='42883'
    def __str__(self):
        raise AssertionError('PostgreSQL message must never be inspected')

class MonthlyDiagnosticTests(unittest.TestCase):
    def setUp(self):
        fixture=f.SinglePlanTests();fixture.setUp()
        self.client=fixture.client;self.uid=fixture.uid
        db.execute("UPDATE users SET role='KILAS_ADMIN' WHERE id=?",(self.uid,))
        self.network=patch('requests.sessions.Session.request',side_effect=AssertionError('offline'))
        self.network.start();self.addCleanup(self.network.stop)

    def test_query_failure_503_precise_state_no_raw_message(self):
        with patch.object(db,'query_all',side_effect=UndefinedFunction()),self.assertLogs('ai_usage',level='ERROR') as logs:
            response=self.client.get('/admin/ai-usage')
        self.assertEqual(response.status_code,503)
        self.assertEqual(len(logs.output),1)
        line=logs.output[0]
        self.assertIn('phase=monthly_query',line)
        self.assertIn('exception_type=UndefinedFunction',line)
        self.assertIn('sqlstate=42883',line)
        self.assertIn('message=undefined_function_or_operator',line)
        self.assertNotIn('42883',response.get_data(as_text=True))

    def test_transform_failure_503_no_row_values(self):
        rows=[{'tenant_id':123,'calls':'private person@example.test 6289990011 token=abc DATABASE_URL=secret'}]
        with patch.object(db,'query_all',return_value=rows),self.assertLogs('ai_usage',level='ERROR') as logs:
            response=self.client.get('/admin/ai-usage')
        self.assertEqual(response.status_code,503);self.assertEqual(len(logs.output),1)
        text=' '.join(logs.output)+response.get_data(as_text=True)
        self.assertIn('phase=monthly_transform',text);self.assertIn('exception_type=ValueError',text)
        for value in ('person@example.test','6289990011','token=abc','DATABASE_URL','123'):
            self.assertNotIn(value,text)

    def test_transform_calculation_not_relabelled_database_query(self):
        rows=[dict(tenant_id=1,calls=1,replies=1,cost_usd='private-value',cost_idr=None)]
        with patch.object(db,'query_all',return_value=rows),self.assertLogs('ai_usage',level='ERROR') as logs:
            with self.assertRaises(TypeError):usage.monthly(admin=True)
        self.assertIn('phase=monthly_transform',logs.output[0])
        self.assertNotIn('private-value',logs.output[0]);self.assertNotIn('monthly_query',logs.output[0])

    def test_pg_sqlstate_validation_and_class_allowlist(self):
        Unknown=type('SECRET_CUSTOMER', (Exception,), {'__module__':'psycopg2.errors'})
        for state in ('42804','22P02','42703','42P01','42P10','25P02','XX000','token=SECRET','42883\nPII',None):
            error=Unknown('postgres://user:password@host/db params customer@example.test')
            error.pgcode=state
            with self.assertLogs('ai_usage',level='ERROR') as logs:usage.log_dashboard_failure(error,'monthly_query')
            line=logs.output[0]
            self.assertIn('exception_type=Exception',line)
            for text in ('SECRET','postgres://','password','customer@example.test','params'):
                self.assertNotIn(text,line)
            if state and len(state)==5:self.assertIn('sqlstate='+state,line)
            else:self.assertIn('sqlstate=unknown',line)

    def test_type_probe_only_allowlisted_names_and_builtin_types(self):
        cursor=Mock()
        cursor.fetchall.return_value=[('tenant_id','int4'),('is_reply','bool'),('created_at','timestamptz'),
            ('input_tokens','numeric'),('estimated_cost_usd','float8'),('model','private_custom_type'),
            ('SECRET_COLUMN','text')]
        with self.assertLogs('ai_usage',level='WARNING') as logs:usage._log_postgres_monthly_types(cursor)
        line=logs.output[0]
        for text in ('"is_reply": "bool"','"input_tokens": "numeric"','"model": "unknown"'):
            self.assertIn(text,line)
        self.assertNotIn('private_custom_type',line);self.assertNotIn('SECRET_COLUMN',line)
        sql,params=cursor.execute.call_args.args
        self.assertTrue(sql.startswith('SELECT '));self.assertIn('pg_catalog.pg_attribute',sql)
        self.assertIn("to_regclass('ai_usage_ledger')",sql)
        self.assertEqual(params,(list(usage.MONTHLY_COLUMNS),))
        self.assertNotIn('FROM ai_usage_ledger',sql)

    def test_probe_connection_readonly_and_metadata_failure_nonfatal(self):
        for failed in (False,True):
            conn=Mock();cursor=conn.cursor.return_value
            cursor.fetchall.return_value=[(c,'text') for c in usage.MONTHLY_COLUMNS]
            if failed:cursor.execute.side_effect=[UndefinedFunction(),None]
            driver=Mock();driver.connect.return_value=conn
            with patch.object(db,'BACKEND','postgres'),patch.object(db,'psycopg2',driver,create=True),self.assertLogs('ai_usage',level='WARNING') as logs:
                usage.check_monthly_schema()
            conn.set_session.assert_called_once_with(readonly=True,autocommit=True)
            self.assertEqual(cursor.execute.call_count,2)
            self.assertTrue(cursor.execute.call_args.args[0].endswith('WHERE 1=0'))
            conn.close.assert_called_once();cursor.close.assert_called_once()
            conn.commit.assert_not_called();conn.rollback.assert_not_called()
            self.assertIn('phase=monthly_schema_types',' '.join(logs.output))
            if failed:self.assertIn('sqlstate=42883',' '.join(logs.output))

    def test_sqlite_does_not_query_pg_metadata(self):
        with patch.object(usage,'_log_postgres_monthly_types',side_effect=AssertionError('PG only')):
            usage.check_monthly_schema()
            self.assertEqual(self.client.get('/admin/ai-usage').status_code,200)

    def test_query_tenant_parameters_preserved_not_logged(self):
        with patch.object(db,'query_all',return_value=[]) as query:
            rows=usage.monthly(71)
        self.assertIn('AND tenant_id = ?',query.call_args.args[0])
        self.assertEqual(query.call_args.args[1][-1],71)
        self.assertEqual(rows[0]['tenant_id'],71)
        with patch.object(db,'query_all') as query:
            with self.assertRaises(ValueError):usage.monthly()
        query.assert_not_called()

if __name__=='__main__':unittest.main()
