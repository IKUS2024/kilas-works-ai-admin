import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal as D
from demo_instrument_profiles import (mapping, broker_facts, broker_specs,
                                      minimum_notional, price_distance_for_usd)
from demo_auto_controller import Blocked,Signal,Controller
from mt5_demo_adapter import MT5DemoAdapter,Journal
from test_mt5_demo_adapter import FakeSDK,FakeClock,policy

class GoldSDK(FakeSDK):
    def __init__(self):
        super().__init__(); self.info.name='GOLD'; self.info.trade_contract_size=100
        self.info.volume_max=50.; self.tick.bid=4195.2; self.tick.ask=4195.59
    def order_calc_profit(self,kind,symbol,lot,entry,exit_price):
        if symbol!='GOLD': raise AssertionError('Wrong instrument mapping')
        return lot*self.info.trade_contract_size*(exit_price-entry)*(1 if kind==0 else -1)

class ProfileTests(unittest.TestCase):
    def test_explicit_mapping_no_alias_guess_or_activation(self):
        self.assertEqual((mapping('GOLD').model_symbol,mapping('GOLD').broker_symbol),('XAUUSD','GOLD'))
        self.assertFalse(mapping('GOLD').order_transport_supported)
        for unknown in ('XAUUSD','gold','GOLDmicro','EURUSD'):
            with self.assertRaises(Blocked): mapping(unknown)
    def test_actual_contract_drives_units_not_btc_multiplier(self):
        gold=GoldSDK(); btc=FakeSDK()
        self.assertEqual(minimum_notional(gold.info,'4195.59'),D('4195.5900'))
        self.assertEqual(minimum_notional(btc.info,'82844.15'),D('828.4415'))
        self.assertEqual(price_distance_for_usd('2','1'),D('2'))
        self.assertEqual(price_distance_for_usd('2','.01'),D('200'))
        facts=broker_facts(mapping('GOLD'),gold.info)
        self.assertEqual(facts['contract_size'],'100')
        gold.info.name='XAUUSD'
        with self.assertRaises(Blocked): broker_facts(mapping('GOLD'),gold.info)
    def test_gold_readonly_adapter_and_usd_risk_block_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            sdk=GoldSDK(); clock=FakeClock()
            p=replace(policy(),sl_loss_usd=D('2'),tp_profit_usd=D('1'))
            adapter=MT5DemoAdapter(sdk,Journal(tmp+'/gold.sqlite'),p,instrument='GOLD',clock=clock,wall=clock)
            for _ in range(3): s=adapter.snapshot()
            self.assertEqual(s.symbol,'GOLD')
            risk=adapter.quote_risk(Signal('fixture','BUY',D('4194.59'),D('4197.59'),symbol='GOLD'),D('.01'))
            self.assertGreater(risk.notional_usd,D('2000'))
            self.assertAlmostEqual(float(risk.stop_loss_usd),1.,places=7)
            controller=Controller(adapter,clock=clock)
            self.assertEqual(controller.start()['state'],'OFF')
            adapter.execute=True # Mutation cannot bypass the independent GOLD guard.
            with self.assertRaisesRegex(Blocked,'INSTRUMENT_EXECUTION_UNREVIEWED'): adapter.submit_once(Signal('fake','BUY',D('4194'),D('4200'),symbol='GOLD'),D('.01'))
            with self.assertRaises(Blocked): adapter.tighten_stop(30,D('4195'))
            with self.assertRaises(Blocked): adapter.begin_run()
            self.assertEqual((sdk.checks,sdk.sends),([],[]))
    def test_gold_execute_constructor_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(Blocked): MT5DemoAdapter(GoldSDK(),Journal(tmp+'/gold.sqlite'),policy(),instrument='GOLD',execute=True)
    def test_instrument_journal_cannot_be_reused_between_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Journal(tmp+'/ledger.sqlite'); MT5DemoAdapter(FakeSDK(),ledger)
            with self.assertRaisesRegex(Blocked,'JOURNAL_INSTRUMENT_MISMATCH'):
                MT5DemoAdapter(GoldSDK(),ledger,instrument='GOLD')


