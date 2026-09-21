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
        self.assertNotIn('PRIVATE OTHER BUSINESS',html)
        self.assertNotIn('Aktivitas terbaru',html)
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

    def test_empty_dashboard_shows_real_zero_budget_and_omits_attention(self):
        html,context=self.page()
        self.assertIn('Anggaran',html)
        self.assertEqual(context['budget_total_display'],'Rp0')
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
        self.assertIn('Akun',html)
        self.assertNotIn('Pengaturan Finance',html)
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

    def test_monthly_budget_is_branch_scoped_and_updates_dashboard(self):
        expense_cat=fixture.f.list_categories(self.b,'EXPENSE')[0]['id']
        fixture.f.set_monthly_budget(self.b,'2026-09',expense_cat,500000,'IDR',actor_user_id=self.uid)
        html,context=self.page('?month=2026-09')
        self.assertEqual(context['budget_total_display'],'Rp500.000')
        self.assertIn('Rp500.000',html)
        rows=fixture.f.list_monthly_budgets(self.b,'2026-09',actor_user_id=self.uid)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['category_id'],expense_cat)

    def test_home_uses_translated_homebudget_primary_sections(self):
        html,context=self.page('?month=2026-09')
        for label in ('Pengeluaran','Tagihan','Pemasukan','Anggaran','Akun','Penerima'):
            self.assertIn(label,html)
        self.assertNotIn('Pengaturan Finance',html)
        self.assertNotIn('Customer</span>',html)
        self.assertIn('Pengeluaran dari anggaran',html)
        self.assertIn('Tanya Kilas Finance',html)

    def test_penerima_is_derived_from_expense_counterparty(self):
        expense_cat=fixture.f.list_categories(self.b,'EXPENSE')[0]['id']
        fixture.f.create_transaction(self.b,'EXPENSE',125000,self.a,expense_cat,
            '2026-09-12',counterparty_name='Vendor Kopi',description='Biji kopi',
            actor_user_id=self.uid)
        html,context=self.page('?month=2026-09')
        self.assertEqual(context['payee_count'],1)
        page=self.client.get(f'/business/{self.b}/finance/payees')
        self.assertEqual(page.status_code,200)
        self.assertIn('Penerima',page.text)
        self.assertIn('Vendor Kopi',page.text)

    def test_budget_page_uses_compact_homebudget_style_rows(self):
        expense_cat=fixture.f.list_categories(self.b,'EXPENSE')[0]['id']
        fixture.f.set_monthly_budget(self.b,'2026-09',expense_cat,500000,'IDR',actor_user_id=self.uid)
        response=self.client.get(f'/business/{self.b}/finance/budget?month=2026-09')
        self.assertEqual(response.status_code,200)
        html=response.text
        self.assertIn('finance-budget-category-row',html)
        self.assertIn('Bulanan',html)
        self.assertIn('Terpakai',html)
        self.assertIn('Tersedia',html)
        self.assertIn('Simpan Anggaran',html)
        self.assertIn('＋ Tambah Kategori',html)
        self.assertIn('Simpan Nama',html)
        self.assertIn('Ketuk kategori untuk mengatur anggaran atau mengubah namanya.',html)
        self.assertNotIn('finance-budget-form',html)

    def test_budget_page_adds_and_renames_expense_categories_in_place(self):
        branch_id=__import__('finance_branches').list_branches(self.b)[0]['id']
        budget_url=f'/business/{self.b}/finance/budget'
        created=self.client.post(budget_url,data={
            'branch_id':str(branch_id),'month':'2026-09','display_currency':'IDR',
            'action':'create_category','name':'Sewa Studio'})
        self.assertEqual(created.status_code,303)
        self.assertIn('/finance/budget',created.location)
        categories=fixture.f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid)
        category=next(c for c in categories if c['name']=='Sewa Studio')

        renamed=self.client.post(budget_url,data={
            'branch_id':str(branch_id),'month':'2026-09','display_currency':'IDR',
            'action':'rename_category','category_id':str(category['id']),'name':'Studio / Lokasi'})
        self.assertEqual(renamed.status_code,303)
        names=[c['name'] for c in fixture.f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid)]
        self.assertIn('Studio / Lokasi',names)
        self.assertNotIn('Sewa Studio',names)

        income=fixture.f.list_categories(self.b,'INCOME',actor_user_id=self.uid)[0]
        blocked=self.client.post(budget_url,data={
            'branch_id':str(branch_id),'month':'2026-09','display_currency':'IDR',
            'action':'rename_category','category_id':str(income['id']),'name':'Jangan Ubah'})
        self.assertEqual(blocked.status_code,303)
        income_names=[c['name'] for c in fixture.f.list_categories(self.b,'INCOME',actor_user_id=self.uid)]
        self.assertNotIn('Jangan Ubah',income_names)

if __name__=='__main__': unittest.main()
