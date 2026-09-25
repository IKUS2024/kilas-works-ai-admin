"""Phase 9 navigation/retirement security with real routes and isolated Finance DB."""
import unittest
from unittest.mock import patch
import test_finance_phase2a as fixture
import repo
import db


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        fixture.ReceivablesTests.setUp(self)
        # Fixture accounts make this a legitimate Finance workspace without AI setup.
        db.execute("UPDATE businesses SET package='NONE' WHERE id=?", (self.b,))
        with self.client.session_transaction() as session:
            session.update(role='CLIENT_OWNER', active_product='finance', _csrf_token='phase9-test')
        fixture.app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS'] = True

    def test_finance_only_can_open_home_more_and_services(self):
        response = self.client.get('/workspace', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Navigasi Kilas Finance', response.text)
        self.assertNotIn('/workspace/go/inbox', response.text)
        self.assertNotIn('kw-primary', response.text)
        self.assertNotIn('Other business', response.text)
        self.assertEqual(self.client.get('/workspace/more').status_code, 200)
        response = self.client.get('/workspace/go/services')
        self.assertEqual(response.status_code, 303)
        with self.client.session_transaction() as session:
            self.assertNotIn('active_product', session)

    def test_full_navigation_and_foreign_business_denied_before_preference_write(self):
        db.execute("UPDATE businesses SET package='AI_ADMIN' WHERE id=?", (self.b,))
        response = self.client.get('/workspace/ai')
        for area in ('inbox', 'customers', 'jobs'):
            self.assertIn('/workspace/go/'+area, response.text)
        self.assertNotIn('Other business', response.text)
        response = self.client.get('/workspace/go/finance?business_id='+str(self.other))
        self.assertEqual(response.status_code, 404)
        response = self.client.get('/workspace/go/inbox?business_id='+str(self.other))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get('/workspace/go/evil?next=https://evil.test').status_code, 404)

    def test_marketplace_all_entry_methods_stopped_no_search_or_handoff(self):
        from legacy_order_retirement import ENDPOINTS
        db.execute("INSERT INTO kilas_order_requests(request_code,draft_token,user_id,request_text,status) VALUES (?,?,?,?,?)", ('historical','history-token',self.uid,'Historical customer request','DELIVERED'))
        before = db.query_one('SELECT COUNT(*) AS n FROM kilas_order_requests')['n']
        for rule in fixture.app.url_map.iter_rules():
            if rule.endpoint not in ENDPOINTS:
                continue
            path = rule.rule.replace('<product_code>', 'private').replace('<request_code>', 'private')
            for method in rule.methods - {'HEAD', 'OPTIONS'}:
                response = self.client.open(path, method=method, data={'csrf_token':'phase9-test'})
                self.assertEqual(response.status_code, 410, (path, method))
                self.assertNotIn('private', response.text)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_order_requests')['n'], before)

    def test_setup_csrf_and_goal_never_activates_finance_or_creates_business(self):
        self.client.get('/workspace/go/setup')
        before = len(repo.list_businesses_for_user(self.uid))
        self.assertEqual(self.client.post('/products/start', data={'product':'both'}).status_code, 400)
        response = self.client.post('/products/start', data={'product':'both','csrf_token':'phase9-test'})
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith('/products/assist'))
        self.assertEqual(len(repo.list_businesses_for_user(self.uid)), before)
        with self.client.session_transaction() as session:
            self.assertEqual(session['onboarding_goal'], 'both')
        self.assertNotIn('Lengkapi ruang kerja', self.client.get('/workspace', follow_redirects=True).text)

    def test_anonymous_no_owner_data_and_error_is_not_empty_state(self):
        with patch.object(repo, 'list_businesses_for_user', side_effect=RuntimeError('private')):
            response = self.client.get('/workspace')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private', response.text)
        self.assertIn('belum dapat dimuat', response.text)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get('/workspace').status_code, 302)
        self.assertEqual(self.client.get('/workspace/go/finance').status_code, 302)

    def test_home_attention_is_authoritative_scoped_and_read_only(self):
        invoice = fixture.f.create_finance_invoice(self.b, self.c, '2026-09-01', '2026-09-30',
            [dict(description='Customer service', quantity=1, unit_price_minor=15000)], actor_user_id=self.uid)
        fixture.f.issue_finance_invoice(self.b, invoice, actor_user_id=self.uid)
        before = fixture.f.get_finance_invoice(self.b, invoice, actor_user_id=self.uid)
        with patch.dict(__import__('os').environ, {'KILAS_FINANCE_ACCESS_MODE':'self_service', 'KILAS_FINANCE_UNLIMITED_TRIAL':'false'}):
            response = self.client.get('/workspace', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Navigasi Kilas Finance', response.text)
        self.assertIn('Finance hanya-baca', response.text)
        self.assertNotIn('PRIVATE CUSTOMER', response.text)
        self.assertEqual(before, fixture.f.get_finance_invoice(self.b, invoice, actor_user_id=self.uid))
        self.assertEqual(fixture.f.list_transactions(self.b, actor_user_id=self.uid), [])

    def test_owned_direct_business_links_keep_selected_context(self):
        first=repo.create_business(self.uid, 'First AI', package='AI_ADMIN')
        second=repo.create_business(self.uid, 'Second AI', package='AI_ADMIN')
        self.client.get('/workspace/go/review?business_id='+str(first))
        with self.client.session_transaction() as session:
            self.assertEqual(session['workspace_ai_business'], first)
        with patch.dict(__import__('os').environ, {'KILAS_CUSTOMERS_V2_ENABLED':'false'}):
            page=self.client.get('/workspace/go/customers?business_id='+str(second))
        self.assertEqual(page.status_code, 200)
        self.assertIn('Fitur belum tersedia', page.text)
        self.assertIn('Second AI', page.text)
        self.assertNotIn('Other business',page.text)


    def test_ai_only_has_no_finance_navigation_or_switcher(self):
        import re
        db.execute("DELETE FROM finance_accounts WHERE business_id=?", (self.b,))
        db.execute("UPDATE businesses SET package='AI_ADMIN' WHERE id=?", (self.b,))
        with patch('routes_products._finance_business_claimed', return_value=False):
            page = self.client.get('/workspace/ai')
        self.assertEqual(page.status_code, 200)
        nav = re.search(r'<nav class="kw-primary".*?</nav>', page.text, re.S).group()
        self.assertNotIn('Finance', nav)
        self.assertNotIn('Pilih produk', page.text)
        self.assertNotIn('finance-app-sidebar', page.text)
        self.assertNotIn('Buka Finance', page.text)

    def test_both_products_switch_without_mixed_menus_or_business_writes(self):
        import re
        import finance_branches
        db.execute("UPDATE businesses SET package='AI_ADMIN' WHERE id=?", (self.b,))
        second = repo.create_business(self.uid, 'Separate AI', package='AI_ADMIN')
        before = len(repo.list_businesses_for_user(self.uid))
        page = self.client.get('/workspace/ai')
        self.assertIn('Pilih produk', page.text)
        nav = re.search(r'<nav class="kw-primary".*?</nav>', page.text, re.S).group()
        self.assertNotIn('Finance', nav)
        self.assertNotIn('Buka Finance', page.text)
        branch = finance_branches.list_branches(self.b, self.uid)[0]['id']
        page = self.client.get(f'/business/{self.b}/finance?branch_id={branch}')
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('kw-primary', page.text)
        self.assertIn('Navigasi Kilas Finance', page.text)
        self.assertIn('Pilih produk', page.text)
        self.assertNotIn('Separate AI', page.text)
        self.assertEqual(self.client.get('/workspace').status_code, 303)
        # Direct AI deep link exits old Finance session trap, preserving independent ids.
        page = self.client.get(f'/business/{second}/review')
        self.assertEqual(page.status_code, 200)
        with self.client.session_transaction() as session:
            self.assertEqual(session['workspace_ai_business'], second)
            self.assertEqual(session['workspace_finance_business'], self.b)
            self.assertEqual(session['active_product'], 'brain')
        response = self.client.get('/workspace/go/finance')
        self.assertIn(f'/business/{self.b}/finance?branch_id={branch}', response.location)
        page = self.client.get('/workspace/more')
        self.assertNotIn('Pengetahuan &amp; playbook', page.text)
        self.assertNotIn('kw-primary', page.text)
        self.assertEqual(len(repo.list_businesses_for_user(self.uid)), before)

    def test_foreign_remembered_finance_branch_is_not_reused(self):
        import finance_branches
        foreign = finance_branches.list_branches(self.other, self.other_uid)[0]['id']
        with self.client.session_transaction() as session:
            session['workspace_finance_branches'] = {str(self.b): foreign}
        response = self.client.get('/workspace/go/finance')
        self.assertNotIn('branch_id='+str(foreign), response.location)


if __name__ == '__main__': unittest.main()
