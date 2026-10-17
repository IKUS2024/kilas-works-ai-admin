"""Shared Chat FX evidence validation; synthetic HTTP and no DB/provider IO."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kilas_ai import chat_web, tools


class ChatRateEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.spec = chat_web.conversion('1 sgd berapa rupiah')
        self.now = datetime.now(timezone.utc)
        self.source = 'https://example.test/current'
        self.data = {'base': 'SGD', 'quote': 'IDR', 'rate': '14107.80',
                     'as_of': self.now.date().isoformat(), 'source_url': self.source}
        self.citations = [{'url': self.source, 'title': 'Synthetic dated rate'}]
        self.usage = {'input_tokens': 9291, 'output_tokens': 278}

    def answer(self, data):
        return chat_web.conversion_answer(self.spec, json.dumps(data), self.citations, tools._source_url, now=self.now)

    def payload(self, data):
        return {'status': 'completed', 'max_tool_calls': 1, 'usage': deepcopy(self.usage), 'output': [
            {'type': 'web_search_call', 'status': 'completed', 'action': {
                'type': 'search', 'sources': [{'type': 'url', 'url': self.source}]}},
            {'type': 'message', 'status': 'completed', 'content': [{'type': 'output_text',
                'text': json.dumps(data), 'annotations': [{'type': 'url_citation', 'url': self.source}]}]}]}

    def lookup(self, data):
        with patch.dict(os.environ, {'KILAS_AI_OPENAI_WEB_MODEL': 'gpt-6.1-sol'}), \
             patch.object(tools, '_request', return_value=self.payload(data)) as request:
            events = list(tools.web_search_steps([{'role': 'user', 'content': '1 sgd berapa rupiah'}],
                verify_currency=True, minimal_query=True, max_calls=1))
        request.assert_called_once()
        self.assertEqual(request.call_args.args[0]['input'], '1 SGD to IDR: current published exchange rate')
        self.assertEqual(request.call_args.args[0]['max_tool_calls'], 1)
        return events[-1]['result']

    def test_unambiguous_grouped_rates_match_the_canonical_value_exactly(self):
        expected = self.answer(self.data)
        for rate in ('14,107.80', '14.107,80'):
            with self.subTest(rate=rate):
                self.assertEqual(self.answer({**self.data, 'rate': rate}), expected)
        direct_decimal = self.answer({**self.data, 'rate': '14.107'})
        self.assertIn('1 SGD ≈ Rp14,11', direct_decimal)
        self.assertNotIn('Rp14.107,00', direct_decimal)

    def test_actual_adapter_keeps_one_lookup_usage_citations_and_source_date(self):
        for rate in ('14107.80', '14,107.80', '14.107,80'):
            with self.subTest(rate=rate):
                result = self.lookup({**self.data, 'rate': rate})
                self.assertIn('1 SGD ≈ Rp14.107,80', result['text'])
                self.assertIn('Waktu sumber: '+self.data['as_of'], result['text'])
                self.assertEqual(result['citations'][0]['url'], self.source)
                self.assertEqual(result['search_calls'], 1)
                self.assertEqual(result['usage']['input_tokens'], self.usage['input_tokens'])
                self.assertEqual(result['usage']['output_tokens'], self.usage['output_tokens'])

    def test_ambiguous_or_invalid_rates_are_not_reinterpreted(self):
        rates = ('14,107', '14107,80', '14,10.80', '14.10,80', '1,41,107.80', '1.41.107,80',
                 '14,107.80.0', '14.107,80,0', 'Rp14.107,80', '14,107.80 IDR', '14 107,80',
                 ' 14,107.80 ', '-14,107.80', '+14.107,80', 'NaN', 'Infinity', '1e4', '1e-999999',
                 '0,000.00', '0.000,00', '1,000,000,000,000.01', '1.000.000.000.000,01',
                 '14,107.1234567890123', '14.107,1234567890123', '1,'+'000,'*22+'000.00')
        for rate in rates:
            with self.subTest(rate=rate), self.assertRaisesRegex(ValueError, '^rate_invalid$'):
                self.answer({**self.data, 'rate': rate})

    def test_grouped_format_cannot_bypass_pair_freshness_or_source_gates(self):
        cases = (({'base': 'USD'}, 'currency_pair_missing'),
                 ({'as_of': ''}, 'rate_time_missing'),
                 ({'as_of': (self.now-timedelta(days=8)).date().isoformat()}, 'rate_not_current'),
                 ({'as_of': (self.now+timedelta(days=2)).date().isoformat()}, 'rate_not_current'),
                 ({'source_url': 'https://unreturned.example/rate'}, 'search_uncited_url'),
                 ({'source_url': None}, 'rate_source_missing'))
        for changes, code in cases:
            with self.subTest(code=code), patch.dict(os.environ, {'KILAS_AI_OPENAI_WEB_MODEL': 'gpt-6.1-sol'}), \
                 patch.object(tools, '_request', return_value=self.payload({**self.data, 'rate': '14,107.80', **changes})) as request:
                with self.assertRaises(tools.ToolUnavailable) as error:
                    list(tools.web_search_steps([{'role': 'user', 'content': '1 sgd berapa rupiah'}],
                        verify_currency=True, minimal_query=True, max_calls=1))
                self.assertEqual(error.exception.code, code)
                self.assertEqual(error.exception.usage['input_tokens'], self.usage['input_tokens'])
                self.assertEqual(error.exception.usage['output_tokens'], self.usage['output_tokens'])
                request.assert_called_once()

    def test_invalid_rate_message_explains_validation_without_guessing_an_outage(self):
        message = chat_web.search_failure_message(tools.ToolUnavailable('PRIVATE', code='rate_invalid'))
        self.assertIn('Nilai kurs', message)
        self.assertIn('belum dapat divalidasi', message)
        self.assertIn('belum terverifikasi', message)
        self.assertNotIn('koneksi', message.lower())
        self.assertNotIn('PRIVATE', message)


if __name__ == '__main__': unittest.main()
