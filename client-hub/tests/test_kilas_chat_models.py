"""Selected Chat models: native transports, account metadata and owner accounting.

All inputs are synthetic; Session.request is forbidden. No paid provider call.
"""
import copy
import io
import json
import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import test_kilas_home as fixture
from kilas_ai import chat_models as models, selected_provider, model_policy, providers, agent_store, store, usage, chat_model_tools
import db


def available(model):return {**models.spec(model),'available':True,'images':True,'status':'verified'}

def answer(mode,messages,**kwargs):
    model=messages.selected_model
    yield {'type':'provider',**models.spec(model)} | {'model':model}
    yield {'type':'model_metadata','requested_model':model,'returned_model':model,'provider':models.spec(model)['provider']}
    yield {'type':'delta','text':'Budget tetap 150 juta; tahap berikutnya menguji kebutuhan pelanggan.'}
    yield {'type':'usage','input_tokens':100,'output_tokens':60,'cached_input_tokens':20}
    yield {'type':'finish','reason':'stop'}


class CatalogTests(unittest.TestCase):
    def setUp(self):
        models._cache.clear()
        p=patch('requests.sessions.Session.request',side_effect=AssertionError('Network forbidden'));p.start();self.addCleanup(p.stop)

    def test_all_ten_require_read_only_account_access(self):
        with patch.dict(os.environ,{k:'synthetic-only' for k in models.KEYS.values()}):
            for model in models.CATALOG:
                data={'id':model,'name':'models/'+model,'supportedGenerationMethods':['generateContent'], 'capabilities':{'image_input':{'supported':True}}}
                with self.subTest(model=model),patch.object(models.requests,'get',return_value=SimpleNamespace(status_code=200,json=lambda:data)) as get:
                    self.assertTrue(models.check(model)['available']);self.assertTrue(models.check(model)['available'])
                    self.assertEqual(get.call_count,1);self.assertIn('/models/'+model,get.call_args.args[0])
            self.assertEqual(models.catalog()['default'],'gpt-6.1-sol')
            self.assertEqual(models.spec('gpt-6.1-sol')['name'],'GPT-6.1 Sol')

    def test_missing_forbidden_unknown_mismatch_and_unsupported_are_unavailable(self):
        with patch.dict(os.environ,{k:'' for k in models.KEYS.values()}):self.assertIsNone(models.catalog()['default'])
        for status,data in [(403,{}),(404,{}),(200,{'id':'gpt-6-luna-other'}),(200,{'name':'models/gemini-4-argon','supportedGenerationMethods':[]})]:
            models._cache.clear();model='gemini-4-argon' if 'name' in data else 'gpt-6-luna'
            with patch.dict(os.environ,{k:'synthetic' for k in models.KEYS.values()}),patch.object(models.requests,'get',return_value=SimpleNamespace(status_code=status,json=lambda:data)):
                self.assertFalse(models.check(model)['available'])
        for value in ('unknown',{},['gpt-6-luna']):
            with self.assertRaises(models.SelectionError):models.spec(value)

    def test_effective_prices_cache_writes_and_no_legacy_rate_change(self):
        self.assertEqual(models.estimate('gpt-6.1-sol',1000000,1000000,100000,50000),Decimal('18.67'))
        self.assertEqual(models.rates('claude-haiku-5-5',100001)['input'],Decimal('.50'))
        self.assertEqual(models.rates('gpt-6-astra',272001)['output'],Decimal('75'))
        for model,date,before,after in [('gemini-4-argon','2026-12-01','2','4'),('gemini-3.8-flash','2027-01-01','.75','1.50')]:
            self.assertEqual(models.rates(model,now=datetime(2026,10,17,tzinfo=timezone.utc))['input'],Decimal(before))
            self.assertEqual(models.rates(model,now=datetime.fromisoformat(date).replace(tzinfo=timezone.utc))['input'],Decimal(after))
        self.assertEqual(usage.estimate('gpt-6.1-sol',1000000,1000000,'CHAT'),'12.000000')

    def test_adaptive_depth_is_bounded_and_exact_model_survives(self):
        for prompt in ('Halo','Explain a database index','Analisis desain arsitektur ini dengan risiko dan tradeoffs untuk 100 pengguna.'):
            context=models.bind(model_policy.ChatContext([{'role':'user','content':prompt}]),'claude-opus-5-5')
            profile=model_policy.chat_profile(context)
            self.assertEqual(profile['model'],'claude-opus-5-5');self.assertGreaterEqual(profile['output_tokens'],2048)
            self.assertLessEqual(profile['output_tokens'],24576);self.assertIn(profile['effort'],('low','medium','high'))


