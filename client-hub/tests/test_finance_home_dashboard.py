"""Dashboard reads: six-month trends, recent limit, currency and period boundaries."""
import json
import re
import unittest
from unittest.mock import patch
from flask import template_rendered
import test_finance_phase2a as fixture

class DashboardHomeTests(unittest.TestCase):
    def setUp(self):
        fixture.ReceivablesTests.setUp(self)

    def page(self, query='?month=2026-09'):
        captured = []
        def capture(sender, template, context, **extra): captured.append(context)
        with template_rendered.connected_to(capture, fixture.app):
            response = self.client.get(self.url + query)
        self.assertEqual(response.status_code, 200)
        return response.text, captured[-1]

    def test_six_months_and_five_recent_records_from_scoped_services(self):
        for day in range(1, 8):
            fixture.f.create_transaction(self.b,'INCOME',day*100,self.a,self.cat,
                f'2026-09-{day:02d}',description=f'Transaction {day}',actor_user_id=self.uid)
        other_account=fixture.f.list_accounts(self.other)[0]['id']
        other_category=fixture.f.list_categories(self.other,'INCOME')[0]['id']
        fixture.f.create_transaction(self.other,'INCOME',999999,other_account,other_category,
            '2026-09-08',description='PRIVATE OTHER BUSINESS',actor_user_id=self.other_uid)
        html, context = self.page()
        self.assertEqual([r['month'] for r in context['dashboard_trend']],
                         [f'2026-{m:02d}' for m in range(4,10)])
        self.assertEqual(context['dashboard_trend'][-1]['income_minor'],2800)
        self.assertEqual(len(context['recent_activity']),5)
        self.assertEqual(context['recent_activity'][0]['description'],'Transaction 7')
        self.assertNotIn('PRIVATE OTHER BUSINESS',html)
        self.assertEqual(html.count('class="finance-history-row"'),5)
        self.assertEqual(len(fixture.f.list_transactions(self.b)),7)

    def test_foreign_opening_balance_converts_for_display_but_not_income(self):
        fixture.f.create_account(self.b,'Dollar','BANK','USD',12000,actor_user_id=self.uid)
        import finance_fx
        fx={'rates':{'IDR':'1','USD':'10000'},'date':'2026-09-21','source':'Test FX','stale':False}
        with patch.object(finance_fx,'snapshot',return_value=fx):
            html, context=self.page()
        self.assertEqual(context['balance_total_display'],'Rp1.200.000')
        self.assertEqual(context['period_income_display'],'Rp0')
        self.assertEqual({r['currency'] for r in context['dashboard_trend']},{'IDR'})
        self.assertTrue(all(r['income_minor']==0 for r in context['dashboard_trend']))
        self.assertIn('Test FX',html)
        self.assertIn('dikonversi otomatis ke IDR',html)

    def test_navigation_year_boundary_and_history_unchanged(self):
        _, context=self.page('?month=2026-01')
        self.assertEqual(context['previous_month'],'2025-12')
        self.assertEqual(context['next_month'],'2026-02')
        html, context=self.page('?view=transactions&period_mode=all')
        self.assertEqual(context['transaction_page_size'],10)
        self.assertNotIn('id="finance-trend-data"',html)
        self.assertNotIn('Tanya Kilas Finance',html)

    def test_empty_dashboard_omits_fake_budget_and_attention(self):
        html,context=self.page()
        self.assertNotIn('Anggaran',html)
        self.assertNotIn('Perlu perhatian',html)
        self.assertIn('Belum ada transaksi.',html)
        self.assertEqual(context['recurring_items'],[])

    def test_income_view_is_month_scoped_and_has_add_action(self):
        fixture.f.create_transaction(self.b,'INCOME',250000,self.a,self.cat,
            '2026-09-09',description='Retainer September',actor_user_id=self.uid)
        expense_cat=fixture.f.list_categories(self.b,'EXPENSE')[0]['id']
        fixture.f.create_transaction(self.b,'EXPENSE',99000,self.a,expense_cat,
            '2026-09-10',description='Office expense',actor_user_id=self.uid)
        html,context=self.page('?month=2026-09&view=transactions&direction=INCOME')
        self.assertEqual(context['transaction_total'],1)
        self.assertEqual(context['view'],'transactions')
        self.assertIn('＋ Tambah Pemasukan',html)
        self.assertIn('Retainer September',html)
        self.assertNotIn('Office expense',html)
        self.assertIn('name="return_direction" value="INCOME"',html)
        self.assertIn('Transaksi pemasukan',html)

    def test_accounts_view_uses_live_balance_report_not_dashboard_cards(self):
        account=fixture.f.get_account(self.b,self.a,actor_user_id=self.uid)
        html,context=self.page('?month=2026-09&view=accounts')
        self.assertTrue(context['show_accounts'])
        self.assertIn('Kas &amp; Rekening',html)
        self.assertIn(account['name'],html)
        self.assertIn('Saldo tersedia',html)
        self.assertIn('Saldo awal',html)
        self.assertNotIn('id="finance-trend-data"',html)
        self.assertNotIn('Tanya Kilas Finance',html)

    def test_mixed_currency_income_is_combined_in_display_currency(self):
        usd=fixture.f.create_account(self.b,'USD Bank','BANK','USD',0,actor_user_id=self.uid)
        usd_cat=fixture.f.list_categories(self.b,'INCOME')[0]['id']
        fixture.f.create_transaction(self.b,'INCOME',100000,self.a,self.cat,
            '2026-09-03',description='IDR sale',actor_user_id=self.uid)
        fixture.f.create_transaction(self.b,'INCOME',1000,usd,usd_cat,
            '2026-09-04',currency='USD',description='USD sale',actor_user_id=self.uid)
        import finance_fx
        fx={'rates':{'IDR':'1','USD':'16000'},'date':'2026-09-21','source':'Test FX','stale':False}
        with patch.object(finance_fx,'snapshot',return_value=fx):
            html,context=self.page('?month=2026-09')
        self.assertEqual(context['period_income_display'],'Rp260.000')
        self.assertIn('Rp260.000',html)
        self.assertNotIn('Mata uang ditampilkan terpisah',html)

if __name__=='__main__': unittest.main()
