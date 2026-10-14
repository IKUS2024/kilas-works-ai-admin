"""Real app auth lifecycle; isolated SQLite, no provider transport or production writes."""
import json
import time
import unittest
from datetime import datetime,timedelta,timezone
from http.cookies import SimpleCookie
from unittest.mock import patch
import test_kilas_home as fixture
import customer_auth as auth
import customer_auth_schema as schema
import security
from itsdangerous.timed import TimestampSigner


class CustomerAuthTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture.HomeTests('test_old_routes_still_render');self.base.id=lambda:self.id();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.app=fixture.fixture.base.f.fixture.app.app
        self.db=fixture.fixture.base.f.fixture.db
        self.repo=fixture.fixture.base.f.fixture.repo
        self.owner=self.base.owner;self.other=self.base.other
        self.password='isolated-login-password'
        self.repo.update_user_password(self.owner,security.hash_password(self.password))
        self.email=self.repo.get_user_by_id(self.owner)['email']

    def csrf(self,client,path='/login'):
        client.get(path)
        with client.session_transaction() as state:return state['_csrf_token']

    def login(self):
        c=self.app.test_client();token=self.csrf(c)
        result=c.post('/login',data={'email':self.email,'password':self.password,'csrf_token':token})
        self.assertEqual(result.status_code,302)
        self.assertEqual(result.location,'/products/start')
        return c,result

    def copied(self,client):
        c=self.app.test_client();c.set_cookie('session',client.get_cookie('session').value);return c

    def denied(self,client):
        response=client.get('/products/start');self.assertIn(response.status_code,(302,303));self.assertEqual(response.location,'/login')

    def test_customer_cookie_persistent_secure_and_original_signing_key(self):
        with patch.dict(self.app.config,{'SESSION_COOKIE_SECURE':True}):
            client,result=self.login();header=next(h for h in result.headers.getlist('Set-Cookie') if h.startswith('session='));cookie=SimpleCookie();cookie.load(header)
            self.assertTrue(cookie['session']['expires']);self.assertTrue(cookie['session']['secure']);self.assertTrue(cookie['session']['httponly']);self.assertEqual(cookie['session']['samesite'],'Lax');self.assertFalse(cookie['session']['domain']);self.assertEqual(cookie['session']['path'],'/')
        with client.session_transaction() as state:
            self.assertTrue(state.permanent);self.assertNotIn('_last_activity_at',state);self.assertEqual(len(state[auth.SID]),64)
        self.assertEqual(self.db.query_one('SELECT COUNT(*) AS n FROM customer_auth_sessions WHERE user_id=?',(self.owner,))['n'],1)

    def test_inactivity_beyond_old_idle_and_signature_age_does_not_logout(self):
        client,_=self.login();old=self.copied(client)
        with client.session_transaction() as state:state['_last_activity_at']=int(time.time())-400*86400
        self.assertEqual(client.get('/products/start').status_code,200)
        with patch.object(TimestampSigner,'get_timestamp',return_value=int(time.time())+365*86400):
            self.assertEqual(old.get('/products/start').status_code,200)

    def test_cross_module_continuity_home_launch_and_deep_link_refresh(self):
        client,_=self.login()
        with client.session_transaction() as state:state['active_product']='finance';sid=state[auth.SID]
        for path in ('/products/start','/kilas-translator?mode=voiceover','/kilas-ai/video','/products/finance'):
            self.assertNotEqual(client.get(path).location,'/login')
        self.assertEqual(client.get('/').location,'/products/start')
        for _ in range(2):
            page=client.get('/kilas-translator?mode=voiceover');self.assertEqual(page.status_code,200);self.assertIsNone(page.location);self.assertIn('data-active-mode="voiceover"',page.text)
        with client.session_transaction() as state:self.assertEqual(state[auth.SID],sid)

    def test_logout_revokes_all_copies_of_one_session_and_keeps_other_device(self):
        first,_=self.login();copy=self.copied(first);second,_=self.login()
        self.assertEqual(first.get('/logout').location,'/login')
        self.denied(copy);self.denied(first)
        self.assertEqual(second.get('/products/start').status_code,200)

    def test_password_change_real_route_revokes_prior_devices(self):
        first,_=self.login();copy=self.copied(first);second,_=self.login();token=self.csrf(first,'/account')
        response=first.post('/account',data={'action':'password','current_password':self.password,'new_password':'isolated-new-password','confirm_password':'isolated-new-password','csrf_token':token})
        self.assertEqual(response.location,'/login');self.denied(copy);self.denied(second)
        self.assertEqual(self.db.query_one('SELECT COUNT(*) AS n FROM customer_auth_sessions WHERE user_id=? AND revoked_at IS NULL',(self.owner,))['n'],0)

    def test_password_reset_real_route_revokes_prior_devices_and_burns_link(self):
        first,_=self.login();second,_=self.login();raw,digest=security.generate_reset_token()
        self.repo.create_password_reset_token(self.owner,digest,(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat())
        anon=self.app.test_client();token=self.csrf(anon,'/reset-password/'+raw)
        response=anon.post('/reset-password/'+raw,data={'password':'isolated-reset-password','confirm_password':'isolated-reset-password','csrf_token':token})
        self.assertEqual(response.location,'/login');self.denied(first);self.denied(second)
        self.assertIsNone(self.repo.get_valid_reset_token(digest,datetime.now(timezone.utc).isoformat()))

    def test_backend_password_change_fails_closed_even_if_revoke_write_did_not_run(self):
        client,_=self.login();self.db.execute('UPDATE users SET password_hash=? WHERE id=?',('synthetic-changed-hash',self.owner));self.denied(client)

    def test_account_disable_reenable_does_not_resurrect_prior_cookie(self):
        client,_=self.login();copy=self.copied(client);auth.set_account_disabled(self.owner)
        self.denied(client);auth.set_account_disabled(self.owner,False);self.denied(copy)
        current,_=self.login();self.assertEqual(current.get('/products/start').status_code,200)

    def test_disabled_account_cannot_obtain_new_login(self):
        auth.set_account_disabled(self.owner);client=self.app.test_client();csrf=self.csrf(client)
        response=client.post('/login',data={'email':self.email,'password':self.password,'csrf_token':csrf})
        self.assertEqual(response.status_code,200)
        with client.session_transaction() as state:self.assertNotIn('user_id',state)

    def test_server_revoke_role_change_and_deleted_account_are_checked(self):
        for event in ('revoke','role','delete'):
            client,_=self.login()
            if event=='revoke':auth.revoke_all(self.owner)
            elif event=='role':self.db.execute("UPDATE users SET role='KILAS_ADMIN' WHERE id=?",(self.owner,))
            else:
                with patch.object(auth.db,'query_one',return_value=None):self.denied(client)
                continue
            self.denied(client)
            if event=='role':self.db.execute("UPDATE users SET role='CLIENT_OWNER' WHERE id=?",(self.owner,))

    def test_legacy_cookie_requires_once_relogin_preserves_server_work(self):
        client=self.app.test_client()
        before=self.db.query_one('SELECT COUNT(*) AS n FROM kilas_ai_conversations')['n']
        with client.session_transaction() as state:state.update(user_id=self.owner,role='CLIENT_OWNER',_last_activity_at=int(time.time()))
        self.denied(client)
        self.assertEqual(self.db.query_one('SELECT COUNT(*) AS n FROM kilas_ai_conversations')['n'],before)
        new,_=self.login();self.assertEqual(new.get('/products/start').status_code,200)

    def test_cookie_tampering_and_cross_owner_token_do_not_authenticate(self):
        client,_=self.login()
        with client.session_transaction() as state:state['user_id']=self.other
        self.denied(client)
        client,_=self.login();copy=self.app.test_client();copy.set_cookie('session',client.get_cookie('session').value+'x')
        self.assertEqual(copy.get('/products/start').location,'/login')

    def test_csrf_and_tenant_membership_remain_authoritative(self):
        client,_=self.login();self.assertEqual(client.post('/products/start',data={'product':'finance'}).status_code,400)
        foreign=self.repo.create_business(self.other,'Foreign private business')
        owned=self.repo.create_business(self.owner,'Owned business')
        finance=__import__('finance_service');finance.ensure_finance_defaults(owned);finance.ensure_finance_defaults(foreign)
        with patch.dict(__import__('os').environ,{'KILAS_FINANCE_BETA':'on'}):
            self.assertEqual(client.get('/business/'+str(owned)+'/finance').status_code,200)
            self.assertEqual(client.get('/business/'+str(foreign)+'/finance').status_code,404)
            self.db.execute('DELETE FROM business_memberships WHERE user_id=? AND business_id=?',(self.owner,owned))
            self.assertEqual(client.get('/business/'+str(owned)+'/finance').status_code,404)
        self.assertEqual(self.db.query_one('SELECT COUNT(*) AS n FROM business_memberships WHERE user_id=? AND business_id=?',(self.owner,foreign))['n'],0)

    def test_schema_is_idempotent_and_database_failure_never_admits_cookie(self):
        client,_=self.login();before=self.db.query_all('SELECT * FROM customer_auth_sessions WHERE user_id=?',(self.owner,));schema.apply();schema.apply()
        self.assertEqual(before,self.db.query_all('SELECT * FROM customer_auth_sessions WHERE user_id=?',(self.owner,)))
        with patch.object(auth,'validate',side_effect=RuntimeError('synthetic database outage')):
            self.assertEqual(client.get('/products/start').status_code,503)
            asset=client.get('/static/kilas-new-chat-logo-lossless.webp')
            self.assertEqual(asset.status_code,200);self.assertNotIn('Set-Cookie',asset.headers)

    def test_admin_policy_stays_separate_and_retains_flask_age_bound(self):
        admin=self.repo.create_user(self.id()+'-admin@example.test','synthetic',role='KILAS_ADMIN')
        client=self.app.test_client()
        from auth_test_helpers import authenticate
        authenticate(client,self.repo.get_user_by_id(admin))
        with client.session_transaction() as state:self.assertNotIn(auth.SID,state)
        self.assertEqual(self.db.query_one('SELECT COUNT(*) AS n FROM customer_auth_sessions WHERE user_id=?',(admin,))['n'],0)
        with patch.object(TimestampSigner,'get_timestamp',return_value=int(time.time())+32*86400):
            self.assertEqual(client.get('/').location,'/login')

    def test_registration_and_oauth_use_same_revocable_customer_login(self):
        client=self.app.test_client();csrf=self.csrf(client)
        result=client.post('/register',data={'email':self.id()+'-new@example.test','full_name':'Synthetic account',
                          'password':self.password,'csrf_token':csrf})
        self.assertEqual(result.location,'/products/start')
        with client.session_transaction() as state:self.assertTrue(state.permanent);self.assertTrue(state[auth.SID])
        from routes_auth import _oauth_finish_login
        with self.app.test_request_context('/oauth/google/callback'):
            result=_oauth_finish_login(self.email,'Synthetic OAuth','google','synthetic-subject-'+str(self.owner))
            from flask import session
            self.assertEqual(result.location,'/products/start');self.assertTrue(session.permanent);self.assertTrue(auth.validate())

    def test_role_reversion_cannot_resurrect_a_detected_invalid_session(self):
        client,_=self.login();copy=self.copied(client)
        self.db.execute("UPDATE users SET role='KILAS_ADMIN' WHERE id=?",(self.owner,));self.denied(client)
        self.db.execute("UPDATE users SET role='CLIENT_OWNER' WHERE id=?",(self.owner,));self.denied(copy)

    def test_account_revocation_fences_a_login_insert_already_in_flight(self):
        original=self.db.execute;fired=[]
        def interleave(sql,params=()):
            if sql.startswith('INSERT INTO customer_auth_sessions') and not fired:
                fired.append(True);auth.revoke_all(self.owner)
            return original(sql,params)
        with self.app.test_request_context(),patch.object(self.db,'execute',side_effect=interleave):
            token=auth.create(self.repo.get_user_by_id(self.owner))
            from flask import session
            session.update(user_id=self.owner,role='CLIENT_OWNER');session[auth.SID]=token
            self.assertFalse(auth.validate())
        self.assertTrue(fired)


if __name__=='__main__':unittest.main()
