"""Offline Embedded Signup security and activation regression tests."""
import json
import os
import re
import unittest
from unittest.mock import Mock, patch
import test_single_plan_release as f
import whatsapp_signup as signup
import provisioning
import subscription_service
import requests

ENV = {
    'META_APP_ID': '100', 'META_EMBEDDED_SIGNUP_CONFIG_ID': '200',
    'WHATSAPP_APP_SECRET': 'PRIVATE_APP_SECRET', 'META_PROVIDER_BUSINESS_ID': '300',
    'META_PROVIDER_SYSTEM_USER_ID': '400', 'META_PROVIDER_ADMIN_ACCESS_TOKEN': 'PRIVATE_ADMIN_TOKEN',
    'WHATSAPP_ACCESS_TOKEN': 'PRIVATE_RUNTIME_TOKEN', 'META_REGISTRATION_PIN_KEY': 'PRIVATE_PIN_KEY_' + 'x' * 32,
    'WHATSAPP_PHONE_NUMBER_ID': '999', 'META_GRAPH_API_VERSION': 'v21.0',
}


class SignupTests(unittest.TestCase):
    def setUp(self):
        fixture = f.SinglePlanTests(); fixture.setUp()
        self.client, self.uid, self.bid, self.other = fixture.client, fixture.uid, fixture.bid, fixture.other
        self.user = f.repo.get_user_by_id(self.uid)
        f.db.execute("UPDATE businesses SET status='APPROVED' WHERE id=?", (self.bid,))
        f.repo.save_tenant_config(self.bid, {'business_id': self.bid, 'preserved': 'knowledge', 'whatsapp': {}})
        self.env = patch.dict(os.environ, ENV); self.env.start(); self.addCleanup(self.env.stop)
        self.paid = patch('payment_service.has_verified_ai_admin_payment', return_value=True)
        self.paid_mock = self.paid.start(); self.addCleanup(self.paid.stop)
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('external HTTP forbidden'))
        self.network.start(); self.addCleanup(self.network.stop)
        self.http = patch('whatsapp_signup.requests.request', side_effect=self.meta)
        self.http_mock = self.http.start(); self.addCleanup(self.http.stop)
        self.reachable = patch('provisioning._check_whatsapp_phone_number_reachable', return_value=(True, 'ok'))
        self.reachable_mock = self.reachable.start(); self.addCleanup(self.reachable.stop)
        self.customer_grant = '500'; self.provider_shared = True; self.phone_match = True
        self.biz_app = False; self.phone_status = 'CONNECTED'; self.error_path = None; self.fail_status = 403
        self.calls = []

    def meta(self, method, url, **kwargs):
        path = url.split('/v21.0/')[1]
        self.calls.append((method, path, kwargs))
        if path == self.error_path:
            return Mock(status_code=self.fail_status, json=Mock(return_value={'error': {'message': 'PRIVATE_RAW_ERROR'}}))
        if path == 'oauth/access_token': data = {'access_token': 'PRIVATE_CUSTOMER_TOKEN'}
        elif path == 'debug_token':
            if kwargs['params']['input_token'] == 'PRIVATE_CUSTOMER_TOKEN':
                data = {'data': {'is_valid': True, 'app_id': '100', 'granular_scopes': [
                    {'scope': 'whatsapp_business_management', 'target_ids': [self.customer_grant]}]}}
            else:
                data = {'data': {'is_valid': True, 'app_id': '100', 'user_id': '400',
                                'scopes': ['whatsapp_business_management', 'whatsapp_business_messaging']}}
        elif path == '300/client_whatsapp_business_accounts': data = {'data': [{'id': '500'}] if self.provider_shared else []}
        elif path == '500/phone_numbers': data = {'data': [{'id': '600'}] if self.phone_match else []}
        elif path == '600': data = {'id': '600', 'status': self.phone_status, 'is_on_biz_app': self.biz_app}
        elif path in ('500/assigned_users', '500/subscribed_apps'): data = {'success': True}
        elif path == '600/register': self.phone_status = 'CONNECTED'; data = {'success': True}
        else: raise AssertionError('unexpected Meta request')
        return Mock(status_code=200, json=Mock(return_value=data))

    def payload(self):
        return {'state': signup.new_state(self.bid, self.uid), 'code': 'PRIVATE_CODE',
                'waba_id': '500', 'phone_number_id': '600', 'coexistence': False}

    def post(self, data=None, bid=None):
        return self.client.post(f'/business/{bid or self.bid}/whatsapp/complete', json=data or self.payload())

    def assert_closed(self):
        self.assertEqual(f.repo.get_business(self.bid)['status'], 'APPROVED')
        self.assertFalse(f.repo.get_business(self.bid)['whatsapp_connected'])
        self.assertNotEqual((f.repo.get_whatsapp_config(self.bid) or {}).get('connection_status'), 'CONNECTED')

    def test_success_shared_token_and_all_gates(self):
        r = self.post(); self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.json['status'], 'active')
        self.assertEqual(f.repo.get_business(self.bid)['status'], 'ACTIVE')
        config = f.repo.get_whatsapp_config(self.bid)
        self.assertEqual((config['waba_id'], config['phone_number_id'], config['credentials_reference']), ('500', '600', None))
        self.assertIsNotNone(subscription_service.get_subscription(self.bid))
        self.assertIsNone(f.repo.get_whatsapp_config(self.other))
        stored = f.repo.get_tenant_config_row(self.bid)['config']
        self.assertEqual(stored['preserved'], 'knowledge')
        self.assertEqual(stored['whatsapp']['connection_status'], 'CONNECTED')
        self.assertEqual(self.calls[5][1], '500/assigned_users')
        self.assertEqual(self.calls[5][2]['headers']['Authorization'], 'Bearer PRIVATE_ADMIN_TOKEN')
        self.assertEqual(self.calls[6][2]['headers']['Authorization'], 'Bearer PRIVATE_RUNTIME_TOKEN')
        self.assertNotIn('600/register', [c[1] for c in self.calls])
        for _, _, kwargs in self.calls:
            self.assertEqual(kwargs['timeout'], (3, 8)); self.assertFalse(kwargs['allow_redirects'])

    def test_business_app_requires_support_no_registration(self):
        self.biz_app = True; self.phone_status = 'PENDING'
        self.assertEqual(self.post().status_code, 400); self.assert_closed()
        self.assertNotIn('600/register', [c[1] for c in self.calls])

    def test_business_app_coexistence_discovers_phone_and_skips_registration(self):
        self.biz_app = True; self.phone_status = 'CONNECTED'
        data = self.payload(); data['coexistence'] = True; data['phone_number_id'] = None
        response = self.post(data)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json['connection_mode'], 'coexistence')
        self.assertNotIn('600/register', [c[1] for c in self.calls])
        config = f.repo.get_whatsapp_config(self.bid)
        self.assertEqual(config['phone_number_id'], '600')
        stored = f.repo.get_tenant_config_row(self.bid)['config']
        self.assertEqual(stored['whatsapp']['connection_mode'], 'COEXISTENCE')

    def test_register_when_required(self):
        self.phone_status = 'PENDING'
        self.assertEqual(self.post().status_code, 200)
        reg = [c for c in self.calls if c[1] == '600/register']
        self.assertEqual(len(reg), 1)
        self.assertRegex(reg[0][2]['json']['pin'], r'^\d{6}$')

    def test_replay_consumed_even_on_error(self):
        self.error_path = 'oauth/access_token'; data = self.payload()
        self.assertEqual(self.post(data).status_code, 400)
        count = self.http_mock.call_count
        self.assertEqual(self.post(data).status_code, 400)
        self.assertEqual(self.http_mock.call_count, count)
        self.assert_closed()

    def test_success_replay_no_duplicate_subscription(self):
        data = self.payload(); self.assertEqual(self.post(data).status_code, 200)
        count = self.http_mock.call_count
        self.assertEqual(self.post(data).status_code, 400)
        self.assertEqual(self.http_mock.call_count, count)
        self.assertEqual(f.db.query_one('SELECT COUNT(*) n FROM subscriptions WHERE business_id=?', (self.bid,))['n'], 1)

    def test_wrong_stale_expired_state(self):
        for change in ('wrong', 'expired', 'replaced'):
            data = self.payload()
            if change == 'wrong': data['state'] = 'wrong'
            elif change == 'expired': f.db.execute('UPDATE whatsapp_signup_sessions SET expires_at=0')
            else: signup.new_state(self.bid, self.uid)
            self.assertEqual(self.post(data).status_code, 400)
        self.http_mock.assert_not_called()

    def test_state_bound_to_business_and_user(self):
        data = self.payload()
        self.assertEqual(self.post(data, self.other).status_code, 400)
        with self.assertRaises(signup.SignupError): signup.consume_state(self.bid, self.uid+100, data['state'])
        self.http_mock.assert_not_called()

    def test_owner_and_login_required(self):
        uid = f.repo.create_user('other@example.test', f.security.hash_password('password123'))
        bid = f.repo.create_business(uid, 'Other', 'AI_ADMIN')
        self.assertEqual(self.client.get(f'/business/{bid}/whatsapp/connect').status_code, 404)
        self.assertEqual(self.post(self.payload(), bid).status_code, 404)
        anon = f.app.app.test_client()
        self.assertEqual(anon.get(f'/business/{self.bid}/whatsapp/connect').status_code, 302)
        self.assertEqual(anon.post(f'/business/{self.bid}/whatsapp/complete', json=self.payload()).status_code, 302)
        self.http_mock.assert_not_called()

    def test_csrf_required(self):
        with patch.dict(f.app.app.config, {'CLIENT_HUB_FORCE_CSRF_IN_TESTS': True}):
            self.assertEqual(self.post().status_code, 400)
            with self.client.session_transaction() as sess: sess['_csrf_token'] = 'test-csrf'
            r = self.client.post(f'/business/{self.bid}/whatsapp/complete', json=self.payload(), headers={'X-CSRF-Token': 'test-csrf'})
            self.assertEqual(r.status_code, 200)

    def test_no_verified_payment(self):
        self.paid_mock.return_value = False
        self.assertEqual(self.post().status_code, 400); self.http_mock.assert_not_called(); self.assert_closed()

    def test_nonapproved_or_wrong_package(self):
        for status in ('DRAFT', 'READY_FOR_REVIEW', 'ACTIVE', 'SUSPENDED'):
            f.db.execute('UPDATE businesses SET status=? WHERE id=?', (status, self.bid))
            self.assertEqual(self.post().status_code, 400)
        f.db.execute("UPDATE businesses SET status='APPROVED',package='NONE' WHERE id=?", (self.bid,))
        self.assertEqual(self.post().status_code, 400); self.http_mock.assert_not_called()

    def test_missing_config_or_env(self):
        with patch.dict(os.environ, {'META_APP_ID': ''}):
            self.assertEqual(self.post().status_code, 400)
            self.assertIn('belum tersedia', self.client.get(f'/business/{self.bid}/whatsapp/connect').get_data(as_text=True))
        f.db.execute('DELETE FROM tenant_configs WHERE business_id=?', (self.bid,))
        self.assertEqual(self.post().status_code, 400); self.http_mock.assert_not_called(); self.assert_closed()

    def test_customer_waba_grant_required(self):
        self.customer_grant = '501'
        self.assertEqual(self.post().status_code, 400); self.assert_closed()
        self.assertFalse(any(c[0] == 'POST' for c in self.calls))

    def test_provider_shared_access_required(self):
        self.provider_shared = False
        self.assertEqual(self.post().status_code, 400); self.assert_closed()
        self.assertFalse(any(c[0] == 'POST' for c in self.calls))

    def test_phone_mismatch(self):
        self.phone_match = False
        self.assertEqual(self.post().status_code, 400); self.assert_closed()

    def test_duplicate_phone_no_cross_tenant_write(self):
        f.repo.upsert_whatsapp_config(self.other, '600', '500', None, 'CONNECTED')
        before = f.repo.get_whatsapp_config(self.other)
        self.assertEqual(self.post().status_code, 400); self.http_mock.assert_not_called()
        self.assertEqual(before, f.repo.get_whatsapp_config(self.other)); self.assert_closed()

    def test_platform_phone_reserved(self):
        data = self.payload(); data['phone_number_id'] = '999'
        self.assertEqual(self.post(data).status_code, 400); self.http_mock.assert_not_called(); self.assert_closed()

    def test_http_failures_at_each_step(self):
        for path in ('oauth/access_token', 'debug_token', '500/phone_numbers', '300/client_whatsapp_business_accounts', '500/assigned_users', '500/subscribed_apps', '600', '600/register'):
            for status in (401, 403, 404, 500):
                self.error_path = path; self.fail_status = status; self.phone_status = 'PENDING'
                self.assertEqual(self.post().status_code, 400, path); self.assert_closed()

    def test_network_timeout(self):
        for error in (requests.Timeout('SECRET'), requests.ConnectionError('SECRET')):
            self.http_mock.side_effect = error
            with self.assertLogs('routes_whatsapp', level='WARNING') as logs: r = self.post()
            self.assertEqual(r.status_code, 400); self.assertNotIn('SECRET', ''.join(logs.output)); self.assert_closed()

    def test_existing_validator_failure_fail_closed(self):
        self.reachable_mock.return_value = (False, 'unauthorized')
        self.assertEqual(self.post().status_code, 400); self.assert_closed()

    def test_activation_failure_connected_not_active_then_retry(self):
        with patch.object(subscription_service, 'create_subscription', side_effect=RuntimeError('secret')):
            r = self.post()
        self.assertEqual(r.json['status'], 'connected')
        self.assertEqual(f.repo.get_business(self.bid)['status'], 'APPROVED')
        count = self.http_mock.call_count
        r = self.client.post(f'/business/{self.bid}/whatsapp/activate')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(f.repo.get_business(self.bid)['status'], 'ACTIVE')
        self.assertEqual(self.http_mock.call_count, count)

    def test_late_payment_change_cannot_activate(self):
        self.paid_mock.side_effect = [True, False]
        self.assertEqual(self.post().status_code, 400); self.assert_closed()

    def test_secrets_never_persist_or_render(self):
        page = self.client.get(f'/business/{self.bid}/whatsapp/connect').get_data(as_text=True)
        self.error_path = '500/subscribed_apps'
        with self.assertLogs('routes_whatsapp', level='WARNING') as logs: r = self.post()
        stored = json.dumps(f.db.query_all('SELECT * FROM whatsapp_signup_sessions')) + json.dumps(f.db.query_all('SELECT * FROM audit_log'))
        for secret in ('PRIVATE_CUSTOMER_TOKEN', 'PRIVATE_CODE', 'PRIVATE_RAW_ERROR', 'PRIVATE_APP_SECRET', 'PRIVATE_ADMIN_TOKEN', 'PRIVATE_RUNTIME_TOKEN', 'PRIVATE_PIN_KEY'):
            self.assertNotIn(secret, page + r.get_data(as_text=True) + stored + ''.join(logs.output))

    def test_callback_never_echoes_or_claims_success(self):
        r = self.client.get('/whatsapp/embedded-signup/callback?error_description=SECRET&code=SECRET', follow_redirects=True)
        self.assertNotIn('SECRET', r.get_data(as_text=True)); self.http_mock.assert_not_called()

    def test_migration_idempotent_preserves_history(self):
        state = self.payload(); before = f.db.query_all('SELECT * FROM whatsapp_signup_sessions')
        f.db.init_schema(); f.db.init_schema()
        self.assertEqual(before, f.db.query_all('SELECT * FROM whatsapp_signup_sessions'))
        signup.consume_state(self.bid, self.uid, state['state'])

    def test_manual_admin_validator_still_admin_only(self):
        with self.assertRaises(PermissionError): provisioning.validate_and_connect_whatsapp(self.bid, self.user, '600', '500', None)
        admin = dict(self.user, role='KILAS_ADMIN')
        result = provisioning.validate_and_connect_whatsapp(self.bid, admin, '600', '500', None)
        self.assertEqual(result['status'], 'CONNECTED')
        with self.assertRaises(PermissionError): provisioning.activate_tenant(self.bid, self.user)

    def test_pagination_does_not_follow_external_url(self):
        graph = signup.Graph(signup.settings())
        with patch.object(graph, 'call', side_effect=[{'data': [], 'paging': {'next': 'https://evil/secret', 'cursors': {'after': 'cursor'}}}, {'data': [{'id': '500'}]}]) as call:
            self.assertTrue(graph.contains('300/client_whatsapp_business_accounts', 'secret', '500'))
            self.assertEqual(call.call_args.args[1], '300/client_whatsapp_business_accounts')
            self.assertEqual(call.call_args.kwargs['params']['after'], 'cursor')

    def test_runtime_identity_mismatch_no_assignment(self):
        original = self.meta
        def meta(method, url, **kwargs):
            response = original(method, url, **kwargs)
            if url.endswith('/debug_token') and kwargs['params']['input_token'] == 'PRIVATE_RUNTIME_TOKEN':
                data = response.json(); data['data']['user_id'] = '9999'; response.json.return_value = data
            return response
        self.http_mock.side_effect = meta
        self.assertEqual(self.post().status_code, 400); self.assert_closed()
        self.assertFalse(any(c[0] == 'POST' for c in self.calls))

    def test_late_approval_change_no_binding(self):
        original = self.meta
        def meta(method, url, **kwargs):
            response = original(method, url, **kwargs)
            if url.endswith('/600'):
                f.db.execute("UPDATE businesses SET status='READY_FOR_REVIEW' WHERE id=?", (self.bid,))
            return response
        self.http_mock.side_effect = meta
        self.assertEqual(self.post().status_code, 400)
        self.assertFalse(f.repo.get_business(self.bid)['whatsapp_connected'])
        self.assertIsNone(f.repo.get_whatsapp_config(self.bid))

    def test_registration_pending_no_activation(self):
        original = self.meta; self.phone_status = 'PENDING'
        def meta(method, url, **kwargs):
            response = original(method, url, **kwargs)
            if url.endswith('/register'): self.phone_status = 'PENDING'
            return response
        self.http_mock.side_effect = meta
        self.assertEqual(self.post().status_code, 400); self.assert_closed()

    def test_success_does_not_store_oauth_or_provider_secrets(self):
        self.assertEqual(self.post().status_code, 200)
        persisted = ''.join(f.db.get_connection().iterdump())
        for value in ('PRIVATE_CUSTOMER_TOKEN','PRIVATE_CODE','PRIVATE_RUNTIME_TOKEN','PRIVATE_ADMIN_TOKEN','PRIVATE_APP_SECRET','PRIVATE_PIN_KEY'):
            self.assertNotIn(value, persisted)

    def test_request_size_limit(self):
        data = self.payload(); data['code'] = 'x'*9000
        self.assertEqual(self.post(data).status_code, 400); self.http_mock.assert_not_called()

    def test_concurrent_same_phone_only_one_tenant_binds(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        f.db.execute("UPDATE businesses SET status='APPROVED' WHERE id=?", (self.other,))
        f.repo.save_tenant_config(self.other, {'business_id': self.other, 'whatsapp': {}})
        barrier = threading.Barrier(2)
        def run(bid):
            barrier.wait(timeout=5)
            try:
                return provisioning.complete_self_service_whatsapp(bid, self.user, '500', '600')['status']
            except signup.SignupError as exc:
                return str(exc)
            finally:
                f.db.get_connection().close(); f.db._local.conn = None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, [self.bid, self.other]))
        self.assertEqual(sorted(results), ['ACTIVE', 'duplicate_phone'])
        self.assertEqual(f.db.query_one("SELECT COUNT(*) n FROM tenant_whatsapp_config WHERE phone_number_id='600'")['n'], 1)

    def test_transaction_rolls_back_nested_config_write(self):
        before = f.repo.get_tenant_config_row(self.bid)
        with patch.object(provisioning, '_activate_tenant_core', side_effect=RuntimeError('fail after config save')):
            self.assertEqual(self.post().status_code, 503)
        self.assert_closed()
        self.assertEqual(before, f.repo.get_tenant_config_row(self.bid))

    def test_signup_migration_postgres_sql_compatible_with_sqlite(self):
        from pathlib import Path
        pg = Path(signup.__file__).parent / 'migrations/0027_whatsapp_signup_postgres.sql'
        # Both migrations deliberately use the common SQL subset; not a live PostgreSQL test.
        self.assertEqual(pg.read_text(), pg.with_name('0027_whatsapp_signup_sqlite.sql').read_text())

if __name__ == '__main__': unittest.main()
