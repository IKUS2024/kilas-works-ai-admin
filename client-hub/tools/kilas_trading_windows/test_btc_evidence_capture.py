"""Offline producer tests. Fake SDK only; no attachment or network calls."""
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from btc_evidence_capture import BTCMarketCapture, spec_from_info
from btc_integration_protocol import contract_hash, validate_evidence_request
from demo_auto_controller import Blocked, Position
from mt5_demo_adapter import MT5DemoAdapter, Journal, MAGIC
from test_mt5_demo_adapter import FakeSDK, FakeClock


POLICY_VERSION = 'b' * 64
START = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


def reviewed_risk(snapshot):
    # Explicit offline facts, not inferred from an account/session balance.
    return dict(daily_loss_remaining_cents=1234, strategy_verified=False,
                cooldown_clear=True, loss_streak_clear=False)


class CaptureSDK(FakeSDK):
    TIMEFRAME_M1 = 1

    def __init__(self):
        super().__init__()
        # Preserve this raw broker epoch; it is deliberately +3h from the
        # injected UTC clock and is not certified as an actual UTC timestamp.
        self.tick.time = int(START.timestamp()) + 3 * 3600 + 17
        self.tick.time_msc = self.tick.time * 1000
        self.history_calls = []
        current_open = self.tick.time // 60 * 60
        self.bars = [dict(time=current_open - (12 - i) * 60, open=999.91,
                          high=1000.1, low=999.8, close=1000.0) for i in range(12)]

    def copy_rates_from_pos(self, *args):
        self.history_calls.append(args)
        return self.bars


