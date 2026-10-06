"""Synthetic-only observation acceptance; no uploads, provider calls or real clock assumptions."""
import unittest
import io
import json
from datetime import timedelta
from unittest.mock import patch
from datetime import datetime, timezone
import test_kilas_trading as f
from kilas_trading import observation, analysis, engine, store


def observation_fixture():
    receipt = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    raw = int(receipt.timestamp()) + 3*3600 # Deliberately ambiguous; not a broker-clock assertion.
    return dict(kind='TEST_FIXTURE', source_symbol='GOLD', bid='2500.10', ask='2500.30',
                time=raw, time_msc=raw*1000+123, observed_at_utc=receipt.isoformat())


def demo_upload():
    raw = dict(observation_fixture(), kind='DEMO', schema_version=1, timeframe='M1')
    raw['candles'] = [dict(time=raw['time']-60*(2-i), open='2500.00', high='2501.00', low='2499.00', close='2500.20') for i in range(3)]
    return raw


class ObservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not hasattr(f.TradingTests, 'user'): f.TradingTests.setUpClass()

    def setUp(self):
        self.base = f.TradingTests('test_xauusd_contract_and_units')
        self.base.setUp(); self.addCleanup(self.base.doCleanups)
        f.app.app.config.update(TESTING=True)
        self.addCleanup(lambda: f.app.app.config.pop('KILAS_TRADING_OBSERVATION_FIXTURE', None))
        self.context = f.app.app.app_context(); self.context.push(); self.addCleanup(self.context.pop)

    def test_preserves_raw_future_epoch_without_normalizing(self):
        raw = observation_fixture(); result = observation.validate_fixture(raw)
        for field in observation.FIELDS: self.assertEqual(result[field], raw[field])
        self.assertIsNone(result['event_time_utc'])
        self.assertEqual(result['source_time_status'], 'unverified')
        self.assertEqual(result['freshness'], 'unknown')
        for flag in ('ai_analysis', 'paper_execution', 'ingestion_enabled'): self.assertIs(result[flag], False)
        self.assertEqual(raw, observation_fixture()) # No mutation of evidence.

    def test_receipt_is_never_quote_freshness(self):
        for receipt in ('2001-01-01T00:00:00Z', '2099-01-01T00:00:00Z'):
            result = observation.validate_fixture(dict(observation_fixture(), observed_at_utc=receipt))
            self.assertEqual(result['freshness'], 'unknown'); self.assertIsNone(result['event_time_utc'])

    def test_mapping_is_unknown_even_for_lookalike_canonical_symbol(self):
        for symbol in ('GOLD', 'GOLD.', 'XAUUSD'):
            result = observation.validate_fixture(dict(observation_fixture(), source_symbol=symbol))
            self.assertIsNone(result['canonical_symbol']); self.assertEqual(result['mapping_status'], 'unknown')

    def test_extra_private_fields_and_capability_claims_rejected(self):
        for field, value in {'account_id':'fixture', 'balance':1000, 'positions':[], 'password':'fixture',
                             'credential':'fixture', 'event_time_utc':'verified', 'freshness':'fresh',
                             'ai_analysis':True, 'paper_execution':True, 'canonical_symbol':'XAUUSD'}.items():
            with self.assertRaises(engine.TradingError):
                observation.validate_fixture(dict(observation_fixture(), **{field:value}))

    def test_invalid_values_and_real_source_rejected(self):
        changes = ({'kind':'DEMO'}, {'kind':'REAL'}, {'source_symbol':'<script>'}, {'bid':'NaN'},
                   {'ask':'Infinity'}, {'bid':'-1'}, {'bid':2500.1}, {'ask':'1'}, {'time':True},
                   {'time':0}, {'time_msc':1}, {'observed_at_utc':'2026-10-06T12:00:00'},
                   {'observed_at_utc':'2026-10-06T15:00:00+03:00'})
        for change in changes:
            with self.assertRaises(engine.TradingError): observation.validate_fixture(dict(observation_fixture(), **change))

    def test_production_ignores_even_configured_fixture(self):
        f.app.app.config['KILAS_TRADING_OBSERVATION_FIXTURE'] = observation_fixture()
        f.app.app.config['TESTING'] = False
        try:
            with self.assertRaises(engine.TradingError): observation.validate_fixture(observation_fixture())
            self.assertEqual(observation.view()['outcome'], 'UNAVAILABLE')
            self.assertNotIn('time', observation.view())
        finally: f.app.app.config['TESTING'] = True

    def test_observation_cannot_enter_analyst_or_paper_route(self):
        raw = observation_fixture()
        with self.assertRaises(engine.TradingError): analysis.validate_snapshot(observation.validate_fixture(raw))
        store.snapshot(self.base.user)
        before = f.db.query_all('SELECT * FROM kilas_trading_events')
        for action in ('order', 'analyze', 'observe'):
            response = self.base.client.post('/products/services/trading/'+action, json=raw, headers={'X-CSRF-Token':'paper-csrf'})
            self.assertEqual(response.status_code, 409); self.assertEqual(response.json['outcome'], 'REJECTED')
        self.assertEqual(f.db.query_all('SELECT * FROM kilas_trading_events'), before)
        self.assertEqual(f.db.query_one('SELECT count(*) AS n FROM kilas_trading_positions')['n'], 0)

    def test_pilot_fixture_ui_and_rejected_or_missing_states(self):
        store.snapshot(self.base.user)
        baseline = f.db.query_all('SELECT * FROM kilas_trading_events')
        f.app.app.config['KILAS_TRADING_OBSERVATION_FIXTURE'] = observation_fixture()
        page = self.base.client.get('/products/services/trading')
        self.assertEqual(page.status_code, 200)
        for text in ('OBSERVATION_ONLY', 'TEST FIXTURE SINTETIS', 'freshness unknown', 'GOLD', 'Raw time_msc', 'null · belum diketahui'):
            self.assertIn(text, page.text)
        self.assertEqual(self.base.login(self.base.other).get('/products/services/trading').status_code, 404)
        self.assertEqual(f.db.query_all('SELECT * FROM kilas_trading_events'), baseline)
        f.app.app.config['KILAS_TRADING_OBSERVATION_FIXTURE'] = dict(observation_fixture(), account_id='not-allowed')
        self.assertEqual(observation.view()['outcome'], 'REJECTED')
        f.app.app.config.pop('KILAS_TRADING_OBSERVATION_FIXTURE')
        self.assertEqual(observation.view()['outcome'], 'UNAVAILABLE')

    def upload(self, raw=None, content=None, client=None, csrf=True):
        data = {'observation':(io.BytesIO(content if content is not None else json.dumps(raw or demo_upload()).encode()), 'ignored-path.json')}
        if csrf: data['csrf_token'] = 'paper-csrf'
        return (client or self.base.client).post('/products/services/trading/observations/upload', data=data, headers={'Accept':'application/json'})

    def test_upload_persists_market_only_without_execution(self):
        result = self.upload(); self.assertEqual(result.status_code, 200)
        saved = observation.view(self.base.user)
        for key in ('time', 'time_msc', 'observed_at_utc'): self.assertEqual(saved[key], demo_upload()[key])
        self.assertEqual(saved['candles'], demo_upload()['candles'])
        self.assertIsNone(saved['event_time_utc']); self.assertIsNone(saved['canonical_symbol'])
        self.assertFalse(saved['ai_analysis']); self.assertFalse(saved['paper_execution'])
        self.assertEqual(saved['freshness'], 'unknown')
        self.assertEqual(f.db.query_one('SELECT count(*) AS n FROM kilas_trading_positions')['n'], 0)
        self.assertEqual(f.db.query_one("SELECT count(*) AS n FROM kilas_trading_events WHERE action='AI_ANALYSIS'")['n'], 0)
        page = self.base.client.get('/products/services/trading')
        self.assertIn('sumber dinyatakan DEMO', page.text); self.assertIn('3 candle mentah', page.text)
        self.assertIn('Diterima server UTC', page.text)

    def test_upload_gate_and_csrf(self):
        self.assertEqual(self.upload(csrf=False).status_code, 400)
        for who in (self.base.other, self.base.admin): self.assertEqual(self.upload(client=self.base.login(who)).status_code, 404)
        self.assertEqual(self.upload(client=f.app.app.test_client()).status_code, 400) # Existing global CSRF runs before login.
        with patch.dict('os.environ', {'KILAS_TRADING_OBSERVATION_ENABLED':'false'}):
            self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(f.db.query_one('SELECT count(*) AS n FROM kilas_trading_events')['n'], 0)

    def test_upload_dedup_rate_limit_and_one_snapshot_retention(self):
        now = store.now()
        with patch.object(store, 'now', return_value=now):
            self.assertEqual(self.upload().status_code, 200)
            self.assertTrue(self.upload().json['duplicate'])
            changed = dict(demo_upload(), bid='2500.11')
            self.assertEqual(self.upload(changed).status_code, 409)
        with patch.object(store, 'now', return_value=now+timedelta(seconds=31)):
            self.assertEqual(self.upload(changed).status_code, 200)
        self.assertEqual(observation.view(self.base.user)['bid'], '2500.11')
        self.assertEqual(f.db.query_one("SELECT count(*) AS n FROM kilas_trading_events WHERE action=?", (observation.ACTION,))['n'], 1)

    def test_upload_rejects_private_unknown_real_and_fixture_fields(self):
        for raw in (dict(demo_upload(), balance='1'), dict(demo_upload(), account_id='fixture'), dict(demo_upload(), kind='REAL'),
                    dict(demo_upload(), source_symbol='XAUUSD'), dict(demo_upload(), event_time_utc='verified'), observation_fixture()):
            self.assertEqual(self.upload(raw).status_code, 409)
        self.assertEqual(f.db.query_one('SELECT count(*) AS n FROM kilas_trading_events')['n'], 0)

    def test_upload_bytes_json_duplicates_and_candle_validation(self):
        for content in (b'', b'\xff', b'{', b'[]', b'{"kind":"DEMO","kind":"REAL"}', b'x'*8193):
            self.assertEqual(self.upload(content=content).status_code, 409)
        self.assertEqual(self.upload(content=b'x'*17000).status_code, 413)
        for change in ({'candles':[]}, {'candles':demo_upload()['candles']*17}, {'timeframe':'H1'}, {'candles':[dict(demo_upload()['candles'][0], balance='1')]},
                       {'candles':[dict(demo_upload()['candles'][0], high='1')]}, {'candles':[dict(demo_upload()['candles'][0], open='NaN')]}):
            self.assertEqual(self.upload(dict(demo_upload(), **change)).status_code, 409)
        tick = demo_upload(); tick.pop('timeframe'); tick.pop('candles')
        self.assertEqual(self.upload(tick).status_code, 200)

    def test_upload_concurrent_duplicate_does_not_create_multiple_records(self):
        from concurrent.futures import ThreadPoolExecutor
        content = json.dumps(demo_upload()).encode()
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: observation.ingest(self.base.user, content), range(3)))
        self.assertEqual(sum(not r['duplicate'] for r in results), 1)
        self.assertEqual(f.db.query_one("SELECT count(*) AS n FROM kilas_trading_events WHERE action=?", (observation.ACTION,))['n'], 1)

    def test_upload_does_not_authorize_analysis_or_observation_orders(self):
        self.assertEqual(self.upload().status_code, 200)
        with self.assertRaises(engine.TradingError): analysis.validate_snapshot(observation.view(self.base.user))
        self.assertIsNone(analysis.market_source)
        response = self.base.client.post('/products/services/trading/order', json=demo_upload(), headers={'X-CSRF-Token':'paper-csrf'})
        self.assertIn(response.status_code, (400, 409))
        self.assertEqual(f.db.query_one('SELECT count(*) AS n FROM kilas_trading_positions')['n'], 0)


if __name__ == '__main__': unittest.main(verbosity=2)
