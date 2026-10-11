"""Offline GOLD guards. Fake SDK only; no installed strategy or authority."""
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path

from demo_auto_controller import Blocked, Signal, Specs
from mt5_demo_adapter import Journal, MT5DemoAdapter
from test_demo_auto_controller import fixture
from test_demo_instrument_profiles import GoldSDK
from test_mt5_demo_adapter import FakeClock, FakeSDK, policy


class GoldProtectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock, self.sdk = FakeClock(), GoldSDK()
        self.p = replace(policy(), sl_loss_usd=D('2'), tp_profit_usd=D('1'))
        self.adapter = MT5DemoAdapter(self.sdk, Journal(Path(self.tmp.name)/'gold.sqlite'),
                                      self.p, instrument='GOLD', clock=self.clock, wall=self.clock)
        for _ in range(3):
            self.adapter.snapshot()
        self.signal = Signal('same-decision', 'BUY', D('4194.59'), D('4197.59'), symbol='GOLD')
        self.profit_calls = []
        original = self.sdk.order_calc_profit
        def profit(*args):
            self.profit_calls.append(args)
            return original(*args)
        self.sdk.order_calc_profit = profit

    def tearDown(self):
        self.assertEqual((self.sdk.checks, self.sdk.sends), ([], []))

    def test_unbound_and_btc_signal_rejected_before_profit(self):
        for symbol in (None, 'BTCUSD', 'XAUUSD', 'gold'):
            signal = replace(self.signal, symbol=symbol)
            for call in (self.adapter.quote_risk, self.adapter.submit_once):
                with self.assertRaisesRegex(Blocked, '^SIGNAL_INSTRUMENT_MISMATCH$'):
                    call(signal, D('.01'))
        self.assertEqual(self.profit_calls, [])

    def test_gold_signal_cannot_reuse_btc_adapter(self):
        btc = FakeSDK()
        adapter = MT5DemoAdapter(btc, Journal(Path(self.tmp.name)/'btc.sqlite'), self.p)
        for call in (adapter.quote_risk, adapter.submit_once):
            with self.assertRaisesRegex(Blocked, '^SIGNAL_INSTRUMENT_MISMATCH$'):
                call(self.signal, D('.01'))
        self.assertEqual((btc.checks, btc.sends), ([], []))

    def test_controller_checks_instrument_before_decision_deduplication(self):
        for symbol in (None, 'GOLD'):
            controller, broker, strategy, _ = fixture()
            strategy.signal = replace(strategy.signal, symbol=symbol)
            controller.start()
            controller.seen.add(strategy.signal.key)
            state = controller.poll()
            self.assertEqual(state['state'], 'OFF')
            self.assertEqual(state['reason'], 'SIGNAL_INSTRUMENT_MISMATCH')
            self.assertEqual(broker.sent, [])

    def test_exact_lot_limits_no_adjustment(self):
        for lot in (D('.001'), D('.015'), D('50.01'), D('NaN'), True, None):
            with self.assertRaises(Blocked):
                self.adapter.quote_risk(self.signal, lot)
        self.assertEqual(self.profit_calls, [])
        Specs(D('.01'), D('1'), D('.01')).validate('.01')

    def test_price_grid_wrong_side_and_zero_distance_stop(self):
        self.sdk.info.trade_stops_level = self.sdk.info.trade_freeze_level = 0
        for side, stop, target in (
            ('BUY', '4194.591', '4197.59'),
            ('BUY', '4195.20', '4197.59'),
            ('SELL', '4195.59', '4193.20'),
        ):
            risk = self.adapter.quote_risk(Signal('fixture', side, D(stop), D(target), 'GOLD'), D('.01'))
            self.assertFalse(risk.valid_protective_stop)
        for changes in (dict(stop=D('4200')), dict(target=D('4190')), dict(stop=D('-1'))):
            with self.assertRaises(Blocked):
                self.adapter.quote_risk(replace(self.signal, **changes), D('.01'))
        risk = self.adapter.quote_risk(replace(self.signal, target=D('4197.591')), D('.01'))
        self.assertFalse(risk.valid_take_profit)

    def test_freeze_level_can_block_otherwise_valid_stop(self):
        self.sdk.info.trade_freeze_level = 100
        risk = self.adapter.quote_risk(self.signal, D('.01'))
        self.assertFalse(risk.valid_protective_stop)
        self.sdk.info.trade_freeze_level = 300
        with self.assertRaisesRegex(Blocked, '^BROKER_STOP_DISTANCE_CONFLICT$'):
            self.adapter.currency_signal('fixture', 'BUY', D('.01'))

    def test_invalid_freeze_stops_before_profit(self):
        for value in (None, True, -1, 1.5):
            self.sdk.info.trade_freeze_level = value
            with self.assertRaisesRegex(Blocked, '^FREEZE_INVALID$'):
                self.adapter.quote_risk(self.signal, D('.01'))
        self.assertEqual(self.profit_calls, [])

    def test_currency_conversion_keeps_gold_contract_and_binding(self):
        self.adapter.policy = replace(self.p, fee_reserve_usd=D('.2'), deviation_points=10)
        for side in ('BUY', 'SELL'):
            signal = self.adapter.currency_signal('fixture-'+side, side, D('.01'))
            risk = self.adapter.quote_risk(signal, D('.01'))
            self.assertEqual(signal.symbol, 'GOLD')
            self.assertTrue(risk.valid_protective_stop and risk.valid_take_profit)
            self.assertLessEqual(risk.stop_loss_usd, D('2'))
            self.assertGreater(risk.notional_usd, D('2000'))
            self.assertLess(abs(signal.target-signal.stop), D('4'))
        self.assertTrue(all(args[1] == 'GOLD' for args in self.profit_calls))

    def test_fee_reserve_invalidates_previously_valid_budget(self):
        self.adapter.policy = replace(self.p, fee_reserve_usd=D('1.1'))
        risk = self.adapter.quote_risk(self.signal, D('.01'))
        self.assertFalse(risk.valid_protective_stop)


