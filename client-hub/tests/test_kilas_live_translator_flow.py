"""Real Flask admission/input/output flow, synthetic suppliers, disposable ledger.

This verifies application control flow and accounting, not audible phone quality.
Run through scripts/run_offline_tests.py so every real network call is blocked.
"""
import base64
import io
import json
import math
import os
import time
import unittest
from contextlib import ExitStack
from queue import Queue
from threading import Event
from unittest.mock import MagicMock, patch

import test_kilas_audio as audio
import test_kilas_live_translator as fixture
from kilas_ai import audio_branded_voices as branded, audio_store, providers
from kilas_ai import audio_transcription_budget as batch
from kilas_ai import free_test, live_translator as live
from kilas_ai import live_translator_realtime as realtime
from kilas_ai import live_translator_realtime_budget as realtime_budget
from kilas_ai import live_translator_realtime_check as proof
from kilas_ai import live_translator_segments as segments
from kilas_ai import live_translator_store as sessions
from kilas_ai import live_translator_transport as transport


class SyntheticSocket:
    """One stable final acknowledgment, with controllable delivery and no IO."""
    def __init__(self, text):
        self.text = text
        self.queue = Queue()
        self.queue.put(json.dumps({
            'message_type': 'session_started',
            'config': {'model_id': 'scribe_v2_realtime',
                       'audio_format': 'pcm_16000', 'sample_rate': 16000},
        }))
        self.sent = []
        self.committed = Event()
        self.closed = Event()
        self.acknowledgments = 0

    def settimeout(self, seconds):
        self.timeout = seconds

    def recv(self):
        value = self.queue.get(timeout=3)
        if value is None:
            raise OSError('Synthetic socket closed')
        return value

    def send(self, message):
        value = json.loads(message)
        self.sent.append(base64.b64decode(value['audio_base_64']))
        if value['commit']:
            self.committed.set()
        else:
            self.queue.put(json.dumps({
                'message_type': 'partial_transcript',
                'text': 'Unstable prefix must never be translated',
            }))

    def acknowledge(self):
        self.acknowledgments += 1
        self.queue.put(json.dumps({
            'message_type': 'committed_transcript', 'text': self.text,
        }))

    def shutdown(self):
        self.closed.set()
        self.queue.put(None)


