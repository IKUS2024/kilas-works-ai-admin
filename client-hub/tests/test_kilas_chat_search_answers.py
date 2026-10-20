"""Chat/Search regressions: synthetic evidence only; no model/search transport."""
import copy
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import test_kilas_chat_auto_search as fixture
from kilas_ai import (agent_store, chat_model_tools, chat_models, chat_quality, chat_web,
                      model_policy, providers, response_style, routing, store, tools, unified_runtime)


URL = 'https://example.test/current'


class AnswerTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('External transport forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def lookup(self, data, question='Cari berita ekonomi terbaru', **kwargs):
        with patch.dict(os.environ, {'KILAS_AI_OPENAI_WEB_MODEL': model_policy.LUNA}), \
                patch.object(tools, '_request', return_value=data) as transport:
            result = next(e['result'] for e in tools.web_search_steps(
                [{'role': 'user', 'content': question}], **kwargs) if 'result' in e)
        self.assertEqual(transport.call_count, 1)
        return result

    def test_provider_urls_keep_functional_path_query_and_fragment(self):
        url = 'https://example.test/archive/;edition=2?q=a%20b&empty=&q=c#table-2'
        data = fixture.response('[Sumber](' + url + ')')
        data['output'][1]['content'][0]['annotations'][0]['url'] = url
        result = self.lookup(data)
        self.assertEqual(result['citations'][0]['url'], url)
        self.assertEqual(tools._source_destination(url), url)

    def test_valid_parenthesized_links_from_annotations_and_search_sources(self):
        url = 'https://example.test/wiki/Ekonomi_(Indonesia)'
        for annotations in (True, False):
            data = fixture.response('Temuan sintetis. [Sumber](' + url + ').', sources=False)
            if annotations:
                data['output'][1]['content'][0]['annotations'] = [{'type': 'url_citation', 'url': url}]
            else:
                data['output'][0]['action'] = {'sources': [{'url': url}]}
            with self.subTest(annotations=annotations):
                self.assertEqual(self.lookup(data)['citations'][0]['url'], url)
        self.assertFalse(tools._cited_urls_only('[A](' + url + ')[B](https://invented.test/a)', [{'url': url}]))

    def test_followup_chain_keeps_original_entities_and_intermediate_correction(self):
        questions = ['Cari harga paket Halo AI dan Cekat AI terbaru?',
                     'Kalau harga tahunannya?', 'Yang untuk tim 5 orang?']
        history = [{'role': 'system', 'content': 'SYSTEM_PRIVATE'}]
        for question in questions:
            history += [{'role': 'user', 'content': question + '\nPRIVATE_NOTE'},
                        {'role': 'assistant', 'content': 'ASSISTANT_PRIVATE'}]
        history += [{'role': 'user', 'content': 'Yang paling murah sekarang?'}]
        query = tools._chat_search_text(history)
        for question in questions:
            self.assertIn(question, query)
        self.assertNotIn('PRIVATE', query)
        self.assertIsNone(routing.lookup_topic('Yang kedua?', ['Cari harga emas', 'Jelaskan fotosintesis']))

    def test_long_current_request_keeps_its_final_constraints_without_attachment_export(self):
        question = 'Cari perbandingan paket terbaru. ' + 'Kriteria penilaian. ' * 350 + 'WAJIB harga tahunan untuk 5 orang.'
        query = tools._chat_search_text([{'role': 'user', 'content': question +
            "\n\nTeks berikut berhasil diekstrak dari lampiran 'private.pdf'.\nPRIVATE_ATTACHMENT"}])
        self.assertEqual(query, question)
        self.assertIn('WAJIB harga tahunan untuk 5 orang.', query)

    def test_current_weather_is_lookup_now_and_scheduling_remains_explicit(self):
        for question in ('Cuaca Jakarta besok bagaimana?', 'Weather in Jakarta tomorrow?', 'Cuaca Bandung sekarang?'):
            with self.subTest(question=question):
                self.assertEqual(routing.tool_for(question), 'WEB')
                self.assertEqual(unified_runtime.intent(question), 'WEB')
        for question in ('Apa itu cuaca?', 'Jelaskan cara membuat jadwal belajar', 'Translate: Weather in Jakarta tomorrow?',
                         'Buat puisi tentang cuaca', 'Buat caption tentang cuaca', 'Analisis data cuaca berikut: suhu 30, 31, 32.'):
            with self.subTest(question=question):
                self.assertEqual(routing.tool_for(question), 'CHAT')
                self.assertEqual(unified_runtime.intent(question), 'CHAT')
        self.assertEqual(unified_runtime.intent('Ingatkan cek cuaca Jakarta besok jam 8'), 'SCHEDULE')
        self.assertEqual(unified_runtime.intent('Besok jam 8 cari cuaca Jakarta'), 'WORK')

    def test_research_synthesis_gets_original_request_and_all_sources(self):
        request = 'Bandingkan beberapa sumber tentang paket A dan B untuk tim 5 orang; harga tahunan.'
        first = fixture.response('Fakta pertama.'); second = fixture.response('Fakta kedua.')
        second['output'][1]['content'][0]['annotations'][0]['url'] = 'https://second.test/a'
        synthesis = {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'Perbandingan [1] [2].'}]}]}
        with patch.dict(os.environ, {'KILAS_AI_OPENAI_WEB_MODEL': model_policy.LUNA}), \
                patch.object(tools, '_request', side_effect=[first, second, synthesis]) as transport:
            result = next(e['result'] for e in tools.web_search_steps(
                [{'role': 'user', 'content': request}], max_calls=2, minimal_query=True) if 'result' in e)
        self.assertIn(request, transport.call_args.args[0]['input'])
        self.assertIn('[2]', result['text'])
        self.assertEqual(transport.call_count, 3)

    def test_complete_answer_and_citations_are_not_silently_sliced(self):
        data = fixture.response('Penjelasan sintetis lengkap. ' * 1300 + 'AKHIR_JAWABAN')
        sources = [{'type': 'url_citation', 'url': f'https://example.test/{i}', 'title': f'Sumber {i}'} for i in range(10)]
        data['output'][1]['content'][0]['annotations'] = sources
        result = self.lookup(data)
        self.assertTrue(result['text'].endswith('AKHIR_JAWABAN'))
        self.assertEqual(len(result['citations']), 10)

    def test_selected_synthesis_rejects_nonexistent_numbered_source(self):
        context = chat_models.bind(model_policy.ChatContext([{'role': 'user', 'content': 'Cari berita terkini'}]), 'gemini-3.8-flash')
        evidence = {'text': 'Temuan sintetis.', 'model': model_policy.LUNA,
                    'citations': [{'url': URL, 'title': 'Sumber'}], 'usage': {}, 'search_calls': 1}
        events = [{'type': 'delta', 'text': 'Temuan bersumber [99].'}, {'type': 'finish', 'reason': 'stop'}]
        with patch.object(providers, 'stream', return_value=iter(events)) as generate:
            with self.assertRaises(tools.ToolUnavailable):
                chat_model_tools.compose(evidence, context)
        self.assertEqual(generate.call_count, 1)

    def test_numeric_currency_chain_keeps_rate_gate_and_selected_result(self):
        context = chat_models.bind(model_policy.ChatContext([
            {'role': 'user', 'content': '600 RMB ke IDR'},
            {'role': 'assistant', 'content': 'PRIVATE unverified old guess'},
            {'role': 'user', 'content': 'kalau 700?'},
            {'role': 'assistant', 'content': 'PRIVATE unverified old guess'},
            {'role': 'user', 'content': 'kalau 800?'}]), 'gemini-3.8-flash')
        with patch.dict(os.environ, {'KILAS_AI_OPENAI_WEB_MODEL': model_policy.LUNA}), \
                patch.object(tools, '_request', return_value=fixture.response(fixture.rate())) as search, \
                patch.object(providers, 'stream', side_effect=AssertionError('No second generation')):
            result = next(e['result'] for e in tools.web_search_steps(context, minimal_query=True, verify_currency=True) if 'result' in e)
            result = chat_model_tools.compose(result, context)
        self.assertIn('1.921.000,00', result['text'])
        self.assertTrue(result['currency_verified'])
        self.assertFalse(result['model_metadata']['selected_model_called'])
        self.assertEqual(search.call_args.args[0]['input'], '800 CNY to IDR: current published exchange rate')
        self.assertIsNone(chat_web.conversion_followup_context('kalau 800?', ['600 RMB ke IDR', 'Jelaskan fotosintesis']))

    def test_old_quote_unavailable_source_and_empty_result_do_not_become_facts(self):
        stale = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        for data in (fixture.response(fixture.rate(as_of=stale)),
                     fixture.response(fixture.rate(source_url='https://unavailable.test/quote')),
                     {'status': 'completed', 'output': [], 'usage': {'input_tokens': 5}},
                     fixture.response('', sources=False)):
            with self.subTest(data=data), self.assertRaises(tools.ToolUnavailable):
                self.lookup(data, question='600 RMB ke IDR', verify_currency=True)

    def test_source_dates_and_unavailable_evidence_remain_explicit(self):
        text = ('Sumber ini diterbitkan pada 2022-01-01. Data terbaru belum terverifikasi; '
                'situs utama tidak tersedia. Temuan historis dari sumber alternatif [1].')
        data = fixture.response(text)
        data['output'][0]['action'] = {'sources': [{'url': 'https://unavailable.test/denied'}, {'url': URL}]}
        result = self.lookup(data)
        self.assertEqual(result['text'], text)
        self.assertNotIn('unavailable.test', json.dumps(result['citations']))
        instructions = response_style.search_instructions('2026-10-20', '')
        self.assertIn('never invent a date or describe an undated source as current', instructions)

    def test_fake_indonesian_lookup_claims_are_flagged_but_honest_limits_are_allowed(self):
        for answer in ('Sudah saya cek sumber terbaru, hasilnya demikian.',
                       'Saya telah melakukan pencarian web dan menemukan hasil ini.',
                       'Saya sudah mengecek situs resminya.',
                       'Saya sudah mencari di internet, tetapi tidak menemukan hasil.',
                       'I have searched the web and found this.'):
            with self.subTest(answer=answer):
                self.assertIn('fake_web', chat_quality.violations('Jelaskan hasilnya', answer))
        for answer in ('Saya belum mengecek situs resminya.', 'Saya tidak melakukan pencarian web.',
                       'Periksa sumber terbaru sebelum memutuskan.', 'Jika saya mencari di internet, hasilnya perlu diperiksa.'):
            self.assertNotIn('fake_web', chat_quality.violations('Jelaskan hasilnya', answer))
        self.assertNotIn('fake_web', chat_quality.violations('Terjemahkan: I have searched the web.', 'Saya sudah mencari di internet.'))

    def test_numeric_data_and_links_do_not_masquerade_as_numbered_references(self):
        for answer in ('[99]', '`data[99]`', '```python\narray[99]\n```', '[2026](' + URL + ')'):
            self.assertTrue(tools._citation_indices_valid(answer, [{'url': URL}]))
        for answer in ('Sumber [0].', 'Sumber [99].', 'Sumber [999999999999999999].'):
            self.assertFalse(tools._citation_indices_valid(answer, [{'url': URL}]))

    def test_retrieval_rejects_nonexistent_reference_and_reencoded_functional_query(self):
        with self.assertRaises(tools.ToolUnavailable) as failure:
            self.lookup(fixture.response('Temuan sintetis [99].'))
        self.assertEqual(failure.exception.code, 'search_invalid_citation')
        allowed = [{'url': 'https://example.test/signed/?sig=a%20b&empty='}]
        self.assertFalse(tools._cited_urls_only('[Sumber](https://example.test/signed/?sig=a+b&empty=)', allowed))