class TrackingAdapter(MT5DemoAdapter):
    def __init__(self, *args, **kwargs):
        self.read_calls = []
        super().__init__(*args, **kwargs)

    def read(self, method, *args, **kwargs):
        self.read_calls.append((method.__name__, args, kwargs))
        return super().read(method, *args, **kwargs)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sdk = CaptureSDK()
        clock = FakeClock()
        self.adapter = TrackingAdapter(self.sdk, Journal(Path(self.tmp.name) / 'capture.sqlite'),
                                       clock=clock, wall=clock)

    def capture(self, *, elapsed_ns=200_000_000, wall_seconds=.2, **options):
        mono = iter((1_000_000_000, 1_000_000_000 + elapsed_ns))
        wall = iter((START, START + timedelta(seconds=wall_seconds)))
        config = dict(risk_provider=reviewed_risk, policy_version=POLICY_VERSION,
                      clock_ns=lambda: next(mono), now=lambda: next(wall))
        config.update(options)
        return BTCMarketCapture(self.adapter, **config)

    def assert_rejected(self, capture):
        with self.assertRaisesRegex(Blocked, '^BTC_CAPTURE_REJECTED$'):
            capture.collect()
        self.assertEqual((self.sdk.checks, self.sdk.sends), ([], []))

    def test_construction_performs_no_reads_and_requires_no_adapter_properties(self):
        class UnusableAdapter:
            def __getattr__(self, name):
                raise AssertionError('Construction accessed adapter')
        BTCMarketCapture(UnusableAdapter())
        self.capture()
        self.assertEqual(self.adapter.read_calls, [])
        self.assertIsNone(self.adapter.private_identity)

    def test_capture_exact_wire_shape_raw_epochs_and_actual_closed_history(self):
        capture = self.capture().collect()
        self.assertEqual(set(capture), {'market', 'spec', 'risk'})
        market, spec, risk = (capture[key] for key in ('market', 'spec', 'risk'))
        self.assertEqual((market['symbol'], market['timeframe']), ('BTCUSD', 'M1'))
        self.assertEqual(market['tick']['time'], int(START.timestamp()) + 10800 + 17)
        self.assertEqual(market['tick']['time_msc'], market['tick']['time'] * 1000 + 1)
        self.assertEqual((market['tick']['bid'], market['tick']['ask']), ('999.9', '1000'))
        self.assertEqual([bar['time'] for bar in market['candles']],
                         [bar['time'] for bar in self.sdk.bars])
        self.assertIsNone(market['clock'])
        self.assertIsNone(market['clock_profile'])
        self.assertEqual(self.sdk.history_calls, [('BTCUSD', self.sdk.TIMEFRAME_M1, 1, 12)])
        self.assertIn(('copy_rates_from_pos', ('BTCUSD', self.sdk.TIMEFRAME_M1, 1, 12), {}),
                      self.adapter.read_calls)
        self.assertEqual((spec['contract_size'], spec['volume_max']), ('1', '1'))
        self.assertEqual((spec['volume_min'], spec['volume_step']), ('0.01', '0.01'))
        self.assertEqual((spec['tick_cents'], spec['stops_distance_cents']), (1, 1))
        self.assertIsNone(spec['cost_bound_cents'])
        self.assertEqual(spec['verified_at'], market['capture']['end_utc'])
        self.assertEqual(risk['captured_at'], market['capture']['end_utc'])
        self.assertEqual(risk['broker_contract_sha256'], contract_hash(spec))
        self.assertEqual(risk['policy_version'], POLICY_VERSION)
        self.assertEqual((risk['position_open'], risk['protection_active']), (False, False))
        self.assertEqual(risk['daily_loss_remaining_cents'], 1234)
        self.assertFalse(risk['strategy_verified'])
        self.assertFalse(risk['loss_streak_clear'])
        validate_evidence_request(dict(schema_version=2, session_id='1' * 32,
            revision=4, command_id='2' * 32, instrument='BTC', lot='0.01', sequence=1,
            challenge='3' * 64, account_mode='DEMO', terminal_connected=True, **capture))
        self.assertEqual((self.sdk.checks, self.sdk.sends), ([], []))

    def test_missing_provider_or_policy_fails_before_reads(self):
        for options in (dict(risk_provider=None), dict(policy_version=None),
                        dict(policy_version='B' * 64), dict(policy_version='reviewed'),
                        dict(cost_bound_cents=True), dict(cost_bound_cents=-1)):
            with self.subTest(options=options):
                self.assert_rejected(self.capture(**options))
                self.assertEqual(self.adapter.read_calls, [])

    def test_risk_provider_must_supply_exact_strict_facts(self):
        invalid = [None, {}, reviewed_risk(None) | {'position_open': False},
                   reviewed_risk(None) | {'daily_loss_remaining_cents': True},
                   reviewed_risk(None) | {'daily_loss_remaining_cents': -1},
                   reviewed_risk(None) | {'daily_loss_remaining_cents': 50001},
                   reviewed_risk(None) | {'daily_loss_remaining_cents': '1234'},
                   reviewed_risk(None) | {'strategy_verified': 1},
                   reviewed_risk(None) | {'cooldown_clear': None},
                   reviewed_risk(None) | {'loss_streak_clear': 'true'}]
        for result in invalid:
            with self.subTest(result=result):
                self.assert_rejected(self.capture(risk_provider=lambda snapshot: result))

    def test_provider_receives_verified_snapshot_and_errors_are_sanitized(self):
        received = []
        def provider(snapshot):
            received.append(snapshot)
            raise RuntimeError('private account information')
        self.assert_rejected(self.capture(risk_provider=provider))
        self.assertEqual(len(received), 1)
        self.assertTrue(received[0].terminal_binding_verified)
        self.assertEqual(received[0].identity.mode, 'DEMO')

    def test_no_daily_budget_inference_from_adapter_session_loss(self):
        actual_snapshot = self.adapter.snapshot
        def snapshot():
            return replace(actual_snapshot(), session_loss=D('490'))
        with patch.object(self.adapter, 'snapshot', snapshot):
            capture = self.capture().collect()
        self.assertEqual(capture['risk']['daily_loss_remaining_cents'], 1234)

    def test_open_protected_position_is_derived_from_broker_snapshot(self):
        # Seed a previously reconciled fake fill directly; do not send an order.
        with self.adapter.journal.connect() as connection:
            connection.execute('INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?)',
                ('fixture', 'fixture', 'CONFIRMED', 10, 20, 'BUY', '.01', '900', '1200', '0'))
        self.sdk.positions = [NS(ticket=99, identifier=20, symbol='BTCUSD', magic=MAGIC,
                                 type=0, volume=.01, profit=0., swap=0., sl=900., tp=1200.)]
        self.sdk.deals = [NS(ticket=100, order=10, position_id=20, magic=MAGIC,
            symbol='BTCUSD', type=0, entry=0, volume=.01, profit=0., commission=0., swap=0., fee=0.)]
        capture = self.capture().collect()
        self.assertTrue(capture['risk']['position_open'])
        self.assertTrue(capture['risk']['protection_active'])

    def test_unprotected_position_pending_order_or_unreconciled_snapshot_rejects(self):
        actual_snapshot = self.adapter.snapshot
        replacements = (
            dict(positions=(Position(1, 'BUY', None, True, D('1200')),)),
            dict(positions=(Position(1, 'BUY', D('900'), True, None),)),
            dict(positions=(Position(1, 'BUY', D('-1'), True, D('1200')),)),
            dict(pending_orders=1), dict(session_reconciled=False),
            dict(symbol='GOLD'), dict(connected=False), dict(terminal_binding_verified=False))
        for change in replacements:
            with self.subTest(change=change):
                with patch.object(self.adapter, 'snapshot', lambda: replace(actual_snapshot(), **change)):
                    self.assert_rejected(self.capture())

    def test_capture_durations_and_wall_disagreement_reject(self):
        for elapsed, wall in ((0, .2), (-1, .2), (2_000_000_001, 2),
                              (200_000_000, 0), (200_000_000, -.2),
                              (200_000_000, .3), (2_000_000_000, 2.000001)):
            with self.subTest(elapsed=elapsed, wall=wall):
                self.assert_rejected(self.capture(elapsed_ns=elapsed, wall_seconds=wall))
        self.capture(elapsed_ns=2_000_000_000, wall_seconds=2).collect()

    def test_non_utc_or_naive_local_clock_rejects(self):
        for value in (START.replace(tzinfo=None), START.astimezone(timezone(timedelta(hours=3)))):
            with self.subTest(value=value):
                self.assert_rejected(self.capture(now=lambda: value))

    def test_actual_last_closed_bar_relationship_is_required(self):
        original = [dict(row) for row in self.sdk.bars]
        for shift in (-60, 60, -10800):
            with self.subTest(shift=shift):
                self.sdk.bars = [dict(row, time=row['time'] + shift) for row in original]
                self.assert_rejected(self.capture())
        self.sdk.bars = original

    def test_missing_duplicate_disordered_forming_or_gapped_history_rejects(self):
        original = [dict(row) for row in self.sdk.bars]
        invalid = [original[:-1], original + [original[-1]], list(reversed(original)),
                   [dict(row, time=row['time'] + (1 if i == 3 else 0)) for i, row in enumerate(original)],
                   [dict(row, time=original[0]['time']) if i == 1 else row for i, row in enumerate(original)],
                   [dict(row, time=row['time'] + (60 if i > 3 else 0)) for i, row in enumerate(original)]]
        for bars in invalid:
            with self.subTest(bars=len(bars)):
                self.sdk.bars = bars
                self.assert_rejected(self.capture())
        self.sdk.bars = original

    def test_bad_ohlc_fractional_epoch_and_noncent_price_reject(self):
        original = [dict(row) for row in self.sdk.bars]
        for change in (dict(low=1001), dict(high=900), dict(open='NaN'),
                       dict(close='1000.001'), dict(time=float(original[0]['time'])),
                       dict(time=True)):
            with self.subTest(change=change):
                self.sdk.bars = [original[0] | change] + original[1:]
                self.assert_rejected(self.capture())
        self.sdk.bars = original

    def test_tick_millisecond_binding_and_cent_grid_required(self):
        original = vars(self.sdk.tick).copy()
        for change in (dict(time_msc=1), dict(time=True), dict(bid=1001),
                       dict(ask='1000.001'), dict(ask='NaN')):
            with self.subTest(change=change):
                self.sdk.tick = NS(**(original | change))
                self.assert_rejected(self.capture())
        self.sdk.tick = NS(**original)
        self.sdk.info.trade_tick_size = .05
        self.assert_rejected(self.capture())  # Candle 999.91 is off broker grid.

    def test_units_changing_during_capture_reject_whole_evidence(self):
        def provider(snapshot):
            self.sdk.info.trade_contract_size = 2
            return reviewed_risk(snapshot)
        self.assert_rejected(self.capture(risk_provider=provider))

    def test_real_account_or_wrong_symbol_fails_verified_read(self):
        self.sdk.account.trade_mode = 2
        self.assert_rejected(self.capture())
        self.sdk.account.trade_mode = 0
        self.sdk.info.name = 'BTCUSDmicro'
        self.assert_rejected(self.capture())


