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
        self.assertIn('Rincian Utilitas',budget.text)
        self.assertIn('Listrik',budget.text)
        self.assertIn('Rp50.000',budget.text)

    def test_home_uses_translated_homebudget_primary_sections(self):
        html,context=self.page('?month=2026-09')
        for label in ('Pengeluaran','Tagihan','Pemasukan','Anggaran','Akun','Penerima'):
            self.assertIn(label,html)
        self.assertNotIn('Pengaturan Finance',html)
        self.assertNotIn('Customer</span>',html)
        self.assertNotIn('Pengeluaran dari anggaran',html)
        self.assertIn('Tanya Kilas Finance',html)

    def test_finance_pages_have_distinct_global_header_context(self):
        html,_=self.page('?month=2026-09')
        self.assertIn('finance-context-bar',html)
        self.assertIn('finance-brand-label">Finance</strong>',html)
        self.assertIn('class="topbar-active" aria-current="page"',html)
        self.assertIn('>Finance</a>',html)

    def test_transaction_form_can_add_income_and_expense_categories_in_place(self):
        html,_=self.page('?month=2026-09')
        self.assertIn('data-category-quick-add',html)
        self.assertIn('＋ Tambah / kelola kategori',html)
        self.assertIn('Tambah &amp; pilih',html)

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
        self.assertNotIn('Tagihan &amp; Rutin',html)
        self.assertNotIn('fin-tool-grid',html)

        future=self.client.get(f'/business/{self.b}/finance/operations?month=2026-10')
        self.assertEqual(future.status_code,200)
        self.assertIn('Oktober 2026',future.text)
        self.assertIn('Internet',future.text)

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
