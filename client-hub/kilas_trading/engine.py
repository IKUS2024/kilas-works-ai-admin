"""Deterministic replay and paper risk math. Prices/P&L use integer USD cents."""
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

UNITS = 1000000
SOURCE = 'Kilas synthetic BTC/USD replay v1 (no market feed)'
RISK = {'risk_bps': 100, 'max_positions': 3, 'max_exposure_cents': 200000, 'daily_loss_cents': 50000}
STRATEGY = {'fast': 3, 'slow': 8, 'threshold_bps': 5, 'quantity': '0.01', 'stop_distance': '300', 'target_distance': '600', 'trailing_distance': '0', 'trailing_activation': '300'}


class TradingError(ValueError):
    pass


def scaled(value, scale, maximum=100000000):
    try:
        n = Decimal(str(value)) * scale
        if not n.is_finite() or n < 0 or n > maximum or n != n.to_integral_value():
            raise TradingError('Angka tidak valid atau presisi terlalu tinggi.')
        return int(n)
    except (InvalidOperation, ValueError, TypeError):
        raise TradingError('Isi angka yang valid.') from None


def candle(tick):
    def price(t):
        return 6000000 + round(85000 * math.sin(t / 7) + 45000 * math.sin(t / 3))
    opened, closed = price(tick - 1), price(tick)
    return {'tick': tick, 'open': opened, 'close': closed,
            'high': max(opened, closed) + 9000, 'low': min(opened, closed) - 9000,
            'source_time': (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=tick)).isoformat()}


def candles(tick):
    return [candle(n) for n in range(max(1, tick - 39), tick + 1)]


def pnl(position, price):
    sign = 1 if position['side'] == 'BUY' else -1
    return sign * (price - position['entry_cents']) * position['quantity_units'] // UNITS


def protect(position, bar):
    """Stop wins an ambiguous bar. Gap fills at open; trailing activates for next bar."""
    stop, target, side = position['stop_cents'], position['target_cents'], position['side']
    if side == 'BUY':
        if bar['low'] <= stop:
            return min(stop, bar['open']), 'SL', stop
        if bar['high'] >= target:
            return max(target, bar['open']), 'TP', stop
    else:
        if bar['high'] >= stop:
            return max(stop, bar['open']), 'SL', stop
        if bar['low'] <= target:
            return min(target, bar['open']), 'TP', stop
    sign = 1 if side == 'BUY' else -1
    if position['trailing_cents'] and sign * (bar['close'] - position['entry_cents']) >= position['activation_cents']:
        candidate = bar['close'] - sign * position['trailing_cents']
        stop = max(stop, candidate) if side == 'BUY' else min(stop, candidate)
    return None, None, stop


def decision(config, bars):
    closes = [b['close'] for b in bars]
    fast, slow = config['fast'], config['slow']
    f, s = sum(closes[-fast:]) // fast, sum(closes[-slow:]) // slow
    prev_f, prev_s = sum(closes[-fast-1:-1]) // fast, sum(closes[-slow-1:-1]) // slow
    spread = (f - s) * 10000 // s
    side = 'BUY' if prev_f <= prev_s and spread >= config['threshold_bps'] else 'SELL' if prev_f >= prev_s and spread <= -config['threshold_bps'] else None
    return side, {'strategy': 'SMA crossover v1', 'config': config, 'closes_cents': closes[-slow-1:],
                  'fast_cents': f, 'slow_cents': s, 'previous_fast_cents': prev_f,
                  'previous_slow_cents': prev_s, 'spread_bps': spread,
                  'explanation': 'Persilangan SMA memenuhi ambang.' if side else 'Tidak ada persilangan SMA yang memenuhi ambang; tidak membuat posisi.'}
