"""Single plan, historical compatibility and scoped cost accounting. Offline only."""
import os, sys, unittest, json
from datetime import datetime, timezone
from unittest.mock import patch
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import test_business_hub_v2_phase_a as fixture
import db, repo, security, app, catalog_service as catalog, feature_flags as flags
import subscription_service as subs, payment_service as payments, projects_repo, ai_usage, ai_onboarding

class SinglePlanTests(unittest.TestCase):
    def setUp(self):
        fixture.reset_db(); catalog.seed_catalog_if_needed()
        self.uid=repo.create_user('plan@example.test',security.hash_password('password123'))
        self.bid=repo.create_business(self.uid,'My business','AI_ADMIN')
        self.other=repo.create_business(self.uid,'Second business','AI_ADMIN_PRO')
        self.client=app.app.test_client()
        self.client.post('/login',data={'email':'plan@example.test','password':'password123'})

    def usage(self,bid=None,**kw):
        return ai_usage.record('claude-haiku-4-5-20251001',{'content':[{'type':'text','text':'Example'}],'usage':{'input_tokens':100,'output_tokens':50,'cache_read_input_tokens':200,'cache_creation_input_tokens':300}},tenant_id=bid or self.bid,context='tenant_customer',**kw)

    def test_one_current_offer_and_price(self):
        rows=[r for r in catalog.list_active_catalog() if r['category']=='AI_ADMIN']
        self.assertEqual([(r['catalog_key'],r['price_amount']) for r in rows],[('ai_admin',499000)])
        body=self.client.get('/services').get_data(as_text=True)
        self.assertIn('499.000',body);self.assertNotIn('Kilas Brain Basic',body);self.assertNotIn('Kilas Brain Pro',body)
        self.assertIn('Biaya penggunaan WhatsApp Business Platform',body)

    def test_new_plan_flags_and_none(self):
        self.assertEqual(flags.features_for_package('AI_ADMIN'),flags.features_for_package('AI_ADMIN_PRO'))
        self.assertFalse(any(flags.features_for_package('NONE').values()))
        self.assertTrue(repo.get_tenant_features(self.bid)['owner_commands'])

    def test_old_subscriptions_and_history_survive_seed_and_migration(self):
        bid=repo.create_business(self.uid,'Legacy','AI_ADMIN_BASIC')
        subid=subs.create_subscription(bid,'ai_admin_basic')
        item=catalog.get_catalog_item('ai_admin_basic')
        pid=projects_repo.create_fixed_price_project(bid,item,self.uid)
        invoice=payments.checkout(pid,bid,self.uid)
        before=db.query_one('SELECT * FROM invoices WHERE id=?',(invoice,))
        db.init_schema();catalog.seed_catalog_if_needed();catalog.seed_catalog_if_needed()
        self.assertEqual(before,db.query_one('SELECT * FROM invoices WHERE id=?',(invoice,)))
        self.assertEqual(repo.get_business(bid)['package'],'AI_ADMIN_BASIC')
        self.assertEqual(subs.get_subscription(bid)['plan_key'],'ai_admin_basic')
        self.assertEqual(projects_repo.get_project(pid)['catalog_key'],'ai_admin_basic')
        self.assertFalse(catalog.get_catalog_item('ai_admin_basic')['is_active'])
        self.assertFalse(catalog.get_catalog_item('ai_admin_pro')['is_active'])

    def test_seed_preserves_admin_price(self):
        item=catalog.get_catalog_item('ai_admin')
        catalog.update_catalog_item(item['id'],price_amount=510000)
        catalog.seed_catalog_if_needed()
        self.assertEqual(catalog.get_catalog_item('ai_admin')['price_amount'],510000)

    def test_cannot_reactivate_retired_plan(self):
        with self.assertRaises(catalog.InvalidCatalogState):
            catalog.update_catalog_item(catalog.get_catalog_item('ai_admin_pro')['id'],is_active=True)

    def test_old_form_alias_creates_current_package(self):
        for old in ('AI_ADMIN_BASIC','AI_ADMIN_PRO'):
            response=self.client.post('/business/create',data={'business_name':old,'package':old})
            self.assertEqual(response.status_code,302)
            self.assertEqual(db.query_one('SELECT package FROM businesses WHERE business_name=?',(old,))['package'],'AI_ADMIN')

    def test_checkout_current_and_historical_resume(self):
        response=self.client.post(f'/business/{self.bid}/ai-admin/checkout')
        self.assertEqual(response.status_code,302)
        project=db.query_one('SELECT * FROM projects WHERE business_id=?',(self.bid,))
        self.assertEqual(project['catalog_key'],'ai_admin');self.assertEqual(project['final_price'],499000)
        self.client.post(f'/business/{self.bid}/ai-admin/checkout')
        self.assertEqual(db.query_one('SELECT COUNT(*) n FROM projects WHERE business_id=?',(self.bid,))['n'],1)
        legacy=projects_repo.create_fixed_price_project(self.other,catalog.get_catalog_item('ai_admin_pro'),self.uid)
        response=self.client.post(f'/business/{self.other}/ai-admin/checkout')
        self.assertIn(str(legacy),response.location)

    def test_legacy_to_current_requires_verified_entitlement(self):
        bid=repo.create_business(self.uid,'Legacy Basic','AI_ADMIN_BASIC')
        db.execute("UPDATE businesses SET status='ACTIVE' WHERE id=?",(bid,));subs.create_subscription(bid,'ai_admin_basic')
        with self.assertRaises(ValueError): repo.set_business_package(bid,'AI_ADMIN')
        response=self.client.post(f'/business/{bid}/ai-admin/checkout?package=AI_ADMIN')
        project=db.query_one('SELECT * FROM projects WHERE business_id=?',(bid,))
        self.assertEqual(project['catalog_key'],'ai_admin')
        invoice=payments.checkout(project['id'],bid,self.uid)
        pay=payments.get_payment_for_invoice(invoice)
        db.execute("UPDATE payments SET status='UNDER_REVIEW' WHERE id=?",(pay['id'],))
        payments.verify_payment(pay['id'],bid,self.uid)
        self.assertEqual(repo.get_business(bid)['package'],'AI_ADMIN')
        self.assertEqual(subs.get_subscription(bid)['plan_key'],'ai_admin')
        self.assertTrue(repo.get_tenant_features(bid)['owner_commands'])

    def test_single_plan_subscription_expiry_still_removes_privileges(self):
        subs.create_subscription(self.bid,'ai_admin')
        db.execute("UPDATE subscriptions SET status='SUSPENDED' WHERE business_id=?",(self.bid,))
        self.assertFalse(any(repo.get_tenant_features(self.bid)[k] for k in flags.ALL_FEATURE_KEYS))

    def test_usage_scoped_persistent_and_idempotent_schema(self):
        self.assertTrue(self.usage());self.assertTrue(self.usage(self.other))
        db.init_schema()
        self.assertEqual(ai_usage.monthly(self.bid)[0]['replies'],1)
        self.assertEqual(ai_usage.monthly(self.other)[0]['replies'],1)
        self.assertEqual(len(ai_usage.monthly(admin=True)),2)
        with self.assertRaises(ValueError): ai_usage.monthly()

    def test_malformed_content_costs_count_as_calls_not_replies(self):
        ai_usage.record('claude-haiku-4-5-20251001', {'usage':dict(input_tokens=10,output_tokens=5),'content':[]},tenant_id=self.bid,context='tenant_customer')
        row=ai_usage.monthly(self.bid)[0]
        self.assertEqual(row['calls'],1);self.assertEqual(row['replies'],0)
        self.assertIsNotNone(row['cost_usd'])

    def test_accounting_never_commits_caller_transaction(self):
        conn=db.get_connection()
        conn.execute('UPDATE businesses SET business_name=? WHERE id=?',('Uncommitted',self.bid))
        self.assertFalse(self.usage())  # separate connection times out on SQLite write lock
        self.assertEqual(conn.execute('SELECT business_name FROM businesses WHERE id=?',(self.bid,)).fetchone()[0],'Uncommitted')
        conn.rollback()
        self.assertEqual(repo.get_business(self.bid)['business_name'],'My business')

    def test_currency_snapshot_and_month_boundary(self):
        with patch.dict(os.environ,{'AI_COST_USD_IDR':'15000'}):self.usage()
        with patch.dict(os.environ,{'AI_COST_USD_IDR':'20000'}):
            self.assertAlmostEqual(ai_usage.monthly(self.bid)[0]['cost_idr'],11.175)
        db.execute("UPDATE ai_usage_ledger SET created_at='2000-01-01T00:00:00+00:00'")
        self.assertEqual(ai_usage.monthly(self.bid)[0]['calls'],0)

    def test_platform_scope_is_distinct_from_tenants(self):
        response={'usage':dict(input_tokens=10,output_tokens=5),'content':[{'text':'Example'}]}
        self.assertTrue(ai_usage.record('claude-haiku-4-5-20251001',response,context='platform_customer'))
        self.assertEqual(ai_usage.monthly(self.bid)[0]['replies'],0)
        self.assertIsNone(ai_usage.monthly(admin=True)[0]['tenant_id'])

    def test_unknown_model_is_unknown_cost(self):
        self.assertIsNone(ai_usage.estimate('unknown-model',dict(input_tokens=10,output_tokens=2)))
        ai_usage.record('unknown-model',{'usage':dict(input_tokens=10,output_tokens=2)},tenant_id=self.bid,context='tenant_customer')
        self.assertIsNone(ai_usage.monthly(self.bid)[0]['cost_usd'])

    def test_cache_cost_and_currency_no_guess(self):
        u=dict(input_tokens=100,output_tokens=50,cache_read_input_tokens=200,cache_creation_input_tokens=300,cache_creation={'ephemeral_1h_input_tokens':100})
        self.assertAlmostEqual(ai_usage.estimate('claude-haiku-4-5-20251001',u),.00082)
        with patch.dict(os.environ,{'AI_COST_USD_IDR':''}): self.usage()
        self.assertIsNone(ai_usage.monthly(self.bid)[0]['cost_idr'])

    def test_failure_does_not_break_reply_or_leak_content(self):
        with patch.object(ai_usage,'_insert',side_effect=RuntimeError('sensitive')),self.assertLogs(ai_usage.log,level='WARNING') as logs:
            self.assertFalse(self.usage())
        self.assertNotIn('sensitive',''.join(logs.output))

    def test_soft_fair_use_only_and_other_tenant_not_blocked(self):
        with patch.dict(os.environ,{'KILAS_BRAIN_FAIR_USE_RESPONSES':'4'}):
            for _ in range(3): self.usage()
            self.assertEqual(ai_usage.monthly(self.bid)[0]['status'],'WARNING')
            self.usage();self.usage()
            self.assertEqual(ai_usage.monthly(self.bid)[0]['status'],'HIGH')
            self.assertEqual(ai_usage.monthly(self.bid)[0]['replies'],5)
            self.assertEqual(ai_usage.monthly(self.other)[0]['status'],'NORMAL')
            self.assertTrue(repo.get_tenant_features(self.bid)['owner_commands'])

    def test_admin_only_cost_page(self):
        self.usage()
        self.assertEqual(self.client.get('/admin/ai-usage').status_code,403)
        anon=app.app.test_client();self.assertEqual(anon.get('/admin/ai-usage').status_code,302)
        db.execute("UPDATE users SET role='KILAS_ADMIN' WHERE id=?",(self.uid,))
        response=self.client.get('/admin/ai-usage');self.assertEqual(response.status_code,200)
        self.assertIn('My business',response.get_data(as_text=True))

    def test_dashboard_usage_is_own_business_only(self):
        outsider=repo.create_user('other@example.test',security.hash_password('password123'))
        hidden=repo.create_business(outsider,'Private tenant','AI_ADMIN')
        self.usage(hidden)
        body=self.client.get('/dashboard').get_data(as_text=True)
        self.assertIn('Respons AI bulan ini',body);self.assertNotIn('Private tenant',body)
        self.assertNotIn('estimated_cost_usd',body)

    def test_ai_scope_isolation_and_reset(self):
        captured=[]
        with patch.object(ai_usage,'_insert',side_effect=lambda values: captured.append(values)):
            with ai_usage.scope(self.bid,'simulation'):
                ai_usage.record('claude-haiku-4-5-20251001',{'usage':dict(input_tokens=1,output_tokens=1)})
            ai_usage.record('claude-haiku-4-5-20251001',{'usage':dict(input_tokens=1,output_tokens=1)})
        self.assertEqual(captured[0][:2],(self.bid,'simulation'))
        self.assertEqual(captured[1][:2],(None,'platform_helper'))

    def test_all_monthly_warning_types(self):
        for _ in range(10):
            ai_usage.record('claude-sonnet-4-6',{'usage':dict(input_tokens=9000,output_tokens=100)},tenant_id=self.bid,context='tenant_customer')
        with patch.dict(os.environ,{'AI_COST_WARNING_USD':'0.01'}): row=ai_usage.monthly(self.bid)[0]
        self.assertEqual(len(row['warnings']),3)

    def test_simulation_one_call_and_usage_not_normalization_model(self):
        class Response:
            def raise_for_status(self): pass
            def json(self): return {'content':[{'text':'Jawaban'}],'usage':dict(input_tokens=10,output_tokens=5)}
        with patch.object(ai_onboarding,'ANTHROPIC_API_KEY','test'),patch.object(ai_onboarding.requests,'post',return_value=Response()) as call:
            reply,error=ai_onboarding.simulate_customer_reply(repo.get_business(self.bid),{},[],'Pertanyaan')
        self.assertEqual(reply,'Jawaban');self.assertEqual(call.call_count,1)
        self.assertEqual(call.call_args.kwargs['json']['model'],ai_onboarding.CLIENT_HUB_SIMULATION_MODEL)
        self.assertEqual(ai_usage.monthly(self.bid)[0]['replies'],1)

if __name__=='__main__': unittest.main()
