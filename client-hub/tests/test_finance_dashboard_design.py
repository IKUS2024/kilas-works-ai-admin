"""Dashboard integration: real ledger reads, context isolation and existing actions."""
import unittest
from unittest.mock import patch
from flask import template_rendered
from datetime import date
import test_finance_phase2a as fixture
import finance_branches as branches
import finance_fx


class DashboardDesignTests(unittest.TestCase):
    def setUp(self):
        fixture.ReceivablesTests.setUp(self)
        self.clock = patch.object(fixture.f, 'business_today', return_value=date(2026, 9, 22))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.branch = branches.default(self.b, self.uid)
        self.expense = fixture.f.list_categories(self.b, 'EXPENSE')[0]['id']

    def page(self, query=''):
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, fixture.app):
            response = self.client.get(self.url+'?month=2026-09'+query)
        self.assertEqual(response.status_code, 200)
        return response.text, contexts[-1]

    def test_balance_is_current_ledger_not_selected_month_net(self):
        fixture.f.create_transaction(self.b, 'INCOME', 750000, self.a, self.cat, '2026-08-10', actor_user_id=self.uid)
        fixture.f.create_transaction(self.b, 'EXPENSE', 120000, self.a, self.expense, '2026-09-10', actor_user_id=self.uid)
        html, c = self.page()
        self.assertEqual(c['balance_total_display'], 'Rp6.300,00')
        self.assertEqual(c['period_income_display'], 'Rp0,00')
        self.assertEqual(c['period_expense_display'], 'Rp1.200,00')
        self.assertEqual(c['dashboard_view']['income_display'], 'Rp7.500,00')
        self.assertEqual(c['dashboard_trend'][-1]['net_minor'], -120000)
        self.assertIn('Total Keuangan Akun', html)
        self.assertNotIn('Putri Maudy', html)
        self.assertNotIn('Aktivitas Terbaru', html)

    def test_bill_payment_uses_same_projection_and_existing_payment_endpoint(self):
        rule = fixture.f.create_recurring_expense(self.b, 'Internet nyata', 170000, self.a, self.expense,
            'MONTHLY', '2026-09-22', actor_user_id=self.uid)
        html, c = self.page()
        self.assertEqual(c['dashboard_view']['bills_display'], 'Rp1.700,00')
        self.assertEqual(c['dashboard_view']['payments_display'], 'Rp0,00')
        self.assertEqual(c['dashboard_view']['upcoming'][0]['id'], rule)
        self.assertIn('/operations?',html)
        bills=self.client.get(f'/business/{self.b}/finance/operations?branch_id={self.branch}&month=2026-09&day=2026-09-22')
        self.assertEqual(bills.status_code,200)
        self.assertIn(f'id="bill-pay-{rule}-2026-09-22"',bills.text)
        self.assertIn('name="paid_on"',bills.text)
        response = self.client.post(f'/business/{self.b}/finance/recurring/process', data={
            'branch_id': self.branch, 'month':'2026-09', 'occurrence':f'{rule}:2026-09-22',
            'paid_on':'2026-09-22', 'account_id':self.a})
        self.assertEqual(response.status_code, 303)
        _, after = self.page()
        self.assertEqual(after['dashboard_view']['payments_display'], 'Rp1.700,00')
        self.assertEqual(after['dashboard_view']['bills_display'], 'Rp0,00')
        self.assertEqual(after['period_expense_display'], 'Rp1.700,00')
        self.assertEqual(after['dashboard_view']['upcoming'][0]['next_due_on'], '2026-10-22')
        self.assertEqual(len(fixture.f.list_transactions(self.b)), 1)

    def test_upcoming_sorted_capped_and_other_business_excluded(self):
        for day in (29, 23, 28, 25, 24, 27):
            fixture.f.create_recurring_expense(self.b, f'Bill {day}', 10000, self.a, self.expense,
                'MONTHLY', f'2026-09-{day}', actor_user_id=self.uid)
        html, c = self.page()
        self.assertEqual([r['next_due_on'] for r in c['dashboard_view']['upcoming']],
                         ['2026-09-23','2026-09-24','2026-09-25','2026-09-27','2026-09-28'])
        response = self.client.get(f'/business/{self.other}/finance')
        self.assertIn(response.status_code, (403,404))

    def test_personal_switch_preserves_full_feature_parity(self):
        # Resolve using existing route registration, never a second workspace system.
        with fixture.app.test_request_context():
            from flask import url_for
            path = url_for('finance.enter_workspace',business_id=self.b,workspace_type='PERSONAL')
        response = self.client.post(path)
        self.assertEqual(response.status_code,303)
        personal = branches.ensure_personal(self.b,self.uid)
        with branches.scope(self.b,personal,self.uid):
            account=fixture.f.list_accounts(self.b,actor_user_id=self.uid)[0]['id']
            category=fixture.f.create_category(self.b,'INCOME','Personal test income',actor_user_id=self.uid)
            fixture.f.create_transaction(self.b,'INCOME',45000,account,category,'2026-09-01',actor_user_id=self.uid)
        html,c=self.page(f'&branch_id={personal}')
        self.assertEqual(c['period_income_display'],'Rp450,00')
        self.assertIn('>Scan Struk</a>',html)
        self.assertIn('>Buat Invoice</a>',html)
        self.assertIn('>Tanya Kilas</a>',html)
        self.assertIn('Invoice',html)
        _,business=self.page(f'&branch_id={self.branch}')
        self.assertEqual(business['period_income_display'],'Rp0,00')

    def test_currency_unavailable_does_not_become_zero(self):
        account=fixture.f.create_account(self.b,'USD','BANK','USD',10000,actor_user_id=self.uid)
        fixture.f.create_transaction(self.b,'INCOME',5000,account,self.cat,'2026-09-01',currency='USD',actor_user_id=self.uid)
        with patch.object(finance_fx,'snapshot',return_value={'rates':{'IDR':'1'},'source':'unavailable','date':'','stale':True}):
            html,c=self.page()
        self.assertEqual(c['balance_total_display'],'Kurs belum lengkap')
        self.assertIsNone(c['dashboard_trend'][-1]['income_minor'])
        self.assertFalse(c['dashboard_view']['chart_valid'])
        self.assertIn('Kurs belum lengkap untuk menampilkan arus kas.',html)

    def test_period_selector_and_search_read_actual_records(self):
        fixture.f.create_transaction(self.b,'INCOME',18000,self.a,self.cat,'2026-09-01',description='Unique retainer',actor_user_id=self.uid)
        html,c=self.page('&trend_months=3&q=Unique')
        self.assertEqual(len(c['dashboard_trend']),3)
        self.assertEqual(c['dashboard_view']['search'][0]['label'],'Unique retainer')
        _,c=self.page('&trend_months=12')
        self.assertEqual(len(c['dashboard_trend']),12)
        _,c=self.page('&trend_months=2000')
        self.assertEqual(len(c['dashboard_trend']),6)
        self.assertNotIn('finance_dashboard.css',self.client.get(self.url+'?view=accounts').text)
        self.assertNotIn('finance_dashboard.css',self.client.get(self.url+'?view=transactions').text)

    def test_invoice_card_is_unpaid_value_and_not_cash_income(self):
        invoice=fixture.f.create_finance_invoice(self.b,self.c,'2026-09-01','2026-09-30',
            [dict(description='Service',quantity=1,unit_price_minor=340000)],actor_user_id=self.uid)
        fixture.f.issue_finance_invoice(self.b,invoice,actor_user_id=self.uid)
        _,c=self.page()
        self.assertEqual(c['dashboard_view']['invoice_display'],'Rp3.400,00')
        self.assertEqual(c['period_income_display'],'Rp0,00')
        self.assertEqual(c['balance_total_display'],'Rp0,00')

    def test_branch_selection_and_existing_all_fallback(self):
        other_branch=branches.create_branch(self.b,'Second outlet',self.uid)
        with branches.scope(self.b,other_branch,self.uid):
            fixture.f.ensure_finance_defaults(self.b,actor_user_id=self.uid)
            account=fixture.f.list_accounts(self.b,actor_user_id=self.uid)[0]['id']
            category=fixture.f.list_categories(self.b,'INCOME',actor_user_id=self.uid)[0]['id']
            fixture.f.create_transaction(self.b,'INCOME',91000,account,category,'2026-09-02',actor_user_id=self.uid)
        _,c=self.page(f'&branch_id={other_branch}')
        self.assertEqual(c['period_income_display'],'Rp910,00')
        _,c=self.page(f'&branch_id={self.branch}')
        self.assertEqual(c['period_income_display'],'Rp0,00')
        _,c=self.page('&branch_id=all')
        self.assertEqual(c['selected_branch_id'],self.branch)
        self.assertEqual(c['period_income_display'],'Rp0,00')

    def test_business_selector_uses_existing_authorized_redirect(self):
        import repo
        second=repo.create_business(self.uid,'Second owned business')
        fixture.f.ensure_finance_defaults(second)
        with fixture.app.test_request_context():
            from flask import url_for
            path=url_for('finance.overview',business_id=second,month='2026-08')
        response=self.client.get(path,follow_redirects=True)
        self.assertEqual(response.status_code,200)
        self.assertIn('Second owned business',response.text)
        self.assertIn('Agustus 2026',response.text)

    def test_report_limit_shows_unavailable_not_fake_zero(self):
        with patch.object(fixture.f,'get_monthly_cashflow_trends',side_effect=fixture.f.FinanceError('report_limit')):
            html,c=self.page()
        self.assertEqual(c['dashboard_view']['income_display'],'Tidak tersedia')
        self.assertIn('Data terlalu banyak',html)
        self.assertEqual(c['dashboard_view']['bills_display'],'Tidak tersedia')
        self.assertIn('Tidak tersedia',html)
