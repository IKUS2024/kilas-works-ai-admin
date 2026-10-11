"""Readonly BTC v2 evidence from an already injected, pinned DEMO adapter.

Construction does no reads or SDK attachment. The caller must invoke collect
only after receiving its server capture challenge. Raw broker OPEN epochs are
preserved; local capture timestamps do not establish broker-to-UTC mapping.
"""
import re
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, Inexact, localcontext
from numbers import Integral, Real

from demo_auto_controller import Blocked
from demo_instrument_profiles import broker_facts, mapping


def _need(condition):
    if not condition:
        raise Blocked('BTC_CAPTURE_REJECTED')


def _utcnow():
    return datetime.now(timezone.utc)


def _utc_text(value):
    _need(isinstance(value, datetime) and value.tzinfo is not None
          and value.utcoffset() == timedelta(0))
    return value.isoformat().replace('+00:00', 'Z')


def _integer(value, *, minimum=0, maximum=None):
    # MT5 rates contain numpy integer scalars. Accept integral values without
    # importing numpy, but never truncate floats or accept bool as a count.
    _need(isinstance(value, Integral) and not isinstance(value, bool))
    value = int(value)
    _need(value >= minimum and (maximum is None or value <= maximum))
    return value


def _decimal(value, *, positive=True):
    _need(isinstance(value, (str, Decimal, Real)) and not isinstance(value, bool))
    result = Decimal(str(value))
    _need(result.is_finite() and (result > 0 if positive else result >= 0))
    # Any individual field this large cannot fit the v2 8192-byte wire limit.
    _need(len(result.as_tuple().digits) <= 8192 and abs(result.adjusted()) <= 8192)
    return result


