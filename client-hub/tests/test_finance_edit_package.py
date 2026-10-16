"""Scoped, atomic saved-entry edits on disposable local ledgers only."""
import re,threading,unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
import test_finance_approved_revisions as prior
import finance_service as f,finance_branches as branches
import db,repo


class FinanceEditPackageTests(unittest.TestCase):
    setUp=prior.ApprovedFinanceTests.setUp
    page=prior.ApprovedFinanceTests.page

    def expense_category(self):return f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid)[0]['id']
    def bill(self,branch=None,account=None):
        branch=branch or self.branch;account=account or self.a
        with branches.scope(self.b,branch,self.uid):
            category=self.expense_category()
            rule=f.create_recurring_expense(self.b,'Synthetic bill',100,account,category,'MONTHLY','2026-09-10',
                end_on='2026-09-10',description='Original bill note',actor_user_id=self.uid)
            paid=f.record_recurring_payment(self.b,rule,'2026-09-10','2026-09-10',self.uid)
        return rule,paid['ledger_transaction_id'],category

    def invoice_payment(self):
        invoice=f.create_finance_invoice(self.b,self.c,'2026-09-01','2026-09-15',
            [dict(description='Synthetic service',quantity=1,unit_price_minor=1000)],actor_user_id=self.uid)
        f.issue_finance_invoice(self.b,invoice,self.uid)
        payment=f.record_invoice_payment(self.b,invoice,400,'2026-09-10',self.a,self.cat,actor_user_id=self.uid,idempotency_key='synthetic_edit_payment_1')
        row=db.query_one('SELECT * FROM finance_invoice_payments WHERE id=?',(payment,))
        return invoice,row['ledger_transaction_id'],payment

    def balances(self,when='2026-12-31'):
        return {r['id']:r['balance_minor'] for r in f.get_account_balance_report(self.b,when,self.uid)}
    def snapshot(self):
        return {name:db.query_all('SELECT * FROM '+name) for name in ('finance_transactions','finance_transaction_revisions',
            'finance_recurring_postings','finance_recurring_expenses','finance_invoice_payments','finance_invoices','audit_log')}

    def test_navigation_order_active_direction_and_search_absence_both_modes(self):
        for branch in (self.branch,self.personal):
            html,_=self.page(branch)
            nav=re.search(r'<nav class="finance-primary-navigation">.*?</nav>',html,re.S).group()
            links=re.findall(r'<a.*?</a>',nav,re.S)
            self.assertIn('Dasbor',links[0])
            self.assertIn('direction=INCOME',links[1]);self.assertIn('direction=EXPENSE',links[2])
            self.assertIn('view=transactions',links[3]);self.assertNotIn('direction=',links[3])
            self.assertIn('view=accounts',links[4]);self.assertIn('/reports?',links[-1])
            self.assertGreater(nav.index('class="finance-reset-launch"'),nav.index('/reports?'))
            for direction in ('INCOME','EXPENSE',None):
                html,_=self.page(branch,view='transactions',**({'direction':direction} if direction else {}))
                self.assertNotRegex(html,r'<input[^>]*type="search"')
                active=re.findall(r'<a[^>]*aria-current="page"[^>]*>',re.search(r'<nav class="finance-primary-navigation">.*?</nav>',html,re.S).group())
                self.assertEqual(len(active),1)
                if direction:self.assertIn('direction='+direction,active[0])
                self.assertNotIn('class="finance-reset-launch"',html)

    def test_business_switch_removed_legacy_route_and_records_retained(self):
        other=repo.create_business(self.uid,'Synthetic other existing business');f.ensure_finance_defaults(other,actor_user_id=self.uid)
        before=db.query_all('SELECT * FROM businesses')
        html,_=self.page();self.assertNotIn('finance-legacy-switch',html);self.assertNotIn('name="business_id"',html)
        self.assertEqual(self.client.get('/finance').status_code,200)
        self.assertIn(str(other),self.client.get('/finance').text)
        self.assertEqual(before,db.query_all('SELECT * FROM businesses'))

    def test_manual_income_expense_edits_reverse_old_account_and_period(self):
        for direction,category in (('INCOME',self.cat),('EXPENSE',self.expense_category())):
            tx=f.create_transaction(self.b,direction,100,self.a,category,'2026-09-10',actor_user_id=self.uid)
            before=self.balances();sign=1 if direction=='INCOME' else -1
            f.update_transaction(self.b,tx,amount_minor=350,account_id=self.dest,occurred_on='2026-10-01',description='Edited',actor_user_id=self.uid)
            after=self.balances()
            self.assertEqual(after[self.a],before[self.a]-sign*100)
            self.assertEqual(after[self.dest],before[self.dest]+sign*350)
            self.assertEqual(f.get_transaction(self.b,tx)['description'],'Edited')
            self.assertEqual(len([r for r in f.list_transactions(self.b) if r['id']==tx]),1)

    def test_paid_bill_edit_changes_cashflow_once_and_keeps_schedule_and_link(self):
        rule,tx,category=self.bill();future=f.get_recurring_expense(self.b,rule,self.uid);posting=f.list_recurring_postings(self.b,rule,self.uid)
        before=self.balances();newcat=f.create_category(self.b,'EXPENSE','Synthetic edited expense',actor_user_id=self.uid)
        f.update_bill_payment(self.b,tx,amount_minor=350,account_id=self.dest,category_id=newcat,occurred_on='2026-10-01',description='Edited paid bill',actor_user_id=self.uid)
        after=self.balances();self.assertEqual(after[self.a],before[self.a]+100);self.assertEqual(after[self.dest],before[self.dest]-350)
        self.assertEqual(future,f.get_recurring_expense(self.b,rule,self.uid));self.assertEqual(posting,f.list_recurring_postings(self.b,rule,self.uid))
        self.assertEqual(f.get_finance_summary(self.b,'2026-09-01','2026-09-30',actor_user_id=self.uid)['total_expense_minor'],0)
        self.assertEqual(f.get_finance_summary(self.b,'2026-10-01','2026-10-31',actor_user_id=self.uid)['total_expense_minor'],350)
        self.assertEqual(db.query_one('SELECT count(*) AS n FROM finance_transaction_revisions')['n'],1)
        f.update_bill_payment(self.b,tx,amount_minor=350,account_id=self.dest,category_id=newcat,occurred_on='2026-10-01',description='Edited paid bill',actor_user_id=self.uid)
        self.assertEqual(db.query_one('SELECT count(*) AS n FROM finance_transaction_revisions')['n'],1)

    def test_bill_edit_links_on_paid_calendar_and_list_in_both_modes(self):
        for branch,account in ((self.branch,self.a),(self.personal,self.pa)):
            rule,tx,category=self.bill(branch,account)
            for view in ('list','calendar'):
                response=self.client.get(self.url+'/operations',query_string=dict(branch_id=branch,month='2026-09',view=view,day='2026-09-10',payment_status='paid'))
                self.assertEqual(response.status_code,200);self.assertIn('/transactions/'+str(tx)+'/edit?',response.text)
            self.assertEqual(self.client.get(self.url+f'/transactions/{tx}/edit?branch_id={branch}').status_code,200)

    def test_paid_bill_invalid_and_cross_scope_updates_are_atomic(self):
        _,tx,category=self.bill();foreign=f.list_accounts(self.other)[0]['id']
        for values in (dict(amount_minor=0),dict(account_id=foreign),dict(account_id=self.pa),dict(category_id=self.cat),dict(occurred_on='2099-01-01'),dict(source_ref='new'),dict(currency='USD')):
            before=self.snapshot()
            with self.assertRaises(f.FinanceError):f.update_bill_payment(self.b,tx,actor_user_id=self.uid,**values)
            self.assertEqual(before,self.snapshot())
        with branches.scope(self.b,self.personal,self.uid),self.assertRaises(f.FinanceError):f.update_bill_payment(self.b,tx,amount_minor=200,actor_user_id=self.uid)
        with self.assertRaises(f.FinanceError):f.update_bill_payment(self.b,tx,amount_minor=200,actor_user_id=self.other_uid)

    def test_late_audit_failure_rolls_back_bill_and_revision(self):
        _,tx,_=self.bill();before=self.snapshot()
        with patch.object(f,'_audit',side_effect=RuntimeError('synthetic failure')),self.assertRaises(RuntimeError):
            f.update_bill_payment(self.b,tx,amount_minor=250,actor_user_id=self.uid)
        self.assertEqual(before,self.snapshot())

    def test_stale_edit_cannot_overwrite_later_changes(self):
        _,tx,_=self.bill();stamp=f.get_transaction(self.b,tx)['updated_at']
        f.update_bill_payment(self.b,tx,amount_minor=250,expected_updated_at=stamp,actor_user_id=self.uid)
        before=self.snapshot()
        with self.assertRaisesRegex(f.FinanceError,'transaction_changed'):
            f.update_bill_payment(self.b,tx,amount_minor=300,expected_updated_at=stamp,actor_user_id=self.uid)
        self.assertEqual(before,self.snapshot())

    def test_concurrent_bill_edits_never_duplicate_posting_or_expense(self):
        _,tx,_=self.bill();barrier=threading.Barrier(2)
        def worker(_):
            try:barrier.wait();return f.update_bill_payment(self.b,tx,amount_minor=250,actor_user_id=self.uid)['id']
            finally:
                if getattr(db._local,'conn',None):db._local.conn.close();db._local.conn=None
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(list(pool.map(worker,range(2))),[tx,tx])
        self.assertEqual(db.query_one('SELECT count(*) AS n FROM finance_recurring_postings')['n'],1)
        self.assertEqual(f.get_finance_summary(self.b,'2026-09-01','2026-09-30',actor_user_id=self.uid)['total_expense_minor'],250)

    def test_invoice_payment_edit_updates_receivable_and_income_atomically(self):
        invoice,tx,payment=self.invoice_payment();before=self.balances()
        f.update_invoice_payment(self.b,tx,amount_minor=1000,account_id=self.dest,occurred_on='2026-10-01',description='Edited invoice payment',actor_user_id=self.uid)
        row=db.query_one('SELECT * FROM finance_invoice_payments WHERE id=?',(payment,))
        self.assertEqual((row['amount_minor'],row['account_id'],row['paid_on']),(1000,self.dest,'2026-10-01'))
        self.assertEqual(f.get_invoice_totals(self.b,invoice)['outstanding_minor'],0)
        self.assertEqual(f.get_finance_invoice(self.b,invoice,self.uid)['status'],'PAID')
        self.assertEqual(self.balances()[self.a],before[self.a]-400);self.assertEqual(self.balances()[self.dest],before[self.dest]+1000)
        f.update_invoice_payment(self.b,tx,amount_minor=200,actor_user_id=self.uid)
        self.assertEqual(f.get_invoice_totals(self.b,invoice)['outstanding_minor'],800)
        self.assertEqual(f.get_finance_invoice(self.b,invoice,self.uid)['status'],'PARTIALLY_PAID')
        self.assertEqual(db.query_one('SELECT count(*) AS n FROM finance_invoice_payments')['n'],1)

    def test_invoice_overpayment_and_late_failure_leave_both_sides_unchanged(self):
        invoice,tx,payment=self.invoice_payment();before=self.snapshot()
        with self.assertRaisesRegex(f.FinanceError,'overpayment'):f.update_invoice_payment(self.b,tx,amount_minor=1001,actor_user_id=self.uid)
        self.assertEqual(before,self.snapshot())
        original=f._audit
        def fail(bid,actor,event,record):
            if event=='FINANCE_INVOICE_PAYMENT_UPDATED':raise RuntimeError('synthetic late failure')
            return original(bid,actor,event,record)
        with patch.object(f,'_audit',side_effect=fail),self.assertRaises(RuntimeError):f.update_invoice_payment(self.b,tx,amount_minor=500,actor_user_id=self.uid)
        self.assertEqual(before,self.snapshot())

    def test_http_edit_saves_all_fields_and_requires_csrf(self):
        _,tx,category=self.bill();path=self.url+f'/transactions/{tx}/edit?branch_id={self.branch}'
        html=self.client.get(path).text;self.assertIn('expected_updated_at',html)
        data=dict(amount='2.50',occurred_on='2026-09-11',account_id=self.dest,category_id=category,description='HTTP edited bill')
        before=self.snapshot();prior.app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=True
        self.assertEqual(self.client.post(path,data=data).status_code,400);self.assertEqual(before,self.snapshot())
        prior.app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=False
        self.assertEqual(self.client.post(path,data=data).status_code,303)
        row=f.get_transaction(self.b,tx)
        self.assertEqual((row['amount_minor'],row['occurred_on'],row['account_id'],row['description']),(250,'2026-09-11',self.dest,'HTTP edited bill'))

    def test_personal_income_keeps_archived_legacy_category_when_editing(self):
        with branches.scope(self.b,self.personal,self.uid):
            category=f.list_categories(self.b,'INCOME',actor_user_id=self.uid)[0]['id']
            tx=f.create_transaction(self.b,'INCOME',100,self.pa,category,'2026-09-10',description='Original',actor_user_id=self.uid)
            f.update_category_workspace_setting(self.b,category,deactivate=True,actor_user_id=self.uid)
            f.update_transaction(self.b,tx,description='Edited legacy income',actor_user_id=self.uid)
            self.assertEqual(f.get_transaction(self.b,tx)['category_id'],category)

    def test_edit_actor_must_match_explicit_workspace_context(self):
        _,tx,_=self.bill()
        db.execute("INSERT INTO business_memberships(business_id,user_id,role_in_business) VALUES (?,?,'OWNER')",(self.b,self.other_uid))
        before=self.snapshot()
        with branches.scope(self.b,self.branch,self.uid),self.assertRaises(f.FinanceError):
            f.update_bill_payment(self.b,tx,amount_minor=200,actor_user_id=self.other_uid)
        self.assertEqual(before,self.snapshot())