class NativeTests(CatalogTests):
    def test_native_payloads_every_model_and_usage(self):
        for model in models.CATALOG:
            provider=models.spec(model)['provider']
            if provider=='openai':events=[{'model':model,'choices':[{'delta':{'content':'Jawaban'},'finish_reason':'stop'}],'usage':{'prompt_tokens':20,'completion_tokens':10,'prompt_tokens_details':{'cached_tokens':3,'cache_write_tokens':2}}}]
            elif provider=='anthropic':events=[{'type':'message_start','message':{'model':model,'usage':{'input_tokens':15,'cache_read_input_tokens':3,'cache_creation_input_tokens':2,'output_tokens':0}}},{'delta':{'type':'text_delta','text':'Jawaban'}},{'delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':10}}]
            else:events=[{'modelVersion':model,'candidates':[{'content':{'parts':[{'text':'Jawaban'}]},'finishReason':'STOP'}],'usageMetadata':{'promptTokenCount':20,'candidatesTokenCount':8,'thoughtsTokenCount':2,'cachedContentTokenCount':3}}]
            response=SimpleNamespace(raise_for_status=lambda:None)
            class Response:
                def __enter__(self):return response
                def __exit__(self,*args):pass
            context=models.bind(model_policy.ChatContext([{'role':'user','content':'Budget 150 juta'},{'role':'assistant','content':'Baik'},{'role':'user','content':'Lanjutkan'}]),model)
            with self.subTest(model=model),patch.object(models,'check',side_effect=available),patch.object(selected_provider.requests,'post',return_value=Response()) as post,patch.object(providers,'_events',return_value=iter(events)):
                output=list(providers.stream('FAST',context));payload=post.call_args.kwargs['json']
                self.assertEqual(''.join(e['text'] for e in output if e['type']=='delta'),'Jawaban')
                self.assertEqual(next(e for e in output if e['type']=='model_metadata')['returned_model'],model)
                tokens={};[tokens.update(e) for e in output if e['type']=='usage'];self.assertEqual(tokens['input_tokens'],20);self.assertEqual(tokens['output_tokens'],10)
                self.assertEqual(post.call_count,1)
                if provider=='google':self.assertIn(model,post.call_args.args[0]);self.assertEqual(payload['contents'][1]['role'],'model');self.assertIn('systemInstruction',payload)
                else:self.assertEqual(payload['model'],model)
                if provider=='anthropic':self.assertIn('system',payload);self.assertEqual(payload['thinking']['type'],'adaptive')
                if provider=='openai':self.assertEqual(payload['messages'][0]['role'],'system');self.assertFalse(payload['store'])

    def test_mismatch_unknown_attachments_and_no_fallback(self):
        with self.assertRaises(providers.ProviderError):selected_provider._returned('gpt-6.1-sol','gpt-6-luna')
        self.assertEqual(selected_provider._returned('gpt-6.1-sol','gpt-6.1-sol-2026-10-01'),'gpt-6.1-sol-2026-10-01')
        with self.assertRaises(providers.ProviderError):selected_provider._parts([{'type':'file','id':'x'}])
        image=[{'type':'image_url','image_url':{'url':'data:image/png;base64,YQ=='}}]
        self.assertEqual(selected_provider._parts(image,True)[0]['inlineData']['mimeType'],'image/png')
        with patch.object(models,'check',return_value={**available('gpt-6-luna'),'images':False}):
            with self.assertRaises(models.SelectionError):models.validate_messages('gpt-6-luna',[{'content':image}])
        context=models.bind(model_policy.ChatContext([{'role':'user','content':'Halo'}]),'gpt-6.1-sol')
        with patch.object(models,'check',side_effect=available),patch.object(selected_provider.requests,'post',side_effect=selected_provider.requests.ConnectionError()) as post:
            with self.assertRaises(providers.ProviderError):list(providers.stream('FAST',context))
            self.assertEqual(post.call_count,1)


