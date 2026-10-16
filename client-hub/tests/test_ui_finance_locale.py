"""Finance labels follow UI locale; canonical values and full Finance rows survive."""
import json
import os
import re
import unittest
from pathlib import Path
from flask import render_template_string
import test_finance_home_dashboard as prior
from test_finance_home_dashboard import fixture, db


class FinanceLocaleTests(unittest.TestCase):
    setUp = prior.DashboardHomeTests.setUp
    page = prior.DashboardHomeTests.page

    def snapshot(self):
        return '\n'.join(line for line in db.get_connection().iterdump()
                         if line.startswith('INSERT INTO "finance_'))

    def test_report_budget_profile_and_builtin_types_roundtrip_without_financial_writes(self):
        db.execute('UPDATE users SET full_name=? WHERE id=?', ('Recent', self.uid))
        fixture.f.create_account_type_option(self.b, 'Recent', actor_user_id=self.uid)
        fixture.f.create_account(self.b, 'Wallet', account_type_label='Recent', actor_user_id=self.uid)
        expense = fixture.f.list_categories(self.b, 'EXPENSE')[0]['id']
        fixture.f.set_monthly_budget(self.b, '2026-09', expense, 10000, 'IDR', actor_user_id=self.uid)
        paths = {'reports':f'/business/{self.b}/finance/reports?preset=month',
                 'budget':f'/business/{self.b}/finance/budget?month=2026-09',
                 'accounts':self.url+'?view=accounts&month=2026-09'}
        for path in paths.values():
            self.assertEqual(self.client.get(path).status_code, 200)
        before = self.snapshot()
        pages = {}
        for language in ('en', 'id', 'en'):
            self.client.set_cookie('kilas_language', language)
            for name, path in paths.items():
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, (name, language))
                html = response.text
                self.assertTrue('<html lang="'+language+'">' in html)
                self.assertTrue(('aria-label="Profile Business"' if language=='en' else 'aria-label="Profil Business"') in html)
                if name == 'reports':
                    self.assertTrue(('<strong>This month</strong>' if language=='en' else '<strong>Bulan ini</strong>') in html)
                if name == 'budget':
                    self.assertTrue(('0 percent used' if language=='en' else '0 persen terpakai') in html)
                if name == 'accounts':
                    self.assertTrue(('>Wallet</span>' if language=='en' else '>Dompet</span>') in html)
                    self.assertTrue('value="Wallet"' in html)
                    self.assertTrue('value="Recent">Recent</option>' in html)
                    self.assertTrue('<strong>Wallet</strong>' in html)
                pages[name+'-'+language] = html
            self.assertEqual(self.snapshot(), before)
        target = os.environ.get('KILAS_FINANCE_LOCALE_FIXTURE_PATH')
        if target:
            pages['type-options'] = fixture.f.list_account_type_options(self.b, actor_user_id=self.uid)
            Path(target).write_text(json.dumps(pages), encoding='utf-8')

    def test_custom_label_equal_to_builtin_ui_key_is_not_translated(self):
        with fixture.app.test_request_context(headers={'Cookie':'kilas_language=id'}):
            html = render_template_string("{% from '_finance_account_type_label.html' import account_type_label %}{{ account_type_label('Wallet', options) }}", options=[{'name':'Wallet','is_default':False}])
            self.assertEqual(html, 'Wallet')
            html = render_template_string("{% from '_finance_account_type_label.html' import account_type_label %}{{ account_type_label('Wallet', options) }}", options=[{'name':'Wallet','is_default':True}])
            self.assertEqual(html, 'Dompet')

    def test_dashboard_ring_and_navigation_roundtrip_without_financial_writes(self):
        expense = fixture.f.list_categories(self.b, 'EXPENSE')[0]['id']
        fixture.f.set_monthly_budget(self.b, '2026-09', expense, 10000, 'IDR', actor_user_id=self.uid)
        fixture.f.create_transaction(self.b, 'EXPENSE', 2500, self.a, expense, '2026-09-15',
                                     description='Home Dashboard Invoice', actor_user_id=self.uid)
        self.page()
        before = self.snapshot()
        for locale, expected in [('en','Budget usage 25 percent'),
                                 ('id','Penggunaan anggaran 25 persen'),
                                 ('en','Budget usage 25 percent')]:
            self.client.set_cookie('kilas_language', locale)
            html, context = self.page()
            self.assertIn('role="img" aria-label="'+expected+'"', html)
            self.assertEqual(context['budget_percent'], 25)
            self.assertIn('--budget-percent: 25;', html)
            self.assertEqual(self.snapshot(), before)

    def test_navigation_and_account_count_roundtrip_preserves_names_and_values(self):
        first = fixture.f.list_accounts(self.b, actor_user_id=self.uid)[0]
        for count in (1, 2):
            if count == 2:
                fixture.f.create_account(self.b, 'Invoice', account_type_label=first['account_type_label'],
                                         actor_user_id=self.uid)
            for query in ('?month=2026-09', '?view=accounts&month=2026-09'):
                self.page(query)
            before = self.snapshot()
            for locale in ('en', 'id', 'en'):
                self.client.set_cookie('kilas_language', locale)
                for query in ('?month=2026-09', '?view=accounts&month=2026-09'):
                    html, context = self.page(query)
                    sidebar = re.search(r'<aside class="finance-(?:app|dashboard)-sidebar".*?</aside>',html,re.S)[0]
                    labels = ('Home','Dashboard','Invoices') if locale=='en' else ('Beranda','Dasbor','Faktur')
                    for label in labels:
                        self.assertIn('>'+label+'</a>', sidebar)
                    if locale == 'id':
                        for leftover in ('Home', 'Dashboard', 'Invoice'):
                            self.assertNotIn('>'+leftover+'</a>', sidebar)
                    if 'view=accounts' in query:
                        expected = str(count)+' '+('akun' if locale=='id' else 'account' if count==1 else 'accounts')
                        self.assertIn('<small class="finance-account-group-count">'+expected+'</small>', html)
                        self.assertNotIn('<strong>1 accounts</strong>', html)
                        if count == 2:
                            self.assertIn('<strong>Invoice</strong>', html)
                    else:
                        expected = 'Not set' if locale=='en' else 'Belum diatur'
                        self.assertIn('role="img" aria-label="'+expected+'"', html)
                        self.assertEqual(context['budget_percent'], 0)
                self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
