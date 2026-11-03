"""Owned diagnostic scope and exact transport invariants; synthetic/mocked only."""
import copy
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import uuid
from pathlib import Path
from types import SimpleNamespace
from contextlib import ExitStack, redirect_stdout
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
        now = datetime.now(timezone.utc)
        self.config = {'owner_id':self.owner, 'batch':uuid.uuid4().hex, 'question':'Synthetic object question.',
            'starts_at':(now-timedelta(seconds=20)).isoformat().replace('+00:00','Z'),
            'expires_at':(now+timedelta(minutes=20)).isoformat().replace('+00:00','Z')}
        self.first = self.add_first(self.thread)

    def add_first(self, thread, question=None):
        ident, _ = store.append_user_once(self.owner, thread, question or self.config['question'], 'SMART', 'eval_'+uuid.uuid4().hex)
        store.save_attachments(self.owner, thread, ident, [self.sample])
        return ident

    def new_case(self, question=None):
        thread = store.create_thread(self.owner)
        self.add_first(thread, question)
        return thread

    def context(self, model=experiment.MODEL, samples=None):
        blocks = attachments.prompt_content(self.config['question'], samples or [self.sample])
        return chat_models.bind(model_policy.ChatContext([{'role': 'user', 'content': blocks}]), model)

    def bind(self, context, arm=None, user=None, path=None, thread=None):
        import db
        user = self.owner if user is None else user
        thread = self.thread if thread is None else thread
        if arm == 'high' and not db.query_one('SELECT sequence FROM kilas_ai_vision_eval_claims WHERE user_id=?', (self.owner,)):
            self.bind(self.context(), thread=self.new_case())  # A real first claim precedes the high arm.
        path = path or f'/kilas-ai/threads/{thread}/send'
        with patch.dict(os.environ, {experiment.FLAG:json.dumps(self.config)}), self.client().application.test_request_context(path, method='POST'):
            session['user_id'] = user
            experiment.bind(context, user, thread)
        return context

    def payload(self, context):
        return {'model': experiment.MODEL, 'messages': [{'role': 'system', 'content': 'Synthetic system.'}]+list(context),
                'reasoning_effort': 'medium', 'max_completion_tokens': 8192, 'store': False,
                'stream': True, 'stream_options': {'include_usage': True}}

    def test_default_off_has_no_scope_queries_or_payload_changes(self):
        context = self.context();payload = self.payload(context)
        with patch('kilas_ai.usage._connect', side_effect=AssertionError('No extra query when OFF')), \
             patch.object(experiment, '_emit') as emit:
            experiment.bind(context, self.owner, self.thread)
            result, diag = experiment.begin(context, payload)
        self.assertIs(result, payload);self.assertIsNone(diag);emit.assert_not_called()

    def test_malformed_configuration_is_completely_inactive(self):
        bad = ['', '{}', '[]', 'null', 'true', '{', ' '*2049, '{"owner_id":1,"owner_id":2}']
        for key, value in (('owner_id', True), ('owner_id', 0), ('owner_id', '1'), ('owner_id', 2**63),
                ('batch','invalid'), ('question',''), ('question',' x '), ('question','x\ny'),
                ('starts_at','invalid'), ('expires_at',self.config['starts_at'])):
            bad.append(json.dumps({**self.config,key:value}))
        bad.append(json.dumps({**self.config,'unknown':'high'}))
        now = datetime.now(timezone.utc)
        for start, end in ((now-timedelta(hours=1), now+timedelta(minutes=1)),
                           (now+timedelta(minutes=1),now+timedelta(minutes=2)),
                           (now-timedelta(minutes=2),now-timedelta(minutes=1))):
            bad.append(json.dumps({**self.config,'starts_at':start.isoformat().replace('+00:00','Z'),
                'expires_at':end.isoformat().replace('+00:00','Z')}))
        for raw in bad:
            with self.subTest(raw=raw[:40]), patch.dict(os.environ, {experiment.FLAG:raw}):
                self.assertEqual(experiment.configured(), {})
        with patch.dict(os.environ, {experiment.FLAG:json.dumps(self.config)}):
            self.assertEqual(experiment.configured()['owner_id'], self.owner)

    def test_foreign_owner_wrong_route_session_or_model_cannot_bind(self):
        for user, path, model in ((self.other, None, experiment.MODEL),
                (self.owner, '/kilas-ai/agent/chat', experiment.MODEL),
                (self.owner, f'/kilas-ai/threads/{self.thread}/voice-script', experiment.MODEL),
                (self.owner, None, 'gpt-6.1-sol')):
            with self.subTest(user=user, path=path, model=model):
                context = self.bind(self.context(model), user=user, path=path)
                self.assertFalse(hasattr(context, '_vision_experiment'))
        context = self.context()
        with patch.dict(os.environ, {experiment.FLAG: json.dumps(self.config)}), \
             self.client().application.test_request_context(f'/kilas-ai/threads/{self.thread}/send', method='POST'):
            experiment.bind(context, self.owner, self.thread)  # No authenticated session.
        self.assertFalse(hasattr(context, '_vision_experiment'))

    def test_second_turn_is_not_an_experiment(self):
        store.append_user_once(self.owner, self.thread, 'Synthetic follow-up.', 'SMART', 'eval_second_synthetic')
        self.assertFalse(hasattr(self.bind(self.context(), 'high'), '_vision_experiment'))

    def test_configured_scope_is_not_bound_outside_http_or_in_another_thread(self):
        context = self.context()
        with patch.dict(os.environ, {experiment.FLAG:json.dumps(self.config)}):
            experiment.bind(context, self.owner, self.thread)
        self.assertFalse(hasattr(context, '_vision_experiment'))
        context = self.bind(self.context(), 'high', path=f'/kilas-ai/threads/{self.thread+1}/send')
        self.assertFalse(hasattr(context, '_vision_experiment'))

    def test_http_ownership_auth_and_csrf_are_not_widened_by_configuration(self):
        url = f'/kilas-ai/threads/{self.thread}/send'
        data = {'content':'Synthetic question.', 'operation_key':'eval_unauthorized_synthetic',
                'csrf_token':'work-csrf', 'vision_detail':'high'}
        with patch.dict(os.environ, {experiment.FLAG:json.dumps(self.config)}), \
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
                if arm == 'high':self.thread = self.new_case()
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
        captured = io.StringIO()
        with redirect_stdout(captured):
            _, diag = experiment.begin(context, self.payload(context))
            response = MagicMock(status_code=200, headers={'x-request-id': 'req_synthetic_123'})
            diag.response(response);diag.model('gpt-6-luna-2026-10-01')
            diag.tokens({'prompt_tokens': 123, 'completion_tokens': 45,
                         'prompt_tokens_details': {'cached_tokens': 10, 'cache_write_tokens': 5}, 'private': 'FORBIDDEN'})
            diag.delta();diag.finish('stop');diag.end()
        records = [json.loads(line.split('kilas_vision_eval ', 1)[1]) for line in captured.getvalue().splitlines()]
        self.assertEqual(len(records), 2)
        self.assertEqual(set(records[0]), {'event','run','arm','sequence','requested_model','image_count','images','reasoning_effort','max_completion_tokens'})
        self.assertEqual(set(records[1]), {'event','run','arm','sequence','requested_model','returned_model','provider_request_id',
            'http_status','finish_reason','status','duration_ms','ttft_ms','usage'})
        self.assertEqual(records[0]['run'], records[1]['run'])
        self.assertEqual(records[1]['usage'], {'input_tokens':123,'output_tokens':45,'cached_input_tokens':10,'cache_write_input_tokens':5})
        self.assertGreaterEqual(records[1]['duration_ms'], records[1]['ttft_ms'])
        text = captured.getvalue()
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
        self.config['question'] = 'Identify this object.'
        reply = MagicMock(status_code=200, headers={'x-request-id':'req_mocked_123'})
        reply.__enter__.return_value = reply
        events = [{'model':experiment.MODEL,'choices':[{'delta':{'content':'Synthetic private answer.'},'finish_reason':'stop'}],
                   'usage':{'prompt_tokens':100,'completion_tokens':30}}]
        logs = io.StringIO()
        with patch.dict(os.environ, {experiment.FLAG:json.dumps(self.config), 'OPENAI_API_KEY':'synthetic-only'}), \
             patch.object(selected_provider.requests, 'post', return_value=reply) as post, \
             patch.object(providers, '_events', side_effect=lambda r, **kwargs:iter(events)), \
             redirect_stdout(logs):
            result = self.submit(agent=False, text='Identify this object.', vision_detail='original',key='eval_http_retry_synthetic',
                attachments=[(io.BytesIO(self.sample['content']),self.sample['filename'])])
        self.assertEqual(result.status_code, 200);self.assertEqual(post.call_count, 1)
        self.assertIn('event: done',result.get_data(as_text=True))
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['model'], experiment.MODEL)
        self.assertEqual(payload['reasoning_effort'], 'medium')
        self.assertEqual(payload['max_completion_tokens'], 8192)
        self.assertNotIn('detail', payload['messages'][-1]['content'][1]['image_url'])
        self.assertEqual(image_bytes(payload['messages'][-1]['content']), [self.sample['content']])
        self.assertEqual(len([line for line in logs.getvalue().splitlines() if line.startswith('kilas_vision_eval ')]), 2)
        self.assertNotIn('Synthetic private answer.', logs.getvalue())
        with patch.dict(os.environ, {experiment.FLAG:json.dumps(self.config)}), \
             patch.object(selected_provider.requests,'post',side_effect=AssertionError('No duplicate inference')) as duplicate, \
             patch.object(experiment,'_emit') as emit:
            retried=self.submit(agent=False,text='Identify this object.',vision_detail='original',key='eval_http_retry_synthetic',
                attachments=[(io.BytesIO(self.sample['content']),self.sample['filename'])])
        self.assertEqual(retried.status_code,200,retried.get_json(silent=True));duplicate.assert_not_called();emit.assert_not_called()
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_ai_vision_eval_claims WHERE user_id=? AND batch=?',
                                     (self.owner,self.config['batch']))['n'],1)
        self.thread = store.create_thread(self.owner)
        with patch.dict(os.environ, {experiment.FLAG:json.dumps(self.config), 'OPENAI_API_KEY':'synthetic-only'}), \
             patch.object(selected_provider.requests, 'post', return_value=reply) as second, \
             patch.object(providers, '_events', side_effect=lambda r, **kwargs:iter(events)), patch.object(experiment, '_emit'):
            result = self.submit(agent=False, text=self.config['question'],
                attachments=[(io.BytesIO(self.sample['content']),self.sample['filename'])])
        self.assertEqual(result.status_code, 200);self.assertEqual(second.call_count, 1)
        high_payload = copy.deepcopy(second.call_args.kwargs['json'])
        self.assertEqual(high_payload['messages'][-1]['content'][1]['image_url'].pop('detail'), 'high')
        self.assertEqual(high_payload, payload)
        # Scope is not inherited by later turns or by arbitrary posted knobs.
        with patch.dict(os.environ, {experiment.FLAG:json.dumps(self.config), 'OPENAI_API_KEY':'synthetic-only'}), \
             patch.object(selected_provider.requests, 'post', return_value=reply) as post, \
             patch.object(providers, '_events', side_effect=lambda r, **kwargs:iter(events)), patch.object(experiment, '_emit') as emit:
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
        logs = io.StringIO()
        with patch.dict(os.environ, {'OPENAI_API_KEY':'synthetic-only'}), \
             patch.object(selected_provider.requests, 'post', return_value=response) as post, \
             redirect_stdout(logs):
            with self.assertRaises(providers.ProviderError):list(selected_provider.stream('SMART', context))
        self.assertEqual(post.call_count, 1)
        self.assertNotIn('FORBIDDEN', logs.getvalue())
        self.assertIn('"status":"incomplete"', logs.getvalue())

    def test_emitter_flushes_metadata_and_a_broken_sink_does_not_interrupt_chat(self):
        record={'event':'request','image_count':1}
        with patch('builtins.print') as emit:
            experiment._emit(record)
        self.assertEqual(emit.call_args.kwargs,{'flush':True})
        self.assertEqual(json.loads(emit.call_args.args[0].split(' ',1)[1]),record)
        with patch('builtins.print',side_effect=BrokenPipeError('synthetic broken output')):
            experiment._emit(record)

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

    def test_eight_slots_are_atomic_idempotent_and_not_replenished_by_chat_deletion(self):
        import db
        threads = [self.thread]+[self.new_case() for _ in range(11)]
        contexts = [self.context() for _ in threads]
        with ThreadPoolExecutor(6) as pool:
            list(pool.map(lambda pair:self.bind(pair[1],thread=pair[0]), zip(threads,contexts)))
        grants = [getattr(context, '_vision_experiment', None) for context in contexts]
        accepted = [grant for grant in grants if grant]
        self.assertEqual(sorted(g.sequence for g in accepted), list(range(1,9)))
        self.assertEqual([g.arm for g in sorted(accepted,key=lambda g:g.sequence)], ['auto','high']*4)
        rows = db.query_all('SELECT thread_id,sequence FROM kilas_ai_vision_eval_claims WHERE user_id=?', (self.owner,))
        chosen = rows[0]
        again = self.bind(self.context(),thread=chosen['thread_id'])
        self.assertEqual(again._vision_experiment.sequence,chosen['sequence'])
        self.assertEqual(len(db.query_all('SELECT sequence FROM kilas_ai_vision_eval_claims WHERE user_id=?',(self.owner,))),8)
        store.delete_thread(self.owner, chosen['thread_id'])
        self.assertFalse(hasattr(self.bind(self.context(),thread=self.new_case()), '_vision_experiment'))
        self.assertEqual(len(db.query_all('SELECT sequence FROM kilas_ai_vision_eval_claims WHERE user_id=?',(self.owner,))),8)

    def test_wrong_question_old_thread_and_changed_batch_configuration_are_inactive(self):
        import db
        context = self.context();context[0]['content'][0]['text']='Unrelated ordinary activity.'
        self.assertFalse(hasattr(self.bind(context), '_vision_experiment'))
        db.execute('UPDATE kilas_ai_threads SET created_at=? WHERE id=?',('2001-01-01 00:00:00',self.thread))
        self.assertFalse(hasattr(self.bind(self.context()), '_vision_experiment'))
        self.thread = self.new_case()
        first = self.bind(self.context())
        self.assertEqual(first._vision_experiment.sequence,1)
        self.config['question']='Different synthetic question.'
        self.thread = self.new_case()
        self.assertFalse(hasattr(self.bind(self.context()), '_vision_experiment'))

    def test_expiry_and_disabled_configuration_cannot_admit_new_claims(self):
        context = self.context()
        end = datetime.fromisoformat(self.config['expires_at'])
        with patch.object(experiment, '_now', return_value=end):
            self.assertFalse(hasattr(self.bind(context), '_vision_experiment'))
        first = self.bind(self.context())
        with patch.object(experiment, '_emit'), patch.object(experiment, '_now',return_value=end):
            # An already admitted in-flight attempt retains its accepted variant.
            self.assertIsNotNone(experiment.begin(first,self.payload(first))[1])
        self.assertFalse(hasattr(self.context(), '_vision_experiment'))

    def test_a_batch_identity_cannot_be_reassigned_to_a_different_owner(self):
        self.assertEqual(self.bind(self.context())._vision_experiment.sequence,1)
        self.config['owner_id'] = self.other
        foreign = store.create_thread(self.other)
        store.append_user_once(self.other,foreign,self.config['question'],'SMART','different_owner_'+uuid.uuid4().hex)
        context = self.bind(self.context(),user=self.other,thread=foreign)
        self.assertFalse(hasattr(context, '_vision_experiment'))

    def test_storage_failure_does_not_enable_override_or_leak_exception(self):
        with patch.object(experiment, '_claim', side_effect=RuntimeError('PRIVATE-FAILURE-CONTENT')), \
             self.assertLogs('kilas_ai.vision_experiment',level='WARNING') as logs:
            context = self.bind(self.context())
        self.assertFalse(hasattr(context, '_vision_experiment'))
        self.assertIn('kilas_vision_eval_scope_storage_unavailable','\n'.join(logs.output))
        self.assertNotIn('PRIVATE-FAILURE-CONTENT','\n'.join(logs.output))

    def test_sqlite_migration_repeats_without_changing_existing_data(self):
        import db
        before = [dict(row) for row in store.messages(self.owner,self.thread)]
        script = (Path(__file__).resolve().parents[1]/'migrations/0114_kilas_vision_eval_sqlite.sql').read_text()
        with db.get_connection() as conn:
            conn.executescript(script);conn.executescript(script)
            columns = [row[1] for row in conn.execute('PRAGMA table_info(kilas_ai_vision_eval_claims)')]
        self.assertEqual(columns,['user_id','batch','sequence','thread_id','message_id','config_fingerprint'])
        self.assertEqual([dict(row) for row in store.messages(self.owner,self.thread)],before)

    def test_normal_blueprint_startup_applies_narrow_schema_without_broad_migrations(self):
        from kilas_ai.routes import ai_bp
        prepare_chat_models = next(callback for callback in ai_bp.deferred_functions if callback.__name__=='prepare_chat_models')
        with ExitStack() as stack:
            stack.enter_context(patch('db.init_schema',side_effect=AssertionError('No broad boot migration')))
            release=stack.enter_context(patch('kilas_ai.chat_models_schema.apply_release'))
            for target in ('kilas_ai.workspace_execution_proof.maybe_start','kilas_ai.workspace_execution_access.log_readiness',
                           'kilas_ai.workspace_large_proof.maybe_start','kilas_ai.workspace_document_runtime.maybe_start'):
                stack.enter_context(patch(target))
            with patch.dict(os.environ,{'KILAS_AI_ENABLED':'true',experiment.FLAG:'','RUN_MIGRATIONS_ON_BOOT':'false'}):
                prepare_chat_models(SimpleNamespace(first_registration=True,app=SimpleNamespace(testing=True)))
            names=[args.args[0] if args.args else '0102_kilas_chat_models' for args in release.call_args_list]
            self.assertEqual(names,['0102_kilas_chat_models','0103_kilas_image_models','0105_kilas_workspace_streams',
                '0106_kilas_workspace_execution','0111_kilas_chat_recovery','0112_kilas_chat_hardening',
                '0113_kilas_chat_sponsorship','0114_kilas_vision_eval'])
            release.reset_mock()
            with patch.dict(os.environ,{'KILAS_AI_ENABLED':'false'}):
                prepare_chat_models(SimpleNamespace(first_registration=True,app=SimpleNamespace(testing=True)))
            release.assert_not_called()


if __name__ == '__main__':
    unittest.main()
