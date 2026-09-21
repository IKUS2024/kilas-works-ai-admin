"""Branch/outlet contract tests. Disposable SQLite and mocked providers only."""
import csv
import io
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from flask import template_rendered
import test_finance_phase6a as prior
import db
import repo
import finance_service as f
import finance_branches as branches
import finance_operator as operator
import finance_receipts as receipts
import finance_bank_service as bank
import finance_bank_extract as extraction
import finance_reports as reports
import finance_collections as collections
import finance_fx as fx

app = prior.app


class BranchTests(unittest.TestCase):
    def setUp(self):
        prior.ReceiptTests.setUp(self)
        self.ba = branches.list_branches(self.b)[0]['id']
        self.bb = branches.create_branch(self.b, 'Serpong', self.uid)
        self.ab = next(a['id'] for a in f.list_accounts(self.b) if a['branch_id'] == self.bb)
        self.foreign = branches.list_branches(self.other)[0]['id']

    def scope(self, branch):
        return branches.scope(self.b, branch, self.uid)

    def tx(self, branch, amount=100, direction='INCOME', day='2026-09-17', **extra):
        with self.scope(branch):
            return f.create_transaction(self.b, direction, amount, self.a if branch == self.ba else self.ab,
                self.cat if direction == 'INCOME' else self.expense['id'], day, actor_user_id=self.uid, **extra)

    def invoice(self, branch):
        with self.scope(branch):
            i = f.create_finance_invoice(self.b, self.c, '2026-09-01', '2026-09-10',
                [dict(description='Coffee', quantity=1, unit_price_minor=1000)], actor_user_id=self.uid)
            f.issue_finance_invoice(self.b, i, self.uid)
            return i

    def page(self, branch, suffix='', **query):
        captures = []
        def capture(sender, template, context, **kwargs): captures.append(context)
        with template_rendered.connected_to(capture, app):
            response = self.client.get(self.url + suffix, query_string=dict(branch_id=branch or 'all', month='2026-09', **query))
        return response, captures[-1] if captures else {}

    def test_branch_does_not_create_business_and_gets_one_kas(self):
        self.assertEqual(len(db.query_all('SELECT id FROM businesses')), 2)
        self.assertEqual([r['name'] for r in branches.list_branches(self.b)], ['Utama', 'Serpong'])
        with self.scope(self.bb):
            accounts = f.list_accounts(self.b)
            self.assertEqual([(a['name'], a['currency'], a['account_type']) for a in accounts], [('Kas', 'IDR', 'CASH')])
            f.ensure_finance_defaults(self.b)
            self.assertEqual(len(f.list_accounts(self.b)), 1)
        with self.scope(self.ba):
            f.create_account(self.b, 'BCA', 'BANK')
        with self.scope(self.bb):
            f.create_account(self.b, 'BCA', 'BANK')
        self.assertEqual(len(db.query_all('SELECT id FROM businesses')), 2)

    def test_forged_branch_and_tenant_context_rejected(self):
        for branch in (self.foreign, 999999, '-1', '1 OR 1=1', '0'):
            response, _ = self.page(branch)
            self.assertEqual(response.status_code, 404)
        with self.assertRaises(f.FinanceError), branches.scope(self.b, self.foreign, self.uid): pass
        with self.assertRaises(f.FinanceError), branches.scope(self.b, self.ba, self.other_uid): pass
        with self.scope(self.ba), self.assertRaises(f.FinanceError): f.list_accounts(self.other)

    def test_account_cross_branch_and_record_reads_updates_rejected(self):
        tx = self.tx(self.ba)
        with self.scope(self.bb):
            self.assertIsNone(f.get_transaction(self.b, tx))
            for operation in (
                lambda: f.create_transaction(self.b, 'INCOME', 10, self.a, self.cat, '2026-09-17'),
                lambda: f.update_transaction(self.b, tx, amount_minor=1),
                lambda: f.void_transaction(self.b, tx),
                lambda: branches.update_record(self.b, 'account', self.a, name='Forged')):
                with self.assertRaises(f.FinanceError): operation()
        with self.assertRaises(f.FinanceError): f.update_transaction(self.b, tx, account_id=self.ab)
        self.assertEqual(f.get_transaction(self.b, tx)['amount_minor'], 100)

    def test_history_branch_isolation_and_legacy_all_resolves_default_branch(self):
        self.tx(self.ba, 111, description='UTAMA-ONLY')
        self.tx(self.bb, 222, description='SERPONG-ONLY')

        utama, utama_context = self.page(self.ba, period_mode='all', view='transactions', page=1)
        self.assertEqual(utama.status_code, 200)
        self.assertEqual(utama_context['transaction_total'], 1)
        self.assertIn('UTAMA-ONLY', utama.text)
        self.assertNotIn('SERPONG-ONLY', utama.text)
        self.assertIn('Utama', utama.text)

        serpong, serpong_context = self.page(self.bb, period_mode='all', view='transactions', page=1)
        self.assertEqual(serpong.status_code, 200)
        self.assertEqual(serpong_context['transaction_total'], 1)
        self.assertIn('SERPONG-ONLY', serpong.text)
        self.assertNotIn('UTAMA-ONLY', serpong.text)

        legacy, legacy_context = self.page(None, period_mode='all', view='transactions', page=1)
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(legacy_context['transaction_total'], 1)
        self.assertIn('UTAMA-ONLY', legacy.text)
        self.assertNotIn('SERPONG-ONLY', legacy.text)
        self.assertNotIn('Semua Cabang', legacy.text)

    def test_monthly_totals_and_current_balances_remain_branch_scoped(self):
        db.execute('UPDATE finance_accounts SET opening_balance_minor=50 WHERE id=?', (self.a,))
        self.tx(self.ba, 300); self.tx(self.ba, 70, 'EXPENSE'); self.tx(self.bb, 200)
        self.tx(self.ba, 40, day='2026-08-01')
        void = self.tx(self.bb, 900)
        with self.scope(self.bb): f.void_transaction(self.b, void)
        for branch, income, expense, balance in ((self.ba,300,70,320),(self.bb,200,0,200)):
            response, context = self.page(branch)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(context['summary']['total_income_minor'], income)
            self.assertEqual(context['summary']['total_expense_minor'], expense)
            self.assertEqual(context['balance_total'], balance)
        response, context = self.page(None)
        self.assertEqual(context['summary']['total_income_minor'], 300)
        self.assertEqual(context['summary']['total_expense_minor'], 70)
        self.assertIn('Utama', response.text)
        self.assertNotIn('Semua Cabang', response.text)
        self.assertIn('Saldo tersedia', response.text)

    def test_opening_foreign_balance_is_not_period_income_and_is_explained(self):
        with self.scope(self.ba):
            usd = f.create_account(self.b, 'BOFA', 'BANK', currency='USD',
                                   opening_balance_minor=10000, actor_user_id=self.uid)
            f.create_transaction(self.b, 'INCOME', 1000000, self.a, self.cat, '2026-09-17',
                                 currency='IDR', actor_user_id=self.uid)
        rates = {'rates': {'IDR':'1','USD':'17857.14'}, 'date':'2026-09-18',
                 'source':'Frankfurter', 'stale':False}
        with patch.object(fx, 'snapshot', return_value=rates):
            response, context = self.page(self.ba, period_mode='all')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['currency'] for row in context['summaries']], ['IDR'])
        usd_balance = next(row for row in context['balance_totals'] if row['currency']=='USD')
        self.assertEqual(usd_balance['opening_balance_minor'], 10000)
        self.assertEqual(usd_balance['balance_minor'], 10000)
        self.assertEqual(context['balance_total'], 1000000)
        self.assertNotIn('Arus kas USD', response.text)
        for text in ('Arus kas', 'US$100.00'):
            self.assertIn(text, response.text)

    def test_missing_fx_rate_never_returns_partial_combined_balance(self):
        with self.scope(self.ba):
            f.create_account(self.b, 'BOFA', 'BANK', currency='USD',
                             opening_balance_minor=10000, actor_user_id=self.uid)
            f.create_transaction(self.b, 'INCOME', 1000000, self.a, self.cat, '2026-09-17',
                                 currency='IDR', actor_user_id=self.uid)
        missing = {'rates': {'IDR':'1'}, 'date':'', 'source':'unavailable', 'stale':True}
        with patch.object(fx, 'snapshot', return_value=missing):
            response, context = self.page(self.ba, period_mode='all')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(context['estimated_balance_idr'])
        self.assertNotIn('≈', response.text)
        self.assertIn('<span>USD</span>', response.text)
        self.assertIn('US$100.00', response.text)

    def test_dashboard_range_and_all_period_modes(self):
        self.tx(self.ba, 100, day='2026-01-10')
        self.tx(self.ba, 200, day='2026-03-10')
        self.tx(self.ba, 300, day='2025-12-10')
        response, context = self.page(self.ba, period_mode='range', range_start='2026-01', range_end='2026-03')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(context['summary']['total_income_minor'], 300)
        self.assertEqual(context['period_start'], '2026-01-01')
        self.assertEqual(context['period_end'], '2026-03-31')
        self.assertEqual(context['period_label'], 'Januari 2026 – Maret 2026')
        self.assertIn('Rentang bulan', response.text)
        response, context = self.page(self.ba, period_mode='all')
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(context['summary']['total_income_minor'], 600)
        self.assertEqual(context['period_start'], '2025-12-10')
        self.assertEqual(context['period_label'], 'Semua transaksi')
        with self.scope(self.ba):
            self.assertEqual(f.get_transaction_date_bounds(self.b)['first_on'], '2025-12-10')

    def test_legacy_all_get_resolves_default_branch_but_all_writes_stay_rejected(self):
        with self.scope(None):
            for operation in (lambda: f.create_account(self.b, 'Forbidden'),
                              lambda: f.create_customer(self.b, 'Forbidden'),
                              lambda: branches.create_branch(self.b, 'Forbidden'),
                              lambda: receipts.analyze(self.b, self.uid, 'r.png', self.raw)):
                with self.assertRaises(f.FinanceError): operation()
        before = '\n'.join(db.get_connection().iterdump())
        for suffix in ('transactions','accounts','categories','branches','recurring/process','receipts/analyze','operator/draft','bank-imports/analyze','invoices/new'):
            response = self.client.post(self.url + '/' + suffix + '?branch_id=all', data={})
            self.assertEqual(response.status_code, 403, suffix)
        self.assertEqual(before, '\n'.join(db.get_connection().iterdump()))
        page, context = self.page(None)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(context['selected_branch_id'], self.ba)
        self.assertIn('id="add-transaction"', page.text)
        self.assertIn('Tanya Kilas Finance', page.text)
        self.assertNotIn('Semua Cabang', page.text)
        self.http.assert_not_called()

    def test_unscoped_multibranch_post_and_conflicting_selector_rejected(self):
        self.assertEqual(self.client.post(self.url+'/accounts', data=dict(name='Wrong',account_type='CASH')).status_code, 403)
        self.assertEqual(self.client.post(self.url+'/accounts?branch_id='+str(self.ba), data=dict(branch_id=self.bb)).status_code, 400)
        self.assertEqual(self.client.get(self.url+'?branch_id=all&branch_id='+str(self.ba)).status_code, 400)

    def test_transaction_edit_revision_cancel_and_lainnya(self):
        category = next(c for c in f.list_categories(self.b, 'EXPENSE') if c['name']=='Pengeluaran Lain')
        fields = dict(direction='EXPENSE',amount='75',occurred_on='2026-09-17',account_id=self.a,
                      category_id=category['id'],description='Selesai',other_description='Servis mesin kopi')
        response = self.client.post(self.url+'/transactions?branch_id='+str(self.ba), data=fields)
        self.assertEqual(response.status_code, 303)
        tx = f.list_transactions(self.b)[0]
        self.assertEqual(tx['description'], 'Servis mesin kopi\nSelesai')
        edit_page = self.client.get(self.url+f'/transactions/{tx["id"]}/edit?branch_id={self.ba}')
        self.assertEqual(edit_page.status_code,200)
        self.assertIn('value="Servis mesin kopi"',edit_page.text)
        self.assertEqual(len(f.list_categories(self.b)), 10)
        fields.update(amount='80',other_description='Servis ulang')
        response = self.client.post(self.url+f'/transactions/{tx["id"]}/edit?branch_id={self.ba}', data=fields)
        self.assertEqual(response.status_code,303)
        history = db.query_all('SELECT * FROM finance_transaction_revisions')
        self.assertEqual(len(history),1)
        self.assertEqual(json.loads(history[0]['before_json'])['amount_minor'],75)
        self.assertEqual(json.loads(history[0]['after_json'])['amount_minor'],80)
        self.client.post(self.url+f'/transactions/{tx["id"]}/void?branch_id={self.ba}')
        self.assertEqual(f.get_transaction(self.b,tx['id'])['status'],'VOID')
        self.assertNotIn('Servis ulang',self.page(self.ba)[0].text)

    def test_branch_account_category_rename_deactivate_preserves_history(self):
        tx=self.tx(self.ba)
        with self.scope(self.ba):
            f.create_account(self.b,'Kas cadangan',actor_user_id=self.uid)
            for kind, ident, name in (('account',self.a,'Tunai'),('category',self.cat,'Penjualan kopi'),('branch',self.ba,'Karawaci')):
                branches.update_record(self.b,kind,ident,name=name,actor_user_id=self.uid)
            branches.update_record(self.b,'category',self.cat,deactivate=True,actor_user_id=self.uid)
            branches.update_record(self.b,'account',self.a,deactivate=True,actor_user_id=self.uid)
            branches.update_record(self.b,'branch',self.ba,deactivate=True,actor_user_id=self.uid)
        response,_=self.page(self.ba)
        self.assertEqual(response.status_code,303)
        self.assertIn('branch_id=',response.headers['Location'])
        self.assertEqual(f.get_transaction(self.b,tx)['amount_minor'],100)
        self.assertEqual(self.client.post(self.url+f'/transactions/{tx}/void?branch_id={self.ba}').status_code,403)

    def test_customer_edit_delete_is_global_and_preserves_finance_history(self):
        with self.scope(self.ba):
            customer=f.create_customer(self.b,'Customer Lama',phone='0811',email='old@example.com',notes='lama',actor_user_id=self.uid)
            invoice=f.create_finance_invoice(self.b,customer,'2026-09-01','2026-09-30',
                [dict(description='Jasa',quantity=1,unit_price_minor=250000)],actor_user_id=self.uid)
            f.issue_finance_invoice(self.b,invoice,self.uid)
            f.update_customer(self.b,customer,'Customer Baru',phone='0822',email='new@example.com',notes='baru',actor_user_id=self.uid)
            updated=f.get_customer(self.b,customer,self.uid)
            self.assertEqual((updated['name'],updated['phone'],updated['email'],updated['notes']),
                             ('Customer Baru','0822','new@example.com','baru'))
            f.delete_customer(self.b,customer,actor_user_id=self.uid)
            self.assertNotIn(customer,[row['id'] for row in f.list_customers(self.b,actor_user_id=self.uid)])
            archived=next(row for row in f.list_customers(self.b,include_inactive=True,actor_user_id=self.uid) if row['id']==customer)
            self.assertFalse(archived['is_active'])
            self.assertEqual(f.get_finance_invoice(self.b,invoice,self.uid)['customer_id'],customer)
            self.assertEqual(f.get_invoice_totals(self.b,invoice,self.uid)['total_minor'],250000)
        customers=self.client.get(self.url+f'/receivables?branch_id={self.ba}&section=customers')
        self.assertEqual(customers.status_code,200)
        self.assertNotIn('Customer Baru',customers.text)
        invoices=self.client.get(self.url+f'/receivables?branch_id={self.ba}&section=invoices')
        self.assertEqual(invoices.status_code,200)
        self.assertIn('Customer Baru',invoices.text)

    def test_invoice_payment_collections_and_cross_branch_lock(self):
        ia=self.invoice(self.ba);ib=self.invoice(self.bb)
        with self.scope(self.ba):
            f.record_invoice_payment(self.b,ia,100,'2026-09-17',self.a,self.cat,actor_user_id=self.uid,idempotency_key='branch-payment-key')
            self.assertEqual(collections.position(self.b,self.uid)['aging']['total_outstanding_minor'],900)
            self.assertIsNone(f.get_finance_invoice(self.b,ib))
            for invoice, account in ((ia,self.ab),(ib,self.a)):
                with self.assertRaises(f.FinanceError):
                    f.record_invoice_payment(self.b,invoice,1,'2026-09-17',account,self.cat,idempotency_key='cross-branch-payment')
        with self.assertRaises(f.FinanceError):
            f.record_invoice_payment(self.b,ia,1,'2026-09-17',self.ab,self.cat,idempotency_key='internal-wrong-account')
        with self.scope(None): self.assertEqual(collections.position(self.b,self.uid)['aging']['total_outstanding_minor'],1900)
        with self.scope(self.bb): self.assertEqual(collections.position(self.b,self.uid)['aging']['total_outstanding_minor'],1000)
        self.assertEqual(f.list_transactions(self.b)[0]['branch_id'],self.ba)

    def test_recurring_keeps_configured_branch_in_job_and_ui(self):
        with self.scope(self.bb):
            rule=f.create_recurring_expense(self.b,'Rent',80,self.ab,self.expense['id'],'MONTHLY','2026-09-17',actor_user_id=self.uid)
            with self.assertRaises(f.FinanceError): f.create_recurring_expense(self.b,'Wrong',80,self.a,self.expense['id'],'MONTHLY','2026-09-17')
        with self.scope(self.ba):
            self.assertEqual(f.list_recurring_expenses(self.b),[])
            self.assertEqual(f.process_due_recurring_expenses(self.b,'2026-09-17')['posted_count'],0)
        self.assertEqual(f.process_due_recurring_expenses(self.b,'2026-09-17')['posted_count'],1)
        tx=f.list_transactions(self.b)[0]
        self.assertEqual((tx['branch_id'],tx['account_id']),(self.bb,self.ab))
        self.assertEqual(f.process_due_recurring_expenses(self.b,'2026-09-17')['posted_count'],0)
        self.assertEqual(f.get_recurring_expense(self.b,rule)['branch_id'],self.bb)
        with self.scope(self.bb):
            commitments = f.get_upcoming_recurring_commitments(self.b,'2026-10-01','2026-10-31')
            self.assertEqual(commitments[0]['branch_name'],'Serpong')

    def test_bank_scope_import_decision_and_cross_match(self):
        source=extraction.validate_sources([('bank.csv',b'date,description,debit,credit\n2026-09-17,Coffee,10,0\n')])
        row=dict(transaction_date='2026-09-17',description='Coffee',direction='EXPENSE',amount_minor=10,reference=None)
        with self.scope(self.ba):
            imp=bank.stage(self.b,self.a,source,[row],self.uid)
            bank.open_import(self.b,imp,0,self.uid)
        with self.scope(self.bb):
            self.assertEqual(bank.list_imports(self.b,self.uid),[])
            with self.assertRaises(f.FinanceError):bank.get_import(self.b,imp,self.uid)
            with self.assertRaises(f.FinanceError):bank.stage(self.b,self.a,source,[row],self.uid)
        wrong=self.tx(self.bb,10,'EXPENSE')
        with self.scope(self.ba):
            rid=bank.get_rows(self.b,imp,self.uid)[0]['id']
            with self.assertRaises(f.FinanceError):bank.decide(self.b,imp,rid,'match',self.uid,transaction_id=wrong)
            bank.decide(self.b,imp,rid,'post',self.uid,fields=dict(category_id=self.expense['id'],occurred_on='2026-09-17',description='Coffee',counterparty_name=None))
            self.assertEqual(f.list_transactions(self.b)[0]['branch_id'],self.ba)

    def test_receipt_signed_branch_identity_and_replay(self):
        with app.app_context(), self.scope(self.ba):
            review=receipts.analyze(self.b,self.uid,'receipt.png',self.raw)
            self.assertEqual(receipts.signer().loads(review['token'])['branch_id'],self.ba)
        fields=prior.ReceiptTests.fields(self)
        with app.app_context(),self.scope(self.bb),self.assertRaises(f.FinanceError):
            receipts.confirm(self.b,self.uid,review['token'],dict(fields,account_id=str(self.ab)))
        with app.app_context(),self.scope(self.ba):
            first=receipts.confirm(self.b,self.uid,review['token'],fields)
            self.assertEqual(receipts.confirm(self.b,self.uid,review['token'],fields),first)
        self.assertEqual(f.get_transaction(self.b,first)['branch_id'],self.ba)

    def test_operator_signed_branch_identity_and_replay(self):
        payload=dict(action='create_income',request='Coffee 100',date='2026-09-17',account_id=self.a,category_id=self.cat,invoice_id=None)
        with app.app_context(),patch.dict(os.environ, KILAS_FINANCE_OPERATOR_BUSINESS_IDS=str(self.b)),patch.object(operator,'interpret',return_value=dict(amount_minor=100,description='Coffee')):
            with self.scope(self.ba):
                draft=operator.prepare(self.b,self.uid,payload)
                self.assertEqual(operator.signer().loads(draft['token'])['branch_id'],self.ba)
            with self.scope(self.bb),self.assertRaises(f.FinanceError):operator.confirm(self.b,self.uid,draft['token'])
            with self.scope(self.ba):
                result=operator.confirm(self.b,self.uid,draft['token'])
                self.assertEqual(operator.confirm(self.b,self.uid,draft['token'])['record_id'],result['record_id'])

    def test_reports_export_branch_labels_period_and_pdf(self):
        self.tx(self.ba,11);self.tx(self.bb,22);self.tx(self.ba,99,day='2025-09-17')
        filters=dict(start='2026-09-01',end='2026-09-20',as_of='2026-09-20',commitment_start='2026-09-20',commitment_end='2026-10-19')
        for branch,n,total in ((self.ba,1,11),(self.bb,1,22)):
            with self.scope(branch):
                rows=list(csv.DictReader(io.StringIO(reports.export_csv('transactions',self.b,filters,self.uid).decode('utf-8-sig'))))
                self.assertEqual(len(rows),n)
                self.assertEqual(sum(int(r['nominal']) for r in rows),total)
                self.assertTrue(all(r['Branch'] in ('Utama','Serpong') for r in rows))
            page=self.client.get(self.url+f'/reports?branch_id={branch}&start=2026-09-01&end=2026-09-20&as_of=2026-09-20')
            self.assertEqual(page.status_code,200)
            self.assertIn('Unduh PDF',page.text)
            self.assertNotIn('Download Semua CSV',page.text)
            pdf=self.client.get(self.url+f'/reports/export/report.pdf?branch_id={branch}&start=2026-09-01&end=2026-09-20&as_of=2026-09-20')
            self.assertEqual(pdf.status_code,200)
            self.assertEqual(pdf.mimetype,'application/pdf')
            self.assertTrue(pdf.data.startswith(b'%PDF'))
            self.assertIn('attachment; filename="kilas-finance-2026-09-01_2026-09-20.pdf"',pdf.headers['Content-Disposition'])

    def test_all_businesses_and_scope_does_not_leak_between_requests(self):
        self.tx(self.ba,11);self.tx(self.bb,22)
        self.assertEqual(self.page(self.ba)[1]['summary']['total_income_minor'],11)
        contexts=[]
        def capture(sender,template,context,**kw): contexts.append(context)
        with template_rendered.connected_to(capture,app):response=self.client.get('/finance?month=2026-09')
        self.assertEqual(response.status_code,200)
        self.assertEqual(next(r for r in contexts[-1]['totals_by_currency'] if r['currency']=='IDR')['total_income_minor'],33)
        self.assertEqual(self.page(self.bb)[1]['summary']['total_income_minor'],22)

    def test_branch_period_filter_links_and_csrf(self):
        response=self.client.get(self.url+f'?branch_id={self.bb}&period_year=2024&period_month=02')
        self.assertIn('branch_id='+str(self.bb),response.location)
        self.assertIn('month=2024-02',response.location)
        page=self.client.get(response.location)
        self.assertEqual(page.status_code,200)
        self.assertIn('value="02" selected',page.text)
        self.assertIn('start=2024-02-01',page.text)
        self.assertIn('end=2024-02-29',page.text)
        report = self.client.get(self.url+f'/reports?branch_id={self.bb}&start=2024-02-01&end=2024-02-29&as_of=2024-02-29')
        self.assertEqual(report.status_code,200)
        self.assertIn('name="start" value="2024-02-01"',report.text)
        app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=True
        for suffix in ('branches',f'settings/branch/{self.bb}',f'transactions/1/edit'):
            self.assertEqual(self.client.post(self.url+'/'+suffix+f'?branch_id={self.bb}',data={'name':'No token'}).status_code,400)

    def test_public_statement_does_not_expand_selected_branch(self):
        self.invoice(self.ba);self.invoice(self.bb)
        with app.app_context(),self.scope(self.ba):token=collections.create_token(self.b,self.c,self.uid)
        response=self.client.get('/finance/statement-share/'+token)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.text.count('KFIN-2026-'),1)

    def test_raw_database_guards(self):
        tx=self.tx(self.ba)
        with self.assertRaises(sqlite3.IntegrityError):db.execute('UPDATE finance_transactions SET branch_id=? WHERE id=?',(self.bb,tx))
        with self.assertRaises(sqlite3.IntegrityError):db.execute('UPDATE finance_transactions SET account_id=? WHERE id=?',(self.ab,tx))
        with self.assertRaises(sqlite3.IntegrityError):db.execute('UPDATE finance_accounts SET branch_id=? WHERE id=?',(self.bb,self.a))

    def test_project_and_customer_cash_entries_scoped_master_shared(self):
        project=db.insert_returning_id("INSERT INTO projects (business_id,project_type,pricing_mode,title,status,created_by_user_id) VALUES (?,'CONTENT','CUSTOM_QUOTE','Coffee project','REQUESTED',?)",(self.b,self.uid))
        self.tx(self.ba,20,project_id=project,customer_id=self.c)
        self.tx(self.bb,70,project_id=project,customer_id=self.c)
        for branch,amount in ((self.ba,20),(self.bb,70),(None,90)):
            with self.scope(branch):
                self.assertEqual(f.get_project_cash_contribution(self.b,'2026-09-01','2026-09-30')[0]['income_minor'],amount)
                self.assertEqual(f.get_customer_cash_contribution(self.b,'2026-09-01','2026-09-30')[0]['income_minor'],amount)
                self.assertEqual(f.list_finance_projects(self.b)[0]['id'],project)
                self.assertEqual(f.list_customers(self.b)[0]['id'],self.c)

    def test_shared_finance_pages_normalize_archived_branch_to_active(self):
        self.tx(self.bb,10)
        with self.scope(self.ba):
            branches.update_record(self.b,'branch',self.bb,deactivate=True,actor_user_id=self.uid)
        for suffix in ('/assistant','/reports','/receivables','/operations'):
            response=self.client.get(self.url+suffix+f'?branch_id={self.bb}')
            self.assertEqual(response.status_code,200,suffix)
            self.assertNotIn('Serpong (Nonaktif)',response.text)
            self.assertNotIn('Semua Cabang',response.text)

    def test_dashboard_redirects_archived_branch_to_active_branch(self):
        self.tx(self.bb, 10)
        with self.scope(self.ba):
            branches.update_record(self.b,'branch',self.bb,deactivate=True,actor_user_id=self.uid)
        response=self.client.get(self.url+f'?branch_id={self.bb}')
        self.assertEqual(response.status_code,303)
        self.assertIn('branch_id='+str(self.ba),response.location)

    def test_delete_empty_branch_removes_it_instead_of_leaving_nonactive_choice(self):
        with self.scope(self.ba):
            empty=branches.create_branch(self.b,'Disposable',self.uid)
        self.assertEqual(len([a for a in f.list_accounts(self.b,True) if a['branch_id']==empty]),1)
        with self.scope(self.ba):
            branches.update_record(self.b,'branch',empty,deactivate=True,actor_user_id=self.uid)
        self.assertIsNone(db.query_one('SELECT id FROM finance_branches WHERE business_id=? AND id=?',(self.b,empty)))
        self.assertEqual(db.query_all('SELECT id FROM finance_accounts WHERE business_id=? AND branch_id=?',(self.b,empty)),[])

    def test_essential_settings_cannot_all_be_deleted(self):
        with self.scope(self.ba):
            # One active account must always remain in an active branch.
            accounts=f.list_accounts(self.b)
            for account in accounts[1:]:
                branches.update_record(self.b,'account',account['id'],deactivate=True,actor_user_id=self.uid)
            remaining=f.list_accounts(self.b)
            with self.assertRaisesRegex(f.FinanceError,'account_last_active'):
                branches.update_record(self.b,'account',remaining[0]['id'],deactivate=True,actor_user_id=self.uid)

            # Keep at least one usable category for each side of the ledger.
            for direction in ('INCOME','EXPENSE'):
                categories=f.list_categories(self.b,direction)
                for category in categories[1:]:
                    branches.update_record(self.b,'category',category['id'],deactivate=True,actor_user_id=self.uid)
                with self.assertRaisesRegex(f.FinanceError,'category_last_active'):
                    branches.update_record(self.b,'category',categories[0]['id'],deactivate=True,actor_user_id=self.uid)

    def test_last_account_for_currency_with_balance_is_protected(self):
        with self.scope(self.ba):
            usd=f.create_account(self.b,'USD Bank','BANK','USD',10000,actor_user_id=self.uid)
            other=f.create_account(self.b,'Spare IDR','BANK','IDR',0,actor_user_id=self.uid)
            self.assertTrue(other)
            with self.assertRaisesRegex(f.FinanceError,'account_currency_required'):
                branches.update_record(self.b,'account',usd,deactivate=True,actor_user_id=self.uid)

    def test_new_finance_setup_has_working_defaults(self):
        empty=repo.create_business(self.uid,'Fresh finance')
        url=f'/business/{empty}/finance'
        response=self.client.post(url+'/start')
        self.assertEqual(response.status_code,303)
        branch=branches.list_branches(empty)[0]
        self.assertTrue(branch['is_active'])
        with branches.scope(empty,branch['id'],self.uid):
            accounts=f.list_accounts(empty)
            self.assertEqual([(a['name'],a['currency']) for a in accounts],[('Kas','IDR')])
            self.assertGreaterEqual(len(f.list_categories(empty,'INCOME')),1)
            self.assertGreaterEqual(len(f.list_categories(empty,'EXPENSE')),1)
        page=self.client.get(url+f'?branch_id={branch["id"]}')
        self.assertEqual(page.status_code,200)
        for value in ('data-finance-open="add-transaction-dialog"','Customer','Piutang','Biaya Rutin','Lihat laporan','Tanya Kilas Finance'):
            self.assertIn(value,page.text)

    def test_readding_hidden_branch_reactivates_same_record(self):
        self.tx(self.bb)  # A branch with history is archived; an empty branch is deleted.
        with self.scope(self.bb):
            branches.update_record(self.b,'branch',self.bb,deactivate=True,actor_user_id=self.uid)
        with self.scope(self.ba):
            restored=branches.create_branch(self.b,'Serpong',self.uid)
        self.assertEqual(restored,self.bb)
        self.assertTrue(branches.get(self.b,self.bb)['is_active'])
        self.assertEqual(len([b for b in branches.list_branches(self.b) if b['name']=='Serpong']),1)

    def test_branch_routes_and_last_active_guard(self):
        response=self.client.post(self.url+f'/branches?branch_id={self.ba}',data={'name':'BSD'})
        self.assertEqual(response.status_code,303)
        branch=branches.list_branches(self.b)[-1]
        self.assertIn('branch_id='+str(branch['id']),response.location)
        response=self.client.post(self.url+f'/settings/branch/{branch["id"]}?branch_id={branch["id"]}',data={'name':'BSD City','action':'edit'})
        self.assertEqual(response.status_code,303)
        self.assertEqual(branches.get(self.b,branch['id'])['name'],'BSD City')
        branches.update_record(self.b,'branch',branch['id'],deactivate=True)
        branches.update_record(self.b,'branch',self.bb,deactivate=True)
        with self.scope(self.ba),self.assertRaisesRegex(f.FinanceError,'branch_last_active'):
            branches.update_record(self.b,'branch',self.ba,deactivate=True)

    def test_one_subscription_for_all_branches_expiry_blocks_each(self):
        import finance_entitlements as entitlement
        with patch.dict(os.environ,KILAS_FINANCE_ACCESS_MODE='self_service'):
            entitlement.start_trial(self.b,self.uid)
            with self.scope(self.ba):branches.create_branch(self.b,'BSD',self.uid)
            self.assertEqual(len(db.query_all('SELECT * FROM finance_entitlements WHERE business_id=?',(self.b,))),1)
            self.assertEqual(len(db.query_all('SELECT id FROM businesses')),2)
            db.execute("UPDATE finance_entitlements SET trial_until='2020-01-01T00:00:00+00:00' WHERE business_id=?",(self.b,))
            for branch in (self.ba,self.bb):
                with self.scope(branch),self.assertRaisesRegex(f.FinanceError,'finance_read_only'):
                    f.create_account(self.b,'Denied')

    def test_snapshot_and_edit_roll_back_on_audit_failure(self):
        tx=self.tx(self.ba,100)
        with self.scope(self.ba),patch.object(f,'_audit',side_effect=RuntimeError('audit failed')),self.assertRaises(RuntimeError):
            f.update_transaction(self.b,tx,amount_minor=200)
        self.assertEqual(f.get_transaction(self.b,tx)['amount_minor'],100)
        self.assertEqual(db.query_all('SELECT * FROM finance_transaction_revisions'),[])

    def test_branch_context_isolated_across_concurrent_tasks(self):
        import asyncio
        self.tx(self.ba,11);self.tx(self.bb,22)
        async def read(branch):
            with self.scope(branch):
                await asyncio.sleep(0)
                return f.get_finance_summary(self.b,'2026-09-01','2026-09-30')['total_income_minor']
        async def run():return await asyncio.gather(read(self.ba),read(self.bb),read(None))
        self.assertEqual(asyncio.run(run()),[11,22,33])

    def test_legacy_first_setup_does_not_make_all_mode_writable(self):
        empty=repo.create_business(self.uid,'Empty business')
        url=f'/business/{empty}/finance'
        page=self.client.get(url)
        self.assertEqual(page.status_code,200)
        self.assertNotIn('finance_read_only.js',page.text)
        self.assertEqual(self.client.post(url+'/start?branch_id=all').status_code,403)
        self.assertEqual(branches.list_branches(empty),[])
        self.assertEqual(self.client.post(url+'/start').status_code,303)
        self.assertEqual(branches.list_branches(empty)[0]['name'],'Utama')


    def test_reset_finance_zeroes_selected_branch_only_and_keeps_setup(self):
        db.execute('UPDATE finance_accounts SET opening_balance_minor=500 WHERE id=?', (self.a,))
        db.execute('UPDATE finance_accounts SET opening_balance_minor=700 WHERE id=?', (self.ab,))
        self.tx(self.ba, 300)
        self.tx(self.bb, 200)
        invoice = self.invoice(self.ba)
        with self.scope(self.ba):
            f.record_invoice_payment(
                self.b, invoice, 100, '2026-09-17', self.a, self.cat,
                actor_user_id=self.uid, idempotency_key='reset-payment-key-0001')
            recurring = f.create_recurring_expense(
                self.b, 'Rent reset', 50, self.a, self.expense['id'], 'MONTHLY',
                '2026-10-01', actor_user_id=self.uid)
            self.assertEqual(f.get_finance_summary(
                self.b, '2026-09-01', '2026-09-30')['total_income_minor'], 400)

        denied = self.client.post(
            self.url + f'/reset?branch_id={self.ba}', data={'confirmation': 'NO'})
        self.assertEqual(denied.status_code, 303)
        with self.scope(self.ba):
            self.assertEqual(f.get_finance_summary(
                self.b, '2026-09-01', '2026-09-30')['total_income_minor'], 400)

        response = self.client.post(
            self.url + f'/reset?branch_id={self.ba}', data={'confirmation': 'RESET'})
        self.assertEqual(response.status_code, 303)
        with self.scope(self.ba):
            summary = f.get_finance_summary(self.b, '2026-09-01', '2026-09-30')
            self.assertEqual((summary['total_income_minor'], summary['total_expense_minor']), (0, 0))
            self.assertEqual(sum(
                row['balance_minor'] for row in f.get_account_balance_report(
                    self.b, '2026-09-30')), 0)
            self.assertTrue(all(
                row['status'] == 'VOID' for row in f.list_transactions(self.b)))
            self.assertEqual(f.get_finance_invoice(self.b, invoice)['status'], 'VOID')
            self.assertFalse(f.get_recurring_expense(self.b, recurring)['is_active'])
            self.assertEqual(
                collections.position(self.b, self.uid)['aging']['total_outstanding_minor'], 0)
            self.assertTrue(branches.get(self.b, self.ba)['is_active'])
            self.assertTrue(any(a['id'] == self.a for a in f.list_accounts(
                self.b, include_inactive=True)))
            self.assertTrue(any(c['id'] == self.cat for c in f.list_categories(
                self.b, include_inactive=True)))

        with self.scope(self.bb):
            summary = f.get_finance_summary(self.b, '2026-09-01', '2026-09-30')
            self.assertEqual(summary['total_income_minor'], 200)
            self.assertEqual(sum(
                row['balance_minor'] for row in f.get_account_balance_report(
                    self.b, '2026-09-30')), 900)



    def test_future_actual_dates_and_months_are_rejected(self):
        tomorrow=(date.today()+timedelta(days=1)).isoformat()
        with self.scope(self.ba):
            with self.assertRaisesRegex(f.FinanceError,'future_date'):
                f.create_transaction(self.b,'INCOME',100,self.a,self.cat,tomorrow,actor_user_id=self.uid)
            with self.assertRaisesRegex(f.FinanceError,'future_date'):
                f.create_finance_invoice(self.b,self.c,tomorrow,tomorrow,
                    [dict(description='Future',quantity=1,unit_price_minor=100)],actor_user_id=self.uid)
        future_month=(date.today().replace(day=28)+timedelta(days=4)).replace(day=1).strftime('%Y-%m')
        response=self.client.get(self.url,query_string={'branch_id':self.ba,'month':future_month})
        self.assertEqual(response.status_code,302)
        self.assertNotIn('month='+future_month,response.location)
        future=(date.today()+timedelta(days=1)).isoformat()
        with self.assertRaises(f.FinanceError):
            reports.parse_filters({'start':date.today().isoformat(),'end':future,'as_of':future})



