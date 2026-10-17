"""Synthetic public lookup boundaries and lifecycle; no paid/network/DB IO."""
import json
import os
from pathlib import Path
import sys
from threading import Event, Lock, RLock
from time import monotonic, sleep
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kilas_ai import ai_call_public_search as search, ai_call as calls


class Call:
    def __init__(self):
        self.owner = 1; self.ident = 'a'*32
        self.closed = Event(); self.renewing = Event()
        self.lock = RLock(); self.send_lock = Lock()
        self.frames = []; self.messages = []; self.checks = 0
        self.ws = Mock(send=lambda raw: self.messages.append(json.loads(raw)))
    def check(self): self.checks += 1
    def transport_check(self):
        if self.closed.is_set(): raise RuntimeError('ended')
    def publish(self, frame): self.frames.append(frame)
    def stop(self, code): self.closed.set()


class PublicSearchTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-not-a-key',
            'KILAS_AI_OPENAI_WEB_MODEL': 'offline-model', 'KILAS_AI_CALL_PUBLIC_SEARCH_ENABLED': 'true'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.call = Call(); self.search = search.PublicSearch(self.call)
        self.addCleanup(self.search.cancel)
        self.reserve = patch.object(search.usage, 'reserve', return_value=('PLUS', ('WEB_SEARCH',))).start()
        self.finish = patch.object(search.usage, 'finish').start()
        self.discard = patch.object(search.db, '_discard_cached_connection').start()
        self.addCleanup(patch.stopall)
        self.result = {'text': 'Synthetic source-backed finding.', 'citations': [
            {'url': 'https://example.org/news', 'title': 'Synthetic public source'}],
            'model': 'offline-model', 'usage': {'input_tokens': 20, 'output_tokens': 15}}
        self.lookups = []
        def lookup(context, **kwargs):
            self.lookups.append((context, kwargs)); yield {'result': self.result}
        self.lookup = patch.object(search.tools, 'web_search_steps', side_effect=lookup).start()

    def handle(self, ident='one', args=None):
        return self.search.handle({'functionCalls': [{'id': ident, 'name': search.NAME,
            'args': {'country': 'ID', 'topic': 'general'} if args is None else args}]})

    def wait(self):
        deadline = monotonic()+3
        while self.search.job is not None and monotonic() < deadline: sleep(.005)
        self.assertIsNone(self.search.job, 'worker did not finish')

    def response(self): return self.call.messages[-1]['toolResponse']['functionResponses'][0]['response']

    def test_setup_declares_only_narrow_tool_when_existing_config_present(self):
        value = calls.setup()['setup']
        self.assertEqual(value['tools'], [search.declaration()])
        self.assertIn('source organizations', value['systemInstruction']['parts'][0]['text'])
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            self.assertNotIn('tools', calls.setup()['setup'])
            self.assertIn('No external lookup', calls.setup()['setup']['systemInstruction']['parts'][0]['text'])

    def test_full_request_uses_only_server_public_constants_never_transcript(self):
        private = 'PRIVATE HISTORY SENTINEL: private account 723836. '
        self.search.observe(private+'Gimana keadaan Indonesia sekarang?', finished=True)
        self.assertTrue(self.handle()); self.wait()
        context, kwargs = self.lookups[0]
        self.assertEqual(len(context), 1)
        self.assertNotIn(private, str(context))
        self.assertNotIn('723836', str(context))
        self.assertNotIn('Gimana', str(context))
        self.assertIn('Indonesia', context[0]['content'])
        self.assertEqual(kwargs['max_calls'], 1)
        self.assertTrue(kwargs['minimal_query'])
        self.assertEqual(kwargs['request_timeout'], 8)
        self.reserve.assert_called_once()
        self.assertEqual(self.reserve.call_args.args[2][:9], 'call-web-')
        self.assertTrue(self.response()['available'])
        self.assertEqual(self.call.frames[0]['citations'][0]['url'], 'https://example.org/news')
        self.finish.assert_called_once()
        self.assertTrue(self.finish.call_args.kwargs['success'])
        self.assertEqual(self.call.checks, 1)
        self.search.turn_complete(); self.assertEqual(self.search.buffer, '')

    def test_tool_before_final_transcript_waits_without_charging_partial_speech(self):
        self.search.observe('Gimana keadaan Indonesia sekarang?', finished=False)
        self.handle(); sleep(.025)
        self.reserve.assert_not_called()
        self.search.observe('', finished=True)
        self.wait(); self.reserve.assert_called_once()

    def test_split_no_search_optout_prevents_lookup_and_no_speech_is_not_a_request(self):
        self.search.observe('Gimana keadaan Indonesia sekarang? Jangan ')
        self.search.observe('cari di internet.', finished=True)
        # Force only the intent wait's deadline; no provider/deadline sleeps.
        with patch.object(search, 'monotonic', side_effect=[0, 0, 0, 3]):
            # Direct execution is deterministic here; handle's Timer is not needed.
            job = {'id': 'denied', 'args': {'country': 'ID', 'topic': 'general'},
                   'deadline': 20, 'cancelled': Event(), 'replied': False, 'timer': Mock()}
            self.search._execute(job)
        self.reserve.assert_not_called(); self.lookup.assert_not_called()
        self.assertFalse(self.response()['available'])
        for text in ('', 'S', 'Saya punya tiga apel. Berapa jumlahnya?', 'How are you?', 'Indonesia'):
            self.assertIsNone(search.public_intent(text))

    def test_unknown_and_arbitrary_query_rejected_without_search(self):
        self.assertFalse(self.search.handle({'functionCalls': [{'id': 'x', 'name': 'read_private_chat'}]}))
        self.handle(args={'country': 'ID', 'topic': 'general', 'query': 'PRIVATE USER DATA'})
        self.wait(); self.reserve.assert_not_called(); self.lookup.assert_not_called()
        self.assertFalse(self.response()['available'])

    def test_duplicate_and_same_spoken_turn_cannot_pay_twice(self):
        self.search.observe('Gimana keadaan Indonesia sekarang?', finished=True)
        self.handle(); self.wait(); self.handle(); self.wait()
        self.reserve.assert_called_once(); self.lookup.assert_called_once()
        self.assertEqual(len(self.call.messages), 1)
        # Same recognized utterance cannot authorize another new function ID.
        job = {'id': 'again', 'args': {'country': 'ID', 'topic': 'general'}, 'deadline': 20,
               'cancelled': Event(), 'replied': False, 'timer': Mock()}
        with patch.object(search, 'monotonic', side_effect=[0, 0, 3]): self.search._execute(job)
        self.reserve.assert_called_once()

    def test_quota_provider_timeout_and_missing_sources_fail_explicitly(self):
        self.search.observe('Ada berita terbaru di Indonesia?', finished=True)
        self.reserve.side_effect = search.usage.UsageLimit('offline limit')
        self.handle(); self.wait(); self.lookup.assert_not_called()
        self.finish.assert_not_called(); self.assertFalse(self.response()['available'])
        self.reserve.side_effect = None
        self.search.observe('Ada berita terbaru di Indonesia?', finished=True)
        self.lookup.side_effect = search.tools.ToolUnavailable('offline', model='offline-model',
            usage={'input_tokens': 10}, code='provider_timeout')
        self.handle('timeout'); self.wait()
        self.assertFalse(self.response()['current_verified'])
        self.assertFalse(self.finish.call_args.kwargs['success'])
        self.assertEqual(self.finish.call_args.kwargs['usage']['input_tokens'], 10)
        self.search.observe('Ada berita terbaru di Indonesia?', finished=True)
        self.lookup.side_effect = lambda *a, **k: iter([{'result': {**self.result, 'citations': []}}])
        self.handle('uncited'); self.wait()
        self.assertFalse(self.response()['available'])
        self.assertFalse(self.finish.call_args.kwargs['success'])

    def test_end_during_search_keeps_pcm_lock_free_drops_late_reply_and_settles_work(self):
        entered, release = Event(), Event()
        self.addCleanup(release.set)
        def blocked(*args, **kwargs):
            entered.set(); release.wait(2); yield {'result': self.result}
        self.lookup.side_effect = blocked
        self.search.observe('Gimana keadaan Indonesia sekarang?', finished=True)
        before = monotonic(); self.handle(); self.assertLess(monotonic()-before, .2)
        self.assertTrue(entered.wait(1))
        self.assertTrue(self.call.lock.acquire(timeout=.1)); self.call.lock.release()
        self.call.closed.set(); self.search.cancel(); release.set(); self.wait()
        self.assertEqual(self.call.messages, []); self.assertEqual(self.call.frames, [])
        self.finish.assert_called_once(); self.assertTrue(self.finish.call_args.kwargs['success'])

    def test_timeout_sends_one_failure_and_late_result_cannot_replace_it(self):
        entered, release = Event(), Event(); self.addCleanup(release.set)
        def blocked(*args, **kwargs):
            entered.set(); release.wait(2); yield {'result': self.result}
        self.lookup.side_effect = blocked
        self.search.observe('Gimana keadaan Indonesia sekarang?', finished=True)
        self.handle(); self.assertTrue(entered.wait(1))
        job = self.search.job
        self.search._reply(job, {'available': False, 'reason': 'search_timeout', 'current_verified': False})
        release.set(); self.wait()
        self.assertEqual(len(self.call.messages), 1)
        self.assertFalse(self.response()['available'])
        self.assertEqual(self.call.frames[0]['citations'], [])
        self.finish.assert_called_once()

    def test_public_topic_followup_uses_only_enum_memory_and_context_optout(self):
        self.assertEqual(search.public_intent('Bagaimana kondisi ekonomi Indonesia hari ini?'), 'economy')
        self.assertEqual(search.public_intent('Ekonominya gimana?', True), 'economy')
        self.assertIsNone(search.public_intent('Ekonominya gimana?', False))
        self.assertIsNone(search.public_intent('What is the economy?', True))
        self.assertIsNone(search.public_intent('Jangan cari di internet. Gimana keadaan Indonesia sekarang?'))

    def test_provider_tool_cancellation_discards_reply_but_settles_already_started_work(self):
        entered, release = Event(), Event(); self.addCleanup(release.set)
        def blocked(*args, **kwargs):
            entered.set(); release.wait(2); yield {'result': self.result}
        self.lookup.side_effect = blocked
        self.search.observe('Gimana keadaan Indonesia sekarang?', finished=True)
        self.handle(); self.assertTrue(entered.wait(1))
        self.search.cancel(['one']); release.set(); self.wait()
        self.assertFalse(self.call.closed.is_set())
        self.assertEqual(self.call.messages, []); self.assertEqual(self.call.frames, [])
        self.finish.assert_called_once()

    def test_new_spoken_request_prevents_stale_result_attribution(self):
        entered, release = Event(), Event(); self.addCleanup(release.set)
        def blocked(*args, **kwargs):
            entered.set(); release.wait(2); yield {'result': self.result}
        self.lookup.side_effect = blocked
        self.search.observe('Gimana keadaan Indonesia sekarang?', finished=True)
        self.handle(); self.assertTrue(entered.wait(1))
        self.search.observe('Sekarang saya mau membahas masalah pribadi.', finished=True)
        release.set(); self.wait()
        self.assertFalse(self.response()['available'])
        self.assertEqual(self.call.frames[0]['citations'], [])
        self.finish.assert_called_once()


if __name__ == '__main__': unittest.main()
