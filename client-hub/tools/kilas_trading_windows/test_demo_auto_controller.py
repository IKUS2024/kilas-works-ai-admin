"""Offline safety behavior only: fixture signals are not a trading strategy."""
import unittest
from dataclasses import replace
from decimal import Decimal as D
from demo_auto_controller import (Blocked, Controller, Identity, Specs, Snapshot,
                                  Policy, Position, Signal, Risk)


class Clock:
    now = 100.0
    def __call__(self):
        return self.now


class FakeBroker:
    def __init__(self, clock):
        self.clock = clock
        self.s = Snapshot(Identity('DEMO', 'XMGlobal-MT5 10', 'USD',
                                  'XM Global Limited', 'private-fake-binding'),
                          True, clock(), Specs(D('.01'), D('1'), D('.01')),
                          (), 0, D('0'), True, True,
                          terminal_binding_verified=True,
                          execution_permissions_verified=True)
        self.risk = Risk(D('1'), D('1000'), D('.4'), True, True)
        self.sent, self.tightened = [], []
        self.result, self.protection_result = 'CONFIRMED', 'CONFIRMED'
        self.raise_submit = False
        self.reads = 0
        self.race = False
    def snapshot(self):
        self.reads += 1
        if self.race and self.reads >= 3:
            return replace(self.s, pending_orders=1)
        return self.s
    def quote_risk(self, signal, lot):
        return self.risk
    def submit_once(self, signal, lot):
        self.sent.append((signal, lot))
        if self.raise_submit:
            raise RuntimeError('private-credential-do-not-log')
        return self.result
    def tighten_stop(self, key, stop):
        self.tightened.append((key, stop))
        return self.protection_result


class FixtureSignals:
    signal = Signal('fake-closed-bar-1', 'BUY', D('90'), D('110'), symbol='BTCUSD')
    stop = None
    def decision(self, snapshot):
        return self.signal
    def protective_stop(self, snapshot, position):
        return self.stop


def fixture():
    clock = Clock()
    broker = FakeBroker(clock)
    strategy = FixtureSignals()
    policy = Policy('TEST_ONLY_NOT_BTCUSD_STRATEGY', 60, 2, D('2'), 1.5,
                    D('2'), D('2000'), D('1'))
    return Controller(broker, strategy, policy, clock=clock), broker, strategy, clock


