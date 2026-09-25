from finance_test_clock import closed_period
"""Offline membership-only consolidated reporting and single-business regressions."""
import os
import unittest
from datetime import datetime, timezone
from html.parser import HTMLParser
from unittest.mock import patch
from flask import template_rendered
import test_finance_phase2a as prior
import db
import repo
import finance_service as finance
import finance_entitlements as entitlement

app = prior.app


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class MultiBusinessTests(unittest.TestCase):
    draft = prior.ReceivablesTests.draft
    issued = prior.ReceivablesTests.issued
    pay = prior.ReceivablesTests.pay

    def setUp(self):
        prior.ReceivablesTests.setUp(self)
        self.second = repo.create_business(self.uid, 'Second authorized business')
        self.empty = repo.create_business(self.uid, 'Empty authorized business')
        finance.ensure_finance_defaults(self.second, actor_user_id=self.uid)
        rates=patch('finance_fx.snapshot',return_value={'rates':{'IDR':'1','USD':'16000'},'date':'2026-09-20','source':'test','stale':False});rates.start();self.addCleanup(rates.stop)

    def page(self, url='/finance?month=2026-09'):
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, app):
            result = self.client.get(url, follow_redirects=True)
        self.assertEqual(result.status_code, 200)
        context=contexts[-1]
        if 'totals_by_currency' in context:
            context['summary']=next(r for r in context['totals_by_currency'] if r['currency']=='IDR').copy()
            context['summary'].pop('currency')
            context['summary'].update(open_invoice_count=context['open_invoice_count'],overdue_invoice_count=context['overdue_invoice_count'])
            for row in context['breakdown']:
                cash=next((r for r in row['cash_summaries'] if r['currency']=='IDR'),{})
                row['summary']={k:cash.get(k,0) for k in context['summary']}
                aging=next((r for r in row['receivables']['by_currency'] if r['currency']=='IDR'),{})
                row['summary'].update({k:aging.get(k,0) for k in ('total_outstanding_minor','total_overdue_minor')})
                row['summary'].update({k:row['receivables'][k] for k in ('open_invoice_count','overdue_invoice_count')})
        return result, context

    def transaction(self, business, direction, amount, day='2026-09-10', currency='IDR'):
        actor = self.other_uid if business == self.other else self.uid
        account = finance.list_accounts(business)[0]['id']
        if currency != 'IDR':
            account = finance.create_account(business, 'Foreign account', currency=currency, actor_user_id=actor)
        category = finance.list_categories(business, direction)[0]['id']
        return finance.create_transaction(business, direction, amount, account, category, day,
                                          currency=currency, actor_user_id=actor)

    def test_membership_selector_and_no_foreign_data(self):
        self.transaction(self.other, 'INCOME', 987654321)
        for url in ('/finance?month=2026-09', self.url+'?month=2026-09'):
            response, context = self.page(url)
            self.assertEqual({b['id'] for b in context['businesses']}, {self.b, self.second, self.empty})
            html = response.get_data(as_text=True)
            for name in ('Business', 'Second authorized business', 'Empty authorized business'):
                self.assertIn(name, html)
            self.assertEqual('Semua Bisnis' in html,url.startswith('/finance?'))
            for secret in ('Other business', 'PRIVATE CUSTOMER', '987.654.321'):
                self.assertNotIn(secret, html)

    def test_forged_business_selection_cannot_expand_scope(self):
        for value in (str(self.other), '999999', '-1', '1,2', '../../admin'):
            self.assertEqual(self.client.get('/finance', query_string={'business_id': value}).status_code, 404)
        self.assertEqual(self.client.get(f'/business/{self.other}/finance').status_code, 404)
        _, context = self.page('/finance?month=2026-09&business_ids='+str(self.other))
        self.assertNotIn(self.other, [r['business']['id'] for r in context['breakdown']])

    def test_admin_overview_still_uses_memberships_only(self):
        admin = repo.create_user('aggregate-admin@example.test', 'unused', role='KILAS_ADMIN')
        own = repo.create_business(admin, 'Admin membership business')
        with self.client.session_transaction() as session:
            session['user_id'] = admin
        with patch('repo.list_all_businesses', side_effect=AssertionError('Global list forbidden')):
            _, context = self.page()
        self.assertEqual([b['id'] for b in context['businesses']], [own])
        self.assertEqual(self.client.get('/finance?business_id='+str(self.b)).status_code, 404)
        self.assertEqual(self.client.get(self.url).status_code, 200)  # existing admin access unchanged

    def test_membership_grant_and_revocation_change_report_scope(self):
        self.transaction(self.other, 'INCOME', 500)
        db.execute("INSERT INTO business_memberships (business_id,user_id,role_in_business) VALUES (?,?,'OWNER')",
                   (self.other, self.uid))
        _, granted = self.page()
        self.assertEqual(granted['summary']['total_income_minor'], 500)
        db.execute('DELETE FROM business_memberships WHERE business_id=? AND user_id=?', (self.other, self.uid))
        response, revoked = self.page()
        self.assertEqual(revoked['summary']['total_income_minor'], 0)
        self.assertNotIn('Other business', response.get_data(as_text=True))
        self.assertEqual(self.client.get('/finance?business_id='+str(self.other)).status_code, 404)

    @closed_period
    def test_cash_totals_sum_only_posted_idr_in_selected_month(self):
        self.transaction(self.b, 'INCOME', 1100)
        self.transaction(self.b, 'EXPENSE', 300)
        self.transaction(self.second, 'INCOME', 700)
        self.transaction(self.second, 'EXPENSE', 200)
        self.transaction(self.second, 'INCOME', 99999, '2026-08-31')
        self.transaction(self.second, 'INCOME', 99999, '2026-10-01')
        self.transaction(self.b, 'INCOME', 99999, currency='USD')
        voided = self.transaction(self.b, 'INCOME', 99999)
        finance.void_transaction(self.b, voided, actor_user_id=self.uid)
        self.transaction(self.other, 'INCOME', 99999)
        _, context = self.page()
        for key, expected in (('total_income_minor', 1800), ('total_expense_minor', 500), ('net_cashflow_minor', 1300)):
            self.assertEqual(context['summary'][key], expected)
            self.assertEqual(context['summary'][key], sum(row['summary'][key] for row in context['breakdown']))
        usd=next(row for row in context['totals_by_currency'] if row['currency']=='USD')
        self.assertEqual(usd['total_income_minor'],99999)
        self.assertEqual(usd['net_cashflow_minor'],99999)
        _, single = self.page(self.url+'?month=2026-09')
        self.assertEqual({k:v for k,v in single['summary'].items() if k!='transaction_count'}, finance.get_finance_summary(self.b, '2026-09-01', '2026-09-30', actor_user_id=self.uid))
        self.assertEqual(single['summary']['net_cashflow_minor'], 800)

    @closed_period
    def test_receivables_and_overdue_use_existing_period_end_calculations(self):
        invoice = self.issued()
        self.pay(invoice, 100)
        self.pay(invoice, 50, key='after-selected-month-1', paid_on='2026-10-01')
        customer = finance.create_customer(self.second, 'Second customer', actor_user_id=self.uid)
        for due in ('2026-09-20', '2026-10-20'):
            invoice = self.draft(business_id=self.second, customer_id=customer, due_date=due)
            finance.issue_finance_invoice(self.second, invoice, actor_user_id=self.uid)
        self.draft()  # drafts do not contribute
        later = self.draft(issue_date='2026-10-01', due_date='2026-10-15')
        finance.issue_finance_invoice(self.b, later, actor_user_id=self.uid)
        foreign = self.draft(business_id=self.other, customer_id=self.oc, actor_user_id=self.other_uid)
        finance.issue_finance_invoice(self.other, foreign, actor_user_id=self.other_uid)
        _, context = self.page()
        for key, expected in (('total_outstanding_minor', 650), ('total_overdue_minor', 400),
                              ('overdue_invoice_count', 2), ('open_invoice_count', 3)):
            self.assertEqual(context['summary'][key], expected)
        self.assertEqual(context['as_of'], '2026-09-30')
        _, august = self.page('/finance?month=2026-08')
        self.assertEqual(august['summary']['total_outstanding_minor'], 0)

    def test_empty_business_zero_without_initialization_or_writes(self):
        before = list(db.get_connection().iterdump())
        _, context = self.page()
        empty = next(row['summary'] for row in context['breakdown'] if row['business']['id'] == self.empty)
        for key in context['summary']:
            self.assertEqual(empty[key], 0)
        self.assertEqual(before, list(db.get_connection().iterdump()))

    def test_no_memberships_shows_safe_empty_state(self):
        user = repo.create_user('no-business@example.test', 'unused')
        with self.client.session_transaction() as session:
            session['user_id'] = user
        response, context = self.page()
        self.assertIn('Belum ada bisnis', response.get_data(as_text=True))
        self.assertFalse(context['breakdown'])
        self.assertTrue(all(value == 0 for value in context['summary'].values()))

    def test_period_and_business_switching_preserve_month(self):
        response = self.client.get('/finance?period_month=02&period_year=2024')
        self.assertTrue(response.location.endswith('/finance?month=2024-02'))
        response, context = self.page(response.location)
        self.assertEqual(context['as_of'], '2024-02-29')
        elements = Elements(response.get_data(as_text=True)).elements
        self.assertIn(('option', {'value': '02', 'selected': None}), elements)
        self.assertIn(('option', {'value': '2024', 'selected': None}), elements)
        self.assertIn(('input', {'type': 'hidden', 'name': 'month', 'value': '2024-02'}), elements)
        response = self.client.get('/finance', query_string={'business_id': self.second, 'month': '2024-02'})
        self.assertTrue(response.location.endswith(f'/business/{self.second}/finance?month=2024-02&display_currency=IDR'))
        response, context = self.page(response.location)
        self.assertEqual(context['month'], '2024-02')
        self.assertIn(('option', {'value': str(self.second), 'selected': None}), Elements(response.get_data(as_text=True)).elements)
        response = self.client.get('/finance?business_id=all&month=2024-02')
        self.assertEqual(response.status_code, 200)

    def test_invalid_period_redirects_safely(self):
        for query in ('month=2026-13', 'period_month=2&period_year=2026', 'month=0000-01'):
            response = self.client.get('/finance?'+query)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/finance', response.location)

    def test_all_business_view_has_no_finance_writes_or_assistant(self):
        response, _ = self.page()
        html = response.get_data(as_text=True)
        self.assertIn('Mode Semua Bisnis hanya untuk melihat ringkasan. Pilih satu bisnis untuk mencatat atau mengubah data.', html)
        for text in ('AI Assistant', 'Catat Pemasukan', 'Catat Pengeluaran', '/receipts', '/bank', '/operator', '/accounts', '/categories', '/invoices', '/recurring'):
            self.assertNotIn(text, html)
        for tag, attrs in Elements(html).elements:
            if tag == 'form':
                self.assertEqual(attrs.get('method', 'get').lower(), 'get')
        self.assertEqual(self.client.post('/finance').status_code, 405)
        self.assertIn('no-store', response.headers['Cache-Control'])
        single, _ = self.page('/finance?business_id='+str(self.b)+'&month=2026-09')
        for text in ('AI Finance', 'Pemasukan', 'Pengeluaran'):
            self.assertIn(text, single.get_data(as_text=True))

    def test_login_and_feature_gates_unchanged(self):
        self.assertEqual(app.test_client().get('/finance').status_code, 302)
        with patch.dict(os.environ, {'KILAS_FINANCE_BETA': 'off'}):
            self.assertEqual(self.client.get('/finance').status_code, 404)
            self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_expired_and_emergency_read_only_remain_viewable_writes_denied(self):
        self.transaction(self.b, 'INCOME', 700)
        with patch.dict(os.environ, {'KILAS_FINANCE_ACCESS_MODE': 'self_service', 'KILAS_FINANCE_BETA': 'off'}):
            with patch.object(entitlement, 'now', return_value=datetime(2026, 1, 1, tzinfo=timezone.utc)):
                entitlement.start_trial(self.b, self.uid)
            with patch.object(entitlement, 'now', return_value=datetime(2026, 9, 30, tzinfo=timezone.utc)):
                self.assertEqual(entitlement.state(self.b)['status'], 'EXPIRED')
                _, context = self.page()
                self.assertEqual(context['summary']['total_income_minor'], 700)
                single, _ = self.page(self.url+'?month=2026-09')
                self.assertIn('Finance hanya-baca', single.get_data(as_text=True))
                self.assertEqual(self.client.post(self.url+'/transactions', json={}).status_code, 403)
                with patch.dict(os.environ, {'KILAS_FINANCE_EMERGENCY_DISABLE': 'true'}):
                    self.assertEqual(self.client.get('/finance').status_code, 200)
                    self.assertEqual(self.client.get(self.url).status_code, 200)
                    self.assertEqual(self.client.post(self.url+'/transactions', json={}).status_code, 403)
        self.assertEqual(len(finance.list_transactions(self.b)), 1)
        with patch.dict(os.environ, {'KILAS_FINANCE_EMERGENCY_DISABLE': 'true'}):
            self.assertEqual(self.client.get('/finance').status_code, 200)
            self.assertEqual(self.client.post(self.url+'/transactions', json={}).status_code, 403)


if __name__ == '__main__':
    unittest.main()
