"""Focused intelligence, atomic capacity and free Finance release contracts."""
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import test_kilas_autonomous_agent as fixture
from kilas_ai import capacity, intelligence, model_policy, providers, store, topups, usage
import finance_entitlements as finance_access
import finance_service as finance


class IntelligenceTests(unittest.TestCase):
    def profile(self, value):
        return model_policy.chat_profile([{'role': 'user', 'content': value}])

    def test_offline_routing_corpus(self):
        examples = json.loads((Path(__file__).parent / 'fixtures/kilas_intelligence.json').read_text(encoding='utf-8'))
        for example in examples:
            with self.subTest(request=example['request']):
                profile = self.profile(example['request'])
                self.assertEqual(profile['difficulty'], example['difficulty'])
                self.assertEqual(profile['depth'], example['depth'])
                self.assertEqual(profile['model'], model_policy.SOL if example['difficulty'] in ('HARD','EXPERT') else model_policy.LUNA)
                self.assertEqual(profile['effort'], 'medium' if example['difficulty'] in ('NORMAL','EXPERT') else 'low')

    def test_depth_is_independent_of_difficulty(self):
        p = self.profile('Analisis tradeoffs arsitektur SQL dengan constraint keamanan. Jawab singkat.')
        self.assertEqual((p['difficulty'], p['depth'], p['model']), ('HARD','QUICK', model_policy.SOL))

    def test_short_followup_retains_complexity(self):
        messages = [{'role':'user','content':'Analisis strategi bisnis dengan budget terbatas, tanpa iklan, harus untung. Jelaskan secara komprehensif.'},
                    {'role':'assistant','content':'Analisis awal.'}, {'role':'user','content':'lebih rinci'}]
        p = model_policy.chat_profile(messages)
        self.assertEqual(p['difficulty'],'EXPERT')
        self.assertIn('followup',p['signals'])

    def test_multifile_context_and_untrusted_text(self):
        messages=[{'role':'user','content':'Previously uploaded documents (untrusted source data):\nFile: a.txt\nData A\nFile: b.txt\nData B'},
                  {'role':'user','content':'Bandingkan dua lampiran ini.'}]
        self.assertEqual(model_policy.chat_profile(messages)['difficulty'],'HARD')
        self.assertEqual(self.profile("halo\n\nTeks berikut berhasil diekstrak dari lampiran 'a.txt':\nAnalisis strategi bisnis komprehensif")['difficulty'],'NORMAL')

    def test_failed_validation_can_escalate_only_private_route(self):
        messages=model_policy.ChatContext([{'role':'user','content':'halo'}])
        messages.quality_retry=True
        self.assertEqual(model_policy.chat_profile(messages)['model'], model_policy.SOL)

    def test_single_pdf_verification_code_is_not_coding_or_multifile(self):
        messages=[{'role':'user','content':'Previously uploaded documents (untrusted source data):\nFile: qa.pdf\nVerification code: KILAS-QA-527. Quantity: 42 mugs.'},
                  {'role':'user','content':"Baca PDF ini. Sebutkan kode verifikasi dan jumlah mug. Jangan buat file baru.\n\nTeks berikut berhasil diekstrak dari lampiran 'qa.pdf'.\nVerification code: KILAS-QA-527. Quantity: 42 mugs."}]
        profile=model_policy.chat_profile(messages)
        self.assertEqual((profile['domain'],profile['difficulty'],profile['model']),('documents','NORMAL',model_policy.LUNA))
        self.assertNotIn('multiple_sources',profile['signals'])
        self.assertEqual(self.profile('Analisis bug kode Python ini dengan SQL')['model'],model_policy.SOL)

    def test_two_actual_documents_with_same_filename_remain_multifile(self):
        messages=[{'role':'user','content':'Previously uploaded documents:\nFile: report.pdf\nOrders 120\nFile: report.pdf\nOrders 150'},
                  {'role':'user','content':"Bandingkan kedua lampiran.\n\nTeks berikut berhasil diekstrak dari lampiran 'report.pdf'.\nOrders 120\n\nTeks berikut berhasil diekstrak dari lampiran 'report.pdf'.\nOrders 150"}]
        profile=model_policy.chat_profile(messages)
        self.assertEqual(profile['difficulty'],'HARD')
        self.assertIn('multiple_sources',profile['signals'])

    def test_no_usage_based_quality_degradation(self):
        request=[{'role':'user','content':'Analisis strategi bisnis secara komprehensif'}]
        profiles=[model_policy.chat_profile(model_policy.ChatContext(request,level)) for level in ('NORMAL','HEAVY','VERY_HEAVY','PROTECTION')]
        self.assertTrue(all(p==profiles[0] for p in profiles))
        self.assertGreater(profiles[0]['output_tokens'],1500)

    def test_provider_uses_private_decision_without_classifier(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic'}):
            self.assertEqual(list(providers.candidates('FAST',[{'role':'user','content':'Analisis bug SQL'}]))[0][1],model_policy.SOL)
            self.assertEqual(list(providers.candidates('EXPERT',[{'role':'user','content':'halo'}]))[0][1],model_policy.LUNA)

    def test_video_sol_contract_is_preserved(self):
        self.assertEqual(model_policy.agent_planner({'instruction':'multi-stage planning'})[:2],(model_policy.SOL,'medium'))

    def test_quality_contracts_for_structured_output_and_private_terms(self):
        from kilas_ai import chat_quality
        self.assertIn('invalid_json',chat_quality.violations('only valid JSON','{bad}'))
        self.assertEqual(chat_quality.violations('only valid JSON','{"result":true}'),[])
        self.assertEqual(chat_quality.violations('only valid JSON',None),['empty'])
        self.assertIn('private_terminology',chat_quality.violations('halo','gpt-6.1-sol'))


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.uid=fixture.repo.create_user(self.id()+'@example.test','synthetic-hash')
        self.thread=store.create_thread(self.uid)
        self.now=usage._now()
        fixture.db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PLUS','ACTIVE',?,?)",
            (self.uid,(self.now-timedelta(days=1)).isoformat(),(self.now+timedelta(days=29)).isoformat()))

    def spent(self, cost, status='COMPLETE', mode='SMART', operation='CHAT'):
        fixture.db.execute("INSERT INTO kilas_ai_usage(user_id,thread_id,operation_key,operation_type,mode,status,estimated_cost_usd,created_at) VALUES (?,?,'prior',?,?,?,?,?)",
            (self.uid,self.thread,operation,mode,status,str(cost),(self.now-timedelta(hours=2)).isoformat()))

    def credit(self, total=1000000):
        order=topups.create_order(self.uid,'MINI')
        fixture.db.execute("INSERT INTO kilas_ai_topup_credits(order_id,user_id,total_micro,expires_at) VALUES (?,?,?,?)",
            (order,self.uid,total,(self.now+timedelta(days=90)).isoformat()))
        return order

    def test_normal_chat_survives_exhaustion(self):
        self.spent(100)
        self.assertEqual(capacity.summary(self.uid)['state'],'Habis')
        self.assertEqual(usage.reserve(self.uid,self.thread,'normal','FAST','CHAT')[0],'PLUS')
        with self.assertRaises(usage.UsageLimit):usage.reserve(self.uid,self.thread,'image','FAST','IMAGE_GENERATE')

    def test_cheap_normal_chat_does_not_consume_shared_premium(self):
        self.spent(100,mode='FAST')
        self.assertEqual(capacity.summary(self.uid)['state'],'Cukup')

    def test_billable_failures_consume_capacity(self):
        self.spent(100,status='FAILED')
        with self.assertRaises(usage.UsageLimit):usage.reserve(self.uid,self.thread,'failed-billable','FAST','WEB')
        self.assertEqual(usage.reserve(self.uid,self.thread,'still-chat','FAST','CHAT')[0],'PLUS')

    def test_no_paid_feature_count_entitlements(self):
        with patch.object(usage,'_limit',return_value=0):
            self.assertEqual(usage.reserve(self.uid,self.thread,'premium-not-counter','FAST','WEB')[0],'PLUS')

    def test_atomic_reservations_have_one_winner(self):
        self.spent(capacity.allowance()-Decimal('0.13'))
        def reserve(key):
            try:return bool(usage.reserve(self.uid,self.thread,key,'FAST','WEB')[1])
            except usage.UsageLimit:return False
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sum(pool.map(reserve,['race-a','race-b'])),1)

    def test_actual_settlement_releases_forecast_and_is_idempotent(self):
        _,ops=usage.reserve(self.uid,self.thread,'settle','FAST','WEB')
        usage.finish(self.uid,'settle',ops,success=True,model=model_policy.LUNA,usage={'input_tokens':100,'output_tokens':100})
        before=dict(fixture.db.query_one("SELECT * FROM kilas_ai_usage WHERE user_id=? AND operation_key='settle'",(self.uid,)))
        usage.finish(self.uid,'settle',ops,success=True,model=model_policy.SOL,usage={'input_tokens':9999,'output_tokens':9999})
        self.assertEqual(before,dict(fixture.db.query_one("SELECT * FROM kilas_ai_usage WHERE user_id=? AND operation_key='settle'",(self.uid,))))
        self.assertLess(Decimal(before['estimated_cost_usd']),Decimal('0.12'))

    def test_topup_billed_failure_charged_without_double_settlement(self):
        self.spent(100);self.credit()
        _,ops=usage.reserve(self.uid,self.thread,'billed-failure','SMART','CHAT')
        usage.finish(self.uid,'billed-failure',ops,success=False,model=model_policy.SOL,usage={'input_tokens':1000,'output_tokens':1000})
        debit=fixture.db.query_one("SELECT * FROM kilas_ai_topup_debits WHERE user_id=? AND operation_key='billed-failure'",(self.uid,))
        self.assertEqual((debit['status'],debit['charged_micro']),('FAILED',12000))
        self.assertLess(topups.balance(self.uid)['percent'],100)
        usage.finish(self.uid,'billed-failure',ops,success=False,model=model_policy.SOL,usage={'input_tokens':1000,'output_tokens':1000})
        self.assertEqual(debit,fixture.db.query_one("SELECT * FROM kilas_ai_topup_debits WHERE user_id=? AND operation_key='billed-failure'",(self.uid,)))

    def test_expired_pro_preserves_topup_without_consuming_it(self):
        self.credit();self.spent(100)
        before=topups.balance(self.uid)
        fixture.db.execute('UPDATE kilas_ai_subscriptions SET period_end=? WHERE user_id=?',((self.now-timedelta(hours=1)).isoformat(),self.uid))
        with self.assertRaises(usage.UsageLimit):usage.reserve(self.uid,self.thread,'expired','FAST','IMAGE_GENERATE')
        self.assertEqual(before,topups.balance(self.uid))
        client=fixture.app.app.test_client()
        with client.session_transaction() as state:state.update(user_id=self.uid,role='CLIENT_OWNER')
        html=client.get('/kilas-ai/usage').get_data(as_text=True)
        self.assertIn('Masa aktif Kilas Pro telah berakhir.',html)
        self.assertIn('Perpanjang Rp99.000 / 30 hari',html)

    def test_qa_allowlist_is_email_owned_and_security_burst_remains(self):
        self.spent(100)
        email=self.id()+'@example.test'
        with patch.dict(os.environ,{'KILAS_AI_INTERNAL_QA_EMAILS':email,'KILAS_AI_BURST_PER_MINUTE':'1'}):
            self.assertEqual(usage.reserve(self.uid,self.thread,'qa-image','FAST','IMAGE_GENERATE')[0],'PLUS')
            with self.assertRaises(usage.UsageLimit):usage.reserve(self.uid,self.thread,'qa-burst','FAST','WEB')
        with self.assertRaises(usage.UsageLimit):usage.reserve(self.uid,self.thread,'not-qa','FAST','WEB')

    def test_fixed_orders_server_amount_and_legacy_orders_unchanged(self):
        for pack,amount in [('MINI',25000),('EXTRA',50000),('POWER',100000)]:
            order=topups.create_order(self.uid,pack)
            self.assertEqual(topups.order(self.uid,order)['amount_idr'],amount)
            self.assertEqual(topups.create_order(self.uid,pack),order)
        self.assertEqual(topups.PACK_ALLOWANCES_IDR,{25000:10000,50000:22000,100000:48000})
        with self.assertRaises(topups.TopupError):topups.create_order(self.uid,'CUSTOM')

    def test_fixed_pack_verified_allowance_expiry_and_replay(self):
        admin=fixture.repo.create_user(self.id()+'admin@example.test','hash',role='KILAS_ADMIN')
        for pack,amount in topups.PACKS.items():
            order=topups.create_order(self.uid,pack)
            fixture.db.execute("UPDATE kilas_ai_topup_orders SET status='UNDER_REVIEW' WHERE id=?",(order,))
            topups.review(order,admin,'VERIFIED');topups.review(order,admin,'VERIFIED')
            rows=fixture.db.query_all('SELECT * FROM kilas_ai_topup_credits WHERE order_id=?',(order,))
            self.assertEqual(len(rows),1)
            expected=int(Decimal(topups.PACK_ALLOWANCES_IDR[amount])/Decimal(os.environ.get('KILAS_AI_USD_IDR','17000'))*1000000)
            self.assertEqual(rows[0]['total_micro'],expected)
            self.assertEqual((usage._as_utc(rows[0]['expires_at'])-self.now).days,90)

    def test_internal_levels_and_public_state_do_not_leak_cost(self):
        for ratio,state in [('0.69','GREEN'),('0.7','WATCH'),('0.9','HEAVY'),('1','PROTECTION')]:
            self.assertEqual(capacity.level(capacity.allowance()*Decimal(ratio)),state)
        public=capacity.summary(self.uid)
        self.assertEqual(set(public),{'state','available','active','has_topup'})

    def test_customer_warning_starts_at_ninety_percent(self):
        self.spent(capacity.allowance()*Decimal('0.75'))
        self.assertEqual(capacity.summary(self.uid)['state'],'Cukup')
        fixture.db.execute('UPDATE kilas_ai_usage SET estimated_cost_usd=? WHERE user_id=?',(str(capacity.allowance()*Decimal('0.91')),self.uid))
        self.assertEqual(capacity.summary(self.uid)['state'],'Menipis')

    def test_billed_search_without_sources_is_not_free(self):
        from kilas_ai import tools
        _,ops=usage.reserve(self.uid,self.thread,'search-invalid','FAST','WEB')
        with patch.dict(os.environ,{'KILAS_AI_OPENAI_WEB_MODEL':model_policy.LUNA}),patch.object(tools,'_request',return_value={'output':[],'usage':{'input_tokens':1000,'output_tokens':500}}):
            try:tools.web_search([{'role':'user','content':'latest weather'}])
            except tools.ToolUnavailable as error:
                usage.finish(self.uid,'search-invalid',ops,success=False,model=error.model,usage=error.usage)
            else:self.fail('Missing source result must fail')
        row=fixture.db.query_one("SELECT * FROM kilas_ai_usage WHERE user_id=? AND operation_key='search-invalid'",(self.uid,))
        self.assertEqual(row['status'],'FAILED')
        self.assertGreater(Decimal(row['estimated_cost_usd']),Decimal(0))

    def test_invalid_billed_planner_attempts_are_metered(self):
        from unittest.mock import Mock
        from kilas_ai import agent_planner,autonomous_planner,connector_planner
        response=Mock()
        response.json.return_value={'status':'incomplete','usage':{'input_tokens':1000,'output_tokens':100}}
        job=fixture.store.create(self.uid,'Analisis strategi bisnis dengan risiko')
        calls=[lambda:agent_planner.propose(self.uid,'Buat tugas besok',[],[]),
               lambda:autonomous_planner.propose(fixture.store.get(self.uid,job),[]),
               lambda:connector_planner.propose(self.uid,'Kirim email sintetis',[],['gmail.send'],[],'Asia/Jakarta')]
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic'}),patch('requests.post',return_value=response):
            for call in calls:
                with self.assertRaises((ValueError,RuntimeError)):call()
        rows=fixture.db.query_all("SELECT status,estimated_cost_usd FROM kilas_ai_usage WHERE user_id=?",(self.uid,))
        self.assertEqual(len(rows),3)
        self.assertTrue(all(r['status']=='FAILED' and Decimal(r['estimated_cost_usd'])>0 for r in rows))

    def test_unified_failed_search_keeps_billed_usage(self):
        from kilas_ai import unified_runtime,tools
        error=tools.ToolUnavailable('synthetic failed validation',model=model_policy.LUNA,usage={'input_tokens':1000,'output_tokens':100})
        with fixture.app.app.test_request_context(headers={'X-Agent-Chat':'1'}),patch.object(unified_runtime.agent_chat,'context',return_value=[{'role':'user','content':'latest sources'}]),patch.object(tools,'web_search_steps',side_effect=error),patch.object(unified_runtime.agent_store,'append'):
            response=unified_runtime.search(self.uid,'failed-search',None)
            response.get_data()
        row=fixture.db.query_one("SELECT status,estimated_cost_usd FROM kilas_ai_usage WHERE user_id=?",(self.uid,))
        self.assertEqual(row['status'],'FAILED')
        self.assertGreater(Decimal(row['estimated_cost_usd']),Decimal(0))

    def test_billed_invalid_image_is_metered_by_worker(self):
        from kilas_ai import tools
        from kilas_ai.agent_workers import image_worker
        error=tools.ToolUnavailable('synthetic invalid image',model='gpt-image-2',usage={'input_tokens':10})
        with patch.dict(os.environ,{'KILAS_AI_OPENAI_IMAGE_MODEL':'gpt-image-2'}),patch.object(tools,'image',side_effect=error):
            with self.assertRaises(tools.ToolUnavailable):
                image_worker.run({'user_id':self.uid,'origin_conversation_id':None},{'idempotency_key':'image-failed','attempts':1,'action':'generate'},{'prompt':'synthetic orange square'})
        row=fixture.db.query_one("SELECT status,estimated_cost_usd FROM kilas_ai_usage WHERE user_id=?",(self.uid,))
        self.assertEqual(row['status'],'FAILED')
        self.assertEqual(Decimal(row['estimated_cost_usd']),Decimal('0.04'))

    def test_default_qa_email_still_requires_send_approval(self):
        from kilas_ai import connectors,connector_flow,connector_actions
        qa=fixture.repo.create_user('irvankarnavi@gmail.com','hash')
        self.assertTrue(usage.qa_exempt(qa))
        self.assertEqual(usage.reserve(qa,None,'qa-free-image','FAST','IMAGE_GENERATE')[0],'FREE')
        stamp=connectors.stamp()
        fixture.db.execute("INSERT INTO kilas_ai_connections(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) VALUES(?,'GOOGLE','CONNECTED',?,'{}','synthetic',?,?)",(qa,'["https://www.googleapis.com/auth/gmail.send"]',stamp,stamp))
        with patch.object(connector_actions.google_tools,'gmail_send',return_value={'id':'synthetic-send'}) as send:
            approval=connector_flow._proposal(qa,'gmail.send',{'to':'qa@example.test','subject':'Synthetic','body':'Controlled test'},None,'Kirim email ke qa@example.test')
            self.assertEqual(connectors.approval(qa,approval)['status'],'PENDING')
            send.assert_not_called()
            connector_actions.execute(qa,approval)
            send.assert_called_once()