class ProtectionRecheckTests(unittest.TestCase):
    def test_changed_grid_or_freeze_after_check_prevents_protective_send(self):
        for field, value, candidate in (('trade_freeze_level', 10000, D('950')),
                                        ('trade_tick_size', .03, D('950')),
                                        ('trade_stops_level', 10000, D('950'))):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                sdk, clock = FakeSDK(), FakeClock()
                adapter = MT5DemoAdapter(sdk, Journal(Path(tmp)/'btc.sqlite'), policy(),
                                         execute=True, clock=clock, wall=clock)
                for _ in range(3): adapter.snapshot()
                adapter.begin_run()
                signal = Signal('btc-fixture', 'BUY', D('900'), D('1200'), 'BTCUSD')
                self.assertEqual(adapter.submit_once(signal, D('.01')), 'CONFIRMED')
                original = sdk.order_check
                def checked(request):
                    result = original(request)
                    setattr(sdk.info, field, value)
                    return result
                sdk.order_check = checked
                self.assertEqual(adapter.tighten_stop(30, candidate), 'UNKNOWN')
                self.assertEqual(len(sdk.sends), 1)  # Only the preceding fake entry.
                self.assertEqual((sdk.positions[0].sl, sdk.positions[0].tp), (900., 1200.))


class GoldAssessmentTests(unittest.TestCase):
    tearDown = GoldProtectionTests.tearDown

    def setUp(self):
        from test_gold_market_readiness import fixture as evidence_fixture, UTC_NOW
        GoldProtectionTests.setUp(self)
        self.session, self.market = evidence_fixture()
        self.adapter.wall = lambda: UTC_NOW.timestamp()
        self.sdk.tick.time_msc = self.market.quote_raw_msc
        self.sdk.tick.time = self.sdk.tick.time_msc // 1000

    def assess(self, **changes):
        kwargs = dict(session_evidence=self.session, market_evidence=self.market)
        kwargs.update(changes)
        result = self.adapter.assess_gold_proposal(self.signal, D('.01'), **kwargs)
        self.assertEqual(result['decision'], 'WAIT')
        self.assertFalse(result['execution_authorized'])
        self.assertFalse(result['broker_execution_allowed'])
        return result

    def test_verified_closed_waits_without_reading_sdk(self):
        def forbidden(): raise AssertionError('Read occurred before CLOSED gate')
        self.sdk.account_info = forbidden
        result = self.assess(session_evidence=replace(self.session, state='CLOSED'), market_evidence=None)
        self.assertEqual(result['reason_code'], 'MARKET_CLOSED')
        self.assertEqual(self.profit_calls, [])

    def test_missing_stale_or_wrong_session_waits_before_sdk(self):
        def forbidden(): raise AssertionError('Read occurred before session gate')
        self.sdk.account_info = forbidden
        for session in (None, replace(self.session, valid_until_at=100),
                        replace(self.session, symbol='BTCUSD')):
            result = self.assess(session_evidence=session)
            self.assertEqual(result['reason_code'], 'MARKET_SESSION_UNVERIFIED')

    def test_old_bars_cannot_be_freshened_by_collection(self):
        old = replace(self.market, latest_m5_raw_open_epoch=self.market.latest_m5_raw_open_epoch-86400,
                      captured_at=self.clock())
        result = self.assess(market_evidence=old)
        self.assertEqual(result['reason_code'], 'MARKET_EVIDENCE_UNVERIFIED')
        self.assertEqual(self.profit_calls, [])

    def test_actual_sdk_quote_must_be_fresh_even_with_good_evidence(self):
        self.sdk.tick.time_msc -= 86400000
        self.sdk.tick.time = self.sdk.tick.time_msc // 1000
        result = self.assess()
        self.assertEqual(result['reason_code'], 'MARKET_EVIDENCE_UNVERIFIED')
        self.assertEqual(self.profit_calls, [])

    def test_historical_minimum_gold_notional_exceeds_unchanged_cap(self):
        result = self.assess()
        self.assertEqual(result['reason_code'], 'NOTIONAL_CAP_EXCEEDED')
        self.assertEqual(D(result['risk']['notional_usd']), D('4195.59'))
        self.assertFalse(result['proposal_risk_validated'])
        self.assertEqual(self.adapter.policy.controller.max_notional_usd, D('2000'))

    def test_synthetic_low_price_passes_math_but_cannot_authorize_gold(self):
        self.sdk.tick.bid, self.sdk.tick.ask = 1499.9, 1500.
        self.signal = replace(self.signal, stop=D('1499'), target=D('1502'))
        result = self.assess()
        self.assertTrue(result['proposal_risk_validated'])
        self.assertEqual(result['reason_code'], 'INSTRUMENT_EXECUTION_UNREVIEWED')
        self.assertEqual(self.adapter.journal.records(), [])

    def test_misaligned_lot_is_rejected_without_profit_calculation(self):
        result = self.adapter.assess_gold_proposal(self.signal, D('.015'),
                   session_evidence=self.session, market_evidence=self.market)
        self.assertEqual(result['reason_code'], 'LOT_OUTSIDE_BROKER_RULES')
        self.assertEqual(self.profit_calls, [])

    def test_proposal_loss_cannot_exceed_entire_session_budget(self):
        self.sdk.tick.bid, self.sdk.tick.ask = 1499.9, 1500.
        self.signal = replace(self.signal, stop=D('1499'), target=D('1502'))
        self.adapter.policy = replace(self.p, controller=replace(self.p.controller, session_loss_usd=D('.5')))
        result = self.assess()
        self.assertFalse(result['proposal_risk_validated'])
        self.assertEqual(result['reason_code'], 'SESSION_RISK_BLOCKED')

    def test_slow_profit_math_cannot_renew_evidence(self):
        original = self.sdk.order_calc_profit
        def slow(*args):
            result = original(*args)
            self.clock.value += 2
            return result
        self.sdk.order_calc_profit = slow
        result = self.assess()
        self.assertEqual(result['reason_code'], 'QUOTE_LEASE_EXPIRED')

    def test_unverified_liveness_waits_despite_fresh_clock_proof(self):
        from mt5_demo_session import DemoReceiptLiveness
        self.adapter.liveness = DemoReceiptLiveness(now=self.clock)
        result = self.assess()
        self.assertEqual(result['reason_code'], 'QUOTE_LIVENESS_UNVERIFIED')
        self.assertEqual(self.profit_calls, [])


if __name__ == '__main__':
    unittest.main()
