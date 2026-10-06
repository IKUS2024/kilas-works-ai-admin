"""Independent transactions touching only Trader tables; serialized per paper account."""
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import db
from . import engine, access


def now():
    return datetime.now(timezone.utc)


def stamp():
    return now().isoformat()


def query(conn, sql, params=(), *, one=False):
    cur = conn.cursor()
    try:
        cur.execute(db._adapt_placeholders(sql), params)
        if cur.description:
            names = [c[0] for c in cur.description]
            rows = [dict(zip(names, row)) for row in cur.fetchall()]
            return (rows[0] if rows else None) if one else rows
        return cur.lastrowid if db.BACKEND == 'sqlite' else None
    finally:
        cur.close()


@contextmanager
def locked(user):
    conn = db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs()) if db.BACKEND == 'postgres' else sqlite3.connect(db.SQLITE_PATH, timeout=10)
    try:
        if db.BACKEND == 'sqlite':
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('BEGIN IMMEDIATE')
        else:
            query(conn, "SET LOCAL lock_timeout='10s'")
        pilot = query(conn, "SELECT u.id FROM users u JOIN oauth_identities o ON o.user_id=u.id WHERE u.id=? AND lower(u.email)=? AND o.provider='google' AND lower(o.email_at_link)=?", (user, access.PILOT_EMAIL, access.PILOT_EMAIL), one=True)
        if not access.enabled() or not pilot:
            raise PermissionError('pilot_only')
        timestamp = stamp()
        query(conn, 'INSERT INTO kilas_trading_accounts(user_id,generated_at,updated_at,risk_json,strategy_json) VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO NOTHING', (user, timestamp, timestamp, json.dumps(engine.RISK), json.dumps(engine.STRATEGY)))
        query(conn, 'UPDATE kilas_trading_accounts SET user_id=user_id WHERE user_id=?', (user,))
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def account(conn, user):
    return query(conn, 'SELECT * FROM kilas_trading_accounts WHERE user_id=?', (user,), one=True)


def positions(conn, user):
    return query(conn, "SELECT * FROM kilas_trading_positions WHERE user_id=? AND status='OPEN' ORDER BY id", (user,))


def fresh(a):
    age = (now() - datetime.fromisoformat(a['generated_at'])).total_seconds()
    return 0 <= age <= 120