class FreeFinanceTests(unittest.TestCase):
    def setUp(self):
        self.uid=fixture.repo.create_user(self.id()+'@example.test','hash')
        self.business=fixture.repo.create_business(self.uid,'Synthetic free finance')
        self.client=fixture.app.app.test_client()
        with self.client.session_transaction() as state:state.update(user_id=self.uid,role='CLIENT_OWNER',_csrf_token='free-finance-csrf')

    def test_free_finance_without_any_subscription(self):
        self.assertEqual(usage.effective_plan(self.uid)['plan'],'FREE')
        self.assertEqual(finance_access.state(self.business)['status'],'FREE')
        with patch('requests.post',side_effect=AssertionError('paid provider must never run')):
            finance_access.setup(self.business,self.uid,'Kas','CASH',0)
            finance_access.require_write(self.business,self.uid)
            for path in ('','/reports','/operations','/budget','/receivables'):
                self.assertEqual(self.client.get(f'/business/{self.business}/finance'+path).status_code,200)
        self.assertIsNone(fixture.db.query_one('SELECT * FROM finance_entitlements WHERE business_id=?',(self.business,)))

    def test_all_paid_finance_routes_archived_and_flags_cannot_enable(self):
        with patch.dict(os.environ,{'KILAS_FINANCE_ANALYST_ENABLED':'true','KILAS_FINANCE_OPERATOR_ENABLED':'true','ANTHROPIC_API_KEY':'synthetic'}),patch('requests.post',side_effect=AssertionError('paid provider must never run')):
            for path in ('analyst','operator','assistant','receipts/new','bank-imports'):
                self.assertEqual(self.client.get(f'/business/{self.business}/finance/'+path).status_code,404)
            self.assertFalse(finance_access.capability(self.business,'ANALYST'))
            with self.assertRaises(finance.FinanceError):finance_access.require_ai(self.business,self.uid)
            import finance_ai_safety,finance_bank_extract,finance_receipts
            with self.assertRaises(ValueError):finance_ai_safety.configuration()
            with self.assertRaises(finance_bank_extract.BankError):finance_bank_extract.configuration()
            with self.assertRaises(finance_receipts.ReceiptError):finance_receipts.extract(b'synthetic','image/png','',[],self.business)

    def test_all_legacy_finance_provider_entrypoints_are_disabled(self):
        import finance_analyst,finance_operator,finance_documents,finance_draft_interpreter,finance_semantics,finance_bank_extract
        entrypoints=[lambda:finance_analyst.generate('synthetic',{},business_id=self.business,user_id=self.uid),
                     lambda:finance_operator.interpret('CREATE','synthetic','IDR',self.business),
                     lambda:finance_documents.recognize(self.business,self.uid,[],'synthetic'),
                     lambda:finance_draft_interpreter.interpret('synthetic',{'values':{}},[]),
                     lambda:finance_semantics.interpret('synthetic',[],[],business_id=self.business),
                     lambda:finance_bank_extract.ai_rows({},'IDR',self.business)]
        with patch.dict(os.environ,{'ANTHROPIC_API_KEY':'synthetic'}),patch('requests.sessions.Session.request',side_effect=AssertionError('Paid Finance provider forbidden')) as network:
            for call in entrypoints:
                with self.assertRaises(ValueError):call()
            network.assert_not_called()

    def test_emergency_disable_and_tenant_isolation_still_win(self):
        other=fixture.repo.create_user(self.id()+'other@example.test','hash')
        with self.assertRaises(finance.FinanceError):finance_access.require_write(self.business,other)
        with patch.dict(os.environ,{'KILAS_FINANCE_EMERGENCY_DISABLE':'true'}):
            with self.assertRaises(finance.FinanceError):finance_access.require_write(self.business,self.uid)

    def test_no_new_finance_subscription_charge(self):
        self.assertEqual(self.client.post(f'/business/{self.business}/finance-subscription',data={'csrf_token':'free-finance-csrf','action':'subscribe'}).status_code,404)


if __name__ == '__main__':
    unittest.main()
