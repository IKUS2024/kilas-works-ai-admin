"""Code-only DEMO controller. No MT5 import, adapter, credentials or endpoint.

The existing XAUUSD replay is not a BTCUSD broker strategy. Consequently the
shipped controller has no policy/strategy and cannot start. Dependency seams
below support fake-broker verification and a separately reviewed integration.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import isfinite
from threading import RLock, Lock, Event
from time import perf_counter


class Blocked(ValueError):
    pass


def number(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise Blocked('INVALID_NUMBER') from None
    if not result.is_finite() or result <= 0:
        raise Blocked('INVALID_NUMBER')
    return result


def nonnegative(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise Blocked('INVALID_NUMBER') from None
    if not result.is_finite() or result < 0:
        raise Blocked('INVALID_NUMBER')
    return result


@dataclass(frozen=True)
class Identity:
    mode: str
    server: str
    currency: str
    company: str
    # Private account binding is supplied in memory; never included in status.
    binding: object


@dataclass(frozen=True)
class Specs:
    minimum: Decimal
    maximum: Decimal
    step: Decimal

    def validate(self, lot):
        lot = number(lot)
        low, high, step = map(number, (self.minimum, self.maximum, self.step))
        if low > high or not low <= lot <= high or lot % step != 0:
            raise Blocked('LOT_OUTSIDE_BROKER_RULES')
        if lot < Decimal('0.01'):
            raise Blocked('LOT_BELOW_UI_MINIMUM')


@dataclass(frozen=True)
class Position:
    key: object
    side: str
    stop: Decimal | None
    owned: bool
    target: Decimal | None = None


@dataclass(frozen=True)
class Snapshot:
    identity: Identity
    connected: bool
    receipt_at: float
    specs: Specs
    positions: tuple
    pending_orders: int
    session_loss: Decimal
    # Reconciliation must cover this controller's complete session, including
    # realized losses and current adverse P/L. Unknown history blocks entries.
    session_reconciled: bool
    liveness_verified: bool
    symbol: str = 'BTCUSD'
    terminal_binding_verified: bool = False
    execution_permissions_verified: bool = False


@dataclass(frozen=True)
class Policy:
    """Required future review inputs. No executable defaults are supplied."""
    strategy_reference: str
    max_run_seconds: float
    max_entries: int
    session_loss_usd: Decimal
    max_tick_receipt_age: float
    max_stop_loss_usd: Decimal
    max_notional_usd: Decimal
    max_spread_cost_usd: Decimal

    def validate(self):
        if not self.strategy_reference or type(self.max_entries) is not int or self.max_entries <= 0:
            raise Blocked('POLICY_INVALID')
        for value in (self.max_run_seconds, self.max_tick_receipt_age,
                      self.session_loss_usd, self.max_stop_loss_usd,
                      self.max_notional_usd, self.max_spread_cost_usd):
            number(value)
        # Retain the previously reviewed smoke ceilings as stricter safety
        # bounds only. They do not authorize recurring trading.
        if (number(self.max_stop_loss_usd) > 2 or number(self.max_notional_usd) > 2000
                or number(self.max_spread_cost_usd) > 1):
            raise Blocked('EXISTING_RISK_CEILING_EXCEEDED')


@dataclass(frozen=True)
class Signal:
    key: str  # Stable closed-bar/strategy decision key, never raw tick time.
    side: str
    stop: Decimal
    target: Decimal | None = None
    # A missing binding is never inferred from the selected adapter.
    symbol: str | None = None


@dataclass(frozen=True)
class Risk:
    stop_loss_usd: Decimal
    notional_usd: Decimal
    spread_cost_usd: Decimal
    valid_protective_stop: bool
    valid_take_profit: bool = False


class Controller:
    """Serialized, in-process control seam; default OFF and execution blocked.

    Future broker adapter contract: snapshot() is freshly read, quote_risk()
    uses broker contract/profit calculations, submit_once() returns CONFIRMED
    only after ticket-bound fill and broker SL/TP reconciliation. Any ambiguous
    result stops and requires manual reconciliation, with no automatic retry.
    tighten_stop() must preserve TP and may only improve the existing stop.
    The separate MT5 adapter defaults read-only; no strategy is activated here.
    """
    def __init__(self, broker=None, strategy=None, policy=None, *, clock=perf_counter):
        self.broker, self.strategy, self.policy = broker, strategy, policy
        self.clock = clock
        self.lot = Decimal('0.01')
        self.on = False
        self.deadline = None
        self.entries = 0
        self.seen = set()
        self.binding = None
        self.reason = 'OFF'
        self.connected = False
        self.protection = 'UNKNOWN'
        self.reconciliation_required = False
        self.events = []
        self.lock = RLock()
        self.entry_gate = Lock()
        self.entry_revoked = Event()
        self.entry_revoked.set()
        self.stop_generation = 0
        self.authority_guard = None
        bind_guard = getattr(broker, 'bind_entry_guard', None)
        if callable(bind_guard):
            bind_guard(self.entry_allowed)

    def entry_allowed(self):
        """Lock-free veto, including while strategy/SDK work holds self.lock."""
        deadline = self.deadline
        try:
            authorized = self.authority_guard is None or self.authority_guard() is True
        except Exception:
            authorized = False
        return (authorized and not self.entry_revoked.is_set() and self.on and deadline is not None
                and self.clock() < deadline)

    def bind_authority_guard(self, guard):
        if not callable(guard) or self.authority_guard is not None:
            raise Blocked('ENTRY_AUTHORITY_BINDING_INVALID')
        self.authority_guard = guard

    def _require_entry(self):
        if self.entry_revoked.is_set() or not self.on:
            raise Blocked('OFF_BROKER_PROTECTION_PRESERVED')
        if self.deadline is None or self.clock() >= self.deadline:
            raise Blocked('RUN_EXPIRED')
        if self.authority_guard is not None and self.authority_guard() is not True:
            raise Blocked('ENTRY_AUTHORITY_UNAVAILABLE')

    def _event(self, code):
        allowed = {'OFF', 'ON', 'OFF_BROKER_PROTECTION_PRESERVED',
                   'LOT_VALIDATED_ENTRY_RISK_STILL_REQUIRED', 'ENTRY_CONFIRMED_BY_ADAPTER',
                   'LOCAL_RECONCILIATION_REQUIRED', 'BTCUSD_STRATEGY_AND_SESSION_POLICY_MISSING',
                   'POLICY_INVALID', 'EXISTING_RISK_CEILING_EXCEEDED',
                   'NO_REVIEWED_BROKER_ADAPTER', 'DEMO_IDENTITY_REQUIRED',
                   'ACCOUNT_BINDING_CHANGED', 'DISCONNECTED_OR_INVALID_RECEIPT',
                   'RECEIPT_LIVENESS_UNVERIFIED', 'LOT_OUTSIDE_BROKER_RULES',
                   'LOT_BELOW_UI_MINIMUM', 'INVALID_NUMBER', 'INVALID_EXPOSURE_OR_LOSS',
                   'EXISTING_EXPOSURE', 'SESSION_RISK_BLOCKED', 'ENTRY_BUDGET_EXHAUSTED',
                   'START_READ_FAILED', 'PROTECTION_RECONCILIATION_REQUIRED', 'RUN_EXPIRED',
                   'UNPROTECTED_POSITION', 'EXPOSURE_BLOCKED', 'SIGNAL_INVALID',
                   'LOT_EXCEEDS_ENTRY_OR_SESSION_RISK', 'EXPOSURE_CHANGED',
                   'ADAPTER_OR_STRATEGY_FAILED', 'TERMINAL_OR_SYMBOL_UNVERIFIED',
                   'EXECUTION_PERMISSIONS_UNVERIFIED', 'TAKE_PROFIT_MISSING',
                   'SIGNAL_INSTRUMENT_MISMATCH', 'ENTRY_AUTHORITY_UNAVAILABLE'}
        if code not in allowed:
            code = 'INTERNAL_REJECTION'
        self.reason = code
        self.events.append(code)  # Sanitized fixed codes only, bounded memory.
        self.events[:] = self.events[-100:]

    def _off(self, reason):
        self.entry_revoked.set()
        self.on = False
        self.deadline = None
        self._event(reason)

    def _snapshot(self, *, freshness=None):
        if self.broker is None:
            self.connected = False
            raise Blocked('NO_REVIEWED_BROKER_ADAPTER')
        self.connected = False
        s = self.broker.snapshot()
        state_reader = getattr(self.broker, 'execution_state', None)
        if callable(state_reader):
            state = state_reader()
            self.entries = max(self.entries, state['entries_reserved'])
            self.reconciliation_required |= state['reconciliation_required']
        i = s.identity
        if s.symbol != 'BTCUSD' or s.terminal_binding_verified is not True:
            raise Blocked('TERMINAL_OR_SYMBOL_UNVERIFIED')
        if (i.mode != 'DEMO' or i.server != 'XMGlobal-MT5 10' or i.currency != 'USD'
                or i.company != 'XM Global Limited' or i.binding is None):
            raise Blocked('DEMO_IDENTITY_REQUIRED')
        if self.binding is not None and i.binding != self.binding:
            raise Blocked('ACCOUNT_BINDING_CHANGED')
        now = self.clock()
        if (s.connected is not True or type(s.receipt_at) not in (int, float)
                or not isfinite(s.receipt_at) or not isfinite(now) or s.receipt_at > now):
            raise Blocked('DISCONNECTED_OR_INVALID_RECEIPT')
        if freshness is not None and (now - s.receipt_at >= freshness or s.liveness_verified is not True):
            raise Blocked('RECEIPT_LIVENESS_UNVERIFIED')
        self.connected = True
        self.binding = i.binding
        s.specs.validate(self.lot)
        if (type(s.pending_orders) is not int or s.pending_orders < 0
                or not isinstance(s.session_loss, Decimal) or not s.session_loss.is_finite()
                or s.session_loss < 0):
            raise Blocked('INVALID_EXPOSURE_OR_LOSS')
        self.protection = ('UNPROTECTED' if any(p.stop is None or p.stop <= 0 for p in s.positions)
                           else 'BROKER_SL_ONLY' if any(p.target is None or p.target <= 0 for p in s.positions)
                           else 'BROKER_SL_TP_PRESENT' if s.positions else 'FLAT')
        return s

    def set_lot(self, value):
        with self.lock:
            if self.on:
                raise Blocked('STOP_BEFORE_LOT_CHANGE')
            lot = number(value)
            if lot < Decimal('0.01'):
                raise Blocked('LOT_BELOW_UI_MINIMUM')
            if self.broker is None:
                raise Blocked('LOT_UNVERIFIED_NO_BROKER_SPECS')
            previous = self.lot
            self.lot = lot
            try:
                self._snapshot()
            except Exception:
                self.lot = previous
                raise Blocked('LOT_VALIDATION_FAILED') from None
            self._event('LOT_VALIDATED_ENTRY_RISK_STILL_REQUIRED')

    def start(self):
        with self.lock:
            if self.on:
                return self.status()
            with self.entry_gate:
                generation = self.stop_generation
            try:
                if self.reconciliation_required:
                    raise Blocked('LOCAL_RECONCILIATION_REQUIRED')
                if self.policy is None or self.strategy is None:
                    raise Blocked('BTCUSD_STRATEGY_AND_SESSION_POLICY_MISSING')
                self.policy.validate()
                s = self._snapshot(freshness=self.policy.max_tick_receipt_age)
                if s.execution_permissions_verified is not True:
                    raise Blocked('EXECUTION_PERMISSIONS_UNVERIFIED')
                if s.positions or s.pending_orders:
                    raise Blocked('EXISTING_EXPOSURE')
                if s.session_reconciled is not True or s.session_loss >= self.policy.session_loss_usd:
                    raise Blocked('SESSION_RISK_BLOCKED')
                if self.entries >= self.policy.max_entries:
                    raise Blocked('ENTRY_BUDGET_EXHAUSTED')
                if self.reconciliation_required:
                    raise Blocked('LOCAL_RECONCILIATION_REQUIRED')
                begin = getattr(self.broker, 'begin_run', None)
                if callable(begin):
                    begin(self.policy)
                with self.entry_gate:
                    if generation != self.stop_generation:
                        raise Blocked('OFF_BROKER_PROTECTION_PRESERVED')
                    self.deadline = self.clock() + self.policy.max_run_seconds
                    self.entry_revoked.clear()
                    self.on = True
                    self._event('ON')
            except Blocked as exc:
                self._off(str(exc))
            except Exception:
                self._off('START_READ_FAILED')
            return self.status()

    def stop(self):
        # Do not wait behind model, snapshot, risk or order-check latency.
        # The adapter independently consults this veto before any entry send.
        with self.entry_gate:
            self.stop_generation += 1
            self.entry_revoked.set()
            self.on = False
        if self.lock.acquire(False):
            try: self._off('OFF_BROKER_PROTECTION_PRESERVED')
            finally: self.lock.release()
        return self.status()

    def poll(self):
        with self.lock:
            try:
                age = self.policy.max_tick_receipt_age if self.policy is not None else None
                s = self._snapshot(freshness=age)
                # OFF never clears SL/TP or closes a position. With a reviewed
                # protection provider it can tighten an owned existing SL.
                if self.strategy is not None and self.policy is not None:
                    for p in s.positions:
                        if not p.owned or p.stop is None or p.side not in ('BUY', 'SELL'):
                            continue
                        candidate = self.strategy.protective_stop(s, p)
                        if candidate is not None:
                            candidate = number(candidate)
                            if ((p.side == 'BUY' and candidate > p.stop)
                                    or (p.side == 'SELL' and candidate < p.stop)):
                                if self.broker.tighten_stop(p.key, candidate) != 'CONFIRMED':
                                    self.reconciliation_required = True
                                    raise Blocked('PROTECTION_RECONCILIATION_REQUIRED')
                if not self.on:
                    return self.status()
                if self.clock() >= self.deadline:
                    raise Blocked('RUN_EXPIRED')
                if s.execution_permissions_verified is not True:
                    raise Blocked('EXECUTION_PERMISSIONS_UNVERIFIED')
                if self.protection == 'UNPROTECTED':
                    raise Blocked('UNPROTECTED_POSITION')
                if self.protection == 'BROKER_SL_ONLY':
                    raise Blocked('TAKE_PROFIT_MISSING')
                if s.session_reconciled is not True or s.session_loss >= self.policy.session_loss_usd:
                    raise Blocked('SESSION_RISK_BLOCKED')
                if len(s.positions) > 1 or s.pending_orders or any(not p.owned for p in s.positions):
                    raise Blocked('EXPOSURE_BLOCKED')
                if s.positions:
                    return self.status()
                if self.entries >= self.policy.max_entries:
                    raise Blocked('ENTRY_BUDGET_EXHAUSTED')
                signal = self.strategy.decision(s)
                self._require_entry()
                if signal is None:
                    return self.status()
                if not isinstance(signal, Signal) or signal.symbol != s.symbol:
                    raise Blocked('SIGNAL_INSTRUMENT_MISMATCH')
                if (type(signal.key) is not str or not 1 <= len(signal.key) <= 128
                        or signal.side not in ('BUY', 'SELL')):
                    raise Blocked('SIGNAL_INVALID')
                if signal.key in self.seen:
                    return self.status()
                number(signal.stop)
                if signal.target is None:
                    raise Blocked('TAKE_PROFIT_MISSING')
                number(signal.target)
                risk = self.broker.quote_risk(signal, self.lot)
                self._require_entry()
                if (risk.valid_protective_stop is not True or risk.valid_take_profit is not True
                        or number(risk.stop_loss_usd) > self.policy.max_stop_loss_usd
                        or number(risk.notional_usd) > self.policy.max_notional_usd
                        or nonnegative(risk.spread_cost_usd) > self.policy.max_spread_cost_usd
                        or s.session_loss + risk.stop_loss_usd > self.policy.session_loss_usd):
                    raise Blocked('LOT_EXCEEDS_ENTRY_OR_SESSION_RISK')
                # Reacquire identity, receipt and exposure immediately before
                # reserving the unique decision. Adapter must independently
                # perform broker order_check and same-session/exposure checks.
                latest = self._snapshot(freshness=self.policy.max_tick_receipt_age)
                self._require_entry()
                if latest.execution_permissions_verified is not True:
                    raise Blocked('EXECUTION_PERMISSIONS_UNVERIFIED')
                if latest.positions or latest.pending_orders:
                    raise Blocked('EXPOSURE_CHANGED')
                if (latest.session_reconciled is not True
                        or latest.session_loss + risk.stop_loss_usd > self.policy.session_loss_usd
                        or self.clock() >= self.deadline):
                    raise Blocked('SESSION_RISK_BLOCKED')
                self.seen.add(signal.key)
                self.entries += 1
                # Reserve BEFORE submission: exceptions/unknown results never
                # retry. Further entries require explicit local reconciliation.
                self.reconciliation_required = True
                result = self.broker.submit_once(signal, self.lot)
                if result != 'CONFIRMED':
                    raise Blocked('LOCAL_RECONCILIATION_REQUIRED')
                self.reconciliation_required = False
                self._event('ENTRY_CONFIRMED_BY_ADAPTER')
            except Blocked as exc:
                self._off(str(exc))
            except Exception:
                self.connected = False
                self._off('ADAPTER_OR_STRATEGY_FAILED')
            return self.status()

    def status(self):
        # Informational last-observed fields only; status must remain readable
        # while a stop interrupts slow work. Broker-current is always false.
        return {'state': 'ON' if self.entry_allowed() else 'OFF', 'lot': str(self.lot),
                    'symbol': 'BTCUSD', 'connected_at_last_poll': self.connected,
                    'broker_connection_current_verified': False,
                    'reason': self.reason, 'protection': self.protection,
                    'entries_reserved': self.entries,
                    'reconciliation_required': self.reconciliation_required,
                    'runtime_adapter_installed': self.broker is not None,
                    'strategy_policy_present': self.strategy is not None and self.policy is not None}


if __name__ == '__main__':
    import json
    print(json.dumps(Controller().status(), indent=2))
