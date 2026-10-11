"""Pinned DEMO-only MT5 transport; default read-only, no trading CLI.

SDK injection supports offline tests. Real SDK attachment is explicit and only
attaches the already-running pinned terminal. No login or settings mutations.
"""
import hashlib
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, DecimalException, ROUND_FLOOR, ROUND_CEILING
from pathlib import Path
from threading import RLock

from mt5_demo_session import (EXE, DATA, SERVER, path,
                               one_terminal_running, DemoReceiptLiveness)
from demo_auto_controller import (Blocked, Identity, Specs, Snapshot, Position,
                                  Signal, Risk, Policy, number)
from demo_instrument_profiles import mapping,broker_facts

MAGIC = 26101002  # Separate from the historical immediate-close smoke.


def require(ok, code):
    if not ok:
        raise Blocked(code)


def dec(value):
    try:
        value = Decimal(str(value))
    except (DecimalException, ValueError, TypeError):
        raise Blocked('BROKER_NUMBER_INVALID') from None
    require(value.is_finite(), 'BROKER_NUMBER_INVALID')
    return value


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def execution_failure(exc, stage, evidence):
    """Fixed guard codes and numeric broker evidence; no credentials/raw dumps."""
    code = str(exc) if isinstance(exc, Blocked) else None
    if code is not None and not re.fullmatch(r'[A-Z][A-Z0-9_]{0,99}', code):
        code = 'UNCLASSIFIED_BLOCK'
    frames = []
    tb = exc.__traceback__
    while tb is not None:
        frames.append(dict(file=Path(tb.tb_frame.f_code.co_filename).name,
                           function=tb.tb_frame.f_code.co_name,line=tb.tb_lineno))
        tb = tb.tb_next
    return dict(stage=stage,error_type=type(exc).__name__,
                failure_code=code or 'NATIVE_OR_LOCAL_EXCEPTION',
                raw_message_omitted=not isinstance(exc, Blocked),frames=frames,
                evidence=dict(evidence))


def broker_result_fields(result):
    # Numeric allowlist deliberately excludes request echoes and broker comments.
    fields = {}
    for name in ('retcode','order','deal','volume','price','bid','ask','retcode_external'):
        value = getattr(result,name,None)
        fields[name] = value if type(value) in (int,float) else None
    return fields


@dataclass(frozen=True)
class DemoTestPolicy:
    session_id: str
    controller: Policy
    sl_loss_usd: Decimal
    tp_profit_usd: Decimal
    fee_reserve_usd: Decimal
    deviation_points: int

    def validate(self):
        self.controller.validate()
        require(type(self.session_id) is str and 1 <= len(self.session_id) <= 80,
                'SESSION_ID_INVALID')
        require(type(self.controller.strategy_reference) is str
                and 1 <= len(self.controller.strategy_reference) <= 200, 'STRATEGY_REFERENCE_INVALID')
        require(type(self.deviation_points) is int and 0 <= self.deviation_points <= 20,
                'DEVIATION_INVALID')
        require(self.controller.max_tick_receipt_age <= 1.5, 'RECEIPT_POLICY_TOO_LOOSE')
        require(0 <= dec(self.fee_reserve_usd) < number(self.sl_loss_usd)
                <= self.controller.max_stop_loss_usd, 'SL_OR_FEE_POLICY_INVALID')
        number(self.tp_profit_usd)

    @classmethod
    def parse(cls, raw):
        fields = {'schema_version', 'session_id', 'strategy_reference', 'max_run_seconds',
                  'max_entries', 'session_loss_usd', 'max_tick_receipt_age',
                  'max_stop_loss_usd', 'max_notional_usd', 'max_spread_cost_usd',
                  'sl_loss_usd', 'tp_profit_usd', 'fee_reserve_usd', 'deviation_points'}
        require(type(raw) is dict and set(raw) == fields and type(raw['schema_version']) is int
                and raw['schema_version'] == 1,
                'POLICY_SCHEMA_INVALID')
        require(all(v is not None for v in raw.values()), 'POLICY_UNSET')
        require(type(raw['session_id']) is str and 1 <= len(raw['session_id']) <= 80,
                'SESSION_ID_INVALID')
        require(type(raw['deviation_points']) is int and 0 <= raw['deviation_points'] <= 20,
                'DEVIATION_INVALID')
        p = Policy(raw['strategy_reference'], float(number(raw['max_run_seconds'])),
                   raw['max_entries'], number(raw['session_loss_usd']),
                   float(number(raw['max_tick_receipt_age'])),
                   number(raw['max_stop_loss_usd']), number(raw['max_notional_usd']),
                   number(raw['max_spread_cost_usd']))
        p.validate()
        require(p.max_tick_receipt_age <= 1.5, 'RECEIPT_POLICY_TOO_LOOSE')
        fees = dec(raw['fee_reserve_usd'])
        sl, tp = number(raw['sl_loss_usd']), number(raw['tp_profit_usd'])
        require(0 <= fees < sl <= p.max_stop_loss_usd, 'SL_OR_FEE_POLICY_INVALID')
        result = cls(raw['session_id'], p, sl, tp, fees, raw['deviation_points'])
        result.validate()
        return result


