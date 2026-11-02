"""Real isolated account/ledger/routes with sponsored offering; all inference mocked."""
import io
import os
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import test_kilas_chat_models as fixture
from kilas_ai import chat_offering as offering, chat_models, image_models, model_preferences
from kilas_ai import usage, capacity, store, agent_store, providers, selected_image, tools, selected_provider
import db
import repo

FLAGS={offering.MANAGED_FLAG:'true',offering.CHAT_FREE_FLAG:'true',offering.IMAGE_FREE_FLAG:'true',
       'KILAS_APP_FREE_TEST_ENABLED':'false','KILAS_AI_INTERNAL_QA_ENABLED':'false'}

class ManagedOfferingTests(unittest.TestCase):
    client=fixture.RouteTests.client
    submit=fixture.RouteTests.submit

    def setUp(self):
        fixture.RouteTests.setUp(self)
        p=patch.dict(os.environ,FLAGS);p.start();self.addCleanup(p.stop)
        p=patch.object(image_models,'check',side_effect=lambda model:{**image_models.spec(model),'available':True,'status':'verified'})
        p.start();self.addCleanup(p.stop)

    def test_models_pinned_without_rewriting_retained_preferences(self):
        with patch.dict(os.environ,{offering.MANAGED_FLAG:'false'}):
            chat_models.choose(self.owner,'thread',self.thread,'gpt-6.1-sol')
            model_preferences.remember(self.owner,'chat','gpt-6.1-sol')
        self.assertEqual(chat_models.preference(self.owner,'thread',self.thread),offering.CHAT_MODEL)
        self.assertEqual(model_preferences.get(self.owner,'chat'),offering.CHAT_MODEL)
        self.assertEqual(chat_models.choose(self.owner,'thread',self.thread,'gpt-6-astra'),offering.CHAT_MODEL)
        self.assertEqual(image_models.requested(self.owner,'thread',self.thread,None,required=True),offering.IMAGE_MODEL)
        self.assertEqual([m['id'] for m in chat_models.catalog()['models']],[offering.CHAT_MODEL])
        with patch.dict(os.environ,{offering.MANAGED_FLAG:'false'}):
            self.assertEqual(chat_models.preference(self.owner,'thread',self.thread),'gpt-6.1-sol')
            self.assertEqual(model_preferences.get(self.owner,'chat'),'gpt-6.1-sol')

    def test_no_substitution_when_fixed_model_unavailable(self):
        with patch.object(chat_models,'check',side_effect=lambda model:{**chat_models.spec(model),'available':False}):
            self.assertIsNone(chat_models.catalog()['default'])
            with self.assertRaises(chat_models.SelectionError):chat_models.choose(self.owner,'thread',self.thread,'gpt-6-astra')
        with patch.object(image_models,'check',return_value={'available':False}):
            with self.assertRaises(chat_models.SelectionError):image_models.requested(self.owner,'thread',self.thread,None,required=True)

    def test_owner_and_staff_chat_admission_preserves_other_gates(self):
        staff=repo.create_user(self.id()+'staff@example.test','hash',role='CLIENT_STAFF')
        client=self.client(staff)
        self.assertEqual(client.get('/products/start').status_code,200)
        self.assertEqual(client.get('/kilas-ai',follow_redirects=True).status_code,200)
        self.assertEqual(client.get('/kilas-ai/chat/models').status_code,200)
        self.assertEqual(client.get('/kilas-ai/video').status_code,404)
        self.assertEqual(client.get('/kilas-ai/threads/'+str(self.thread)).status_code,404)
        self.assertNotEqual(client.post('/kilas-ai/chat/model',json={'model':'gpt-6-astra'}).status_code,200)
        response=client.post('/kilas-ai/chat/model',json={'model':'gpt-6-astra'},headers={'X-CSRF-Token':'work-csrf'})
        self.assertEqual((response.status_code,response.json['code']),(409,'models_managed'))
        anonymous=client.application.test_client()
        self.assertEqual(anonymous.post('/kilas-ai/agent/chat',data={'message':'hello'}).status_code,401)
        self.assertNotEqual(anonymous.get('/kilas-ai/chat/models').status_code,200)

    def test_managed_ui_in_all_locales_no_picker_or_provider_branding(self):
        client=self.client()
        for locale in ('id','en','es','zh'):
            client.set_cookie('kilas_language',locale)
            for path in ('/products/start','/kilas-ai/threads/'+str(self.thread),'/kilas-ai/agent?conversation='+str(self.conversation)):
                with self.subTest(locale=locale,path=path):
                    response=client.get(path);self.assertEqual(response.status_code,200)
                    self.assertIn('<strong>Kilas AI</strong>',response.text)
                    self.assertNotIn('data-chat-model-selector',response.text)
                    self.assertNotIn('id="chat-model-dialog"',response.text)
                    self.assertNotIn('kilas_chat_models.js',response.text)
                    self.assertNotIn('Conversation Copilot',response.text)

    def test_chat_keeps_luna_and_latest_correction_context(self):
        answers=[fixture.answer(None,chat_models.bind(fixture.model_policy.ChatContext([]),offering.CHAT_MODEL)),
                 fixture.answer(None,chat_models.bind(fixture.model_policy.ChatContext([]),offering.CHAT_MODEL))]
        with patch.object(providers,'stream',side_effect=answers) as provider:
            self.submit(model='gpt-6-astra',text='Budget saya 150 juta. Apa langkah awal?',key='managed_context_one_0001')
            self.submit(model='claude-opus-5-5',text='Koreksi: budget saya 175 juta, bukan 150 juta.',key='managed_context_two_0002')
        self.assertEqual(provider.call_count,2)
        self.assertEqual(provider.call_args.args[1].selected_model,offering.CHAT_MODEL)
        self.assertIn('175 juta',str(provider.call_args.args[1]))
        messages=agent_store.messages(self.owner,conversation_id=self.conversation)
        self.assertIn('175 juta',str(messages))

    def test_duplicate_send_one_provider_and_no_duplicate_history(self):
        key='managed_duplicate_request_0001'
        with patch.object(providers,'stream',side_effect=fixture.answer) as provider:
            self.submit(key=key);self.submit(key=key)
        self.assertEqual(provider.call_count,1)
        rows=db.query_all('SELECT * FROM kilas_ai_usage WHERE user_id=? AND operation_key=?',(self.owner,'agent-chat-'+key))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['customer_charge_exempt'],1)

    def test_sponsored_costs_recorded_without_topup_or_customer_capacity(self):
        with patch.object(usage,'_qa_quota_exempt',return_value=False),patch('kilas_ai.topups.reserve',side_effect=AssertionError('customer debit')),patch('kilas_ai.topups.settle',side_effect=AssertionError('customer settle')):
            plan,ops=usage.reserve(self.owner,self.thread,'sponsor_chat','FAST','CHAT')
            self.assertEqual(plan,'FREE')
            # Reservation remains exempt even if the deployment flag changes mid-flight.
            with patch.dict(os.environ,{offering.CHAT_FREE_FLAG:'false'}):
                usage.finish(self.owner,'sponsor_chat',ops,success=True,provider='openai',model=offering.CHAT_MODEL,
                             usage={'selected_model':offering.CHAT_MODEL,'input_tokens':200,'output_tokens':100})
            _,ops=usage.reserve(self.owner,self.thread,'sponsor_image','FAST','IMAGE_GENERATE',profile={'image_model':offering.IMAGE_MODEL})
            usage.finish(self.owner,'sponsor_image',ops,success=True,provider='openai',model=offering.IMAGE_MODEL,
                         usage={'selected_image_model':offering.IMAGE_MODEL,'image_token_usage':{'input_tokens':100,'input_tokens_details':{'text_tokens':50,'image_tokens':50},'output_tokens':1000}})
        rows=db.query_all('SELECT * FROM kilas_ai_usage WHERE user_id=?',(self.owner,))
        self.assertEqual(len(rows),2)
        for row in rows:
            self.assertEqual(row['customer_charge_exempt'],1)
            self.assertGreater(Decimal(row['estimated_cost_usd']),0)
            self.assertEqual(row['quota_source'],'BASE')
        self.assertTrue(capacity.summary(self.owner)['available'])
        self.assertIsNone(usage.snapshot(self.owner)['usage']['Gambar']['limit'])
        with patch.dict(os.environ,{offering.CHAT_FREE_FLAG:'false',offering.IMAGE_FREE_FLAG:'false'}):
            state=usage.snapshot(self.owner)
            self.assertTrue(all(item['used']==0 for item in state['usage'].values()))
            conn=usage._connect()
            try:self.assertEqual(capacity.spent(conn,self.owner,usage._now().replace(year=2020),usage._now()),0)
            finally:conn.close()

    def test_sponsored_idempotency_rate_concurrency_and_scope(self):
        _,ops=usage.reserve(self.owner,self.thread,'one','FAST','CHAT')
        self.assertEqual(usage.reserve(self.owner,self.thread,'one','FAST','CHAT'),(None,()))
        usage.reserve(self.owner,self.thread,'two','FAST','CHAT')
        usage.reserve(self.owner,self.thread,'three','FAST','CHAT')
        with self.assertRaises(usage.UsageLimit):usage.reserve(self.owner,self.thread,'four','FAST','CHAT')
        usage.finish(self.owner,'one',ops,success=False,usage={'provider_rejected':True})
        with patch.dict(os.environ,{'KILAS_AI_BURST_PER_MINUTE':'3'}):
            with self.assertRaises(usage.UsageLimit):usage.reserve(self.owner,self.thread,'burst','FAST','CHAT')
        with patch.object(usage,'qa_exempt',return_value=False):
            self.assertEqual(usage.attachment_plan(self.owner),'MAX')
            self.assertEqual(usage.attachment_plan(self.owner,chat=False),'FREE')
        self.assertFalse(offering.admits(self.owner,'kilas_ai.video_page'))
        self.assertFalse(offering.sponsored(self.owner,('VOICEOVER',)))

    def test_quota_rejection_is_zero_cost_no_retries_and_safe_message(self):
        rejection=SimpleNamespace(status_code=429,json=lambda:{'error':{'code':'insufficient_quota','message':'private account detail'}})
        response=SimpleNamespace(__enter__=lambda s:rejection)
        class Reply:
            def __enter__(self):return rejection
            def __exit__(self,*args):pass
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(selected_provider.requests,'post',return_value=Reply()) as post:
            context=chat_models.bind(fixture.model_policy.ChatContext([{'role':'user','content':'Halo'}]),offering.CHAT_MODEL)
            with self.assertRaises(providers.ProviderQuotaError):list(providers.stream('FAST',context))
            self.assertEqual(post.call_count,1)
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(selected_image.requests,'post',return_value=rejection) as post:
            with self.assertRaises(tools.ToolUnavailable) as caught:selected_image.generate(offering.IMAGE_MODEL,'A simple orange circle')
            self.assertEqual(caught.exception.code,'provider_quota_exhausted')
            self.assertFalse(caught.exception.usage['billing_unknown'])
            self.assertNotIn('private',str(caught.exception))
            self.assertEqual(post.call_count,1)
        _,ops=usage.reserve(self.owner,self.thread,'quota_failure','FAST','CHAT')
        usage.finish(self.owner,'quota_failure',ops,success=False,provider='openai',model=offering.CHAT_MODEL,usage=providers.ProviderQuotaError.usage)
        row=db.query_one('SELECT * FROM kilas_ai_usage WHERE user_id=? AND operation_key=?',(self.owner,'quota_failure'))
        self.assertEqual((row['status'],Decimal(row['estimated_cost_usd'])),('FAILED',Decimal(0)))

    def test_generation_and_edit_use_exact_high_quality_model_and_original_reference(self):
        import base64
        from PIL import Image
        output=io.BytesIO();Image.new('RGB',(2048,2048),'orange').save(output,'PNG')
        reference=io.BytesIO();Image.new('RGB',(320,240),'navy').save(reference,'PNG')
        raw=reference.getvalue()
        body={'model':offering.IMAGE_MODEL,'data':[{'b64_json':base64.b64encode(output.getvalue()).decode()}],
              'usage':{'input_tokens':100,'input_tokens_details':{'text_tokens':50,'image_tokens':50},'output_tokens':1000}}
        reply=SimpleNamespace(status_code=200,raise_for_status=lambda:None,json=lambda:body)
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(selected_image.requests,'post',return_value=reply) as post:
            generated=tools.image('Create an orange poster with a readable KILAS title')
            self.assertEqual(generated['model'],offering.IMAGE_MODEL)
            self.assertEqual(post.call_args.kwargs['json']['quality'],'high')
            self.assertEqual(post.call_args.kwargs['json']['size'],'2048x2048')
            edited=tools.image('Make the background warmer',source={'filename':'owned.png','mime_type':'image/png','content':raw})
            self.assertEqual(edited['model'],offering.IMAGE_MODEL)
            self.assertTrue(post.call_args.args[0].endswith('/images/edits'))
            self.assertEqual(post.call_args.kwargs['files']['image'][1],raw)
            self.assertNotIn('input_fidelity',post.call_args.kwargs['data'])
            self.assertEqual(post.call_count,2)

    def test_retrieval_cost_survives_later_synthesis_quota_rejection(self):
        _,ops=usage.reserve(self.owner,self.thread,'retrieved_then_quota','FAST','WEB')
        used={'provider_rejected':True,'billing_unknown':False,'cost_components':[
            {'model':offering.CHAT_MODEL,'operation':'WEB_SEARCH','input_tokens':20,'output_tokens':10,'web_search_calls':1}]}
        usage.finish(self.owner,'retrieved_then_quota',ops,success=False,provider='openai',model=offering.CHAT_MODEL,usage=used)
        row=db.query_one('SELECT estimated_cost_usd FROM kilas_ai_usage WHERE user_id=? AND operation_key=?',(self.owner,'retrieved_then_quota'))
        self.assertGreater(Decimal(row['estimated_cost_usd']),0)

    def test_quality_repair_stays_on_luna_and_quota_rejection_never_repairs(self):
        contexts=[]
        def broken(mode,messages,**kwargs):
            contexts.append(messages.selected_model)
            yield {'type':'provider','provider':'openai','model':offering.CHAT_MODEL}
            yield {'type':'delta','text':'PDF sudah dibuat.'}
            yield {'type':'usage','input_tokens':100,'output_tokens':20}
            yield {'type':'finish','reason':'stop'}
        def good(mode,messages,**kwargs):
            contexts.append(messages.selected_model)
            yield from fixture.answer(mode,messages,**kwargs)
        with patch.object(providers,'stream',side_effect=[broken(None,chat_models.bind(fixture.model_policy.ChatContext([]),offering.CHAT_MODEL)),good(None,chat_models.bind(fixture.model_policy.ChatContext([]),offering.CHAT_MODEL))]) as provider:
            self.submit(text='halo',key='quality_managed_luna_0001')
        self.assertEqual(provider.call_count,2)
        self.assertEqual([call.args[1].selected_model for call in provider.call_args_list],[offering.CHAT_MODEL,offering.CHAT_MODEL])
        with patch.object(providers,'stream',side_effect=providers.ProviderQuotaError('quota')) as provider:
            result=self.submit(text='halo',key='quota_managed_luna_0002')
        self.assertEqual(provider.call_count,1)
        self.assertIn('Saldo layanan AI tidak tersedia',result.text)

    def test_staff_sends_owned_file_with_no_plan_or_customer_debit(self):
        staff=repo.create_user(self.id()+'staff@example.test','hash',role='CLIENT_STAFF')
        conversation=agent_store.new_conversation(staff)
        client=self.client(staff)
        with patch.object(providers,'stream',side_effect=fixture.answer) as provider,patch('kilas_ai.topups.settle',side_effect=AssertionError('customer debit')):
            result=client.post('/kilas-ai/agent/chat',data={'csrf_token':'work-csrf','message':'Baca file ini. Jangan buat file baru.',
                'conversation_id':conversation,'operation_key':'staff_file_managed_00001',
                'source_files':(io.BytesIO(b'Budget 175 million.'),'budget.txt')},headers={'X-Agent-Chat':'1'})
            result.get_data()
        self.assertEqual(result.status_code,200)
        self.assertEqual(provider.call_count,1)
        self.assertEqual(provider.call_args.args[1].selected_model,offering.CHAT_MODEL)
        self.assertIn('175 million',str(provider.call_args.args[1]))
        self.assertEqual(db.query_one('SELECT customer_charge_exempt FROM kilas_ai_usage WHERE user_id=?',(staff,))['customer_charge_exempt'],1)