class BrokerSpecificationTests(unittest.TestCase):
    def test_mapping_must_match_all_reviewed_fields(self):
        for change in (dict(broker_symbol='XAUUSD'), dict(model_symbol='GOLD'),
                       dict(order_transport_supported=True),
                       dict(order_transport_supported=0), dict(logical='gold')):
            with self.subTest(change=change):
                with self.assertRaisesRegex(Blocked, '^INSTRUMENT_MAPPING_UNREVIEWED$'):
                    broker_facts(replace(mapping('GOLD'), **change), GoldSDK().info)
        with self.assertRaisesRegex(Blocked, '^INSTRUMENT_MAPPING_UNREVIEWED$'):
            broker_facts(None, GoldSDK().info)

    def test_exact_broker_symbol_and_usd_units_required(self):
        for field, value in (('name', 'XAUUSD'), ('name', 'GOLDmicro'),
                             ('name', 'gold'), ('name', None), ('custom', True),
                             ('custom', 0), ('currency_profit', 'EUR'),
                             ('currency_margin', 'usd')):
            with self.subTest(field=field, value=value):
                info = GoldSDK().info
                setattr(info, field, value)
                for inspect in (lambda: broker_facts(mapping('GOLD'), info),
                                lambda: minimum_notional(info, '4195.59')):
                    with self.assertRaisesRegex(Blocked, '^BROKER_SYMBOL_OR_UNITS_UNVERIFIED$'):
                        inspect()
        with self.assertRaisesRegex(Blocked, '^BROKER_SYMBOL_OR_UNITS_UNVERIFIED$'):
            broker_facts(mapping('GOLD'), None)

    def test_missing_identity_or_unit_fields_have_fixed_code(self):
        for field in ('name', 'custom', 'currency_profit', 'currency_margin'):
            with self.subTest(field=field):
                info = GoldSDK().info
                delattr(info, field)
                with self.assertRaisesRegex(Blocked, '^BROKER_SYMBOL_OR_UNITS_UNVERIFIED$'):
                    broker_facts(mapping('GOLD'), info)

    def test_numeric_fields_reject_nonpositive_nonfinite_and_wrong_types(self):
        fields = ('volume_min', 'volume_max', 'volume_step', 'trade_contract_size',
                  'point', 'trade_tick_size')
        invalid = (0, -1, True, None, '', 'bad', float('inf'), float('nan'),
                   D('sNaN'), D('-Infinity'), object())
        for field in fields:
            for value in invalid:
                with self.subTest(field=field, value=value):
                    info = GoldSDK().info
                    setattr(info, field, value)
                    with self.assertRaisesRegex(Blocked, '^BROKER_NUMBER_INVALID$'):
                        broker_facts(mapping('GOLD'), info)
            with self.subTest(missing=field):
                info = GoldSDK().info
                delattr(info, field)
                with self.assertRaisesRegex(Blocked, '^BROKER_NUMBER_INVALID$'):
                    broker_specs(info)

    def test_volume_bounds_and_minimum_grid_are_consistent(self):
        for field, value in (('volume_max', '.009'), ('volume_min', '.015'),
                             ('volume_step', '.02'), ('volume_step', '.003')):
            with self.subTest(field=field, value=value):
                info = GoldSDK().info
                setattr(info, field, value)
                for inspect in (lambda: broker_facts(mapping('GOLD'), info),
                                lambda: minimum_notional(info, '4195.59')):
                    with self.assertRaisesRegex(Blocked, '^BROKER_VOLUME_SPEC_INVALID$'):
                        inspect()

    def test_maximum_is_a_bound_and_actual_minimum_has_no_ui_substitution(self):
        info = GoldSDK().info
        info.volume_max = '50.005'
        self.assertEqual(broker_facts(mapping('GOLD'), info)['volume_max'], '50.005')
        info.volume_min = '.001'
        info.volume_step = '.001'
        self.assertEqual(minimum_notional(info, '4195.59'), D('419.559'))
        self.assertEqual(broker_facts(mapping('GOLD'), info)['volume_min'], '0.001')

    def test_tick_is_an_integer_multiple_of_broker_point(self):
        for value in ('.001', '.015'):
            with self.subTest(tick=value):
                info = GoldSDK().info
                info.trade_tick_size = value
                with self.assertRaisesRegex(Blocked, '^BROKER_PRICE_SPEC_INVALID$'):
                    broker_facts(mapping('GOLD'), info)
        info = GoldSDK().info
        info.point = '.001'
        info.trade_tick_size = '.005'
        facts = broker_facts(mapping('GOLD'), info)
        self.assertEqual((facts['point'], facts['tick_size']), ('0.001', '0.005'))
        self.assertEqual(minimum_notional(info, '4195.590'), D('4195.590'))

    def test_stops_and_freeze_are_required_nonnegative_integer_points(self):
        for field, code in (('trade_stops_level', 'STOPS_INVALID'),
                            ('trade_freeze_level', 'FREEZE_INVALID')):
            for value in (-1, True, 0.0, 1.5, '0', None, D('1')):
                with self.subTest(field=field, value=value):
                    info = GoldSDK().info
                    setattr(info, field, value)
                    with self.assertRaisesRegex(Blocked, '^' + code + '$'):
                        minimum_notional(info, '4195.59')
            with self.subTest(missing=field):
                info = GoldSDK().info
                delattr(info, field)
                with self.assertRaisesRegex(Blocked, '^' + code + '$'):
                    broker_facts(mapping('GOLD'), info)
        info = GoldSDK().info
        info.trade_stops_level = 0
        info.trade_freeze_level = 123
        facts = broker_facts(mapping('GOLD'), info)
        self.assertEqual(facts['trade_stops_level_points'], 0)
        self.assertEqual(facts['trade_freeze_level_points'], 123)

    def test_minimum_notional_rejects_bad_or_off_grid_ask(self):
        for ask in (0, -1, True, None, 'bad', 'NaN', 'Infinity'):
            with self.subTest(ask=ask):
                with self.assertRaisesRegex(Blocked, '^BROKER_NUMBER_INVALID$'):
                    minimum_notional(GoldSDK().info, ask)
        with self.assertRaisesRegex(Blocked, '^BROKER_QUOTE_GRID_INVALID$'):
            minimum_notional(GoldSDK().info, '4195.591')

    def test_actual_contract_and_historical_cap_conflict_are_preserved(self):
        info = GoldSDK().info
        notional = minimum_notional(info, '4195.59')
        self.assertEqual(notional, D('4195.59'))
        self.assertGreater(notional, policy().controller.max_notional_usd)
        self.assertEqual(policy().controller.max_notional_usd, D('2000'))
        # Changing supplied units changes the result; no GOLD constant is used.
        info.trade_contract_size = '10'
        self.assertEqual(minimum_notional(info, '4195.59'), D('419.559'))

    def test_decimal_arithmetic_failure_has_fixed_code(self):
        info = GoldSDK().info
        info.trade_contract_size = D('1e999999')
        with self.assertRaisesRegex(Blocked, '^BROKER_NUMBER_INVALID$'):
            minimum_notional(info, '4195.59')
        info.trade_contract_size = D('1.12345678901234567890123456789')
        with self.assertRaisesRegex(Blocked, '^BROKER_NUMBER_INVALID$'):
            minimum_notional(info, '4195.59')

if __name__=='__main__': unittest.main()
