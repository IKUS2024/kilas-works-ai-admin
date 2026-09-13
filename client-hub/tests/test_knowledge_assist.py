"""Phase 2: mocked Anthropic, explicit-click drafts only, no knowledge persistence."""
import copy
import json
import os
import unittest
from unittest.mock import patch, Mock
import requests
from test_knowledge_setup_v2 import KnowledgeTests, repo, db, hub, knowledge, ai_onboarding
import knowledge_assist as assist


class AssistTests(unittest.TestCase):
    state = KnowledgeTests.state
    form = KnowledgeTests.form

    def setUp(self):
        KnowledgeTests.setUp(self)
        assist._RATE.clear()
        self.assist_url = f'/business/{self.bid}/knowledge-assist'
        self.payload = {'scope':'business', 'context':{'category':'Konsultan'},
                        'fields':{'short_description':'Konsultasi usaha kecil'}, 'clarifications':''}
        self.key = patch.object(ai_onboarding, 'ANTHROPIC_API_KEY', 'unit-test-key')
        self.key.start(); self.addCleanup(self.key.stop)
        self.http = patch.object(assist.requests, 'post')
        self.post = self.http.start(); self.addCleanup(self.http.stop)
        self.respond({'short_description':'Konsultasi untuk usaha kecil.'})

    def respond(self, fields=None, questions=None, warnings=None):
        self.post.return_value = Mock(status_code=200)
        self.post.return_value.json.return_value = {'stop_reason':'end_turn', 'content':[{'type':'text','text':json.dumps(
            {'draft_fields': fields or {}, 'questions': questions or [], 'warnings':warnings or []})}]}

    def sent(self):
        return json.loads(self.post.call_args.kwargs['json']['messages'][0]['content'])

    def test_load_save_readiness_zero_ai_calls(self):
        self.assertEqual(self.client.get(self.url).status_code,200)
        form=self.form(); form['category']='Edited directly'
        self.assertEqual(self.client.post(self.url,data=form).status_code,302)
        profile,services,faqs=self.state()
        knowledge.readiness(profile,services,faqs,{},knowledge.editor(self.bid,services,faqs))
        self.post.assert_not_called()

    def test_click_one_call_and_no_db_mutation(self):
        before=self.state(); config=repo.get_tenant_config_row(self.bid)
        response=self.client.post(self.assist_url,json=self.payload)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['draft_fields']['short_description'],'Konsultasi untuk usaha kecil.')
        self.post.assert_called_once()
        self.assertEqual(self.state(),before)
        self.assertEqual(repo.get_tenant_config_row(self.bid),config)
        self.assertIsNone(knowledge.latest(self.bid))

    def test_business_minimal_context_no_repo_knowledge_fetch(self):
        self.payload['fields'].update(address='Bandung',operating_hours='09-17',business_phone='Public contact')
        with patch.object(repo,'get_business_services',side_effect=AssertionError('whole services fetched')), \
             patch.object(repo,'get_tenant_config_row',side_effect=AssertionError('config fetched')):
            self.assertEqual(self.client.post(self.assist_url,json=self.payload).status_code,200)
        data=self.sent()
        self.assertEqual(set(data),{'business_name','category','fields','clarifications'})
        self.assertNotIn('runtime',str(data)); self.assertNotIn('tenant_id',data)

    def test_service_only_one_card(self):
        self.payload={'scope':'services','context':{'category':'Jasa','short_description':'Bisnis kecil'},
                      'fields':{'name':'Konsultasi','description':'Diskusi','raw':'Catatan kartu ini'}}
        self.respond({'name':'Konsultasi'})
        self.assertEqual(self.client.post(self.assist_url,json=self.payload).status_code,200)
        data=self.sent()
        self.assertEqual(data['fields']['name'],'Konsultasi')
        self.assertNotIn('Catatan lama tanpa format',json.dumps(data))
        self.assertNotIn('Jam buka?',json.dumps(data))

    def test_faq_unknown_policy_questions_only_no_other_data(self):
        self.payload={'scope':'faqs','fields':{'question':'Boleh refund?','answer':''}}
        self.respond({},['Apa kebijakan refund yang benar untuk bisnismu?'])
        with patch.object(repo,'get_business_profile',side_effect=AssertionError('unrelated profile fetched')), \
             patch.object(repo,'get_business_faqs',side_effect=AssertionError('all FAQ fetched')):
            response=self.client.post(self.assist_url,json=self.payload)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['draft_fields'],{})
        self.assertEqual(self.sent()['fields']['answer'],'')
        self.assertIn('jangan isi jawaban',self.post.call_args.kwargs['json']['system'])

    def test_communication_scope(self):
        self.payload={'scope':'communication','context':{'category':'Jasa'},
                      'fields':{'tone':'Ramah','primary_language':'id','customer_salutation':'Kak'}}
        self.respond({'tone':'Ramah dan jelas','customer_salutation':'Kak'})
        self.assertEqual(self.client.post(self.assist_url,json=self.payload).status_code,200)
        self.assertEqual(set(self.sent()['fields']),set(assist.SCOPES['communication']))

    def test_unexpected_model_fields_fail_closed(self):
        self.respond({'package':'PRO','short_description':'Draft'})
        response=self.client.post(self.assist_url,json=self.payload)
        self.assertEqual(response.status_code,502)
        self.assertNotIn('PRO',response.get_data(as_text=True))
        self.assertIsNone(knowledge.latest(self.bid))

    def test_malformed_model_json_safe(self):
        self.post.return_value.json.return_value['content'][0]['text']='not JSON private upstream'
        response=self.client.post(self.assist_url,json=self.payload)
        self.assertEqual(response.status_code,502)
        self.assertEqual(response.json['error'],assist.ERROR)
        self.assertNotIn('private upstream',response.get_data(as_text=True))

    def test_api_failure_and_timeout_safe_no_retry(self):
        for failure in ('http','timeout','network'):
            with self.subTest(failure=failure):
                self.post.reset_mock();self.post.side_effect=None
                self.respond({'short_description':'Draft'})
                if failure=='http': self.post.return_value.status_code=429
                else:self.post.side_effect=requests.Timeout('sensitive error') if failure=='timeout' else requests.ConnectionError('sensitive error')
                response=self.client.post(self.assist_url,json=self.payload)
                self.assertEqual(response.status_code,502)
                self.assertEqual(response.json['error'],assist.ERROR)
                self.post.assert_called_once()

    def test_draft_requires_normal_save(self):
        before=self.state()
        response=self.client.post(self.assist_url,json=self.payload)
        self.assertEqual(self.state(),before)
        form=self.form()
        for key,value in response.json['draft_fields'].items():form[key]=value
        self.assertEqual(self.client.post(self.url,data=form).status_code,302)
        self.assertEqual(repo.get_business_profile(self.bid)['short_description'],'Konsultasi untuk usaha kecil.')
        self.post.assert_called_once()

    def test_tenant_authorization_login_and_package_gate(self):
        other_user=repo.create_user('other-assist@test.com','unused')
        other=repo.create_business(other_user,'Private','AI_ADMIN_BASIC')
        self.assertEqual(self.client.post(f'/business/{other}/knowledge-assist',json=self.payload).status_code,404)
        self.assertEqual(hub.app.test_client().post(self.assist_url,json=self.payload).status_code,302)
        db.execute("UPDATE businesses SET package='NONE' WHERE id=?",(self.bid,))
        self.assertEqual(self.client.post(self.assist_url,json=self.payload).status_code,403)
        self.post.assert_not_called()

    def test_json_csrf_required_and_valid_header_succeeds(self):
        with patch.dict(hub.app.config,{'CLIENT_HUB_FORCE_CSRF_IN_TESTS':True}):
            self.assertEqual(self.client.post(self.assist_url,json=self.payload).status_code,400)
            self.post.assert_not_called()
            self.client.get(self.url)
            with self.client.session_transaction() as session:
                token=session.get('_csrf_token') or session.get('csrf_token')
            self.assertTrue(token)
            self.assertEqual(self.client.post(self.assist_url,json=self.payload,headers={'X-CSRF-Token':token}).status_code,200)

    def test_question_warning_type_and_count_limits(self):
        for key,value in [('questions',['q']*4),('warnings',['w']*4),('questions','wrong'),('warnings',[3])]:
            with self.subTest(key=key,value=value):
                result={'draft_fields':{},'questions':[],'warnings':[]};result[key]=value
                with self.assertRaises(ValueError):assist.validate_result(result,'business')

    def test_request_and_input_bounds(self):
        for payload in ({'scope':'unsupported'}, {'scope':[]}, {'scope':'business','fields':{'token':'secret'}},
                        {'scope':'business','fields':{'short_description':'x'*2001}},
                        {'scope':'services','fields':{k:'x'*1100 for k in assist.SCOPES['services']}}):
            with self.subTest(scope=payload.get('scope')):
                self.assertEqual(self.client.post(self.assist_url,json=payload).status_code,400)
        self.assertEqual(self.client.post(self.assist_url,data='x'*24001,content_type='application/json').status_code,413)
        self.post.assert_not_called()

    def test_output_limits_and_truncation_rejected(self):
        for value in ({'draft_fields':{'short_description':'x'*1601},'questions':[],'warnings':[]},
                      {'draft_fields':{'short_description':42},'questions':[],'warnings':[]}):
            with self.assertRaises(ValueError):assist.validate_result(value,'business')
        self.post.return_value.json.return_value['stop_reason']='max_tokens'
        self.assertEqual(self.client.post(self.assist_url,json=self.payload).status_code,502)

    def test_separate_model_budget_fallback_and_timeout(self):
        normal=ai_onboarding.CLIENT_HUB_MODEL
        with patch.dict(os.environ,{'CLIENT_HUB_ASSIST_MODEL':'test-assist-model','CLIENT_HUB_ASSIST_MAX_TOKENS':'9999'}):
            self.client.post(self.assist_url,json=self.payload)
        kwargs=self.post.call_args.kwargs
        self.assertEqual(kwargs['json']['model'],'test-assist-model')
        self.assertEqual(kwargs['json']['max_tokens'],800)
        self.assertEqual(kwargs['timeout'],(5,25));self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(ai_onboarding.CLIENT_HUB_MODEL,normal)
        with patch.dict(os.environ,{'CLIENT_HUB_ASSIST_MODEL':'','CLIENT_HUB_ASSIST_MAX_TOKENS':'bad'}):
            self.client.post(self.assist_url,json=self.payload)
        self.assertEqual(self.post.call_args.kwargs['json']['model'],normal)
        self.assertEqual(self.post.call_args.kwargs['json']['max_tokens'],700)

    def test_missing_api_key_no_request(self):
        with patch.object(ai_onboarding,'ANTHROPIC_API_KEY',''):
            self.assertEqual(self.client.post(self.assist_url,json=self.payload).status_code,502)
        self.post.assert_not_called()

    def test_rate_limit_and_explicit_clarification_second_request(self):
        self.respond({},['Apa layananmu?'])
        self.assertEqual(self.client.post(self.assist_url,json=self.payload).status_code,200)
        self.post.assert_called_once()
        self.payload['clarifications']='Layanan konsultasi usaha kecil.'
        self.client.post(self.assist_url,json=self.payload)
        self.assertEqual(self.post.call_count,2)
        self.assertEqual(self.sent()['clarifications'],self.payload['clarifications'])
        for _ in range(4):self.client.post(self.assist_url,json=self.payload)
        self.assertEqual(self.client.post(self.assist_url,json=self.payload).status_code,429)
        self.assertEqual(self.post.call_count,6)

    def test_input_no_whole_knowledge_or_extra_context_allowed(self):
        for key in ('config','messages','files','services','credentials'):
            payload=copy.deepcopy(self.payload);payload['context'][key]='not allowed'
            self.assertEqual(self.client.post(self.assist_url,json=payload).status_code,400)
        self.post.assert_not_called()

    def test_json_only_contract_prompt_and_bounded_input(self):
        self.client.post(self.assist_url,json=self.payload)
        body=self.post.call_args.kwargs['json']
        self.assertLessEqual(len(body['messages'][0]['content']),4000)
        self.assertIn('Return JSON only',body['system'])
        self.assertIn('Gunakan hanya fakta',body['system'])
        self.assertIn('maksimal 3',body['system'])


if __name__=='__main__':unittest.main()
