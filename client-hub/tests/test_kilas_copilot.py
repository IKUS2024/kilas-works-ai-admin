"""Offline Copilot contracts: actual auth/CSRF/store/quota, mocked OpenAI only."""
import io
import json
import os
import sys
import tempfile
import time
import unittest
import uuid
import wave
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['CLIENT_HUB_DB_PATH'] = tempfile.mktemp(prefix='kilas-copilot-', suffix='.sqlite')
os.environ['SECRET_KEY'] = 'copilot-disposable-fixture'
os.environ['KILAS_AI_ENABLED'] = 'true'
os.environ.pop('DATABASE_URL', None)
import app
import db
import repo
from auth_test_helpers import authenticate
from kilas_ai import copilot, store, usage, providers


def recording(silent=False, seconds=1):
    output = io.BytesIO()
    with wave.open(output, 'wb') as writer:
        writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(16000)
        writer.writeframes((b'\0\0' if silent else b'\x00\x20') * (16000 * seconds))
    return output.getvalue()


def answer(text='Could you clarify the timeline?'):
    yield {'type': 'delta', 'text': text[:8]}
    yield {'type': 'delta', 'text': text[8:]}
    yield {'type': 'usage', 'input_tokens': 100, 'output_tokens': 20}
    yield {'type': 'finish', 'reason': 'stop'}


def await_operation(client, response):
    if response.status_code != 202:return response
    url=response.json['status_url'];deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        result=client.get(url)
        if result.status_code!=200 or result.json['state']!='processing':return result
        time.sleep(.01)
    raise AssertionError('Synthetic operation did not finish')