def _canonical(value):
    text = format(_decimal(value), 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _cents(value, *, positive=True):
    value = _decimal(value, positive=positive)
    with localcontext() as context:
        context.prec = max(28, len(value.as_tuple().digits) + 3)
        context.traps[Inexact] = True
        cents = value * 100
        _need(cents == cents.to_integral_value())
    return int(cents)


def _price(value, grid):
    value = _decimal(value)
    _cents(value)
    with localcontext() as context:
        context.prec = max(28, len(value.as_tuple().digits)
                           + abs(value.as_tuple().exponent)
                           + abs(grid.as_tuple().exponent) + 3)
        _need(value % grid == 0)
    return _canonical(value)


def spec_from_info(info, *, cost_bound_cents, verified_at, instrument='BTC'):
    """Pure conversion of verified broker BTC facts to the exact v2 spec."""
    try:
        from btc_integration_protocol import contract_hash

        facts = broker_facts(mapping(instrument), info)
        _need(info.select is True and info.visible is True
              and type(info.trade_mode) is int and info.trade_mode == 4)
        if cost_bound_cents is not None:
            _need(type(cost_bound_cents) is int and cost_bound_cents >= 0)
        with localcontext() as context:
            context.traps[Inexact] = True
            distance = Decimal(facts['point']) * max(
                facts['trade_stops_level_points'], facts['trade_freeze_level_points'])
        spec = dict(symbol=mapping(instrument).broker_symbol,
                    **{key: _canonical(facts[key]) for key in
                       ('contract_size', 'volume_min', 'volume_max', 'volume_step')},
                    tick_cents=_cents(facts['tick_size']),
                    stops_distance_cents=_cents(distance, positive=False),
                    cost_bound_cents=cost_bound_cents, verified_at=verified_at)
        contract_hash(spec,instrument=instrument)  # Validate the exact wire shape.
        return spec
    except Exception:
        raise Blocked('BTC_CAPTURE_SPEC_REJECTED') from None


class BTCMarketCapture:
    def __init__(self, adapter, risk_provider=None, *, cost_bound_cents=None,
                 policy_version=None, clock_ns=time.perf_counter_ns, now=_utcnow, instrument='BTC'):
        self.profile = mapping(instrument)
        self.adapter = adapter
        self.risk_provider = risk_provider
        self.cost_bound_cents = cost_bound_cents
        self.policy_version = policy_version
        self.clock_ns = clock_ns
        self.now = now

    def collect(self):
        """Capture after a server challenge; never creates or sends one."""
        try:
            return self._collect()
        except Exception:
            # Provider/SDK exceptions can contain account details. Only a fixed
            # rejection crosses this producer boundary; no partial evidence.
            raise Blocked('BTC_CAPTURE_REJECTED') from None

    def _collect(self):
        from btc_integration_protocol import contract_hash, validate_evidence_request

        _need(callable(self.risk_provider) and callable(self.clock_ns) and callable(self.now))
        _need(type(self.policy_version) is str
              and re.fullmatch('[0-9a-f]{64}', self.policy_version))
        if self.cost_bound_cents is not None:
            _need(type(self.cost_bound_cents) is int and self.cost_bound_cents >= 0)
        _need(self.adapter.symbol == self.profile.broker_symbol and self.adapter.profile == self.profile)
        _need(self.profile.logical=='BTC' or self.adapter.execute is False)
        with self.adapter.lock:
            start_ns = _integer(self.clock_ns(), minimum=1)
            start_utc = _utc_text(self.now())
            info, raw_tick, _ = self.adapter.market()
            spec = spec_from_info(info, cost_bound_cents=self.cost_bound_cents,
                                  verified_at=start_utc,instrument=self.profile.logical)
            grid = Decimal(spec['tick_cents']) / 100
            tick = dict(time=_integer(raw_tick.time, minimum=1),
                        time_msc=_integer(raw_tick.time_msc, minimum=1),
                        bid=_price(raw_tick.bid, grid), ask=_price(raw_tick.ask, grid))
            rates = self.adapter.read(self.adapter.sdk.copy_rates_from_pos,
                                      self.profile.broker_symbol, self.adapter.sdk.TIMEFRAME_M1, 1, 12)
            _need(len(rates) == 12)
            bars = [dict(time=_integer(row['time'], minimum=1),
                         **{key: _price(row[key], grid)
                            for key in ('open', 'high', 'low', 'close')}) for row in rates]

            snapshot = self.adapter.snapshot()
            _need(snapshot.symbol == self.profile.broker_symbol and snapshot.connected is True
                  and snapshot.terminal_binding_verified is True
                  and snapshot.identity.mode == 'DEMO' and snapshot.identity.currency == 'USD'
                  and snapshot.session_reconciled is True
                  and type(snapshot.pending_orders) is int and snapshot.pending_orders == 0)
            _need(type(snapshot.positions) is tuple)
            position_open = bool(snapshot.positions)
            protection_active = position_open and all(
                position.side in ('BUY', 'SELL')
                and _decimal(position.stop) > 0 and _decimal(position.target) > 0
                for position in snapshot.positions)
            _need(not position_open or protection_active)
            supplied = self.risk_provider(snapshot)
            _need(type(supplied) is dict and set(supplied) == {
                'daily_loss_remaining_cents', 'strategy_verified',
                'cooldown_clear', 'loss_streak_clear'})
            _need(type(supplied['daily_loss_remaining_cents']) is int)
            _integer(supplied['daily_loss_remaining_cents'], maximum=50000)
            for key in ('strategy_verified', 'cooldown_clear', 'loss_streak_clear'):
                _need(type(supplied[key]) is bool)
            supplied = dict(supplied)

            # Re-read the exact units after snapshot/provider work. A metadata
            # change invalidates the whole capture instead of mixing contracts.
            current = spec_from_info(self.adapter.read(self.adapter.sdk.symbol_info, self.profile.broker_symbol),
                                     cost_bound_cents=self.cost_bound_cents, verified_at=start_utc,
                                     instrument=self.profile.logical)
            _need(contract_hash(current,instrument=self.profile.logical) ==
                  contract_hash(spec,instrument=self.profile.logical))
            _need(snapshot.specs.minimum == Decimal(spec['volume_min'])
                  and snapshot.specs.maximum == Decimal(spec['volume_max'])
                  and snapshot.specs.step == Decimal(spec['volume_step']))
            end_utc = _utc_text(self.now())
            end_ns = _integer(self.clock_ns(), minimum=1)
            spec['verified_at'] = end_utc

        market = dict(symbol=self.profile.broker_symbol, timeframe='M1', tick=tick,
                      capture=dict(start_utc=start_utc, end_utc=end_utc,
                                   start_mono_ns=start_ns, end_mono_ns=end_ns),
                      candles=bars, clock=None, clock_profile=None)
        risk = dict(captured_at=end_utc, position_open=position_open,
                    protection_active=protection_active, **supplied,
                    broker_contract_sha256=contract_hash(spec,instrument=self.profile.logical), policy_version=self.policy_version)
        capture = dict(market=market, spec=spec, risk=risk)
        # This local validation envelope is discarded. Its sentinel IDs are
        # never returned, sent, or accepted as the caller's actual challenge.
        validate_evidence_request(dict(
            schema_version=2, session_id='0' * 32, revision=0, command_id=None,
            instrument=self.profile.logical, lot='0.01', sequence=1, challenge='0' * 64,
            account_mode='DEMO', terminal_connected=True, **capture),instrument=self.profile.logical)
        return capture
