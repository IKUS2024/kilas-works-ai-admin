"""Owned diagnostic scope and exact transport invariants; synthetic/mocked only."""
import copy
import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from flask import session
import test_kilas_managed_offering as fixture
from test_kilas_visual_grounding import image, image_bytes
from kilas_ai import attachments, chat_models, model_policy, providers, selected_provider, store
from kilas_ai import vision_experiment as experiment


class ExperimentTests(unittest.TestCase):
    client = fixture.ManagedOfferingTests.client
    submit = fixture.ManagedOfferingTests.submit

    def setUp(self):
        fixture.ManagedOfferingTests.setUp(self)
        p = patch.dict(os.environ, {experiment.FLAG: ''});p.start();self.addCleanup(p.stop)
        self.sample = image('navy')
        self.first, _ = store.append_user_once(self.owner, self.thread, 'Synthetic object question.', 'SMART', 'eval_first_synthetic')
        store.save_attachments(self.owner, self.thread, self.first, [self.sample])

    def context(self, model=experiment.MODEL, samples=None):
        blocks = attachments.prompt_content('Synthetic object question.', samples or [self.sample])
        return chat_models.bind(model_policy.ChatContext([{'role': 'user', 'content': blocks}]), model)

    def bind(self, context, arm='auto', user=None, path=None):
        user = self.owner if user is None else user
        path = path or f'/kilas-ai/threads/{self.thread}/send'
        config = json.dumps({str(self.thread): arm})
        with patch.dict(os.environ, {experiment.FLAG: config}), self.client().application.test_request_context(path, method='POST'):
            session['user_id'] = user
            experiment.bind(context, user, self.thread)
        return context

    def payload(self, context):
        return {'model': experiment.MODEL, 'messages': [{'role': 'system', 'content': 'Synthetic system.'}]+list(context),
                'reasoning_effort': 'medium', 'max_completion_tokens': 8192, 'store': False,
                'stream': True, 'stream_options': {'include_usage': True}}

    def test_default_off_has_no_scope_queries_or_payload_changes(self):
        context = self.context();payload = self.payload(context)
        with patch.object(store, 'thread', side_effect=AssertionError('No extra query when OFF')), \
             patch.object(experiment, '_emit') as emit:
            experiment.bind(context, self.owner, self.thread)
            result, diag = experiment.begin(context, payload)
        self.assertIs(result, payload);self.assertIsNone(diag);emit.assert_not_called()

    def test_malformed_configuration_is_completely_inactive(self):
        for raw in ('', '{}', '[]', 'null', 'true', '{', '{"1":"high","1":"auto"}',
                    '{"01":"high"}', '{"-1":"high"}', '{"1":true}', '{"1":{}}',
                    '{"9223372036854775808":"high"}', '{"1":"original"}',
                    json.dumps({str(i): 'high' for i in range(1, 10)}), ' '*2049):
            with self.subTest(raw=raw[:40]), patch.dict(os.environ, {experiment.FLAG: raw}):
                self.assertEqual(experiment.configured(), {})
        with patch.dict(os.environ, {experiment.FLAG: '{"1":"auto","2":"high"}'}):
            self.assertEqual(experiment.configured(), {'1': 'auto', '2': 'high'})

    def test_foreign_owner_wrong_route_session_or_model_cannot_bind(self):
        for user, path, model in ((self.other, None, experiment.MODEL),
                (self.owner, '/kilas-ai/agent/chat', experiment.MODEL),
                (self.owner, f'/kilas-ai/threads/{self.thread}/voice-script', experiment.MODEL),
                (self.owner, None, 'gpt-6.1-sol')):
            with self.subTest(user=user, path=path, model=model):
                context = self.bind(self.context(model), user=user, path=path)
                self.assertFalse(hasattr(context, '_vision_experiment'))
        context = self.context()
        with patch.dict(os.environ, {experiment.FLAG: json.dumps({str(self.thread): 'high'})}), \
             self.client().application.test_request_context(f'/kilas-ai/threads/{self.thread}/send', method='POST'):
            experiment.bind(context, self.owner, self.thread)  # No authenticated session.
        self.assertFalse(hasattr(context, '_vision_experiment'))

    def test_second_turn_is_not_an_experiment(self):
        store.append_user_once(self.owner, self.thread, 'Synthetic follow-up.', 'SMART', 'eval_second_synthetic')
        self.assertFalse(hasattr(self.bind(self.context(), 'high'), '_vision_experiment'))

    def test_configured_scope_is_not_bound_outside_http_or_in_another_thread(self):
        context = self.context()
        with patch.dict(os.environ, {experiment.FLAG:json.dumps({str(self.thread):'high'})}):
            experiment.bind(context, self.owner, self.thread)
        self.assertFalse(hasattr(context, '_vision_experiment'))
        context = self.bind(self.context(), 'high', path=f'/kilas-ai/threads/{self.thread+1}/send')
        self.assertFalse(hasattr(context, '_vision_experiment'))

    def test_http_ownership_auth_and_csrf_are_not_widened_by_configuration(self):
        url = f'/kilas-ai/threads/{self.thread}/send'
        data = {'content':'Synthetic question.', 'operation_key':'eval_unauthorized_synthetic',
                'csrf_token':'work-csrf', 'vision_detail':'high'}
        with patch.dict(os.environ, {experiment.FLAG:json.dumps({str(self.thread):'high'})}), \
             patch.object(selected_provider.requests, 'post', side_effect=AssertionError('Unauthorized inference')) as post, \
             patch.object(experiment, '_emit') as emit:
            self.assertEqual(self.client(self.other).post(url, data=data).status_code, 404)
            client = self.client()
            with client.session_transaction() as state:state.clear()
            self.assertEqual(client.post(url, data=data).status_code, 401)
            data['csrf_token'] = 'invalid-synthetic'
            authenticated = self.client(self.owner)
            with patch.dict(authenticated.application.config, {'CLIENT_HUB_FORCE_CSRF_IN_TESTS':True}):
                self.assertEqual(authenticated.post(url, data=data).status_code, 400)
        post.assert_not_called();emit.assert_not_called()

    def test_auto_is_identical_and_high_changes_only_detail_not_source_context_or_budget(self):
        for arm in ('auto', 'high'):
            with self.subTest(arm=arm), patch.object(experiment, '_emit') as emit:
                context = self.bind(self.context(), arm)
                payload = self.payload(context);original = copy.deepcopy(payload)
                result, diag = experiment.begin(context, payload)
                self.assertIsNotNone(diag)
                self.assertEqual(payload, original)
                self.assertEqual(image_bytes(result['messages'][-1]['content']), [self.sample['content']])
                restored = copy.deepcopy(result)
                if arm == 'high':
                    self.assertEqual(restored['messages'][-1]['content'][1]['image_url'].pop('detail'), 'high')
                else:self.assertIs(result, payload)
                self.assertEqual(restored, original)
                request = emit.call_args.args[0]
                self.assertEqual(request['images'], [{'mime': 'image/png', 'width': 900, 'height': 1200,
                    'bytes': len(self.sample['content']), 'detail': arm, 'detail_explicit': arm == 'high'}])

    def test_copied_or_forged_context_cannot_inherit_scope(self):
        context = self.bind(self.context(), 'high')
        copied = copy.copy(context)
        self.assertIsNone(experiment.begin(copied, self.payload(copied))[1])
        context._vision_experiment = {'arm': 'high'}
        self.assertIsNone(experiment.begin(context, self.payload(context))[1])

    def test_no_silent_experiment_on_text_multiple_images_history_or_invalid_image(self):
        variants = [self.context(samples=[self.sample, image('red')]), self.context(), self.context(), self.context()]
        variants[1][-1]['content'] = 'Synthetic text-only request.'
        variants[2].insert(0, {'role': 'assistant', 'content': 'Synthetic earlier answer.'})
        variants[3][-1]['content'][1]['image_url']['url'] = 'data:image/png;base64,aW52YWxpZA=='
        with patch.object(experiment, '_emit') as emit:
            for context in variants:
                self.bind(context, 'high')
                payload = self.payload(context)
                result, diag = experiment.begin(context, payload)
                self.assertIs(result, payload);self.assertIsNone(diag)
        emit.assert_not_called()

    def test_logs_are_allowlisted_and_malicious_metadata_is_not_echoed(self):
        context = self.bind(self.context(), 'high')
        with self.assertLogs('kilas_ai.vision_experiment', level='INFO') as captured:
            _, diag = experiment.begin(context, self.payload(context))
            response = MagicMock(status_code=200, headers={'x-request-id': 'req_synthetic_123'})
            diag.response(response);diag.model('gpt-6-luna-2026-10-01')
            diag.tokens({'prompt_tokens': 123, 'completion_tokens': 45,
                         'prompt_tokens_details': {'cached_tokens': 10, 'cache_write_tokens': 5}, 'private': 'FORBIDDEN'})
            diag.delta();diag.finish('stop');diag.end()
        records = [json.loads(line.split('kilas_vision_eval ', 1)[1]) for line in captured.output]
        self.assertEqual(len(records), 2)
        self.assertEqual(set(records[0]), {'event','run','arm','requested_model','image_count','images','reasoning_effort','max_completion_tokens'})
        self.assertEqual(set(records[1]), {'event','run','arm','requested_model','returned_model','provider_request_id',
            'http_status','finish_reason','status','duration_ms','ttft_ms','usage'})
        self.assertEqual(records[0]['run'], records[1]['run'])
        self.assertEqual(records[1]['usage'], {'input_tokens':123,'output_tokens':45,'cached_input_tokens':10,'cache_write_input_tokens':5})
        self.assertGreaterEqual(records[1]['duration_ms'], records[1]['ttft_ms'])
        text = '\n'.join(captured.output)
        for forbidden in ('Synthetic object question.', 'Synthetic system.', self.sample['filename'],
                          'data:image', 'base64', 'FORBIDDEN', 'Authorization', 'user_id', 'thread_id', 'http://'):
            self.assertNotIn(forbidden, text)
        with patch.object(experiment, '_emit') as emit:
            diag.response(MagicMock(status_code=400, headers={'x-request-id':'secret\nbody'}))
            diag.request_id = 'unreported'
            diag.model('secret-model');diag.tokens({'prompt_tokens': 'secret', 'completion_tokens': True})
            diag.finish('secret-finish');diag.end()
            record = emit.call_args.args[0]
            self.assertNotIn('secret', json.dumps(record))
            self.assertIsNone(record['usage']['input_tokens'])

    def test_native_http_experiment_and_normal_users_make_one_call_with_unchanged_accounting(self):
        # A fresh first turn is required; remove only disposable fixture rows.
        import db
        db.execute('DELETE FROM kilas_ai_attachments WHERE thread_id=?', (self.thread,))
        db.execute('DELETE FROM kilas_ai_messages WHERE thread_id=?', (self.thread,))
        reply = MagicMock(status_code=200, headers={'x-request-id':'req_mocked_123'})
        reply.__enter__.return_value = reply
        events = [{'model':experiment.MODEL,'choices':[{'delta':{'content':'Synthetic private answer.'},'finish_reason':'stop'}],
                   'usage':{'prompt_tokens':100,'completion_tokens':30}}]
        with patch.dict(os.environ, {experiment.FLAG:json.dumps({str(self.thread):'high'}), 'OPENAI_API_KEY':'synthetic-only'}), \
             patch.object(selected_provider.requests, 'post', return_value=reply) as post, \
             patch.object(providers, '_events', side_effect=lambda r:iter(events)), \
             self.assertLogs('kilas_ai.vision_experiment', level='INFO') as logs:
            result = self.submit(agent=False, text='Identify this object.', vision_detail='original',
                attachments=[(io.BytesIO(self.sample['content']),self.sample['filename'])])
        self.assertEqual(result.status_code, 200);self.assertEqual(post.call_count, 1)
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['model'], experiment.MODEL)
        self.assertEqual(payload['reasoning_effort'], 'medium')
        self.assertEqual(payload['max_completion_tokens'], 8192)
        self.assertEqual(payload['messages'][-1]['content'][1]['image_url']['detail'], 'high')
        self.assertEqual(image_bytes(payload['messages'][-1]['content']), [self.sample['content']])
        self.assertEqual(len(logs.output), 2)
        self.assertNotIn('Synthetic private answer.', '\n'.join(logs.output))
        # Scope is not inherited by later turns or by arbitrary posted knobs.
        with patch.dict(os.environ, {experiment.FLAG:json.dumps({str(self.thread):'high'}), 'OPENAI_API_KEY':'synthetic-only'}), \
             patch.object(selected_provider.requests, 'post', return_value=reply) as post, \
             patch.object(providers, '_events', side_effect=lambda r:iter(events)), patch.object(experiment, '_emit') as emit:
            result = self.submit(agent=False, text='Identify another object.', vision_detail='high',
                attachments=[(io.BytesIO(self.sample['content']),self.sample['filename'])])
        self.assertEqual(result.status_code, 200);self.assertEqual(post.call_count, 1)
        self.assertNotIn('detail', post.call_args.kwargs['json']['messages'][-1]['content'][1]['image_url'])
        emit.assert_not_called()

    def test_provider_error_is_not_retried_or_logged_as_raw_body(self):
        context = self.bind(self.context(), 'high')
        response = MagicMock(status_code=400, headers={'x-request-id':'req_error_123'})
        response.__enter__.return_value = response
        import requests
        response.raise_for_status.side_effect = requests.HTTPError('FORBIDDEN PRIVATE BODY')
        with patch.dict(os.environ, {'OPENAI_API_KEY':'synthetic-only'}), \
             patch.object(selected_provider.requests, 'post', return_value=response) as post, \
             self.assertLogs('kilas_ai.vision_experiment', level='INFO') as logs:
            with self.assertRaises(providers.ProviderError):list(selected_provider.stream('SMART', context))
        self.assertEqual(post.call_count, 1)
        self.assertNotIn('FORBIDDEN', '\n'.join(logs.output))
        self.assertIn('"status":"incomplete"', '\n'.join(logs.output))

    def test_existing_create_endpoint_returns_an_empty_owned_thread_without_inference(self):
        with patch.object(selected_provider.requests, 'post', side_effect=AssertionError('No inference for creation')) as post:
            response = self.client().post('/kilas-ai/threads', json={'first_message':'Visual QA setup'},
                headers={'X-CSRF-Token':'work-csrf'})
        self.assertEqual(response.status_code, 201)
        ident = response.json['thread_id']
        self.assertIsNotNone(store.thread(self.owner, ident))
        self.assertEqual(store.messages(self.owner, ident), [])
        self.assertIsNone(store.thread(self.other, ident))
        post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
