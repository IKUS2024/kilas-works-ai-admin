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
        self.assertEqual(context['balance_total_display'],'Rp1.200.000,00')
        self.assertEqual(context['period_income_display'],'Rp0,00')
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
        self.assertEqual(context['budget_total_display'],'Rp0,00')
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

    def test_accounts_view_uses_homebudget_overview_and_live_balance_report(self):
        account=fixture.f.get_account(self.b,self.a,actor_user_id=self.uid)
        html,context=self.page('?month=2026-09&view=accounts')
        self.assertTrue(context['show_accounts'])
        self.assertEqual(context['selected_account']['id'],self.a)
        self.assertIn('finance-account-hb-list',html)
        self.assertIn('Akun',html)
        self.assertNotIn('Pengaturan Finance',html)
        self.assertIn(account['name'],html)
        self.assertIn('Saldo tersedia',html)
        self.assertIn('Saldo awal',html)
        self.assertIn('Dana masuk',html)
        self.assertIn('Dana keluar',html)
        self.assertIn('Lihat Transaksi',html)
        self.assertIn('Edit Akun',html)
        self.assertNotIn('Import Mutasi',html)
        self.assertNotIn('/finance/bank/new',html)
        self.assertNotIn('id="finance-trend-data"',html)
        self.assertNotIn('Tanya Kilas Finance',html)

    def test_account_types_default_add_delete_and_assignment_are_consistent(self):
        html,_=self.page('?month=2026-09&view=accounts')
        for label in ('Credit','Debit','Piutang','Tabungan','E-wallet','Wallet'):
            self.assertIn(f'value="{label}"',html)
        self.assertIn('＋ Tambah / kelola tipe',html)

        branch_id=__import__('finance_branches').list_branches(self.b)[0]['id']
        endpoint=f'/business/{self.b}/finance/account-types'
        created=self.client.post(endpoint,data={
            'branch_id':str(branch_id),'action':'create','name':'Investasi',
        },headers={'X-Requested-With':'XMLHttpRequest','Accept':'application/json'})
        self.assertEqual(created.status_code,200)
        self.assertIn('Investasi',[row['name'] for row in created.get_json()['options']])

        removed=self.client.post(endpoint,data={
            'branch_id':str(branch_id),'action':'delete','name':'Credit',
        },headers={'X-Requested-With':'XMLHttpRequest','Accept':'application/json'})
        self.assertEqual(removed.status_code,200)
        self.assertNotIn('Credit',[row['name'] for row in removed.get_json()['options']])

        added=self.client.post(f'/business/{self.b}/finance/accounts',data={
            'branch_id':str(branch_id),'return_view':'accounts','name':'Broker',
            'account_type_name':'Investasi','currency':'IDR','opening_balance':'0',
        })
        self.assertEqual(added.status_code,303)
        account=next(row for row in fixture.f.list_accounts(
            self.b,actor_user_id=self.uid) if row['name']=='Broker')
        self.assertEqual(account['account_type_label'],'Investasi')
        self.assertEqual(account['account_type'],'OTHER')
        balance=next(row for row in fixture.f.get_account_balance_report(
            self.b,'2026-09-22',actor_user_id=self.uid) if row['id']==account['id'])
        self.assertEqual(balance['account_type_label'],'Investasi')

        html,_=self.page('?month=2026-09&view=accounts')
        self.assertIn('Investasi',html)
        self.assertNotIn('value="Credit"',html)

    def test_account_value_rows_edit_sources_not_calculated_total(self):
        expense=fixture.f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid)[0]['id']
        fixture.f.create_transaction(
            self.b,'INCOME',250000,self.a,self.cat,'2026-09-20',
            description='Masuk editable',actor_user_id=self.uid)
        fixture.f.create_transaction(
            self.b,'EXPENSE',50000,self.a,expense,'2026-09-21',
            description='Keluar editable',actor_user_id=self.uid)
        branch_id=__import__('finance_branches').list_branches(self.b)[0]['id']

        html,_=self.page(
            f'?month=2026-09&view=accounts&account_id={self.a}&branch_id={branch_id}')
        self.assertIn(f'/accounts/{self.a}/balance',html)
        self.assertIn('Saldo awal',html)
        self.assertIn('Saldo sekarang',html)
        self.assertIn('Dihitung otomatis',html)
        self.assertIn('Edit transaksi',html)
        self.assertIn('direction=INCOME',html)
        self.assertIn('direction=EXPENSE',html)
        self.assertNotIn('name="action" value="current"',html)
        self.assertNotIn('Sesuaikan saldo',html)

        response=self.client.post(
            f'/business/{self.b}/finance/accounts/{self.a}/balance',
            data={'branch_id':str(branch_id),'action':'opening','amount':'100000,50',
                  'display_currency':'IDR'})
        self.assertEqual(response.status_code,303)
        account=fixture.f.get_account(self.b,self.a,actor_user_id=self.uid)
        self.assertEqual(account['opening_balance_minor'],10000050)

        before=fixture.f.get_account(self.b,self.a,actor_user_id=self.uid)['opening_balance_minor']
        blocked=self.client.post(
            f'/business/{self.b}/finance/accounts/{self.a}/balance',
            data={'branch_id':str(branch_id),'action':'current','amount':'500000',
                  'display_currency':'IDR'})
        self.assertEqual(blocked.status_code,303)
        after=fixture.f.get_account(self.b,self.a,actor_user_id=self.uid)['opening_balance_minor']
        self.assertEqual(before,after)

    def test_idr_decimal_account_value_is_persisted_not_rounded_away(self):
        branch_id=__import__('finance_branches').list_branches(self.b)[0]['id']
        response=self.client.post(
            f'/business/{self.b}/finance/accounts/{self.a}/balance',
            data={'branch_id':str(branch_id),'action':'opening','amount':'1441000,25',
                  'display_currency':'IDR'})
        self.assertEqual(response.status_code,303)
        account=fixture.f.get_account(self.b,self.a,actor_user_id=self.uid)
        self.assertEqual(account['opening_balance_minor'],144100025)
        html,_=self.page(
            f'?view=accounts&account_id={self.a}&branch_id={branch_id}&display_currency=IDR')
        self.assertIn('Rp1.441.000,25',html)
        self.assertIn('value="1441000.25"',html)

    def test_voided_transaction_recalculates_account_and_available_total(self):
        branch_id=__import__('finance_branches').list_branches(self.b)[0]['id']
        expense_cat=fixture.f.list_categories(
            self.b,'EXPENSE',actor_user_id=self.uid)[0]['id']
        income_id=fixture.f.create_transaction(
            self.b,'INCOME',30000000,self.a,self.cat,'2026-09-20',
            description='Income live total',actor_user_id=self.uid)
        expense_id=fixture.f.create_transaction(
            self.b,'EXPENSE',5000000,self.a,expense_cat,'2026-09-21',
            description='Expense to delete',actor_user_id=self.uid)

        _,before=self.page(
            f'?view=accounts&account_id={self.a}&branch_id={branch_id}&display_currency=IDR')
        self.assertEqual(before['selected_account']['income_minor'],30000000)
        self.assertEqual(before['selected_account']['expense_minor'],5000000)
        self.assertEqual(before['selected_account']['balance_minor'],25000000)

        response=self.client.post(
            f'/business/{self.b}/finance/transactions/{expense_id}/void',
            data={'branch_id':str(branch_id)})
        self.assertEqual(response.status_code,303)
        self.assertEqual(
            fixture.f.get_transaction(
                self.b,expense_id,actor_user_id=self.uid)['status'],'VOID')

        _,after=self.page(
            f'?view=accounts&account_id={self.a}&branch_id={branch_id}&display_currency=IDR')
        self.assertEqual(after['selected_account']['income_minor'],30000000)
        self.assertEqual(after['selected_account']['expense_minor'],0)
        self.assertEqual(after['selected_account']['balance_minor'],30000000)
        total=next(row for row in after['balance_totals'] if row['currency']=='IDR')
        self.assertEqual(total['balance_minor'],30000000)

    def test_nonzero_account_cannot_be_deleted_and_inactive_never_counts_as_available(self):
        import db
        import finance_branches as branch_service
        branch_id=branch_service.list_branches(self.b)[0]['id']
        second=fixture.f.create_account(
            self.b,'Dana Cadangan','BANK','IDR',50000000,
            actor_user_id=self.uid)

        blocked=self.client.post(
            f'/business/{self.b}/finance/settings/account/{second}',
            data={'branch_id':str(branch_id),'action':'deactivate','name':'Dana Cadangan',
                  'return_view':'accounts','display_currency':'IDR'})
        self.assertEqual(blocked.status_code,303)
        self.assertTrue(fixture.f.get_account(
            self.b,second,actor_user_id=self.uid)['is_active'])

        fixture.f.update_account_opening_balance(
            self.b,second,0,actor_user_id=self.uid)
        removed=self.client.post(
            f'/business/{self.b}/finance/settings/account/{second}',
            data={'branch_id':str(branch_id),'action':'deactivate','name':'Dana Cadangan',
                  'return_view':'accounts','display_currency':'IDR'})
        self.assertEqual(removed.status_code,303)
        self.assertFalse(fixture.f.get_account(
            self.b,second,actor_user_id=self.uid)['is_active'])

        # Simulate a legacy archived account that still has a historical non-zero
        # stored opening balance. It must not leak into today's Saldo tersedia.
        db.execute(
            'UPDATE finance_accounts SET opening_balance_minor=? '
            'WHERE business_id=? AND id=?',
            (99000000,self.b,second))
        _,context=self.page(
            f'?view=accounts&branch_id={branch_id}&display_currency=IDR')
        self.assertTrue(all(row['id']!=second for row in context['account_balance_rows']))
        active_total=next(
            row for row in context['balance_totals'] if row['currency']=='IDR')
        active_ids={
            row['id'] for row in fixture.f.get_account_balance_report(
                self.b,'2026-09-22',actor_user_id=self.uid)
            if row['is_active']
        }
        expected=sum(
            row['balance_minor'] for row in fixture.f.get_account_balance_report(
                self.b,'2026-09-22',actor_user_id=self.uid)
            if row['id'] in active_ids and row['currency']=='IDR'
        )
        self.assertEqual(active_total['balance_minor'],expected)

    def test_account_transaction_drilldown_filters_to_selected_account(self):
        second=fixture.f.create_account(self.b,'BCA Kedua','BANK','IDR',0,actor_user_id=self.uid)
        expense_cat=fixture.f.list_categories(self.b,'EXPENSE')[0]['id']
        fixture.f.create_transaction(self.b,'EXPENSE',1111,self.a,expense_cat,
            '2026-09-05',description='Akun pertama only',actor_user_id=self.uid)
        fixture.f.create_transaction(self.b,'EXPENSE',2222,second,expense_cat,
            '2026-09-06',description='Akun kedua only',actor_user_id=self.uid)
        html,context=self.page(f'?period_mode=all&view=transactions&account_id={second}')
        self.assertEqual(context['transaction_account_id'],second)
        self.assertEqual(context['transaction_total'],1)
        self.assertIn('BCA Kedua',html)
        self.assertIn('Akun kedua only',html)
        self.assertNotIn('Akun pertama only',html)

    def test_money_inputs_accept_decimal_dot_comma_and_grouping(self):
        from routes_finance import currency_amount
        self.assertEqual(currency_amount('1250.50','USD'),125050)
        self.assertEqual(currency_amount('1250,50','USD'),125050)
        self.assertEqual(currency_amount('1.250,50','USD'),125050)
        self.assertEqual(currency_amount('1,250.50','USD'),125050)
        self.assertEqual(currency_amount('1 250,50','USD'),125050)
        self.assertEqual(currency_amount('1.000.000','IDR'),100000000)
        self.assertEqual(currency_amount('1250,50','IDR'),125050)
        self.assertEqual(currency_amount('1250.49','IDR'),125049)
        self.assertEqual(currency_amount('-12,50','USD',signed=True),-1250)

    def test_mixed_currency_income_is_combined_in_display_currency(self):
        usd=fixture.f.create_account(self.b,'USD Bank','BANK','USD',0,actor_user_id=self.uid)
        usd_cat=fixture.f.list_categories(self.b,'INCOME')[0]['id']
        fixture.f.create_transaction(self.b,'INCOME',10000000,self.a,self.cat,
            '2026-09-03',description='IDR sale',actor_user_id=self.uid)
        fixture.f.create_transaction(self.b,'INCOME',1000,usd,usd_cat,
            '2026-09-04',currency='USD',description='USD sale',actor_user_id=self.uid)
        import finance_fx
        fx={'rates':{'IDR':'1','USD':'16000'},'date':'2026-09-21','source':'Test FX','stale':False}
        with patch.object(finance_fx,'snapshot',return_value=fx):
            html,context=self.page('?month=2026-09')
        self.assertEqual(context['period_income_display'],'Rp260.000,00')
        self.assertIn('Rp260.000,00',html)
        self.assertNotIn('Mata uang ditampilkan terpisah',html)

    def test_monthly_budget_is_branch_scoped_and_updates_dashboard(self):
        expense_cat=fixture.f.list_categories(self.b,'EXPENSE')[0]['id']
        fixture.f.set_monthly_budget(self.b,'2026-09',expense_cat,50000000,'IDR',actor_user_id=self.uid)
        html,context=self.page('?month=2026-09')
        self.assertEqual(context['budget_total_display'],'Rp500.000,00')
        self.assertIn('Rp500.000,00',html)
        rows=fixture.f.list_monthly_budgets(self.b,'2026-09',actor_user_id=self.uid)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['category_id'],expense_cat)

    def test_default_expense_categories_use_requested_indonesian_set(self):
        names=[row['name'] for row in fixture.f.list_categories(
            self.b,'EXPENSE',actor_user_id=self.uid)]
        self.assertEqual(names,[
            'Biaya Sewa','Utilitas','Makanan & Belanja Harian','Perlengkapan',
            'Transportasi','Asuransi','Biaya Tak Terduga',
        ])
        html,_=self.page('?month=2026-09')
        for name in names:
            self.assertIn(name,html)
        self.assertNotIn('Produksi / Vendor',html)
        self.assertNotIn('Gaji / Freelancer',html)
        self.assertNotIn('Marketing / Ads',html)

    def test_utilitas_shows_connected_subcategories_and_posts_child_category(self):
        html,_=self.page('?month=2026-09')
        self.assertIn('data-subcategory-field',html)
        self.assertIn('>Subkategori',html)
        for name in ('Listrik','Air','Internet','Telepon','Gas','Laundry','Sampah / Kebersihan'):
            self.assertIn(name,html)

        utility=next(row for row in fixture.f.list_categories(
            self.b,'EXPENSE',actor_user_id=self.uid) if row['name']=='Utilitas')
        electricity=next(row for row in fixture.f.list_category_children(
            self.b,utility['id'],actor_user_id=self.uid) if row['name']=='Listrik')
        branch_id=__import__('finance_branches').list_branches(self.b)[0]['id']
        response=self.client.post(f'/business/{self.b}/finance/transactions',data={
            'branch_id':str(branch_id),'direction':'EXPENSE','account_id':str(self.a),
            'amount':'50000','occurred_on':'2026-09-22','category_id':str(utility['id']),
            'subcategory_id':str(electricity['id']),'description':'Tagihan listrik',
        })
        self.assertEqual(response.status_code,303)
        transaction=fixture.f.list_transactions(self.b)[0]
        self.assertEqual(transaction['category_id'],electricity['id'])

        budget=self.client.get(
            f'/business/{self.b}/finance/budget?branch_id={branch_id}&month=2026-09')
        self.assertEqual(budget.status_code,200)
        self.assertNotIn('Rincian Utilitas',budget.text)
        self.assertIn('Utilitas',budget.text)
        self.assertIn('Rp50.000,00',budget.text)

    def test_reports_support_all_time_and_custom_date_ranges(self):
        branch_id=__import__('finance_branches').list_branches(self.b)[0]['id']
        fixture.f.create_transaction(
            self.b,'INCOME',10000000,self.a,self.cat,'2025-01-15',
            description='Old all-time income',actor_user_id=self.uid)
        fixture.f.create_transaction(
            self.b,'INCOME',20000000,self.a,self.cat,'2026-09-10',
            description='Current income',actor_user_id=self.uid)

        all_time=self.client.get(
            f'/business/{self.b}/finance/reports?branch_id={branch_id}'
            '&section=summary&preset=all')
        self.assertEqual(all_time.status_code,200)
        self.assertIn('Semua waktu',all_time.text)
        self.assertIn('2025-01-15',all_time.text)
        self.assertIn('2026-09-22',all_time.text)
        self.assertIn('Rp300.000,00',all_time.text)

        custom=self.client.get(
            f'/business/{self.b}/finance/reports?branch_id={branch_id}'
            '&section=summary&preset=custom&start=2026-09-01&end=2026-09-22'
            '&as_of=2026-09-22')
        self.assertEqual(custom.status_code,200)
        self.assertIn('Tanggal khusus',custom.text)
        self.assertIn('2026-09-01',custom.text)
        self.assertIn('2026-09-22',custom.text)
        self.assertIn('Rp200.000,00',custom.text)
        self.assertNotIn('Rp300.000,00',custom.text)

        for label in ('Hari ini','Bulan ini','Bulan lalu','3 bulan','6 bulan',
                      'Tahun ini','Semua waktu','Tanggal khusus'):
            self.assertIn(label,custom.text)

    def test_reports_are_one_complete_dashboard_aligned_report(self):
        branch_id=__import__('finance_branches').list_branches(self.b)[0]['id']
        expense_cat=fixture.f.list_categories(
            self.b,'EXPENSE',actor_user_id=self.uid)[0]['id']
        fixture.f.create_transaction(
            self.b,'INCOME',15000000,self.a,self.cat,'2026-09-10',
            description='Report income',actor_user_id=self.uid)
        fixture.f.create_transaction(
            self.b,'EXPENSE',2500000,self.a,expense_cat,'2026-09-11',
            counterparty_name='Vendor Report',description='Report expense',
            actor_user_id=self.uid)
        fixture.f.set_monthly_budget(
            self.b,'2026-09',expense_cat,5000000,'IDR',
            actor_user_id=self.uid)

        response=self.client.get(
            f'/business/{self.b}/finance/reports?branch_id={branch_id}'
            '&preset=month')
        self.assertEqual(response.status_code,200)
        html=response.text
        self.assertNotIn('aria-label="Jenis laporan"',html)
        self.assertNotIn('Kas &amp; Rekening',html)
        self.assertNotIn('Acuan piutang',html)
        for heading in ('Ringkasan','Pemasukan','Pengeluaran','Anggaran',
                        'Tagihan','Akun','Penerima'):
            self.assertIn(f'<h2>{heading}</h2>',html)
        self.assertIn('Vendor Report',html)
        self.assertIn('Rp50.000,00',html)
        self.assertIn('Rp150.000,00',html)
        self.assertIn('Rp25.000,00',html)

    def test_finance_subpages_do_not_repeat_branch_selector_card(self):
        branch_id=__import__('finance_branches').list_branches(self.b)[0]['id']
        reports=self.client.get(
            f'/business/{self.b}/finance/reports?branch_id={branch_id}&preset=month')
        self.assertEqual(reports.status_code,200)
        self.assertNotIn('finance-scope-card',reports.text)
        self.assertNotIn('Cabang aktif:',reports.text)

        operations=self.client.get(
            f'/business/{self.b}/finance/operations?branch_id={branch_id}')
        self.assertEqual(operations.status_code,200)
        self.assertNotIn('finance-scope-card',operations.text)
        self.assertNotIn('Cabang aktif:',operations.text)

    def test_business_home_surfaces_invoice_status_without_mixing_with_personal(self):
        invoice=fixture.f.create_finance_invoice(
            self.b,self.c,'2026-09-22','2026-09-30',
            [dict(description='Jasa',quantity=1,unit_price_minor=200000000)],
            actor_user_id=self.uid)
        fixture.f.issue_finance_invoice(
            self.b,invoice,actor_user_id=self.uid)
        paid=fixture.f.create_finance_invoice(
            self.b,self.c,'2026-09-22','2026-09-30',
            [dict(description='Lunas',quantity=1,unit_price_minor=100000000)],
            actor_user_id=self.uid)
        fixture.f.issue_finance_invoice(
            self.b,paid,actor_user_id=self.uid)
        fixture.f.record_invoice_payment(
            self.b,paid,100000000,'2026-09-22',self.a,self.cat,
            actor_user_id=self.uid,idempotency_key='dashboard-invoice-paid-0001')

        html,context=self.page('?month=2026-09')
        self.assertIn('>Invoice</span>',html)
        self.assertIn('1 <em>belum bayar</em>',html)
        self.assertIn('1 lunas',html)
        self.assertIn('otomatis masuk Piutang',html)
        self.assertEqual(context['invoice_open_count'],1)
        self.assertEqual(context['invoice_paid_count'],1)

    def test_finance_global_navigation_has_dashboard_and_exit(self):
        html,_=self.page('?month=2026-09')
        self.assertIn('finance-dashboard-link',html)
        self.assertIn('>Dashboard</a>',html)
        self.assertIn('>Keluar Finance</a>',html)

    def test_workspace_chooser_has_no_dashboard_action(self):
        response=self.client.get(f'/business/{self.b}/finance/workspaces')
        self.assertEqual(response.status_code,200)
        self.assertNotIn('finance-dashboard-link',response.text)
        self.assertNotIn('>Dashboard</a>',response.text)
        self.assertIn('>Keluar Finance</a>',response.text)

    def test_dashboard_action_stays_inside_current_business_or_personal_workspace(self):
        import finance_branches
        business_branch=finance_branches.list_branches(
            self.b,self.uid,workspace_type='BUSINESS')[0]['id']
        business=self.client.get(
            f'/business/{self.b}/finance?branch_id={business_branch}&month=2026-09')
        self.assertEqual(business.status_code,200)
        self.assertIn(
            f'/business/{self.b}/finance?branch_id={business_branch}',
            business.text)

        personal_branch=finance_branches.ensure_personal(self.b,self.uid)
        personal=self.client.get(
            f'/business/{self.b}/finance?branch_id={personal_branch}&month=2026-09')
        self.assertEqual(personal.status_code,200)
        self.assertIn('finance-dashboard-link',personal.text)
        self.assertIn(
            f'/business/{self.b}/finance?branch_id={personal_branch}',
            personal.text)
        self.assertNotIn(
            f'class="finance-exit-link finance-dashboard-link" href="/business/{self.b}/finance?branch_id={business_branch}"',
            personal.text)

    def test_home_uses_translated_homebudget_primary_sections(self):
        html,context=self.page('?month=2026-09')
        for label in ('Pengeluaran','Tagihan','Pemasukan','Anggaran','Akun','Penerima'):
            self.assertIn(label,html)
        self.assertNotIn('Pengaturan Finance',html)
        self.assertNotIn('Customer</span>',html)
        self.assertNotIn('Pengeluaran dari anggaran',html)
        self.assertIn('Tanya Kilas Finance',html)

    def test_finance_pages_hide_client_hub_topbar_and_offer_dashboard_back(self):
        html,_=self.page('?month=2026-09')
        self.assertNotIn('Kilas<span>Works</span> Client Hub',html)
        self.assertNotIn('finance-context-bar',html)
        self.assertNotIn('class="topbar-active" aria-current="page"',html)
        self.assertIn('Keluar Finance',html)
        self.assertIn('finance-exit-bar',html)

    def test_transaction_form_can_add_income_and_expense_categories_in_place(self):
        html,_=self.page('?month=2026-09')
        self.assertIn('data-category-quick-add',html)
        self.assertIn('data-category-placeholder selected disabled>Pilih kategori</option>',html)
        self.assertIn('data-subcategory-field hidden',html)
        self.assertIn('data-finance-open="category-dialog"',html)
        self.assertIn('data-category-manager-launch',html)
        self.assertIn('＋ Tambah / kelola kategori',html)
        self.assertNotIn('data-category-add-panel',html)

        branch_id=__import__('finance_branches').list_branches(self.b)[0]['id']
        endpoint=f'/business/{self.b}/finance/categories'
        for direction,name in (('INCOME','Affiliate Baru'),('EXPENSE','Sewa Studio Baru')):
            response=self.client.post(endpoint,data={
                'branch_id':str(branch_id),'direction':direction,'name':name,
            },headers={'X-Requested-With':'XMLHttpRequest','Accept':'application/json'})
            self.assertEqual(response.status_code,201)
            payload=response.get_json()
            self.assertEqual(payload['category']['name'],name)
            self.assertEqual(payload['category']['direction'],direction)
            rows=fixture.f.list_categories(self.b,direction,actor_user_id=self.uid)
            self.assertTrue(any(row['id']==payload['category']['id'] and row['name']==name for row in rows))

            deleted=self.client.post(endpoint,data={
                'branch_id':str(branch_id),'direction':direction,'action':'delete',
                'category_id':str(payload['category']['id']),
            },headers={'X-Requested-With':'XMLHttpRequest','Accept':'application/json'})
            self.assertEqual(deleted.status_code,200)
            self.assertNotIn(name,[row['name'] for row in deleted.get_json()['options']])

    def test_business_income_catalog_is_clean_and_has_useful_top_level_choices(self):
        html,_=self.page('?month=2026-09')
        for name in (
            'Penjualan / Jasa',
            'Langganan / Retainer',
            'Komisi &amp; Affiliate',
            'Sponsor / Kerja Sama',
            'Sewa / Rental',
            'Royalti / Lisensi',
            'Bunga / Cashback',
        ):
            self.assertIn(name,html)
        self.assertNotIn('>Lainnya</option>',html)
        self.assertNotIn('>Pendapatan Lain</option>',html)

        rows=fixture.f.list_categories(
            self.b,'INCOME',include_children=True,actor_user_id=self.uid)
        names={row['name'] for row in rows if not row.get('parent_category_id')}
        for name in (
            'Penjualan / Jasa','Langganan / Retainer','Komisi & Affiliate',
            'Sponsor / Kerja Sama','Sewa / Rental','Royalti / Lisensi',
            'Bunga / Cashback',
        ):
            self.assertIn(name,names)

    def test_category_manager_can_add_edit_and_delete_subcategories(self):
        html,_=self.page('?month=2026-09')
        self.assertIn('data-category-manager-root',html)
        self.assertIn('data-category-direction-tab="INCOME"',html)
        self.assertIn('data-category-direction-tab="EXPENSE"',html)
        self.assertIn('data-category-create-popup',html)
        self.assertIn('data-category-editor',html)
        self.assertIn('data-category-edit-popup',html)
        self.assertIn('data-category-add-child-popup',html)
        self.assertIn('finance-category-tree',html)
        self.assertIn('＋ Tambah Kategori',html)
        self.assertNotIn('＋ Tambah Kategori / Subkategori',html)
        self.assertIn('data-category-editor-child-choice',html)
        self.assertIn('name="add_subcategories"',html)
        self.assertIn('name="subcategory_name"',html)
        self.assertIn('＋ Tambah subkategori lagi',html)
        self.assertIn('＋ Subkategori',html)
        self.assertIn('>Edit</button>',html)
        self.assertIn('>Hapus</button>',html)
        self.assertNotIn('>Lainnya</strong>',html)
        self.assertNotIn('Pendapatan Lain',html)
        for direction in ('INCOME','EXPENSE'):
            rows=fixture.f.list_categories(
                self.b,direction,include_children=True,actor_user_id=self.uid)
            self.assertTrue(rows)

        branch_id=__import__('finance_branches').list_branches(self.b)[0]['id']
        endpoint=f'/business/{self.b}/finance/categories'
        headers={'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}

        parent_response=self.client.post(endpoint,data={
            'branch_id':str(branch_id),'direction':'EXPENSE',
            'action':'create','name':'Operasional Khusus',
            'add_subcategories':'1',
            'subcategory_name':['Bensin Genset','Oli Genset'],
        },headers=headers)
        self.assertEqual(parent_response.status_code,201)
        parent_payload=parent_response.get_json()
        parent=parent_payload['category']
        self.assertIsNone(parent['parent_category_id'])
        self.assertEqual(
            {row['name'] for row in parent_payload['children']},
            {'Bensin Genset','Oli Genset'})
        child=next(
            row for row in parent_payload['children']
            if row['name']=='Bensin Genset')
        self.assertEqual(child['parent_category_id'],parent['id'])
        self.assertEqual(child['parent_name'],'Operasional Khusus')

        edited=self.client.post(endpoint,data={
            'branch_id':str(branch_id),'direction':'EXPENSE',
            'action':'edit','category_id':str(child['id']),
            'name':'BBM Genset',
        },headers=headers)
        self.assertEqual(edited.status_code,200)
        edited_payload=edited.get_json()
        self.assertEqual(edited_payload['category']['name'],'BBM Genset')
        self.assertEqual(edited_payload['category']['parent_category_id'],parent['id'])

        deleted_parent=self.client.post(endpoint,data={
            'branch_id':str(branch_id),'direction':'EXPENSE',
            'action':'delete','category_id':str(parent['id']),
        },headers=headers)
        self.assertEqual(deleted_parent.status_code,200)
        remaining=deleted_parent.get_json()['options']
        self.assertNotIn('Operasional Khusus',[row['name'] for row in remaining])
        self.assertNotIn('BBM Genset',[row['name'] for row in remaining])
        self.assertNotIn('Oli Genset',[row['name'] for row in remaining])

        active=fixture.f.list_categories(
            self.b,'EXPENSE',include_children=True,actor_user_id=self.uid)
        self.assertNotIn('Operasional Khusus',[row['name'] for row in active])
        self.assertNotIn('BBM Genset',[row['name'] for row in active])
        self.assertNotIn('Oli Genset',[row['name'] for row in active])

    def test_retired_lainnya_categories_cannot_return_to_active_ui(self):
        branch_id=__import__('finance_branches').list_branches(self.b)[0]['id']
        endpoint=f'/business/{self.b}/finance/categories'
        headers={'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}
        for direction,name in (
            ('INCOME','Pendapatan Lain'),
            ('EXPENSE','Pengeluaran Lain'),
            ('EXPENSE','Lainnya'),
        ):
            response=self.client.post(endpoint,data={
                'branch_id':str(branch_id),'direction':direction,
                'action':'create','name':name,
            },headers=headers)
            self.assertEqual(response.status_code,400)
            self.assertIn('tidak digunakan lagi',response.get_json()['error'])

        for direction in ('INCOME','EXPENSE'):
            active=fixture.f.list_categories(
                self.b,direction,include_children=True,actor_user_id=self.uid)
            self.assertFalse(any(
                row['name'] in ('Pendapatan Lain','Pengeluaran Lain','Lainnya')
                or row.get('parent_name') in ('Pendapatan Lain','Pengeluaran Lain','Lainnya')
                for row in active))

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

    def test_penerima_can_be_added_before_any_expense_like_homebudget(self):
        branch_id=__import__('finance_branches').list_branches(self.b)[0]['id']
        response=self.client.post(f'/business/{self.b}/finance/payees',data={
            'branch_id':str(branch_id),'display_currency':'IDR','name':'Vendor Baru'})
        self.assertEqual(response.status_code,303)
        self.assertIn('/finance/payees',response.location)
        self.assertEqual(fixture.f.list_transactions(self.b),[])

        rows=fixture.f.list_payee_summaries(self.b,actor_user_id=self.uid)
        vendor=next(row for row in rows if row['name']=='Vendor Baru')
        self.assertEqual(vendor['transaction_count'],0)
        self.assertEqual(vendor['total_minor'],0)
        self.assertIsNone(vendor['last_paid_on'])

        page=self.client.get(f'/business/{self.b}/finance/payees?branch_id={branch_id}')
        self.assertEqual(page.status_code,200)
        self.assertIn('＋ Tambah Penerima',page.text)
        self.assertIn('Vendor Baru',page.text)
        self.assertIn('belum pernah dibayar',page.text)

    def test_penerima_edit_and_delete_are_safe_global_actions(self):
        branch_id=__import__('finance_branches').list_branches(self.b)[0]['id']
        expense_cat=fixture.f.list_categories(self.b,'EXPENSE')[0]['id']
        fixture.f.create_transaction(
            self.b,'EXPENSE',125000,self.a,expense_cat,'2026-09-12',
            counterparty_name='Vendor Lama',description='Biji kopi',
            actor_user_id=self.uid)
        payee=next(p for p in fixture.f.list_payees(
            self.b,actor_user_id=self.uid) if p['name']=='Vendor Lama')

        page=self.client.get(f'/business/{self.b}/finance/payees?branch_id={branch_id}')
        self.assertEqual(page.status_code,200)
        self.assertIn('✏️ Edit',page.text)
        self.assertIn('🗑️ Hapus',page.text)

        edited=self.client.post(
            f'/business/{self.b}/finance/payees/{payee["id"]}/edit',data={
                'branch_id':str(branch_id),'display_currency':'IDR','page':'1',
                'name':'Vendor Baru'})
        self.assertEqual(edited.status_code,303)
        transaction=fixture.f.list_transactions(self.b,actor_user_id=self.uid)[0]
        self.assertEqual(transaction['counterparty_name'],'Vendor Baru')
        self.assertIn('Vendor Baru',[p['name'] for p in fixture.f.list_payees(
            self.b,actor_user_id=self.uid)])

        deleted=self.client.post(
            f'/business/{self.b}/finance/payees/{payee["id"]}/delete',data={
                'branch_id':str(branch_id),'display_currency':'IDR','page':'1'})
        self.assertEqual(deleted.status_code,303)
        self.assertNotIn('Vendor Baru',[p['name'] for p in fixture.f.list_payees(
            self.b,actor_user_id=self.uid)])
        self.assertNotIn('Vendor Baru',[p['name'] for p in fixture.f.list_payee_summaries(
            self.b,actor_user_id=self.uid)])
        transaction=fixture.f.list_transactions(self.b,actor_user_id=self.uid)[0]
        self.assertEqual(transaction['status'],'POSTED')
        self.assertEqual(transaction['amount_minor'],125000)

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
        self.assertIn('✏️ Simpan Edit',html)
        self.assertIn('🗑️ Hapus Kategori',html)
        self.assertIn('Ketuk kategori untuk mengatur anggaran, mengedit, atau menghapus kategori.',html)
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

        deleted=self.client.post(budget_url,data={
            'branch_id':str(branch_id),'month':'2026-09','display_currency':'IDR',
            'action':'delete_category','category_id':str(category['id'])})
        self.assertEqual(deleted.status_code,303)
        active_names=[c['name'] for c in fixture.f.list_categories(
            self.b,'EXPENSE',actor_user_id=self.uid)]
        self.assertNotIn('Studio / Lokasi',active_names)
        archived=next(c for c in fixture.f.list_categories(
            self.b,'EXPENSE',include_inactive=True,actor_user_id=self.uid)
            if c['id']==category['id'])
        self.assertFalse(archived['is_active'])

        income=fixture.f.list_categories(self.b,'INCOME',actor_user_id=self.uid)[0]
        blocked=self.client.post(budget_url,data={
            'branch_id':str(branch_id),'month':'2026-09','display_currency':'IDR',
            'action':'rename_category','category_id':str(income['id']),'name':'Jangan Ubah'})
        self.assertEqual(blocked.status_code,303)
        income_names=[c['name'] for c in fixture.f.list_categories(self.b,'INCOME',actor_user_id=self.uid)]
        self.assertNotIn('Jangan Ubah',income_names)

    def test_bills_page_uses_homebudget_calendar_list_and_recurring_views(self):
        expense_cat=fixture.f.list_categories(self.b,'EXPENSE')[0]['id']
        fixture.f.create_recurring_expense(
            self.b,'Internet',275000,self.a,expense_cat,'MONTHLY','2026-09-10',
            counterparty_name='Provider Net',actor_user_id=self.uid)
        response=self.client.get(f'/business/{self.b}/finance/operations?month=2026-09')
        self.assertEqual(response.status_code,200)
        html=response.text
        for token in ('finance-bills-calendar','September 2026','Tambah Tagihan','Kalender','Daftar','Rutin','Internet','Provider Net'):
            self.assertIn(token,html)
        self.assertIn('name="paid_on"',html)
        self.assertIn('Tanggal ini yang dipakai untuk Pengeluaran, saldo akun, laporan, dan pemakaian Anggaran.',html)
        self.assertNotIn('Tagihan &amp; Rutin',html)
        self.assertNotIn('fin-tool-grid',html)

        future=self.client.get(f'/business/{self.b}/finance/operations?month=2026-10')
        self.assertEqual(future.status_code,200)
        self.assertIn('Oktober 2026',future.text)
        self.assertIn('Internet',future.text)

    def test_bill_payment_uses_real_payment_date_subcategory_and_updates_actuals_once(self):
        branch_id=__import__('finance_branches').list_branches(self.b)[0]['id']
        utility=next(row for row in fixture.f.list_categories(
            self.b,'EXPENSE',actor_user_id=self.uid) if row['name']=='Utilitas')
        internet=next(row for row in fixture.f.list_category_children(
            self.b,utility['id'],actor_user_id=self.uid) if row['name']=='Internet')

        # A parent with subcategories must not silently accept a parent-only bill.
        blocked=self.client.post(f'/business/{self.b}/finance/recurring',data={
            'branch_id':str(branch_id),'month':'2026-08','name':'Internet Tanpa Subkategori',
            'account_id':str(self.a),'amount':'500000','category_id':str(utility['id']),
            'next_due_on':'2026-08-31','cadence':'ONCE'})
        self.assertEqual(blocked.status_code,303)
        self.assertEqual(fixture.f.list_recurring_expenses(self.b),[])

        created=self.client.post(f'/business/{self.b}/finance/recurring',data={
            'branch_id':str(branch_id),'month':'2026-08','name':'Internet Kantor',
            'account_id':str(self.a),'amount':'500000','category_id':str(utility['id']),
            'subcategory_id':str(internet['id']),'next_due_on':'2026-08-31',
            'cadence':'ONCE','counterparty_name':'Provider Net'})
        self.assertEqual(created.status_code,303)
        rule=next(row for row in fixture.f.list_recurring_expenses(
            self.b,include_inactive=True,actor_user_id=self.uid) if row['name']=='Internet Kantor')
        self.assertEqual(rule['category_id'],internet['id'])
        self.assertEqual(fixture.f.list_transactions(self.b),[])

        # Budget is planning only. The unpaid August due date changes no actual cash figures.
        fixture.f.set_monthly_budget(
            self.b,'2026-09',utility['id'],1000000,'IDR',actor_user_id=self.uid)
        self.assertEqual(
            fixture.f.get_finance_summary(self.b,'2026-08-01','2026-08-31')['total_expense_minor'],0)

        payment={
            'branch_id':str(branch_id),'month':'2026-08','day':'2026-08-31','view':'calendar',
            'occurrence':f"{rule['id']}:2026-08-31",'paid_on':'2026-09-22'}
        first=self.client.post(f'/business/{self.b}/finance/recurring/process',data=payment)
        second=self.client.post(f'/business/{self.b}/finance/recurring/process',data=payment)
        self.assertEqual(first.status_code,303)
        self.assertEqual(second.status_code,303)

        transactions=fixture.f.list_transactions(self.b,actor_user_id=self.uid)
        self.assertEqual(len(transactions),1)
        transaction=transactions[0]
        self.assertEqual(transaction['source_type'],'FINANCE_RECURRING_EXPENSE')
        self.assertEqual(transaction['occurred_on'],'2026-09-22')
        self.assertEqual(transaction['category_id'],internet['id'])
        self.assertEqual(
            fixture.f.get_finance_summary(self.b,'2026-08-01','2026-08-31')['total_expense_minor'],0)
        self.assertEqual(
            fixture.f.get_finance_summary(self.b,'2026-09-01','2026-09-30')['total_expense_minor'],500000)

        balances=fixture.f.get_account_balance_report(self.b,'2026-09-22',self.uid)
        account=next(row for row in balances if row['id']==self.a)
        self.assertEqual(account['balance_minor'],-500000)

        budget=self.client.get(
            f'/business/{self.b}/finance/budget?branch_id={branch_id}&month=2026-09')
        self.assertEqual(budget.status_code,200)
        self.assertIn('Rp500.000,00',budget.text)
        self.assertIn('Rp1.000.000,00',budget.text)

    def test_bills_recurring_rules_have_edit_and_safe_delete(self):
        branch_id=__import__('finance_branches').list_branches(self.b)[0]['id']
        expense_cat=fixture.f.list_categories(self.b,'EXPENSE')[0]['id']
        rule_id=fixture.f.create_recurring_expense(
            self.b,'Internet Lama',275000,self.a,expense_cat,'MONTHLY','2026-09-10',
            counterparty_name='Provider Lama',actor_user_id=self.uid)

        page=self.client.get(
            f'/business/{self.b}/finance/operations?branch_id={branch_id}&month=2026-09&view=recurring')
        self.assertEqual(page.status_code,200)
        self.assertIn('✏️ Edit',page.text)
        self.assertIn('🗑️ Hapus',page.text)
        self.assertIn(f'id="bill-edit-{rule_id}"',page.text)

        edited=self.client.post(
            f'/business/{self.b}/finance/recurring/{rule_id}/edit',data={
                'branch_id':str(branch_id),'month':'2026-09','display_currency':'IDR',
                'name':'Internet Baru','account_id':str(self.a),'amount':'325000',
                'category_id':str(expense_cat),'next_due_on':'2026-09-17',
                'cadence':'WEEKLY','counterparty_name':'Provider Baru',
                'description':'Paket kantor'})
        self.assertEqual(edited.status_code,303)
        rule=fixture.f.get_recurring_expense(self.b,rule_id,self.uid)
        self.assertEqual(rule['name'],'Internet Baru')
        self.assertEqual(rule['amount_minor'],325000)
        self.assertEqual(rule['cadence'],'WEEKLY')
        self.assertEqual(rule['next_due_on'],'2026-09-17')
        self.assertEqual(rule['counterparty_name'],'Provider Baru')
        self.assertEqual(fixture.f.list_transactions(self.b),[])

        deleted=self.client.post(
            f'/business/{self.b}/finance/recurring/{rule_id}/deactivate',data={
                'branch_id':str(branch_id),'month':'2026-09','display_currency':'IDR'})
        self.assertEqual(deleted.status_code,303)
        rule=fixture.f.get_recurring_expense(self.b,rule_id,self.uid)
        self.assertFalse(rule['is_active'])
        self.assertEqual(fixture.f.list_transactions(self.b),[])

    def test_bills_add_once_maps_to_single_due_rule(self):
        branch_id=__import__('finance_branches').list_branches(self.b)[0]['id']
        expense_cat=fixture.f.list_categories(self.b,'EXPENSE')[0]['id']
        response=self.client.post(f'/business/{self.b}/finance/recurring',data={
            'branch_id':str(branch_id),'month':'2026-09','name':'Sewa Studio',
            'account_id':str(self.a),'amount':'450000','category_id':str(expense_cat),
            'next_due_on':'2026-09-25','cadence':'ONCE','counterparty_name':'Studio A'})
        self.assertEqual(response.status_code,303)
        rules=fixture.f.list_recurring_expenses(self.b,include_inactive=True,actor_user_id=self.uid)
        rule=next(row for row in rules if row['name']=='Sewa Studio')
        self.assertEqual(rule['cadence'],'MONTHLY')
        self.assertEqual(rule['next_due_on'],'2026-09-25')
        self.assertEqual(rule['end_on'],'2026-09-25')

if __name__=='__main__': unittest.main()
