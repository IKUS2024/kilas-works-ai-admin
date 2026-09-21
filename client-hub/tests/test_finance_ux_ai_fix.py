"""Focused Finance UX and response-format regressions; offline, disposable SQLite."""
import io
import json
import os
import unittest
from urllib.parse import urlsplit, parse_qs
from html import unescape
import re
from datetime import timedelta
from unittest.mock import patch

import requests
import test_final_product_flow as prior
import test_finance_phase6a as receipt_tests
import finance_ai_safety as safety
import finance_receipts as receipts
import finance_analyst as analyst
import finance_operator as operator


class ProviderJSONTests(unittest.TestCase):
    def parse(self, raw, stop='end_turn'):
        body = {'stop_reason': stop, 'content': [{'type': 'text', 'text': raw}]}
        return safety.json_object(safety.response_text(body, 6000))

    def test_plain_and_one_complete_json_fence(self):
        for raw in (' {"ok":true} ', '```json\n{"ok":true}\n```', ' \n```json\r\n{"ok":true}\r\n```\n'):
            self.assertEqual(self.parse(raw), {'ok': True})

    def test_prose_multiple_objects_duplicate_nonfinite_and_incomplete_rejected(self):
        for raw in ('Here: {"ok":true}', '{} {}', '[]', '```\n{}\n```',
                    '```json\n{}\n``` trailing', 'prefix ```json\n{}\n```',
                    '```json\n{}\n```\n```json\n{}\n```',
                    '{"x":1,"x":2}', '{"x":{"a":1,"a":2}}',
                    '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}',
                    '```json\n{"x":1,"x":2}\n```'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.parse(raw)
        with self.assertRaises(ValueError): self.parse('{}', 'max_tokens')
        with self.assertRaises(ValueError): safety.json_object('```json\n{}\n```')


class FinanceUXTests(unittest.TestCase):
    setUp = prior.FinalFlowTests.setUp
    trial = prior.FinalFlowTests.trial
    snapshot = prior.FinalFlowTests.snapshot
    upload = receipt_tests.ReceiptTests.upload
    token = receipt_tests.ReceiptTests.token
    confirm = receipt_tests.ReceiptTests.confirm
    fields = receipt_tests.ReceiptTests.fields

    def prepare_receipt(self):
        self.trial()
        self.base = self.url + '/receipts'
        result = dict(merchant_name='Toko Contoh', transaction_date='2026-09-17',
                      total_minor=125000, currency='IDR', receipt_number='R-1',
                      description='Belanja kantor', suggested_category_name=self.expense['name'], readable=True)
        self.response.json.return_value = {'stop_reason': 'end_turn', 'content': [dict(type='text', text=json.dumps(result))]}
        return result

    def test_dashboard_one_ai_entry_and_secondary_tools(self):
        self.trial()
        html = self.client.get(self.url).text
        links = [urlsplit(unescape(link)) for link in re.findall(r'href="([^"]+)"', html)]
        self.assertEqual(sum(link.path == self.url + '/assistant' for link in links), 1)
        for text in ('AI Analyst', 'AI Operator', 'Upload File', 'Beta'):
            self.assertNotIn(text, html)
        self.assertIn('Pengaturan Finance', html)
        for suffix in ('reports', 'operations', 'receivables'):
            link = next(link for link in links if link.path == self.url + '/' + suffix)
            self.assertEqual(parse_qs(link.query)['branch_id'], [str(__import__('finance_branches').list_branches(self.b)[0]['id'])])

    def test_assistant_keeps_existing_engines_and_routes(self):
        self.trial()
        page = self.client.get(self.url + '/assistant')
        self.assertEqual(page.status_code, 200)
        for suffix in ('assistant/message', 'assistant/review', 'assistant/recognize', 'assistant/document'):
            self.assertIn(self.url + '/' + suffix, page.text)
        for mode, filename, workflow in (('ask', None, 'READ_ONLY_ANALYSIS'),
                ('record', None, 'TEXT_OPERATOR'), ('receipt', 'a.png', 'RECEIPT'),
                ('bank', 'a.pdf', 'BANK_STATEMENT'), ('auto', 'a.csv', 'BANK_STATEMENT')):
            response = self.client.post(self.url + '/assistant/route', json={'mode': mode, 'text': '', 'files': [{'name': filename}] if filename else []})
            self.assertEqual(response.json['workflow'], workflow)
        self.http.assert_not_called()

    def test_period_dropdown_canonical_query_and_persistence(self):
        for year, month in (('2024', '02'), ('2025', '12'), ('1999', '01')):
            response = self.client.get(self.url, query_string={'period_year': year, 'period_month': month, 'direction': 'EXPENSE'})
            self.assertEqual(response.status_code, 302)
            self.assertIn('month=' + year + '-' + month, response.location)
            self.assertIn('direction=EXPENSE', response.location)
            html = self.client.get(response.location).text
            self.assertIn('value="' + month + '" selected', html)
            self.assertIn('value="' + year + '" selected', html)
            self.assertNotIn('type="month"', html)
            self.assertIn('Februari', html)
        html = self.client.get(self.url + '?month=1980-03').text
        self.assertIn('value="1980" selected', html)

    def test_invalid_split_period_rejected_without_changing_data(self):
        before = self.snapshot()
        for query in ({'period_year': '2026'}, {'period_year': '2026', 'period_month': '13'},
                      {'period_year': '0000', 'period_month': '01'}, {'period_year': 'evil', 'period_month': '01'}):
            location = urlsplit(self.client.get(self.url, query_string=query).location)
            self.assertEqual(location.path, self.url)
            self.assertEqual(parse_qs(location.query)['branch_id'], [str(__import__('finance_branches').list_branches(self.b)[0]['id'])])
        self.assertEqual(before, self.snapshot())

    def test_period_mobile_shrink_and_stack_rules(self):
        html = self.client.get(self.url).text
        self.assertIn('.finance-filter>div{flex:1 1 140px;min-width:0}', html)
        self.assertIn('.finance-filter select{width:100%;box-sizing:border-box}', html)
        self.assertIn('@media', html);self.assertIn('min-width:0',html)

    def test_dashboard_currency_chart_and_recent_activity(self):
        fxmock=patch('finance_fx.snapshot',return_value={'rates':{'IDR':'1','USD':'16000'},'date':'2026-09-20','source':'test','stale':False});fxmock.start();self.addCleanup(fxmock.stop)
        self.trial()
        finance = __import__('finance_service')
        income = finance.list_categories(self.b, 'INCOME')[0]
        finance.create_transaction(self.b, 'INCOME', 2200000, self.a, income['id'], '2026-09-17',
            description='Jasa foto', actor_user_id=self.uid)
        usd_account = finance.create_account(self.b, 'BOFA', currency='USD', actor_user_id=self.uid)
        finance.create_transaction(self.b, 'INCOME', 1500, usd_account, income['id'], '2026-09-17',
            currency='USD', description='USD client payment', actor_user_id=self.uid)
        html = self.client.get(self.url + '?month=2026-09').text
        self.assertIn('finance-trend-currency', html)
        self.assertIn('Lihat semua', html)
        self.assertIn('Jasa foto', html)
        self.assertIn('USD client payment', html)
        self.assertIn('finance-trend-data', html)
        self.assertLessEqual(html.count('class="finance-history-row"'), 5)

    def test_transaction_history_is_all_time_and_paginated_ten_per_page(self):
        self.trial()
        finance = __import__('finance_service')
        income = finance.list_categories(self.b, 'INCOME')[0]
        for index in range(23):
            finance.create_transaction(self.b, 'INCOME', 100000 + index, self.a, income['id'], '2026-09-17',
                description=f'PAGED-{index:02d}', actor_user_id=self.uid)
        summary = self.client.get(self.url + '?month=2026-09').text
        full_links = [urlsplit(unescape(link)) for link in re.findall(r'href="([^"]+)"', summary)]
        history = next(link for link in full_links if parse_qs(link.query).get('view') == ['transactions']
                       and parse_qs(link.query).get('period_mode') == ['all'])
        self.assertEqual(parse_qs(history.query).get('page'), ['1'])

        page1 = self.client.get(history.geturl()).text
        self.assertIn('23 transaksi', page1)
        self.assertIn('10 per halaman', page1)
        self.assertNotIn('Kilas Finance</h1>', page1)
        self.assertNotIn('Arus Kas Periode', page1)
        self.assertNotIn('Pengaturan Finance', page1)
        self.assertNotIn('Pilih yang mau dikerjakan', page1)
        self.assertNotIn('Uang Tersedia', page1)
        self.assertIn('PAGED-22', page1)
        self.assertNotIn('PAGED-00', page1)
        links1 = [urlsplit(unescape(link)) for link in re.findall(r'href="([^"]+)"', page1)]
        pages1 = {parse_qs(link.query).get('page', [''])[0] for link in links1
                  if parse_qs(link.query).get('view') == ['transactions']}
        self.assertTrue({'1','2','3'}.issubset(pages1))

        page3 = self.client.get(self.url, query_string={'period_mode':'all','view':'transactions','page':'3'}).text
        self.assertIn('PAGED-00', page3)
        self.assertIn('Halaman 3 dari 3', page3)
        self.assertNotIn('PAGED-22', page3)

    def test_receipt_fenced_success_populates_review_without_write_and_confirms_once(self):
        result = self.prepare_receipt()
        self.response.json.return_value['content'][0]['text'] = '```json\n' + json.dumps(result) + '\n```'
        before = self.snapshot()
        with self.assertLogs('kilas.finance_ai', level='INFO') as logs:
            response = self.upload()
        self.assertIn('receipt_reason=success', ' '.join(logs.output))
        token = self.token(response)
        for value in ('Review Hasil', 'value="Toko Contoh"', 'value="2026-09-17"', 'value="125000"', 'Belanja kantor', self.expense['name']):
            self.assertIn(value, response.text)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.confirm(token).status_code, 302)
        self.assertEqual(self.confirm(token).status_code, 302)
        self.assertEqual(len(__import__('finance_service').list_transactions(self.b)), 1)
        self.assertEqual(self.http.call_count, 1)

    def test_receipt_unreadable_safe_message(self):
        self.prepare_receipt()
        self.response.json.return_value['content'][0]['text'] = json.dumps(receipts.empty_result())
        before = self.snapshot()
        with self.assertLogs('kilas.finance_ai', level='INFO') as logs:
            response = self.upload()
        self.assertIn(receipts.READ_ERROR, response.text)
        self.assertIn('Foto / pilih struk lagi', response.text)
        self.assertIn('receipt_reason=unreadable', ' '.join(logs.output))
        self.assertEqual(before, self.snapshot())

    def test_receipt_claimed_readable_but_empty_shows_unreadable_message(self):
        self.prepare_receipt()
        empty = receipts.empty_result()
        empty.update(readable=True, currency='IDR')
        self.response.json.return_value['content'][0]['text'] = json.dumps(empty)
        with self.assertLogs('kilas.finance_ai', level='INFO') as logs:
            response = self.upload()
        self.assertIn(receipts.READ_ERROR, response.text)
        self.assertIn('receipt_reason=unreadable', ' '.join(logs.output))
        self.assertEqual(__import__('finance_service').list_transactions(self.b), [])

    def test_receipt_provider_diagnostics_are_bounded_no_retry_no_leaks(self):
        self.prepare_receipt()
        cases = [(500, None, 'upstream_failure'), (429, None, 'rate_limited'),
                 (200, requests.Timeout('SECRET_PROVIDER_PAYLOAD'), 'timeout'),
                 (200, requests.ConnectionError('SECRET_PROVIDER_PAYLOAD'), 'network_failure')]
        before = self.snapshot()
        for code, error, reason in cases:
            self.response.status_code = code
            self.http.side_effect = error
            self.http.reset_mock()
            with self.assertLogs('kilas.finance_ai', level='INFO') as logs:
                response = self.upload()
            self.assertIn(receipts.READ_ERROR, response.text)
            self.assertIn('receipt_reason=' + reason, ' '.join(logs.output))
            self.assertNotIn('SECRET_PROVIDER_PAYLOAD', response.text + ' '.join(logs.output))
            self.assertNotIn('test-receipt-key', response.text + ' '.join(logs.output))
            self.assertEqual(self.http.call_count, 1)
        self.assertEqual(before, self.snapshot())

    def test_receipt_not_configured_and_quota_messages(self):
        self.prepare_receipt()
        with patch.dict(os.environ, ANTHROPIC_API_KEY=''), self.assertLogs('kilas.finance_ai', level='INFO') as logs:
            response = self.upload()
        self.assertIn('receipt_reason=not_configured', ' '.join(logs.output))
        self.assertIn(receipts.READ_ERROR, response.text)
        with patch.object(safety, 'allow_attempt', return_value=False), self.assertLogs('kilas.finance_ai', level='INFO') as logs:
            response = self.upload()
        self.assertIn('receipt_reason=rate_limited', ' '.join(logs.output))
        self.assertIn(receipts.READ_ERROR, response.text)
        self.http.assert_not_called()

    def test_receipt_invalid_json_and_schema_fail_safely(self):
        self.prepare_receipt()
        before = self.snapshot()
        for raw in ('SECRET_PROVIDER_PAYLOAD', '{"readable":true,"readable":false}',
                    '```json\n{"readable":true}\n```', '{"total_minor":NaN}'):
            self.response.json.return_value['content'][0]['text'] = raw
            with self.assertLogs('kilas.finance_ai', level='INFO') as logs:
                response = self.upload()
            self.assertIn(receipts.READ_ERROR, response.text)
            self.assertIn('receipt_reason=invalid_result', ' '.join(logs.output))
            self.assertNotIn('SECRET_PROVIDER_PAYLOAD', response.text + ' '.join(logs.output))
        self.assertEqual(before, self.snapshot())

    def test_receipt_tenant_and_expired_entitlement_preserved(self):
        self.prepare_receipt()
        self.assertEqual(self.client.post(f'/business/{self.other}/finance/receipts/analyze', data={'receipt': (io.BytesIO(self.raw), 'a.png')}).status_code, 404)
        self.time.return_value += timedelta(days=7)
        self.assertIn(self.upload().status_code, (302, 303))
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.http.assert_not_called()

    def test_analyst_fenced_response_and_safe_failure(self):
        self.trial()
        self.response.json.return_value = {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': '```json\n' + json.dumps({'observations': [{'text': 'Pemasukan tercatat.', 'refs': ['f1']}], 'suggestions': []}) + '\n```'}]}
        payload = {'question': 'Bagaimana laporan?', 'month': '2026-09', 'scope': 'summary'}
        before = self.snapshot()
        response = self.client.post(self.url + '/analyst', json=payload)
        self.assertEqual(response.status_code, 200)
        self.response.status_code = 500
        self.response.text = 'SECRET_PROVIDER_PAYLOAD'
        with self.assertLogs('kilas.finance_ai', level='INFO') as logs:
            response = self.client.post(self.url + '/analyst', json=payload)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json['error'], analyst.ERROR)
        self.assertIn('Laporan & Export', response.json['error'])
        self.assertNotIn('SECRET_PROVIDER_PAYLOAD', response.text + ' '.join(logs.output))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.http.call_count, 2)

    def test_operator_fenced_response_preserves_grounding(self):
        self.response.json.return_value = {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': '```json\n' + json.dumps({'action': 'create_expense', 'amount_text': '300 ribu', 'description': 'bensin'}) + '\n```'}]}
        result = operator.interpret('create_expense', 'catat bensin 300 ribu','IDR')
        self.assertEqual(result, {'amount_minor': 300000, 'description': 'bensin'})


if __name__ == '__main__':
    unittest.main()
