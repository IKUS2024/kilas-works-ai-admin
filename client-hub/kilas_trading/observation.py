"""Pilot-only market observations. Never a data source for analysis or execution."""
import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from flask import current_app, has_app_context
from .engine import TradingError
from . import store

FIELDS = {'kind', 'source_symbol', 'bid', 'ask', 'time', 'time_msc', 'observed_at_utc'}
MAX_FILE_BYTES = 8192
ACTION = 'MARKET_OBSERVATION'
KEY = 'market-observation-current-v1'


def enabled():
    return os.environ.get('KILAS_TRADING_OBSERVATION_ENABLED', 'true').lower() == 'true'


def validate_fixture(raw):
    if not has_app_context() or not current_app.testing:
        raise TradingError('Ingestion belum diaktifkan. Fixture hanya untuk pengujian offline.')
    return _validate(raw, fixture=True)


def _validate(raw, *, fixture=False):
    allowed = FIELDS if fixture else FIELDS | {'schema_version'}
    extra = {'timeframe', 'candles'} if not fixture and isinstance(raw, dict) and 'candles' in raw else set()
    if not isinstance(raw, dict) or set(raw) != allowed | extra or raw['kind'] != ('TEST_FIXTURE' if fixture else 'DEMO'):
        raise TradingError('Hanya schema market-only; field akun, credential dan klaim freshness ditolak.')
    if not fixture and (type(raw['schema_version']) != int or raw['schema_version'] != 1 or raw['source_symbol'] != 'GOLD'):
        raise TradingError('Schema harus v1, kind DEMO, simbol sumber GOLD; mapping canonical belum diketahui.')
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
    if extra:
        bars = raw['candles']; interval = {'M1':60, 'M5':300, 'M15':900}.get(raw['timeframe']) if isinstance(raw['timeframe'], str) else None
        if not interval or not isinstance(bars, list) or not 1 <= len(bars) <= 48:
            raise TradingError('Candle observasi: M1/M5/M15 dan 1–48 bar mentah; tidak mengklaim closed/fresh.')
        last = None
        import re
        for bar in bars:
            if not isinstance(bar, dict) or set(bar) != {'time', 'open', 'high', 'low', 'close'}:
                raise TradingError('Field candle hanya raw time dan OHLC; data akun ditolak.')
            t = bar['time']
            if type(t) != int or not 0 < t < 10**15 or last is not None and t-last != interval:
                raise TradingError('Urutan/interval raw candle tidak valid.')
            last = t
            values = [bar[k] for k in ('open', 'high', 'low', 'close')]
            if any(not isinstance(v, str) or len(v) > 24 or not re.fullmatch(r'\d+(?:\.\d{1,8})?', v) for v in values):
                raise TradingError('OHLC harus decimal string positif.')
            prices = [Decimal(v) for v in values]
            if any(not 0 < p <= 100000000 for p in prices) or prices[2] > min(prices) or prices[1] < max(prices):
                raise TradingError('Nilai OHLC tidak valid.')
    # Receipt time is not event time. No subtraction, freshness inference or symbol alias.
    return dict(raw, observed_at_utc=at.astimezone(timezone.utc).isoformat(),
                canonical_symbol=None, mapping_status='unknown', event_time_utc=None,
                source_time_status='unverified', freshness='unknown',
                ai_analysis=False, paper_execution=False, ingestion_enabled=False,
                candle_time_semantics='unverified', outcome='OBSERVATION_ONLY')


def parse_file(content):
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_FILE_BYTES:
        raise TradingError('File JSON harus 1–8192 byte.')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('duplicate_key')
            result[key] = value
        return result
    try:
        raw = json.loads(content.decode('utf-8'), object_pairs_hook=unique,
                         parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite')))
        return _validate(raw)
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise TradingError('File bukan UTF-8 JSON valid; field duplikat/nonfinite ditolak.') from None


def ingest(user, content):
    if not enabled(): raise TradingError('Upload observasi dinonaktifkan.')
    result = parse_file(content)
    # Hash only validated input; client cannot grant analysis/execution capabilities.
    fingerprint = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    with store.locked(user) as conn:
        if not enabled(): raise TradingError('Upload observasi dinonaktifkan.')
        row = store.query(conn, 'SELECT * FROM kilas_trading_events WHERE user_id=? AND operation_key=?', (user, KEY), one=True)
        if row and row['action'] != ACTION: raise TradingError('Slot observasi perlu ditinjau.')
        if row and row['fingerprint'] == fingerprint:
            return dict(outcome='OK', message='Snapshot identik sudah tersimpan; tidak diulang.', duplicate=True, ai_analysis=False, paper_execution=False)
        now = store.now()
        if row:
            at = datetime.fromisoformat(row['created_at'])
            if not 30 <= (now-at).total_seconds():
                raise TradingError('Maksimal satu snapshot baru per 30 detik. Tidak ada upload otomatis.')
        result['received_at_utc'] = now.isoformat()
        result['ingestion_enabled'] = True
        payload = json.dumps(result)
        message = 'Observasi DEMO unggahan manual. Waktu/mapping belum terverifikasi; tidak dipakai AI/order.'
        # One current snapshot per pilot: bounded replacement, not an unbounded observation log.
        if row:
            store.query(conn, 'UPDATE kilas_trading_events SET fingerprint=?,inputs_json=?,created_at=? WHERE id=? AND user_id=?', (fingerprint, payload, now.isoformat(), row['id'], user))
        else:
            store.query(conn, 'INSERT INTO kilas_trading_events(user_id,operation_key,fingerprint,action,outcome,message,inputs_json,created_at) VALUES (?,?,?,?,?,?,?,?)', (user, KEY, fingerprint, ACTION, 'OBSERVATION_ONLY', message, payload, now.isoformat()))
    return dict(outcome='OK', message=message, duplicate=False, ai_analysis=False, paper_execution=False)


def view(user=None):
    unavailable = dict(outcome='UNAVAILABLE', ingestion_enabled=enabled(), kind=None,
                       canonical_symbol=None, mapping_status='unknown', event_time_utc=None,
                       source_time_status='unverified', freshness='unknown',
                       ai_analysis=False, paper_execution=False)
    raw = current_app.config.get('KILAS_TRADING_OBSERVATION_FIXTURE') if has_app_context() and current_app.testing else None
    if raw is None:
        if user is None: return unavailable
        with store.locked(user) as conn:
            row = store.query(conn, 'SELECT inputs_json FROM kilas_trading_events WHERE user_id=? AND operation_key=? AND action=?', (user, KEY, ACTION), one=True)
        if not row: return unavailable
        saved = json.loads(row['inputs_json'])
        fields = FIELDS | {'schema_version'} | ({'timeframe', 'candles'} if 'candles' in saved else set())
        safe = _validate({k:saved[k] for k in fields})
        return dict(safe, received_at_utc=saved['received_at_utc'], ingestion_enabled=enabled())
    try:
        return validate_fixture(raw)
    except TradingError:
        return dict(unavailable, outcome='REJECTED')
