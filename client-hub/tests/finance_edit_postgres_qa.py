"""Native accounting edit checks; refuses every production/non-loopback database."""
import os,sys,uuid,threading,unittest
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
url=urlsplit(os.environ.get('DATABASE_URL',''))
if url.hostname not in ('127.0.0.1','localhost') or url.path!='/kilas_finance_qa' or os.environ.get('FINANCE_LOCAL_PG_QA')!='1':
    raise SystemExit('Dedicated loopback synthetic Finance PostgreSQL database required')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db,repo,finance_service as f,finance_branches as branches


class NativeEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):assert db.BACKEND=='postgres';db.init_schema()
    def setUp(self):
        self.uid=repo.create_user('synthetic-edit-'+uuid.uuid4().hex+'@example.test','unused')
        self.bid=repo.create_business(self.uid,'Synthetic native edits');f.ensure_finance_defaults(self.bid,actor_user_id=self.uid)
        self.branch=branches.list_branches(self.bid,self.uid)[0]['id']
        self.a=f.list_accounts(self.bid,actor_user_id=self.uid)[0]['id']
        self.target=f.create_account(self.bid,'Synthetic reserve','BANK',opening_balance_minor=10000,actor_user_id=self.uid)
        self.exp=f.list_categories(self.bid,'EXPENSE',actor_user_id=self.uid)[0]['id'];self.inc=f.list_categories(self.bid,'INCOME',actor_user_id=self.uid)[0]['id']
    def bill(self):
        rule=f.create_recurring_expense(self.bid,'Synthetic bill',100,self.a,self.exp,'MONTHLY','2026-09-10',actor_user_id=self.uid)
        payment=f.record_recurring_payment(self.bid,rule,'2026-09-10','2026-09-10',self.uid)
        return rule,payment['ledger_transaction_id']
    def snapshot(self):
        return {table:db.query_all('SELECT * FROM '+table+' WHERE business_id=? ORDER BY id',(self.bid,)) for table in
            ('finance_transactions','finance_transaction_revisions','finance_recurring_postings','finance_recurring_expenses','finance_invoice_payments','finance_invoices')}
    def test_bill_native_balances_and_posting_identity(self):
        rule,tx=self.bill();posting=f.list_recurring_postings(self.bid,rule,self.uid);future=f.get_recurring_expense(self.bid,rule,self.uid)
        f.update_bill_payment(self.bid,tx,amount_minor=350,account_id=self.target,occurred_on='2026-10-01',actor_user_id=self.uid)
        balances={r['id']:r['balance_minor'] for r in f.get_account_balance_report(self.bid,'2026-10-31',self.uid)}
        self.assertEqual((balances[self.a],balances[self.target]),(0,9650))
        self.assertEqual(posting,f.list_recurring_postings(self.bid,rule,self.uid));self.assertEqual(future,f.get_recurring_expense(self.bid,rule,self.uid))
        self.assertEqual(f.get_finance_summary(self.bid,'2026-09-01','2026-09-30',actor_user_id=self.uid)['total_expense_minor'],0)
    def test_invoice_native_payment_and_receivable_are_synchronized(self):
        customer=f.create_customer(self.bid,'Synthetic customer',actor_user_id=self.uid)
        invoice=f.create_finance_invoice(self.bid,customer,'2026-09-01','2026-09-15',[dict(description='Synthetic service',quantity=1,unit_price_minor=1000)],actor_user_id=self.uid)
        f.issue_finance_invoice(self.bid,invoice,self.uid)
        pay=f.record_invoice_payment(self.bid,invoice,400,'2026-09-10',self.a,self.inc,actor_user_id=self.uid,idempotency_key='synthetic_native_edit_payment')
        tx=db.query_one('SELECT ledger_transaction_id FROM finance_invoice_payments WHERE id=?',(pay,))['ledger_transaction_id']
        f.update_invoice_payment(self.bid,tx,amount_minor=1000,account_id=self.target,occurred_on='2026-10-01',actor_user_id=self.uid)
        self.assertEqual(f.get_invoice_totals(self.bid,invoice)['outstanding_minor'],0)
        self.assertEqual(f.get_finance_invoice(self.bid,invoice,self.uid)['status'],'PAID')
        before=self.snapshot()
        with self.assertRaises(f.FinanceError):f.update_invoice_payment(self.bid,tx,amount_minor=1001,actor_user_id=self.uid)
        self.assertEqual(before,self.snapshot())
    def test_late_failure_is_atomic_on_native_postgres(self):
        _,tx=self.bill();before=self.snapshot()
        with patch.object(f,'_audit',side_effect=RuntimeError('synthetic audit failure')),self.assertRaises(RuntimeError):
            f.update_bill_payment(self.bid,tx,amount_minor=350,actor_user_id=self.uid)
        self.assertEqual(before,self.snapshot())
    def test_native_concurrency_updates_one_existing_payment(self):
        rule,tx=self.bill();barrier=threading.Barrier(4)
        def run(_):
            try:barrier.wait();return f.update_bill_payment(self.bid,tx,amount_minor=350,actor_user_id=self.uid)['id']
            finally:
                if getattr(db._local,'conn',None):db._local.conn.close();db._local.conn=None
        with ThreadPoolExecutor(max_workers=4) as pool:self.assertEqual(list(pool.map(run,range(4))),[tx]*4)
        self.assertEqual(len(f.list_recurring_postings(self.bid,rule,self.uid)),1)
        self.assertEqual(db.query_one('SELECT count(*) AS n FROM finance_transaction_revisions WHERE transaction_id=?',(tx,))['n'],1)
    def test_native_cross_branch_and_currency_rejected(self):
        _,tx=self.bill();other=branches.create_branch(self.bid,'Synthetic second branch',self.uid)
        with branches.scope(self.bid,other,self.uid):account=f.list_accounts(self.bid,actor_user_id=self.uid)[0]['id']
        usd=f.create_account(self.bid,'Synthetic USD','BANK','USD',actor_user_id=self.uid);before=self.snapshot()
        for target in (account,usd):
            with self.assertRaises(f.FinanceError):f.update_bill_payment(self.bid,tx,account_id=target,actor_user_id=self.uid)
        self.assertEqual(before,self.snapshot())


if __name__=='__main__':unittest.main(verbosity=2)