def snapshot(user):
    with locked(user) as conn:
        a = account(conn, user)
        opened = positions(conn, user)
        bars = engine.candles(a['tick'])
        price = bars[-1]['close']
        for p in opened:
            p['unrealized_cents'] = engine.pnl(p, price)
        realized_today = query(conn, "SELECT COALESCE(SUM(pnl_cents),0) AS pnl FROM kilas_trading_positions WHERE user_id=? AND status='CLOSED' AND closed_at>=?", (user, now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()), one=True)['pnl']
        events = query(conn, 'SELECT * FROM kilas_trading_events WHERE user_id=? ORDER BY id DESC LIMIT 50', (user,))
        for event in events:
            event['inputs'] = json.loads(event['inputs_json'])
        return {'account': a, 'positions': opened, 'events': events, 'candles': bars, 'price_cents': price,
                'fresh': fresh(a), 'source': engine.SOURCE, 'source_time': bars[-1]['source_time'],
                'equity_cents': a['initial_cents'] + a['realized_cents'] + sum(p['unrealized_cents'] for p in opened),
                'exposure_cents': sum(price * p['quantity_units'] // engine.UNITS for p in opened),
                'today_pnl_cents': realized_today, 'risk': json.loads(a['risk_json']), 'strategy': json.loads(a['strategy_json'])}


def _close(conn, user, position, price, reason):
    result = engine.pnl(position, price)
    query(conn, "UPDATE kilas_trading_positions SET status='CLOSED',exit_cents=?,pnl_cents=?,close_reason=?,closed_at=? WHERE id=? AND user_id=? AND status='OPEN'", (price, result, reason, stamp(), position['id'], user))
    query(conn, 'UPDATE kilas_trading_accounts SET realized_cents=realized_cents+? WHERE user_id=?', (result, user))
    return {'position_id': position['id'], 'exit_cents': price, 'pnl_cents': result, 'reason': reason}


def _order(conn, user, a, data):
    if a['paused'] or a['killed']:
        raise engine.TradingError('Trading dijeda atau kill switch aktif. Posisi baru diblokir.')
    if not fresh(a):
        raise engine.TradingError('Snapshot simulasi kedaluwarsa. Perbarui snapshot replay dahulu.')
    side = data.get('side')
    if side not in ('BUY', 'SELL'):
        raise engine.TradingError('Pilih BUY atau SELL simulasi.')
    quantity = engine.scaled(data.get('quantity'), engine.UNITS, engine.UNITS)
    stop, target = engine.scaled(data.get('stop'), 100), engine.scaled(data.get('target'), 100)
    trailing = engine.scaled(data.get('trailing_distance', '0'), 100)
    activation = engine.scaled(data.get('trailing_activation', '0'), 100)
    price = engine.candle(a['tick'])['close']
    sign = 1 if side == 'BUY' else -1
    if not quantity or sign * (price - stop) <= 0 or sign * (target - price) <= 0 or stop <= 0:
        raise engine.TradingError('SL dan TP harus berada di sisi harga yang benar, dengan jumlah positif.')
    if trailing and (activation < trailing or trailing >= price):
        raise engine.TradingError('Aktivasi trailing harus ≥ jarak trailing dan jarak harus di bawah harga.')
    risk = json.loads(a['risk_json'])
    opened = positions(conn, user)
    equity = a['initial_cents'] + a['realized_cents'] + sum(engine.pnl(p, price) for p in opened)
    trade_risk = (abs(price - stop) * quantity + engine.UNITS - 1) // engine.UNITS
    if equity <= 0 or trade_risk > equity * risk['risk_bps'] // 10000:
        raise engine.TradingError('Risiko SL melebihi batas risiko per posisi.')
    if len(opened) >= risk['max_positions']:
        raise engine.TradingError('Jumlah posisi terbuka mencapai batas.')
    exposure = price * (quantity + sum(p['quantity_units'] for p in opened)) // engine.UNITS
    if exposure > min(risk['max_exposure_cents'], max(0, equity) * 20 // 100):
        raise engine.TradingError('Eksposur total melebihi batas 20% ekuitas atau batas nominal.')
    day = now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    daily = query(conn, "SELECT COALESCE(SUM(pnl_cents),0) AS pnl FROM kilas_trading_positions WHERE user_id=? AND status='CLOSED' AND closed_at>=?", (user, day), one=True)['pnl']
    unrealized = sum(engine.pnl(p, price) for p in opened)
    if daily + unrealized <= -risk['daily_loss_cents']:
        raise engine.TradingError('Batas kerugian harian tercapai; posisi baru diblokir.')
    sql = 'INSERT INTO kilas_trading_positions(user_id,side,quantity_units,entry_cents,stop_cents,target_cents,trailing_cents,activation_cents,opened_at) VALUES (?,?,?,?,?,?,?,?,?)'
    params = (user, side, quantity, price, stop, target, trailing, activation, stamp())
    ident = query(conn, sql + ' RETURNING id', params, one=True)['id'] if db.BACKEND == 'postgres' else query(conn, sql, params)
    return {'position_id': ident, 'side': side, 'fill_cents': price, 'quantity_units': quantity,
            'stop_cents': stop, 'target_cents': target, 'risk_cents': trade_risk, 'equity_cents': equity, 'exposure_cents': exposure}


def _configure(data):
    risk = {'risk_bps': engine.scaled(data.get('risk_percent'), 100, 100),
            'max_positions': engine.scaled(data.get('max_positions'), 1, 3),
            'max_exposure_cents': engine.scaled(data.get('max_exposure'), 100, 200000),
            'daily_loss_cents': engine.scaled(data.get('daily_loss'), 100, 50000)}
    if any(v <= 0 for v in risk.values()):
        raise engine.TradingError('Semua batas risiko harus positif.')
    cfg = {'fast': engine.scaled(data.get('fast'), 1, 10), 'slow': engine.scaled(data.get('slow'), 1, 30),
           'threshold_bps': engine.scaled(data.get('threshold_bps'), 1, 100)}
    if not 2 <= cfg['fast'] < cfg['slow']:
        raise engine.TradingError('SMA cepat minimal 2 dan harus lebih kecil dari SMA lambat (maksimal 30).')
    for name, scale in [('quantity', engine.UNITS), ('stop_distance', 100), ('target_distance', 100), ('trailing_distance', 100), ('trailing_activation', 100)]:
        value = engine.scaled(data.get(name), scale, engine.UNITS if name == 'quantity' else 100000000)
        if name in ('quantity', 'stop_distance', 'target_distance') and value <= 0:
            raise engine.TradingError('Jumlah, jarak SL, dan jarak TP harus positif.')
        cfg[name] = str(Decimal(value) / scale)
    if Decimal(cfg['trailing_distance']) > Decimal(cfg['trailing_activation']):
        raise engine.TradingError('Aktivasi trailing harus ≥ jarak trailing.')
    return risk, cfg


from decimal import Decimal


def act(user, action, data):
    if action not in ('order', 'close', 'protect', 'step', 'refresh', 'pause', 'resume', 'kill', 'configure', 'agent'):
        raise engine.TradingError('Aksi tidak tersedia.')
    key = str(data.get('operation_key', ''))
    if not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}', key):
        raise engine.TradingError('Kunci permintaan tidak valid. Muat ulang halaman.')
    payload = {k: v for k, v in data.items() if k not in ('operation_key', 'csrf_token')}
    fingerprint = hashlib.sha256(json.dumps([action, payload], sort_keys=True).encode()).hexdigest()
    with locked(user) as conn:
        a = account(conn, user)
        # An agent may evaluate/order at most once per candle, including other tabs/retries.
        if action == 'agent':
            key = 'agent-candle-' + str(data.get('tick', ''))
        existing = query(conn, 'SELECT * FROM kilas_trading_events WHERE user_id=? AND operation_key=?', (user, key), one=True)
        if existing:
            if existing['fingerprint'] != fingerprint:
                raise engine.TradingError('Permintaan dengan kunci ini berubah. Muat ulang halaman.')
            return {'outcome': existing['outcome'], 'message': existing['message'], 'duplicate': True}
        if query(conn, 'SELECT COUNT(*) AS n FROM kilas_trading_events WHERE user_id=? AND created_at>?', (user, (now()-timedelta(minutes=1)).isoformat()), one=True)['n'] >= 30:
            raise engine.TradingError('Maksimal 30 aksi per menit. Tunggu sebentar.')
        price = engine.candle(a['tick'])['close']
        inputs = {'source': engine.SOURCE, 'source_time': engine.candle(a['tick'])['source_time'], 'generated_at': a['generated_at'], 'tick': a['tick'], 'quote_cents': price, 'request': payload}
        outcome, message = 'OK', 'Aksi simulasi selesai.'
        try:
            if action in ('order', 'close', 'protect', 'step', 'refresh', 'agent') and str(data.get('tick')) != str(a['tick']):
                raise engine.TradingError('Replay sudah berubah di tab lain. Muat ulang dahulu.')
            if action in ('order', 'close', 'protect', 'agent') and not fresh(a):
                raise engine.TradingError('Snapshot simulasi kedaluwarsa. Perbarui snapshot replay dahulu.')
            if action == 'order':
                inputs['result'] = _order(conn, user, a, data)
                message = 'Posisi ' + data['side'] + ' MOCK dibuka.'
            elif action in ('close', 'protect'):
                ident = engine.scaled(data.get('position_id'), 1)
                p = query(conn, "SELECT * FROM kilas_trading_positions WHERE id=? AND user_id=? AND status='OPEN'", (ident, user), one=True)
                if not p:
                    raise engine.TradingError('Posisi terbuka tidak ditemukan untuk akun ini.')
                if action == 'close':
                    inputs['result'] = _close(conn, user, p, price, 'MANUAL')
                    message = 'Posisi MOCK ditutup.'
                else:
                    stop, target = engine.scaled(data.get('stop'), 100), engine.scaled(data.get('target'), 100)
                    sign = 1 if p['side'] == 'BUY' else -1
                    if stop <= 0 or sign * (price-stop) <= 0 or sign * (target-price) <= 0 or sign * (stop-p['stop_cents']) < 0:
                        raise engine.TradingError('SL hanya dapat diperketat dan SL/TP harus berada di sisi harga yang benar.')
                    query(conn, 'UPDATE kilas_trading_positions SET stop_cents=?,target_cents=? WHERE id=? AND user_id=?', (stop, target, ident, user))
                    inputs['result'] = {'position_id': ident, 'stop_cents': stop, 'target_cents': target}
                    message = 'SL/TP posisi MOCK diperbarui.'
            elif action in ('step', 'refresh'):
                tick = a['tick'] + (1 if action == 'step' else 0)
                if tick > 100000:
                    raise engine.TradingError('Batas replay tercapai.')
                closures, trailing = [], []
                if action == 'step':
                    for p in positions(conn, user):
                        exit_price, reason, stop = engine.protect(p, engine.candle(tick))
                        if exit_price is not None:
                            closures.append(_close(conn, user, p, exit_price, reason))
                        elif stop != p['stop_cents']:
                            query(conn, 'UPDATE kilas_trading_positions SET stop_cents=? WHERE id=? AND user_id=?', (stop, p['id'], user))
                            trailing.append({'position_id': p['id'], 'stop_cents': stop})
                query(conn, 'UPDATE kilas_trading_accounts SET tick=?,generated_at=? WHERE user_id=?', (tick, stamp(), user))
                inputs.update(next_candle=engine.candle(tick), closed_positions=closures, trailing_updates=trailing)
                message = 'Replay maju satu candle; SL/TP dan trailing diperiksa.' if action == 'step' else 'Snapshot sintetis dibuat ulang pada candle yang sama; bukan harga live.'
            elif action in ('pause', 'resume', 'kill'):
                if action == 'resume' and a['killed']:
                    raise engine.TradingError('Kill switch terkunci. Pembukaan posisi tetap diblokir; posisi dapat ditutup manual.')
                query(conn, 'UPDATE kilas_trading_accounts SET paused=?,killed=? WHERE user_id=?', (0 if action == 'resume' else 1, 1 if action == 'kill' else a['killed'], user))
                message = {'pause': 'Posisi baru dijeda. Replay dan penutupan tetap tersedia.', 'resume': 'Simulasi dilanjutkan.', 'kill': 'Kill switch terkunci: semua posisi baru diblokir. Posisi lama tetap memiliki SL/TP dan dapat ditutup.'}[action]
            elif action == 'configure':
                risk, config = _configure(data)
                query(conn, 'UPDATE kilas_trading_accounts SET risk_json=?,strategy_json=? WHERE user_id=?', (json.dumps(risk), json.dumps(config), user))
                inputs.update(risk=risk, strategy=config)
                message = 'Batas risiko dan strategi paper disimpan. Tidak menjalankan strategi otomatis.'
            elif action == 'agent':
                side, evidence = engine.decision(json.loads(a['strategy_json']), engine.candles(a['tick']))
                inputs['decision'] = evidence
                if a['paused'] or a['killed']:
                    raise engine.TradingError('Strategi dijeda atau kill switch aktif.')
                if not side:
                    outcome, message = 'NO_SIGNAL', evidence['explanation']
                else:
                    cfg = json.loads(a['strategy_json'])
                    sign = 1 if side == 'BUY' else -1
                    order = dict(cfg, side=side, stop=str(Decimal(price-sign*engine.scaled(cfg['stop_distance'],100))/100), target=str(Decimal(price+sign*engine.scaled(cfg['target_distance'],100))/100))
                    inputs['result'] = _order(conn, user, a, order)
                    message = 'Persilangan SMA: posisi ' + side + ' MOCK dibuka setelah pemeriksaan risiko.'
        except engine.TradingError as exc:
            # Validation occurs before each action's writes. Retain the rejected decision too.
            outcome, message = 'REJECTED', str(exc)
        status = 'ERROR' if outcome == 'REJECTED' else 'IDLE'
        query(conn, 'UPDATE kilas_trading_accounts SET status=?,last_error=?,updated_at=? WHERE user_id=?', (status, message if outcome == 'REJECTED' else '', stamp(), user))
        query(conn, 'INSERT INTO kilas_trading_events(user_id,operation_key,fingerprint,action,outcome,message,inputs_json,created_at) VALUES (?,?,?,?,?,?,?,?)', (user, key, fingerprint, action, outcome, message, json.dumps(inputs), stamp()))
        return {'outcome': outcome, 'message': message, 'duplicate': False}
