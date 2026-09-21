"""Daily reference FX for Finance display estimates; never executable buy/sell quotes.

Ledger values remain in their original currency. Conversion is presentation-only, uses Decimal,
and combined totals are rounded once after all native balances are summed.
"""
from datetime import datetime, timezone, date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import threading
import time

import requests

SUPPORTED = ('IDR','USD','SGD','MYR','EUR','GBP','AUD','JPY','CNY','HKD','THB')
_SYMBOLS = {'IDR':'Rp','USD':'US$','SGD':'S$','MYR':'RM','EUR':'€','GBP':'£',
            'AUD':'A$','JPY':'¥','CNY':'CN¥','HKD':'HK$','THB':'฿'}
_TTL = 3600
_cache = None
_retry_at = 0.0
_lock = threading.Lock()


def _positive(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() and Decimal(0) < result <= Decimal('1e12') else None


def _copy(snapshot_value, stale=False):
    result = dict(snapshot_value, rates=dict(snapshot_value['rates']))
    try:
        age = (datetime.now(timezone.utc).date() - date.fromisoformat(snapshot_value['date'])).days
    except (ValueError, TypeError):
        age = 9999
    result['stale'] = stale or age > 7
    return result


def snapshot(currencies):
    wanted = set(currencies or ())
    if not wanted.issubset(SUPPORTED):
        raise ValueError('unsupported_currency')
    today = datetime.now(timezone.utc).date().isoformat()
    identity = {'rates': {'IDR': '1'}, 'date': today, 'source': 'IDR', 'stale': False}
    if not wanted.difference({'IDR'}):
        return identity
    global _cache, _retry_at
    with _lock:
        now = time.monotonic()
        if _cache and now - _cache['fetched_at'] < _TTL and wanted.issubset(_cache['rates']):
            return _copy(_cache)
        if now < _retry_at:
            return _copy(_cache, True) if _cache else dict(identity, date='', source='unavailable', stale=True)
        try:
            response = requests.get(
                'https://api.frankfurter.dev/v1/latest',
                params={'base':'EUR','symbols':','.join(code for code in SUPPORTED if code != 'EUR')},
                timeout=(2,4), allow_redirects=False)
            response.raise_for_status()
            payload = response.json(parse_float=Decimal)
            if payload.get('base') != 'EUR' or Decimal(str(payload.get('amount', 1))) != 1:
                raise ValueError('invalid_base')
            rate_date = date.fromisoformat(str(payload['date']))
            if rate_date > datetime.now(timezone.utc).date():
                raise ValueError('future_rate')
            raw = dict(payload.get('rates') or {}, EUR='1')
            numbers = {code:_positive(raw.get(code)) for code in SUPPORTED}
            if not all(numbers.values()):
                raise ValueError('invalid_or_missing_rate')
            with localcontext() as context:
                context.prec = 60
                # Store one unit of each currency expressed in IDR.
                rates = {code:str(numbers['IDR'] / numbers[code]) for code in SUPPORTED}
            _cache = {'rates':rates, 'date':rate_date.isoformat(), 'source':'Frankfurter',
                      'stale':False, 'fetched_at':now}
            _retry_at = 0.0
            return _copy(_cache)
        except (requests.RequestException, ValueError, TypeError, KeyError, InvalidOperation):
            _retry_at = now + 60
            return _copy(_cache, True) if _cache else dict(identity, date='', source='unavailable', stale=True)


def minor_scale(currency):
    if currency not in SUPPORTED:
        raise ValueError('unsupported_currency')
    return Decimal(1) if currency in ('IDR','JPY') else Decimal(100)


def major(amount_minor, currency):
    if type(amount_minor) is not int:
        raise ValueError('invalid_money_minor')
    with localcontext() as context:
        context.prec = max(60, len(str(abs(amount_minor))) + 20)
        return Decimal(amount_minor) / minor_scale(currency)


def reference_pair(from_currency, to_currency, fx):
    if from_currency not in SUPPORTED or to_currency not in SUPPORTED or from_currency == to_currency:
        return None
    rates = (fx or {}).get('rates', {})
    source = _positive(rates.get(from_currency))
    target = _positive(rates.get(to_currency))
    if source is None or target is None:
        return None
    with localcontext() as context:
        context.prec = 60
        return source / target


def convert_total(rows, to_currency, fx, field='balance_minor'):
    """Convert a full native-currency position; missing any needed rate returns None.

    This intentionally never returns a partial total. Rounding occurs once at the end.
    """
    scale = minor_scale(to_currency)
    with localcontext() as context:
        context.prec = 80
        total = Decimal(0)
        for row in rows:
            amount = int(row[field])
            currency = row['currency']
            if amount == 0:
                continue
            if currency == to_currency:
                total += Decimal(amount)
                continue
            rate = reference_pair(currency, to_currency, fx)
            if rate is None:
                return None
            total += major(amount, currency) * rate * scale
        return int(total.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def to_idr(amount_minor, currency, fx):
    return convert_total([{'currency':currency,'balance_minor':int(amount_minor)}], 'IDR', fx)


def format_money(amount_minor, currency):
    if currency not in SUPPORTED:
        raise ValueError('unsupported_currency')
    if type(amount_minor) is not int:
        raise ValueError('invalid_money_minor')
    sign = '-' if amount_minor < 0 else ''
    amount = abs(amount_minor)
    if currency == 'IDR':
        # Presentation uses two visible decimals consistently while the ledger
        # still stores whole rupiah exactly.
        number = format(amount, ',').replace(',', '.') + ',00'
    elif currency == 'JPY':
        # JPY remains whole-unit in the ledger; .00 is presentation only.
        number = format(amount, ',') + '.00'
    else:
        number = f'{amount // 100:,}.{amount % 100:02d}'
    return sign + _SYMBOLS[currency] + number


def balance_displays(rows, fx, currencies=None):
    """Preformatted combined-position strings so browser JS never performs money arithmetic."""
    codes = tuple(currencies or [row['currency'] for row in rows] or ('IDR',))
    result = {}
    for code in codes:
        if code not in SUPPORTED:
            continue
        total = convert_total(rows, code, fx)
        estimated = any(row['currency'] != code and row['balance_minor'] != 0 for row in rows)
        reference_lines = []
        for row in rows:
            if row['balance_minor'] == 0 or row['currency'] == code:
                continue
            rate = reference_pair(row['currency'], code, fx)
            if rate is not None:
                text = format(rate, ',.6f').rstrip('0').rstrip('.')
                reference_lines.append('1 ' + row['currency'] + ' ≈ ' + text + ' ' + code)
        result[code] = {
            'value':'Kurs belum lengkap' if total is None else format_money(total, code),
            'complete':total is not None,
            'estimated':estimated,
            'rates':' · '.join(reference_lines),
            'label':('Estimasi gabungan dalam ' if estimated else 'Saldo dalam ') + code,
        }
    return result