class AnswerRouteTests(unittest.TestCase):
    setUp = fixture.AutoSearchTests.setUp
    client = fixture.AutoSearchTests.client
    submit_chat = fixture.AutoSearchTests.submit_chat

    def test_long_search_answer_and_all_sources_survive_both_chat_surfaces(self):
        text = 'Penjelasan dari sumber sintetis. ' * 450 + 'AKHIR_JAWABAN'
        data = fixture.response(text)
        data['output'][1]['content'][0]['annotations'] = [
            {'type': 'url_citation', 'url': f'https://example.test/{i}', 'title': f'Sumber {i}'} for i in range(10)]
        for agent in (False, True):
            with self.subTest(agent=agent), patch.object(tools, '_request', return_value=copy.deepcopy(data)), \
                    patch.object(providers, 'stream', side_effect=AssertionError('No guessed fallback')):
                response = self.submit_chat('Cari berita ekonomi terkini', agent)
                answer = agent_store.messages(self.owner, conversation_id=self.conversation)[-1]['content'] if agent else store.messages(self.owner, self.thread)[-1]['content']
                self.assertIn('AKHIR_JAWABAN', answer)
                self.assertIn('https://example.test/9', answer if agent else response.text)

    def test_no_search_after_multiple_followups_never_guesses_current_rate(self):
        for agent in (False, True):
            with patch.object(tools, '_request', return_value=fixture.response(fixture.rate())):
                self.submit_chat('kalau 700?', agent, previous_request='600 RMB ke IDR')
            client = self.client(self.owner)
            with self.subTest(agent=agent), patch.object(tools, '_request', side_effect=AssertionError('No browsing')), \
                    patch.object(providers, 'stream', side_effect=AssertionError('No current rate guess')):
                if agent:
                    client.post('/kilas-ai/agent/chat', data={'message': 'kalau 800, jangan search',
                        'conversation_id': self.conversation, 'operation_key': 'no_search_chain_1234567890', 'csrf_token': 'work-csrf'}).get_data()
                    answer = agent_store.messages(self.owner, conversation_id=self.conversation)[-1]['content']
                else:
                    response = client.post(f'/kilas-ai/threads/{self.thread}/send', data={
                        'content': 'kalau 800, jangan search', 'operation_key': 'no_search_chain_1234567890', 'csrf_token': 'work-csrf'})
                    response.get_data()
                    answer = store.messages(self.owner, self.thread)[-1]['content']
                self.assertIn('belum terverifikasi', answer)

    def test_empty_and_error_results_never_publish_done_or_guessed_fallback(self):
        for agent in (False, True):
            for failure in (tools.ToolUnavailable('PRIVATE', code='provider_timeout'),
                            tools.ToolUnavailable('PRIVATE', code='provider_rate_limited'),
                            {'status': 'completed', 'output': []}):
                with self.subTest(agent=agent, failure=type(failure).__name__), \
                        patch.object(tools, '_request', side_effect=failure if isinstance(failure, Exception) else None,
                                     return_value=failure) as search, \
                        patch.object(providers, 'stream', side_effect=AssertionError('No guessed fallback')):
                    response = self.submit_chat('Cari berita Indonesia terbaru', agent)
                    answer = agent_store.messages(self.owner, conversation_id=self.conversation)[-1]['content'] if agent else response.text
                    self.assertIn('belum terverifikasi', answer)
                    self.assertNotIn('PRIVATE', answer)
                    self.assertNotIn('event: done', response.text)
                    self.assertEqual(search.call_count, 1)


if __name__ == '__main__':
    unittest.main()
