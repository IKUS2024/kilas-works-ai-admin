"""Offline Copilot contracts: actual auth/CSRF/store/quota, mocked OpenAI only."""
import io
import json
import os
import sys
import tempfile
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


class CopilotTests(unittest.TestCase):
    def setUp(self):
        self.app = app.app
        self.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        self.owner = repo.create_user('copilot-'+uuid.uuid4().hex+'@example.test', 'hash')
        self.other = repo.create_user('copilot-other-'+uuid.uuid4().hex+'@example.test', 'hash')
        self.client = self.client_for(self.owner)
        self.ident = copilot.create(self.owner)
        self.key = uuid.uuid4().hex

    def client_for(self, owner):
        client = self.app.test_client()
        authenticate(client, repo.get_user_by_id(owner), _csrf_token='copilot-csrf')
        return client

    def premium(self):
        from datetime import timedelta
        now = usage._now()
        db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PRO','ACTIVE',?,?)",
                   (self.owner, now.isoformat(), (now+timedelta(days=30)).isoformat()))

    def post(self, operation_key=None, silent=False, consent='yes', **options):
        return self.client.post(f'/kilas-ai/copilot/sessions/{self.ident}/{operation_key or self.key}/process',
                                data={'audio': (io.BytesIO(recording(silent)), 'recording.wav', 'audio/wav'),
                                      'csrf_token': 'copilot-csrf', 'consent': consent, **options})

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
            self.assertIn('Audio diproses OpenAI setelah berhenti.', page.text)
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

    def test_disconnect_finalizes_without_storing_partial(self):
        self.premium()
        with patch.object(copilot, 'configured', return_value=True), patch.object(copilot, 'transcribe', return_value='hello'), patch.object(copilot, 'text_stream', side_effect=lambda *a: answer()):
            stream = copilot.process(self.owner, self.ident, self.key, recording(), False, 'santai', None)
            next(stream); next(stream); next(stream); stream.close()
        self.assertEqual(copilot.turns(self.owner, self.ident), [])
        self.assertEqual(json.loads(copilot.operation(self.owner, self.ident, self.key)['metadata_json'])['status'], 'failed')

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

    def test_heartbeat_disconnect_fences_blocked_provider_without_cancel_post(self):
        import threading
        self.premium()
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def stt(_):
            entered.set()
            release.wait(3)
            finished.set()
            return 'private voice'
        with patch.object(copilot, 'configured', return_value=True), patch.object(copilot, 'transcribe', side_effect=stt), patch.object(copilot, 'text_stream') as text:
            response = self.post()
            try:
                reader = iter(response.response)
                self.assertTrue(entered.wait(2))
                frames = [next(reader), next(reader), next(reader)]
                self.assertTrue(any(b'heartbeat' in frame if isinstance(frame, bytes) else 'heartbeat' in frame for frame in frames), repr(frames))
                response.close()
                self.assertFalse(copilot.active(self.owner, self.ident, self.key))
            finally:
                response.close();release.set();finished.wait(2)
            text.assert_not_called()
        self.assertEqual(copilot.turns(self.owner, self.ident), [])


if __name__ == '__main__':
    unittest.main()
