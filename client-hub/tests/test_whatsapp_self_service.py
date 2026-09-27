"""Assisted-only release contract over the retired Embedded Signup endpoints.

The final master explicitly retires customer Embedded Signup and Coexistence. Every old
route scenario remains exercised, now asserting no transport, mapping, activation or
subscription write. Direct helper security tests remain; assisted connection tests cover
positive mapping, signed inbound/outbound evidence, ownership and activation rollback.
"""
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
        # Current validator requires the owner's declared business number before binding.
        for bid in (self.bid,self.other):
            f.repo.upsert_business_profile(bid, {'business_phone':'628123456789'})
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

    def assert_retired(self, data=None, bid=None):
        data=data or self.payload()
        tables=('businesses','tenant_configs','tenant_whatsapp_config','subscriptions','payments','invoices','audit_log')
        before={t:f.db.query_all('SELECT * FROM '+t) for t in tables}
        result=self.post(data,bid)
        self.assertEqual(result.status_code,410)
        self.http_mock.assert_not_called()
        self.reachable_mock.assert_not_called()
        self.assertEqual(before,{t:f.db.query_all('SELECT * FROM '+t) for t in tables})
        return result

    def test_success_shared_token_and_all_gates(self):
        self.assert_retired()

    def test_business_app_requires_support_no_registration(self):
        self.biz_app=True; self.phone_status='PENDING'
        self.assert_retired()

    def test_business_app_coexistence_discovers_phone_and_skips_registration(self):
        self.biz_app=True
        data=self.payload(); data.update(coexistence=True,phone_number_id=None)
        self.assert_retired(data)

    def test_active_web_business_can_connect_optional_whatsapp(self):
        f.db.execute("UPDATE businesses SET status='ACTIVE' WHERE id=?",(self.bid,))
        self.assert_retired()

    def test_pending_whatsapp_page_exposes_web_skip_without_meta_claim(self):
        page=self.client.get(f'/business/{self.bid}/whatsapp/connect')
        self.assertEqual(page.status_code,303)
        self.assertTrue(page.location.endswith('/assist-whatsapp'))
        page=self.client.get(page.location)
        self.assertEqual(page.status_code,200)
        for text in ('Web Chat','Coexistence','wa-config','App Review'):
            self.assertNotIn(text,page.text)
        self.http_mock.assert_not_called()

    def test_register_when_required(self):
        self.phone_status='PENDING'
        self.assert_retired()

    def test_replay_consumed_even_on_error(self):
        self.error_path='oauth/access_token'
        data=self.payload()
        self.assert_retired(data); self.assert_retired(data)

    def test_success_replay_no_duplicate_subscription(self):
        data=self.payload()
        self.assert_retired(data); self.assert_retired(data)
        self.assertEqual(f.db.query_one('SELECT COUNT(*) n FROM subscriptions WHERE business_id=?',(self.bid,))['n'],0)

    def test_wrong_stale_expired_state(self):
        for change in ('wrong','expired','replaced'):
            data=self.payload()
            if change=='wrong':data['state']='wrong'
            elif change=='expired':f.db.execute('UPDATE whatsapp_signup_sessions SET expires_at=0')
            else:signup.new_state(self.bid,self.uid)
            self.assert_retired(data)

    def test_state_bound_to_business_and_user(self):
        data=self.payload()
        self.assert_retired(data,bid=self.other)
        with self.assertRaises(signup.SignupError):signup.consume_state(self.bid,self.uid+100,data['state'])

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
        with patch.dict(f.app.app.config,{'CLIENT_HUB_FORCE_CSRF_IN_TESTS':True}):
            self.assertEqual(self.post().status_code,400)
            with self.client.session_transaction() as sess:sess['_csrf_token']='test-csrf'
            r=self.client.post(f'/business/{self.bid}/whatsapp/complete',json=self.payload(),headers={'X-CSRF-Token':'test-csrf'})
            self.assertEqual(r.status_code,410)
        self.http_mock.assert_not_called(); self.assert_closed()

    def test_no_verified_payment(self):
        self.paid_mock.return_value=False
        self.assert_retired()

    def test_nonapproved_or_wrong_package(self):
        for status in ('DRAFT','READY_FOR_REVIEW','ACTIVE','SUSPENDED'):
            f.db.execute('UPDATE businesses SET status=? WHERE id=?',(status,self.bid))
            self.assert_retired()
        f.db.execute("UPDATE businesses SET status='APPROVED',package='NONE' WHERE id=?",(self.bid,))
        self.assert_retired()

    def test_missing_config_or_env(self):
        with patch.dict(os.environ,{'META_APP_ID':''}):self.assert_retired()
        f.db.execute('DELETE FROM tenant_configs WHERE business_id=?',(self.bid,))
        self.assert_retired()

    def test_customer_waba_grant_required(self):
        self.customer_grant='501'
        self.assert_retired()

    def test_provider_shared_access_required(self):
        self.provider_shared=False
        self.assert_retired()

    def test_phone_mismatch(self):
        self.phone_match=False
        self.assert_retired()

    def test_duplicate_phone_no_cross_tenant_write(self):
        f.repo.upsert_whatsapp_config(self.other,'600','500',None,'CONNECTED')
        self.assert_retired()

    def test_platform_phone_reserved(self):
        data=self.payload(); data['phone_number_id']='999'
        self.assert_retired(data)

    def test_http_failures_at_each_step(self):
        for path in ('oauth/access_token','debug_token','500/phone_numbers','300/client_whatsapp_business_accounts','500/assigned_users','500/subscribed_apps','600','600/register'):
            for status in (401,403,404,500):
                self.error_path=path;self.fail_status=status;self.phone_status='PENDING'
                self.assert_retired()

    def test_network_timeout(self):
        for error in (requests.Timeout('SECRET'),requests.ConnectionError('SECRET')):
            self.http_mock.side_effect=error
            self.assert_retired()

    def test_existing_validator_failure_fail_closed(self):
        self.reachable_mock.return_value=(False,'unauthorized')
        self.assert_retired()

    def test_activation_failure_connected_not_active_then_retry(self):
        with patch.object(subscription_service,'create_subscription',side_effect=RuntimeError('secret')) as activate:
            self.assert_retired();activate.assert_not_called()
        self.assertEqual(self.client.post(f'/business/{self.bid}/whatsapp/activate').status_code,410)
        self.assert_closed()

    def test_late_payment_change_cannot_activate(self):
        self.paid_mock.side_effect=[True,False]
        self.assert_retired()
        self.paid_mock.assert_not_called()

    def test_secrets_never_persist_or_render(self):
        page=self.client.get(f'/business/{self.bid}/whatsapp/connect',follow_redirects=True)
        r=self.assert_retired()
        stored=json.dumps(f.db.query_all('SELECT * FROM whatsapp_signup_sessions'))+json.dumps(f.db.query_all('SELECT * FROM audit_log'))
        for value in ('PRIVATE_CUSTOMER_TOKEN','PRIVATE_CODE','PRIVATE_RAW_ERROR','PRIVATE_APP_SECRET','PRIVATE_ADMIN_TOKEN','PRIVATE_RUNTIME_TOKEN','PRIVATE_PIN_KEY'):
            self.assertNotIn(value,page.text+r.text+stored)

    def test_callback_never_echoes_or_claims_success(self):
        r = self.client.get('/whatsapp/embedded-signup/callback?error_description=SECRET&code=SECRET', follow_redirects=True)
        self.assertNotIn('SECRET', r.get_data(as_text=True)); self.http_mock.assert_not_called()

    def test_migration_idempotent_preserves_history(self):
        state = self.payload(); before = f.db.query_all('SELECT * FROM whatsapp_signup_sessions')
        f.db.init_schema(); f.db.init_schema()
        self.assertEqual(before, f.db.query_all('SELECT * FROM whatsapp_signup_sessions'))
        signup.consume_state(self.bid, self.uid, state['state'])

    def test_manual_admin_validator_still_admin_only(self):
        with self.assertRaises(PermissionError):provisioning.validate_and_connect_whatsapp(self.bid,self.user,'600','500',None)
        admin=dict(self.user,role='KILAS_ADMIN')
        with self.assertRaisesRegex(provisioning.ProvisioningError,'assisted_connection_required'):
            provisioning.validate_and_connect_whatsapp(self.bid,admin,'600','500',None)
        with self.assertRaises(PermissionError):provisioning.activate_tenant(self.bid,self.user)
        self.assert_closed()

    def test_pagination_does_not_follow_external_url(self):
        graph = signup.Graph(signup.settings())
        with patch.object(graph, 'call', side_effect=[{'data': [], 'paging': {'next': 'https://evil/secret', 'cursors': {'after': 'cursor'}}}, {'data': [{'id': '500'}]}]) as call:
            self.assertTrue(graph.contains('300/client_whatsapp_business_accounts', 'secret', '500'))
            self.assertEqual(call.call_args.args[1], '300/client_whatsapp_business_accounts')
            self.assertEqual(call.call_args.kwargs['params']['after'], 'cursor')

    def test_runtime_identity_mismatch_no_assignment(self):
        self.customer_grant='9999'
        self.assert_retired()

    def test_late_approval_change_no_binding(self):
        f.db.execute("UPDATE businesses SET status='READY_FOR_REVIEW' WHERE id=?",(self.bid,))
        self.assert_retired()

    def test_registration_pending_no_activation(self):
        self.phone_status='PENDING'
        self.assert_retired()

    def test_success_does_not_store_oauth_or_provider_secrets(self):
        self.assert_retired()
        persisted=''.join(f.db.get_connection().iterdump())
        for value in ('PRIVATE_CUSTOMER_TOKEN','PRIVATE_CODE','PRIVATE_RUNTIME_TOKEN','PRIVATE_ADMIN_TOKEN','PRIVATE_APP_SECRET','PRIVATE_PIN_KEY'):
            self.assertNotIn(value,persisted)

    def test_platform_identity_uses_internal_bot_bridge(self):
        fake_identity = {'phone_number_id': '999', 'display_phone_number': '+62 822-1303-9137',
                         'display_phone_digits': '6282213039137', 'status': 'CONNECTED',
                         'is_on_biz_app': False, 'platform_type': 'CLOUD_API'}
        with patch.object(signup, '_platform_bot_call',
                          return_value={'status': 'ok', 'identity': fake_identity}) as bridge:
            identity = signup.platform_current_identity()
        self.assertEqual(identity['display_phone_digits'], '6282213039137')
        bridge.assert_called_once_with('status')

    def test_platform_deregister_uses_internal_bot_bridge(self):
        fake_identity = {'phone_number_id': '999', 'display_phone_digits': '6282213039137'}
        with patch.object(signup, '_platform_bot_call',
                          return_value={'status': 'ok', 'identity': fake_identity}) as bridge:
            identity = signup.deregister_platform_phone('6282213039137')
        self.assertEqual(identity['phone_number_id'], '999')
        bridge.assert_called_once_with('deregister', {'expected_phone_digits': '6282213039137'})

    def test_platform_coexistence_browser_grant_then_runtime_bridge(self):
        original = self.meta
        self.biz_app = True
        def meta(method, url, **kwargs):
            response = original(method, url, **kwargs)
            if url.endswith('/600'):
                response.json.return_value = {
                    'id': '600', 'display_phone_number': '+62 822-1303-9137',
                    'status': 'CONNECTED', 'is_on_biz_app': True, 'platform_type': 'CLOUD_API'}
            elif url.endswith('/500/phone_numbers'):
                response.json.return_value = {
                    'data': [{'id': '600', 'display_phone_number': '+62 822-1303-9137'}]}
            return response
        self.http_mock.side_effect = meta
        with patch.object(signup, '_platform_bot_call',
                          return_value={'status': 'ok', 'phone_number_id': '600', 'waba_id': '500'}) as bridge:
            waba, phone = signup.verify_platform_coexistence(
                'PRIVATE_CODE', '500', '600', expected_phone_digits='6282213039137')
        self.assertEqual((waba, phone), ('500', '600'))
        bridge.assert_called_once_with('verify', {
            'waba_id': '500', 'phone_number_id': '600',
            'expected_phone_digits': '6282213039137'})

    def test_request_size_limit(self):
        data=self.payload();data['code']='x'*9000
        self.assert_retired(data)

    def test_concurrent_same_phone_only_one_tenant_binds(self):
        from concurrent.futures import ThreadPoolExecutor
        f.db.execute("UPDATE businesses SET status='APPROVED' WHERE id=?",(self.other,))
        f.repo.save_tenant_config(self.other,{'business_id':self.other,'whatsapp':{}})
        def run(bid):
            try:
                with self.assertRaisesRegex(provisioning.ProvisioningError,'assisted_connection_required'):
                    provisioning.complete_self_service_whatsapp(bid,self.user,'500','600')
            finally:
                f.db.get_connection().close();f.db._local.conn=None
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,[self.bid,self.other]))
        self.assertEqual(f.db.query_one("SELECT COUNT(*) n FROM tenant_whatsapp_config WHERE phone_number_id='600'")['n'],0)

    def test_transaction_rolls_back_nested_config_write(self):
        with patch.object(provisioning,'_activate_tenant_core',side_effect=RuntimeError('fail after config save')) as activate:
            self.assert_retired();activate.assert_not_called()

    def test_signup_migration_postgres_sql_compatible_with_sqlite(self):
        from pathlib import Path
        pg = Path(signup.__file__).parent / 'migrations/0027_whatsapp_signup_postgres.sql'
        # Both migrations deliberately use the common SQL subset; not a live PostgreSQL test.
        self.assertEqual(pg.read_text(), pg.with_name('0027_whatsapp_signup_sqlite.sql').read_text())

if __name__ == '__main__': unittest.main()
