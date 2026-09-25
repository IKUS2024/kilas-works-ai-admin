"""Synthetic, disposable PostgreSQL certification; never accepts a production target."""
import os
from urllib.parse import urlsplit
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pathlib import Path
import sys
if os.environ.get('KILAS_PHASE7_POSTGRES_QA') != '1':
    raise SystemExit('Explicit Phase 7 synthetic QA flag required')
target=urlsplit(os.environ.get('DATABASE_URL',''))
if target.hostname not in ('localhost','127.0.0.1') or target.path != '/kilas_phase7':
    raise SystemExit('Dedicated loopback kilas_phase7 database required')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db, repo, finance_service as f, finance_branches as branches

class WorkspacePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert db.BACKEND=='postgres'
        db.init_schema()

    def setUp(self):
        from uuid import uuid4
        self.uid=repo.create_user(uuid4().hex+'@example.test','unused')
        self.bid=repo.create_business(self.uid,'Synthetic corrections')
        f.ensure_finance_defaults(self.bid,actor_user_id=self.uid)
        self.source=branches.list_branches(self.bid,self.uid)[0]['id']
        self.target=branches.ensure_personal(self.bid,self.uid)
        with branches.scope(self.bid,self.source,self.uid):
            self.a=f.create_account(self.bid,'PG account','BANK',opening_balance_minor=500,actor_user_id=self.uid)
            self.cat=f.list_categories(self.bid,'INCOME',actor_user_id=self.uid)[0]['id']
            self.tx=f.create_transaction(self.bid,'INCOME',123,self.a,self.cat,'2026-09-10',actor_user_id=self.uid)

    def move(self,source=None,target=None):
        with branches.scope(self.bid,source or self.source,self.uid):
            return f.move_transaction_workspace(self.bid,self.tx,target or self.target,actor_user_id=self.uid)

    def snapshot(self):
        tables=('finance_accounts','finance_transactions','finance_transaction_revisions',
                'finance_workspace_corrections','finance_workspace_opening_history',
                'finance_recurring_expenses','audit_log','finance_branches','finance_branch_workspaces')
        return {t:[dict(r) for r in db.query_all('SELECT * FROM '+t+' WHERE business_id=?',(self.bid,))] for t in tables}

    def test_move_reverse_and_migration_repeat(self):
        self.move(); self.move(self.target,self.source)
        row=f.get_transaction(self.bid,self.tx,actor_user_id=self.uid)
        self.assertEqual((row['branch_id'],row['account_id'],row['amount_minor'],row['relocation_version']), (self.source,self.a,123,2))
        db.init_schema();db.init_schema()
        self.assertEqual(f.get_transaction(self.bid,self.tx,actor_user_id=self.uid),row)
        with self.assertRaises(Exception):db.execute('UPDATE finance_transactions SET branch_id=? WHERE id=?',(self.target,self.tx))
        with self.assertRaises(Exception):db.execute('DELETE FROM finance_workspace_corrections WHERE business_id=?',(self.bid,))

    def test_account_opening_and_rule_atomic(self):
        with branches.scope(self.bid,self.source,self.uid):
            category=f.list_categories(self.bid,'EXPENSE',actor_user_id=self.uid)[0]['id']
            rule=f.create_recurring_expense(self.bid,'PG bill',12,self.a,category,'MONTHLY','2026-10-01',actor_user_id=self.uid)
            result=f.move_account_workspace(self.bid,self.a,self.target,actor_user_id=self.uid)
        self.assertEqual(f.get_recurring_expense(self.bid,rule,self.uid)['branch_id'],self.target)
        self.assertEqual(f.get_account(self.bid,result['target_account_id'],actor_user_id=self.uid)['opening_balance_minor'],500)
        self.assertEqual(f.get_account(self.bid,self.a,actor_user_id=self.uid)['opening_balance_minor'],0)
        self.assertEqual(sum(r['balance_minor'] for r in f.get_account_balance_report(self.bid,'2026-09-30',self.uid)),623)

    def test_audit_failure_rolls_back(self):
        original=f._audit
        def fail(bid,actor,action,*args):
            if action=='FINANCE_ACCOUNT_WORKSPACE_MOVED':raise RuntimeError('failure')
            return original(bid,actor,action,*args)
        before=self.snapshot()
        with branches.scope(self.bid,self.source,self.uid),patch.object(f,'_audit',side_effect=fail),self.assertRaises(RuntimeError):
            f.move_account_workspace(self.bid,self.a,self.target,actor_user_id=self.uid)
        self.assertEqual(self.snapshot(),before)

    def test_concurrent_move_once(self):
        barrier=threading.Barrier(2)
        def worker(_):
            try:
                barrier.wait()
                try:self.move();return True
                except f.FinanceError:return False
            finally:
                if getattr(db._local,'conn',None):db._local.conn.close();db._local.conn=None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(worker,range(2)))
        self.assertEqual(sorted(results),[False,True])
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_workspace_corrections WHERE business_id=?',(self.bid,))['n'],1)

if __name__=='__main__':unittest.main(verbosity=2)
