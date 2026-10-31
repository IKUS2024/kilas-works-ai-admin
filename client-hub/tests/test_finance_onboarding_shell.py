"""Current Finance entry navigation and real owner/session boundaries, offline only."""
import re
import unittest
import uuid
from unittest.mock import patch
import test_customer_auth_sessions as auth_fixture
import security


class FinanceOnboardingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = auth_fixture.CustomerAuthTests('test_cross_module_continuity_home_launch_and_deep_link_refresh')
        self.fixture.id = self.id
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.app, self.repo = self.fixture.app, self.fixture.repo
        self.password = 'synthetic-onboarding-password'
        self.accounts = []
        for index in range(2):
            email = f'finance-onboarding-{uuid.uuid4().hex}-{index}@example.test'
            user = self.repo.create_user(email, security.hash_password(self.password))
            self.accounts.append((user, email))

    def login(self, account=0, client=None):
        client = client or self.app.test_client()
        token = self.fixture.csrf(client)
        response = client.post('/login', data={
            'email': self.accounts[account][1], 'password': self.password, 'csrf_token': token})
        self.assertEqual(response.location, '/products/start')
        return client

    def test_new_account_finance_handoff_uses_current_product_navigation(self):
        client = self.login()
        token = self.fixture.csrf(client, '/products/start')
        response = client.post('/products/start', data={'product': 'finance', 'csrf_token': token})
        self.assertEqual((response.status_code, response.location), (303, '/products/finance?step=business'))
        for path in (response.location, '/products/finance'):
            page = client.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertEqual(page.headers['Cache-Control'], 'private, no-store')
            self.assertIn('kilas_revision_shell.css', page.text)
            self.assertIn('kilas_chat_sidebar.css', page.text)
            self.assertIn('kilas-reference-header', page.text)
            sidebar = page.text.split('<aside', 1)[1].split('</aside>', 1)[0]
            self.assertIn('data-chat-sidebar', sidebar)
            self.assertIn('name="product" value="finance"', sidebar)
            self.assertIn('href="/kilas-ai/library"', sidebar)
            self.assertIn('kilas-profile-menu', sidebar)
            self.assertNotIn('premium-sidebar-account', sidebar)
            self.assertNotIn('premium-nav', sidebar)
            for obsolete in ('href="/kilas-ai/video"', 'href="/kilas-translator"'):
                self.assertNotIn(obsolete, sidebar)
            self.assertIn('kilas-profile-language', sidebar)
            self.assertIn('product_forms.js', page.text)

    def test_sidebar_history_is_owned_and_read_only(self):
        from kilas_ai import store, copilot
        # Chat history is primary again; retain the owner/read-only/business checks.
        own = store.create_thread(self.accounts[0][0])
        foreign = store.create_thread(self.accounts[1][0])
        for user, thread, title in ((self.accounts[0][0], own, 'Synthetic owned conversation'),
                                     (self.accounts[1][0], foreign, 'Synthetic other account secret')):
            store.rename_thread(user, thread, title)
            store.append_user_once(user, thread, 'Synthetic history message', 'FAST', uuid.uuid4().hex)
        client = self.login()
        with patch('requests.sessions.Session.request', side_effect=AssertionError('No external transport')):
            page = client.get('/products/finance?step=business')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Synthetic owned conversation', page.text)
        self.assertNotIn('Synthetic other account secret', page.text)
        self.assertEqual(self.repo.list_businesses_for_user(self.accounts[0][0]), [])

    def test_creation_csrf_idempotency_and_tenant_authority_remain_intact(self):
        client = self.login()
        page = client.get('/products/finance?step=business')
        identity = re.search(r'name="setup_identity" value="([a-f0-9]{32})"', page.text).group(1)
        token = self.fixture.csrf(client, '/products/finance?step=business')
        data = {'action': 'create_trial', 'business_name': 'Synthetic owned Finance',
                'setup_identity': identity, 'csrf_token': token}
        invalid = client.post('/products/finance', data={**data, 'csrf_token': 'invalid'})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.repo.list_businesses_for_user(self.accounts[0][0]), [])
        with patch.dict(__import__('os').environ, {'KILAS_FINANCE_BETA': 'on'}):
            self.assertEqual(client.post('/products/finance', data=data).status_code, 303)
            self.assertEqual(client.post('/products/finance', data=data).status_code, 303)
        businesses = self.repo.list_businesses_for_user(self.accounts[0][0])
        self.assertEqual(len(businesses), 1)
        self.assertEqual(businesses[0]['business_name'], data['business_name'])
        other = self.login(1)
        other_token = self.fixture.csrf(other, '/products/finance?step=business')
        denied = other.post('/products/finance', data={
            'action': 'open', 'business_id': businesses[0]['id'], 'csrf_token': other_token})
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn(data['business_name'], other.get('/products/finance?step=business').text)

    def test_logout_then_switch_account_does_not_restore_old_identity(self):
        client = self.login()
        copied = self.fixture.copied(client)
        self.assertEqual(client.get('/logout').location, '/login')
        for previous in (client, copied):
            self.assertEqual(previous.get('/products/finance?step=business').location, '/login')
        self.login(1, client)
        page = client.get('/products/finance?step=business')
        self.assertEqual(page.status_code, 200)
        self.assertIn(self.accounts[1][1], page.text)
        self.assertNotIn(self.accounts[0][1], page.text)


if __name__ == '__main__':
    unittest.main()
