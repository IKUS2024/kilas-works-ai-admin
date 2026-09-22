"""Finance UI integration against disposable real ledger records (no production data)."""
from datetime import date
import re
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from flask import template_rendered
import test_finance_phase2a as fixture
import finance_branches as branches
import finance_fx
import finance_reports
import db

f = fixture.f


class UnifiedFinanceTests(unittest.TestCase):
    def setUp(self):
        fixture.ReceivablesTests.setUp(self)
        self.clock = patch.object(f, 'business_today', return_value=date(2026, 9, 22))
        self.clock.start(); self.addCleanup(self.clock.stop)
        self.rates = patch.object(finance_fx, 'snapshot', return_value={
            'rates': {'IDR':'1', 'USD':'16000'}, 'date':'2026-09-22', 'source':'test', 'stale':False})
        self.rates.start(); self.addCleanup(self.rates.stop)
        self.branch = branches.default(self.b, self.uid)
        self.expense = f.list_categories(self.b, 'EXPENSE')[0]['id']

    def page(self, suffix='', **params):
        contexts=[]
        def capture(sender, template, context, **extra): contexts.append(context)
        params={'month':'2026-09', 'branch_id':self.branch, **params}
        with template_rendered.connected_to(capture, fixture.app):
            response=self.client.get(self.url+suffix, query_string=params)
        self.assertEqual(response.status_code, 200, response.text[:200])
        return response.text, contexts[-1]

    def create(self, direction, amount, **kw):
        return f.create_transaction(self.b,direction,amount,self.a,
            self.cat if direction=='INCOME' else self.expense,
            kw.pop('occurred_on','2026-09-10'),actor_user_id=self.uid,**kw)

    def totals(self, income, expense, balance):
        _, dashboard=self.page()
        self.assertEqual(dashboard['period_income_display'],finance_fx.format_money(income,'IDR'))
        self.assertEqual(dashboard['period_expense_display'],finance_fx.format_money(expense,'IDR'))
        self.assertEqual(dashboard['balance_total_display'],finance_fx.format_money(balance,'IDR'))
        self.assertEqual(dashboard['dashboard_trend'][-1]['income_minor'],income)
        self.assertEqual(dashboard['dashboard_trend'][-1]['expense_minor'],expense)
        _,reports=self.page('/reports')
        summary=next(row for row in reports['summary'] if row['currency']=='IDR')
        self.assertEqual((summary['total_income_minor'],summary['total_expense_minor']),(income,expense))
        _,account=self.page(view='accounts',account_id=self.a)
        self.assertTrue(account['account_detail_mode'])
        self.assertEqual(account['selected_account']['balance_minor'],balance)
        for direction,expected in [('INCOME',income),('EXPENSE',expense)]:
            _,tx=self.page(view='transactions',direction=direction)
            self.assertEqual(sum(t['amount_minor'] for t in tx['transactions']),expected)

    def test_income_expense_opening_budget_reconcile_on_all_pages(self):
        f.update_account_opening_balance(self.b,self.a,100000,actor_user_id=self.uid)
        self.create('INCOME',75000)
        self.create('EXPENSE',30000)
        f.set_monthly_budget(self.b,'2026-09',self.expense,100000,actor_user_id=self.uid)
        self.totals(75000,30000,145000)
        _,budget=self.page('/budget')
        category=next(row for row in budget['rows'] if row['category']['id']==self.expense)
        self.assertEqual((category['spent_value_minor'],category['remaining_value_minor']),(30000,70000))
        self.assertEqual(category['percent_used'],30)
        _,dashboard=self.page()
        self.assertEqual(dashboard['budget_remaining_display'],budget['remaining_display'])
        self.assertEqual(dashboard['budget_percent'],30)

    def test_edit_void_updates_existing_ledger_once(self):
        response=self.client.post(self.url+'/transactions?month=2026-09',data={
            'branch_id':self.branch,'direction':'INCOME','amount':'500','account_id':self.a,
            'category_id':self.cat,'occurred_on':'2026-09-10','description':'Created in form'})
        self.assertEqual(response.status_code,303)
        tx=f.list_transactions(self.b)[0]
        self.assertEqual(tx['amount_minor'],50000)
        response=self.client.post(self.url+f'/transactions/{tx["id"]}/edit?month=2026-09',data={
            'branch_id':self.branch,'amount':'650','account_id':self.a,'category_id':self.cat,
            'occurred_on':'2026-09-10','description':'Edited in form'})
        self.assertEqual(response.status_code,303)
        self.totals(65000,0,65000)
        response=self.client.post(self.url+f'/transactions/{tx["id"]}/void?month=2026-09',data={'branch_id':self.branch})
        self.assertEqual(response.status_code,303)
        self.totals(0,0,0)
        self.assertEqual(f.get_transaction(self.b,tx['id'])['status'],'VOID')
        self.assertEqual(len(f.list_transactions(self.b)),1)

    def test_currency_exchange_and_usd_opening_are_not_operating_income(self):
        f.update_account_opening_balance(self.b,self.a,160000000,actor_user_id=self.uid)
        usd=f.create_account(self.b,'USD account','BANK','USD',10000,actor_user_id=self.uid)
        f.record_currency_exchange(self.b,self.a,usd,16000000,1000,'2026-09-10',actor_user_id=self.uid)
        balances={row['id']:row for row in f.get_account_balance_report(self.b,'2026-09-22')}
        self.assertEqual(balances[self.a]['balance_minor'],144000000)
        self.assertEqual(balances[usd]['balance_minor'],11000)
        self.assertEqual(f.list_transactions(self.b),[])
        _,dashboard=self.page(display_currency='USD')
        self.assertEqual(dashboard['period_income_display'],'US$0.00')
        self.assertEqual(dashboard['period_expense_display'],'US$0.00')
        self.assertEqual(dashboard['balance_total_display'],'US$200.00')
        _,reports=self.page('/reports')
        self.assertEqual(sum(row['total_income_minor'] for row in reports['summary']),0)
        _,account=self.page(view='accounts',account_id=usd,display_currency='USD')
        self.assertEqual(account['selected_account']['balance_minor'],11000)

    def test_invoice_partial_full_payment_reconciles_without_issuance_income(self):
        invoice=f.create_finance_invoice(self.b,self.c,'2026-09-01','2026-09-30',
            [dict(description='Actual test service',quantity=1,unit_price_minor=100000)],actor_user_id=self.uid)
        f.issue_finance_invoice(self.b,invoice,actor_user_id=self.uid)
        self.totals(0,0,0)
        for amount,key,expected,status in [(40000,'unify-partial-payment',40000,'PARTIALLY_PAID'),(60000,'unify-final-payment',100000,'PAID')]:
            args=dict(actor_user_id=self.uid,idempotency_key=key)
            first=f.record_invoice_payment(self.b,invoice,amount,'2026-09-10',self.a,self.cat,**args)
            self.assertEqual(first,f.record_invoice_payment(self.b,invoice,amount,'2026-09-10',self.a,self.cat,**args))
            self.assertEqual(f.get_finance_invoice(self.b,invoice)['status'],status)
            self.assertEqual(f.get_invoice_totals(self.b,invoice)['outstanding_minor'],100000-expected)
            self.totals(expected,0,expected)
            self.page('/invoices/'+str(invoice))
        self.assertEqual(len(f.list_transactions(self.b)),2)

    def test_paid_bill_history_uses_transaction_after_rule_is_edited(self):
        rule=f.create_recurring_expense(self.b,'Recurring test',17000,self.a,self.expense,'MONTHLY','2026-09-10',actor_user_id=self.uid)
        f.record_recurring_payment(self.b,rule,'2026-09-10','2026-09-10',actor_user_id=self.uid)
        f.record_recurring_payment(self.b,rule,'2026-09-10','2026-09-10',actor_user_id=self.uid)
        f.update_recurring_expense(self.b,rule,'Recurring test',25000,self.a,self.expense,'MONTHLY','2026-10-10',actor_user_id=self.uid)
        self.totals(0,17000,-17000)
        _,dashboard=self.page()
        self.assertEqual(dashboard['dashboard_view']['payments_display'],'Rp170,00')
        html,_=self.page('/operations',payment_status='paid')
        self.assertIn('Rp170,00',html)
        self.assertEqual(len(f.list_transactions(self.b)),1)

    def test_search_pagination_literal_matching_and_branch_isolation(self):
        for index in range(12):self.create('EXPENSE',100,description=f'Unique rent {index}')
        self.create('INCOME',100,description='100% exact_literal')
        _,one=self.page(view='transactions',direction='EXPENSE',search='rent')
        _,two=self.page(view='transactions',direction='EXPENSE',search='rent',page=2)
        self.assertEqual(one['transaction_total'],12)
        self.assertEqual(len(one['transactions']),10);self.assertEqual(len(two['transactions']),2)
        self.assertEqual(one['transaction_query']['search'],'rent')
        self.assertEqual(f.count_transactions(self.b,search='% exact_'),1)
        self.assertEqual(f.count_transactions(self.b,search="' OR 1=1 --"),0)
        other=branches.create_branch(self.b,'Other branch',self.uid)
        self.assertEqual(self.page(view='transactions',branch_id=other,search='rent')[1]['transaction_total'],0)

    def test_all_finance_pages_share_shell_and_context_without_affecting_client_hub(self):
        f.create_account(self.b,'USD account','BANK','USD',0,actor_user_id=self.uid)
        tx=self.create('INCOME',100)
        invoice=f.create_finance_invoice(self.b,self.c,'2026-09-01','2026-09-30',
            [dict(description='Service',quantity=1,unit_price_minor=100)],actor_user_id=self.uid)
        pages=[('',{}),('',{'view':'accounts'}),('',{'view':'accounts','account_id':self.a}),('',{'view':'transactions'}),
               ('',{'view':'transactions','direction':'INCOME'}),('',{'view':'transactions','direction':'EXPENSE'}),
               ('/operations',{}),('/budget',{}),('/payees',{}),('/receivables',{}),('/reports',{}),
               ('/invoices/new',{}),('/invoices/'+str(invoice),{}),('/invoices/'+str(invoice)+'/edit',{}),
               ('/transactions/'+str(tx)+'/edit',{}),('/assistant',{}),('/receipts/new',{})]
        for suffix,args in pages:
            with self.subTest(page=suffix,args=args):
                html,_=self.page(suffix,month='2026-08',display_currency='USD',**args)
                self.assertEqual(html.count('class="finance-app-sidebar"'),1)
                self.assertIn('finance_ui.css',html)
                self.assertIn('data-finance-month="2026-08"',html)
                self.assertIn('data-finance-currency="USD"',html)
                self.assertIn('month=2026-08',html)
                self.assertNotIn('Putri Maudy',html)
        self.assertNotIn('finance_ui.css',self.client.get('/login').text)

    def test_report_month_and_explicit_ranges(self):
        self.create('INCOME',20000,occurred_on='2026-08-10')
        _,reports=self.page('/reports',month='2026-08')
        self.assertEqual((reports['filters']['start'],reports['filters']['end']),('2026-08-01','2026-08-31'))
        self.assertEqual(reports['summary'][0]['total_income_minor'],20000)
        filters=finance_reports.parse_filters({'month':'2026-08','start':'2026-07-01','end':'2026-07-31'},today=date(2026,9,22))
        self.assertEqual(filters['start'],'2026-07-01')
        response=self.client.get(self.url+'?month=2099-01',follow_redirects=True)
        self.assertEqual(response.status_code,200)
        self.assertIn('September 2026',response.text)

    def test_action_links_preserve_month_and_display_currency(self):
        f.create_account(self.b,'USD account','BANK','USD',0,actor_user_id=self.uid)
        tx=self.create('INCOME',100)
        html,_=self.page(view='transactions',month='2026-08',display_currency='USD')
        response=self.client.post(self.url+f'/transactions/{tx}/void?month=2026-08&display_currency=USD',data={'branch_id':self.branch})
        params=parse_qs(urlsplit(response.location).query)
        self.assertEqual(params['month'],['2026-08'])
        self.assertEqual(params['display_currency'],['USD'])

    def test_migration_replay_keeps_existing_invoice_and_ledger(self):
        tx=self.create('INCOME',12500)
        before=f.get_transaction(self.b,tx)
        db.init_schema();db.init_schema()
        self.assertEqual(f.get_transaction(self.b,tx),before)
