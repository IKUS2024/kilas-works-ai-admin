"""Display-only Frankfurter v2 FX. No database, environment key or usage recording.

Public endpoint contract: https://frankfurter.dev/#rate
"""
import logging
import math
import re
import threading
import time
from datetime import date
from decimal import Decimal, InvalidOperation

import requests

URL = 'https://api.frankfurter.dev/v2/rate/USD/IDR'
CACHE_SECONDS = 30 * 60
FAILURE_CACHE_SECONDS = 60
_lock = threading.Lock()
_cached = None
_expires = 0.0
log = logging.getLogger(__name__)


def get_usd_idr():
    """One short request per refresh, including concurrent dashboard requests.

    Expired rates are not silently reused after failure. Negative caching avoids
    hammering an unavailable provider. No customer or usage data leaves the server.
    """
    global _cached, _expires
    with _lock:
        if time.monotonic() < _expires:
            return dict(_cached) if _cached else None
        try:
            response = requests.get(URL, timeout=2, allow_redirects=False)
            try:
                if response.status_code != 200:
                    raise ValueError('unavailable')
                data = response.json()
            finally:
                response.close()
            if not isinstance(data, dict) or data.get('base') != 'USD' or data.get('quote') != 'IDR':
                raise ValueError('invalid_pair')
            rate = data.get('rate')
            if type(rate) not in (float, int) or not math.isfinite(rate) or rate <= 0:
                raise ValueError('invalid_rate')
            rate_date = data.get('date')
            if not isinstance(rate_date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', rate_date):
                raise ValueError('invalid_date')
            date.fromisoformat(rate_date)
            _cached = {'rate': Decimal(str(rate)), 'date': rate_date, 'source': 'Frankfurter v2'}
            _expires = time.monotonic() + CACHE_SECONDS
        except Exception:
            # Never log a response body, raw exception, headers or user data.
            _cached = None
            _expires = time.monotonic() + FAILURE_CACHE_SECONDS
            log.warning('[AI_USAGE_FX] unavailable')
        return dict(_cached) if _cached else None


def display_rows(rows, fx):
    """Copy monthly output; historical cost_idr and database values stay untouched."""
    result = []
    for original in rows:
        row = dict(original)
        row['display_cost_idr'] = None
        row['display_contribution_idr'] = None
        if fx and row.get('cost_usd') is not None:
            try:
                usd = Decimal(str(row['cost_usd']))
                if usd.is_finite() and usd >= 0:
                    cost = usd * fx['rate']
                    row['display_cost_idr'] = cost
                    if row.get('reference_revenue_idr') is not None:
                        row['display_contribution_idr'] = Decimal(str(row['reference_revenue_idr'])) - cost
            except (InvalidOperation, ValueError, TypeError, KeyError):
                pass
        result.append(row)
    return result
