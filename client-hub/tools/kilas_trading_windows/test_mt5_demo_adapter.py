import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
from decimal import Decimal as D

from demo_auto_controller import Blocked, Signal
from mt5_demo_adapter import (MT5DemoAdapter, Journal, DemoTestPolicy, MAGIC,
                              EXE, DATA, SERVER, digest)


def policy():
    # Fixture values only, never installed as runtime configuration.
    return DemoTestPolicy.parse(dict(schema_version=1, session_id='OFFLINE-TEST',
        strategy_reference='FAKE-SIGNAL-NOT-A-STRATEGY', max_run_seconds=60,
        max_entries=2, session_loss_usd='2', max_tick_receipt_age=1.5,
        max_stop_loss_usd='2', max_notional_usd='2000', max_spread_cost_usd='1',
        sl_loss_usd='1', tp_profit_usd='2', fee_reserve_usd='0', deviation_points=0))


class FakeClock:
    value = 100.0
    def __call__(self): return self.value


class FakeSDK:
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    POSITION_TYPE_BUY = 0
    ORDER_FILLING_IOC, ORDER_FILLING_FOK = 1, 0
    ORDER_TIME_GTC = 0
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 1, 6
    TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL = 10009, 10010
    DEAL_ENTRY_IN, DEAL_ENTRY_OUT = 0, 1
    def __init__(self):
        self.account = NS(trade_mode=0, server=SERVER, currency='USD', company='XM Global Limited',
                          login=123, trade_allowed=True, trade_expert=True)
        self.terminal = NS(path=str(Path(EXE).parent), data_path=DATA, connected=True,
                           trade_allowed=True, tradeapi_disabled=False)
        self.info = NS(name='BTCUSD', select=True, visible=True, custom=False, trade_mode=4,
                       currency_profit='USD', currency_margin='USD', point=.01, trade_tick_size=.01,
                       trade_contract_size=1, trade_stops_level=1, trade_freeze_level=1,
                       volume_min=.01, volume_max=1., volume_step=.01, filling_mode=2)
        self.tick = NS(time=100, time_msc=100000, bid=999.9, ask=1000.)
        self.positions, self.orders, self.deals = [], [], []
        self.checks, self.sends = [], []
        self.retcode, self.checkcode = 10009, 0
        self.omit_sl, self.omit_tp, self.raise_send, self.partial = False, False, False, False
        self.order_id, self.position_id = 10, 20
    def account_info(self): return self.account
    def terminal_info(self): return self.terminal
    def symbol_info(self, symbol): return self.info
    def symbol_info_tick(self, symbol):
        self.tick.time_msc += 1
        return self.tick
    def positions_get(self, **kw):
        return tuple(p for p in self.positions if 'ticket' not in kw or p.ticket == kw['ticket'])
    def orders_get(self, **kw): return tuple(self.orders)
    def history_deals_get(self, **kw):
        return tuple(d for d in self.deals if ('position' not in kw or d.position_id == kw['position'])
                     and ('ticket' not in kw or d.order == kw['ticket']))
    def order_calc_profit(self, kind, symbol, lot, entry, exit_price):
        return lot*(exit_price-entry)*(1 if kind == 0 else -1)
    def order_check(self, request):
        self.checks.append(dict(request)); return NS(retcode=self.checkcode)
    def order_send(self, request):
        self.sends.append(dict(request))
        if self.raise_send: raise RuntimeError('do-not-expose-secret')
        if request['action'] == self.TRADE_ACTION_SLTP:
            p = self.positions[0]; p.sl = request['sl']; p.tp = request['tp']
            return NS(retcode=self.retcode)
        volume = request['volume']/2 if self.partial else request['volume']
        self.positions = [NS(ticket=30, identifier=self.position_id, magic=MAGIC, symbol='BTCUSD',
                             price_open=request['price'],
                             type=request['type'], volume=volume, profit=0., swap=0.,
                             sl=0. if self.omit_sl else request['sl'], tp=0. if self.omit_tp else request['tp'])]
        self.deals = [NS(ticket=40, order=self.order_id, position_id=self.position_id, magic=MAGIC,
                         symbol='BTCUSD', type=request['type'], entry=0, volume=volume,
                         profit=0., commission=0., swap=0., fee=0.)]
        return NS(retcode=self.retcode, order=self.order_id, deal=40, volume=volume)
    def exit(self, loss=-.5, partial=False):
        volume = self.positions[0].volume
        self.deals.append(NS(ticket=50, order=11, position_id=self.position_id, magic=MAGIC,
            symbol='BTCUSD', type=1-self.positions[0].type, entry=1, volume=volume/2 if partial else volume,
            profit=loss, commission=-.1, swap=0., fee=0.))
        if partial: self.positions[0].volume /= 2
        else: self.positions = []


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name)/'ledger.sqlite'
        self.clock = FakeClock(); self.sdk = FakeSDK()
        self.journal = Journal(self.file)
        self.adapter = MT5DemoAdapter(self.sdk, self.journal, policy(), execute=True,
                                     clock=self.clock, wall=self.clock)
        for _ in range(3): self.adapter.snapshot()
        self.adapter.begin_run()
        self.signal = Signal('closed-bar-1', 'BUY', D('900'), D('1200'), symbol='BTCUSD')
    def tearDown(self): self.tmp.cleanup()
    def submit(self): return self.adapter.submit_once(self.signal, D('.01'))

    def test_readonly_no_check_or_send(self):
        self.adapter.execute = False
        self.adapter.snapshot(); self.adapter.quote_risk(self.signal, D('.01'))
        with self.assertRaises(Blocked): self.submit()
        with self.assertRaises(Blocked): self.adapter.tighten_stop(30, D('950'))
        self.assertEqual((self.sdk.checks, self.sdk.sends), ([], []))

    def test_ticket_bound_entry_and_hold(self):
        self.assertEqual(self.submit(), 'CONFIRMED')
        s = self.adapter.snapshot()
        self.assertTrue(s.session_reconciled)
        self.assertTrue(s.positions[0].owned)
        self.assertEqual((s.positions[0].stop, s.positions[0].target), (D('900'), D('1200')))
        self.assertEqual(len(self.sdk.sends), 1)

    def test_restart_reconciles_open_then_broker_exit(self):
        self.assertEqual(self.submit(), 'CONFIRMED')
        other = MT5DemoAdapter(self.sdk, Journal(self.file), policy(), clock=self.clock, wall=self.clock)
        self.assertTrue(other.snapshot().positions[0].owned)
        self.sdk.exit()
        self.assertEqual(other.snapshot().positions, ())
        self.assertEqual(other.snapshot().session_loss, D('.6'))
        self.assertEqual(other.execution_state()['entries_reserved'], 1)

    def test_duplicate_survives_closed_position_restart(self):
        self.submit(); self.sdk.exit(); self.adapter.snapshot()
        other = MT5DemoAdapter(self.sdk, Journal(self.file), policy(), execute=True,
                               clock=self.clock, wall=self.clock)
        for _ in range(3): other.snapshot()
        other.begin_run()
        with self.assertRaises(Blocked): other.submit_once(self.signal, D('.01'))
        self.assertEqual(len(self.sdk.sends), 1)

    def test_two_journals_cannot_reserve_two_positions(self):
        self.journal.reserve(policy(), digest('a'), 'BUY', D('.01'), D('900'), D('1200'), 100)
        with self.assertRaises(Blocked):
            Journal(self.file).reserve(policy(), digest('b'), 'BUY', D('.01'), D('900'), D('1200'), 100)

    def test_crash_reservation_sticky_even_if_flat(self):
        self.journal.reserve(policy(), digest('a'), 'BUY', D('.01'), D('900'), D('1200'), 100)
        other = MT5DemoAdapter(self.sdk, Journal(self.file), policy(), clock=self.clock)
        self.assertFalse(other.snapshot().session_reconciled)
        self.assertTrue(other.execution_state()['reconciliation_required'])

    def test_partial_placed_rejected_missing_protection_unknown(self):
        for field, value in (('partial', True), ('retcode', 10008), ('retcode', 10010),
                             ('retcode', 10006), ('omit_sl', True), ('omit_tp', True), ('raise_send', True)):
            with self.subTest(field=field, value=value):
                sdk = FakeSDK(); setattr(sdk, field, value)
                journal = Journal(Path(self.tmp.name)/(field+str(value)+'.sqlite'))
                a = MT5DemoAdapter(sdk, journal, policy(), execute=True, clock=self.clock, wall=self.clock)
                for _ in range(3): a.snapshot()
                a.begin_run()
                self.assertEqual(a.submit_once(self.signal, D('.01')), 'UNKNOWN')
                self.assertTrue(a.execution_state()['reconciliation_required'])
                with self.assertRaises(Blocked): a.submit_once(self.signal, D('.01'))
                self.assertEqual(len(sdk.sends), 1)

    def test_rejected_check_no_send_no_retry(self):
        self.sdk.checkcode = 1
        self.assertEqual(self.submit(), 'UNKNOWN')
        self.assertEqual(self.sdk.sends, [])
        with self.assertRaises(Blocked): self.submit()

    def test_wrong_account_real_terminal_currency_blocks_reads(self):
        for field, value in (('trade_mode', 2), ('server', 'wrong'), ('currency', 'EUR')):
            original = getattr(self.sdk.account, field); setattr(self.sdk.account, field, value)
            with self.assertRaises(Blocked): self.adapter.snapshot()
            setattr(self.sdk.account, field, original)
        self.sdk.terminal.data_path = 'wrong'
        with self.assertRaises(Blocked): self.adapter.snapshot()
        self.assertEqual(self.sdk.sends, [])

    def test_restart_account_binding_mismatch(self):
        self.sdk.account.login = 456
        other = MT5DemoAdapter(self.sdk, Journal(self.file), clock=self.clock)
        with self.assertRaises(Blocked): other.snapshot()

    def test_exact_lot_not_increased(self):
        with self.assertRaises(Blocked): self.adapter.quote_risk(self.signal, D('.015'))
        self.sdk.info.volume_min = .1
        with self.assertRaises(Blocked): self.adapter.quote_risk(self.signal, D('.01'))
        self.assertEqual(self.sdk.sends, [])

    def test_currency_conversion_buy_sell(self):
        for side in ('BUY', 'SELL'):
            signal = self.adapter.currency_signal('conversion-'+side, side, D('.01'))
            risk = self.adapter.quote_risk(signal, D('.01'))
            self.assertTrue(risk.valid_protective_stop and risk.valid_take_profit)
            self.assertLessEqual(risk.stop_loss_usd, D('1'))
            self.assertEqual(signal.stop % D('.01'), 0)

    def test_minimum_stop_conflict_not_widened(self):
        self.sdk.info.trade_stops_level = 20000
        with self.assertRaises(Blocked): self.adapter.currency_signal('x', 'BUY', D('.01'))
        self.assertEqual(self.sdk.sends, [])

    def test_protective_update_preserves_tp_and_reconciles(self):
        self.submit()
        self.assertEqual(self.adapter.tighten_stop(30, D('950')), 'CONFIRMED')
        self.assertEqual(self.sdk.positions[0].tp, 1200.)
        self.assertTrue(self.adapter.snapshot().session_reconciled)
        with self.assertRaises(Blocked): self.adapter.tighten_stop(30, D('940'))

    def test_history_missing_or_foreign_volume_blocks(self):
        self.submit(); self.sdk.deals = []
        with self.assertRaises(Blocked): self.adapter.snapshot()

    def test_partial_exit_never_flat(self):
        self.submit(); self.sdk.exit(partial=True)
        s = self.adapter.snapshot()
        self.assertEqual(len(s.positions), 1)
        self.assertTrue(s.positions[0].owned)

    def test_session_duration_survives_restart(self):
        self.clock.value = 161
        other = MT5DemoAdapter(self.sdk, Journal(self.file), policy(), execute=True,
                               clock=self.clock, wall=self.clock)
        with self.assertRaises(Blocked): other.begin_run()

    def test_clock_rollback_and_policy_change_block(self):
        self.clock.value = 99
        with self.assertRaises(Blocked): self.adapter.begin_run()
        self.clock.value = 100
        self.adapter.policy = replace(policy(), tp_profit_usd=D('3'))
        with self.assertRaises(Blocked): self.adapter.begin_run()

    def test_unset_schema_blocks(self):
        raw = json.loads(Path(__file__).with_name('demo_test_policy.unset.json').read_text())
        with self.assertRaises(Blocked): DemoTestPolicy.parse(raw)

    def test_persistent_loss_budget_blocks_next_entry(self):
        self.submit(); self.sdk.exit(loss=-1.1); self.adapter.snapshot()
        with self.assertRaises(Blocked):
            self.adapter.submit_once(replace(self.signal, key='next'), D('.01'))
        self.assertEqual(len(self.sdk.sends), 1)

    def test_snapshot_receipt_not_relabelled_after_slow_history(self):
        self.submit()
        original = self.sdk.history_deals_get
        def slow(**kw):
            result = original(**kw)
            self.clock.value += 2
            return result
        self.sdk.history_deals_get = slow
        s = self.adapter.snapshot()
        self.assertGreaterEqual(self.clock()-s.receipt_at, 2)

    def test_adverse_fill_fails_actual_sl_risk_confirmation(self):
        original = self.sdk.order_send
        def adverse(request):
            result = original(request)
            self.sdk.positions[0].price_open += 100
            return result
        self.sdk.order_send = adverse
        self.assertEqual(self.submit(), 'UNKNOWN')
        self.assertTrue(self.adapter.execution_state()['reconciliation_required'])

    def test_slow_profit_calculation_expires_quote_before_order_check(self):
        original = self.sdk.order_calc_profit
        def slow(*args):
            result = original(*args)
            self.clock.value += 2
            return result
        self.sdk.order_calc_profit = slow
        with self.assertRaises(Blocked): self.submit()
        self.assertEqual((self.sdk.checks, self.sdk.sends), ([], []))

    def test_permission_revoked_during_protection_check_no_send(self):
        self.submit()
        original = self.sdk.order_check
        def revoked(request):
            result = original(request)
            self.sdk.terminal.tradeapi_disabled = True
            return result
        self.sdk.order_check = revoked
        self.assertEqual(self.adapter.tighten_stop(30, D('950')), 'UNKNOWN')
        self.assertEqual(len(self.sdk.sends), 1)


if __name__ == '__main__': unittest.main()