class ApplicationFlowTests(unittest.TestCase):
    setUp = fixture.LiveTranslatorTests.setUp
    funded = fixture.LiveTranslatorTests.funded
    on = fixture.LiveTranslatorTests.on
    credit = fixture.LiveTranslatorTests.credit
    key = fixture.LiveTranslatorTests.key
    signal = fixture.LiveTranslatorTests.signal
    transcribe = fixture.LiveTranslatorTests.transcribe

    @classmethod
    def setUpClass(cls):
        cls.raw = audio.mp3(1.4)

    def context(self, translated='Hello. Hello. Complete final sentence.', *, realtime_on=False,
                provider_languages=('id', 'en')):
        stack = ExitStack()
        stack.enter_context(self.funded())
        stack.enter_context(self.on())
        stack.enter_context(patch.dict(os.environ, {
            'KILAS_VO_STT_ALLOWED_OWNER_ID': str(self.user),
            'KILAS_VO_STT_USAGE_MODE': 'owner',
            'KILAS_LIVE_TRANSLATOR_USAGE_MODE': 'owner',
            'KILAS_APP_FREE_TEST_ENABLED': 'false',
        }))
        stack.enter_context(patch.object(branded, 'resolve', return_value=fixture.VOICE))
        stack.enter_context(patch.object(branded, 'public_choices', return_value=[fixture.VOICE]))
        stack.enter_context(patch.object(realtime.account, 'verified', return_value=realtime_on))

        def translate(*args, **kwargs):
            yield {'type': 'delta', 'text': json.dumps({
                'text': translated, 'source_language': provider_languages[0],
                'target_language': provider_languages[1],
            })}
            yield {'type': 'usage', 'input_tokens': 20, 'output_tokens': 18}
            yield {'type': 'finish', 'reason': 'stop'}

        self.translation_mock = stack.enter_context(patch.object(providers, '_openai', side_effect=translate))
        self.batch_mock = stack.enter_context(patch.object(live.stt, 'transcribe', side_effect=self.transcribe))
        return stack

    def start(self, expected_mode='batch'):
        response = self.client.post('/kilas-translator/live/sessions', data={
            'csrf_token': 'audio-csrf', 'consent': 'yes',
            'language_a': 'id', 'language_b': 'en', 'voice': 'kilas-male',
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json['input_mode'], expected_mode)
        self.assertRegex(response.json['session_id'], r'^[a-f0-9]{48}$')
        ident = response.json['session_id']
        self.addCleanup(realtime.cancel, self.user, ident)
        self.addCleanup(sessions.end, self.user, ident)
        return ident

    def path(self, ident, key=None):
        return '/kilas-translator/live/sessions/' + ident + '/turns/' + (key or self.key())

    def post_batch(self, ident, key=None):
        return self.client.post(self.path(ident, key), data={
            'csrf_token': 'audio-csrf', 'stream_output': 'sentences-v1',
            'recording': (io.BytesIO(self.signal()), 'synthetic.wav', 'audio/wav'),
        })

    def wait(self, predicate, message, seconds=3):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.005)
        self.fail(message)

    def output_transport(self, release=None, received=None):
        response = MagicMock(status_code=200)
        response.__enter__.return_value = response

        def chunks(size):
            yield self.raw[:80]
            if received:
                received.set()
            if release and not release.wait(3):
                raise AssertionError('Synthetic output tail was not released')
            yield self.raw[80:]

        response.iter_content.side_effect = chunks
        return response

    def assert_processing_private(self, ident):
        self.assertEqual(self.client.get(self.path(ident)).json, {'status': 'PROCESSING'})
        self.assertEqual(self.client.get(self.path(ident) + '/audio').status_code, 404)
        self.assertEqual(self.client.get(self.path(ident) + '/audio/segments/0').status_code, 404)

    def assert_complete(self, ident, text, request):
        self.wait(lambda: sessions.result(self.user, ident, self.key())['status'] != 'PROCESSING',
                  'Synthetic pipeline did not settle')
        metadata = self.client.get(self.path(ident))
        self.assertEqual(metadata.status_code, 200)
        self.assertEqual(metadata.headers['Cache-Control'], 'private, no-store')
        self.assertEqual(metadata.json['status'], 'COMPLETED', metadata.json)
        self.assertEqual(metadata.json['translated_text'], text)
        self.assertNotIn('segments', metadata.json)
        self.assertNotIn('stream_output', metadata.json)
        output = self.client.get(metadata.json['audio_url'])
        self.assertEqual(output.status_code, 200)
        self.assertEqual(output.data, self.raw)
        self.assertEqual(output.mimetype, 'audio/mpeg')
        self.assertEqual(output.headers['Cache-Control'], 'private, no-store')
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs['json']['text'], text)
        self.assertEqual(request.call_args.kwargs['json']['model_id'], 'eleven_multilingual_v2')
        self.assertIn('/text-to-speech/' + fixture.VOICE['id'] + '/stream', request.call_args.args[1])
        row = audio.f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE user_id=?', (self.user,))
        self.assertEqual(row['status'], 'COMPLETED')
        self.assertIsNone(row['original_script'])
        self.assertIsNone(row['result_content'])
        self.assertGreater(row['seconds_charged'], 0)
        self.assertEqual(row['seconds_charged'], math.ceil(row['actual_ms'] / 1000))
        self.assertEqual(audio_store.balance(self.user)['seconds'], 300 - row['seconds_charged'])

    def start_realtime(self, ident):
        response = self.client.post(self.path(ident) + '/input/start', data={
            'csrf_token': 'audio-csrf', 'text': 'Client injection must never reach translation',
        })
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json, {'status': 'LISTENING', 'input_mode': 'realtime-v1'})
        relay = realtime.owned(self.user, ident, self.key())
        def stop():
            realtime.cancel(self.user, ident)
            sessions.end(self.user, ident)
            self.wait(lambda: relay.finished, 'Synthetic relay did not stop')
        self.addCleanup(stop)
        return relay

    def send_pcm(self, ident):
        raw = b'\x01\x00' * 16000
        response = self.client.post(self.path(ident) + '/input/chunks/0', data={
            'csrf_token': 'audio-csrf',
            'pcm': (io.BytesIO(raw), 'synthetic.pcm', 'application/octet-stream'),
        })
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json, {'accepted_index': 0})
        response = self.client.post(self.path(ident) + '/input/commit', data={
            'csrf_token': 'audio-csrf', 'count': '1',
        })
        self.assertEqual(response.status_code, 202, response.text)
        return raw

    def test_batch_routes_buffer_full_audio_once_and_keep_tenant_end_and_duplicate_guards(self):
        received, release = Event(), Event()
        self.addCleanup(release.set)
        text = 'Hello. Hello. Complete final sentence.'
        with self.context(text), patch.object(segments.transport, 'request',
                return_value=self.output_transport(release, received)) as request:
            self.credit(300)
            ident = self.start()
            html = self.client.get('/kilas-translator/live').text
            self.assertIn('data-ready="true"', html)
            self.assertIn('name="voice"', html)
            self.assertEqual(self.post_batch(ident).status_code, 202)
            self.assertTrue(received.wait(3))
            self.assert_processing_private(ident)
            self.assertEqual(self.post_batch(ident).status_code, 409)
            request.assert_called_once()
            self.batch_mock.assert_called_once()
            self.translation_mock.assert_called_once()
            release.set()
            self.assert_complete(ident, text, request)
            before = dict(audio.f.db.query_one('SELECT * FROM kilas_audio_balances WHERE user_id=?', (self.user,)))
            from auth_test_helpers import authenticate
            authenticate(self.client,__import__('repo').get_user_by_id(self.other),_csrf_token='audio-csrf')
            self.assertEqual(self.client.get(self.path(ident)).status_code, 404)
            self.assertEqual(self.client.get(self.path(ident) + '/audio').status_code, 404)
            self.assertEqual(self.client.post('/kilas-translator/live/sessions/' + ident + '/end',
                data={'csrf_token': 'audio-csrf'}).status_code, 404)
            from auth_test_helpers import authenticate
            authenticate(self.client,__import__('repo').get_user_by_id(self.user),_csrf_token='audio-csrf')
            self.assertEqual(self.post_batch(ident).status_code, 409)
            self.assertEqual(self.client.post('/kilas-translator/live/sessions/' + ident + '/end').status_code, 400)
            self.assertEqual(self.client.post('/kilas-translator/live/sessions/' + ident + '/end',
                data={'csrf_token': 'audio-csrf'}).status_code, 200)
            self.assertEqual(self.client.get(self.path(ident) + '/audio').status_code, 404)
            self.assertEqual(before, dict(audio.f.db.query_one('SELECT * FROM kilas_audio_balances WHERE user_id=?', (self.user,))))
            request.assert_called_once()

    def test_realtime_routes_wait_stable_ack_then_use_one_whole_tts_without_batch_replay(self):
        stable = 'Halo. Halo. Kalimat terakhir lengkap.'
        text = 'Hello. Hello. Complete final sentence.'
        socket = SyntheticSocket(stable)
        received, release = Event(), Event()
        self.addCleanup(release.set)
        with self.context(text, realtime_on=True), patch.object(realtime, 'connect', return_value=socket) as connect, \
                patch.object(segments.transport, 'request', return_value=self.output_transport(release, received)) as request:
            self.credit(300)
            ident = self.start('realtime-v1')
            relay = self.start_realtime(ident)
            raw = self.send_pcm(ident)
            self.assertTrue(socket.committed.wait(3))
            self.assert_processing_private(ident)
            self.translation_mock.assert_not_called()
            self.batch_mock.assert_not_called()
            self.assertEqual(self.client.post(self.path(ident) + '/input/start',
                data={'csrf_token': 'audio-csrf'}).status_code, 409)
            self.assertEqual(self.post_batch(ident).status_code, 409)
            connect.assert_called_once()
            socket.acknowledge()
            self.assertTrue(received.wait(3))
            self.assert_processing_private(ident)
            self.assertEqual(self.translation_mock.call_args.args[2][0]['content'], stable)
            self.batch_mock.assert_not_called()
            release.set()
            self.assert_complete(ident, text, request)
            self.wait(lambda: relay.finished, 'Realtime flow did not finish')
            self.assertEqual(b''.join(socket.sent), raw)
            self.assertEqual(socket.acknowledgments, 1)
            self.assertTrue(socket.closed.is_set())
            row = audio.f.db.query_one('SELECT status,charge_micro FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key=?',
                (self.user, realtime_budget.ledger_key(self.key())))
            self.assertEqual(row['status'], 'COMPLETED')
            self.assertEqual(row['charge_micro'], realtime_budget.RESERVE_MICRO)
            self.assertIsNone(batch.owned(self.user, self.key()))

    def test_end_realtime_before_final_ack_retains_dispatched_cost_and_blocks_translation_fallback(self):
        socket = SyntheticSocket('Stable result arriving too late.')
        with self.context(realtime_on=True), patch.object(realtime, 'connect', return_value=socket) as connect, \
                patch.object(segments.transport, 'request') as request:
            self.credit(300)
            ident = self.start('realtime-v1')
            relay = self.start_realtime(ident)
            self.send_pcm(ident)
            self.assertTrue(socket.committed.wait(3))
            response = self.client.post('/kilas-translator/live/sessions/' + ident + '/end',
                data={'csrf_token': 'audio-csrf'})
            self.assertEqual(response.status_code, 200)
            socket.acknowledge()
            self.wait(lambda: relay.finished, 'End did not stop realtime worker')
            self.translation_mock.assert_not_called()
            self.batch_mock.assert_not_called()
            request.assert_not_called()
            connect.assert_called_once()
            self.assertEqual(self.client.get(self.path(ident) + '/audio').status_code, 404)
            self.assertEqual(self.client.get('/kilas-translator/live/sessions/active').json, {'session': None})
            row = audio.f.db.query_one('SELECT status,charge_micro FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key=?',
                (self.user, realtime_budget.ledger_key(self.key())))
            self.assertEqual(row['status'], 'UNKNOWN')
            self.assertEqual(row['charge_micro'], realtime_budget.RESERVE_MICRO)
            self.assertEqual(audio_store.balance(self.user)['seconds'], 300)

    def test_end_batch_during_output_tail_never_exposes_partial_audio_or_retries(self):
        received, release = Event(), Event()
        self.addCleanup(release.set)
        with self.context(), patch.object(segments.transport, 'request',
                return_value=self.output_transport(release, received)) as request:
            self.credit(300)
            ident = self.start()
            self.assertEqual(self.post_batch(ident).status_code, 202)
            self.assertTrue(received.wait(3))
            self.assert_processing_private(ident)
            self.assertEqual(self.client.post('/kilas-translator/live/sessions/' + ident + '/end',
                data={'csrf_token': 'audio-csrf'}).status_code, 200)
            release.set()
            self.wait(lambda: audio.f.db.query_one('SELECT status FROM kilas_audio_jobs WHERE user_id=?',
                (self.user,))['status'] == 'FAILED', 'Cancelled output tail did not settle')
            self.assertEqual(self.client.get(self.path(ident) + '/audio').status_code, 404)
            self.assertEqual(self.post_batch(ident).status_code, 409)
            self.assertEqual(sessions.result(self.user, ident, self.key()), {'status': 'CANCELLED'})
            request.assert_called_once()
            self.batch_mock.assert_called_once()
            self.translation_mock.assert_called_once()

    def test_fresh_pre_tts_credit_exhaustion_blocks_speech_without_cached_admission_credit(self):
        checks = []

        def credit():
            checks.append('fresh')
            if len(checks) == 2:
                raise batch.BudgetError('provider_credit_exhausted', 402)

        with self.context(), patch.object(live.stt, 'require_subscription_credit', side_effect=credit), \
                patch.object(segments.transport, 'request') as request:
            self.credit(300)
            ident = self.start()
            self.assertEqual(self.post_batch(ident).status_code, 202)
            self.wait(lambda: sessions.result(self.user, ident, self.key())['status'] != 'PROCESSING',
                      'Exhausted credit did not settle')
            result = self.client.get(self.path(ident)).json
            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual(result['code'], 'provider_credit_exhausted')
            self.assertFalse(result['recoverable'])
            self.assertEqual(checks, ['fresh', 'fresh'])
            self.batch_mock.assert_called_once()
            request.assert_not_called()
            self.assertEqual(self.client.get(self.path(ident) + '/audio').status_code, 404)
            self.assertEqual(audio_store.balance(self.user)['seconds'], 300)
            self.assertEqual(self.post_batch(ident).status_code, 409)

    def test_free_test_proof_revoked_during_stream_blocks_output_on_next_dynamic_fence(self):
        valid = [True]
        first_delta, release = Event(), Event()
        self.addCleanup(release.set)

        def translate(*args, **kwargs):
            yield {'type': 'delta', 'text': '{"text":"Full translated utterance.",'}
            first_delta.set()
            if not release.wait(3):
                raise AssertionError('Synthetic translation was not released')
            yield {'type': 'delta', 'text': '"source_language":"id","target_language":"en"}'}
            yield {'type': 'finish', 'reason': 'stop'}

        with self.context(), patch.dict(os.environ, {
                'KILAS_APP_FREE_TEST_ENABLED': 'true',
                'KILAS_APP_FREE_TEST_END_AT': free_test.END_AT.isoformat(),
            }), patch.object(proof, 'verified', side_effect=lambda: valid[0]), \
                patch.object(providers, '_openai', side_effect=translate) as translation, \
                patch.object(segments.transport, 'request') as request:
            self.credit(300)
            ident = self.start()
            self.assertEqual(self.post_batch(ident).status_code, 202)
            self.assertTrue(first_delta.wait(3))
            valid[0] = False
            release.set()
            self.wait(lambda: sessions.result(self.user, ident, self.key())['status'] != 'PROCESSING',
                      'Revoked proof did not settle')
            result = self.client.get(self.path(ident)).json
            self.assertEqual(result['status'], 'FAILED')
            # Preserve the actual lost-readiness fence instead of rewriting it
            # as a supplier translation failure. TTS must still be blocked.
            self.assertEqual(result['code'], 'translator_unavailable')
            translation.assert_called_once()
            request.assert_not_called()
            self.assertEqual(self.client.get(self.path(ident) + '/audio').status_code, 404)

    def test_actual_realtime_handoff_reuses_one_owned_https_session_with_two_fresh_credit_reads(self):
        socket = SyntheticSocket('Halo. Halo. Kalimat terakhir lengkap.')
        text = 'Hello. Hello. Complete final sentence.'
        supplier = MagicMock()
        credit = MagicMock(status_code=200)
        credit.json.side_effect = lambda: {
            'tier': 'creator', 'status': 'active', 'max_credit_limit_extension': 0,
            'allowed_to_extend_character_limit': False, 'can_extend_character_limit': False,
            'character_count': 10, 'character_limit': 1000,
        }
        supplier.get.return_value = credit
        supplier.request.return_value = self.output_transport()
        with self.context(text, realtime_on=True), patch.object(realtime, 'connect', return_value=socket), \
                patch.object(live.stt, 'require_subscription_credit', side_effect=self.subscription_credit_check), \
                patch.object(transport.requests, 'Session', return_value=supplier) as factory:
            self.credit(300)
            ident = self.start('realtime-v1')
            relay = self.start_realtime(ident)
            self.send_pcm(ident)
            self.assertTrue(socket.committed.wait(3))
            self.assertEqual(supplier.get.call_count, 1)
            supplier.request.assert_not_called()
            socket.acknowledge()
            self.assert_complete(ident, text, supplier.request)
            self.wait(lambda: relay.finished, 'Realtime HTTPS scope did not finish')
            self.wait(lambda: supplier.close.call_count == 1, 'Owned HTTPS client was not closed')
            factory.assert_called_once()
            self.assertEqual(supplier.get.call_count, 2)
            self.assertEqual(credit.json.call_count, 2, 'Each credit read must parse its own response')
            for call in supplier.get.call_args_list:
                self.assertEqual(call.args, ('https://api.elevenlabs.io/v1/user/subscription',))
                self.assertFalse(call.kwargs['allow_redirects'])
            supplier.close.assert_called_once()
            self.batch_mock.assert_not_called()
            self.assertIsNone(transport._turn_client.get(), 'The relay supplier client must not leak to Flask requests')

    def test_realtime_https_setup_failure_settles_turn_lease_and_releases_slot_before_dispatch(self):
        with self.context(realtime_on=True), patch.object(transport.requests, 'Session',
                side_effect=RuntimeError('Synthetic HTTPS client setup failure')), \
                patch.object(realtime, 'connect') as connect, patch.object(segments.transport, 'request') as request:
            self.credit(300)
            ident = self.start('realtime-v1')
            info = sessions.claim(self.user, ident, self.key())
            capability = realtime_budget.claim(self.user, ident, self.key())
            self.assertTrue(realtime._slots.acquire(blocking=False))
            relay = realtime.Relay(self.user, ident, self.key(), info, capability)
            try:
                relay.run()
            finally:
                # Keep this failure regression isolated when run against an
                # implementation that leaks before entering relay cleanup.
                if not relay.finished:
                    realtime_budget.finish(capability, False)
                    sessions.finish(self.user, ident, self.key(), False, code='realtime_failed')
                    realtime._slots.release()
            self.assertTrue(relay.finished)
            self.assertTrue(relay.closed.is_set())
            connect.assert_not_called()
            request.assert_not_called()
            self.translation_mock.assert_not_called()
            self.batch_mock.assert_not_called()
            self.assertEqual(sessions.result(self.user, ident, self.key())['status'], 'FAILED')
            row = audio.f.db.query_one('SELECT status,charge_micro FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key=?',
                (self.user, realtime_budget.ledger_key(self.key())))
            self.assertEqual(dict(row), {'status': 'CANCELLED', 'charge_micro': 0})


if __name__ == '__main__':
    unittest.main()
