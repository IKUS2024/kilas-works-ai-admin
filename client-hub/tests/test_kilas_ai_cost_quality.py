"""Focused deterministic cost/quality and durable boundaries; no live provider calls."""
import json
import os
import unittest
from datetime import timedelta
from decimal import Decimal
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
            self.assertIn(profile['effort'],('low','medium'))
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

    def test_protection_below_ceiling_without_abnormal_frequency_remains_functional(self):
        self.spend('1.8')
        self.assertEqual(usage.reserve(self.uid,self.thread,'still-human','SMART','CHAT')[0],'PLUS')

    def test_sustainability_configuration_is_bounded_and_not_below_protection(self):
        revenue=fair_use.revenue_usd(99000)
        for configured,expected in [('0.20','0.30'),('0.60','0.60'),('NaN','0.35'),('Infinity','0.35'),('bad','0.35'),('0.19','0.35'),('0.61','0.35')]:
            with self.subTest(configured=configured),patch.dict(os.environ,{'KILAS_AI_CHAT_SUSTAINABILITY_COST_RATIO':configured}):
                self.assertEqual(fair_use.sustainability_ceiling(99000),revenue*Decimal(expected))
        with patch.dict(os.environ,{'KILAS_AI_CHAT_PROTECTION_COST_RATIO':'0.40','KILAS_AI_CHAT_SUSTAINABILITY_COST_RATIO':'0.30'}):
            self.assertEqual(fair_use.sustainability_ceiling(99000),revenue*Decimal('0.40'))
        with patch.dict(os.environ,{'KILAS_AI_CHAT_PROTECTION_COST_RATIO':'0.70'}):
            with self.assertRaises(ValueError):fair_use.sustainability_ceiling(99000)

    def test_all_cost_tiers_below_ceiling_still_allow_chat(self):
        revenue=fair_use.revenue_usd(99000)
        for n,(ratio,level) in enumerate([('0.10','NORMAL'),('0.18','HEAVY'),('0.25','VERY_HEAVY'),('0.32','PROTECTION')]):
            fixture.db.execute('DELETE FROM kilas_ai_usage WHERE user_id=?',(self.uid,))
            self.spend(revenue*Decimal(ratio))
            self.assertEqual(usage.chat_level(self.uid),level)
            self.assertEqual(usage.reserve(self.uid,self.thread,'tier-'+str(n),'SMART','CHAT')[0],'PLUS')

    def test_slow_user_at_ceiling_is_denied_before_provider_or_topup(self):
        from kilas_ai import topups
        self.spend(fair_use.sustainability_ceiling(99000))
        client=fixture.app.app.test_client()
        with client.session_transaction() as state:state.update(user_id=self.uid,role='CLIENT_OWNER',_csrf_token='ceiling-csrf')
        with patch.object(providers,'stream') as provider,patch.object(topups,'reserve') as credit:
            response=client.post('/kilas-ai/threads/'+str(self.thread)+'/send',json={'content':'Jelaskan ide ini','mode':'SMART','operation_key':'chatop_ceiling0123456789'},headers={'X-CSRF-Token':'ceiling-csrf'})
            self.assertEqual(response.status_code,429)
            self.assertIn('Fair Use',response.json['error'])
            self.assertIn('periode penggunaan berikutnya',response.json['error'])
            provider.assert_not_called();credit.assert_not_called()
        self.assertEqual(fixture.db.query_one("SELECT COUNT(*) n FROM kilas_ai_usage WHERE user_id=? AND status='PENDING'",(self.uid,))['n'],0)

    def test_single_bounded_call_may_cross_ceiling_then_next_call_stops(self):
        self.spend(fair_use.sustainability_ceiling(99000)-Decimal('0.0001'))
        _,ops=usage.reserve(self.uid,self.thread,'cross-ceiling','SMART','CHAT')
        with self.assertRaises(usage.UsageLimit):usage.reserve(self.uid,self.thread,'parallel-crossing','SMART','CHAT')
        usage.finish(self.uid,'cross-ceiling',ops,success=True,provider='openai',model=policy.LUNA,usage={'input_tokens':2400,'output_tokens':650})
        with self.assertRaisesRegex(usage.UsageLimit,'Fair Use'):usage.reserve(self.uid,self.thread,'after-crossing','SMART','CHAT')

    def test_next_paid_cycle_resets_chat_cost(self):
        self.spend(10)
        with self.assertRaises(usage.UsageLimit):usage.reserve(self.uid,self.thread,'old-cycle','SMART','CHAT')
        fixture.db.execute('UPDATE kilas_ai_subscriptions SET period_start=? WHERE user_id=?',((usage._now()-timedelta(minutes=1)).isoformat(),self.uid))
        self.assertEqual(usage.chat_level(self.uid),'NORMAL')
        self.assertEqual(usage.reserve(self.uid,self.thread,'next-cycle','SMART','CHAT')[0],'PLUS')

    def test_tool_and_background_costs_do_not_consume_normal_chat_ceiling(self):
        old=(usage._now()-timedelta(hours=2)).isoformat()
        for key,operation,thread in [('web-pair','CHAT',self.thread),('web-pair','WEB_SEARCH',self.thread),('pdf-pair','CHAT',self.thread),('pdf-pair','PDF',self.thread),('image','IMAGE',self.thread),('background','CHAT',None),('external','EXTERNAL_ACTION',None)]:
            fixture.db.execute("INSERT INTO kilas_ai_usage(user_id,thread_id,operation_key,operation_type,mode,status,estimated_cost_usd,created_at) VALUES (?,?,?,?,'SMART','COMPLETE','10',?)",(self.uid,thread,key,operation,old))
        self.assertEqual(usage.chat_level(self.uid),'NORMAL')
        self.assertEqual(usage.reserve(self.uid,self.thread,'independent-chat','SMART','CHAT')[0],'PLUS')

    def test_ordinary_agent_qa_cost_is_subject_to_the_same_ceiling(self):
        self.spend(fair_use.sustainability_ceiling(99000))
        fixture.db.execute("UPDATE kilas_ai_usage SET thread_id=NULL,operation_key='agent-chat-existing' WHERE user_id=?",(self.uid,))
        with self.assertRaisesRegex(usage.UsageLimit,'Fair Use'):usage.reserve(self.uid,None,'agent-chat-normal-ceiling','SMART','CHAT')

    def test_billable_failed_chat_still_consumes_ceiling(self):
        self.spend(fair_use.sustainability_ceiling(99000))
        fixture.db.execute("UPDATE kilas_ai_usage SET status='FAILED' WHERE user_id=?",(self.uid,))
        with self.assertRaisesRegex(usage.UsageLimit,'Fair Use'):usage.reserve(self.uid,self.thread,'failed-ceiling','SMART','CHAT')

    def test_exact_owner_qa_bypasses_ceiling_but_remains_metered(self):
        fixture.db.execute('DELETE FROM kilas_ai_usage WHERE user_id=9')
        now=usage._now()
        fixture.db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (9,'PLUS','ACTIVE',?,?) ON CONFLICT(user_id) DO UPDATE SET plan='PLUS',status='ACTIVE',period_start=excluded.period_start,period_end=excluded.period_end",((now-timedelta(days=1)).isoformat(),(now+timedelta(days=29)).isoformat()))
        thread=store.create_thread(9)
        fixture.db.execute("INSERT INTO kilas_ai_usage(user_id,thread_id,operation_key,operation_type,mode,status,estimated_cost_usd,created_at) VALUES (9,?,'qa-expensive','CHAT','SMART','COMPLETE','100',?)",(thread,(usage._now()-timedelta(hours=2)).isoformat()))
        with patch.object(fair_use,'sustainability_ceiling',side_effect=AssertionError('QA ceiling applied')):
            usage.reserve(9,thread,'qa-ceiling-bypass','SMART','CHAT')
        self.assertEqual(fixture.db.query_one('SELECT COUNT(*) n FROM kilas_ai_usage WHERE user_id=9')['n'],2)
        fixture.db.execute('DELETE FROM kilas_ai_usage WHERE user_id=9')

    def test_public_rp99k_checkout_uses_plus_and_preserves_historical_plans(self):
        from kilas_ai import billing
        historical=[billing.create_invoice(self.uid,plan) for plan in ('PRO','MAX')]
        before=[dict(billing.invoice(self.uid,invoice)) for invoice in historical]
        client=fixture.app.app.test_client()
        with client.session_transaction() as state:state.update(user_id=self.uid,role='CLIENT_OWNER',_csrf_token='checkout-csrf')
        response=client.post('/kilas-ai/checkout',data={'csrf_token':'checkout-csrf','plan':'PRO'})
        self.assertEqual(response.status_code,303)
        invoice=fixture.db.query_one("SELECT plan,amount_idr FROM kilas_ai_invoices WHERE user_id=? AND plan='PLUS'",(self.uid,))
        self.assertEqual((invoice['plan'],invoice['amount_idr']),('PLUS',99000))
        self.assertEqual(usage.snapshot(self.uid)['plan'],'PLUS')
        self.assertEqual([dict(billing.invoice(self.uid,invoice)) for invoice in historical],before)

    def test_qa_owner_gmail_still_requires_explicit_approval(self):
        from kilas_ai import connectors,connector_flow,connector_actions
        stamp=connectors.stamp()
        fixture.db.execute("INSERT INTO kilas_ai_connections(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) VALUES (9,'GOOGLE','CONNECTED',?,'{}','synthetic',?,?)",('["https://www.googleapis.com/auth/gmail.send"]',stamp,stamp))
        with patch.object(connector_actions.google_tools,'gmail_send',return_value={'id':'controlled-qa-send'}) as send:
            approval=connector_flow._proposal(9,'gmail.send',{'to':'controlled@example.test','subject':'QA','body':'Synthetic test'},None,'Kirim email ke controlled@example.test')
            self.assertEqual(connectors.approval(9,approval)['status'],'PENDING')
            send.assert_not_called()
            self.assertEqual(connector_actions.execute(9,approval)['id'],'controlled-qa-send')
            send.assert_called_once()
            with self.assertRaises(connectors.ConnectorError):connector_actions.execute(9,approval)

    def test_protection_temporarily_throttles_abnormal_activity(self):
        self.spend('1.8')
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
        self.assertGreaterEqual(len(cases),200)
        self.assertEqual(len({c['id'] for c in cases}),len(cases))
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
        self.assertEqual(report[-1]['policy_enforced']['provider_calls'],3608)
        self.assertEqual(report[-1]['policy_enforced']['denied_turns'],6392)
        self.assertLessEqual(float(report[-1]['policy_enforced']['cost_revenue_percent']),35.01)

    def test_actual_adapter_request_uses_reasoning_caps_and_reports_cache(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def raise_for_status(self):pass
            def iter_lines(self,**_):
                return iter(['data: '+json.dumps({'usage':{'prompt_tokens':100,'completion_tokens':20,'prompt_tokens_details':{'cached_tokens':70}},'choices':[]}), ''])
        for prompt,effort,cap in [('halo','low',600),('Jelaskan ide ini','low',1000),('Analisis strategi','medium',1500)]:
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
        self.assertIn('dibatasi sementara sesuai Fair Use',page)
        self.assertNotIn('600 /',page)
        self.assertNotIn('gpt-6',page)
        for internal in ('16%','24%','30%','35%','API cost','token cost','GPT-6','OpenAI'):
            self.assertNotIn(internal,page)

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
