"""Offline spending, fixture, and durable-once fences for approved QA."""
import contextlib
import base64
from datetime import datetime, timezone, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from threading import Event
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kilas_ai import ai_call_search_smoke as smoke, ai_call as calls, ai_call_budget as budget, ai_call_public_search as search
import db

class SearchSmokeTests(unittest.TestCase):
    def test_default_off_and_exact_pinned_fixture(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(smoke.subprocess,'Popen') as popen:
            self.assertFalse(smoke.launch());popen.assert_not_called()
        self.assertEqual(len(smoke.fixture()),185600)
        self.assertEqual(hashlib.sha256(smoke.fixture()).hexdigest(),smoke.RAW_SHA)

    def test_existing_durable_marker_never_starts_again(self):
        env={smoke.ARM:smoke.RUN,'RENDER_SERVICE_ID':smoke.SERVICE,
             'KILAS_AI_CALL_SMOKE_EXPIRES_AT':(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat()}
        with patch.dict(os.environ,env), patch.object(db,'BACKEND','postgres'), \
             patch.object(budget,'config',return_value={'allowed_owner':1}), \
             patch.object(budget,'owned',return_value={'status':'CLOSED'}), \
             patch.object(calls,'start') as start, contextlib.redirect_stdout(io.StringIO()) as output:
            smoke.run()
        start.assert_not_called()
        self.assertEqual(json.loads(output.getvalue().split(' ',1)[1])['status'],'already_attempted_no_retry')

    def test_one_search_reservation_and_http_only_fixed_public_query(self):
        result={'search_reserve_attempts':0,'web_http_requests':0}
        reserve=Mock(return_value=(None,[{'synthetic':True}]))
        response=Mock(status_code=200)
        response.json.return_value={'output':[{'type':'web_search_call','status':'completed'}],
                                    'usage':{'input_tokens':100,'output_tokens':20,'total_tokens':120}}
        post=Mock(return_value=response);finish=Mock()
        fence=smoke.SearchFence(result,lambda:None,reserve,finish,post,1)
        fence.reserve(1,None,'call-web-synthetic','FAST','WEB')
        with self.assertRaisesRegex(ValueError,'search_reserve_fence'):
            fence.reserve(1,None,'call-web-synthetic-again','FAST','WEB')
        reserve.assert_called_once()
        payload={'model':'gpt-6-luna','input':search.public_query('general',datetime.now(timezone.utc).strftime('%Y-%m-%d')),
                 'tools':[{'type':'web_search'}],'tool_choice':'required','max_tool_calls':1,
                 'max_output_tokens':2048,'store':False}
        with self.assertRaisesRegex(ValueError,'web_request_fence'):
            fence.post('https://api.openai.com/v1/responses',json={**payload,'input':'private arbitrary query'})
        post.assert_not_called()
        fence.post('https://api.openai.com/v1/responses',json=payload,headers={'Authorization':'NEVER_LOG'})
        with self.assertRaisesRegex(ValueError,'web_request_fence'):
            fence.post('https://api.openai.com/v1/responses',json=payload)
        post.assert_called_once();self.assertEqual(result['web_completed_searches'],1)
        self.assertNotIn('NEVER_LOG',json.dumps(result))
        fence.finish(1,'call-web-synthetic',[{}],success=False)
        finish.assert_called_once();self.assertTrue(result['search_settled'])
        self.assertFalse(result['search_finished_success'])

    def test_error_observer_records_only_machine_fields(self):
        result={'web_http_requests':0,'search_reserved':True}
        response=Mock(status_code=400)
        response.json.return_value={'error':{'code':'unsupported_parameter','param':'reasoning.effort',
            'type':'invalid_request_error','message':'NEVER_LOG_PRIVATE'}}
        fence=smoke.SearchFence(result,lambda:None,Mock(),Mock(),Mock(return_value=response),1)
        payload={'model':'gpt-6-luna','input':search.public_query('general',datetime.now(timezone.utc).strftime('%Y-%m-%d')),
                 'tools':[{'type':'web_search'}],'tool_choice':'required','max_tool_calls':1,
                 'max_output_tokens':2048,'store':False}
        fence.post('https://api.openai.com/v1/responses',json=payload)
        self.assertEqual(result['web_error']['code'],'unsupported_parameter')
        self.assertNotIn('NEVER_LOG_PRIVATE',json.dumps(result))

    def failure_scenario(self, respond):
        now=[0.0];holder=[]
        class Socket:
            def __init__(self):
                self.incoming=[];self.pcm=bytearray();self.asked=False;self.after_bridge=None;self.answered=False
            def send(self,raw):
                value=json.loads(raw)
                if 'setup' in value:self.incoming.append({'setupComplete':{}})
                audio=value.get('realtimeInput',{}).get('audio')
                if audio:self.pcm.extend(base64.b64decode(audio['data']))
                if len(self.pcm)>=204800 and not self.asked:
                    self.asked=True
                    self.incoming.append({'serverContent':{'inputTranscription':{'text':
                        'What is the latest news in Indonesia? Search and name a source.'}}})
                    self.incoming.append({'toolCall':{'functionCalls':[{'id':'synthetic','name':search.NAME,
                        'args':{'country':'ID','topic':'general'}}]}})
                if 'toolResponse' in value:self.after_bridge=now[0]
            def recv(self):return json.dumps(self.incoming.pop(0))
            def model_tick(self):
                if respond and self.after_bridge is not None and now[0]>=self.after_bridge+1.2 and not self.answered:
                    self.answered=True
                    self.incoming.append({'serverContent':{'outputTranscription':{'text':
                        'The search timed out. Current information could not be verified.'},
                        'modelTurn':{'parts':[{'inlineData':{'data':'synthetic'}}]},'turnComplete':True}})
        socket=Socket()
        class Call:
            def __init__(self,owner,ident):
                self.owner=owner;self.ident=ident;self.capability=object();self.state='LISTENING'
                self.closed=Event();self.frames=[]
                self.input_bytes=self.sent_chunks=self.queued=self.output_bytes=self.expected=self.turns=0
                self.public_search=Mock(job=None);self.public_search.diagnostic.return_value={}
                self.ws=calls.wire.connect();self.ws.send(json.dumps(calls.setup()));self.ws.recv()
            def accept(self,index,raw):
                self.ws.send(json.dumps({'realtimeInput':{'audio':{'mimeType':'audio/pcm;rate=16000',
                    'data':base64.b64encode(raw).decode()}}}))
                self.input_bytes+=len(raw);self.expected+=1;self.sent_chunks+=1
            def snapshot(self,cursor):
                socket.model_tick()
                while socket.incoming:
                    value=json.loads(self.ws.recv())
                    if 'toolCall' in value:
                        _,operations=search.usage.reserve(self.owner,None,'call-web-offline','FAST','WEB')
                        try:
                            list(search.tools.web_search_steps([{'role':'user','content':search.public_query('general',
                                datetime.now(timezone.utc).strftime('%Y-%m-%d'))}],max_calls=1,
                                request_timeout=search.WEB_READ_SECONDS,minimal_query=True))
                        except search.tools.ToolUnavailable:
                            self.ws.send(json.dumps({'toolResponse':{'functionResponses':[{'id':'synthetic',
                                'name':search.NAME,'response':{'available':False,'reason':'provider_timeout'}}]}}))
                        search.usage.finish(self.owner,'call-web-offline',operations,success=False)
                    if value.get('serverContent',{}).get('turnComplete'):
                        self.turns+=1;self.output_bytes+=4800
                return {'frames':[],'next_index':0}
        def start(owner,ident):
            value=Call(owner,ident);holder.append(value);return value
        def end(*a):holder[0].closed.set();holder[0].frames.clear()
        env={smoke.ARM:smoke.RUN,'RENDER_SERVICE_ID':smoke.SERVICE,'KILAS_AI_OPENAI_WEB_MODEL':'gpt-6-luna',
             'KILAS_AI_CALL_SMOKE_EXPIRES_AT':(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat()}
        with patch.dict(os.environ,env),patch.object(smoke,'armed',return_value=True), \
             patch.object(db,'BACKEND','postgres'),patch.object(db,'_discard_cached_connection'), \
             patch.object(budget,'config',return_value={'allowed_owner':1,'reserve':250000}), \
             patch.object(budget,'owned',return_value=None),patch.object(budget,'status',return_value={'available':True}), \
             patch.object(budget,'active',return_value=False),patch.object(search,'configured',return_value=True), \
             patch.object(calls.wire,'connect',return_value=socket),patch.object(calls,'start',side_effect=start), \
             patch.object(calls,'end',side_effect=end),patch.object(smoke,'Timer'), \
             patch.object(search.usage,'reserve',return_value=('PLUS',('WEB_SEARCH',))), \
             patch.object(search.usage,'finish'),patch.object(search.tools,'_openai_key',return_value='offline'), \
             patch.object(search.tools.requests,'post',side_effect=search.tools.requests.ReadTimeout('SYNTHETIC')), \
             patch.object(smoke.time,'monotonic',side_effect=lambda:now[0]), \
             patch.object(smoke.time,'sleep',side_effect=lambda seconds:now.__setitem__(0,now[0]+seconds)), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            smoke.run()
        return json.loads(output.getvalue().splitlines()[-1].split(' ',1)[1])

    def test_failure_bridge_is_followed_by_observed_model_turn_before_end(self):
        result=self.failure_scenario(True)
        self.assertEqual(result['status'],'completed_failure_transport')
        self.assertEqual(result['completed_responses'],1)
        self.assertIn('could not be verified',result['response_text'])
        self.assertGreater(result['duration_ms'],result['bridge_sent_ms']+1000)
        self.assertEqual(result['provider_connections'],1);self.assertEqual(result['web_http_requests'],1)
        self.assertEqual(result['web_timeout_kind'],'read')
        self.assertEqual(result['search_reserve_attempts'],1)
        self.assertTrue(result['search_settled']);self.assertTrue(result['call_settled'])
        self.assertTrue(result['search_worker_finished']);self.assertEqual(result['manual_markers'],0)

    def test_missing_failure_speech_has_bounded_wait_and_no_retry(self):
        result=self.failure_scenario(False)
        self.assertEqual(result['code'],'spoken_response_timeout')
        self.assertLessEqual(result['duration_ms']-result['bridge_sent_ms'],30200)
        self.assertEqual(result['provider_connections'],1);self.assertEqual(result['web_http_requests'],1)
        self.assertTrue(result['search_settled']);self.assertTrue(result['call_settled'])
        self.assertLessEqual(result['accepted_bytes'],40*32000)

    def test_normal_metering_boundaries_and_both_completion_outcomes(self):
        self.assertLess(smoke.SESSION_SECONDS,budget.RENEW_SECONDS)
        self.assertLess(smoke.INPUT_SECONDS*32000,calls.INPUT_BYTES)
        self.assertIsNone(smoke.completion_status({'response_turn_target':1,'bridge':{'available':False}},0))
        self.assertEqual(smoke.completion_status({'response_turn_target':1,'bridge':{'available':True}},1),
                         'completed_transport')

if __name__=='__main__':unittest.main()
