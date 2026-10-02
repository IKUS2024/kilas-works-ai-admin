"""Focused deterministic cost/quality and durable boundaries; no live provider calls."""
import json
import os
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch, Mock
import test_kilas_autonomous_agent as fixture
from kilas_ai import model_policy as policy, fair_use, usage, store, providers, conversation_context, conversation_standard
from kilas_ai import agent_store


class CostQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # This module owns a fresh synthetic database; provision the exact QA identity safely.
        while not fixture.db.query_one('SELECT id FROM users WHERE id=9'):
            n=fixture.db.query_one('SELECT COUNT(*) n FROM users')['n']
            fixture.repo.create_user('qa-seed-'+str(n)+'@example.test','hash')
        fixture.db.execute('UPDATE users SET email=? WHERE id=9',('irvankarnavi@gmail.com',))

    def setUp(self):
        self.uid=fixture.repo.create_user(self.id()+'@example.test','hash')
        self.thread=store.create_thread(self.uid)
        now=usage._now()
        fixture.db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PLUS','ACTIVE',?,?)",(self.uid,(now-timedelta(days=1)).isoformat(),(now+timedelta(days=29)).isoformat()))

    def spend(self,cost):
        fixture.db.execute("INSERT INTO kilas_ai_usage(user_id,thread_id,operation_key,operation_type,mode,status,estimated_cost_usd,created_at) VALUES (?,?,'previous','CHAT','SMART','COMPLETE',?,?)",(self.uid,self.thread,str(cost),(usage._now()-timedelta(hours=2)).isoformat()))

    def test_all_chat_modes_only_offer_luna_even_with_legacy_sol_configuration(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic','KILAS_AI_OPENAI_SMART_MODEL':'gpt-6-sol','KILAS_AI_SMART_PRIMARY':'anthropic'}):
            for mode in ('FAST','SMART','EXPERT'):
                self.assertEqual([m for _,m,_ in providers.candidates(mode)],[policy.LUNA])

    def test_no_expensive_outage_fallback(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic','ANTHROPIC_API_KEY':'synthetic'}),patch.object(providers,'_openai',side_effect=providers.ProviderError()),patch.object(providers,'_anthropic') as expensive:
            with self.assertRaises(providers.ProviderError):list(providers.stream('SMART',[]))
            expensive.assert_not_called()

    def test_reasoning_examples_and_output_budgets(self):
        for text,tier in [('halo','QUICK'),('translate ini ke English','QUICK'),('Jelaskan ide ini','NORMAL'),('bantu analisis bisnis gue ada 3 cabang','DEEP'),('jelasin kenapa query SQL ini error','DEEP'),('menurut lu mending usaha laundry atau cafe dengan modal 200 juta','DEEP')]:
            profile=policy.chat_profile([{'role':'user','content':text}])
            self.assertEqual(profile['tier'],tier)
            self.assertIn(profile['effort'],('none','low','medium'))
            self.assertEqual(profile['output_tokens'],policy.TIERS[tier][1])

    def test_simple_and_complex_agent_policy(self):
        for text in ('riset 5 kompetitor AI UMKM Indonesia','buatkan dokumen ringkas','pantau halaman ini setiap jam'):
            self.assertEqual(policy.agent_planner({'instruction':text})[:2],(policy.LUNA,'medium'))
        for text in ('kerjain bug di repo ini sampai test pass','refactor authentication across 15 files, tests and retry'):
            self.assertEqual(policy.agent_planner({'instruction':text})[:2],(policy.SOL,'medium'))
        self.assertEqual(policy.agent_planner({'instruction':'Riset','replans':1,'last_error':'worker_failed'})[0],policy.SOL)
        self.assertEqual(policy.agent_planner({'instruction':'Riset','replans':1})[0],policy.LUNA)

    def test_client_cannot_configure_arbitrary_model(self):
        with patch.dict(os.environ,{'KILAS_AI_CHAT_MODEL':'gpt-6.1-sol'}):
            with self.assertRaises(ValueError):policy.luna_model()

    def test_paid_chat_passes_old_numeric_allowance_without_topup(self):
        old=(usage._now()-timedelta(hours=2)).isoformat()
        fixture.db.execute("WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM seq WHERE n<10001) INSERT INTO kilas_ai_usage(user_id,thread_id,operation_key,operation_type,mode,status,estimated_cost_usd,created_at) SELECT ?,?,'legacy-'||n,'CHAT','SMART','COMPLETE','0.00001',? FROM seq",(self.uid,self.thread,old))
        plan,ops=usage.reserve(self.uid,self.thread,'new-normal-paid','SMART','CHAT')
        self.assertEqual(plan,'PLUS')
        self.assertEqual(fixture.db.query_one('SELECT quota_source FROM kilas_ai_usage WHERE operation_key=?',('new-normal-paid',))['quota_source'],'BASE')
        self.assertIsNone(usage.snapshot(self.uid)['usage']['Chat']['limit'])

    def test_cost_tiers_tighten_budget_without_monthly_hard_wall(self):
        self.spend('1.5')
        self.assertEqual(usage.chat_level(self.uid),'VERY_HEAVY')
        self.assertEqual(usage.reserve(self.uid,self.thread,'heavy-human','SMART','CHAT')[0],'PLUS')
        ctx=store.context(self.uid,self.thread)
        self.assertEqual(ctx.fair_use_level,'VERY_HEAVY')
        self.assertLessEqual(policy.chat_profile(policy.ChatContext([{'role':'user','content':'Analisis strategi'}],'VERY_HEAVY'))['output_tokens'],1000)

    def test_extreme_cost_without_abnormal_frequency_remains_functional(self):
        self.spend(10)
        self.assertEqual(usage.reserve(self.uid,self.thread,'still-human','SMART','CHAT')[0],'PLUS')

    def test_protection_temporarily_throttles_abnormal_activity(self):
        self.spend(10)
        now=usage._now()
        for n in range(70):
            at=now-timedelta(seconds=100+n)
            fixture.db.execute("INSERT INTO kilas_ai_usage(user_id,thread_id,operation_key,operation_type,mode,status,estimated_cost_usd,created_at) VALUES (?,? ,?,'CHAT','FAST','COMPLETE','0.001',?)",(self.uid,self.thread,'abuse-'+str(n),at.isoformat()))
        with self.assertRaisesRegex(usage.UsageLimit,'beberapa menit'):
            usage.reserve(self.uid,self.thread,'automated-more','FAST','CHAT')

    def test_separate_tools_remain_limited(self):
        self.spend(10)
        with self.assertRaises(usage.UsageLimit):usage.reserve(self.uid,self.thread,'expensive-web','FAST','WEB')

    def test_concurrency_and_idempotency_still_apply(self):
        for n in range(3):usage.reserve(self.uid,self.thread,'pending-'+str(n),'FAST','CHAT')
        self.assertEqual(usage.reserve(self.uid,self.thread,'pending-0','FAST','CHAT'),(None,()))
        with self.assertRaises(usage.UsageLimit):usage.reserve(self.uid,self.thread,'pending-more','FAST','CHAT')

    def test_exact_owner_qa_exemption_keeps_security(self):
        fixture.db.execute('DELETE FROM kilas_ai_usage WHERE user_id=9')
        thread=store.create_thread(9)
        with patch.object(usage,'_cost_guard',side_effect=AssertionError('QA cost guard')):
            self.assertEqual(usage.chat_level(9),'NORMAL')
            for n in range(3):usage.reserve(9,thread,'qa-'+str(n),'SMART','CHAT')
            with self.assertRaises(usage.UsageLimit):usage.reserve(9,thread,'qa-concurrent','SMART','CHAT')
        with patch.dict(os.environ,{'KILAS_AI_BURST_PER_MINUTE':'1'}):
            with self.assertRaises(usage.UsageLimit):usage.reserve(9,thread,'qa-burst','FAST','CHAT')
        self.assertEqual(usage.QA_QUOTA_EXEMPTIONS[9][0],'irvankarnavi@gmail.com')

    def test_history_budget_preserves_correction_and_followup(self):
        for n,text in enumerate(['Modal 150 juta. Jangan pilih cafe.','Koreksi: laundry kiloan.']+['Percakapan '+str(i) for i in range(25)]+['kalau modal gw cuma 150 juta?']):
            store.append_user_once(self.uid,self.thread,text,'FAST','history-'+str(n))
            if n<27:store.append_assistant(self.uid,self.thread,'Diskusi singkat','FAST','openai',policy.LUNA,'history-'+str(n),{})
        context=store.context(self.uid,self.thread)
        self.assertLessEqual(len(context),13)
        self.assertIn('Jangan pilih cafe',context[0]['content'])
        self.assertIn('laundry kiloan',context[0]['content'])
        self.assertEqual(context[-1]['content'],'kalau modal gw cuma 150 juta?')
        self.assertEqual(context,store.context(self.uid,self.thread))

    def test_secret_like_material_is_not_added_to_summary(self):
        self.assertEqual(conversation_context.summary([{'role':'user','content':'api_key=secret-value'}]),'')

    def test_cached_cost_uses_server_price_configuration(self):
        with patch.dict(os.environ,{'KILAS_AI_MODEL_PRICING_JSON':json.dumps({'priced':{'input_per_million_usd':1,'cached_input_per_million_usd':0.1,'output_per_million_usd':2}})}):
            self.assertEqual(usage.estimate('priced',1000000,1000000,'CHAT',cached_input_tokens=500000),'2.550000')

    def test_recurring_cycle_reuses_plan_without_model(self):
        fixture.db.execute('DELETE FROM kilas_agent_jobs')
        job=fixture.store.create(self.uid,'Pantau ringkasan setiap jam',mode='RECURRING')
        claim=fixture.store.claim_due(1)[0]
        fixture.store.install_plan(fixture.store.get(self.uid,job),claim[1],fixture.planner.validate(fixture.proposal(mode='RECURRING'),'RECURRING'))
        fixture.store.release(*claim)
        for _ in range(3):
            fixture.db.execute('UPDATE kilas_agent_jobs SET next_wake_at=? WHERE id=?',(fixture.store.stamp(),job))
            with patch.object(fixture.planner,'propose',side_effect=AssertionError('unnecessary replan')):
                fixture.runner.execute(*fixture.store.claim_due(1)[0])
        self.assertEqual(fixture.store.get(self.uid,job)['cycle'],2)
        self.assertEqual(len(fixture.store.steps(job)),2)

    def test_runtime_standard_and_offline_corpus_are_separate(self):
        cases=json.loads((Path(__file__).parent/'fixtures/kilas_conversation_standard.json').read_text(encoding='utf-8'))
        self.assertEqual(len(cases),60)
        self.assertEqual(len({c['id'] for c in cases}),60)
        self.assertLess(len(conversation_standard.SYSTEM),4000)
        for c in cases:
            with self.subTest(c['id']):
                self.assertTrue(c['desired'] and c['avoid'] and c['category'])
        self.assertNotIn('Q001',conversation_standard.SYSTEM)

    def test_offline_simulation_is_api_free(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('simulation',Path(__file__).parents[1]/'scripts/kilas_ai_cost_simulation.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.object(providers.requests,'post',side_effect=AssertionError('offline only')):
            report=module.simulate()
        self.assertEqual([r['turns'] for r in report],[100,500,2000,10000])
        self.assertGreater(float(report[-1]['provider_cost_usd']),float(report[0]['provider_cost_usd']))

    def test_actual_adapter_request_uses_reasoning_caps_and_reports_cache(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def raise_for_status(self):pass
            def iter_lines(self,**_):
                return iter(['data: '+json.dumps({'usage':{'prompt_tokens':100,'completion_tokens':20,'prompt_tokens_details':{'cached_tokens':70}},'choices':[]}), ''])
        for prompt,effort,cap in [('halo','none',600),('Jelaskan ide ini','low',1000),('Analisis strategi','medium',1500)]:
            with patch.object(providers.requests,'post',return_value=Response()) as request:
                events=list(providers._openai(policy.LUNA,'synthetic',[{'role':'user','content':prompt}],'SMART'))
            self.assertEqual(request.call_args.kwargs['json']['reasoning_effort'],effort)
            self.assertEqual(request.call_args.kwargs['json']['max_completion_tokens'],cap)
            self.assertEqual(events[0]['cached_input_tokens'],70)

    def test_qa_maximum_active_jobs_is_not_bypassed(self):
        fixture.db.execute('DELETE FROM kilas_agent_jobs WHERE user_id=9')
        for n in range(20):fixture.store.create(9,'Riset '+str(n))
        with self.assertRaisesRegex(ValueError,'active_job_limit'):fixture.store.create(9,'One more')
        fixture.db.execute('DELETE FROM kilas_agent_jobs WHERE user_id=9')

    def test_paid_offer_has_no_message_counter_or_chat_topup_wall(self):
        client=fixture.app.app.test_client()
        with client.session_transaction() as state:state.update(user_id=self.uid,role='CLIENT_OWNER')
        page=client.get('/kilas-ai/usage').text
        self.assertIn('Unlimited AI Chat',page)
        self.assertIn('Fair usage applies',page)
        self.assertNotIn('600 /',page)
        self.assertNotIn('gpt-6',page)

    def test_provider_token_aliases_remain_metered(self):
        _,ops=usage.reserve(self.uid,self.thread,'actual-token-count','FAST','CHAT')
        usage.finish(self.uid,'actual-token-count',ops,success=True,provider='openai',model=policy.LUNA,usage={'prompt_tokens':1000,'completion_tokens':500,'prompt_tokens_details':{'cached_tokens':500}})
        row=fixture.db.query_one('SELECT input_tokens,output_tokens,estimated_cost_usd FROM kilas_ai_usage WHERE operation_key=?',('actual-token-count',))
        self.assertEqual((row['input_tokens'],row['output_tokens']),(1000,500))
        self.assertEqual(row['estimated_cost_usd'],usage.estimate(policy.LUNA,1000,500,'CHAT',cached_input_tokens=500))

    def test_interrupted_billable_calls_cannot_escape_cost_tiers(self):
        self.spend('1.5')
        fixture.db.execute("UPDATE kilas_ai_usage SET status='FAILED' WHERE user_id=?",(self.uid,))
        self.assertEqual(usage.chat_level(self.uid),'VERY_HEAVY')

    def test_mixed_search_and_synthesis_costs_are_not_charged_at_one_model(self):
        _,ops=usage.reserve(self.uid,self.thread,'mixed-model-search','FAST','WEB')
        components=[{'model':policy.SOL,'operation':'WEB_SEARCH','input_tokens':1000,'output_tokens':500},
                    {'model':policy.LUNA,'operation':'CHAT','input_tokens':1000,'output_tokens':500}]
        usage.finish(self.uid,'mixed-model-search',ops,success=True,provider='openai',model=policy.LUNA,usage={'input_tokens':2000,'output_tokens':1000,'cost_components':components})
        actual=fixture.db.query_one('SELECT estimated_cost_usd FROM kilas_ai_usage WHERE operation_key=?',('mixed-model-search',))['estimated_cost_usd']
        self.assertAlmostEqual(float(actual),float(usage.estimate(policy.SOL,1000,500,'WEB_SEARCH'))+float(usage.estimate(policy.LUNA,1000,500,'CHAT')))


if __name__=='__main__':unittest.main()