class RouteTests(unittest.TestCase):
    client=fixture.HomeTests.client
    def setUp(self):
        fixture.HomeTests.setUp(self)
        p=patch.object(models,'check',side_effect=available);p.start();self.addCleanup(p.stop)
        self.thread=store.create_thread(self.owner)
        self.key=0

    def submit(self,model='gpt-6.1-sol',text='Budget saya 150 juta. Apa langkah awal?',agent=True,key=None,**extra):
        self.key+=1
        data={'selected_model':model,'operation_key':key or ('model_synthetic_'+str(self.key).zfill(18)),'csrf_token':'work-csrf',**extra}
        if agent:data.update(message=text,conversation_id=self.conversation);path='/kilas-ai/agent/chat'
        else:data['content']=text;path=f'/kilas-ai/threads/{self.thread}/send'
        result=self.client().post(path,data=data,headers={'X-Agent-Chat':'1'});result.get_data();return result

    def test_catalog_auth_csrf_and_owner_isolation(self):
        client=self.client();url=f'/kilas-ai/chat/models?surface=conversation&conversation_id={self.conversation}'
        result=client.get(url);self.assertEqual(result.status_code,200);self.assertEqual(len(result.json['models']),10)
        result=client.post('/kilas-ai/chat/model',json={'surface':'conversation','conversation_id':self.conversation,'model':'claude-sonnet-5-5'},headers={'X-CSRF-Token':'work-csrf'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(self.client(self.other).get(url).status_code,404)
        self.assertNotEqual(client.post('/kilas-ai/chat/model',json={'surface':'conversation','conversation_id':self.conversation,'model':'gpt-6-luna'}).status_code,200)
        for value in ('unknown',{},['gpt-6-luna']):
            self.assertEqual(client.post('/kilas-ai/chat/model',json={'surface':'conversation','conversation_id':self.conversation,'model':value},headers={'X-CSRF-Token':'work-csrf'}).status_code,400)

    def test_multiturn_switch_keeps_history_and_actual_model_and_duplicate_once(self):
        for agent in (True,False):
            seen=[]
            def stream(mode,messages,**kwargs):seen.append(copy.deepcopy(messages));return answer(mode,messages,**kwargs)
            with patch.object(providers,'stream',side_effect=stream):
                self.assertEqual(self.submit(agent=agent).status_code,200)
                self.assertEqual(self.submit('claude-sonnet-5-5','Lanjutkan, pertahankan budget tadi.',agent=agent,key='model_duplicate_00000001').status_code,200)
                self.submit('claude-sonnet-5-5','Lanjutkan, pertahankan budget tadi.',agent=agent,key='model_duplicate_00000001')
            self.assertEqual(len(seen),2);self.assertEqual(seen[1].selected_model,'claude-sonnet-5-5');self.assertIn('150 juta',str(seen[1]))
            self.assertEqual(models.preference(self.owner,'conversation' if agent else 'thread',self.conversation if agent else self.thread),'claude-sonnet-5-5')
            if agent:
                row=agent_store.messages(self.owner,conversation_id=self.conversation)[-1];self.assertEqual(row['returned_model'],'claude-sonnet-5-5')
            else:self.assertEqual(json.loads(store.messages(self.owner,self.thread)[-1]['metadata_json'])['model_metadata']['returned_model'],'claude-sonnet-5-5')
            rows=db.query_all('SELECT * FROM kilas_ai_usage WHERE user_id=? AND model=?',(self.owner,'claude-sonnet-5-5'))
            self.assertTrue(rows);self.assertTrue(all(row['status']=='COMPLETE' for row in rows));self.assertTrue(all(Decimal(row['estimated_cost_usd'])>0 for row in rows))

    def test_invalid_and_unavailable_stop_before_mutation_or_dispatch(self):
        for agent in (True,False):
            with patch.object(providers,'stream',side_effect=AssertionError('Must not dispatch')):
                self.assertEqual(self.submit('not-a-model',agent=agent).status_code,400)
                with patch.object(models,'check',return_value={**available('gpt-6.1-sol'),'available':False}):self.assertEqual(self.submit(agent=agent).status_code,400)
        self.assertFalse(db.query_all('SELECT * FROM kilas_ai_usage WHERE user_id=?',(self.owner,)))

    def test_synthetic_document_retained_and_no_execution(self):
        with patch.object(providers,'stream',side_effect=answer) as stream:
            result=self.submit('gemini-4-argon','Baca file, jangan buat file baru.',source_files=[(io.BytesIO(b'Synthetic budget: 150 juta.'),'budget.txt')])
        self.assertEqual(result.status_code,200);self.assertIn('Synthetic budget',str(stream.call_args.args[1]))

    def test_selected_search_synthesis_and_failure_recovery(self):
        retrieval={'model':'gpt-6-luna','text':'Fakta sintetis A.','citations':[{'url':'https://example.test/a','title':'Source A'}],'usage':{'input_tokens':100,'output_tokens':50,'web_search_calls':1}}
        for agent in (True,False):
            with patch('kilas_ai.tools.web_search_steps',side_effect=lambda *a,**k:iter([{'result':copy.deepcopy(retrieval)}])),patch.object(providers,'stream',side_effect=answer) as stream:
                response=self.submit('claude-opus-5-5','Cari informasi terbaru tentang topik sintetis.',agent=agent)
                self.assertEqual(response.status_code,200);self.assertEqual(stream.call_args.args[1].selected_model,'claude-opus-5-5')
            with patch('kilas_ai.tools.web_search_steps',side_effect=lambda *a,**k:iter([{'result':copy.deepcopy(retrieval)}])),patch.object(providers,'stream',side_effect=providers.ProviderError('synthetic_failure')):
                response=self.submit('claude-opus-5-5','Cari informasi terbaru tentang topik sintetis.',agent=agent)
                self.assertIn('error',response.text)
        rows=db.query_all('SELECT status,estimated_cost_usd FROM kilas_ai_usage WHERE user_id=?',(self.owner,));self.assertTrue(any(row['status']=='FAILED' and Decimal(row['estimated_cost_usd'])>0 for row in rows))

    def test_truncation_is_not_completed_and_retry_stays_selected(self):
        def truncated(mode,messages,**kwargs):
            yield from [event if event['type']!='finish' else {'type':'finish','reason':'length'} for event in answer(mode,messages)]
        with patch.object(providers,'stream',side_effect=truncated) as stream:
            response=self.submit('gemini-3.8-flash')
        self.assertNotIn('"type": "done"',response.text);self.assertEqual(stream.call_count,2)
        self.assertTrue(all(call.args[1].selected_model=='gemini-3.8-flash' for call in stream.call_args_list))

    def test_pending_premium_reservation_and_idempotent_settlement(self):
        from kilas_ai import capacity
        from datetime import timedelta
        now=usage._now()
        db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PLUS','ACTIVE',?,?)",(self.owner,(now-timedelta(days=1)).isoformat(),(now+timedelta(days=29)).isoformat()))
        profile={'model':'gpt-6-astra','selected_model':'gpt-6-astra','difficulty':'NORMAL','output_tokens':15000,'input_token_bound':12000}
        key='selected_pending_00000001'
        with patch.object(capacity,'allowance',return_value=Decimal('1')):
            _,operations=usage.reserve(self.owner,self.thread,key,'FAST','CHAT',profile=profile)
            row=db.query_one('SELECT model,estimated_cost_usd FROM kilas_ai_usage WHERE user_id=? AND operation_key=?',(self.owner,key))
            self.assertEqual(row['model'],'gpt-6-astra');self.assertEqual(Decimal(row['estimated_cost_usd']),Decimal('.90'))
            with self.assertRaises(usage.UsageLimit):usage.reserve(self.owner,self.thread,key+'next','FAST','CHAT',profile=profile)
        tokens={'input_tokens':100,'output_tokens':60,'cached_input_tokens':20,'selected_model':'gpt-6-astra'}
        usage.finish(self.owner,key,operations,success=True,provider='openai',model='gpt-6-astra',usage=tokens)
        usage.finish(self.owner,key,operations,success=True,provider='openai',model='gpt-6-astra',usage={**tokens,'output_tokens':99999})
        row=db.query_one('SELECT estimated_cost_usd FROM kilas_ai_usage WHERE user_id=? AND operation_key=?',(self.owner,key))
        self.assertEqual(Decimal(row['estimated_cost_usd']),Decimal('.003820'))

    def test_search_components_include_selected_cost_and_reject_fx_changes(self):
        result={'model':'gpt-6-luna','text':'100 CNY = 240125 IDR.','citations':[{'url':'https://example.test/a','title':'A'}],
                'usage':{'input_tokens':100,'output_tokens':50,'web_search_calls':1}}
        context=models.bind(model_policy.ChatContext([{'role':'user','content':'100 CNY to IDR'}]),'claude-opus-5-5')
        def unchanged(mode,messages,**kwargs):
            for event in answer(mode,messages):yield {**event,'text':result['text']} if event['type']=='delta' else event
        with patch.object(providers,'stream',side_effect=unchanged):composed=chat_model_tools.compose(copy.deepcopy(result),context)
        self.assertEqual(len(composed['usage']['cost_components']),2)
        self.assertTrue(composed['usage']['cost_components'][-1]['selected_pricing'])
        with patch.object(providers,'stream',side_effect=answer):
            from kilas_ai.tools import ToolUnavailable
            with self.assertRaises(ToolUnavailable) as error:chat_model_tools.compose(copy.deepcopy(result),context)
        self.assertEqual(error.exception.model,'claude-opus-5-5');self.assertFalse(error.exception.usage['billing_unknown'])

    def test_input_reservation_counts_document_text_and_model_results_are_owner_scoped(self):
        context=models.bind(model_policy.ChatContext([{'role':'user','content':"Baca.\n\nTeks berikut berhasil diekstrak dari lampiran 'file.txt'.\n"+'synthetic '*4000}]),'gpt-6.1-sol')
        self.assertGreater(model_policy.chat_profile(context)['input_token_bound'],40000)
        mid=agent_store.append(self.owner,'assistant','Synthetic reply',self.conversation,selected_model='gpt-6.1-sol')
        self.assertEqual(agent_store.messages(self.owner,conversation_id=self.conversation)[-1]['returned_model'],'unreported')
        self.assertEqual(agent_store.messages(self.other,conversation_id=self.conversation),[])
