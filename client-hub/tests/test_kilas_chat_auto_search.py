"""Deterministic chat search/FX provenance fixtures; all external transport forbidden."""
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import test_kilas_home as fixture
from kilas_ai import agent_store, chat_web, model_policy, providers, routing, store, tools, usage


def response(text, sources=True, searched=True):
    return {'output': ([{'type': 'web_search_call', 'status': 'completed'}] if searched else []) + [
        {'type': 'message', 'content': [{'type': 'output_text', 'text': text,
         'annotations': [{'type': 'url_citation', 'url': 'https://example.test/current', 'title': 'Sumber sintetis'}] if sources else []}]}],
        'usage': {'input_tokens': 20, 'output_tokens': 30}}


def rate(**changes):
    item = {'base': 'CNY', 'quote': 'IDR', 'rate': '2401.25',
            'as_of': datetime.now(timezone.utc).date().isoformat(),
            'source_url': 'https://example.test/current'}
    item.update(changes)
    return json.dumps(item)


class AutoSearchTests(unittest.TestCase):
    client = fixture.HomeTests.client

    def setUp(self):
        fixture.HomeTests.setUp(self)
        setting = patch.dict(os.environ, {'KILAS_AI_OPENAI_WEB_MODEL': model_policy.LUNA})
        setting.start(); self.addCleanup(setting.stop)
        self.sequence = 0

    def submit_chat(self, prompt, agent, *, previous_request=None, **extra):
        self.sequence += 1
        self.owner = fixture.fixture.base.f.fixture.repo.create_user(
            f'{self.id()}-{self.sequence}@example.test', 'hash')
        self.conversation = agent_store.new_conversation(self.owner)
        client = self.client(self.owner)
        key = 'auto_search_' + str(self.sequence).zfill(20)
        if agent:
            if previous_request:
                agent_store.append(self.owner, 'user', previous_request, self.conversation)
                agent_store.append(self.owner, 'assistant', 'Unverified earlier rate: 2300.', self.conversation)
            result = client.post('/kilas-ai/agent/chat', data={'message': prompt,
                'conversation_id': self.conversation, 'operation_key': key, 'csrf_token': 'work-csrf', **extra})
        else:
            self.thread = store.create_thread(self.owner)
            if previous_request:
                store.append_user_once(self.owner, self.thread, previous_request, 'FAST', key + '_prior')
                store.append_assistant(self.owner, self.thread, 'Unverified earlier rate: 2300.', 'FAST',
                                       None, None, key + '_prior', {'status': 'complete'})
            result = client.post(f'/kilas-ai/threads/{self.thread}/send', data={'content': prompt,
                'operation_key': key, 'csrf_token': 'work-csrf', **extra})
        result.get_data()  # Consume Flask's streaming generator before assertions.
        return result

    def test_currency_news_prices_and_verification_route_automatically(self):
        for text in ('1 USD berapa rupiah', '600 RMB berapa rupiah?', '600RMB to IDR', '600RMBtoIDR', '100 USD ke IDR', 'USD 100 ke IDR',
                     'Berita ekonomi', 'Harga iPhone 16 berapa?', 'Price of gold',
                     'Verifikasi klaim ini', 'Siapa presiden Indonesia sekarang?',
                     'versi Python terbaru sekarang apa?'):
            with self.subTest(text=text):
                self.assertEqual(routing.tool_for(text), 'WEB')
                self.assertEqual(fixture.fixture.unified_runtime.intent(text), 'WEB')
        for text in ('Halo', '2 + 2 berapa?', 'Apa itu kurs?', 'Apa itu RMB dan IDR?',
                     'Buat caption kopi', 'Terjemahkan: harga emas hari ini naik',
                     '600 RMB ke IDR dengan kurs 1 RMB = 2300 IDR',
                     'Cari kemungkinan salahnya pada kode ini', 'berapa harga generate image?'):
            with self.subTest(text=text):
                self.assertEqual(routing.tool_for(text), 'CHAT')
                self.assertEqual(fixture.fixture.unified_runtime.intent(text), 'CHAT')

    def test_no_browse_wins_over_manual_api_flag_and_fresh_followups(self):
        for text in ('600 RMB ke IDR, jangan browsing', 'Harga emas hari ini, tanpa search',
                     "Current news, don't search", 'Kurs dolar sekarang, do not browse',
                     'Berita terbaru, jangan cari di internet'):
            with self.subTest(text=text):
                self.assertEqual(routing.tool_for(text, search=True), 'CHAT')
                self.assertEqual(fixture.fixture.unified_runtime.intent(text), 'CHAT')
        self.assertFalse(routing.fresh_followup('berapa sekarang, jangan search', 'kurs dolar sekarang'))
        self.assertFalse(routing.fresh_followup('kalau 700, jangan search', '600 RMB ke IDR'))
        self.assertTrue(routing.fresh_followup('kalau 700, jangan search', '600 RMB ke IDR', respect_no_search=False))

    def test_currency_search_uses_source_rate_date_and_deterministic_arithmetic(self):
        for agent in (False, True):
            with self.subTest(agent=agent), patch.object(tools, '_request', return_value=response(rate())) as search, \
                    patch.object(providers, 'stream', side_effect=AssertionError('No guessed rate from chat')):
                result = self.submit_chat('600 RMB berapa rupiah?', agent)
                text = agent_store.messages(self.owner, conversation_id=self.conversation)[-1]['content'] if agent else result.get_data(as_text=True)
                self.assertIn('1.440.750,00', text)
                self.assertIn('2.401,25', text)
                self.assertIn('Waktu sumber:', text)
                self.assertIn('Diperiksa:', text)
                self.assertIn('https://example.test/current', text)
                self.assertNotIn('2300', text)
                self.assertEqual(search.call_count, 1)
                payload = search.call_args.args[0]
                self.assertEqual(payload['model'], model_policy.LUNA)
                self.assertEqual(payload['max_tool_calls'], 1)
                self.assertEqual(payload['tool_choice'], 'required')
                self.assertIn('never a remembered or assumed rate', payload['instructions'])
                self.assertEqual(payload['input'], '600 CNY to IDR: current published exchange rate')

    def test_completed_retrieved_sources_recover_missing_inline_annotations(self):
        for agent in (False, True):
            for question, answer in (
                ('Berita ekonomi terbaru', 'Temuan sintetis bertanggal hari ini: https://example.test/current'),
                ('Harga iPhone terbaru berapa?', 'Harga sintetis menurut https://example.test/current'),
                ('1 USD berapa rupiah', '```json\n' + rate(base='USD',rate='16000.25') + '\n```')):
                data=response(answer,sources=False)
                data['output'][0]['action']={'type':'search','sources':[
                    {'type':'url','url':'https://example.test/current','title':'Sumber aktual sintetis'},
                    {'type':'url','url':'https://unused.test/other','title':'Unused'}]}
                with self.subTest(agent=agent,question=question), patch.object(tools,'_request',return_value=data) as search, \
                        patch.object(providers,'stream',side_effect=AssertionError('No guessed fallback')):
                    result=self.submit_chat(question,agent)
                    text=agent_store.messages(self.owner,conversation_id=self.conversation)[-1]['content'] if agent else result.get_data(as_text=True)
                    self.assertIn('https://example.test/current',text)
                    self.assertNotIn('belum terverifikasi',text)
                    self.assertNotIn('unused.test',text)
                    if question.startswith('1 USD'):
                        self.assertIn('16.000,25',text)
                        self.assertIn('Waktu sumber:',text)
                    self.assertEqual(search.call_count,1)
                    self.assertEqual(search.call_args.args[0]['include'],['web_search_call.action.sources'])
                    self.assertEqual(search.call_args.args[0]['max_tool_calls'],1)

    def test_retrieved_source_fallback_rejects_uncited_failed_or_stale_evidence(self):
        answers=('Unsupported finding without any cited URL.',
                 'Invented URL https://invented.test/current',
                 rate(base='USD',as_of=(datetime.now(timezone.utc)-timedelta(days=30)).date().isoformat()))
        for answer in answers:
            data=response(answer,sources=False)
            data['output'][0]['action']={'type':'search','sources':[{'type':'url','url':'https://example.test/current'}]}
            with self.subTest(answer=answer),patch.object(tools,'_request',return_value=data) as search:
                with self.assertRaises(tools.ToolUnavailable):
                    list(tools.web_search_steps([{'role':'user','content':'1 USD berapa rupiah'}],verify_currency=True))
                self.assertEqual(search.call_count,1)
        data=response('See https://example.test/current',sources=False)
        data['output'][0].update(status='failed',action={'sources':[{'url':'https://example.test/current'}]})
        with patch.object(tools,'_request',return_value=data):
            with self.assertRaises(tools.ToolUnavailable):
                list(tools.web_search_steps([{'role':'user','content':'Berita terbaru'}]))

    def test_search_failure_reasons_are_distinct_and_do_not_retry_paid_transport(self):
        failures=[(tools.requests.Timeout('PRIVATE'),'provider_timeout'),
                  (tools.requests.ConnectionError('PRIVATE'),'provider_connection'),
                  (ValueError('PRIVATE'),'provider_invalid_response')]
        for status,code in [(400,'provider_request_rejected'),(401,'configuration_rejected'),
                            (403,'configuration_rejected'),(429,'provider_rate_limited'),(503,'provider_http_error')]:
            http=tools.requests.Response();http.status_code=status
            failures.append((tools.requests.HTTPError('PRIVATE',response=http),code))
        for error,code in failures:
            with self.subTest(code=code),patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}), \
                    patch.object(tools.requests,'post',side_effect=error) as post:
                with self.assertRaises(tools.ToolUnavailable) as failure:
                    list(tools.web_search_steps([{'role':'user','content':'Berita terbaru'}]))
                self.assertEqual(failure.exception.code,code)
                self.assertEqual(post.call_count,1)
                message=chat_web.search_failure_message(failure.exception)
                self.assertIn('belum terverifikasi',message)
                self.assertNotIn('PRIVATE',message)
                with self.assertLogs('kilas_ai.tools',level='WARNING') as logs:
                    tools.log_search_failure(failure.exception)
                self.assertIn(code,logs.output[0]);self.assertNotIn('PRIVATE',logs.output[0])
        with patch.dict(os.environ,{'KILAS_AI_OPENAI_WEB_MODEL':''}),patch.object(tools.requests,'post') as post:
            with self.assertRaises(tools.ToolUnavailable) as failure:
                list(tools.web_search_steps([{'role':'user','content':'Berita terbaru'}]))
            self.assertEqual(failure.exception.code,'configuration_missing');post.assert_not_called()

    def test_failed_later_research_call_preserves_verified_partial_results(self):
        data=response('Temuan bersumber https://example.test/current')
        with patch.object(tools,'_request',side_effect=[data,tools.ToolUnavailable('Private failure',code='provider_timeout')]) as search:
            result=next(event['result'] for event in tools.web_search_steps(
                [{'role':'user','content':'riset beberapa sumber berita terbaru'}],max_calls=2) if 'result' in event)
        self.assertEqual(search.call_count,2)
        self.assertEqual(result['search_calls'],2)
        self.assertTrue(result['partial'])
        self.assertIn('Sebagian pemeriksaan sumber belum berhasil',result['text'])
        self.assertIn('https://example.test/current',result['text'])
        self.assertNotIn('Private failure',result['text'])

    def test_both_chat_routes_report_timeout_without_a_guessed_answer(self):
        for agent in (False,True):
            with self.subTest(agent=agent),patch.object(tools,'_request',side_effect=tools.ToolUnavailable('Private failure',code='provider_timeout')) as search, \
                    patch.object(providers,'stream',side_effect=AssertionError('No guessed fallback')):
                result=self.submit_chat('Berita terbaru',agent)
                text=agent_store.messages(self.owner,conversation_id=self.conversation)[-1]['content'] if agent else result.get_data(as_text=True)
                self.assertIn('melewati batas waktu',text)
                self.assertIn('belum terverifikasi',text)
                self.assertNotIn('Private failure',text)
                self.assertEqual(search.call_count,1)

    def test_currency_json_wrapping_does_not_accept_extra_prose_or_invalid_provenance(self):
        for raw in ('Here is a guess: '+rate(base='USD'),
                    '```json\n'+rate(base='USD',source_url='https://invented.test/rate')+'\n```',
                    '```json\n'+rate(base='USD',as_of='')+'\n```'):
            with self.subTest(raw=raw),self.assertRaises((ValueError,TypeError)):
                chat_web.conversion_answer(chat_web.conversion('1 USD berapa rupiah'),raw,
                    [{'url':'https://example.test/current'}],tools._source_url)

    def test_news_and_prices_search_without_checkbox(self):
        for agent in (False, True):
            for question in ('Berita ekonomi', 'Harga iPhone 16 berapa?'):
                with self.subTest(agent=agent, question=question), patch.object(tools, '_request', return_value=response('Temuan sintetis dengan sumber.')) as search, \
                        patch.object(providers, 'stream', side_effect=AssertionError('No chat guess')):
                    self.submit_chat(question, agent)
                    self.assertEqual(search.call_count, 1)

    def test_stable_chat_and_no_browse_do_not_call_search(self):
        for agent in (False, True):
            with patch.object(tools, '_request', side_effect=AssertionError('No external search')), \
                    patch.object(providers, 'stream', side_effect=lambda *a, **k: fixture.fixture.answer('Halo!')) as chat:
                self.submit_chat('Halo', agent)
                self.assertEqual(chat.call_count, 1)
                result = self.submit_chat('600 RMB ke IDR, jangan browsing', agent, search='1')
                self.assertEqual(chat.call_count, 1)
                text = agent_store.messages(self.owner, conversation_id=self.conversation)[-1]['content'] if agent else result.get_data(as_text=True)
                self.assertIn('belum terverifikasi', text)
                result = self.submit_chat('kalau 700, jangan search', agent, previous_request='600 RMB ke IDR')
                self.assertEqual(chat.call_count, 1)
                text = agent_store.messages(self.owner, conversation_id=self.conversation)[-1]['content'] if agent else result.get_data(as_text=True)
                self.assertIn('belum terverifikasi', text)
                self.assertNotIn('2300', text)

    def test_invalid_or_missing_currency_evidence_is_not_shown(self):
        cases = [response('600 RMB = Rp1.380.000 dengan kurs perkiraan 2300'),
                 response(rate(source_url='https://unreturned.example/rate')),
                 response(rate(as_of='')), response(rate(base='USD')),
                 response(rate(rate='NaN')), response(rate(rate='-1')),
                 response(rate(rate='1e-999999')), response(rate(rate='12345678901234567890')),
                 response(rate(as_of=(datetime.now(timezone.utc)+timedelta(days=2)).date().isoformat())),
                 response(rate(as_of=(datetime.now(timezone.utc)-timedelta(days=30)).date().isoformat())),
                 response(rate(), sources=False), response(rate(), searched=False)]
        for data in cases:
            with self.subTest(data=data), patch.object(tools, '_request', return_value=data):
                with self.assertRaises(tools.ToolUnavailable):
                    list(tools.web_search_steps([{'role': 'user', 'content': '600 RMB ke IDR'}], verify_currency=True))
        with patch.object(tools, '_request', side_effect=AssertionError('Ambiguous amounts must not search')):
            for prompt in ('-600 RMB ke IDR', '1.234,56 RMB ke IDR', '1e5 RMB ke IDR'):
                with self.subTest(prompt=prompt), self.assertRaises(tools.ToolUnavailable):
                    list(tools.web_search_steps([{'role': 'user', 'content': prompt}], verify_currency=True))

    def test_numeric_currency_followup_fetches_rate_again_and_keeps_evidence_gate(self):
        context = [{'role': 'user', 'content': '600 RMB ke IDR'},
                   {'role': 'assistant', 'content': 'Kurs dugaan 2300, jangan dipercaya.'},
                   {'role': 'user', 'content': 'kalau 700?'}]
        self.assertTrue(routing.fresh_followup('kalau 700?', '600 RMB ke IDR'))
        stamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
        with patch.object(tools, '_request', return_value=response(rate(as_of=stamp))) as search:
            result = next(event['result'] for event in tools.web_search_steps(context, verify_currency=True, minimal_query=True) if 'result' in event)
        self.assertIn('700 CNY', result['text'])
        self.assertIn('1.680.875,00', result['text'])
        self.assertIn(stamp, result['text'])
        self.assertEqual(search.call_count, 1)
        self.assertEqual(search.call_args.args[0]['input'], '700 CNY to IDR: current published exchange rate')
        with patch.object(tools, '_request', return_value=response(rate(as_of=''))):
            with self.assertRaises(tools.ToolUnavailable):
                list(tools.web_search_steps(context, verify_currency=True))

    def test_chat_search_transmits_only_required_query_context(self):
        history = [{'role': 'system', 'content': 'SYSTEM_PRIVATE'},
                   {'role': 'user', 'content': 'USER_PRIVATE'},
                   {'role': 'assistant', 'content': 'ASSISTANT_PRIVATE'}]
        for question in ('Berita ekonomi', 'Harga iPhone 16 berapa?', '600RMB to IDR', '600RMBtoIDR',
                         'Price of iPhone 16: is it discounted today?'):
            context = history + [{'role': 'user', 'content': question +
                "\n\nTeks berikut berhasil diekstrak dari lampiran 'private.pdf'.\nATTACHMENT_PRIVATE"}]
            data = response(rate()) if 'RMB' in question else response('Temuan bersumber.')
            with self.subTest(question=question), patch.object(tools, '_request', return_value=data) as search:
                list(tools.web_search_steps(context, verify_currency=True, minimal_query=True))
                query = search.call_args.args[0]['input']
                self.assertNotIn('PRIVATE', query)
                self.assertEqual(query, '600 CNY to IDR: current published exchange rate' if 'RMB' in question else question)
        context = history + [
            {'role': 'user', 'content': 'Bandingkan Halo AI dan Cekat AI?\nPRIVATE_NOTE'},
            {'role': 'assistant', 'content': 'ASSISTANT_PRIVATE'},
            {'role': 'user', 'content': 'sekarang cari harga terbaru keduanya'}]
        with patch.object(tools, '_request', return_value=response('Temuan bersumber.')) as search:
            list(tools.web_search_steps(context, verify_currency=True, minimal_query=True))
        query = search.call_args.args[0]['input']
        self.assertEqual(query, 'sekarang cari harga terbaru keduanya\nPrevious user question: Bandingkan Halo AI dan Cekat AI?')
        self.assertNotIn('PRIVATE', query)

    def test_provider_failure_and_quota_exhaustion_disclose_unverified(self):
        for agent in (False, True):
            with patch.object(tools, '_request', side_effect=tools.ToolUnavailable('Synthetic failure')), \
                    patch.object(providers, 'stream', side_effect=AssertionError('No chat fallback')):
                result = self.submit_chat('600 RMB berapa rupiah?', agent)
                text = agent_store.messages(self.owner, conversation_id=self.conversation)[-1]['content'] if agent else result.get_data(as_text=True)
                self.assertIn('belum terverifikasi', text)
                self.assertNotIn('1.380.000', text)
            with patch.object(usage, 'reserve', side_effect=usage.UsageLimit('Kuota habis.')), \
                    patch.object(tools, '_request', side_effect=AssertionError('No search beyond quota')):
                result = self.submit_chat('600 RMB berapa rupiah?', agent)
                text = agent_store.messages(self.owner, conversation_id=self.conversation)[-1]['content'] if agent else result.get_data(as_text=True)
                self.assertIn('Kuota habis', text)
                self.assertIn('belum terverifikasi', text)
                if not agent:
                    self.assertEqual(result.status_code, 429)

    def test_all_chat_templates_have_no_search_control(self):
        client = self.client()
        thread = store.create_thread(self.owner)
        for path in ('/products/start', '/kilas-ai', f'/kilas-ai/threads/{thread}',
                     f'/kilas-ai/agent?conversation={self.conversation}'):
            with self.subTest(path=path):
                html = client.get(path, follow_redirects=True).get_data(as_text=True)
                self.assertNotIn('id="ai-search"', html)


if __name__ == '__main__':
    unittest.main()
