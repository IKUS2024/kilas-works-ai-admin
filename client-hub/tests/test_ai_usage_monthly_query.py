"""Bound LIKE patterns through the actual PostgreSQL adapter; SQLite result parity."""
import re
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import test_single_plan_release as f

usage, db, repo = f.ai_usage, f.db, f.repo

class MonthlyQueryTests(unittest.TestCase):
    def setUp(self):
        fixture=f.SinglePlanTests();fixture.setUp()
        self.bid=fixture.bid;self.other=fixture.other
        self.network=patch('requests.sessions.Session.request',side_effect=AssertionError('offline'))
        self.network.start();self.addCleanup(self.network.stop)

    def postgres_query(self, admin):
        conn=Mock();cursor=conn.cursor.return_value
        cursor.description=None;cursor.fetchall.return_value=[]
        def validate(sql,params):
            # Reject any raw percent token that psycopg2 could interpret as formatting.
            self.assertNotIn('%',sql.replace('%s',''))
            self.assertEqual(sql.count('model LIKE %s'),2)
            self.assertNotIn('claude-haiku-',sql);self.assertNotIn('claude-sonnet-',sql)
            self.assertEqual(sql.count('%s'),len(params))
        cursor.execute.side_effect=validate
        now=datetime(2026,9,15,tzinfo=timezone.utc)
        with patch.object(db,'BACKEND','postgres'),patch.object(db,'get_connection',return_value=conn):
            usage.monthly(admin=True,now=now) if admin else usage.monthly(self.bid,now=now)
        cursor.execute.assert_called_once()
        sql,params=cursor.execute.call_args.args
        self.assertEqual(params[:2],['claude-haiku-%','claude-sonnet-%'])
        self.assertEqual(params[2:4],list(usage.month_bounds(now)))
        self.assertEqual(len(params),4 if admin else 5)
        if not admin:
            self.assertIn('AND tenant_id = %s',sql);self.assertEqual(params[4],self.bid)
        conn.rollback.assert_not_called()

    def test_postgres_admin_both_patterns_bound_through_real_adapter(self):
        self.postgres_query(True)

    def test_postgres_tenant_parameter_order_and_scope(self):
        self.postgres_query(False)

    def test_sqlite_results_match_original_like_semantics(self):
        response={'content':[{'type':'text','text':'fixture'}], 'usage':{'input_tokens':10,'output_tokens':5}}
        for model in ('claude-haiku-4-5-20251001','claude-haiku-future','claude-sonnet-4-6','unrecognized-model'):
            self.assertTrue(usage.record(model,response,tenant_id=self.bid,context='tenant_customer'))
        self.assertTrue(usage.record('claude-sonnet-4-6',response,tenant_id=self.other,context='tenant_customer'))
        before=db.query_one('SELECT COUNT(*) n FROM ai_usage_ledger')['n']
        start,end=usage.month_bounds()
        expected=db.query_one("SELECT SUM(CASE WHEN model LIKE 'claude-haiku-%' THEN 1 ELSE 0 END) h, "
            "SUM(CASE WHEN model LIKE 'claude-sonnet-%' THEN 1 ELSE 0 END) s FROM ai_usage_ledger "
            "WHERE created_at >= ? AND created_at < ? AND tenant_id = ?",(start,end,self.bid))
        row=usage.monthly(self.bid)[0]
        self.assertEqual((row['haiku_calls'],row['sonnet_calls']),(expected['h'],expected['s']))
        self.assertEqual((row['calls'],row['haiku_calls'],row['sonnet_calls']),(4,2,1))
        other=usage.monthly(self.other)[0]
        self.assertEqual((other['calls'],other['sonnet_calls']),(1,1))
        self.assertEqual(len(usage.monthly(admin=True)),2)
        self.assertEqual(db.query_one('SELECT COUNT(*) n FROM ai_usage_ledger')['n'],before)

if __name__=='__main__':unittest.main()
