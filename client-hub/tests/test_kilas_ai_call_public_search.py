"""Synthetic public lookup boundaries and lifecycle; no paid/network/DB IO."""
import json
import base64
from itertools import chain, repeat
import os
from pathlib import Path
import sys
from threading import Event, Lock, RLock, Thread
from datetime import datetime, timezone, timedelta
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
        patch.object(search,"TEXT_SETTLE_SECONDS",0).start()
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
        self.original_lookup = search.tools.web_search_steps
        self.lookup = patch.object(search.tools, 'web_search_steps', side_effect=lookup).start()

    def handle(self, ident='one', args=None):
        return self.search.handle({'functionCalls': [{'id': ident, 'name': search.NAME,
            'args': {'country': 'ID', 'topic': 'general'} if args is None else args}]})

    def wait(self):
        deadline = monotonic()+4
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
        self.search.observe(private+'Gimana keadaan Indonesia sekarang?')
        self.assertTrue(self.handle()); self.wait()
        context, kwargs = self.lookups[0]
        self.assertEqual(len(context), 1)
        self.assertNotIn(private, str(context))
        self.assertNotIn('723836', str(context))
        self.assertNotIn('Gimana', str(context))
        self.assertIn('Indonesia', context[0]['content'])
        self.assertEqual(kwargs['max_calls'], 1)
        self.assertTrue(kwargs['minimal_query'])
        self.assertEqual(kwargs['request_timeout'], 25)
        sentinel = {'status': 'failed', 'output': []}
        self.assertIs(kwargs['response_normalizer'](sentinel), sentinel)
        self.reserve.assert_called_once()
        self.assertEqual(self.reserve.call_args.args[2][:9], 'call-web-')
        self.assertTrue(self.response()['available'])
        self.assertEqual(self.call.frames[0]['citations'][0]['url'], 'https://example.org/news')
        self.finish.assert_called_once()
        self.assertTrue(self.finish.call_args.kwargs['success'])
        self.assertEqual(self.call.checks, 1)
        self.search.turn_complete(); self.assertEqual(self.search.buffer, '')

    def test_tool_waits_for_documented_activity_end_without_charging_live_speech(self):
        self.search.activity('ACTIVITY_START')
        self.search.observe('Gimana keadaan Indonesia sekarang?')
        self.handle(); sleep(.025)
        self.reserve.assert_not_called()
        self.search.activity('ACTIVITY_END')
        self.wait(); self.reserve.assert_called_once()

    def test_split_no_search_optout_prevents_lookup_and_no_speech_is_not_a_request(self):
        self.search.observe('Gimana keadaan Indonesia sekarang? Jangan ')
        self.search.observe('cari di internet.')
        # Force only the intent wait's deadline; no provider/deadline sleeps.
        with patch.object(search, 'monotonic', side_effect=chain([0, 0], repeat(4))):
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
        self.search.observe('Gimana keadaan Indonesia sekarang?')
        self.handle(); self.wait(); self.handle(); self.wait()
        self.reserve.assert_called_once(); self.lookup.assert_called_once()
        self.assertEqual(len(self.call.messages), 1)
        # Same recognized utterance cannot authorize another new function ID.
        job = {'id': 'again', 'args': {'country': 'ID', 'topic': 'general'}, 'deadline': 20,
               'cancelled': Event(), 'replied': False, 'timer': Mock()}
        with patch.object(search, 'monotonic', side_effect=chain([0, 0], repeat(4))): self.search._execute(job)
        self.reserve.assert_called_once()

    def test_quota_provider_timeout_and_missing_sources_fail_explicitly(self):
        self.search.observe('Ada berita terbaru di Indonesia?')
        self.reserve.side_effect = search.usage.UsageLimit('offline limit')
        self.handle(); self.wait(); self.lookup.assert_not_called()
        self.finish.assert_not_called(); self.assertFalse(self.response()['available'])
        self.reserve.side_effect = None
        self.search.turn_complete()
        self.search.observe('Ada berita terbaru di Indonesia?')
        self.lookup.side_effect = search.tools.ToolUnavailable('offline', model='offline-model',
            usage={'input_tokens': 10}, code='provider_timeout')
        self.handle('timeout'); self.wait()
        self.assertFalse(self.response()['current_verified'])
        self.assertFalse(self.finish.call_args.kwargs['success'])
        self.assertEqual(self.finish.call_args.kwargs['usage']['input_tokens'], 10)
        self.search.turn_complete()
        self.search.observe('Ada berita terbaru di Indonesia?')
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
        self.search.observe('Gimana keadaan Indonesia sekarang?')
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
        self.search.observe('Gimana keadaan Indonesia sekarang?')
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

    def test_general_public_information_and_country_questions_are_recognized(self):
        for text in ('Cari informasi terkini tentang Indonesia.',
                     'Tolong carikan informasi tentang Indonesia.',
                     'Informasi terbaru mengenai Indonesia?',
                     'Bagaimana Indonesia sekarang?', 'Gimana dengan Indonesia hari ini?',
                     'Indonesia sekarang gimana?', 'How is Indonesia today?',
                     'Search for information about Indonesia.', 'Current information about Indonesia?'):
            with self.subTest(text=text):
                self.assertEqual(search.public_intent(text), 'general')
        for text in ('Saya sekarang di Indonesia.', 'Saya tinggal di Indonesia hari ini.',
                     'Bagaimana rekening saya di Indonesia sekarang?',
                     'Cari informasi pribadi saya di Indonesia.',
                     'Informasi tentang Indonesia.', 'Bagaimana Indonesia merdeka?',
                     'Halo Indonesia!', 'Apa itu informasi?',
                     'Jangan cari informasi terkini tentang Indonesia.',
                     "Don't search for current information about Indonesia."):
            with self.subTest(text=text):
                self.assertIsNone(search.public_intent(text))

    def test_fragmented_general_information_request_dispatches_only_public_constants(self):
        self.search.activity('ACTIVITY_START')
        for fragment in ('Tolong cari ', 'informasi terkini ', 'tentang Indonesia.'):
            self.search.observe(fragment)
        self.search.activity('ACTIVITY_END')
        self.handle(); self.wait()
        self.assertTrue(self.response()['available'])
        self.assertEqual(self.search.diagnostic()['lookup_started'], 1)
        self.assertEqual(self.search.diagnostic()['function_responses_sent'], 1)
        context, _ = self.lookups[0]
        self.assertEqual(context, [{'role': 'user', 'content': search.public_query(
            'general', self.response()['checked_on'])}])
        self.reserve.assert_called_once(); self.finish.assert_called_once()

    def test_intent_rejection_reasons_are_bounded_and_do_not_dispatch(self):
        cases = (
            ('no_transcript', '', None),
            ('scope_unrecognized', 'PRIVATE SENTINEL saya tinggal di Indonesia sekarang.', None),
            ('scope_mismatch', 'Bagaimana ekonomi Indonesia sekarang?', None),
            ('opt_out', 'Jangan cari informasi terkini tentang Indonesia.', None),
            ('speech_active', 'Bagaimana Indonesia sekarang?', 'speaking'),
            ('turn_already_used', 'Bagaimana Indonesia sekarang?', 'used'),
        )
        for reason, text, state in cases:
            with self.subTest(reason=reason):
                gate = search.PublicSearch(self.call)
                gate.observe(text)
                if state == 'speaking': gate.speaking = True
                if state == 'used': gate.used_number = gate.number
                job = {'id': reason, 'args': {'country': 'ID', 'topic': 'general'},
                       'deadline': monotonic()+20, 'cancelled': Event(), 'replied': False, 'timer': Mock()}
                with patch.object(search, 'INTENT_WAIT_SECONDS', 0): gate._execute(job)
                stats = gate.diagnostic()
                self.assertEqual(stats['intent_rejections'], {reason: 1})
                self.assertNotIn('PRIVATE', json.dumps(stats))
                stats['intent_rejections'].clear()
                self.assertEqual(gate.diagnostic()['intent_rejections'], {reason: 1})
                self.assertEqual(self.response()['reason'], 'public_request_not_recognized')
        self.reserve.assert_not_called(); self.lookup.assert_not_called()

    def generic(self, query, ident='public-one'):
        return self.search.handle({'functionCalls': [{'id': ident, 'name': search.PUBLIC_NAME,
            'args': {'query': query}}]})

    def test_general_public_lookup_uses_minimized_current_turn_keywords_once(self):
        self.search.observe('Tolong cari jadwal museum nasional terbaru.')
        self.generic('jadwal museum nasional terbaru'); self.wait()
        self.assertTrue(self.response()['available'])
        context, kwargs = self.lookups[0]
        self.assertIn('Public topic keywords: jadwal museum nasional terbaru', context[0]['content'])
        self.assertNotIn('Tolong cari', context[0]['content'])
        self.assertEqual(kwargs['max_calls'], 1)
        self.reserve.assert_called_once(); self.finish.assert_called_once()
        self.assertEqual(self.search.diagnostic()['lookup_attempts'][0]['kind'], 'public')
        self.assertEqual(self.search.diagnostic()['lookup_attempts'][0]['result'], 'available')

    def test_generic_unsafe_ungrounded_and_currency_queries_never_dispatch(self):
        for speech, query in (
            ('Cari password rahasia otter saya', 'rahasia otter'),
            ('Cari informasi produk untuk me@example.org', 'informasi produk'),
            ('Cari nomor telepon 08123456789', 'nomor telepon'),
            ('Cari jadwal museum nasional', 'jadwal museum rahasia'),
            ('Jangan cari jadwal museum nasional', 'jadwal museum nasional'),
            ('Berapa kurs SGD ke IDR sekarang?', 'kurs SGD IDR sekarang'),
            ('Berapa kurs saat ini?', 'kurs saat ini'),
            ('Halo', 'Halo teman'),
        ):
            with self.subTest(query=query):
                self.search.turn_complete(); self.search.observe(speech)
                job = {'id': query, 'name': search.PUBLIC_NAME, 'args': {'query': query},
                       'deadline': monotonic()+20, 'cancelled': Event(), 'replied': False, 'timer': Mock()}
                with patch.object(search, 'INTENT_WAIT_SECONDS', 0): self.search._execute(job)
                self.assertFalse(self.response()['available'])
        self.reserve.assert_not_called(); self.lookup.assert_not_called()

    def test_generic_adapter_records_safe_envelope_and_does_not_retry_failure(self):
        payload = {'status': 'completed', 'max_tool_calls': 1, 'output': [
            {'id': 'SECRET_ID', 'type': 'web_search_call', 'status': 'searching',
             'action': {'type': 'search', 'query': 'PRIVATE_QUERY'}},
            {'type': 'message', 'status': 'completed', 'content': [
                {'type': 'output_text', 'text': 'PRIVATE_TEXT', 'annotations': []}]}]}
        self.lookup.side_effect = self.original_lookup
        with patch.object(search.tools, '_request', return_value=payload) as request:
            self.search.observe('Cari jadwal museum nasional terbaru.')
            self.generic('jadwal museum nasional terbaru'); self.wait()
        request.assert_called_once(); self.reserve.assert_called_once(); self.finish.assert_called_once()
        self.assertEqual(self.response()['reason'], 'search_not_completed')
        self.assertIn('Do not retry', self.response()['instruction'])
        stats = self.search.diagnostic()
        self.assertEqual(stats['lookup_attempts'][0]['envelope']['items']['web_search_call:searching'], 1)
        self.assertEqual(stats['failures_by_kind'], {'public:search_not_completed': 1})
        self.assertNotIn('PRIVATE', json.dumps(stats)); self.assertNotIn('SECRET', json.dumps(stats))
        stats['lookup_attempts'].clear()
        self.assertEqual(len(self.search.diagnostic()['lookup_attempts']), 1)

    def test_generic_actual_adapter_keeps_citations_and_bounds_attempt_metadata(self):
        payload = {'status': 'completed', 'output': [
            {'type': 'web_search_call', 'status': 'completed'},
            {'type': 'message', 'status': 'completed', 'content': [
                {'type': 'output_text', 'text': 'Synthetic museum finding.', 'annotations': [
                    {'type': 'url_citation', 'url': 'https://example.org/museum', 'title': 'Synthetic Museum'}]}]}],
            'usage': {'input_tokens': 20, 'output_tokens': 15}}
        self.lookup.side_effect = self.original_lookup
        with patch.object(search.tools, '_request', return_value=payload) as request:
            for number in range(9):
                self.search.turn_complete(); self.search.observe('Cari jadwal museum nasional terbaru.')
                self.generic('jadwal museum nasional terbaru', ident='public-'+str(number)); self.wait()
                self.assertTrue(self.response()['available'])
                self.assertEqual(self.response()['sources'][0]['url'], 'https://example.org/museum')
                self.assertEqual(request.call_count, number+1)
        self.assertEqual(self.reserve.call_count, 9); self.assertEqual(self.finish.call_count, 9)
        stats = self.search.diagnostic()
        self.assertEqual(stats['lookup_completed'], 9)
        self.assertEqual(len(stats['lookup_attempts']), 8)
        self.assertNotIn('museum', json.dumps(stats))

    def test_provider_tool_cancellation_discards_reply_but_settles_already_started_work(self):
        entered, release = Event(), Event(); self.addCleanup(release.set)
        def blocked(*args, **kwargs):
            entered.set(); release.wait(2); yield {'result': self.result}
        self.lookup.side_effect = blocked
        self.search.observe('Gimana keadaan Indonesia sekarang?')
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
        self.search.observe('Gimana keadaan Indonesia sekarang?')
        self.handle(); self.assertTrue(entered.wait(1))
        self.search.turn_complete()
        self.search.observe('Sekarang saya mau membahas masalah pribadi.')
        release.set(); self.wait()
        self.assertFalse(self.response()['available'])
        self.assertEqual(self.call.frames[0]['citations'], [])
        self.finish.assert_called_once()

    def fx(self, args=None, ident='fx-one'):
        return self.search.handle({'functionCalls':[{'id':ident,'name':search.FX_NAME,
            'args':{'base':'USD','quote':'IDR'} if args is None else args}]})

    def test_documented_live_transcript_without_finished_is_searchable(self):
        self.search.activity('ACTIVITY_START')
        self.search.observe('Bagaimana keadaan Indonesia saat ini?')
        self.search.activity('ACTIVITY_END')
        self.handle();self.wait()
        self.assertTrue(self.response()['available'])
        self.reserve.assert_called_once()
        self.assertEqual(self.search.diagnostic()['activity_end'],1)

    def test_transcript_after_tool_and_activity_end_does_not_need_extra_marker(self):
        self.search.activity('ACTIVITY_START');self.search.activity('ACTIVITY_END')
        self.handle();sleep(.01);self.reserve.assert_not_called()
        self.search.observe('Bagaimana keadaan Indonesia saat ini?')
        self.wait();self.assertTrue(self.response()['available'])

    def test_transcript_before_start_event_is_not_discarded(self):
        self.search.observe('Bagaimana keadaan Indonesia saat ini?')
        self.search.activity('ACTIVITY_START');self.search.activity('ACTIVITY_END')
        self.handle();self.wait();self.assertTrue(self.response()['available'])

    def test_fx_pair_aliases_and_direction_are_allowlisted_not_raw_queries(self):
        for text,expected in [('Berapa kurs dolar ke rupiah hari ini?',('USD','IDR')),
            ('Kurs USD ke IDR sekarang berapa?',('USD','IDR')),
            ('Berapa rupiah per dolar?',('USD','IDR')),
            ('Berapa rupiah untuk satu dolar?',('USD','IDR')),
            ('Kurs IDR ke USD hari ini?',('IDR','USD')),
            ('100 yuan ke rupiah berapa?',('CNY','IDR')),
            ('Berapa kurs dolar Singapura ke rupiah?',('SGD','IDR')),
            ('Current Australian dollars to rupiah rate?',('AUD','IDR')),
            ('Kurs dolar Hong Kong ke rupiah sekarang?',('HKD','IDR'))]:
            self.assertEqual(search.currency_pair(text),expected)
        self.assertIsNone(search.currency_pair('Berapa kurs saat ini?'))
        self.assertIsNone(search.currency_pair('My USD account and IDR account are private.'))
        self.assertIsNone(search.currency_pair('Jangan cari kurs USD ke IDR.'))

    def test_fx_uses_one_unit_constants_and_matching_function_name(self):
        self.search.observe('PRIVATE ACCOUNT 998123. Berapa kurs 100 dolar ke rupiah hari ini?')
        self.fx();self.wait()
        context,kwargs=self.lookups[0]
        self.assertEqual(context,[{'role':'user','content':'1 USD to IDR: current published exchange rate'}])
        self.assertTrue(kwargs['verify_currency']);self.assertEqual(kwargs['max_calls'],1)
        response=self.response();self.assertTrue(response['available'])
        self.assertEqual((response['base'],response['quote'],response['unit_amount']),('USD','IDR',1))
        self.assertEqual(self.call.messages[0]['toolResponse']['functionResponses'][0]['name'],search.FX_NAME)
        self.assertNotIn('998123',json.dumps(context))
        self.finish.assert_called_once()

    def test_quote_first_currency_amounts_keep_the_requested_direction(self):
        cases = (
            ('Berapa rupiah untuk 100 dolar?', ('USD', 'IDR')),
            ('Berapa rupiah untuk 10 dolar Singapura?', ('SGD', 'IDR')),
            ('Berapa USD untuk 100 IDR?', ('IDR', 'USD')),
            ('How much rupiah for 100 dollars?', ('USD', 'IDR')),
            ('How much IDR is 100 USD?', ('USD', 'IDR')),
            ('How much IDR are one hundred USD?', ('USD', 'IDR')),
            ('Berapa rupiah untuk seratus dolar?', ('USD', 'IDR')),
            ('Berapa rupiah untuk dua puluh dolar?', ('USD', 'IDR')),
            ('Berapa rupiah untuk 1.000 dolar?', ('USD', 'IDR')),
            ('Berapa 100 dolar dalam rupiah?', ('USD', 'IDR')),
            ('Kurs IDR ke USD sekarang?', ('IDR', 'USD')),
            ('Current USD to IDR rate?', ('USD', 'IDR')),
            ('Convert USD to IDR for 100 dollars', ('USD', 'IDR')),
            ('Konversi USD ke IDR untuk 100 dolar', ('USD', 'IDR')),
            ('Berapa rupiah untuk 100 USD atau dolar Amerika?', ('USD', 'IDR')),
            ('Berapa rupiah per dolar?', ('USD', 'IDR')),
        )
        for text, pair in cases:
            with self.subTest(text=text):
                self.assertEqual(search.currency_pair(text), pair)
        for text in ('Berapa rupiah untuk dolar?', 'How much rupiah for some dollars?',
                     'Berapa rupiah untuk beberapa dolar?', 'Berapa rupiah untuk -100 dolar?',
                     'Berapa rupiah untuk 100 USD dan 100 EUR?',
                     'Jangan cari berapa rupiah untuk 100 dolar?', 'What is rupiah against USD?'):
            with self.subTest(text=text):
                self.assertIsNone(search.currency_pair(text))

    def test_supported_named_dollar_variants_do_not_fall_back_to_usd(self):
        for name, base in (
            ('dollar Singapura', 'SGD'), ('dolar Singapore', 'SGD'), ('Singapore dollar', 'SGD'),
            ('dollar Australia', 'AUD'), ('Australian dollars', 'AUD'),
            ('dollar Hong Kong', 'HKD'), ('dolar Hongkong', 'HKD'),
            ('dollar Amerika Serikat', 'USD'), ('dolar US', 'USD'), ('U.S. dollars', 'USD'),
        ):
            with self.subTest(name=name):
                self.assertEqual(search.currency_pair('Berapa kurs '+name+' ke rupiah?'), (base, 'IDR'))
                self.assertEqual(search.currency_pair('Berapa rupiah untuk 100 '+name+'?'), (base, 'IDR'))

    def test_quote_first_fx_request_dispatches_only_correct_one_unit_pair(self):
        self.search.activity('ACTIVITY_START')
        self.search.observe('Berapa rupiah untuk 100 dolar?')
        self.search.activity('ACTIVITY_END')
        with patch.object(search, 'INTENT_WAIT_SECONDS', 0):
            self.fx(ident='quote-first-correct-direction'); self.wait()
        self.assertTrue(self.response()['available'])
        self.assertEqual(self.lookups[0][0], [{'role': 'user', 'content':
            '1 USD to IDR: current published exchange rate'}])
        self.assertEqual(self.lookups[0][1]['max_calls'], 1)
        self.reserve.assert_called_once(); self.finish.assert_called_once()

    def test_fx_scope_mismatch_clarifies_before_search_with_bounded_pair_diagnostics(self):
        for number in range(9):
            self.search.turn_complete()
            self.search.observe('PRIVATE_SENTINEL_'+str(number)+'. Berapa kurs USD ke IDR sekarang?')
            with patch.object(search, 'INTENT_WAIT_SECONDS', 0):
                self.fx({'base': 'IDR', 'quote': 'USD'}, ident='private-tool-id-'+str(number)); self.wait()
            response = self.response()
            self.assertEqual(response['reason'], 'public_request_not_recognized')
            self.assertIn('No exchange-rate search was sent', response['instruction'])
            self.assertIn('one brief clarification', response['instruction'])
            self.assertIn('direction', response['instruction'])
        self.reserve.assert_not_called(); self.lookup.assert_not_called(); self.finish.assert_not_called()
        diagnostics = self.search.diagnostic()
        self.assertEqual(diagnostics['intent_rejections'], {'scope_mismatch': 9})
        self.assertEqual(diagnostics['currency_pair_mismatches'], [
            {'requested_pair': ['IDR', 'USD'], 'recognized_pair': ['USD', 'IDR']}]*8)
        self.assertNotIn('PRIVATE', json.dumps(diagnostics))
        self.assertNotIn('private-tool-id', json.dumps(diagnostics))
        diagnostics['currency_pair_mismatches'].clear()
        self.assertEqual(len(self.search.diagnostic()['currency_pair_mismatches']), 8)

    def test_fx_mismatch_diagnostic_keeps_the_pair_used_by_the_rejected_comparison(self):
        self.search.observe('Berapa kurs USD ke IDR sekarang?')
        changed = Event()
        original_alive = self.search._alive
        def recognition_update(job):
            if not changed.is_set():
                changed.set()
                with self.search.lock:
                    self.search.fx_pair = ('IDR', 'USD')
            return original_alive(job)
        with patch.object(search, 'INTENT_WAIT_SECONDS', 0), \
             patch.object(self.search, '_alive', side_effect=recognition_update):
            self.fx({'base': 'IDR', 'quote': 'USD'}, ident='comparison-snapshot'); self.wait()
        self.assertTrue(changed.is_set())
        self.assertEqual(self.search.diagnostic()['currency_pair_mismatches'], [
            {'requested_pair': ['IDR', 'USD'], 'recognized_pair': ['USD', 'IDR']}])
        self.assertIn('one brief clarification', self.response()['instruction'])
        self.reserve.assert_not_called(); self.lookup.assert_not_called()

    def test_fx_rejects_extra_private_query_or_unknown_currency_before_reserving(self):
        self.fx({'base':'USD','quote':'IDR','amount':998123});self.wait()
        self.reserve.assert_not_called();self.lookup.assert_not_called()
        self.assertEqual(self.response()['reason'],'invalid_currency_pair')
        self.fx({'base':'PRIVATE','quote':'IDR'},ident='unknown');self.wait()
        self.reserve.assert_not_called()
        self.assertIn('which base and quote',self.response()['instruction'])

    def test_fx_actual_adapter_requires_matching_current_dated_cited_rate(self):
        today=datetime.now(timezone.utc)
        payload={'status':'completed','usage':{'input_tokens':100,'output_tokens':40},'output':[
            {'type':'web_search_call','status':'completed','action':{'sources':[{'url':'https://example.org/rate'}]}},
            {'type':'message','status':'completed','content':[{'type':'output_text',
                'text':json.dumps({'base':'USD','quote':'IDR','rate':'12345.67','as_of':today.date().isoformat(),
                                   'source_url':'https://example.org/rate'}),
                'annotations':[{'type':'url_citation','url':'https://example.org/rate','title':'Synthetic rate source'}]}]}]}
        # Remove only our outer adapter mock; retain normal usage spies. The
        # actual search adapter and currency verifier run on synthetic API data.
        from kilas_ai import tools
        self.lookup.side_effect=self.original_lookup
        with patch.dict(os.environ,{'KILAS_AI_OPENAI_WEB_MODEL':'gpt-6.1-sol'}),patch.object(tools,'_request',return_value=payload) as request:
            self.search.observe('Berapa kurs USD ke IDR hari ini?');self.fx();self.wait()
            self.assertTrue(self.response()['available'])
            self.assertIn('Waktu sumber:',self.response()['findings'])
            self.assertIn('12.345,67',self.response()['findings'])
            self.assertEqual(request.call_args.args[0]['max_tool_calls'],1)
            self.assertFalse(request.call_args.args[0]['store'])
            payload['output'][1]['content'][0]['text']=json.dumps({'base':'USD','quote':'IDR','rate':'12345.67',
                'as_of':(today-timedelta(days=8)).date().isoformat(),'source_url':'https://example.org/rate'})
            self.search.turn_complete();self.search.observe('Berapa kurs USD ke IDR hari ini?')
            self.fx(ident='stale');self.wait()
            self.assertFalse(self.response()['available'])
            self.assertEqual(self.response()['reason'],'rate_not_current')
            self.assertNotIn('findings',self.response())

    def test_failed_public_scope_and_currency_pair_remain_for_safe_followup(self):
        self.search.observe('Bagaimana keadaan Indonesia hari ini?');self.search.turn_complete()
        self.search.observe('Cari lagi informasinya di internet.')
        self.assertEqual(self.search.topic,'general')
        self.search.turn_complete();self.search.observe('Berapa kurs USD ke IDR sekarang?');self.search.turn_complete()
        self.search.observe('Cek lagi kursnya sekarang.')
        # Indonesian suffix doesn't widen the outbound query vocabulary.
        self.assertEqual(self.search.previous_pair,('USD','IDR'))
        self.assertEqual(self.search.fx_pair,('USD','IDR'))

    def test_fx_value_terms_and_explicit_same_pair_retries_keep_only_enums(self):
        self.assertEqual(search.currency_pair('Nilai tukar SGD/IDR hari ini?'), ('SGD', 'IDR'))
        self.search.observe('Berapa kurs SGD ke IDR sekarang?')
        self.fx({'base': 'SGD', 'quote': 'IDR'}); self.wait()
        for number, text in enumerate(('Berapa nilai tukarnya sekarang?', 'Coba cari lagi.', 'Cari yang tadi.')):
            with self.subTest(text=text):
                self.search.turn_complete(); self.search.observe(text)
                with patch.object(search, 'INTENT_WAIT_SECONDS', 0):
                    self.fx({'base': 'SGD', 'quote': 'IDR'}, ident='repeat-'+str(number)); self.wait()
                self.assertTrue(self.response()['available'])
                self.assertEqual(self.lookups[-1][0], [{'role': 'user', 'content':
                    '1 SGD to IDR: current published exchange rate'}])
        self.assertEqual(self.reserve.call_count, 4)
        self.assertEqual(self.finish.call_count, 4)
        self.assertEqual(self.search.diagnostic()['function_responses_sent'], 4)

    def test_latest_public_scope_does_not_reappear_after_topic_change_or_private_turn(self):
        self.search.observe('Berapa kurs SGD ke IDR sekarang?'); self.search.turn_complete()
        self.search.observe('Cari jadwal museum nasional terbaru.')
        self.generic('jadwal museum nasional terbaru'); self.wait(); self.search.turn_complete()
        self.search.observe('Berapa kursnya sekarang?')
        self.assertIsNone(self.search.fx_pair)
        self.search.turn_complete()
        self.search.observe('Berapa kurs USD ke IDR sekarang?'); self.search.turn_complete()
        self.search.observe('Jangan cari lagi.'); self.search.turn_complete()
        self.search.observe('Cek lagi kursnya sekarang.'); self.assertIsNone(self.search.fx_pair)
        self.search.turn_complete()
        self.search.observe('Berapa kurs USD ke IDR sekarang?'); self.search.turn_complete()
        self.search.observe('Cari rekening pribadi saya.'); self.search.turn_complete()
        self.search.observe('Cek lagi kursnya sekarang.'); self.assertIsNone(self.search.fx_pair)

    def test_generic_same_topic_retry_uses_only_previous_validated_keywords(self):
        query = 'jadwal museum nasional terbaru'
        self.search.observe('Tolong cari '+query+'.')
        self.generic(query); self.wait(); self.search.turn_complete()
        self.search.observe('Coba cari lagi.')
        with patch.object(search, 'INTENT_WAIT_SECONDS', 0):
            self.generic(query, ident='retry'); self.wait()
        self.assertTrue(self.response()['available'])
        self.assertEqual(self.lookups[0][0], self.lookups[1][0])
        self.assertNotIn('Coba cari lagi', str(self.lookups[-1][0]))
        self.assertEqual(self.reserve.call_count, 2)
        self.search.turn_complete(); self.search.observe('Cari yang tadi untuk rekening pribadi saya.')
        with patch.object(search, 'INTENT_WAIT_SECONDS', 0):
            self.generic(query, ident='private'); self.wait()
        self.assertFalse(self.response()['available'])
        self.assertEqual(self.reserve.call_count, 2)

    def test_non_currency_rates_remain_public_topics_after_fx_discussion(self):
        for number, (speech, query) in enumerate((
            ('Cari inflation rate terbaru.', 'inflation rate terbaru'),
            ('Search unemployment rate today.', 'unemployment rate today'),
        )):
            self.search.turn_complete(); self.search.observe('Berapa kurs USD ke IDR sekarang?')
            self.search.turn_complete(); self.search.observe(speech)
            self.assertIsNone(self.search.fx_pair)
            self.generic(query, ident='non-currency-'+str(number)); self.wait()
            self.assertTrue(self.response()['available'])
            self.assertIn(query, self.lookups[-1][0][0]['content'])
        self.assertIsNone(search.currency_pair('What is the latest inflation rate?', ('USD', 'IDR')))
        self.assertEqual(search.currency_pair('What is the rate now?', ('USD', 'IDR')), ('USD', 'IDR'))

    def test_new_general_topic_owns_context_after_indonesia_news(self):
        self.search.observe('Ada berita terbaru di Indonesia?'); self.handle(); self.wait()
        self.search.turn_complete(); self.search.observe('Bagaimana cuaca New York hari ini?')
        query = 'cuaca New York hari ini'
        self.generic(query); self.wait(); self.assertTrue(self.response()['available'])
        self.search.observe('.')
        self.search.turn_complete()
        self.assertIsNone(self.search.previous_topic)
        self.assertEqual(self.search.previous_query, query)
        self.search.observe('Coba cari lagi.')
        with patch.object(search, 'INTENT_WAIT_SECONDS', 0):
            self.generic(query, ident='same-new-topic'); self.wait()
        self.assertTrue(self.response()['available'])
        self.assertEqual(self.lookups[-1][0], self.lookups[-2][0])
        self.assertEqual(self.reserve.call_count, 3); self.assertEqual(self.finish.call_count, 3)

    def test_selected_specialized_tool_owns_retry_scope_despite_other_topic_hints(self):
        for number, kind in enumerate(('indonesia', 'currency')):
            self.search.turn_complete()
            self.search.observe('Bagaimana kondisi ekonomi Indonesia dan berapa kurs USD ke IDR sekarang?')
            if kind == 'indonesia': self.handle(ident='mixed-'+str(number), args={'country': 'ID', 'topic': 'economy'})
            else: self.fx(ident='mixed-'+str(number))
            self.wait(); self.assertTrue(self.response()['available']); self.search.observe('.')
            self.search.turn_complete()
            self.assertEqual(self.search.previous_topic, 'economy' if kind == 'indonesia' else None)
            self.assertEqual(self.search.previous_pair, ('USD', 'IDR') if kind == 'currency' else None)
            self.search.observe('Coba cari lagi.')
            if kind == 'indonesia': self.handle(ident='mixed-retry-'+str(number), args={'country': 'ID', 'topic': 'economy'})
            else: self.fx(ident='mixed-retry-'+str(number))
            self.wait(); self.assertTrue(self.response()['available'])
        self.assertEqual(self.reserve.call_count, 4); self.assertEqual(self.finish.call_count, 4)

    def test_news_fx_general_and_repeated_changed_queries_share_one_call(self):
        requests = (
            ('Ada berita terbaru di Indonesia?', search.NAME, {'country': 'ID', 'topic': 'general'}),
            ('Berapa kurs SGD ke IDR sekarang?', search.FX_NAME, {'base': 'SGD', 'quote': 'IDR'}),
            ('Cari jadwal museum nasional terbaru.', search.PUBLIC_NAME, {'query': 'jadwal museum nasional terbaru'}),
            ('Cari jadwal museum nasional terbaru.', search.PUBLIC_NAME, {'query': 'jadwal museum nasional terbaru'}),
            ('Cari harga tiket museum nasional terbaru.', search.PUBLIC_NAME, {'query': 'harga tiket museum nasional terbaru'}),
            ('Terus euro ke rupiah?', search.FX_NAME, {'base': 'EUR', 'quote': 'IDR'}),
        )
        for number, (text, name, args) in enumerate(requests):
            if number: self.search.turn_complete()
            self.search.activity('ACTIVITY_START'); self.search.observe(text); self.search.activity('ACTIVITY_END')
            self.search.handle({'functionCalls': [{'id': 'turn-'+str(number), 'name': name, 'args': args}]})
            self.wait(); self.assertTrue(self.response()['available'])
            self.assertFalse(self.call.closed.is_set())
        self.assertEqual(self.reserve.call_count, 6); self.assertEqual(self.finish.call_count, 6)
        self.assertEqual(len({call.args[2] for call in self.reserve.call_args_list}), 6)
        self.assertEqual(self.search.diagnostic()['lookup_started'], 6)

    def test_waiting_tool_cannot_consume_a_new_spoken_request(self):
        self.search.activity('ACTIVITY_START'); self.search.observe('Ada berita terbaru di Indonesia?')
        self.search.activity('ACTIVITY_END')
        waiting = Event()
        original_wait = self.search.changed.wait
        def observed_wait(timeout):
            waiting.set(); return original_wait(timeout)
        with patch.object(self.search.changed, 'wait', side_effect=observed_wait):
            self.handle(ident='old-topic', args={'country': 'ID', 'topic': 'economy'})
            self.assertTrue(waiting.wait(.5))
            self.search.activity('ACTIVITY_START'); self.search.observe('Bagaimana ekonomi Indonesia sekarang?')
            self.search.activity('ACTIVITY_END'); self.wait()
        self.assertFalse(self.response()['available'])
        self.assertEqual(self.search.diagnostic()['intent_rejections'], {'request_changed': 1})
        self.reserve.assert_not_called(); self.lookup.assert_not_called()
        self.handle(ident='new-topic', args={'country': 'ID', 'topic': 'economy'}); self.wait()
        self.assertTrue(self.response()['available'])
        self.reserve.assert_called_once(); self.finish.assert_called_once()

    def test_fx_tool_before_any_transcript_binds_to_the_first_request(self):
        self.fx(); sleep(.01); self.reserve.assert_not_called()
        self.search.observe('Berapa nilai tukar USD ke IDR sekarang?'); self.wait()
        self.assertTrue(self.response()['available'])
        self.reserve.assert_called_once(); self.finish.assert_called_once()

    def test_failure_then_new_explicit_request_can_succeed_without_retry_loop(self):
        for number, code in enumerate(('provider_timeout', 'search_not_completed', 'rate_time_missing', 'quota_unavailable')):
            with self.subTest(code=code):
                self.search.turn_complete(); self.search.observe('Berapa kurs USD ke IDR sekarang?')
                before = self.lookup.call_count
                self.lookup.side_effect = search.tools.ToolUnavailable('offline', code=code)
                if code == 'quota_unavailable': self.reserve.side_effect = search.usage.UsageLimit('offline')
                self.fx(ident='fail-'+str(number)); self.wait()
                self.assertFalse(self.response()['available'])
                self.assertEqual(self.response()['reason'], code)
                self.assertEqual(self.lookup.call_count-before, 0 if code == 'quota_unavailable' else 1)
                self.reserve.side_effect = None
                self.lookup.side_effect = lambda *a, **k: iter([{'result': self.result}])
                self.search.turn_complete(); self.search.observe('Coba cari lagi.')
                self.fx(ident='recovery-'+str(number)); self.wait()
                self.assertTrue(self.response()['available'])
                self.assertFalse(self.call.closed.is_set())

    def test_finished_timeout_or_cancellation_releases_slot_for_next_request(self):
        for number, outcome in enumerate(('timeout', 'cancel')):
            with self.subTest(outcome=outcome):
                entered, release = Event(), Event(); self.addCleanup(release.set)
                def blocked(*a, **k):
                    entered.set(); release.wait(2); yield {'result': self.result}
                self.lookup.side_effect = blocked
                self.search.turn_complete(); self.search.observe('Ada berita terbaru di Indonesia?')
                ident = 'blocked-'+str(number)
                self.handle(ident=ident); self.assertTrue(entered.wait(.5))
                if outcome == 'timeout': self.search._timeout(self.search.job)
                else: self.search.cancel([ident])
                release.set(); self.wait()
                self.lookup.side_effect = lambda *a, **k: iter([{'result': self.result}])
                self.search.turn_complete(); self.search.observe('Berapa kurs SGD ke IDR sekarang?')
                self.fx({'base': 'SGD', 'quote': 'IDR'}, ident='after-'+str(number)); self.wait()
                self.assertTrue(self.response()['available'])
                self.assertFalse(self.call.closed.is_set())
        self.assertEqual(self.reserve.call_count, 4); self.assertEqual(self.finish.call_count, 4)

    def test_fx_verification_failures_explain_only_the_recorded_limitation(self):
        cases = {'rate_time_missing': 'published source date/time', 'rate_not_current': 'too old or in the future',
                 'rate_source_missing': 'validated cited source', 'rate_invalid': 'valid positive exchange rate',
                 'currency_pair_missing': 'requested base and quote currencies'}
        for number, (code, expected) in enumerate(cases.items()):
            self.search.turn_complete(); self.search.observe('Berapa kurs USD ke IDR sekarang?')
            self.lookup.side_effect = search.tools.ToolUnavailable('offline', code=code)
            self.fx(ident='evidence-'+str(number)); self.wait()
            response = self.response()
            self.assertFalse(response['available']); self.assertEqual(response['reason'], code)
            self.assertIn(expected, response['instruction'])
            self.assertIn('invent a network problem or source outage', response['instruction'])
            self.assertNotIn('findings', response)
        self.assertEqual(self.lookup.call_count, 5)

    def test_end_clears_public_context_and_rejects_further_lookup_dispatch(self):
        self.search.observe('Berapa kurs SGD ke IDR sekarang?')
        self.fx({'base': 'SGD', 'quote': 'IDR'}); self.wait(); self.search.turn_complete()
        self.assertEqual(self.search.previous_pair, ('SGD', 'IDR'))
        self.search.cancel()
        self.assertIsNone(self.search.previous_pair); self.assertIsNone(self.search.previous_query)
        self.assertIsNone(self.search.fx_pair); self.assertEqual(self.search.buffer, '')
        self.search.observe('Coba cari lagi.'); self.fx(ident='after-end'); self.wait()
        self.reserve.assert_called_once(); self.finish.assert_called_once()
        self.assertEqual(len(self.call.messages), 1)

    def test_safe_configuration_report_and_failure_counts_do_not_log_text_or_keys(self):
        with patch.dict(os.environ,{'KILAS_AI_OPENAI_WEB_MODEL':'gpt-6.1-sol'}):
            report=search.configuration_report()
        self.assertEqual(report['public_search_model'],'gpt-6.1-sol')
        self.assertEqual(report['public_search_model_input_usd_per_million'],'2.00')
        self.assertEqual(report['public_search_forecast_usd'],'0.12')
        with patch.dict(os.environ,{'KILAS_AI_OPENAI_WEB_MODEL':'sk-PRIVATE-SECRET'}):
            self.assertNotIn('PRIVATE',json.dumps(search.configuration_report()))
        self.search.observe('PRIVATE TRANSCRIPT SENTINEL')
        self.search.failed('provider_timeout')
        stats=self.search.diagnostic()
        self.assertEqual(stats['failures']['provider_timeout'],1)
        self.assertNotIn('PRIVATE',json.dumps(stats))

    def audio_call(self):
        """Real Call input/output code, synthetic Gemini transport only."""
        call = calls.Call(1, 'a'*32, object())
        call.public_search.cancel();call.public_search = self.search;self.search.call = call
        call.check = Mock();call.transport_check = Mock();call.messages = []
        self.call = call
        pcm_sent = Event()
        def send(raw):
            value = json.loads(raw)
            if 'realtimeInput' in value:
                pcm_sent.set();return
            call.messages.append(value)
            response = value['toolResponse']['functionResponses'][0]['response']
            # This is a protocol fixture, not evidence of real model speech.
            text = ('According to Synthetic Source, the published finding is synthetic.' if response['available']
                    else 'The search timed out. I could not verify current information.')
            call.receive(json.dumps({'serverContent':{'outputTranscription':{'text':text},
                'modelTurn':{'parts':[{'inlineData':{'mimeType':'audio/pcm;rate=24000',
                    'data':base64.b64encode(bytes(4800)).decode()}}]},'turnComplete':True}}))
        call.ws = Mock(send=send)
        sender = Thread(target=call.send,daemon=True);sender.start()
        self.addCleanup(lambda:sender.join(.5));self.addCleanup(call.stop)
        return call,pcm_sent

    def test_delayed_actual_adapter_success_after_old_budget_keeps_pcm_and_sources_flowing(self):
        call,pcm_sent = self.audio_call()
        entered,release = Event(),Event();self.addCleanup(release.set)
        clock = [100.0]
        response = Mock(status_code=200)
        response.json.return_value = {'status':'completed','output':[
            {'type':'web_search_call','status':'completed'},
            {'type':'message','content':[{'type':'output_text','text':'Synthetic finding from a source.',
             'annotations':[{'type':'url_citation','url':'https://example.org/news','title':'Synthetic Source'}]}]}],
            'usage':{'input_tokens':20,'output_tokens':15}}
        def delayed(*a,**k):
            entered.set();release.wait(2);return response
        self.lookup.side_effect = lambda *a,**k:self.original_lookup(*a,**k)
        with patch.object(search,'monotonic',side_effect=lambda:clock[0]), \
             patch.object(search.tools.requests,'post',side_effect=delayed) as post:
            self.search.observe('What is the latest news in Indonesia?')
            self.handle();self.assertTrue(entered.wait(.5))
            before = monotonic();call.accept(0,bytes(6400))
            self.assertTrue(pcm_sent.wait(.5));self.assertLess(monotonic()-before,.5)
            clock[0] += 12 # Provider wait longer than the former 8s Call budget.
            release.set();self.wait()
        self.assertEqual(post.call_args.kwargs['timeout'],(10,25));post.assert_called_once()
        self.assertFalse(call.closed.is_set());self.assertEqual(call.turns,1)
        frames=call.snapshot(0)['frames'];types=[f['type'] for f in frames]
        self.assertLess(types.index('sources'),types.index('audio'))
        self.assertEqual(frames[0]['citations'][0]['url'],'https://example.org/news')
        self.assertEqual(self.search.diagnostic()['function_responses_sent'],1)
        self.reserve.assert_called_once();self.finish.assert_called_once()
        self.assertTrue(self.finish.call_args.kwargs['success'])

    def test_actual_adapter_read_timeout_delivers_truthful_spoken_protocol_turn_without_closing_call(self):
        call,_ = self.audio_call()
        self.lookup.side_effect = lambda *a,**k:self.original_lookup(*a,**k)
        with patch.object(search.tools.requests,'post',side_effect=search.tools.requests.ReadTimeout('SYNTHETIC')) as post:
            self.search.observe('What is the latest news in Indonesia?')
            self.handle();self.wait()
        post.assert_called_once();self.assertEqual(post.call_args.kwargs['timeout'],(10,25))
        self.assertFalse(call.closed.is_set());self.assertEqual(call.turns,1)
        response=self.response();self.assertEqual(response['reason'],'provider_timeout')
        self.assertFalse(response['current_verified']);self.assertIn('say aloud',response['instruction'])
        self.assertIn('Do not guess facts or retry',response['instruction'])
        self.assertEqual(call.frames[0]['citations'],[])
        self.assertTrue(any(f['type']=='audio' for f in call.frames))
        self.assertIn('could not verify',next(f['text'] for f in call.frames if f['type']=='text'))
        self.finish.assert_called_once();self.assertFalse(self.finish.call_args.kwargs['success'])

    def handoff_timeout(self, cancel):
        entered,release = Event(),Event();self.addCleanup(release.set)
        def blocked(*a,**k):
            entered.set();release.wait(2);yield {'result':self.result}
        self.lookup.side_effect=blocked
        clock=[100.0]
        with patch.object(search,'monotonic',side_effect=lambda:clock[0]),patch.object(search,'Timer'):
            self.search.observe('What is the latest news in Indonesia?')
            self.call.renewing.set();self.handle();self.assertTrue(entered.wait(.5))
            job=self.search.job;clock[0]=job['deadline']+1
            delivery=Thread(target=self.search._timeout,args=(job,),daemon=True);delivery.start()
            until=monotonic()+.5
            while not job['replied'] and monotonic()<until:sleep(.005)
            self.assertTrue(job['replied']);release.set()
            until=monotonic()+.5
            while not job.get('worker_done') and monotonic()<until:sleep(.005)
            self.assertTrue(job.get('worker_done'))
            self.assertIs(self.search.job,job) # Still cancellable after HTTP settlement.
            self.finish.assert_called_once()
            if cancel:self.search.cancel(['one'])
            self.call.renewing.clear();delivery.join(.5);self.wait()
            self.assertFalse(delivery.is_alive())
        self.assertFalse(self.call.closed.is_set())

    def test_lookup_deadline_failure_survives_handoff_and_is_delivered_once(self):
        self.handoff_timeout(cancel=False)
        self.assertEqual(len(self.call.messages),1)
        self.assertEqual(self.response()['reason'],'search_timeout')
        self.assertIn('say aloud',self.response()['instruction'])
        self.assertEqual(self.call.frames[0]['citations'],[])
        self.assertEqual(self.search.diagnostic()['function_responses_sent'],1)

    def test_provider_cancellation_after_worker_finish_suppresses_pending_handoff_reply(self):
        self.handoff_timeout(cancel=True)
        self.assertEqual(self.call.messages,[]);self.assertEqual(self.call.frames,[])
        self.assertEqual(self.search.diagnostic()['function_responses_sent'],0)

    def test_reservation_consuming_deadline_returns_failure_without_provider_dispatch(self):
        clock=[100.0]
        def delayed_reserve(*a,**k):
            clock[0] += search.LOOKUP_SECONDS+1;return 'PLUS',('WEB_SEARCH',)
        self.reserve.side_effect=delayed_reserve
        with patch.object(search,'monotonic',side_effect=lambda:clock[0]),patch.object(search,'Timer'):
            self.search.observe('What is the latest news in Indonesia?')
            self.handle();self.wait()
        self.lookup.assert_not_called();self.finish.assert_called_once()
        self.assertFalse(self.finish.call_args.kwargs['success'])
        self.assertEqual(self.response()['reason'],'search_timeout')

    def test_late_success_cannot_be_delivered_as_current_verified_evidence(self):
        clock=[100.0]
        def late(*a,**k):
            clock[0] += search.LOOKUP_SECONDS+1;yield {'result':self.result}
        self.lookup.side_effect=late
        with patch.object(search,'monotonic',side_effect=lambda:clock[0]),patch.object(search,'Timer'):
            self.search.observe('What is the latest news in Indonesia?');self.handle();self.wait()
        self.assertEqual(self.response()['reason'],'search_timeout')
        self.assertEqual(self.call.frames[0]['citations'],[])
        self.finish.assert_called_once();self.assertTrue(self.finish.call_args.kwargs['success'])

    def test_reply_handoff_has_bound_and_end_stays_responsive(self):
        # Delivery failure ends the broken transport, without another lookup.
        self.call.renewing.set()
        job={'id':'bounded','name':search.NAME,'replied':False,'cancelled':Event(),'deadline':0}
        with patch.object(search,'monotonic',side_effect=[100,131]):
            self.search._reply(job,self.search._timeout_response())
        self.assertTrue(self.call.closed.is_set());self.assertEqual(self.call.messages,[])
        self.assertEqual(self.search.diagnostic()['reply_delivery_failed'],1)
        self.reserve.assert_not_called()

    def test_end_during_send_lock_wait_cancels_reply_without_waiting_for_network_lock(self):
        job={'id':'ending','name':search.NAME,'replied':False,'cancelled':Event(),'deadline':0}
        self.search.job=job;self.call.send_lock.acquire()
        worker=Thread(target=self.search._reply,args=(job,self.search._timeout_response()),daemon=True)
        worker.start()
        until=monotonic()+.5
        while not job['replied'] and monotonic()<until:sleep(.005)
        before=monotonic();self.call.closed.set();self.search.cancel()
        worker.join(.2);self.call.send_lock.release()
        self.assertLess(monotonic()-before,.2);self.assertFalse(worker.is_alive())
        self.assertEqual(self.call.messages,[]);self.assertEqual(self.call.frames,[])

    def test_new_request_during_handoff_cannot_receive_old_sources(self):
        self.call.renewing.set()
        self.search.observe('What is the latest news in Indonesia?')
        self.handle()
        until=monotonic()+.5
        while not self.search.job['replied'] and monotonic()<until:sleep(.005)
        self.assertTrue(self.search.job['replied'])
        self.search.turn_complete();self.search.observe('Now help with a personal problem.')
        self.call.renewing.clear();self.wait()
        self.assertEqual(self.response()['reason'],'request_changed')
        self.assertEqual(self.call.frames[0]['citations'],[])
        self.finish.assert_called_once()


if __name__ == '__main__': unittest.main()
