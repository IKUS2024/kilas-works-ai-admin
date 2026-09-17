import os, sys, unittest, io, contextlib, threading
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import test_business_hub_v2_phase_a as auth_fixture
import repo, db, security, email_utils, subscription_service as subs, tenant_config_service as tcs
import catalog_service, projects_repo, payment_service, app as hub

class TargetedHubTests(unittest.TestCase):
    def setUp(self):
        auth_fixture.reset_db();catalog_service.seed_catalog_if_needed()
        self.uid=repo.create_user('targeted@test.com',security.hash_password('password123'))
        self.bid=repo.create_business(self.uid,'Targeted Business','AI_ADMIN_BASIC')
        repo.upsert_business_profile(self.bid,{'short_description':'old','tone':'friendly','primary_language':'id','customer_salutation':'Kak'})
        db.execute("UPDATE businesses SET status='ACTIVE' WHERE id=?",(self.bid,))
        self.client=hub.app.test_client()
        self.client.post('/login',data={'email':'targeted@test.com','password':'password123'})

    def memory(self):
        return dict(short_description='Bisnis milik sendiri',tone='ramah singkat',primary_language='id',customer_salutation='Kak',operating_hours='09-17',closed_days='Minggu',address='Jakarta',business_phone='62811',services_raw='Kopi susu Rp20.000',faq_raw='Buka kapan? | Senin-Sabtu')

    def subscribe(self,package='AI_ADMIN_BASIC'):
        if package!='AI_ADMIN_BASIC':
            db.execute('UPDATE businesses SET package=? WHERE id=?',(package,self.bid));repo.set_tenant_features_for_package(self.bid,package)
        return subs.create_subscription(self.bid,package.lower())

    def pro_receipt(self):
        item=catalog_service.get_catalog_item('ai_admin_pro')
        project=projects_repo.create_fixed_price_project(self.bid,item,self.uid)
        invoice=payment_service.checkout(project,self.bid,self.uid)
        payment=payment_service.get_payment_for_invoice(invoice)
        db.execute("UPDATE payments SET status='VERIFIED', verified_at=? WHERE id=?",(datetime.now(timezone.utc).isoformat(),payment['id']))
        return payment['id']

    def test_smtp_exception_and_unknown_email_have_identical_http_response(self):
        with patch.object(email_utils,'send_password_reset_email',side_effect=TimeoutError('secret-value')):
            with contextlib.redirect_stdout(io.StringIO()) as logs:
                a=self.client.post('/forgot-password',data={'email':'targeted@test.com'})
                b=self.client.post('/forgot-password',data={'email':'absent@test.com'})
        self.assertEqual(a.status_code,200);self.assertEqual(a.data,b.data)
        self.assertNotIn('secret-value',logs.getvalue())

    def test_smtp_transport_failure_safe_and_redacted(self):
        env={'APP_ENV':'production','SMTP_HOST':'smtp.test','SMTP_USERNAME':'private','SMTP_PASSWORD':'secret','SMTP_PORT':'587'}
        with patch.dict(os.environ,env),patch.object(email_utils.smtplib,'SMTP',side_effect=TimeoutError('secret')),contextlib.redirect_stdout(io.StringIO()) as logs:
            self.assertFalse(email_utils._deliver_password_reset_email('private@test.com','https://app.test/token-secret'))
        self.assertIn('TimeoutError',logs.getvalue());self.assertNotIn('private',logs.getvalue());self.assertNotIn('token-secret',logs.getvalue())

    def test_production_smtp_latency_is_off_http_thread(self):
        started=threading.Event();release=threading.Event()
        def slow(*args):started.set();release.wait(3);return False
        with patch.dict(os.environ,{'APP_ENV':'production','SMTP_HOST':'smtp.test','SMTP_USERNAME':'u','SMTP_PASSWORD':'p'}),patch.object(email_utils,'_deliver_password_reset_email',side_effect=slow):
            try:
                self.assertFalse(email_utils.send_password_reset_email('targeted@test.com','https://app.test/reset'))
                self.assertTrue(started.wait(1));self.assertFalse(release.is_set())
            finally:release.set();email_utils._mail_queue.join()

    def test_missing_smtp_returns_false_no_token_log(self):
        for mode in ('production', 'development'):
            with self.subTest(mode=mode), patch.dict(os.environ,{'APP_ENV':mode,'CLIENT_HUB_ENV':mode,'SMTP_HOST':'','SMTP_USERNAME':'','SMTP_PASSWORD':''}),contextlib.redirect_stdout(io.StringIO()) as logs:
                self.assertFalse(email_utils.send_password_reset_email('targeted@test.com','secret-token'))
            self.assertNotIn('secret-token',logs.getvalue());self.assertNotIn('targeted@test.com',logs.getvalue())

    def test_secure_cookie_and_environment_production_wins(self):
        for env in ({'APP_ENV':'production','CLIENT_HUB_ENV':'development'},{'APP_ENV':'development','CLIENT_HUB_ENV':'production'}):
            with self.subTest(env=env),patch.dict(os.environ,env):
                app=hub.create_app();self.assertTrue(app.config['SESSION_COOKIE_SECURE'])
                self.assertTrue(email_utils._is_production())
                c=app.test_client();page=c.get('/login',base_url='https://localhost')
                import re
                token=re.search(r'name="csrf_token" value="([^"]+)"',page.data.decode()).group(1)
                r=c.post('/login',base_url='https://localhost',data={'email':'targeted@test.com','password':'password123','csrf_token':token})
                self.assertEqual(r.status_code,302)
                self.assertIn('Secure',r.headers.get('Set-Cookie',''))

    def test_reset_url_uses_configured_https_base(self):
        with patch.dict(os.environ,{'APP_ENV':'production','PUBLIC_APP_BASE_URL':'https://app.kilasworks.id'}):
            self.assertEqual(email_utils.build_reset_url('http://evil.test/reset','token'),'https://app.kilasworks.id/reset-password/token')
        with patch.dict(os.environ,{'APP_ENV':'production','PUBLIC_APP_BASE_URL':''}):
            with self.assertRaises(ValueError):email_utils.build_reset_url('http://evil.test/reset','token')

    def test_reset_expiry(self):
        raw,hashed=security.generate_reset_token();repo.create_password_reset_token(self.uid,hashed,(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),'test')
        r=self.client.post('/reset-password/'+raw,data={'password':'newpass123','confirm_password':'newpass123'})
        self.assertEqual(r.status_code,302);self.assertIn('forgot-password',r.location)

    def test_reset_single_use(self):
        raw,hashed=security.generate_reset_token();repo.create_password_reset_token(self.uid,hashed,(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),'test')
        r=self.client.post('/reset-password/'+raw,data={'password':'newpass123','confirm_password':'newpass123'})
        self.assertEqual(r.status_code,302);self.assertIn('login',r.location)
        r=self.client.post('/reset-password/'+raw,data={'password':'otherpass123','confirm_password':'otherpass123'})
        self.assertIn('forgot-password',r.location)

    def test_active_tenant_edits_live_memory_without_reonboarding(self):
        r=self.client.post(f'/business/{self.bid}/memory',data=self.memory())
        self.assertEqual(r.status_code,302)
        config=tcs.get_tenant_config(self.bid)
        self.assertEqual(config['ai']['tone'],'ramah singkat');self.assertEqual(config['ai']['system_instructions'],'Bisnis milik sendiri')
        self.assertEqual(config['knowledge']['services'][0]['raw_input'],'Kopi susu Rp20.000')
        self.assertEqual(config['knowledge']['faq'][0]['answer'],'Senin-Sabtu')
        self.assertEqual(repo.get_business(self.bid)['status'],'ACTIVE')
        self.assertEqual(config['business_info']['business_hours']['raw'],'09-17')

    def test_cross_tenant_memory_get_and_post_denied(self):
        other=repo.create_user('other@test.com','unused');bid=repo.create_business(other,'Foreign','AI_ADMIN_PRO')
        for method in ('get','post'):
            response=getattr(self.client,method)(f'/business/{bid}/memory',**({'data':self.memory()} if method=='post' else {}))
            self.assertIn(response.status_code,(403,404))
        self.assertNotEqual((repo.get_business_profile(bid) or {}).get('short_description'),'Bisnis milik sendiri')

    def test_memory_cannot_change_package_or_global_fields(self):
        data=self.memory();data.update(package='AI_ADMIN_PRO',trusted_owner_phone='evil',features_enabled='all')
        self.client.post(f'/business/{self.bid}/memory',data=data)
        self.assertEqual(repo.get_business(self.bid)['package'],'AI_ADMIN_BASIC')
        self.assertFalse(repo.get_tenant_features(self.bid)['owner_commands'])

    def test_basic_pro_settings_post_and_direct_ai_endpoint_denied(self):
        for url,data in [(f'/business/{self.bid}/settings',{'appointment_enabled':'on'}),(f'/business/{self.bid}/wizard/operations',{'trusted_owner_phone':'62811'}),(f'/business/{self.bid}/ai-writing-help',{'field_type':'payment_instructions','action':'draft'})]:
            with self.subTest(url=url):self.assertIn(self.client.post(url,data=data).status_code,(302,403))
        self.assertEqual(self.client.post(f'/business/{self.bid}/settings',data={'payment_account_number':'1234'}).status_code,403)
        body=self.client.get(f'/business/{self.bid}/settings').data.decode()
        self.assertNotIn('name="payment_account_number"',body);self.assertNotIn('name="appointment_enabled"',body)

    def test_unpaid_upgrade_rejected_and_basic_stays_basic(self):
        self.subscribe()
        with self.assertRaisesRegex(ValueError,'verified_pro'):repo.set_business_package(self.bid,'AI_ADMIN_PRO',self.uid)
        self.assertEqual(repo.get_business(self.bid)['package'],'AI_ADMIN_BASIC');self.assertEqual(subs.get_subscription(self.bid)['plan_key'],'ai_admin_basic')
        self.assertFalse(tcs.get_tenant_features(self.bid)['owner_commands'])

    def test_verified_upgrade_syncs_package_subscription_features(self):
        self.subscribe();self.pro_receipt();repo.set_business_package(self.bid,'AI_ADMIN_PRO',self.uid)
        self.assertTrue(tcs.get_tenant_features(self.bid)['owner_commands']);self.assertEqual(subs.get_subscription(self.bid)['plan_key'],'ai_admin_pro')
        self.assertEqual(repo.get_business(self.bid)['package'],'AI_ADMIN_PRO')
        self.assertEqual(self.client.post(f'/business/{self.bid}/settings',data={'appointment_enabled':'on'}).status_code,302)
        self.assertTrue(repo.get_business_profile(self.bid)['appointment_enabled'])

    def test_downgrade_removes_pro_and_receipt_cannot_be_reused(self):
        self.subscribe();self.pro_receipt();repo.set_business_package(self.bid,'AI_ADMIN_PRO',self.uid)
        repo.set_business_package(self.bid,'AI_ADMIN_BASIC',self.uid)
        self.assertFalse(tcs.get_tenant_features(self.bid)['owner_commands']);self.assertEqual(subs.get_subscription(self.bid)['plan_key'],'ai_admin_basic')
        with self.assertRaises(ValueError):repo.set_business_package(self.bid,'AI_ADMIN_PRO',self.uid)

    def test_expiry_removes_pro_even_without_cron(self):
        self.subscribe('AI_ADMIN_PRO')
        db.execute('UPDATE subscriptions SET period_end=?, grace_days=0 WHERE business_id=?',((datetime.now(timezone.utc)-timedelta(seconds=5)).isoformat(),self.bid))
        self.assertFalse(tcs.get_tenant_features(self.bid)['owner_commands'])
        self.assertEqual(self.client.post(f'/business/{self.bid}/settings',data={'appointment_enabled':'on'}).status_code,403)

    def test_mismatch_cannot_enable_pro_and_creation_rejects_divergence(self):
        self.subscribe();db.execute("UPDATE businesses SET package='AI_ADMIN_PRO' WHERE id=?",(self.bid,));repo.set_tenant_features_for_package(self.bid,'AI_ADMIN_PRO')
        self.assertFalse(tcs.get_tenant_features(self.bid)['owner_commands'])
        with self.assertRaises(ValueError):subs.create_subscription(self.bid,'ai_admin_pro')

    def test_existing_active_pro_without_subscription_retains_pro(self):
        db.execute("UPDATE businesses SET package='AI_ADMIN_PRO' WHERE id=?",(self.bid,));repo.set_tenant_features_for_package(self.bid,'AI_ADMIN_PRO')
        self.assertTrue(tcs.get_tenant_features(self.bid)['owner_commands'])

    def test_upgrade_checkout_does_not_grant_entitlement(self):
        self.subscribe()
        r=self.client.post(f'/business/{self.bid}/ai-admin/checkout?package=AI_ADMIN')
        self.assertEqual(r.status_code,302)
        self.assertTrue(db.query_one("SELECT id FROM projects WHERE business_id=? AND catalog_key='ai_admin'",(self.bid,)))
        self.assertEqual(repo.get_business(self.bid)['package'],'AI_ADMIN_BASIC');self.assertFalse(tcs.get_tenant_features(self.bid)['owner_commands'])

if __name__=='__main__':unittest.main()