class CopilotTests(unittest.TestCase):
    def setUp(self):
        self.app = app.app
        self.app.json.compact=False
        self.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        self.owner = repo.create_user('copilot-'+uuid.uuid4().hex+'@example.test', 'hash')
        self.other = repo.create_user('copilot-other-'+uuid.uuid4().hex+'@example.test', 'hash')
        self.client = self.client_for(self.owner)
        self.ident = copilot.create(self.owner)
        self.key = uuid.uuid4().hex

    def client_for(self, owner):
        client = self.app.test_client()
        client.set_cookie('kilas_language', 'id')
        authenticate(client, repo.get_user_by_id(owner), _csrf_token='copilot-csrf')
        return client

    def premium(self):
        from datetime import timedelta
        now = usage._now()
        db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PRO','ACTIVE',?,?)",
                   (self.owner, now.isoformat(), (now+timedelta(days=30)).isoformat()))

    def post(self, operation_key=None, silent=False, consent='yes', **options):
        response = self.client.post(f'/kilas-ai/copilot/sessions/{self.ident}/{operation_key or self.key}/process',
                                data={'audio': (io.BytesIO(recording(silent)), 'recording.wav', 'audio/wav'),
                                      'csrf_token': 'copilot-csrf', 'consent': consent, **options})
        return await_operation(self.client,response)

    def run_turn(self, translate=False):
        streams = [answer()]
        if translate:
            streams.append(answer(json.dumps({'source_translation': 'Kapan Anda bisa mulai?', 'reply_translation': 'Bisa jelaskan jadwalnya?'})))
        with patch.object(copilot, 'configured', return_value=True), patch.object(copilot, 'transcribe', return_value='When can you start?') as stt, patch.object(copilot, 'text_stream', side_effect=streams) as text:
            response = self.post(translate='yes' if translate else 'no', target='id')
            body = response.get_data(as_text=True)
        return response, body, stt, text

    def test_primary_idle_no_capture_and_reversible_legacy_entry(self):
        legacy = store.create_thread(self.owner)
        store.append_user_once(self.owner, legacy, 'Original historical bytes', 'SMART', 'old-history')
        before = store.messages(self.owner, legacy)
        for path in ('/kilas-ai', '/products/start', '/kilas-ai/copilot'):
            page = self.client.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertIn('id="copilot"', page.text)
            self.assertNotIn('id="ai-composer"', page.text)
            self.assertNotIn('AI Chat', page.text)
            self.assertNotIn(f'href="/kilas-ai/threads/{legacy}"', page.text)
            self.assertNotIn('<details class="kilas-profile-menu" open', page.text)
            self.assertIn('Mikrofon mati', page.text)
            self.assertNotIn('id="copilot-consent"', page.text)
            self.assertIn('id="copilot-trigger"', page.text)
            self.assertIn('Bahasa percakapan otomatis', page.text)
            self.assertNotIn('Powered by OpenAI', page.text)
            self.assertNotIn('copilot-help', page.text)
        self.assertIn('audio dikirim ke OpenAI untuk transkripsi', self.client.get('/privacy').text)
        self.assertIn('id="ai-composer"', self.client.get('/kilas-ai?legacy=1').text)
        self.assertIn('Original historical bytes', self.client.get(f'/kilas-ai/threads/{legacy}').text)
        self.assertEqual(store.messages(self.owner, legacy), before)
        self.assertNotIn(legacy, [row['id'] for row in self.client.get('/kilas-ai/sidebar/history').json['items']])
        with patch.dict(os.environ, {'KILAS_COPILOT_VISIBLE': 'false'}):
            self.assertIn('id="ai-composer"', self.client.get('/kilas-ai').text)

    def test_new_session_owner_csrf_rename_delete_and_legacy_integrity(self):
        self.assertEqual(self.client.post('/kilas-ai/copilot/sessions').status_code, 400)
        self.assertEqual(self.client_for(self.other).get(f'/kilas-ai/copilot/sessions/{self.ident}').status_code, 404)
        created = self.client.post('/kilas-ai/copilot/sessions', data={'csrf_token': 'copilot-csrf'})
        self.assertEqual(created.status_code, 201)
        ident = created.json['id']
        self.assertEqual(self.client.post(f'/kilas-ai/threads/{ident}/rename', data={'title': 'Interview', 'csrf_token': 'copilot-csrf'}).status_code, 303)
        self.assertEqual(store.thread(self.owner, ident)['title'], 'Interview')
        self.assertEqual(self.client_for(self.other).post(f'/kilas-ai/threads/{ident}/delete', data={'csrf_token': 'copilot-csrf'}).status_code, 404)
        self.assertEqual(self.client.post(f'/kilas-ai/threads/{ident}/delete', data={'csrf_token': 'copilot-csrf'}).status_code, 303)
        self.assertIsNotNone(store.thread(self.owner, self.ident))

    def test_consent_validation_and_owner_denial_before_provider(self):
        with patch.object(copilot, 'transcribe') as called:
            self.assertEqual(self.post(consent='no').status_code, 400)
            self.assertEqual(self.post(style='expert').status_code, 400)
            self.assertEqual(self.post(translate='yes', target='made-up').status_code, 400)
            other = self.client_for(self.other)
            self.assertEqual(other.post(f'/kilas-ai/copilot/sessions/{self.ident}/{self.key}/process', data={'csrf_token': 'copilot-csrf'}).status_code, 404)
            called.assert_not_called()

    def test_silence_skips_paid_reservation_and_all_providers(self):
        with patch.object(copilot, 'configured', return_value=True), patch.object(copilot, 'transcribe') as stt, patch.object(usage, 'reserve') as reserve:
            self.assertIn('silence', self.post(silent=True).get_data(as_text=True))
            stt.assert_not_called(); reserve.assert_not_called()
        self.assertEqual(copilot.turns(self.owner, self.ident), [])

    def test_billing_denial_precedes_stt_and_no_flag_bypasses_it(self):
        with patch.object(copilot, 'configured', return_value=True), patch.object(copilot, 'transcribe') as stt, patch.object(usage, 'reserve', side_effect=usage.UsageLimit('denied')):
            self.assertIn('capacity_unavailable', self.post().get_data(as_text=True))
            stt.assert_not_called()

    def test_translation_off_one_reply_and_estimate_is_conservative(self):
        self.premium()
        _, body, stt, text = self.run_turn()
        self.assertIn('"type": "complete"', body)
        self.assertEqual((stt.call_count, text.call_count), (1, 1))
        turn = copilot.turns(self.owner, self.ident)[0]
        self.assertIsNone(turn['target'])
        self.assertNotIn('reply_translation', turn)
        self.assertEqual(turn['source'], 'When can you start?')
        self.assertEqual(store.messages(self.owner, self.ident)[0]['role'], 'assistant')
        ledger = db.query_one('SELECT * FROM kilas_ai_usage WHERE user_id=? AND operation_key=?', (self.owner, copilot.key(self.key)))
        self.assertEqual(ledger['status'], 'COMPLETE')
        self.assertEqual(float(ledger['estimated_cost_usd']), .18)

    def test_translation_on_keeps_primary_language_and_history(self):
        self.premium()
        _, body, stt, text = self.run_turn(translate=True)
        self.assertIn('"type": "complete"', body)
        self.assertEqual((stt.call_count, text.call_count), (1, 2))
        self.assertIn('latest intelligible spoken utterance', text.call_args_list[0].args[0])
        self.assertIn('NOT confirmed', text.call_args_list[0].args[0])
        turn = copilot.turns(self.owner, self.ident)[0]
        self.assertEqual(turn['reply'], 'Could you clarify the timeline?')
        self.assertEqual(turn['reply_translation'], 'Bisa jelaskan jadwalnya?')
        self.assertEqual(turn['target'], 'id')
        self.assertIn('id="copilot"', self.client.get(f'/kilas-ai/threads/{self.ident}').text)

    def test_context_labels_suggestions_as_unconfirmed(self):
        self.premium(); self.run_turn()
        self.key = uuid.uuid4().hex
        _, _, _, text = self.run_turn()
        payload = json.loads(text.call_args_list[0].args[1])
        self.assertEqual(payload['previous_turns'][0]['heard'], 'When can you start?')
        self.assertIn('ai_suggestion_not_user_statement', payload['previous_turns'][0])

    def test_duplicate_operation_never_retries_paid_work(self):
        self.premium(); self.run_turn()
        with patch.object(copilot, 'configured', return_value=True), patch.object(copilot, 'transcribe') as stt:
            self.assertIn('operation_already_submitted', self.post().get_data(as_text=True))
            stt.assert_not_called()
        self.assertEqual(len(copilot.turns(self.owner, self.ident)), 1)
        self.key = uuid.uuid4().hex
        copilot.claim(self.owner, self.ident, self.key, 'in-flight')
        with patch.object(copilot, 'configured', return_value=True), patch.object(copilot, 'transcribe') as stt:
            self.assertIn('operation_already_submitted', self.post().get_data(as_text=True))
            stt.assert_not_called()
        self.assertTrue(copilot.active(self.owner, self.ident, self.key))
        copilot.cancel(self.owner, self.ident, self.key)

    def test_cancel_before_post_is_persisted_tombstone(self):
        path = f'/kilas-ai/copilot/sessions/{self.ident}/{self.key}/cancel'
        self.assertEqual(self.client.post(path, data={'csrf_token': 'copilot-csrf'}).status_code, 200)
        with patch.object(copilot, 'configured', return_value=True), patch.object(copilot, 'transcribe') as stt:
            self.assertIn('operation_already_submitted', self.post().get_data(as_text=True))
            stt.assert_not_called()

    def test_cancel_after_stt_never_generates_reply_or_saves_transcript(self):
        self.premium()
        def stt(_):
            copilot.cancel(self.owner, self.ident, self.key)
            return 'private spoken bytes'
        with patch.object(copilot, 'configured', return_value=True), patch.object(copilot, 'transcribe', side_effect=stt), patch.object(copilot, 'text_stream') as text:
            self.assertIn('cancelled', self.post().get_data(as_text=True)); text.assert_not_called()
        self.assertEqual(copilot.turns(self.owner, self.ident), [])
        self.assertNotIn('private spoken bytes', str(store.messages(self.owner, self.ident)))
        row = db.query_one('SELECT status,estimated_cost_usd FROM kilas_ai_usage WHERE user_id=? AND operation_key=?', (self.owner, copilot.key(self.key)))
        self.assertEqual(row['status'], 'FAILED'); self.assertEqual(float(row['estimated_cost_usd']), .18)

    def test_interrupted_stream_never_saved_and_new_explicit_operation_can_proceed(self):
        self.premium()
        with patch.object(copilot, 'configured', return_value=True), patch.object(copilot, 'transcribe', return_value='hello'), patch.object(copilot, 'text_stream', return_value=iter([{'type': 'delta', 'text': 'partial'}])):
            self.assertIn('incomplete_stream', self.post().get_data(as_text=True))
        self.assertEqual(copilot.turns(self.owner, self.ident), [])
        self.key = uuid.uuid4().hex
        self.assertIn('"type": "complete"', self.run_turn()[1])

    def test_generator_close_finalizes_without_storing_partial(self):
        self.premium()
        with patch.object(copilot,'configured',return_value=True),patch.object(copilot,'transcribe',return_value='hello'),patch.object(copilot,'text_stream',side_effect=lambda *a:answer()):
            stream=copilot.process(self.owner,self.ident,self.key,recording(),False,'santai',None)
            next(stream);next(stream);next(stream);stream.close()
        self.assertEqual(copilot.turns(self.owner,self.ident),[])
        self.assertEqual(json.loads(copilot.operation(self.owner,self.ident,self.key)['metadata_json'])['status'],'failed')

    def test_invalid_and_oversized_wav_is_rejected_before_billing(self):
        from werkzeug.datastructures import FileStorage
        for raw in (b'not wav', recording(seconds=61)):
            with self.assertRaises(copilot.CopilotError):
                copilot.audio(FileStorage(stream=io.BytesIO(raw), filename='a.wav', content_type='audio/wav'))

    def test_fixed_luna_provider_contract_no_expensive_fallback(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-only'}), patch.object(providers, '_openai', return_value=iter(())) as called:
            list(copilot.text_stream('system', 'content'))
        self.assertEqual(called.call_args.args[0], 'gpt-6-luna')
        self.assertEqual(called.call_args.kwargs['profile'], {'output_tokens': 1024, 'effort': 'low'})
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-only'}), patch.object(providers, '_openai', return_value=iter(())) as called:
            list(copilot.text_stream('Return JSON', '{}', json_mode=True))
        self.assertEqual(called.call_args.kwargs['response_format'], {'type':'json_object'})

    def test_copilot_history_pagination_hides_legacy_without_mutating_rows(self):
        expected = []
        for index in range(23):
            ident = copilot.create(self.owner)
            op = uuid.uuid4().hex
            copilot.claim(self.owner, ident, op, 'synthetic')
            copilot.update(self.owner, ident, op, 'complete', 'AI suggestion', source='Heard speech', target=None, style='santai')
            expected.append(ident)
        cursor = None; ids = []
        while True:
            response = self.client.get('/kilas-ai/sidebar/history', query_string={'cursor': cursor} if cursor else {})
            self.assertEqual(response.status_code, 200)
            ids.extend(row['id'] for row in response.json['items'])
            cursor = response.json['next_cursor']
            if not cursor: break
        self.assertEqual(set(ids), set(expected)); self.assertEqual(len(ids), len(expected))
        first = self.client.get('/kilas-ai/sidebar/history').json['next_cursor']
        self.assertEqual(self.client_for(self.other).get('/kilas-ai/sidebar/history', query_string={'cursor':first}).status_code, 400)

    def test_pending_turn_blocks_second_key_and_stale_turn_does_not_block_forever(self):
        copilot.claim(self.owner, self.ident, self.key, 'first')
        with self.assertRaisesRegex(copilot.CopilotError, 'operation_busy'):
            copilot.claim(self.owner, self.ident, uuid.uuid4().hex, 'second')
        with patch.object(copilot.time, 'time', return_value=__import__('time').time()+241):
            self.assertFalse(copilot.active(self.owner, self.ident, self.key))
            copilot.claim(self.owner, self.ident, uuid.uuid4().hex, 'explicit-new-attempt')

    def test_dispatch_estimate_is_durable_before_provider_even_if_worker_dies(self):
        self.premium()
        def stt(_):
            row = db.query_one('SELECT status,estimated_cost_usd FROM kilas_ai_usage WHERE user_id=? AND operation_key=?', (self.owner, copilot.key(self.key)))
            self.assertEqual(row['status'], 'FAILED')
            self.assertEqual(float(row['estimated_cost_usd']), .18)
            raise copilot.CopilotError('transcription_failed')
        with patch.object(copilot, 'configured', return_value=True), patch.object(copilot, 'transcribe', side_effect=stt):
            self.assertIn('transcription_failed', self.post().get_data(as_text=True))

    def test_owner_concurrency_remains_bounded_after_durable_dispatch(self):
        for _ in range(3):
            ident = copilot.create(self.owner)
            copilot.claim(self.owner, ident, uuid.uuid4().hex, 'active')
        with self.assertRaisesRegex(copilot.CopilotError, 'operation_busy'):
            copilot.claim(self.owner, self.ident, self.key, 'fourth')

    def test_short_poll_and_cancel_work_while_stt_is_blocked(self):
        import threading
        self.premium();entered=threading.Event();release=threading.Event();finished=threading.Event()
        def stt(_):entered.set();release.wait(4);finished.set();return 'private voice'
        with patch.object(copilot,'configured',return_value=True),patch.object(copilot,'transcribe',side_effect=stt),patch.object(copilot,'text_stream') as text:
            response=self.client.post(f'/kilas-ai/copilot/sessions/{self.ident}/{self.key}/process',data={'audio':(io.BytesIO(recording()),'recording.wav','audio/wav'),'csrf_token':'copilot-csrf','consent':'yes'})
            self.assertEqual(response.status_code,202);self.assertTrue(entered.wait(2))
            started=time.monotonic();state=self.client.get(response.json['status_url'])
            self.assertEqual(state.json['state'],'processing');self.assertLess(time.monotonic()-started,.5)
            stopped=self.client.post(f'/kilas-ai/copilot/sessions/{self.ident}/{self.key}/cancel',data={'csrf_token':'copilot-csrf'})
            self.assertEqual(stopped.status_code,200);self.assertFalse(copilot.active(self.owner,self.ident,self.key))
            release.set();self.assertTrue(finished.wait(2));await_operation(self.client,response)
            text.assert_not_called()
        self.assertEqual(copilot.turns(self.owner,self.ident),[])

    def test_quiet_and_sparse_audio_not_rejected_as_silence(self):
        from werkzeug.datastructures import FileStorage
        import struct
        def clip(values):
            output = io.BytesIO()
            with wave.open(output, 'wb') as writer:
                writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(16000)
                writer.writeframes(struct.pack('<' + 'h' * len(values), *values))
            return FileStorage(stream=io.BytesIO(output.getvalue()), filename='quiet.wav', content_type='audio/wav')
        self.assertFalse(copilot.audio(clip([80]*16000))[1])
        self.assertFalse(copilot.audio(clip([0]*160000+[1000]*640+[0]*160000))[1])
        self.assertTrue(copilot.audio(clip([0]*16000))[1])
        self.assertTrue(copilot.audio(clip([5]*16000))[1])

    def test_context_utf8_budget_preserves_latest_recent_tail_and_marks_clipping(self):
        history = [{'source': str(i)+'界'*4000, 'reply': '😀'*4000} for i in range(12)]
        latest = 'あ'*4000
        content = copilot.reply_context(latest, history)
        self.assertLessEqual(len(content.encode('utf-8')), 24000)
        parsed = json.loads(content)
        self.assertEqual(parsed['latest_spoken_utterance'], latest)
        self.assertTrue(parsed['previous_turns'][-1]['heard'].startswith('11'))
        self.assertTrue(parsed['previous_turns'][-1]['heard_truncated'])
        self.assertTrue(parsed['previous_turns'][-1]['ai_suggestion_not_user_statement_truncated'])
        self.assertEqual(copilot.reply_context('OK', []), json.dumps({'previous_turns': [], 'latest_spoken_utterance': 'OK'}))

    def test_quality_prompt_contract_and_review_fixtures_not_model_evaluation(self):
        from pathlib import Path
        cases = json.loads(Path(__file__).with_name('copilot_quality_cases.json').read_text())
        self.assertGreaterEqual(len(cases), 15)
        for case in cases:
            self.assertNotEqual(case['good'], case['bad'])
            self.assertTrue(case['rubric'])
            if case.get('personal_template'):
                self.assertTrue('isi sendiri' in case['good'] or 'fill in yourself' in case['good'])
                self.assertRegex(case['good'], r'^(Saya|I\b|My\b)')
                for refusal in ('Saya belum punya informasi', 'I do not have information', 'As Kilas Works'):
                    self.assertNotIn(refusal, case['good'])
            if case.get('no_slots'):
                self.assertNotIn('isi sendiri', case['good'])
        for rule in ('Kilas Works', 'Answer the actual question directly', 'NOT confirmed',
                     'HUMAN listener’s FIRST-PERSON answer', 'Ask one focused clarification only',
                     'mixed language', 'short ambiguous utterance', 'OpenAI', 'Preserve legitimate mentions of ChatGPT',
                     'plain spoken text', 'Santai means', 'profesional means'):
            self.assertIn(rule, copilot.SYSTEM)
        for rule in ('No rigid sentence count', 'ONLY the unknown facts', 'isi sendiri', 'fill in yourself', 'Do not respond with assistant-meta refusals', 'not merely because a personal fact is missing'):
            self.assertIn(rule, copilot.SYSTEM)
        self.assertNotIn('Normally use one natural sentence', copilot.SYSTEM)
        self.assertNotIn('Do not put bracket templates', copilot.SYSTEM)
        import hashlib
        self.assertEqual(Path(__file__).parents[1].joinpath('static/kilas_copilot_policy.sha256').read_text().strip(), hashlib.sha256(copilot.SYSTEM.encode()).hexdigest())

    def test_multilingual_pipeline_preserves_source_and_reply_not_accuracy_evaluation(self):
        self.premium()
        pairs = [('Terima kasih.', 'Sama-sama.'), ('Thank you.', "You're welcome."),
                 ('Gracias.', 'De nada.'), ('ありがとう。', 'どういたしまして。'),
                 ('شكراً', 'على الرحب والسعة'), ('谢谢。', '不客气。'), ('धन्यवाद।', 'आपका स्वागत है।'),
                 ('Could you jelasin?', 'Bagian mana yang ingin dijelaskan?')]
        for source, expected in pairs:
            with self.subTest(source=source), patch.object(copilot, 'configured', return_value=True), patch.object(copilot, 'transcribe', return_value=source), patch.object(copilot, 'text_stream', return_value=answer('  '+expected+'  ')) as text:
                response = self.post(operation_key=uuid.uuid4().hex)
                self.assertIn('complete', response.get_data(as_text=True))
                content = json.loads(text.call_args.args[1])
                self.assertEqual(content['latest_spoken_utterance'], source)
                self.assertEqual(copilot.turns(self.owner, self.ident)[-1]['reply'], expected)

    def test_punctuation_only_transcript_requests_repeat_without_reply(self):
        self.premium()
        with patch.object(copilot, 'configured', return_value=True), patch.object(copilot, 'transcribe', return_value='... ؟!'), patch.object(copilot, 'text_stream') as text:
            self.assertIn('unclear_audio', self.post().get_data(as_text=True))
            text.assert_not_called()

    def test_transcription_contract_auto_language_json_and_malformed_body(self):
        from unittest.mock import MagicMock
        for body, expected in [(b'{"text":"Hello"}', 'Hello'), ('{"text":"شكراً"}'.encode(), 'شكراً'), (b'[]', None), (b'{"text":42}', None)]:
            response = MagicMock()
            response.status_code = 200
            response.iter_content.return_value = [body]
            response.__enter__.return_value = response
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-not-a-key'}), patch.object(copilot.requests, 'post', return_value=response) as post:
                if expected is None:
                    with self.assertRaisesRegex(copilot.CopilotError, 'transcription_failed'):
                        copilot.transcribe(b'fixture')
                else:
                    self.assertEqual(copilot.transcribe(b'fixture'), expected)
                self.assertEqual(post.call_args.kwargs['data'], {'model': 'gpt-4o-mini-transcribe', 'response_format': 'json'})
                self.assertFalse(post.call_args.kwargs['allow_redirects'])

    def test_sidebar_absent_only_on_audio_tools_and_history_remains(self):
        for path in ('/kilas-translator', '/kilas-translator?mode=voiceover', '/kilas-translator/live?classic=1', '/kilas-translator/live'):
            page = self.client.get(path)
            if page.status_code in (302, 303):
                page = self.client.get(page.headers['Location'])
            self.assertEqual(page.status_code, 200, path)
            self.assertNotIn('id="premium-sidebar"', page.text)
            self.assertNotIn('data-premium-menu', page.text)
            self.assertIn('kilas-tool-header', page.text)
        voice = self.client.get('/kilas-translator?mode=voiceover').text
        self.assertIn('id="audio-history"', voice)
        self.assertIn('aria-controls="audio-history"', voice)
        copilot_page = self.client.get('/kilas-ai').text
        self.assertIn('id="premium-sidebar"', copilot_page)
        self.assertIn('Jasa Kreatif', copilot_page)
        self.assertIn('Finance', copilot_page)

    def test_enabled_audio_routes_remain_enabled_without_provider_generation(self):
        from kilas_ai import audio_provider, audio_branded_voices, live_translator, live_gemini, translator_languages
        # Real disposable balance, unchanged route/entitlement checks. Read-only
        # render with provider capabilities mocked; forbid generation entirely.
        db.execute('INSERT INTO kilas_audio_balances(user_id,seconds) VALUES (?,?)', (self.owner, 60))
        voices = [{'alias': 'kilas-male', 'name': 'Kilas Male', 'style': 'Natural'}]
        with patch.object(audio_provider, 'configured', return_value=True), patch.object(audio_provider, 'request', side_effect=AssertionError('Provider generation forbidden')), patch.object(audio_branded_voices, 'public_choices', return_value=voices), patch.object(live_translator, 'ready', return_value=True), patch.object(live_gemini, 'ready', return_value=False), patch.object(translator_languages, 'classic_names', return_value={'id': 'Bahasa Indonesia', 'en': 'English'}):
            voice = self.client.get('/kilas-translator?mode=voiceover')
            self.assertEqual(voice.status_code, 200)
            self.assertRegex(voice.text, r'id="voice-generate"[^>]*data-enabled="true"')
            self.assertNotIn('class="audio-notice"', voice.text)
            self.assertIn('id="audio-history"', voice.text)
            live = self.client.get('/kilas-translator/live?classic=1')
            self.assertEqual(live.status_code, 200)
            self.assertIn('data-ready="true"', live.text)
            self.assertIn('data-enabled="true"', live.text)
            self.assertNotIn('id="premium-sidebar"', live.text)
        from kilas_ai import audio_store
        self.assertEqual(audio_store.balance(self.owner)['seconds'], 60)

    def test_human_template_pipeline_translation_preserves_slots_and_context(self):
        from pathlib import Path
        cases = {c['id']: c for c in json.loads(Path(__file__).with_name('copilot_quality_cases.json').read_text())}
        self.premium()
        for case_id in ('school-id-unknown', 'education-en-unknown', 'experience-en-unknown', 'experience-id-known', 'school-experience-id-multipart', 'mixed-personal-template', 'general-no-personal-unknown', 'school-id-known'):
            case = cases[case_id]
            ident = copilot.create(self.owner)
            for heard in case.get('previous_heard', []):
                op = uuid.uuid4().hex
                copilot.claim(self.owner, ident, op, 'synthetic-context')
                copilot.update(self.owner, ident, op, 'complete', 'Unconfirmed AI suggestion, not a user fact.', source=heard, target=None, style='santai')
            translations = {
                'education-en-unknown': ('Anda belajar di mana, dan mengambil jurusan apa?', 'Saya bersekolah di … (isi sendiri), dengan jurusan … (isi sendiri).'),
                'experience-en-unknown': ('Ceritakan pengalaman kerja Anda yang paling relevan.', 'Pengalaman saya yang paling relevan adalah … (isi sendiri). Dalam peran itu, tanggung jawab saya mencakup … (isi sendiri). Salah satu contoh pekerjaan saya adalah … (isi sendiri), dengan hasil … (isi sendiri).'),
            }
            source_translation, translated = translations.get(case_id, (case['heard'], case['good']))
            streams = [answer(case['good']), answer(json.dumps({'source_translation': source_translation, 'reply_translation': translated}, ensure_ascii=False))]
            with self.subTest(case=case_id), patch.object(copilot, 'configured', return_value=True), patch.object(copilot, 'transcribe', return_value=case['heard']), patch.object(copilot, 'text_stream', side_effect=streams) as text:
                events = list(copilot.process(self.owner, ident, uuid.uuid4().hex, recording(), False, 'profesional', 'id'))
            self.assertEqual(events[-1]['type'], 'complete')
            saved = copilot.turns(self.owner, ident)[-1]
            self.assertEqual(saved['reply'], case['good'])
            self.assertEqual(saved['reply_translation'], translated)
            self.assertEqual(saved['source_translation'], source_translation)
            self.assertEqual(saved['reply'].count('isi sendiri') + saved['reply'].count('fill in yourself'), translated.count('isi sendiri'))
            self.assertEqual(saved['style'], 'profesional')
            prompt, content = text.call_args_list[0].args
            self.assertIn('HUMAN listener’s FIRST-PERSON answer', prompt)
            context = json.loads(content)
            self.assertEqual([t['heard'] for t in context['previous_turns']], case.get('previous_heard', []))
            self.assertEqual(context['latest_spoken_utterance'], case['heard'])
            translation_prompt, payload = text.call_args_list[1].args
            self.assertIn('Preserve every fill-yourself slot', translation_prompt)
            self.assertIn('without filling, deleting or inventing', translation_prompt)
            self.assertEqual(json.loads(payload)['reply'], case['good'])
            if case.get('personal_template'):
                self.assertIn('isi sendiri', translated) if case['language'] != 'English' else self.assertTrue('fill in yourself' in saved['reply'])
            if case_id == 'school-experience-id-multipart':
                self.assertGreater(saved['reply'].count('.'), 3)  # No sentence truncation.

    def test_translation_rejects_dropped_or_added_template_slots_without_rewrite(self):
        self.premium()
        reply = 'I studied at … (fill in yourself).'
        for translated in ('Saya sekolah di Harvard.', 'Saya sekolah di … (isi sendiri), jurusan … (isi sendiri).'):
            with self.subTest(translated=translated), patch.object(copilot, 'configured', return_value=True), patch.object(copilot, 'transcribe', return_value='Where did you study?'), patch.object(copilot, 'text_stream', side_effect=[answer(reply), answer(json.dumps({'source_translation': 'Sekolah di mana?', 'reply_translation': translated}))]):
                events = list(copilot.process(self.owner, self.ident, uuid.uuid4().hex, recording(), False, 'santai', 'id'))
            self.assertEqual(events[-1]['type'], 'complete')
            self.assertEqual(events[-1]['turn']['translation_error'], 'incomplete_translation')
            self.assertEqual(events[-1]['turn']['reply'], reply)
            self.assertEqual(copilot.turns(self.owner, self.ident)[0]['reply'], reply)
        self.assertEqual(copilot.slot_count('I studied at ... (fill in yourself).'), 1)
        self.assertEqual(copilot.slot_count('学校は…（自分で記入）です。'), 1)
        self.assertEqual(copilot.slot_count('An ordinary pause… with no slot.'), 0)


if __name__ == '__main__':
    unittest.main()
