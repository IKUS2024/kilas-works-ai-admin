"""Multi-turn exact-model search and identity contracts, no external transport."""
import json
import os
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_kilas_chat_models as fixture
import test_kilas_chat_auto_search as search_fixture
import db
from kilas_ai import selected_provider,providers,tools,chat_model_tools,chat_models,model_policy,store,routing,agent_store

URL='https://example.test/current'


class SearchModelTests(unittest.TestCase):
    setUp=fixture.RouteTests.setUp
    client=fixture.RouteTests.client
    submit=fixture.RouteTests.submit

    def native(self,model,text):
        provider=chat_models.spec(model)['provider']
        event=({'model':model,'choices':[{'delta':{'content':text},'finish_reason':'stop'}],'usage':{'prompt_tokens':20,'completion_tokens':30}} if provider=='openai' else
               {'type':'message_start','message':{'model':model,'usage':{'input_tokens':20,'output_tokens':30}}} if provider=='anthropic' else
               {'modelVersion':model,'candidates':[{'content':{'parts':[{'text':text}]},'finishReason':'STOP'}],'usageMetadata':{'promptTokenCount':20,'candidatesTokenCount':30}})
        events=[event]
        if provider=='anthropic':events.extend([{'delta':{'type':'text_delta','text':text}},{'delta':{'stop_reason':'end_turn'}}])
        class Response:
            def __enter__(self):return SimpleNamespace(raise_for_status=lambda:None)
            def __exit__(self,*a):pass
        return Response(),events

    def test_identity_system_uses_current_exact_backend_over_history_for_all_providers(self):
        for model in ('gemini-3.8-flash','claude-sonnet-5-5','gpt-6.1-sol'):
            response,events=self.native(model,'Synthetic selected model answer.')
            context=chat_models.bind(model_policy.ChatContext([{'role':'assistant','content':'Old model was different.'},{'role':'user','content':'Model AI apa sekarang?'}]),model)
            with self.subTest(model=model),patch.object(selected_provider.requests,'post',return_value=response) as post,patch.object(providers,'_events',return_value=iter(events)),patch.dict(os.environ,{k:'synthetic' for k in chat_models.KEYS.values()}):
                result=list(selected_provider.stream('FAST',context))
            payload=post.call_args.kwargs['json'];provider=chat_models.spec(model)['provider']
            system=payload['systemInstruction']['parts'][0]['text'] if provider=='google' else payload['system'] if provider=='anthropic' else payload['messages'][0]['content']
            self.assertIn('API model ID='+model,system);self.assertIn('override model identities mentioned in earlier conversation',system)
            self.assertEqual(next(e['returned_model'] for e in result if e['type']=='model_metadata'),model)
            if provider=='google':self.assertIn('/'+model+':streamGenerateContent',post.call_args.args[0]);self.assertIn('x-goog-api-key',post.call_args.kwargs['headers'])
            self.assertEqual(post.call_count,1)

    def test_several_searches_same_chat_followup_chain_and_normal_chat(self):
        now=datetime.now(timezone.utc)
        db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PLUS','ACTIVE',?,?)",(self.owner,(now-timedelta(days=1)).isoformat(),(now+timedelta(days=29)).isoformat()))
        for model in ('gemini-3.8-flash','claude-sonnet-5-5','gpt-6.1-sol'):
            response,events=self.native(model,'Synthetic current finding. [Official source]('+URL+').')
            with self.subTest(model=model),patch.dict(os.environ,{'KILAS_AI_OPENAI_WEB_MODEL':model_policy.LUNA,**{k:'synthetic' for k in chat_models.KEYS.values()}}),patch.object(tools,'_request',side_effect=lambda *a,**k:search_fixture.response('Synthetic current finding. [Official source]('+URL+').')) as retrieval,patch.object(selected_provider.requests,'post',return_value=response) as post,patch.object(providers,'_events',side_effect=lambda *a,**k:iter(events)):
                for prompt in ('Cari berita teknologi hari ini','Bagaimana yang lainnya?','Yang terbaru lagi?','Cari berita sains hari ini'):
                    result=self.submit(model,prompt,agent=False)
                    self.assertEqual(result.status_code,200);self.assertIn('Synthetic current finding',result.text)
                self.assertEqual(retrieval.call_count,4);self.assertEqual(post.call_count,4)
                self.assertIn('Previous search topic:',retrieval.call_args_list[2].args[0]['input'])
                row=store.messages(self.owner,self.thread)[-1]
                self.assertEqual(json.loads(row['metadata_json'])['model_metadata']['returned_model'],model)
                before=retrieval.call_count
                self.submit(model,'Jelaskan secara singkat arti fotosintesis.',agent=False)
                self.assertEqual(retrieval.call_count,before)
            # New conversation cannot inherit the preceding lookup topic.
            self.assertIsNone(routing.lookup_topic('Yang terbaru lagi?',[]))
            self.assertIsNone(routing.lookup_topic('Sekarang model AI apa?',['Cari berita sains hari ini']))

    def test_timeout_failure_then_next_search_recovers_without_hidden_retry(self):
        model='gemini-3.8-flash';response,events=self.native(model,'Synthetic recovered result. [Source]('+URL+').')
        failure=tools.ToolUnavailable('synthetic timeout',code='provider_timeout')
        with patch.dict(os.environ,{'KILAS_AI_OPENAI_WEB_MODEL':model_policy.LUNA,'GEMINI_API_KEY':'synthetic'}),patch.object(tools,'_request',side_effect=[failure,search_fixture.response('Synthetic recovered result. [Source]('+URL+').')]) as retrieval,patch.object(selected_provider.requests,'post',return_value=response) as post,patch.object(providers,'_events',side_effect=lambda *a,**k:iter(events)):
            first=self.submit(model,'Cari berita sains sekarang',agent=False);self.assertIn('batas waktu',first.text)
            failed=store.messages(self.owner,self.thread)[-1];self.assertEqual(failed['role'],'assistant');self.assertEqual(json.loads(failed['metadata_json'])['status'],'failed')
            second=self.submit(model,'Cari berita teknologi sekarang',agent=False);self.assertIn('Synthetic recovered result',second.text)
            self.assertEqual(retrieval.call_count,2);self.assertEqual(post.call_count,1)

    def test_validated_currency_result_has_no_second_generation_or_false_provenance(self):
        quote=json.dumps({'base':'USD','quote':'IDR','rate':'16000','as_of':datetime.now(timezone.utc).date().isoformat(),'source_url':URL})
        with patch.dict(os.environ,{'KILAS_AI_OPENAI_WEB_MODEL':model_policy.LUNA}),patch.object(tools,'_request',return_value=search_fixture.response(quote)) as retrieval,patch.object(providers,'stream',side_effect=AssertionError('validated arithmetic must not regenerate')):
            result=self.submit('gemini-3.8-flash','1 usd brp rupiah skrg',agent=False)
            self.assertIn('16.000,00',result.text);self.assertEqual(retrieval.call_count,1)
            saved=json.loads(store.messages(self.owner,self.thread)[-1]['metadata_json'])
            self.assertEqual(saved['model_metadata']['response_kind'],'validated_tool_result')
            self.assertFalse(saved['model_metadata']['selected_model_called']);self.assertIsNone(saved['model_metadata']['returned_model'])
            self.assertEqual(chat_models.preference(self.owner,'thread',self.thread),'gemini-3.8-flash')

    def test_synthesis_failure_reason_is_explicit_and_does_not_fallback(self):
        model='gemini-3.8-flash'
        context=chat_models.bind(model_policy.ChatContext([{'role':'user','content':'Cari berita sains hari ini'}]),model)
        evidence={'text':'Synthetic finding.','model':model_policy.LUNA,'citations':[{'url':URL,'title':'Source'}],'usage':{},'search_calls':1}
        with patch.object(providers,'stream',side_effect=providers.ProviderError('selected_model_mismatch')) as dispatch:
            with self.assertRaises(tools.ToolUnavailable) as failure:chat_model_tools.compose(evidence,context)
        self.assertEqual(failure.exception.code,'selected_model_mismatch');self.assertEqual(dispatch.call_count,1)

    def test_diverse_current_topics_use_only_returned_alternate_sources(self):
        alternate='https://official.example.test/accessible'
        evidence=search_fixture.response('Synthetic verified fixture. [Alternate]('+alternate+').')
        evidence['output'][0]['action']={'sources':[{'url':'https://blocked.example.test/denied'},{'url':alternate}]}
        evidence['output'][1]['content'][0]['annotations']=[{'type':'url_citation','url':alternate,'title':'Accessible alternate fixture'}]
        now=datetime.now(timezone.utc)
        db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PLUS','ACTIVE',?,?)",(self.owner,(now-timedelta(days=1)).isoformat(),(now+timedelta(days=29)).isoformat()))
        response,events=self.native('gemini-3.8-flash','Synthetic fixture answer. [Alternate]('+alternate+').')
        with patch.dict(os.environ,{'KILAS_AI_OPENAI_WEB_MODEL':model_policy.LUNA,'GEMINI_API_KEY':'synthetic'}),patch.object(tools,'_request',return_value=evidence) as retrieval,patch.object(selected_provider.requests,'post',return_value=response),patch.object(providers,'_events',side_effect=lambda *a,**k:iter(events)):
            for prompt in ('Cari cuaca Jakarta hari ini','Cari aturan perjalanan Jepang terbaru','Cari versi stabil Python terbaru','Cari harga paket internet terbaru'):
                result=self.submit('gemini-3.8-flash',prompt,agent=False)
                self.assertIn(alternate,result.text);self.assertNotIn('blocked.example.test',result.text)
            self.assertEqual(retrieval.call_count,4)


if __name__=='__main__':unittest.main()
