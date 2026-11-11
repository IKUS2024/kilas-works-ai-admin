"""Finance re-entry restores authorized context, never changes ledger ownership."""
import unittest
from urllib.parse import parse_qs, urlparse
import test_finance_approved_revisions as fixture
import db, repo, finance_service as finance, finance_branches as branches


class FinanceEntryContextTests(unittest.TestCase):
    setUp = fixture.ApprovedFinanceTests.setUp

    def snapshot(self):
        tables = [row['name'] for row in db.query_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'finance_%'")]
        return {table: db.query_all('SELECT * FROM ' + table + ' ORDER BY 1') for table in tables}

    def branch_target(self, response):
        self.assertEqual(response.status_code, 303)
        return parse_qs(urlparse(response.location).query).get('branch_id', [None])[0]

    def test_product_entry_returns_to_last_owned_business_not_first(self):
        newer = repo.create_business(self.uid, 'New empty workspace')
        finance.ensure_finance_defaults(newer, actor_user_id=self.uid)
        self.assertEqual(self.client.get(f'/business/{newer}/finance').status_code, 200)
        before = self.snapshot()
        response = self.client.post('/products/start', data={'product': 'finance'})
        self.assertIn('/business/' + str(newer) + '/', response.location)
        self.assertEqual(self.snapshot(), before)

    def test_personal_entry_retains_existing_bank_and_does_not_write(self):
        with branches.scope(self.b, self.personal, self.uid):
            finance.create_account(self.b, 'Saved personal bank', 'BANK', opening_balance_minor=1234500, actor_user_id=self.uid)
        self.assertEqual(self.client.get(self.url + '?branch_id=' + str(self.personal)).status_code, 200)
        before = self.snapshot()
        response = self.client.get(self.url + '/workspaces')
        self.assertEqual(self.branch_target(response), str(self.personal))
        page = self.client.get(response.location + '&view=accounts')
        self.assertIn('Saved personal bank', page.text)
        self.assertEqual(self.snapshot(), before)

    def test_nondefault_branch_restored_but_explicit_business_link_stays_explicit(self):
        branch = branches.create_branch(self.b, 'Second office', actor_user_id=self.uid)
        self.assertEqual(self.client.get(self.url + '?branch_id=' + str(branch)).status_code, 200)
        self.assertEqual(self.branch_target(self.client.get(self.url + '/workspaces')), str(branch))
        self.assertEqual(self.client.get(self.url + '?branch_id=' + str(self.branch)).status_code, 200)
        self.assertEqual(self.branch_target(self.client.get(self.url + '/workspaces')), str(self.branch))

    def test_foreign_or_stale_preferences_do_not_grant_access(self):
        foreign_branch = branches.list_branches(self.other, self.other_uid)[0]['id']
        for candidate in (foreign_branch, 999999, 'bad'):
            with self.client.session_transaction() as state:
                state['workspace_finance_business'] = self.other
                state['workspace_finance_branches'] = {str(self.b): candidate}
            before = self.snapshot()
            response = self.client.post('/products/start', data={'product': 'finance'})
            self.assertNotIn('/business/' + str(self.other) + '/', response.location)
            self.assertEqual(self.branch_target(self.client.get(self.url + '/workspaces')), str(self.branch))
            self.assertEqual(self.snapshot(), before)

    def test_revoked_archived_and_hidden_businesses_are_not_resumed(self):
        for mode in ('revoked', 'archived', 'hidden'):
            with self.subTest(mode=mode):
                candidate = repo.create_business(self.uid, 'Unavailable ' + mode)
                finance.ensure_finance_defaults(candidate, actor_user_id=self.uid)
                if mode == 'revoked':
                    db.execute('DELETE FROM business_memberships WHERE business_id=? AND user_id=?', (candidate, self.uid))
                elif mode == 'archived':
                    db.execute("UPDATE businesses SET status='ARCHIVED' WHERE id=?", (candidate,))
                else:
                    db.execute('INSERT INTO finance_entitlements (business_id,updated_at,customer_hidden) VALUES (?,?,TRUE)', (candidate, repo._now()))
                with self.client.session_transaction() as state:
                    state['workspace_finance_business'] = candidate
                before = self.snapshot()
                response = self.client.post('/products/start', data={'product': 'finance'})
                self.assertEqual(response.status_code, 303)
                self.assertNotIn('/business/' + str(candidate) + '/', response.location)
                self.assertEqual(self.snapshot(), before)

    def test_inactive_branch_falls_back_without_reactivation(self):
        branch = branches.create_branch(self.b, 'Archived office', actor_user_id=self.uid)
        self.client.get(self.url + '?branch_id=' + str(branch))
        db.execute('UPDATE finance_branches SET is_active=FALSE WHERE id=?', (branch,))
        before = self.snapshot()
        self.assertEqual(self.branch_target(self.client.get(self.url + '/workspaces')), str(self.branch))
        self.assertEqual(self.snapshot(), before)

    def test_other_members_private_workspace_cannot_be_resumed(self):
        db.execute("INSERT INTO business_memberships (business_id,user_id,role_in_business) VALUES (?,?,'OWNER')", (self.b, self.other_uid))
        foreign_personal = branches.ensure_personal(self.b, self.other_uid)
        with self.client.session_transaction() as state:
            state['workspace_finance_branches'] = {str(self.b): foreign_personal}
        before = self.snapshot()
        self.assertEqual(self.branch_target(self.client.get(self.url + '/workspaces')), str(self.branch))
        self.assertEqual(self.client.get(self.url + '?branch_id=' + str(foreign_personal)).status_code, 404)
        self.assertEqual(self.snapshot(), before)

    def test_foreign_business_context_and_malformed_preferences_are_ignored(self):
        for preference in (None, [], 'bad', {str(self.other): self.personal}):
            with self.client.session_transaction() as state:
                state['workspace_finance_branches'] = preference
            before = self.snapshot()
            self.assertEqual(self.branch_target(self.client.get(self.url + '/workspaces')), str(self.branch))
            self.assertEqual(self.snapshot(), before)

    def test_reports_remember_context_and_admin_does_not_consume_customer_preferences(self):
        self.client.get(self.url + '?branch_id=' + str(self.branch))
        response = self.client.get(self.url + '/reports?branch_id=' + str(self.personal))
        self.assertEqual(response.status_code, 200)
        before = self.snapshot()
        self.assertEqual(self.branch_target(self.client.get(self.url + '/workspaces')), str(self.personal))
        admin = repo.create_user('finance-entry-admin@example.test', 'unused', role='KILAS_ADMIN')
        from auth_test_helpers import authenticate
        authenticate(self.client, repo.get_user_by_id(admin))
        with self.client.session_transaction() as state:
            state['workspace_finance_branches'] = {str(self.b): self.personal}
        self.assertEqual(self.branch_target(self.client.get(self.url + '/workspaces')), str(self.branch))
        with self.client.session_transaction() as state:
            self.assertEqual(state['workspace_finance_branches'], {str(self.b): self.personal})
        self.assertEqual(self.snapshot(), before)

    def test_multiple_businesses_without_valid_preference_show_owned_chooser(self):
        newer = repo.create_business(self.uid, 'Synthetic new business')
        finance.ensure_finance_defaults(newer, actor_user_id=self.uid)
        for preference in (None, self.other, 999999):
            with self.client.session_transaction() as state:
                state.pop('workspace_finance_business', None)
                if preference is not None:
                    state['workspace_finance_business'] = preference
            before = self.snapshot()
            response = self.client.post('/products/start', data={'product': 'finance'})
            self.assertEqual((response.status_code, response.location), (303, '/products/finance'))
            page = self.client.get(response.location)
            self.assertEqual(page.status_code, 200)
            self.assertIn('Synthetic new business', page.text)
            self.assertNotIn('Other business', page.text)
            self.assertEqual(self.snapshot(), before)

    def test_single_business_enters_directly_without_switch_link(self):
        response = self.client.post('/products/start', data={'product': 'finance'})
        self.assertEqual((response.status_code, response.location), (303, self.url + '/workspaces'))
        page = self.client.get(response.location, follow_redirects=True)
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('data-finance-business-switch', page.text)

    def test_switch_link_recovers_older_accounts_without_moving_data(self):
        newer = repo.create_business(self.uid, 'Synthetic empty business')
        finance.ensure_finance_defaults(newer, actor_user_id=self.uid)
        db.execute("UPDATE businesses SET status='SUSPENDED' WHERE id=?", (self.b,))
        with branches.scope(self.b, self.personal, self.uid):
            finance.create_account(self.b, 'Saved older bank', 'BANK', opening_balance_minor=9876500, actor_user_id=self.uid)
        self.client.get(self.url + '?branch_id=' + str(self.personal))
        before = self.snapshot()
        for path in (f'/business/{newer}/finance', self.url + '?branch_id=' + str(self.personal),
                     self.url + '/reports?branch_id=' + str(self.branch)):
            page = self.client.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertIn('href="/products/finance" data-finance-business-switch', page.text)
            self.assertIn('Ganti bisnis', page.text)
            self.assertNotIn('Other business', page.text)
        self.client.get(self.url + '?branch_id=' + str(self.personal))
        self.client.get(f'/business/{newer}/finance')
        chooser = self.client.get('/products/finance')
        self.assertIn('Synthetic empty business', chooser.text)
        self.assertNotIn('Other business', chooser.text)
        response = self.client.post('/products/finance', data={'action': 'open', 'business_id': self.b}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Saved older bank', self.client.get(self.url + '?branch_id=' + str(self.personal) + '&view=accounts').text)
        resumed = self.client.post('/products/start', data={'product': 'finance'})
        self.assertEqual(resumed.location, self.url + '/workspaces')
        self.assertEqual(self.branch_target(self.client.get(resumed.location)), str(self.personal))
        self.assertEqual(self.snapshot(), before)

    def test_switch_link_is_translated_and_hidden_business_does_not_enable_it(self):
        hidden = repo.create_business(self.uid, 'Synthetic hidden business')
        finance.ensure_finance_defaults(hidden, actor_user_id=self.uid)
        db.execute('INSERT INTO finance_entitlements (business_id,updated_at,customer_hidden) VALUES (?,?,TRUE)', (hidden, repo._now()))
        page = self.client.get(self.url)
        self.assertNotIn('data-finance-business-switch', page.text)
        visible = repo.create_business(self.uid, 'Synthetic visible business')
        finance.ensure_finance_defaults(visible, actor_user_id=self.uid)
        before = self.snapshot()
        for locale, label in (('id', 'Ganti bisnis'), ('en', 'Switch business'), ('es', 'Cambiar de negocio'), ('zh', '切换业务')):
            self.client.set_cookie('kilas_language', locale)
            page = self.client.get(self.url)
            self.assertEqual(page.status_code, 200)
            self.assertIn('data-finance-business-switch>' + label + '</a>', page.text)
            chooser = self.client.get('/products/finance')
            self.assertNotIn('Synthetic hidden business', chooser.text)
            self.assertNotIn('Other business', chooser.text)
        self.assertEqual(self.snapshot(), before)

    def test_remembered_personal_does_not_redirect_branchless_post(self):
        self.client.get(self.url + '?branch_id=' + str(self.personal))
        response = self.client.post(self.url + '/accounts', data={'name': 'Explicit legacy business bank', 'account_type': 'BANK'})
        self.assertEqual(response.status_code, 303)
        row = db.query_one('SELECT branch_id FROM finance_accounts WHERE name=?', ('Explicit legacy business bank',))
        self.assertEqual(row['branch_id'], self.branch)


if __name__ == '__main__':
    unittest.main()
