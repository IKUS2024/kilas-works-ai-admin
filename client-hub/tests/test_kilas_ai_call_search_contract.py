"""Documented cap envelopes, provenance and complete-answer gates; no IO."""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kilas_ai import ai_call_search_contract as contract, ai_call_public_search as call_search, tools


def capped():
    return {'status':'completed','max_tool_calls':1,'error':None,'incomplete_details':None,
        'output':[
            {'id':'search-done','type':'web_search_call','status':'completed','action':{'type':'search',
                'sources':[{'type':'url','url':'https://example.org/current'}]}},
            {'id':'search-ignored','type':'web_search_call','status':'incomplete',
                'action':{'type':'search','query':'Synthetic ignored attempt'}},
            {'id':'answer','type':'message','role':'assistant','status':'completed',
                'content':[{'type':'output_text','text':'Synthetic cited finding.',
                    'annotations':[{'type':'url_citation','url':'https://example.org/current','title':'Synthetic Source'}]}]}],
        'usage':{'input_tokens':120,'output_tokens':40}}


class ContractTests(unittest.TestCase):
    def execute(self, data, *, normalizer=True, query=None):
        response=Mock();response.json.return_value=data
        kwargs={'response_normalizer':contract.completed_response} if normalizer else {}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'offline','KILAS_AI_OPENAI_WEB_MODEL':'gpt-6-luna'}), \
             patch.object(tools.requests,'post',return_value=response) as post:
            value=list(tools.web_search_steps([{'role':'user','content':query or call_search.public_query('general','2026-10-17')}],
                max_calls=1,request_timeout=25,verify_currency=True,minimal_query=True,**kwargs))[-1]['result']
        post.assert_called_once()
        payload=post.call_args.kwargs['json']
        self.assertEqual(payload['max_tool_calls'],1);self.assertEqual(payload['max_output_tokens'],2048)
        self.assertEqual(payload['tool_choice'],'required');self.assertFalse(payload['store'])
        return value

    def reject(self, data):
        self.assertIs(contract.completed_response(data),data)
        with self.assertRaises(tools.ToolUnavailable):self.execute(data)

    def test_completed_answer_uses_only_completed_search_after_ignored_cap_attempt(self):
        data=capped();before=copy.deepcopy(data)
        normalized=contract.completed_response(data)
        self.assertEqual(data,before);self.assertIsNot(normalized,data)
        self.assertEqual([i['id'] for i in normalized['output']],['search-done','answer'])
        result=self.execute(data)
        self.assertEqual(result['text'],'Synthetic cited finding.')
        self.assertEqual(result['search_calls'],1)
        self.assertEqual(result['citations'][0]['url'],'https://example.org/current')
        self.assertEqual(result['usage']['input_tokens'],120)
        self.assertEqual(result['usage']['output_tokens'],40)
        self.assertEqual(result['usage']['cost_components'][0]['operation'],'WEB_SEARCH')

    def test_other_tools_callers_remain_strict_without_call_only_normalizer(self):
        with self.assertRaises(tools.ToolUnavailable) as error:self.execute(capped(),normalizer=False)
        self.assertEqual(error.exception.code,'search_not_completed')

    def test_failed_running_missing_and_unknown_search_statuses_remain_rejected(self):
        for state in ('failed','searching','in_progress',None,'unknown','cancelled'):
            with self.subTest(state=state):
                data=capped();data['output'][1]['status']=state;self.reject(data)

    def test_actual_unknown_live_status_is_not_relabelled_as_cap_ignored(self):
        data=capped();data['output'][1].pop('status');self.reject(data)
        self.assertEqual(contract.envelope_summary(data)['items']['web_search_call:missing'],1)

    def test_incomplete_overall_answer_error_and_missing_cap_evidence_fail_closed(self):
        for key,value in [('status','incomplete'),('status','failed'),('max_tool_calls',None),
                ('max_tool_calls',2),('max_tool_calls',True),('error',{'code':'synthetic'}),
                ('incomplete_details',{'reason':'max_output_tokens'})]:
            with self.subTest(key=key,value=value):
                data=capped();data[key]=value;self.reject(data)

    def test_incomplete_or_nonfinal_messages_and_reasoning_are_not_completed_answers(self):
        for key,value in [('status','incomplete'),('status','in_progress'),('role','user'),('phase','commentary')]:
            with self.subTest(key=key,value=value):
                data=capped();data['output'][-1][key]=value;self.reject(data)
        data=capped();data['output'].insert(2,{'id':'reasoning','type':'reasoning','status':'incomplete'})
        self.reject(data)

    def test_only_completed_source_urls_can_support_final_citations(self):
        for source in (None,[],[{'type':'url','url':'https://user:password@example.org/current'}]):
            data=capped();data['output'][0]['action']['sources']=source;self.reject(data)
        data=capped();data['output'][-1]['content'][0]['annotations'][0]['url']='https://example.org/unverified'
        data['output'][1]['action']['sources']=[{'type':'url','url':'https://example.org/unverified'}]
        self.reject(data)
        data=capped();data['output'][-1]['content'][0]['annotations']=[];self.reject(data)
        data=capped();data['output'][-1]['content'][0]['text']='';self.reject(data)
        data=capped();data['output'][1]['action']['results']=['Unfinished evidence'];self.reject(data)

    def test_uncompleted_item_before_search_or_after_answer_is_not_an_ignored_cap_attempt(self):
        for order in ([1,0,2],[0,2,1]):
            data=capped();data['output']=[data['output'][i] for i in order];self.reject(data)
        data=capped();data['output'][1]['id']='search-done';self.reject(data)
        data=capped();data['output'].append({'id':'pending','type':'function_call','status':'in_progress'})
        self.reject(data)

    def test_extra_completed_search_exceeds_one_call_contract(self):
        data=capped();extra=copy.deepcopy(data['output'][0]);extra['id']='second-done'
        data['output'].insert(1,extra);self.reject(data)

    def test_ordinary_completed_result_is_unchanged_and_no_search_remains_unavailable(self):
        data=capped();del data['output'][1]
        self.assertIs(contract.completed_response(data),data);self.execute(data)
        data['output']=data['output'][-1:]
        with self.assertRaises(tools.ToolUnavailable):self.execute(data)

    def test_existing_dated_currency_provenance_validation_still_applies(self):
        for date,expected in [('2020-01-01',False),(datetime.now(timezone.utc).date().isoformat(),True)]:
            data=capped();data['output'][-1]['content'][0]['text']=json.dumps({'base':'USD','quote':'IDR',
                'rate':'16000','as_of':date,'source_url':'https://example.org/current'})
            if expected:
                self.assertIn('16',self.execute(data,query='1 USD to IDR: current published exchange rate')['text'])
            else:
                with self.assertRaises(tools.ToolUnavailable) as error:
                    self.execute(data,query='1 USD to IDR: current published exchange rate')
                self.assertEqual(error.exception.code,'rate_not_current')

    def test_default_off_observer_summary_never_copies_private_or_unrecognized_values(self):
        data=capped();data['output'][1]['action']['query']='PRIVATE_SENTINEL'
        data['output'].append({'id':'PRIVATE_SENTINEL','type':'PRIVATE_SENTINEL','status':'PRIVATE_SENTINEL'})
        summary=contract.envelope_summary(data)
        self.assertNotIn('PRIVATE_SENTINEL',json.dumps(summary))
        self.assertNotIn('example.org',json.dumps(summary))
        self.assertEqual(summary['items']['web_search_call:completed'],1)
        self.assertEqual(summary['items']['web_search_call:incomplete'],1)
        self.assertEqual(summary['ordered_items'][:2],['web_search_call:completed','web_search_call:incomplete'])
        self.assertEqual(summary['items']['other:other'],1)
        contract.envelope_summary({'status':[],'output':[{'type':{},'status':[]}]})


if __name__=='__main__':unittest.main()