class ControllerTests(unittest.TestCase):
    def test_shipped_default_cannot_start(self):
        c = Controller()
        self.assertEqual(c.start()['state'], 'OFF')
        self.assertIn('MISSING', c.reason)
        self.assertEqual(c.lot, D('.01'))

    def test_off_never_enters(self):
        c, b, _, _ = fixture()
        c.poll()
        self.assertEqual(b.sent, [])

    def test_unique_decision_and_stop(self):
        c, b, _, _ = fixture()
        self.assertEqual(c.start()['state'], 'ON')
        c.poll(); c.poll(); c.stop(); c.poll()
        self.assertEqual(len(b.sent), 1)
        self.assertEqual(c.status()['state'], 'OFF')

    def test_real_wrong_identity_or_terminal_blocks(self):
        for changes in ({'mode': 'REAL'}, {'server': 'another'}, {'currency': 'EUR'},
                        {'company': 'another'}, {'binding': None}):
            c, b, _, _ = fixture()
            b.s = replace(b.s, identity=replace(b.s.identity, **changes))
            self.assertEqual(c.start()['state'], 'OFF')
            self.assertEqual(b.sent, [])
        for changes in ({'symbol': 'GOLD'}, {'terminal_binding_verified': False}):
            c, b, _, _ = fixture()
            b.s = replace(b.s, **changes)
            self.assertEqual(c.start()['state'], 'OFF')

    def test_identity_change_after_start(self):
        c, b, _, _ = fixture(); c.start()
        b.s = replace(b.s, identity=replace(b.s.identity, binding='different'))
        self.assertEqual(c.poll()['reason'], 'ACCOUNT_BINDING_CHANGED')
        self.assertEqual(b.sent, [])

    def test_lot_exact_no_rounding(self):
        for value in ('0', '-.01', '.001', '.015', '1.01', 'NaN', 'Infinity'):
            c, b, _, _ = fixture()
            with self.assertRaises(Blocked):
                c.set_lot(value)
            self.assertEqual(c.lot, D('.01'))
        c, b, _, _ = fixture()
        c.set_lot('.02')
        self.assertEqual(c.lot, D('.02'))
        c.start()
        with self.assertRaises(Blocked):
            c.set_lot('.03')

    def test_broker_min_not_silently_increased(self):
        c, b, _, _ = fixture()
        b.s = replace(b.s, specs=Specs(D('.1'), D('1'), D('.1')))
        self.assertEqual(c.start()['state'], 'OFF')
        self.assertEqual(c.lot, D('.01'))

    def test_stale_frozen_disconnected_or_permission(self):
        for changes in ({'receipt_at': 98.5}, {'receipt_at': 101},
                        {'receipt_at': float('nan')}, {'receipt_at': float('inf')},
                        {'liveness_verified': False}, {'connected': False},
                        {'execution_permissions_verified': False}):
            c, b, _, _ = fixture(); c.start()
            b.s = replace(b.s, **changes)
            self.assertEqual(c.poll()['state'], 'OFF')
            self.assertEqual(b.sent, [])

    def test_run_expiry(self):
        c, b, _, clock = fixture(); c.start()
        clock.now = 160
        b.s = replace(b.s, receipt_at=160)
        self.assertEqual(c.poll()['reason'], 'RUN_EXPIRED')
        self.assertEqual(b.sent, [])

    def test_existing_exposure_blocks_start(self):
        for changes in ({'pending_orders': 1}, {'positions': (Position('x', 'BUY', D('90'), True),)}):
            c, b, _, _ = fixture()
            b.s = replace(b.s, **changes)
            self.assertEqual(c.start()['state'], 'OFF')

    def test_max_one_position_and_unprotected(self):
        for positions in ((Position('x', 'BUY', None, True),),
                          (Position('x', 'BUY', D('90'), False),),
                          (Position('x', 'BUY', D('90'), True), Position('y', 'SELL', D('110'), True))):
            c, b, _, _ = fixture(); c.start()
            b.s = replace(b.s, positions=positions)
            self.assertEqual(c.poll()['state'], 'OFF')
            self.assertEqual(b.sent, [])

    def test_owned_position_blocks_second_entry(self):
        c, b, _, _ = fixture(); c.start()
        b.s = replace(b.s, positions=(Position('x', 'BUY', D('90'), True),))
        c.poll()
        self.assertEqual(b.sent, [])

    def test_off_protection_only_tightens_owned_stop(self):
        for side, current, candidate, expected in (
                ('BUY', '90', '95', 1), ('BUY', '90', '85', 0),
                ('SELL', '110', '105', 1), ('SELL', '110', '115', 0)):
            c, b, s, _ = fixture()
            b.s = replace(b.s, positions=(Position('private-ticket', side, D(current), True),))
            s.stop = D(candidate)
            c.poll()
            self.assertEqual(len(b.tightened), expected)
            self.assertEqual(b.sent, [])
            self.assertEqual(c.status()['state'], 'OFF')
            self.assertNotIn('private-ticket', str(c.status()))

    def test_ambiguous_protection_blocks_restart(self):
        c, b, s, _ = fixture()
        b.s = replace(b.s, positions=(Position('x', 'BUY', D('90'), True),))
        s.stop = D('95'); b.protection_result = 'UNKNOWN'
        c.poll()
        self.assertTrue(c.reconciliation_required)
        self.assertEqual(c.start()['state'], 'OFF')

    def test_risk_caps_no_resize(self):
        for changes in ({'stop_loss_usd': D('2.01')}, {'notional_usd': D('2001')},
                        {'spread_cost_usd': D('1.01')}, {'valid_protective_stop': False}):
            c, b, _, _ = fixture(); c.set_lot('.02'); c.start()
            b.risk = replace(b.risk, **changes)
            self.assertEqual(c.poll()['state'], 'OFF')
            self.assertEqual(c.lot, D('.02'))
            self.assertEqual(b.sent, [])

    def test_session_loss_and_unreconciled(self):
        for changes in ({'session_loss': D('2')}, {'session_reconciled': False}):
            c, b, _, _ = fixture(); c.start()
            b.s = replace(b.s, **changes)
            self.assertEqual(c.poll()['state'], 'OFF')
            self.assertEqual(b.sent, [])
        c, b, _, _ = fixture(); c.start()
        b.s = replace(b.s, session_loss=D('1.5'))
        c.poll()
        self.assertEqual(b.sent, [])

    def test_final_exposure_race(self):
        c, b, _, _ = fixture(); c.start(); b.race = True
        self.assertEqual(c.poll()['reason'], 'EXPOSURE_CHANGED')
        self.assertEqual(b.sent, [])

    def test_ambiguous_submission_never_retries(self):
        for exception in (False, True):
            c, b, _, _ = fixture(); c.start()
            b.result = 'UNKNOWN'; b.raise_submit = exception
            c.poll(); c.start(); c.poll()
            self.assertEqual(len(b.sent), 1)
            self.assertTrue(c.reconciliation_required)
            self.assertNotIn('private-credential', str(c.events))

    def test_budget_not_reset_by_toggle(self):
        c, b, s, _ = fixture(); c.start(); c.poll()
        c.stop(); c.start(); s.signal = replace(s.signal, key='fake-2'); c.poll()
        c.stop()
        self.assertEqual(c.start()['reason'], 'ENTRY_BUDGET_EXHAUSTED')
        self.assertEqual(len(b.sent), 2)

    def test_wait_never_enters(self):
        c, b, s, _ = fixture(); s.signal = None
        c.start(); c.poll()
        self.assertEqual(b.sent, [])

    def test_no_sensitive_status_or_implied_current_connection(self):
        c, b, _, _ = fixture(); c.start()
        self.assertNotIn('private-fake-binding', str(c.status()))
        self.assertFalse(c.status()['broker_connection_current_verified'])

    def test_no_policy_ceiling_relaxation(self):
        c, b, _, _ = fixture()
        c.policy = replace(c.policy, max_notional_usd=D('2001'))
        self.assertEqual(c.start()['reason'], 'EXISTING_RISK_CEILING_EXCEEDED')
        self.assertEqual(b.sent, [])

    def test_no_state_reset_after_ambiguous_restart(self):
        c, b, _, _ = fixture(); c.start(); b.result = 'UNKNOWN'
        c.poll(); c.stop()
        self.assertEqual(c.start()['reason'], 'LOCAL_RECONCILIATION_REQUIRED')
        self.assertEqual(len(b.sent), 1)

    def test_lot_unverified_without_adapter(self):
        c = Controller()
        with self.assertRaises(Blocked):
            c.set_lot('.02')
        self.assertEqual(c.lot, D('.01'))

    def test_entry_requires_reviewed_tp_and_broker_validation(self):
        c, b, s, _ = fixture(); s.signal = replace(s.signal, target=None)
        c.start()
        self.assertEqual(c.poll()['reason'], 'TAKE_PROFIT_MISSING')
        self.assertEqual(b.sent, [])
        c, b, _, _ = fixture(); b.risk = replace(b.risk, valid_take_profit=False)
        c.start(); c.poll()
        self.assertEqual(b.sent, [])

    def test_hold_until_broker_exit_then_new_unique_decision(self):
        c, b, s, _ = fixture(); c.start(); c.poll()
        b.s = replace(b.s, positions=(Position('x', 'BUY', D('90'), True, D('110')),))
        s.signal = replace(s.signal, key='fake-next-bar')
        c.poll()
        self.assertEqual(len(b.sent), 1)
        self.assertEqual(c.protection, 'BROKER_SL_TP_PRESENT')
        # Simulated broker TP/SL exit; core sends no forced close request.
        b.s = replace(b.s, positions=())
        c.poll()
        self.assertEqual(len(b.sent), 2)


if __name__ == '__main__':
    unittest.main()
