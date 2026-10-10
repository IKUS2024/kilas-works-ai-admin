"""Offline rejecting-boundary tests; no collector, SDK, NTP or model calls."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kilas_trading import analysis, observation, producer


def candidate():
    # Synthetic documentation values in the existing upload contract.
    return {'schema_version': 1, 'kind': 'DEMO', 'source_symbol': 'GOLD',
            'bid': '2500.10', 'ask': '2500.30', 'time': 1791298800,
            'time_msc': 1791298800123, 'observed_at_utc': '2026-10-06T12:00:00Z'}


def collector_market():
    # Synthetic values, source shape from reviewed ReadOnlyMT5.market_snapshot.
    raw = candidate(); sec = raw['time']
    return {'status': 'READ_ONLY_MARKET_UNQUALIFIED', 'input_kind': 'DEMO_OBSERVATION',
            'account_mode': 'DEMO', 'symbol': 'GOLD', 'canonical_symbol': 'XAUUSD', 'timeframe': 'M1',
            'source_time_status': 'UNQUALIFIED', 'candle_semantics': 'OPEN_TIME_CANDIDATE_NOT_VERIFIED',
            'clock_evidence': None, 'runtime_eligible': False, 'broker_execution_allowed': False,
            'ai_analysis': False, 'paper_execution': False,
            'tick': {k: raw[k] for k in ('time', 'time_msc', 'bid', 'ask')},
            'sample': {'kind': 'DEMO_OBSERVATION', 'time': sec, 'time_msc': raw['time_msc'],
                       'acquired_start_utc': '2026-10-06T12:00:00Z', 'acquired_end_utc': '2026-10-06T12:00:00.100000Z',
                       'acquired_start_mono_ns': 1000000000, 'acquired_end_mono_ns': 1100000000},
            'candles': [{'time': sec-(12-i)*60, 'open': '2500.10', 'high': '2501.00',
                         'low': '2499.00', 'close': '2500.20'} for i in range(12)],
            'session_id': 'SYNTHETIC_PRIVATE_MARKER', 'server': 'SYNTHETIC_PRIVATE_MARKER',
            'specs': {'ignored': 'SYNTHETIC_PRIVATE_MARKER'}, 'calls': {'ignored': 'SYNTHETIC_PRIVATE_MARKER'},
            'diagnostic_details': {'ignored': 'SYNTHETIC_PRIVATE_MARKER'}}


class ProducerTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('No network'))
        self.network.start(); self.addCleanup(self.network.stop)

    def source(self, raw):
        data = raw if isinstance(raw, bytes) else json.dumps(raw).encode()
        return producer.OfflineMarketProducer(lambda user: data)

    def assert_disabled(self, status):
        for key in ('connected', 'runtime_eligible', 'broker_execution_allowed', 'ai_analysis', 'paper_execution'):
            self.assertIs(status[key], False)
        self.assertIs(status['policy_replay_only'], True)
        self.assertEqual(status['producer_acceptance'], 'NOT_IMPLEMENTED')

    def test_reader_absent_and_failure_disclose_no_private_error(self):
        self.assertEqual(producer.OfflineMarketProducer().acceptance('synthetic-user')['reason'], 'NO_PRODUCER_READER')
        reader = Mock(side_effect=RuntimeError('SYNTHETIC_PRIVATE_MARKER'))
        status = producer.OfflineMarketProducer(reader).acceptance('synthetic-user')
        self.assertEqual(status['reason'], 'PRODUCER_READ_FAILED')
        self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', json.dumps(status))
        self.assert_disabled(status)

    def test_valid_market_candidate_is_blocked_and_never_returned_as_snapshot(self):
        source = self.source(candidate())
        status = source.acceptance('synthetic-user')
        self.assertTrue(status['market_only_candidate_valid'])
        self.assertEqual(status['outcome'], 'BLOCKED')
        self.assertEqual(status['missing_evidence'], list(producer.MISSING_EVIDENCE))
        self.assert_disabled(status)
        for field in ('bid', 'ask', 'time_msc', 'observed_at_utc', 'source_symbol', 'candles'):
            self.assertNotIn(field, status)
        with self.assertRaises(analysis.Unavailable): source.snapshot('synthetic-user')

    def test_reader_receives_exact_tenant_and_projection_is_independent(self):
        reader = Mock(return_value=json.dumps(candidate()).encode())
        source = producer.OfflineMarketProducer(reader)
        one = source.acceptance('synthetic-user-a')
        reader.assert_called_once_with('synthetic-user-a')
        one['missing_evidence'].clear()
        two = source.acceptance('synthetic-user-b')
        reader.assert_called_with('synthetic-user-b')
        self.assertEqual(two['missing_evidence'], list(producer.MISSING_EVIDENCE))

    def test_privacy_and_client_verification_claims_rejected(self):
        for key in ('account', 'balance', 'password', 'connected', 'runtime_eligible',
                    'mapping_verified', 'clock_verified', 'notional_units', 'producer_acceptance'):
            with self.subTest(key=key):
                status = self.source(dict(candidate(), **{key: 'SYNTHETIC_PRIVATE_MARKER'})).acceptance('synthetic-user')
                self.assertEqual(status['outcome'], 'REJECTED')
                self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', json.dumps(status))
                self.assert_disabled(status)

    def test_malformed_size_real_and_historical_full_report_rejected(self):
        cases = [b'{', b'\xff', b'{}' + b' ' * observation.MAX_FILE_BYTES,
                 b'{"kind":"DEMO","kind":"DEMO"}', b'{"bid":NaN}',
                 dict(candidate(), kind='REAL'), dict(candidate(), kind='TEST_FIXTURE'),
                 {'schema': 'kilas-collector-diagnostic-v1', 'outcome': 'READ_ONLY_DEMO_DIAGNOSTIC_CAPTURED'}]
        for raw in cases:
            with self.subTest(raw_type=type(raw).__name__):
                status = self.source(raw).acceptance('synthetic-user')
                self.assertEqual(status['outcome'], 'REJECTED')
                self.assert_disabled(status)

    def test_valid_candles_do_not_prove_closure_or_clock(self):
        raw = candidate()
        raw.update(timeframe='M1', candles=[{'time': raw['time']-60, 'open':'2500.10',
                                            'high':'2501.00', 'low':'2499.00', 'close':'2500.20'}])
        before = copy.deepcopy(raw)
        status = self.source(raw).acceptance('synthetic-user')
        self.assertEqual(status['candle_count'], 1)
        self.assertIn('CLOSED_CANDLE_SEMANTICS', status['missing_evidence'])
        self.assertIn('BROKER_TIME_PROFILE', status['missing_evidence'])
        self.assertEqual(raw, before)
        self.assert_disabled(status)

    def test_even_current_utc_capture_cannot_arm_snapshot(self):
        from datetime import datetime, timezone
        raw = candidate(); raw['observed_at_utc'] = datetime.now(timezone.utc).isoformat()
        source = self.source(raw)
        self.assertEqual(source.acceptance('synthetic-user')['outcome'], 'BLOCKED')
        with self.assertRaises(analysis.Unavailable): source.snapshot('synthetic-user')
        self.assertIsNone(analysis.market_source)

    def test_analyst_rejects_manually_injected_skeleton_before_reservation_or_http(self):
        source = self.source(candidate())
        with patch.object(analysis, 'market_source', source), \
             patch.object(analysis, 'availability', return_value={'outcome': 'READY'}), \
             patch.object(analysis.budget, 'previous', return_value=None), \
             patch.object(analysis.budget, 'reserve') as reserve, \
             patch.object(analysis, '_http') as http:
            result = analysis.analyze('synthetic-user', {'operation_key': '1234567890abcdef1234567890abcdef'})
            self.assertEqual(result['outcome'], 'UNAVAILABLE')
            self.assertTrue(result['proposal_only'])
            reserve.assert_not_called()
            http.assert_not_called()
        self.assertIsNone(analysis.market_source)

    def test_collector_projection_preserves_raw_times_and_discards_private_fields(self):
        market = collector_market(); before = copy.deepcopy(market)
        data = producer.project_collector_market(market)
        self.assertLessEqual(len(data), observation.MAX_FILE_BYTES)
        self.assertNotIn(b'SYNTHETIC_PRIVATE_MARKER', data)
        raw = json.loads(data); parsed = observation.parse_file(data)
        self.assertEqual(set(raw), observation.FIELDS | {'schema_version', 'timeframe', 'candles'})
        self.assertEqual(raw['time_msc'], market['tick']['time_msc'])
        self.assertEqual(raw['candles'], market['candles'])
        self.assertEqual(raw['observed_at_utc'], market['sample']['acquired_end_utc'])
        self.assertIsNone(parsed['canonical_symbol']); self.assertIsNone(parsed['event_time_utc'])
        self.assertEqual(parsed['freshness'], 'unknown')
        self.assertEqual(parsed['candle_time_semantics'], 'unverified')
        self.assertEqual(market, before)

    def test_source_grounded_collector_reader_stays_blocked_for_each_tenant(self):
        reader = Mock(side_effect=lambda user: collector_market())
        source = producer.OfflineMarketProducer.from_collector(reader)
        status = source.acceptance('synthetic-tenant-a')
        reader.assert_called_with('synthetic-tenant-a')
        self.assertEqual(status['candle_count'], 12); self.assertEqual(status['outcome'], 'BLOCKED')
        self.assertTrue(status['market_only_candidate_valid']); self.assert_disabled(status)
        with self.assertRaises(analysis.Unavailable): source.snapshot('synthetic-tenant-b')
        reader.assert_called_with('synthetic-tenant-b')
        self.assertIsNone(analysis.market_source)

    def test_collector_unavailable_real_execution_or_clock_claims_rejected(self):
        changes = [{'status': 'UNAVAILABLE'}, {'account_mode': 'REAL'}, {'runtime_eligible': True},
                   {'broker_execution_allowed': True}, {'ai_analysis': True}, {'paper_execution': True},
                   {'source_time_status': 'VERIFIED'}, {'clock_evidence': {'verified': True}},
                   {'candle_semantics': 'CLOSED_VERIFIED'}, {'symbol': 'XAUUSD'}, {'timeframe': 'M5'}]
        for change in changes:
            with self.subTest(change=change):
                market = dict(collector_market(), **change)
                with self.assertRaises(observation.TradingError): producer.project_collector_market(market)
                status = producer.OfflineMarketProducer.from_collector(lambda user: market).acceptance('synthetic-user')
                self.assertFalse(status['market_only_candidate_valid']); self.assert_disabled(status)

    def test_collector_capture_binding_candle_and_value_bounds_rejected(self):
        mutations = [lambda m: m['sample'].update(time_msc=m['tick']['time_msc']+1),
                     lambda m: m['sample'].update(acquired_end_mono_ns=True),
                     lambda m: m['sample'].update(acquired_end_mono_ns=4000000000),
                     lambda m: m['sample'].update(acquired_end_utc='2026-10-06T12:00:01.100000Z'),
                     lambda m: m['sample'].update(acquired_end_utc='2026-10-06T15:00:00.100000+03:00'),
                     lambda m: m['tick'].update(bid='9'*10000),
                     lambda m: m['candles'].pop(),
                     lambda m: m['candles'][-1].update(time=m['tick']['time']),
                     lambda m: m['candles'][0].update(time=m['candles'][0]['time']-60),
                     lambda m: m['candles'][0].update(balance='SYNTHETIC_PRIVATE_MARKER')]
        for mutation in mutations:
            market = collector_market(); mutation(market)
            with self.assertRaises(observation.TradingError): producer.project_collector_market(market)

    def test_collector_report_envelope_is_not_market_result(self):
        report = {'status': 'READ_ONLY_DEMO_DIAGNOSTIC_CAPTURED', 'markets': [collector_market()],
                  'history': [{'account': 'SYNTHETIC_PRIVATE_MARKER'}]}
        with self.assertRaises(observation.TradingError): producer.project_collector_market(report)

    def test_successful_offline_clock_and_fixture_replay_do_not_qualify_producer(self):
        # Shape/status facts reviewed from clock_batch_offline and
        # source_batch_offline; these are declared synthetic results, not a
        # replacement implementation of packet/profile qualification.
        clock_result = {'status': 'OFFLINE_CLOCK_BATCH_VALIDATED',
                        'schema': 'kilas-clock-batch-offline-v2', 'attempt_count': 4,
                        'reply_count': 4, 'offset_seconds': '0', 'uncertainty_seconds': '0.1',
                        'expires_mono_ns': 3000000000, 'evidence_sha256': '0'*64,
                        'assurance': 'UNAUTHENTICATED_OPERATIONAL_PAPER_ONLY',
                        'source_freshness_evaluated': False, 'producer_acceptance': 'NOT_IMPLEMENTED',
                        'runtime_eligible': False, 'broker_execution_allowed': False}
        market = collector_market(); market['clock_evidence'] = clock_result
        source = producer.OfflineMarketProducer.from_collector(lambda user: market)
        self.assertEqual(source.acceptance('synthetic-user')['outcome'], 'REJECTED')
        with self.assertRaises(analysis.Unavailable): source.snapshot('synthetic-user')
        replay = dict(clock_result, status='READ_ONLY_VALIDATED_FIXTURE',
                      synthetic=True, policy_replay_only=True)
        with self.assertRaises(observation.TradingError): producer.project_collector_market(replay)
        self.assertIsNone(analysis.market_source)


if __name__ == '__main__': unittest.main()
