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

    def test_foreign_opening_balance_does_not_become_chart_income(self):
        fixture.f.create_account(self.b,'Dollar','BANK','USD',12000,actor_user_id=self.uid)
        import finance_fx
        with patch.object(finance_fx,'snapshot',return_value={'rates':{'IDR':'1'},'date':'','source':'unavailable','stale':True}):
            html, context=self.page()
        self.assertIn('US$120.00',html)
        self.assertEqual({r['currency'] for r in context['dashboard_trend']},{'IDR'})
        self.assertTrue(all(r['income_minor']==0 for r in context['dashboard_trend']))
        self.assertIn('Mata uang ditampilkan terpisah',html)

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

if __name__=='__main__': unittest.main()