class BranchMigrationTests(unittest.TestCase):
    def test_legacy_history_default_and_repeat_migration(self):
        saved_path=db.SQLITE_PATH
        if getattr(db._local,'conn',None):db._local.conn.close()
        db._local.conn=None
        try:
            with tempfile.TemporaryDirectory() as folder:
                db.SQLITE_PATH=folder+'/legacy.db'
                with patch.object(db,'MIGRATIONS',[m for m in db.MIGRATIONS if m[0] < '0033_']):db.init_schema()
                uid=repo.create_user('legacy@example.test','unused');bid=repo.create_business(uid,'Kopi Mantan')
                now=repo._now()
                account=db.insert_returning_id('INSERT INTO finance_accounts (business_id,name,account_type,opening_balance_minor,created_at,updated_at) VALUES (?,?,?,123,?,?)',(bid,'BCA','BANK',now,now))
                category=db.insert_returning_id('INSERT INTO finance_categories (business_id,direction,name,created_at,updated_at) VALUES (?,?,?,?,?)',(bid,'INCOME','Sales',now,now))
                tx=db.insert_returning_id('INSERT INTO finance_transactions (business_id,direction,amount_minor,account_id,category_id,occurred_on,created_at,updated_at) VALUES (?,\'INCOME\',50,?,?,\'2026-09-17\',?,?)',(bid,account,category,now,now))
                customer=db.insert_returning_id('INSERT INTO finance_customers (business_id,name,created_at,updated_at) VALUES (?,?,?,?)',(bid,'Legacy customer',now,now))
                invoice=db.insert_returning_id('INSERT INTO finance_invoices (business_id,customer_id,invoice_number,issue_date,due_date,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',(bid,customer,'LEGACY-1','2026-09-01','2026-09-30',now,now))
                expense=db.insert_returning_id('INSERT INTO finance_categories (business_id,direction,name,created_at,updated_at) VALUES (?,?,?,?,?)',(bid,'EXPENSE','Rent',now,now))
                recurring=db.insert_returning_id("INSERT INTO finance_recurring_expenses (business_id,name,amount_minor,account_id,category_id,cadence,anchor_day,next_due_on,created_at,updated_at) VALUES (?,'Rent',20,?,?,'MONTHLY',17,'2026-09-17',?,?)",(bid,account,expense,now,now))
                imported=db.insert_returning_id("INSERT INTO finance_bank_imports (business_id,account_id,source_kind,display_label,file_hash,source_count,imported_by_user_id,created_at,updated_at) VALUES (?,?,'CSV','Legacy',?,1,?,?,?)",(bid,account,'a'*64,uid,now,now))
                legacy = {table:db.query_all('SELECT * FROM '+table) for table in ('finance_accounts','finance_transactions','finance_invoices','finance_recurring_expenses','finance_bank_imports')}
                before=db.query_one('SELECT * FROM finance_transactions WHERE id=?',(tx,))
                db.init_schema();db.init_schema()
                rows=branches.list_branches(bid)
                self.assertEqual(len(rows),1);self.assertEqual(rows[0]['name'],'Utama')
                after=db.query_one('SELECT * FROM finance_transactions WHERE id=?',(tx,))
                self.assertEqual({k:after[k] for k in before},before)
                self.assertEqual(after['branch_id'],rows[0]['id'])
                for table, old_rows in legacy.items():
                    new_rows=db.query_all('SELECT * FROM '+table)
                    self.assertEqual(len(old_rows),len(new_rows))
                    for old,new in zip(old_rows,new_rows):
                        self.assertEqual({k:new[k] for k in old},old)
                        self.assertEqual(new['branch_id'],rows[0]['id'])
                self.assertEqual(f.get_account_balance_report(bid,'2026-09-17')[0]['balance_minor'],173)
                branches.create_branch(bid,'Serpong',uid)
                db.init_schema()
                self.assertEqual(len(branches.list_branches(bid)),2)
                self.assertEqual(len(db.query_all('SELECT id FROM businesses')),1)
                self.assertEqual(db.query_all('PRAGMA foreign_key_check'),[])
        finally:
            if getattr(db._local,'conn',None):db._local.conn.close()
            db._local.conn=None;db.SQLITE_PATH=saved_path