class Journal:
    """SQLite FULL-sync reservation before send, cross-process exclusivity.

    Local account/position metadata only; never stores login/password/token.
    Unknown reservations are sticky, including a crash before/after SDK send.
    Do not delete/recreate this ledger to bypass reconciliation.
    """
    def __init__(self, filename):
        self.filename = str(filename)
        with self.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS binding (id INTEGER PRIMARY KEY CHECK(id=1), account TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS adapter_instrument (id INTEGER PRIMARY KEY CHECK(id=1),logical TEXT,symbol TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, policy TEXT, started REAL, last_wall REAL)')
            c.execute('CREATE TABLE IF NOT EXISTS decisions (key TEXT PRIMARY KEY, session TEXT, state TEXT, '
                      'order_id INTEGER, position_id INTEGER, side TEXT, volume TEXT, sl TEXT, tp TEXT, loss TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS close_attempts (decision_key TEXT PRIMARY KEY, '
                      'ticket INTEGER, volume TEXT, state TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS entry_failure_events (id INTEGER PRIMARY KEY AUTOINCREMENT, '
                      'decision_key TEXT, payload TEXT)')

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.filename, timeout=2)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA synchronous=FULL')
        try:
            with c:
                yield c
        finally:
            c.close()

    def bind(self, account):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT account FROM binding WHERE id=1').fetchone()
            require(row is None or row['account'] == account, 'JOURNAL_ACCOUNT_MISMATCH')
            c.execute('INSERT OR IGNORE INTO binding VALUES(1,?)', (account,))

    def records(self):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT * FROM decisions')]

    def entry_failure(self, key, diagnostic):
        with self.connect() as c:
            c.execute('INSERT INTO entry_failure_events(decision_key,payload) VALUES(?,?)',
                      (key,json.dumps(diagnostic,sort_keys=True)))

    def entry_failures(self, key):
        with self.connect() as c:
            return [json.loads(r[0]) for r in c.execute(
                'SELECT payload FROM entry_failure_events WHERE decision_key=? ORDER BY id',(key,))]

    def bind_instrument(self,profile):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            prior=c.execute('SELECT logical,symbol FROM adapter_instrument WHERE id=1').fetchone()
            require(prior is None or tuple(prior)==(profile.logical,profile.broker_symbol),'JOURNAL_INSTRUMENT_MISMATCH')
            require(profile.logical=='BTC' or c.execute('SELECT count(*) FROM decisions').fetchone()[0]==0
                    or prior is not None,'LEGACY_LEDGER_INSTRUMENT_UNVERIFIED')
            c.execute('INSERT OR IGNORE INTO adapter_instrument VALUES(1,?,?)',(profile.logical,profile.broker_symbol))

    def activate(self, policy, wall):
        fingerprint = digest(repr(policy))
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            r = c.execute('SELECT * FROM sessions WHERE id=?', (policy.session_id,)).fetchone()
            if r is None:
                c.execute('INSERT INTO sessions VALUES(?,?,?,?)', (policy.session_id, fingerprint, wall, wall))
            else:
                require(r['policy'] == fingerprint and wall >= r['last_wall'], 'SESSION_POLICY_OR_CLOCK_CHANGED')
                require(wall - r['started'] < policy.controller.max_run_seconds, 'SESSION_EXPIRED')
                c.execute('UPDATE sessions SET last_wall=? WHERE id=?', (wall, policy.session_id))

    def reserve(self, policy, key, side, lot, sl, tp, wall):
        # A single transaction prevents two controllers reserving concurrently.
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            session = c.execute('SELECT * FROM sessions WHERE id=?', (policy.session_id,)).fetchone()
            require(session is not None and session['policy'] == digest(repr(policy)), 'SESSION_NOT_STARTED')
            require(wall >= session['last_wall'] and wall-session['started'] < policy.controller.max_run_seconds,
                    'SESSION_EXPIRED_OR_CLOCK_ROLLBACK')
            require(c.execute("SELECT count(*) FROM decisions WHERE state!='CLOSED'").fetchone()[0] == 0,
                    'JOURNAL_EXPOSURE_UNRESOLVED')
            count = c.execute('SELECT count(*) FROM decisions WHERE session=?', (policy.session_id,)).fetchone()[0]
            require(count < policy.controller.max_entries, 'ENTRY_BUDGET_EXHAUSTED')
            losses = sum((dec(r[0]) for r in c.execute('SELECT loss FROM decisions WHERE session=?',
                                                      (policy.session_id,))), Decimal(0))
            require(losses + policy.sl_loss_usd <= policy.controller.session_loss_usd, 'SESSION_RISK_BLOCKED')
            require(c.execute('SELECT 1 FROM decisions WHERE key=?', (key,)).fetchone() is None, 'DUPLICATE_DECISION')
            c.execute('INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (key, policy.session_id, 'RESERVED', None, None, side, str(lot), str(sl), str(tp), '0'))
            c.execute('UPDATE sessions SET last_wall=? WHERE id=?', (wall, policy.session_id))

    def update(self, key, **fields):
        allowed = {'state', 'order_id', 'position_id', 'loss', 'sl'}
        require(fields and set(fields) <= allowed, 'JOURNAL_UPDATE_INVALID')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if fields.get('state') in ('OPEN', 'CLOSED'):
                attempts = c.execute('SELECT state FROM close_attempts WHERE decision_key=?',
                                     (key,)).fetchone()
                require(attempts is None or (fields['state'] == 'CLOSED' and attempts['state'] == 'CONFIRMED'),
                        'CLOSE_UNRESOLVED')
            c.execute('UPDATE decisions SET '+','.join(k+'=?' for k in fields)+' WHERE key=?',
                      (*fields.values(), key))

    def reserve_close(self, policy, key, ticket, volume, wall):
        """Atomically fence entry/protection/other close before any close check."""
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            session = c.execute('SELECT * FROM sessions WHERE id=?', (policy.session_id,)).fetchone()
            require(session is not None and session['policy'] == digest(repr(policy))
                    and wall >= session['last_wall']
                    and wall-session['started'] < policy.controller.max_run_seconds,
                    'CLOSE_SESSION_INVALID_OR_EXPIRED')
            row = c.execute('SELECT * FROM decisions WHERE key=?', (key,)).fetchone()
            require(row is not None and row['state'] == 'OPEN'
                    and row['session'] == policy.session_id and 0 < volume <= dec(row['volume']),
                    'CLOSE_POSITION_NOT_OWNED')
            require(c.execute('SELECT 1 FROM close_attempts WHERE decision_key=?', (key,)).fetchone()
                    is None, 'CLOSE_ALREADY_ATTEMPTED')
            c.execute('INSERT INTO close_attempts VALUES(?,?,?,?)', (key, ticket, str(volume), 'RESERVED'))
            c.execute("UPDATE decisions SET state='UNKNOWN' WHERE key=?", (key,))
            c.execute('UPDATE sessions SET last_wall=? WHERE id=?', (wall, policy.session_id))

    def finish_close(self, key, *, loss=None):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT state FROM close_attempts WHERE decision_key=?', (key,)).fetchone()
            require(row is not None and row['state'] == 'RESERVED', 'CLOSE_ALREADY_RESOLVED')
            state = 'UNKNOWN' if loss is None else 'CONFIRMED'
            c.execute('UPDATE close_attempts SET state=? WHERE decision_key=?', (state, key))
            if loss is not None:
                require(dec(loss) >= 0, 'CLOSE_LOSS_INVALID')
                c.execute("UPDATE decisions SET state='CLOSED',loss=? WHERE key=? AND state='UNKNOWN'",
                          (str(loss), key))


class MT5DemoAdapter:
    def __init__(self, sdk, journal, policy=None, *, execute=False,
                 clock=time.perf_counter, wall=time.time,instrument='BTC'):
        self.profile=mapping(instrument)
        require(not execute or self.profile.logical=='BTC','INSTRUMENT_EXECUTION_UNREVIEWED')
        journal.bind_instrument(self.profile)
        self.sdk, self.journal, self.policy = sdk, journal, policy
        if policy is not None:
            policy.validate()
        self.execute = execute
        self.clock, self.wall = clock, wall
        self.liveness = DemoReceiptLiveness(now=clock)
        self.private_identity = None
        self.lock = RLock()
        self.expiry = None
        self.entry_guard = None
        self.market_guard = None
        self.risk_guard = None
        self.last_entry_diagnostic = None
        self.last_sdk_error_code = None

    def bind_risk_guard(self, guard):
        require(callable(guard) and self.risk_guard is None, 'RISK_GUARD_BINDING_INVALID')
        self.risk_guard = guard

    def bind_market_guard(self, guard):
        require(callable(guard) and self.market_guard is None, 'MARKET_GUARD_BINDING_INVALID')
        self.market_guard = guard

    def bind_entry_guard(self, guard):
        require(callable(guard) and (self.entry_guard is None or self.entry_guard == guard),
                'ENTRY_GUARD_BINDING_INVALID')
        self.entry_guard = guard

    def check_entry_guard(self):
        require(self.entry_guard is None or self.entry_guard() is True, 'ENTRY_REVOKED')

    @classmethod
    def attach_readonly(cls, journal, policy=None,*,instrument='BTC'):
        require(one_terminal_running(), 'EXACTLY_ONE_RUNNING_TERMINAL_REQUIRED')
        import MetaTrader5 as sdk
        require(sdk.initialize(EXE, timeout=5000) is True, 'ATTACHMENT_UNAVAILABLE')
        try:
            result = cls(sdk, journal, policy,instrument=instrument)
            result.verify()
            return result
        except Exception:
            sdk.shutdown()
            raise

    def close(self):
        self.sdk.shutdown()

    @property
    def symbol(self): return self.profile.broker_symbol

    def verify(self):
        a, t = self.sdk.account_info(), self.sdk.terminal_info()
        require(a is not None and t is not None, 'SESSION_UNAVAILABLE')
        require(type(a.trade_mode) is int and a.trade_mode == 0 and a.server == SERVER
                and a.currency == 'USD' and a.company.strip().lower() in
                ('xm global limited', 'xmglobal limited'), 'NOT_PINNED_DEMO')
        require(t.connected is True and path(t.path) == path(str(Path(EXE).parent))
                and path(t.data_path) == path(DATA), 'TERMINAL_MISMATCH')
        require(type(a.login) is int and a.login > 0, 'IDENTITY_UNAVAILABLE')
        current = (a.login, a.server, a.currency, t.path, t.data_path)
        require(self.private_identity is None or current == self.private_identity, 'IDENTITY_CHANGED')
        self.private_identity = current
        binding = digest(repr(current))
        self.journal.bind(binding)
        permissions = (t.trade_allowed is True and t.tradeapi_disabled is False
                       and a.trade_allowed is True and a.trade_expert is True)
        return binding, permissions

    def read(self, method, *args, **kwargs):
        self.verify()
        result = method(*args, **kwargs)
        if result is None:
            self._capture_sdk_error_code()
        self.verify()
        require(result is not None, 'SDK_READ_UNAVAILABLE')
        return result

    def _capture_sdk_error_code(self):
        # Capture immediately after a None result, before another SDK call can
        # overwrite last_error. Never expose its arbitrary message text.
        try:
            error = self.sdk.last_error()
            self.last_sdk_error_code = error[0] if type(error[0]) is int else None
        except Exception:
            self.last_sdk_error_code = None

    def market(self):
        info = self.read(self.sdk.symbol_info, self.symbol)
        broker_facts(self.profile,info)
        if self.market_guard is not None:
            self.market_guard(info)
        require(info.name == self.symbol and info.select is True and info.visible is True
                and info.custom is False and info.trade_mode == 4
                and info.currency_profit == 'USD' and info.currency_margin == 'USD', 'SYMBOL_UNQUALIFIED')
        for value in (info.point, info.trade_tick_size, info.trade_contract_size):
            number(value)
        require(type(info.trade_stops_level) is int and info.trade_stops_level >= 0, 'STOPS_INVALID')
        tick = self.read(self.sdk.symbol_info_tick, self.symbol)
        evidence = self.liveness(tick)
        evidence['receipt_at'] = self.clock()-evidence['receipt_age_seconds']
        require(0 < dec(tick.bid) <= dec(tick.ask), 'QUOTE_INVALID')
        return info, tick, evidence

    def reconcile(self, positions, orders):
        rows = self.journal.records()
        owned, loss, reconciled = set(), Decimal(0), True
        for r in rows:
            if r['state'] in ('RESERVED', 'UNKNOWN'):
                reconciled = False
                continue  # Never infer success or retry from an empty terminal.
            if r['state'] == 'CLOSED':
                if self.policy and r['session'] == self.policy.session_id:
                    loss += dec(r['loss'])
                continue
            deals = self.read(self.sdk.history_deals_get, position=r['position_id'])
            relevant = [d for d in deals if d.symbol == self.symbol and d.position_id == r['position_id']]
            require(relevant and len({d.ticket for d in relevant}) == len(relevant), 'DEAL_HISTORY_INCOMPLETE')
            require(all(d.entry in (self.sdk.DEAL_ENTRY_IN, self.sdk.DEAL_ENTRY_OUT) for d in relevant),
                    'DEAL_HISTORY_UNSUPPORTED')
            ins = [d for d in relevant if d.entry == self.sdk.DEAL_ENTRY_IN]
            outs = [d for d in relevant if d.entry == self.sdk.DEAL_ENTRY_OUT]
            expected_type = self.sdk.ORDER_TYPE_BUY if r['side'] == 'BUY' else self.sdk.ORDER_TYPE_SELL
            require(ins and all(d.order == r['order_id'] and d.magic == MAGIC and d.type == expected_type
                                for d in ins), 'ENTRY_DEAL_BINDING_MISMATCH')
            entered = sum((dec(d.volume) for d in ins), Decimal(0))
            exited = sum((dec(d.volume) for d in outs), Decimal(0))
            require(entered == dec(r['volume']) and 0 <= exited <= entered, 'DEAL_VOLUME_MISMATCH')
            active = [p for p in positions if p.identifier == r['position_id']]
            net = sum((sum((dec(getattr(d, k)) for k in ('profit', 'commission', 'swap', 'fee')), Decimal(0))
                       for d in relevant), Decimal(0))
            realized_loss = max(Decimal(0), -net)
            if entered == exited:
                require(not active and not orders, 'EXIT_EXPOSURE_CONFLICT')
                self.journal.update(r['key'], state='CLOSED', loss=str(realized_loss))
            else:
                require(len(active) == 1, 'POSITION_HISTORY_CONFLICT')
                p = active[0]
                require(p.symbol == self.symbol and p.magic == MAGIC and p.type == expected_type
                        and dec(p.volume) == entered-exited and dec(p.sl) == dec(r['sl'])
                        and dec(p.tp) == dec(r['tp']) and not orders, 'BROKER_PROTECTION_OR_VOLUME_MISMATCH')
                owned.add(p.ticket)
                realized_loss += max(Decimal(0), -(dec(p.profit) + dec(p.swap)))
            if self.policy and r['session'] == self.policy.session_id:
                loss += realized_loss
        require(len(positions) <= 1, 'MULTIPLE_BTCUSD_POSITIONS')
        if any(p.ticket not in owned for p in positions) or orders:
            reconciled = False
        return owned, loss, reconciled

    def snapshot(self):
        with self.lock:
            binding, permissions = self.verify()
            info, tick, evidence = self.market()
            positions = self.read(self.sdk.positions_get, symbol=self.symbol)
            orders = self.read(self.sdk.orders_get, symbol=self.symbol)
            owned, loss, reconciled = self.reconcile(positions, orders)
            return Snapshot(Identity('DEMO', SERVER, 'USD', 'XM Global Limited', binding),
                            True, evidence['receipt_at'],
                            Specs(dec(info.volume_min), dec(info.volume_max), dec(info.volume_step)),
                            tuple(Position(p.ticket, 'BUY' if p.type == self.sdk.POSITION_TYPE_BUY else 'SELL',
                                           dec(p.sl) if p.sl else None, p.ticket in owned,
                                           dec(p.tp) if p.tp else None) for p in positions),
                            len(orders), loss, reconciled, evidence['verified'],
                            terminal_binding_verified=True, execution_permissions_verified=permissions,symbol=self.symbol)

    def begin_run(self, controller_policy=None):
        require(self.profile.logical=='BTC','INSTRUMENT_EXECUTION_UNREVIEWED')
        require(self.execute and self.policy is not None, 'EXECUTION_DISABLED')
        require(controller_policy is None or controller_policy == self.policy.controller, 'POLICY_MISMATCH')
        self.journal.activate(self.policy, self.wall())
        with self.journal.connect() as c:
            r = c.execute('SELECT started FROM sessions WHERE id=?', (self.policy.session_id,)).fetchone()
        self.expiry = self.clock() + max(0, self.policy.controller.max_run_seconds-(self.wall()-r['started']))

    def execution_state(self):
        rows = self.journal.records()
        return {'entries_reserved': sum(r['session'] == self.policy.session_id for r in rows) if self.policy else 0,
                'reconciliation_required': any(r['state'] in ('RESERVED', 'UNKNOWN') for r in rows)}

    def profit(self, side, lot, entry, exit_price):
        kind = self.sdk.ORDER_TYPE_BUY if side == 'BUY' else self.sdk.ORDER_TYPE_SELL
        return dec(self.read(self.sdk.order_calc_profit, kind, self.symbol, float(lot), float(entry), float(exit_price)))

    def currency_signal(self, key, side, lot):
        """Convert explicitly configured USD SL/TP via broker profit calculator.

        No strategy decision is generated. SL rounds inward, TP outward; if
        minimum stops conflict with the risk budget, block rather than widen.
        """
        require(self.policy is not None and side in ('BUY', 'SELL'), 'POLICY_OR_SIDE_UNSET')
        lot = number(lot)
        info, tick, evidence = self.market()
        Specs(dec(info.volume_min), dec(info.volume_max), dec(info.volume_step)).validate(lot)
        require(evidence['verified'], 'QUOTE_LIVENESS_UNVERIFIED')
        grid, sign = dec(info.trade_tick_size), 1 if side == 'BUY' else -1
        entry = dec(tick.ask if side == 'BUY' else tick.bid) + sign*dec(info.point)*self.policy.deviation_points
        available = self.policy.sl_loss_usd-self.policy.fee_reserve_usd
        def solve(wanted, direction, inward):
            # Integer-tick bisection; bounded calls and no invented tick value.
            maximum = int((entry/grid).to_integral_value(rounding=ROUND_FLOOR))-1 if direction < 0 else 2**30
            require(maximum > 0, 'PRICE_RANGE_INVALID')
            def magnitude(n):
                price = (entry/grid).to_integral_value(rounding=ROUND_FLOOR if direction < 0 else ROUND_CEILING)*grid + direction*n*grid
                return price, abs(self.profit(side, lot, entry, price))
            low, high = 0, 1
            while high < maximum and magnitude(high)[1] < wanted:
                high = min(maximum, high*2)
            require(magnitude(high)[1] >= wanted, 'CURRENCY_DISTANCE_UNREACHABLE')
            while high-low > 1:
                mid = (low+high)//2
                if magnitude(mid)[1] < wanted:
                    low = mid
                else:
                    high = mid
            n = low if inward and magnitude(high)[1] > wanted else high
            require(n > 0, 'SL_BELOW_PRICE_GRID')
            return magnitude(n)[0]
        sl = solve(available, -sign, True)
        tp = solve(self.policy.tp_profit_usd+self.policy.fee_reserve_usd, sign, False)
        signal = Signal(key, side, sl, tp, symbol=self.symbol)
        risk = self.quote_risk(signal, lot)
        require(risk.valid_protective_stop and risk.valid_take_profit, 'BROKER_STOP_DISTANCE_CONFLICT')
        return signal

    def quote_risk(self, signal, lot):
        require(isinstance(signal, Signal) and signal.symbol == self.symbol,
                'SIGNAL_INSTRUMENT_MISMATCH')
        require(self.policy is not None and signal.side in ('BUY', 'SELL'), 'POLICY_OR_SIDE_UNSET')
        return self._risk_from_market(signal, lot, *self.market())

    def _risk_from_market(self, signal, lot, info, tick, evidence):
        require(evidence['verified'] and evidence['receipt_age_seconds'] < self.policy.controller.max_tick_receipt_age,
                'QUOTE_LIVENESS_UNVERIFIED')
        lot = number(lot)
        Specs(dec(info.volume_min), dec(info.volume_max), dec(info.volume_step)).validate(lot)
        bid, ask, step, point = dec(tick.bid), dec(tick.ask), dec(info.trade_tick_size), dec(info.point)
        sign = 1 if signal.side == 'BUY' else -1
        entry = (ask if sign == 1 else bid)+sign*point*self.policy.deviation_points
        sl, tp = number(signal.stop), number(signal.target)
        # Conservative protection bounds while broker semantics are reviewed.
        level = point*max(info.trade_stops_level, info.trade_freeze_level)
        stop_distance = bid-sl if sign == 1 else sl-ask
        valid_sl = sl % step == 0 and stop_distance > 0 and stop_distance >= level and sign*(entry-sl) > 0
        valid_tp = tp % step == 0 and (tp-bid if sign == 1 else ask-tp) >= level and sign*(tp-entry) > 0
        pnl = self.profit(signal.side, lot, entry, sl)
        target = self.profit(signal.side, lot, entry, tp)
        spread = -self.profit(signal.side, lot, ask if sign == 1 else bid, bid if sign == 1 else ask)
        require(pnl < 0 and target > 0 and spread >= 0, 'PROFIT_CALCULATION_INVALID')
        notional = lot*dec(info.trade_contract_size)*max(ask+point*self.policy.deviation_points,
                                                       bid+point*self.policy.deviation_points)
        require(self.clock()-evidence['receipt_at'] < self.policy.controller.max_tick_receipt_age,
                'QUOTE_LEASE_EXPIRED')
        risk = Risk(-pnl+self.policy.fee_reserve_usd, notional, spread,
                    valid_sl and -pnl+self.policy.fee_reserve_usd <= self.policy.sl_loss_usd,
                    valid_tp and target-self.policy.fee_reserve_usd >= self.policy.tp_profit_usd)
        if self.risk_guard is not None:
            self.risk_guard(risk)
        return risk

    def assess_gold_proposal(self, signal, lot, *, session_evidence=None, market_evidence=None):
        """Local readonly assessment; never a model call or execution authority.

        Trusted evidence must be supplied by a separately reviewed collector.
        No such live collector/strategy is installed by this readiness work.
        Missing proof is WAIT, including with advancing ticks/full trade mode.
        """
        from datetime import datetime, timezone
        from gold_market_readiness import validate_gold_evidence, validate_gold_quote

        result = dict(decision='WAIT', reason_code='GOLD_READINESS_UNVERIFIED',
                      proposal_risk_validated=False, execution_authorized=False,
                      broker_execution_allowed=False, symbol=self.symbol)
        def utc_now():
            return datetime.fromtimestamp(self.wall(), timezone.utc)
        def evidence_gate():
            validate_gold_evidence(session_evidence, market_evidence,
                                   now=self.clock(), utc_now=utc_now(),
                                   max_quote_age=self.policy.controller.max_tick_receipt_age)
        try:
            require(self.profile.logical == 'GOLD', 'GOLD_ASSESSMENT_ONLY')
            require(isinstance(signal, Signal) and signal.symbol == self.symbol,
                    'SIGNAL_INSTRUMENT_MISMATCH')
            require(self.policy is not None and signal.side in ('BUY', 'SELL'), 'POLICY_OR_SIDE_UNSET')
            self.policy.validate()
            evidence_gate()  # CLOSED/unknown/stale proofs stop before any SDK call.
            info, tick, evidence = self.market()
            validate_gold_quote(market_evidence, tick.time_msc, utc_now=utc_now(),
                                max_quote_age=self.policy.controller.max_tick_receipt_age)
            risk = self._risk_from_market(signal, lot, info, tick, evidence)
            evidence_gate()  # Slow calculations cannot renew the source evidence.
            validate_gold_quote(market_evidence, tick.time_msc, utc_now=utc_now(),
                                max_quote_age=self.policy.controller.max_tick_receipt_age)
            result['risk'] = dict(stop_loss_usd=str(risk.stop_loss_usd),
                                  notional_usd=str(risk.notional_usd),
                                  spread_cost_usd=str(risk.spread_cost_usd))
            require(risk.valid_protective_stop, 'PROTECTIVE_STOP_INVALID')
            require(risk.valid_take_profit, 'TAKE_PROFIT_INVALID')
            require(risk.notional_usd <= self.policy.controller.max_notional_usd,
                    'NOTIONAL_CAP_EXCEEDED')
            require(risk.spread_cost_usd <= self.policy.controller.max_spread_cost_usd,
                    'SPREAD_CAP_EXCEEDED')
            require(risk.stop_loss_usd <= self.policy.controller.session_loss_usd,
                    'SESSION_RISK_BLOCKED')
            # GOLD transport, strategy and live evidence remain unreviewed.
            result.update(proposal_risk_validated=True,
                          reason_code='INSTRUMENT_EXECUTION_UNREVIEWED')
        except Blocked as exc:
            # Only fixed local codes may cross this readonly status boundary.
            code = str(exc)
            allowed = {'GOLD_ASSESSMENT_ONLY', 'SIGNAL_INSTRUMENT_MISMATCH',
                       'POLICY_OR_SIDE_UNSET', 'MARKET_CLOSED', 'MARKET_SESSION_UNVERIFIED',
                       'MARKET_EVIDENCE_UNVERIFIED',
                       'NOTIONAL_CAP_EXCEEDED', 'SPREAD_CAP_EXCEEDED', 'SESSION_RISK_BLOCKED',
                       'PROTECTIVE_STOP_INVALID', 'TAKE_PROFIT_INVALID',
                       'LOT_OUTSIDE_BROKER_RULES', 'LOT_BELOW_UI_MINIMUM', 'INVALID_NUMBER',
                       'BROKER_SYMBOL_OR_UNITS_UNVERIFIED', 'BROKER_NUMBER_INVALID',
                       'BROKER_VOLUME_SPEC_INVALID', 'BROKER_PRICE_SPEC_INVALID',
                       'STOPS_INVALID', 'FREEZE_INVALID', 'SYMBOL_UNQUALIFIED',
                       'QUOTE_LIVENESS_UNVERIFIED', 'QUOTE_LEASE_EXPIRED', 'QUOTE_INVALID',
                       'PROFIT_CALCULATION_INVALID'}
            result['reason_code'] = code if code in allowed else 'GOLD_READINESS_UNVERIFIED'
        except Exception:
            result['reason_code'] = 'GOLD_READINESS_UNVERIFIED'
        return result

    def submit_once(self, signal, lot):
        with self.lock:
            require(isinstance(signal, Signal) and signal.symbol == self.symbol,
                    'SIGNAL_INSTRUMENT_MISMATCH')
            require(self.profile.logical=='BTC','INSTRUMENT_EXECUTION_UNREVIEWED')
            self.check_entry_guard()
            # This gate precedes every order_check/order_send, including SLTP.
            require(self.execute and self.policy is not None and self.expiry is not None
                    and self.clock() < self.expiry, 'EXECUTION_DISABLED_OR_EXPIRED')
            s = self.snapshot()
            require(s.execution_permissions_verified and s.session_reconciled and not s.positions
                    and s.pending_orders == 0, 'EXPOSURE_OR_SESSION_BLOCKED')
            risk = self.quote_risk(signal, lot)
            p = self.policy.controller
            require(risk.valid_protective_stop and risk.valid_take_profit
                    and risk.stop_loss_usd <= p.max_stop_loss_usd and risk.notional_usd <= p.max_notional_usd
                    and risk.spread_cost_usd <= p.max_spread_cost_usd
                    and s.session_loss+risk.stop_loss_usd <= p.session_loss_usd, 'ENTRY_RISK_BLOCKED')
            info, tick, evidence = self.market()
            require(evidence['verified'], 'QUOTE_LIVENESS_UNVERIFIED')
            fill = self.sdk.ORDER_FILLING_IOC if info.filling_mode & 2 else self.sdk.ORDER_FILLING_FOK if info.filling_mode & 1 else None
            require(fill is not None, 'FILLING_UNSUPPORTED')
            key = digest(signal.key)
            request = dict(action=self.sdk.TRADE_ACTION_DEAL, symbol=self.symbol, volume=float(lot),
                           type=self.sdk.ORDER_TYPE_BUY if signal.side == 'BUY' else self.sdk.ORDER_TYPE_SELL,
                           price=float(tick.ask if signal.side == 'BUY' else tick.bid),
                           sl=float(signal.stop), tp=float(signal.target), deviation=self.policy.deviation_points,
                           magic=MAGIC, comment='KilasDemoAuto', type_time=self.sdk.ORDER_TIME_GTC, type_filling=fill)
            self.journal.reserve(self.policy, key, signal.side, lot, signal.stop, signal.target, self.wall())
            stage = 'RESERVED_PRE_CHECK'
            details = dict(symbol=self.symbol,side=signal.side,volume=str(lot),
                           request_sl=str(signal.stop),request_tp=str(signal.target),
                           request_price=str(request['price']),order_send_invoked=False)
            self.last_sdk_error_code = None
            try:
                self.check_entry_guard()
                _, permissions = self.verify()
                require(self.execute and permissions and self.clock() < self.expiry, 'EXECUTION_DISABLED_OR_EXPIRED')
                stage = 'ORDER_CHECK'
                checked = self.sdk.order_check(request)
                if checked is None:
                    self._capture_sdk_error_code()
                details['check_result'] = broker_result_fields(checked)
                require(checked is not None and checked.retcode == 0, 'ORDER_CHECK_REJECTED')
                stage = 'PRE_SEND_REVALIDATION'
                self.verify()
                require(not self.read(self.sdk.positions_get, symbol=self.symbol)
                        and not self.read(self.sdk.orders_get, symbol=self.symbol), 'EXPOSURE_CHANGED')
                final_risk = self.quote_risk(signal, lot)
                require(final_risk.valid_protective_stop and final_risk.valid_take_profit
                        and final_risk.stop_loss_usd <= p.max_stop_loss_usd
                        and final_risk.notional_usd <= p.max_notional_usd
                        and final_risk.spread_cost_usd <= p.max_spread_cost_usd
                        and self.clock() < self.expiry, 'FINAL_RISK_CHANGED')
                _, permissions = self.verify()
                require(permissions, 'EXECUTION_PERMISSIONS_UNVERIFIED')
                _, latest_tick, latest_evidence = self.market()
                require(latest_evidence['verified']
                        and abs(dec(latest_tick.ask if signal.side == 'BUY' else latest_tick.bid)-dec(request['price']))
                        <= dec(info.point)*self.policy.deviation_points, 'QUOTE_MOVED_RECHECK_REQUIRED')
                final_risk = self.quote_risk(signal, lot)
                require(final_risk.valid_protective_stop and final_risk.valid_take_profit
                        and final_risk.notional_usd <= p.max_notional_usd
                        and final_risk.spread_cost_usd <= p.max_spread_cost_usd
                        and self.clock()-latest_evidence['receipt_at'] < p.max_tick_receipt_age,
                        'QUOTE_LEASE_EXPIRED_OR_RISK_CHANGED')
                # Quote/profit calls above can outlive a stop or the run lease.
                # Recheck after those calls, immediately at the send boundary.
                _, permissions = self.verify()
                self.check_entry_guard()
                require(self.execute and permissions and self.clock() < self.expiry,
                        'EXECUTION_DISABLED_OR_EXPIRED')
                stage = 'ORDER_SEND'
                details['order_send_invoked'] = True
                result = self.sdk.order_send(request)  # Exactly once; never retry.
                if result is None:
                    self._capture_sdk_error_code()
                details['send_result'] = broker_result_fields(result)
                stage = 'SEND_RESULT_VALIDATION'
                require(result is not None and result.retcode == self.sdk.TRADE_RETCODE_DONE
                        and type(result.order) is int and result.order > 0
                        and type(result.deal) is int and result.deal > 0
                        and dec(result.volume) == dec(lot), 'SUBMISSION_NOT_FULLY_CONFIRMED')
                stage = 'ENTRY_HISTORY_READ'
                deals = self.read(self.sdk.history_deals_get, ticket=result.order)
                details['entry_history_count'] = len(deals)
                matches = [d for d in deals if d.ticket == result.deal and d.order == result.order
                           and d.symbol == self.symbol and d.magic == MAGIC and d.entry == self.sdk.DEAL_ENTRY_IN]
                details['matched_entry_deals'] = len(matches)
                stage = 'ENTRY_DEAL_BINDING'
                require(len(matches) == 1 and matches[0].position_id > 0
                        and matches[0].type == request['type'], 'ENTRY_DEAL_UNBOUND')
                stage = 'POST_FILL_EXPOSURE_READ'
                positions = self.read(self.sdk.positions_get, symbol=self.symbol)
                details['post_fill_positions'] = len(positions)
                require(len(positions) == 1 and not self.read(self.sdk.orders_get, symbol=self.symbol), 'FILL_EXPOSURE_UNCONFIRMED')
                pos = positions[0]
                details['observed_position'] = dict(ticket=int(pos.ticket),identifier=int(pos.identifier),
                    magic=int(pos.magic),type=int(pos.type),volume=str(pos.volume),
                    sl=str(pos.sl),tp=str(pos.tp),price_open=str(pos.price_open))
                stage = 'POST_FILL_SLTP_BINDING'
                require(pos.identifier == matches[0].position_id and pos.magic == MAGIC
                        and pos.type == request['type'] and dec(pos.volume) == dec(lot)
                        and dec(pos.sl) == signal.stop and dec(pos.tp) == signal.target,
                        'TICKET_BOUND_SLTP_UNCONFIRMED')
                stage = 'POST_FILL_PROFIT_CALCULATION'
                actual_sl, actual_tp = self._confirmed_fill_risk(signal, lot, dec(pos.price_open))
                details.update(actual_sl_loss_usd=str(actual_sl),actual_tp_profit_usd=str(actual_tp))
                stage = 'POST_FILL_RISK_VALIDATION'
                require(0 < actual_sl <= self.policy.sl_loss_usd
                        and actual_tp >= self.policy.tp_profit_usd, 'ACTUAL_FILL_RISK_UNCONFIRMED')
                stage = 'OPEN_JOURNAL_COMMIT'
                self.journal.update(key, state='OPEN', order_id=result.order, position_id=pos.identifier)
                stage = 'POST_COMMIT_RECONCILIATION'
                self.reconcile(positions, ())
                return 'CONFIRMED'
            except Exception as exc:
                details['sdk_error_code'] = self.last_sdk_error_code
                self.last_entry_diagnostic = execution_failure(exc,stage,details)
                try:
                    self.journal.update(key, state='UNKNOWN')
                finally:
                    try:
                        self.journal.entry_failure(key,self.last_entry_diagnostic)
                        self.last_entry_diagnostic['diagnostic_persistence']='CONFIRMED'
                    except Exception:
                        self.last_entry_diagnostic['diagnostic_persistence']='FAILED'
                return 'UNKNOWN'

    def _confirmed_fill_risk(self, signal, lot, price_open):
        # Production fee-inclusive semantics remain unchanged. A separately
        # authorized DEMO test subclass supplies explicitly gross-only math.
        return (-self.profit(signal.side, lot, price_open, signal.stop)+self.policy.fee_reserve_usd,
                self.profit(signal.side, lot, price_open, signal.target)-self.policy.fee_reserve_usd)

    def close_once(self, ticket, volume):
        """Explicit active DEMO close, exact owned ticket/volume; never retry.

        Default read-only and OFF/expired guards block it. No caller/runner is
        enabled here. UNKNOWN stays sticky across restarts even if later flat.
        """
        with self.lock:
            require(self.profile.logical == 'BTC', 'INSTRUMENT_EXECUTION_UNREVIEWED')
            require(type(ticket) is int and ticket > 0, 'CLOSE_TICKET_INVALID')
            volume = number(volume)
            self.check_entry_guard()
            require(self.execute is True and self.policy is not None and self.expiry is not None
                    and self.clock() < self.expiry, 'EXECUTION_DISABLED_OR_EXPIRED')
            self.policy.validate()
            _, permissions = self.verify()
            require(permissions, 'EXECUTION_PERMISSIONS_UNVERIFIED')
            positions = self.read(self.sdk.positions_get, symbol=self.symbol)
            orders = self.read(self.sdk.orders_get, symbol=self.symbol)
            owned, _, reconciled = self.reconcile(positions, orders)
            require(reconciled and len(positions) == 1 and not orders and ticket in owned,
                    'CLOSE_POSITION_NOT_OWNED')
            pos = positions[0]
            require(pos.ticket == ticket and dec(pos.volume) == volume, 'CLOSE_VOLUME_OR_TICKET_CHANGED')
            rows = [r for r in self.journal.records() if r['state'] == 'OPEN'
                    and r['position_id'] == pos.identifier and r['session'] == self.policy.session_id]
            require(len(rows) == 1, 'CLOSE_POSITION_NOT_OWNED')
            row = rows[0]
            expected = self.sdk.ORDER_TYPE_BUY if row['side'] == 'BUY' else self.sdk.ORDER_TYPE_SELL
            opposite = self.sdk.ORDER_TYPE_SELL if row['side'] == 'BUY' else self.sdk.ORDER_TYPE_BUY

            def exact_position():
                current = self.read(self.sdk.positions_get, symbol=self.symbol)
                pending = self.read(self.sdk.orders_get, symbol=self.symbol)
                require(len(current) == 1 and not pending, 'CLOSE_EXPOSURE_CHANGED')
                p = current[0]
                require(p.ticket == ticket and p.identifier == row['position_id']
                        and p.symbol == self.symbol and p.magic == MAGIC and p.type == expected
                        and dec(p.volume) == volume and dec(p.sl) == dec(row['sl'])
                        and dec(p.tp) == dec(row['tp']), 'CLOSE_POSITION_CHANGED')

            info, tick, evidence = self.market()
            require(evidence['verified'] and evidence['receipt_age_seconds']
                    < self.policy.controller.max_tick_receipt_age, 'QUOTE_LIVENESS_UNVERIFIED')
            fill = self.sdk.ORDER_FILLING_IOC if info.filling_mode & 2 else self.sdk.ORDER_FILLING_FOK if info.filling_mode & 1 else None
            require(fill is not None, 'FILLING_UNSUPPORTED')
            request = dict(action=self.sdk.TRADE_ACTION_DEAL, symbol=self.symbol, position=ticket,
                           volume=float(volume), type=opposite,
                           price=float(tick.bid if row['side'] == 'BUY' else tick.ask),
                           deviation=self.policy.deviation_points, magic=MAGIC,
                           comment='KilasDemoCloseOnce', type_time=self.sdk.ORDER_TIME_GTC,
                           type_filling=fill)
            exact_position()
            self.journal.reserve_close(self.policy, row['key'], ticket, volume, self.wall())
            try:
                _, permissions = self.verify()
                self.check_entry_guard()
                require(self.execute is True and permissions and self.clock() < self.expiry
                        and self.clock()-evidence['receipt_at'] < self.policy.controller.max_tick_receipt_age,
                        'EXECUTION_DISABLED_OR_QUOTE_EXPIRED')
                checked = self.sdk.order_check(request)
                require(checked is not None and checked.retcode == 0, 'CLOSE_CHECK_REJECTED')
                exact_position()
                latest_info, latest_tick, latest = self.market()
                price = dec(latest_tick.bid if row['side'] == 'BUY' else latest_tick.ask)
                require(latest['verified'] and abs(price-dec(request['price']))
                        <= dec(latest_info.point)*self.policy.deviation_points, 'CLOSE_QUOTE_MOVED')
                exact_position()
                _, permissions = self.verify()
                self.check_entry_guard()
                require(self.execute is True and permissions and self.clock() < self.expiry
                        and self.clock()-latest['receipt_at'] < self.policy.controller.max_tick_receipt_age,
                        'EXECUTION_DISABLED_OR_QUOTE_EXPIRED')
                result = self.sdk.order_send(request)  # Exactly once, position-bound.
                require(result is not None and result.retcode == self.sdk.TRADE_RETCODE_DONE
                        and type(result.order) is int and result.order > 0
                        and type(result.deal) is int and result.deal > 0 and dec(result.volume) == volume,
                        'CLOSE_NOT_FULLY_CONFIRMED')
                deals = self.read(self.sdk.history_deals_get, position=row['position_id'])
                relevant = [d for d in deals if d.symbol == self.symbol
                            and d.position_id == row['position_id']]
                require(relevant and len({d.ticket for d in relevant}) == len(relevant)
                        and all(d.entry in (self.sdk.DEAL_ENTRY_IN, self.sdk.DEAL_ENTRY_OUT) for d in relevant),
                        'CLOSE_HISTORY_INCOMPLETE')
                matched = [d for d in relevant if d.ticket == result.deal and d.order == result.order
                           and d.entry == self.sdk.DEAL_ENTRY_OUT and d.type == opposite and d.magic == MAGIC]
                require(len(matched) == 1 and dec(matched[0].volume) == volume, 'CLOSE_DEAL_UNBOUND')
                ins = [d for d in relevant if d.entry == self.sdk.DEAL_ENTRY_IN]
                outs = [d for d in relevant if d.entry == self.sdk.DEAL_ENTRY_OUT]
                require(ins and all(d.order == row['order_id'] and d.magic == MAGIC and d.type == expected for d in ins)
                        and all(d.type == opposite for d in outs)
                        and sum((dec(d.volume) for d in ins), Decimal(0)) == dec(row['volume'])
                        and sum((dec(d.volume) for d in outs), Decimal(0)) == dec(row['volume']),
                        'CLOSE_HISTORY_VOLUME_MISMATCH')
                require(not self.read(self.sdk.positions_get, symbol=self.symbol)
                        and not self.read(self.sdk.orders_get, symbol=self.symbol), 'CLOSE_NOT_FLAT')
                net = sum((sum((dec(getattr(d, field)) for field in ('profit', 'commission', 'swap', 'fee')),
                               Decimal(0)) for d in relevant), Decimal(0))
                self.journal.finish_close(row['key'], loss=max(Decimal(0), -net))
                return 'CONFIRMED'
            except Exception:
                self.journal.finish_close(row['key'])
                return 'UNKNOWN'

    def tighten_stop(self, ticket, candidate):
        with self.lock:
            require(self.profile.logical=='BTC','INSTRUMENT_EXECUTION_UNREVIEWED')
            require(self.execute and self.policy is not None, 'EXECUTION_DISABLED')
            self.verify()
            positions = self.read(self.sdk.positions_get, symbol=self.symbol)
            orders = self.read(self.sdk.orders_get, symbol=self.symbol)
            owned, _, ok = self.reconcile(positions, orders)
            require(ok and ticket in owned and len(positions) == 1, 'POSITION_NOT_OWNED')
            pos = positions[0]
            info, tick, evidence = self.market()
            candidate = number(candidate)
            is_buy = pos.type == self.sdk.POSITION_TYPE_BUY
            distance = dec(info.point)*max(info.trade_stops_level, info.trade_freeze_level)
            stop_distance = dec(tick.bid)-candidate if is_buy else candidate-dec(tick.ask)
            require(evidence['verified'] and candidate % dec(info.trade_tick_size) == 0
                    and (candidate > dec(pos.sl) if is_buy else candidate < dec(pos.sl))
                    and stop_distance > 0 and stop_distance >= distance,
                    'STOP_NOT_VALID_TIGHTENING')
            row = next(r for r in self.journal.records() if r['position_id'] == pos.identifier and r['state'] == 'OPEN')
            self.journal.update(row['key'], state='UNKNOWN')  # Crash-safe protective mutation.
            try:
                _, permissions = self.verify()
                require(permissions, 'EXECUTION_PERMISSIONS_UNVERIFIED')
                request = dict(action=self.sdk.TRADE_ACTION_SLTP, position=pos.ticket, symbol=self.symbol,
                               sl=float(candidate), tp=float(pos.tp), magic=MAGIC)
                checked = self.sdk.order_check(request)
                require(checked is not None and checked.retcode == 0, 'STOP_CHECK_REJECTED')
                current = self.read(self.sdk.positions_get, ticket=ticket)
                require(len(current) == 1 and current[0].identifier == pos.identifier
                        and current[0].magic == MAGIC and dec(current[0].volume) == dec(pos.volume)
                        and dec(current[0].sl) == dec(pos.sl) and dec(current[0].tp) == dec(pos.tp),
                        'POSITION_CHANGED_BEFORE_PROTECTION')
                fresh_info, fresh_tick, fresh_evidence = self.market()
                distance = dec(fresh_info.point)*max(fresh_info.trade_stops_level, fresh_info.trade_freeze_level)
                stop_distance = dec(fresh_tick.bid)-candidate if is_buy else candidate-dec(fresh_tick.ask)
                require(fresh_evidence['verified']
                        and candidate % dec(fresh_info.trade_tick_size) == 0
                        and stop_distance > 0 and stop_distance >= distance,
                        'PROTECTION_QUOTE_CHANGED')
                _, permissions = self.verify()
                require(self.execute and permissions
                        and self.clock()-fresh_evidence['receipt_at'] < self.policy.controller.max_tick_receipt_age,
                        'EXECUTION_DISABLED_OR_QUOTE_EXPIRED')
                result = self.sdk.order_send(request)
                require(result is not None and result.retcode == self.sdk.TRADE_RETCODE_DONE, 'STOP_UPDATE_UNKNOWN')
                updated = self.read(self.sdk.positions_get, ticket=ticket)
                require(len(updated) == 1 and updated[0].identifier == pos.identifier
                        and dec(updated[0].sl) == candidate and dec(updated[0].tp) == dec(pos.tp), 'STOP_UPDATE_UNCONFIRMED')
                self.journal.update(row['key'], state='OPEN', sl=str(candidate))
                return 'CONFIRMED'
            except Exception:
                return 'UNKNOWN'


if __name__ == '__main__':
    print(json.dumps({'state': 'OFF', 'execution_enabled': False, 'strategy': 'UNSET',
                      'policy': 'UNSET', 'sdk_attached': False, 'orders_submitted': 0}))
