"""Disabled-by-default outbound DEMO telemetry. Credentials and time claims confer no runtime."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
import re
import secrets
from . import access, bridge_store
from .store import query

MAX_BYTES = 16384
SERVER = 'XMGlobal-MT5 10'
SYMBOLS = ('GOLD', 'BTCUSD')
FLAGS = ('runtime_eligible', 'broker_execution_allowed', 'ai_analysis', 'paper_execution')
SOURCE_MAX_AGE_SECONDS = 5

class Rejected(ValueError):
    def __init__(self, code='INVALID_PAYLOAD', status=409):
        self.code, self.status = code, status
        super().__init__(code)

def now(): return datetime.now(timezone.utc)
def enabled(): return os.environ.get('KILAS_TRADING_BRIDGE_ENABLED') == 'true'
def digest(value): return hashlib.sha256(value.encode('ascii')).hexdigest()
def require(ok, code='INVALID_PAYLOAD', status=409):
    if not ok: raise Rejected(code, status)
def exact(value, keys):
    require(type(value) is dict and set(value) == set(keys))
    return value
def stamp(value): return value.isoformat()
def date(value):
    require(type(value) is str and len(value) <= 40)
    try: result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError: raise Rejected() from None
    require(result.tzinfo is not None and result.utcoffset().total_seconds() == 0)
    return result
def positive(value):
    require(type(value) is str and len(value) <= 24 and re.fullmatch(r'\d{1,9}(?:\.\d{1,8})?', value))
    try: result = Decimal(value)
    except InvalidOperation: raise Rejected() from None
    require(0 < result <= 100000000)
    return result
def secret(value, length=64):
    require(type(value) is str and re.fullmatch(r'[0-9a-f]{'+str(length)+'}', value), 'INVALID_CREDENTIAL', 401)
    return value

def parse(data):
    require(type(data) is bytes and 0 < len(data) <= MAX_BYTES, 'PAYLOAD_TOO_LARGE', 413)
    def unique(pairs):
        out = {}
        for key, value in pairs:
            require(key not in out and key not in ('__proto__', 'constructor', 'prototype'))
            out[key] = value
        return out
    try:
        result = json.loads(data.decode('utf-8'), object_pairs_hook=unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(Rejected()))
        require(type(result) is dict)
        return result
    except (UnicodeError, ValueError, RecursionError): raise Rejected() from None

def validate_market(value, symbol):
    exact(value, ('symbol', 'timeframe', 'tick', 'capture', 'candles', 'clock', 'clock_profile'))
    require(value['symbol'] == symbol and value['timeframe'] == 'M1')
    tick = exact(value['tick'], ('time', 'time_msc', 'bid', 'ask'))
    require(all(type(tick[k]) is int and 0 < tick[k] < 10**15 for k in ('time', 'time_msc')))
    require(tick['time_msc']//1000 == tick['time'] and positive(tick['ask']) >= positive(tick['bid']))
    capture = exact(value['capture'], ('start_utc', 'end_utc', 'start_mono_ns', 'end_mono_ns'))
    start, end = date(capture['start_utc']), date(capture['end_utc'])
    require(all(type(capture[k]) is int and 0 <= capture[k] < 2**63 for k in ('start_mono_ns', 'end_mono_ns')))
    elapsed = capture['end_mono_ns']-capture['start_mono_ns']
    require(0 < elapsed <= 2000000000 and 0 < (end-start).total_seconds() <= 2
            and abs((end-start).total_seconds()-elapsed/1e9) <= .050)
    bars = value['candles']
    require(type(bars) is list and len(bars) == 12)
    previous = None
    for bar in bars:
        exact(bar, ('time', 'open', 'high', 'low', 'close'))
        t = bar['time']
        require(type(t) is int and 0 < t < 10**15 and t % 60 == 0 and (previous is None or t-previous == 60))
        o,h,l,c = [positive(bar[k]) for k in ('open', 'high', 'low', 'close')]
        require(l <= min(o,c) <= max(o,c) <= h and t+60 <= tick['time'])
        previous = t
    require(0 <= tick['time']-(previous+60) < 60)
    if value['clock'] is not None:
        clock = exact(value['clock'], ('status', 'offset_seconds', 'uncertainty_ms'))
        require(clock['status'] == 'PRODUCER_CLAIM_ONLY')
        for key in ('offset_seconds', 'uncertainty_ms'):
            v = clock[key]
            require(type(v) is str and len(v) <= 24 and re.fullmatch(r'-?\d{1,5}(?:\.\d{1,8})?', v))
        require(abs(Decimal(clock['offset_seconds'])) <= 60 and 0 <= Decimal(clock['uncertainty_ms']) <= 10000)
    if value['clock_profile'] is not None:
        profile = exact(value['clock_profile'], ('profile_id', 'candidate_offset_seconds', 'evidence_ref'))
        require(all(type(profile[k]) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', profile[k]) for k in ('profile_id', 'evidence_ref')))
        require(type(profile['candidate_offset_seconds']) is int and abs(profile['candidate_offset_seconds']) <= 50400)
    return value

def pilot(conn, user):
    require(access.enabled() and query(conn, "SELECT 1 AS ok FROM users u JOIN oauth_identities o ON o.user_id=u.id WHERE u.id=? AND lower(u.email)=? AND o.provider='google' AND lower(o.email_at_link)=?", (user, access.PILOT_EMAIL, access.PILOT_EMAIL), one=True), 'ACCESS_REVOKED', 401)

def pair(user, data):
    exact(data, ('symbol', 'server'))
    require(data['symbol'] in SYMBOLS and data['server'] == SERVER)
    current = now()
    code, ident = secrets.token_hex(16), secrets.token_hex(16)
    with bridge_store.transaction() as conn:
        pilot(conn, user)
        row = query(conn, 'SELECT pair_expires FROM kilas_trading_bridges WHERE user_id=?', (user,), one=True)
        require(not row or current >= date(row['pair_expires'])-timedelta(seconds=270), 'PAIR_RATE_LIMIT', 429)
        query(conn, 'DELETE FROM kilas_trading_bridges WHERE user_id=?', (user,))
        query(conn, 'INSERT INTO kilas_trading_bridges(user_id,bridge_id,symbol,server,pair_hash,pair_expires) VALUES (?,?,?,?,?,?)', (user, ident, data['symbol'], SERVER, digest(code), stamp(current+timedelta(minutes=5))))
    return dict(pair_code=code, bridge_id=ident, expires_at=stamp(current+timedelta(minutes=5)), symbol=data['symbol'], server=SERVER)

def exchange(data):
    exact(data, ('pair_code', 'symbol', 'server'))
    code = secret(data['pair_code'], 32)
    with bridge_store.transaction() as conn:
        row = query(conn, 'SELECT * FROM kilas_trading_bridges WHERE pair_hash=?', (digest(code),), one=True)
        current = now()
        require(row and not row['revoked'] and date(row['pair_expires'])-timedelta(minutes=5) <= current < date(row['pair_expires']), 'INVALID_CREDENTIAL', 401)
        pilot(conn, row['user_id'])
        require(row['symbol'] == data['symbol'] and row['server'] == data['server'], 'SCOPE_MISMATCH', 401)
        token, challenge = secrets.token_hex(32), secrets.token_hex(32)
        expiry, deadline = current+timedelta(hours=1), current+timedelta(seconds=10)
        query(conn, 'UPDATE kilas_trading_bridges SET pair_hash=NULL,token_hash=?,token_expires=?,challenge_hash=?,challenge_expires=? WHERE user_id=?', (digest(token),stamp(expiry),digest(challenge),stamp(deadline),row['user_id']))
    return dict(token=token, expires_at=stamp(expiry), challenge=challenge, challenge_expires_at=stamp(deadline), sequence=0, symbol=row['symbol'], server=row['server'])

def telemetry(token, data):
    secret(token)
    exact(data, ('schema_version','sequence','server_challenge','message_kind','server','account_mode','terminal_connected','market',*FLAGS))
    require(type(data['schema_version']) is int and data['schema_version'] == 1)
    require(type(data['sequence']) is int and 0 < data['sequence'] < 2**63)
    require(data['message_kind'] in ('HEARTBEAT','MARKET') and type(data['terminal_connected']) is bool)
    require(data['account_mode'] in ('DEMO','UNKNOWN') and all(data[k] is False for k in FLAGS))
    secret(data['server_challenge'])
    with bridge_store.transaction() as conn:
        row = query(conn, 'SELECT * FROM kilas_trading_bridges WHERE token_hash=?', (digest(token),), one=True)
        current = now()
        require(row and not row['revoked'] and date(row['token_expires'])-timedelta(hours=1) <= current < date(row['token_expires']), 'INVALID_CREDENTIAL', 401)
        pilot(conn, row['user_id'])
        require(data['server'] == row['server'], 'SCOPE_MISMATCH', 401)
        require(data['sequence'] == row['sequence']+1 and row['challenge_hash'] and secrets.compare_digest(digest(data['server_challenge']),row['challenge_hash']) and date(row['challenge_expires'])-timedelta(seconds=10) <= current < date(row['challenge_expires']), 'REPLAY_OR_EXPIRED_CHALLENGE')
        require(not row['last_received'] or (current-date(row['last_received'])).total_seconds() >= 1, 'TELEMETRY_RATE_LIMIT', 429)
        market, advancing = None, False
        if data['message_kind'] == 'MARKET':
            require(data['terminal_connected'] and data['account_mode'] == 'DEMO')
            market = validate_market(data['market'], row['symbol'])
            prior = json.loads(row['market_json']) if row['market_json'] else None
            require(prior is None or market['tick']['time_msc'] >= prior['tick']['time_msc'], 'BACKWARDS_TICK')
            advancing = prior is not None and market['tick']['time_msc'] > prior['tick']['time_msc']
        else: require(data['market'] is None)
        challenge = secrets.token_hex(32)
        deadline = current+timedelta(seconds=10)
        query(conn, 'UPDATE kilas_trading_bridges SET sequence=?,challenge_hash=?,challenge_expires=?,last_received=?,terminal_connected=?,market_json=?,advancing=? WHERE user_id=?', (data['sequence'],digest(challenge),stamp(deadline),stamp(current),int(data['terminal_connected'] and data['account_mode']=='DEMO'),json.dumps(market) if market else None,int(advancing),row['user_id']))
    return dict(outcome='RECEIVED_READ_ONLY', sequence=data['sequence'], challenge=challenge, challenge_expires_at=stamp(deadline), **{k:False for k in FLAGS})

def revoke(user):
    with bridge_store.transaction() as conn:
        pilot(conn,user)
        query(conn, 'UPDATE kilas_trading_bridges SET revoked=1,pair_hash=NULL,token_hash=NULL,challenge_hash=NULL,market_json=NULL,terminal_connected=0 WHERE user_id=?', (user,))
    return dict(outcome='REVOKED')

def status(user):
    result = dict(enabled=enabled(), outcome='DISABLED' if not enabled() else 'NOT_PAIRED',
                  transport='DISCONNECTED', terminal='UNKNOWN', market_freshness='UNVERIFIED',
                  source_max_age_seconds=SOURCE_MAX_AGE_SECONDS, clock_profile_verification='NOT_INDEPENDENTLY_VERIFIED',
                  producer_acceptance='NOT_IMPLEMENTED', policy_replay_only=False, **{k:False for k in FLAGS})
    if not enabled(): return result
    try:
        with bridge_store.transaction() as conn:
            pilot(conn,user)
            row = query(conn, 'SELECT * FROM kilas_trading_bridges WHERE user_id=?', (user,), one=True)
    except Rejected: raise
    except Exception:
        return dict(result,outcome='SCHEMA_UNAVAILABLE')
    if not row: return result
    current = now()
    result.update(bridge_id=row['bridge_id'],symbol=row['symbol'],server=row['server'])
    if row['revoked']: return dict(result,outcome='REVOKED')
    if not row['token_hash']: return dict(result,outcome='PAIR_PENDING' if current < date(row['pair_expires']) else 'PAIR_EXPIRED')
    if current >= date(row['token_expires']): return dict(result,outcome='TOKEN_EXPIRED')
    if not row['last_received']: return dict(result,outcome='WAITING_COLLECTOR')
    age = (current-date(row['last_received'])).total_seconds()
    if age < 0:
        return dict(result,outcome='SERVER_CLOCK_DISCONTINUITY',market_freshness='UNAVAILABLE_SERVER_CLOCK')
    transport = 'CONNECTED' if age <= 6 else 'STALE' if age <= 15 else 'DISCONNECTED'
    result.update(outcome='READ_ONLY_TELEMETRY',transport=transport,last_received_at=row['last_received'],receipt_age_seconds=age,
                  terminal='DEMO_DECLARED' if row['terminal_connected'] else 'DISCONNECTED_OR_UNKNOWN')
    if row['market_json']:
        result['market'] = json.loads(row['market_json'])
        result['market_freshness'] = 'UNVERIFIED_CLOCK_PROFILE' if row['advancing'] else 'NONADVANCING_OR_FIRST_OBSERVATION'
    if transport != 'CONNECTED': result['market_freshness'] = 'UNAVAILABLE_TRANSPORT_STALE'
    # No trusted broker clock/profile exists in this release. Receipt/challenge
    # prove recent transport, never the <=5s worst-case source age requirement.
    return result
