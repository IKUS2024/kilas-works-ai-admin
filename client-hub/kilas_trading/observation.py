"""Offline market observations. No transport, storage, time normalization or execution."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from flask import current_app, has_app_context
from .engine import TradingError

FIELDS = {'kind', 'source_symbol', 'bid', 'ask', 'time', 'time_msc', 'observed_at_utc'}


def validate_fixture(raw):
    if not has_app_context() or not current_app.testing:
        raise TradingError('Ingestion belum diaktifkan. Fixture hanya untuk pengujian offline.')
    if not isinstance(raw, dict) or set(raw) != FIELDS or raw['kind'] != 'TEST_FIXTURE':
        raise TradingError('Hanya fixture market-only; field akun, credential dan klaim freshness ditolak.')
    import re
    if not isinstance(raw['source_symbol'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,24}', raw['source_symbol']):
        raise TradingError('Simbol sumber tidak valid.')
    try:
        prices = [Decimal(raw[k]) if isinstance(raw[k], str) and len(raw[k]) <= 24 else Decimal('NaN') for k in ('bid', 'ask')]
        if any(not p.is_finite() or not 0 < p <= 100000000 for p in prices) or prices[1] < prices[0]:
            raise ValueError()
        if any(type(raw[k]) != int or not 0 < raw[k] < 10**15 for k in ('time', 'time_msc')) or raw['time_msc']//1000 != raw['time']:
            raise ValueError()
        observed = raw['observed_at_utc']
        if not isinstance(observed, str) or len(observed) > 40:
            raise ValueError()
        at = datetime.fromisoformat(observed.replace('Z', '+00:00'))
        if at.tzinfo is None or at.utcoffset().total_seconds() != 0:
            raise ValueError()
    except (ValueError, TypeError, InvalidOperation):
        raise TradingError('Harga, raw tick time/time_msc atau observed_at_utc tidak valid.') from None
    # Receipt time is not event time. No subtraction, freshness inference or symbol alias.
    return dict(raw, observed_at_utc=at.astimezone(timezone.utc).isoformat(),
                canonical_symbol=None, mapping_status='unknown', event_time_utc=None,
                source_time_status='unverified', freshness='unknown',
                ai_analysis=False, paper_execution=False, ingestion_enabled=False,
                outcome='OBSERVATION_ONLY')


def view():
    unavailable = dict(outcome='UNAVAILABLE', ingestion_enabled=False, kind=None,
                       canonical_symbol=None, mapping_status='unknown', event_time_utc=None,
                       source_time_status='unverified', freshness='unknown',
                       ai_analysis=False, paper_execution=False)
    raw = current_app.config.get('KILAS_TRADING_OBSERVATION_FIXTURE') if has_app_context() and current_app.testing else None
    if raw is None:
        return unavailable
    try:
        return validate_fixture(raw)
    except TradingError:
        return dict(unavailable, outcome='REJECTED')
