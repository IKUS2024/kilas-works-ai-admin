"""Mocked public FX, display-only IDR, unchanged ledger and admin authorization."""
import copy
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import Mock, patch
import requests
import test_single_plan_release as f
import ai_usage_fx as fx

class FXTests(unittest.TestCase):
    def setUp(self):
        self.fixture=f.SinglePlanTests();self.fixture.setUp()
        self.client=self.fixture.client;self.uid=self.fixture.uid
        f.db.execute("UPDATE users SET role='KILAS_ADMIN' WHERE id=?",(self.uid,))
        fx._cached=None;fx._expires=0
        self.network=patch('requests.sessions.Session.request',side_effect=AssertionError('no real HTTP'))
        self.network.start();self.addCleanup(self.network.stop)
        self.response=Mock(status_code=200)
        self.response.json.return_value={'date':'2026-01-02','base':'USD','quote':'IDR','rate':16000.25}
        self.http=patch.object(fx.requests,'get',return_value=self.response)
        self.get=self.http.start();self.addCleanup(self.http.stop)

    def test_valid_pair_date_source_and_30_minute_cache(self):
        with patch.dict(os.environ,{'FX_API_KEY':'','AI_COST_USD_IDR':''}),patch.object(fx.time,'monotonic',return_value=100):
            rate=fx.get_usd_idr();second=fx.get_usd_idr()
        self.assertEqual(rate,{'rate':Decimal('16000.25'),'date':'2026-01-02','source':'Frankfurter v2'})
        self.assertEqual(rate,second);self.assertIsNot(rate,second)
        self.get.assert_called_once_with(fx.URL,timeout=2,allow_redirects=False)
        self.assertEqual(fx._expires,100+1800)
        self.response.close.assert_called_once()

    def test_expiry_refreshes_once(self):
        with patch.object(fx.time,'monotonic',return_value=100):fx.get_usd_idr()
        with patch.object(fx.time,'monotonic',return_value=1899):fx.get_usd_idr()
        self.assertEqual(self.get.call_count,1)
        self.response.json.return_value['rate']=16500
        with patch.object(fx.time,'monotonic',return_value=1900):
            self.assertEqual(fx.get_usd_idr()['rate'],Decimal('16500'))
        self.assertEqual(self.get.call_count,2)

    def test_concurrent_refresh_has_one_http_request(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:fx.get_usd_idr(),range(8)))
        self.assertTrue(all(r==results[0] for r in results));self.get.assert_called_once()

    def test_http_and_network_failure_negative_cached(self):
        for error in (requests.Timeout('SECRET'),requests.ConnectionError('PRIVATE')):
            fx._cached=None;fx._expires=0;self.get.reset_mock();self.get.side_effect=error
            with self.assertLogs('ai_usage_fx',level='WARNING') as logs:
                self.assertIsNone(fx.get_usd_idr());self.assertIsNone(fx.get_usd_idr())
            self.get.assert_called_once();self.assertEqual(len(logs.output),1)
            self.assertNotIn('SECRET',' '.join(logs.output));self.assertNotIn('PRIVATE',' '.join(logs.output))
        self.get.side_effect=None
        for status in (301,429,500):
            fx._expires=0;self.response.status_code=status
            self.assertIsNone(fx.get_usd_idr())

    def test_malformed_json_pair_rate_and_date_rejected(self):
        valid={'date':'2026-01-02','base':'USD','quote':'IDR','rate':16000}
        cases=[None,[],{},dict(valid,base='EUR'),dict(valid,quote='USD')]
        cases += [dict(valid,rate=v) for v in (0,-1,True,'16000',float('nan'),float('inf'))]
        cases += [dict(valid,date=v) for v in ('bad','2026-02-30',None)]
        for data in cases:
            fx._expires=0;self.response.json.return_value=data
            self.assertIsNone(fx.get_usd_idr())
        fx._expires=0;self.response.json.side_effect=ValueError('RAW_RESPONSE')
        self.assertIsNone(fx.get_usd_idr())

    def test_failed_refresh_does_not_show_expired_rate(self):
        fx.get_usd_idr();fx._expires=0
        self.get.side_effect=requests.Timeout()
        self.assertIsNone(fx.get_usd_idr());self.assertIsNone(fx._cached)

    def test_conversion_copies_rows_ignores_historical_idr(self):
        rows=[{'cost_usd':Decimal('2.5'),'cost_idr':999,'reference_revenue_idr':499000,'gross_contribution_idr':123}]
        before=copy.deepcopy(rows)
        output=fx.display_rows(rows,{'rate':Decimal('16000')})
        self.assertEqual(rows,before);self.assertEqual(output[0]['display_cost_idr'],Decimal('40000'))
        self.assertEqual(output[0]['display_contribution_idr'],Decimal('459000'))
        self.assertEqual(output[0]['cost_idr'],999)

    def test_unknown_usd_missing_rate_and_platform_revenue(self):
        for usd in (None,float('nan'),'bad'):
            self.assertIsNone(fx.display_rows([{'cost_usd':usd}],{'rate':Decimal('16000')})[0]['display_cost_idr'])
        self.assertIsNone(fx.display_rows([{'cost_usd':10,'cost_idr':123}],None)[0]['display_cost_idr'])
        row=fx.display_rows([{'cost_usd':0,'reference_revenue_idr':None}],{'rate':Decimal('16000')})[0]
        self.assertEqual(row['display_cost_idr'],0);self.assertIsNone(row['display_contribution_idr'])

    def test_dashboard_renders_fx_and_preserves_entire_ledger(self):
        with patch.dict(os.environ,{'AI_COST_USD_IDR':'2'}):self.fixture.usage()
        before=f.db.query_all('SELECT * FROM ai_usage_ledger ORDER BY id')
        usd=f.ai_usage.monthly(self.fixture.bid)[0]['cost_usd']
        response=self.client.get('/admin/ai-usage');body=response.get_data(as_text=True)
        self.assertEqual(response.status_code,200)
        self.assertIn(f'Estimasi USD: {usd:.6f}',body)
        self.assertIn(f"Estimasi IDR: {Decimal(str(usd))*Decimal('16000.25'):.0f}",body)
        for text in ('Kurs acuan USD/IDR','16000.25','2026-01-02','Frankfurter v2','Pendapatan referensi IDR: 499000'):
            self.assertIn(text,body)
        self.client.get('/admin/ai-usage');self.get.assert_called_once()
        self.assertEqual(before,f.db.query_all('SELECT * FROM ai_usage_ledger ORDER BY id'))

    def test_outage_keeps_200_and_usd_without_idr(self):
        self.fixture.usage();self.get.side_effect=requests.Timeout()
        response=self.client.get('/admin/ai-usage');body=response.get_data(as_text=True)
        self.assertEqual(response.status_code,200)
        self.assertIn('Estimasi USD:',body);self.assertIn('Estimasi IDR: Tidak tersedia',body)
        self.assertIn('Kurs acuan USD/IDR: Tidak tersedia',body)

    def test_client_and_database_failure_never_fetch_fx(self):
        f.db.execute("UPDATE users SET role='CLIENT_OWNER' WHERE id=?",(self.uid,))
        self.assertEqual(self.client.get('/admin/ai-usage').status_code,403)
        self.assertEqual(f.app.app.test_client().get('/admin/ai-usage').status_code,302)
        f.db.execute("UPDATE users SET role='KILAS_ADMIN' WHERE id=?",(self.uid,))
        with patch.object(f.ai_usage,'monthly',side_effect=RuntimeError('fixture')):
            self.assertEqual(self.client.get('/admin/ai-usage').status_code,503)
        self.get.assert_not_called()

if __name__=='__main__':unittest.main()
