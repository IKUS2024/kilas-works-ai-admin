"""Offline spending, fixture, and durable-once fences for approved QA."""
import contextlib
from datetime import datetime, timezone, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
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

if __name__=='__main__':unittest.main()