class SpecConversionTests(unittest.TestCase):
    def spec(self, info, cost=None):
        return spec_from_info(info, cost_bound_cents=cost, verified_at=START.isoformat())

    def test_conservative_freeze_distance_and_canonical_broker_units(self):
        info = FakeSDK().info
        info.trade_contract_size = '2.5000'
        info.volume_max = '1.0050'
        info.trade_stops_level = 2
        info.trade_freeze_level = 7
        spec = self.spec(info, cost=0)
        self.assertEqual(spec['contract_size'], '2.5')
        self.assertEqual(spec['volume_max'], '1.005')
        self.assertEqual(spec['stops_distance_cents'], 7)
        self.assertEqual(spec['cost_bound_cents'], 0)
        info.trade_stops_level = info.trade_freeze_level = 0
        self.assertEqual(self.spec(info)['stops_distance_cents'], 0)

    def test_subcent_tick_or_stop_distance_never_rounds(self):
        info = FakeSDK().info
        info.point = .001
        info.trade_tick_size = .001
        with self.assertRaisesRegex(Blocked, '^BTC_CAPTURE_SPEC_REJECTED$'):
            self.spec(info)
        info.trade_tick_size = .01
        with self.assertRaisesRegex(Blocked, '^BTC_CAPTURE_SPEC_REJECTED$'):
            self.spec(info)
        info.trade_stops_level = info.trade_freeze_level = 10
        self.assertEqual(self.spec(info)['stops_distance_cents'], 1)

    def test_unverified_symbol_units_or_mode_reject(self):
        for field, value in (('name', 'GOLD'), ('currency_profit', 'EUR'),
                             ('select', False), ('visible', False), ('trade_mode', 0),
                             ('volume_step', '.03'), ('trade_freeze_level', -1)):
            with self.subTest(field=field, value=value):
                info = FakeSDK().info
                setattr(info, field, value)
                with self.assertRaisesRegex(Blocked, '^BTC_CAPTURE_SPEC_REJECTED$'):
                    self.spec(info)

    def test_cost_null_stays_unknown_and_noninteger_values_reject(self):
        self.assertIsNone(self.spec(FakeSDK().info)['cost_bound_cents'])
        self.assertEqual(self.spec(FakeSDK().info, 17)['cost_bound_cents'], 17)
        for cost in (True, -1, 1.0, '1'):
            with self.subTest(cost=cost):
                with self.assertRaisesRegex(Blocked, '^BTC_CAPTURE_SPEC_REJECTED$'):
                    self.spec(FakeSDK().info, cost)


if __name__ == '__main__':
    unittest.main()
