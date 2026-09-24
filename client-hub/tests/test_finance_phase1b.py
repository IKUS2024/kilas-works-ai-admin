"""Finance beta UI/security tests, offline; Phase 1A remains the only ledger writer."""
import os
import unittest
from unittest.mock import patch
from pathlib import Path
from html.parser import HTMLParser
import test_business_hub_v2_phase_a as fixture
import db, repo, finance_service as finance

app = fixture.FLASK_APP


class FinanceUITests(unittest.TestCase):
    def setUp(self):
        fixture.reset_db()
        self.env = patch.dict(os.environ, {'KILAS_FINANCE_BETA': 'true'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.http = patch('requests.sessions.Session.request', side_effect=AssertionError('HTTP forbidden'))
        self.http.start(); self.addCleanup(self.http.stop)
        self.uid = repo.create_user('finance@example.test', 'unused')
        self.bid = repo.create_business(self.uid, 'My business')
        self.other_user = repo.create_user('other@example.test', 'unused')
        self.other = repo.create_business(self.other_user, 'Other business')
        self.client = app.test_client()
        with self.client.session_transaction() as session: session['user_id'] = self.uid
        self.url = f'/business/{self.bid}/finance'
        app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS'] = False
        self.addCleanup(lambda: app.config.update(CLIENT_HUB_FORCE_CSRF_IN_TESTS=False))

    def start(self, bid=None):
        finance.ensure_finance_defaults(bid or self.bid, actor_user_id=self.uid if bid is None else self.other_user)

    def data(self, direction='INCOME', **kwargs):
        values = dict(direction=direction, amount='1250000', occurred_on='2026-09-15',
            account_id=str(finance.list_accounts(self.bid)[0]['id']),
            category_id=str(finance.list_categories(self.bid, direction)[0]['id']))
        values.update(kwargs)
        return values

    def test_logged_out_denied(self):
        client = app.test_client()
        self.assertEqual(client.get(self.url).status_code, 302)
        for path in ('start', 'transactions', 'accounts', 'categories', 'transactions/1/void'):
            self.assertEqual(client.post(self.url+'/'+path).status_code, 302)

    def test_beta_off_and_admin_override(self):
        os.environ.pop('KILAS_FINANCE_BETA', None)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url+'/start').status_code, 404)
        admin = repo.create_user('admin@example.test','unused',role='KILAS_ADMIN')
        with self.client.session_transaction() as session: session['user_id'] = admin
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.post(self.url+'/start').status_code, 303)

    def test_beta_aliases_and_own_only(self):
        for flag in ('true','1','yes','on',' TRUE '):
            os.environ['KILAS_FINANCE_BETA'] = flag
            self.assertEqual(self.client.get(self.url).status_code, 200)
        for suffix in ('', '/start', '/transactions', '/accounts', '/categories', '/transactions/1/void'):
            method = self.client.get if not suffix else self.client.post
            self.assertEqual(method(f'/business/{self.other}/finance'+suffix).status_code, 404)

    def test_get_never_initializes_or_writes(self):
        before = db.query_all('SELECT * FROM audit_log')
        html = self.client.get(self.url).get_data(as_text=True)
        self.assertIn('Mulai Kilas Finance', html)
        self.assertEqual(finance.list_accounts(self.bid), [])
        self.assertEqual(finance.list_categories(self.bid), [])
        self.assertEqual(before, db.query_all('SELECT * FROM audit_log'))

    def test_start_idempotent_and_actor_audited(self):
        for _ in range(2): self.assertEqual(self.client.post(self.url+'/start').status_code, 303)
        self.assertEqual(len(finance.list_accounts(self.bid)), 1)
        self.assertEqual(len(finance.list_categories(self.bid)), 9)
        audits = db.query_all("SELECT * FROM audit_log WHERE action LIKE 'FINANCE_%'")
        self.assertEqual(len(audits), 19)
        self.assertTrue(all(a['actor_user_id']==self.uid for a in audits))

    def test_income_expense_summary_and_list(self):
        self.start()
        self.assertEqual(self.client.post(self.url+'/transactions',data=self.data(description='Sale')).status_code,303)
        self.assertEqual(self.client.post(self.url+'/transactions',data=self.data('EXPENSE',amount='250000')).status_code,303)
        html = self.client.get(self.url+'?month=2026-09').get_data(as_text=True)
        for text in ('Rp1.250.000','Rp250.000','Rp1.000.000','Arus Kas'): self.assertIn(text,html)
        self.assertEqual(len(finance.list_transactions(self.bid)), 2)
        self.assertEqual(finance.list_transactions(self.bid)[0]['created_by_user_id'], self.uid)

    def test_invalid_money_rejected(self):
        self.start()
        for amount in ('0','-1','0.000001','1e6','abc','9223372036854775808','9'*100,''):
            result = self.client.post(self.url+'/transactions',data=self.data(amount=amount),follow_redirects=True)
            self.assertEqual(result.status_code,200)
            self.assertEqual(finance.list_transactions(self.bid),[])
        self.assertEqual(finance.list_transactions(self.bid), [])

    def test_cross_account_category_project_rejected(self):
        self.start(); self.start(self.other)
        project = db.insert_returning_id("INSERT INTO projects (business_id,project_type,pricing_mode,title,status,created_by_user_id) VALUES (?,'CONTENT','CUSTOM_QUOTE','Private','REQUESTED',?)", (self.other,self.other_user))
        for change in (dict(account_id=str(finance.list_accounts(self.other)[0]['id'])),
                       dict(category_id=str(finance.list_categories(self.other,'INCOME')[0]['id'])),
                       dict(project_id=str(project))):
            response = self.client.post(self.url+'/transactions',data=self.data(**change),follow_redirects=True)
            self.assertEqual(response.status_code,200)
            self.assertNotIn('Private',response.get_data(as_text=True))
        self.assertEqual(finance.list_transactions(self.bid), [])

    def test_direction_mismatch_and_posted_scope_forgery(self):
        self.start()
        bad = self.data(category_id=str(finance.list_categories(self.bid,'EXPENSE')[0]['id']))
        html=self.client.post(self.url+'/transactions',data=bad,follow_redirects=True).get_data(as_text=True)
        self.assertIn('Kategori tidak tersedia.',html)
        self.assertEqual(finance.list_transactions(self.bid),[])
        self.client.post(self.url+'/transactions',data=self.data(business_id=self.other,actor_user_id=self.other_user,currency='USD'))
        rows=finance.list_transactions(self.bid)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['created_by_user_id'],self.uid)
        self.assertEqual(rows[0]['currency'],'IDR');self.assertEqual(finance.list_transactions(self.other),[])

    def test_list_scope_and_filters(self):
        self.start();self.start(self.other)
        finance.create_transaction(self.other,'INCOME',9,finance.list_accounts(self.other)[0]['id'],finance.list_categories(self.other,'INCOME')[0]['id'],'2026-09-15',description='PRIVATE OTHER')
        self.client.post(self.url+'/transactions',data=self.data(description='own income'))
        self.client.post(self.url+'/transactions',data=self.data('EXPENSE',description='own expense'))
        html=self.client.get(self.url+'?month=2026-09&view=transactions&direction=EXPENSE').get_data(as_text=True)
        self.assertIn('own expense',html);self.assertNotIn('own income',html);self.assertNotIn('PRIVATE OTHER',html)
        self.assertNotIn('own expense',self.client.get(self.url+'?month=2026-10').get_data(as_text=True))

    def test_void_preserves_and_cross_tenant_is_unavailable(self):
        self.start();self.client.post(self.url+'/transactions',data=self.data())
        tx=finance.list_transactions(self.bid)[0]['id']
        self.assertEqual(self.client.post(f'/business/{self.other}/finance/transactions/{tx}/void').status_code,404)
        self.start(self.other)
        foreign=finance.create_transaction(self.other,'INCOME',1,finance.list_accounts(self.other)[0]['id'],finance.list_categories(self.other,'INCOME')[0]['id'],'2026-09-15')
        self.assertEqual(self.client.post(self.url+f'/transactions/{foreign}/void').status_code,404)
        self.assertEqual(self.client.post(self.url+f'/transactions/{tx}/void').status_code,303)
        self.assertEqual(finance.get_transaction(self.bid,tx)['status'],'VOID')
        self.assertEqual(finance.get_finance_summary(self.bid,'2026-09-01','2026-09-30')['total_income_minor'],0)
        self.assertEqual(finance.get_transaction(self.bid,tx)['status'],'VOID')
        self.assertNotIn('Rp1.250.000',self.client.get(self.url+'?month=2026-09&view=transactions').text)

    def test_all_posts_csrf_enforced(self):
        app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=True
        for path in ('start','transactions','accounts','categories','transactions/1/void'):
            self.assertEqual(self.client.post(self.url+'/'+path).status_code,400)
        self.client.get(self.url)
        with self.client.session_transaction() as session: token=session['_csrf_token']
        self.assertEqual(self.client.post(self.url+'/start',data={'csrf_token':token}).status_code,303)

    def test_dashboard_button_gate(self):
        os.environ['KILAS_FINANCE_BETA']='off'
        self.assertNotIn('Kilas Finance',self.client.get('/dashboard').get_data(as_text=True))
        os.environ['KILAS_FINANCE_BETA']='on'
        self.start()  # Real Finance data gives this business an owned Finance lane.
        html=self.client.get('/dashboard').get_data(as_text=True)
        self.assertIn(f'/workspace/go/finance?business_id={self.bid}',html)
        response=self.client.get(f'/workspace/go/finance?business_id={self.bid}')
        self.assertIn(f'/business/{self.bid}/finance/workspaces',response.location)
        self.assertNotIn(f'/business/{self.other}/finance',html)

    def test_accounts_categories_and_duplicate_errors(self):
        self.start()
        data=dict(name='Bank account',account_type='BANK',opening_balance='-500')
        self.assertEqual(self.client.post(self.url+'/accounts',data=data).status_code,303)
        self.assertEqual(finance.list_accounts(self.bid)[1]['opening_balance_minor'],-50000)
        html=self.client.post(self.url+'/accounts',data=data,follow_redirects=True).get_data(as_text=True)
        self.assertIn('sudah ada',html)
        self.client.post(self.url+'/categories',data={'name':'Travel','direction':'EXPENSE'})
        self.assertIn('Travel',[r['name'] for r in finance.list_categories(self.bid,'EXPENSE')])

    def test_invalid_month_and_safe_escaped_content(self):
        self.start()
        for month in ('bad','2026-13','0000-01','2026-1'):
            self.assertEqual(self.client.get(self.url+'?month='+month).status_code,302)
        self.client.post(self.url+'/transactions',data=self.data(description='<script>alert(1)</script>'))
        html=self.client.get(self.url+'?month=2026-09&view=transactions').get_data(as_text=True)
        self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>alert(1)</script>',html)

    def test_mobile_forms_and_no_external_assets(self):
        self.start();html=self.client.get(self.url).get_data(as_text=True)
        tags=[]
        parser=HTMLParser();parser.handle_starttag=lambda tag,attrs:tags.append(tag);parser.feed(html)
        self.assertIn('finance-chart-table-wrap',html)  # chart details scroll independently
        self.assertIn('minmax(min(100%,240px),1fr)',html)
        self.assertIn('Pemasukan',html);self.assertIn('Pengeluaran',html)
        self.assertIn('Pengaturan',html)
        source=(Path(__file__).parents[1]/'templates/finance_dashboard.html').read_text()
        self.assertNotIn('https://',source)


if __name__=='__main__': unittest.main()
