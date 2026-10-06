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
        current=account(conn,user)
        config=json.loads(current['strategy_json'])
        if config.get('market')!=engine.INSTRUMENT:
            activity=query(conn,'SELECT (SELECT count(*) FROM kilas_trading_positions WHERE user_id=?) + (SELECT count(*) FROM kilas_trading_events WHERE user_id=?) AS n',(user,user),one=True)['n']
            if activity or config!=engine.LEGACY_STRATEGY:
                raise engine.TradingError('Replay BTC sebelumnya memiliki aktivitas atau konfigurasi khusus. Perpindahan XAUUSD ditahan untuk menjaga data lama; perlu peninjauan operator.')
            # An unused account may adopt the clarified instrument. Retain prior config in audit.
            query(conn,'UPDATE kilas_trading_accounts SET strategy_json=?,generated_at=?,updated_at=? WHERE user_id=?',(json.dumps(engine.STRATEGY),timestamp,timestamp,user))
            evidence={'previous_instrument':'BTC/USD synthetic v1','previous_config':config,'instrument':engine.INSTRUMENT,'quantity_unit':'synthetic troy ounce','reason':'Owner clarified XAUUSD; unused paper account only; balances and history not reset.'}
            query(conn,'INSERT INTO kilas_trading_events(user_id,operation_key,fingerprint,action,outcome,message,inputs_json,created_at) VALUES (?,?,?,?,?,?,?,?)',(user,'instrument-xauusd-v1',hashlib.sha256(json.dumps(evidence).encode()).hexdigest(),'INSTRUMENT','OK','Workspace simulasi beralih ke XAUUSD; konfigurasi lama disimpan, tanpa trade lama yang ditafsir ulang.',json.dumps(evidence),timestamp))
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
            p['unrealized_cents'] = engine.mark_pnl(p, price, bars[-1]['spread_bps'])
        realized_today = query(conn, "SELECT COALESCE(SUM(pnl_cents),0) AS pnl FROM kilas_trading_positions WHERE user_id=? AND status='CLOSED' AND closed_at>=?", (user, now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()), one=True)['pnl']
        events = query(conn, 'SELECT * FROM kilas_trading_events WHERE user_id=? ORDER BY id DESC LIMIT 50', (user,))
        for event in events:
            event['inputs'] = json.loads(event['inputs_json'])
        return {'account': a, 'positions': opened, 'events': events, 'candles': bars, 'price_cents': price,
                'fresh': fresh(a), 'source': engine.SOURCE, 'contract':engine.CONTRACT,'source_time': bars[-1]['source_time'],
                'equity_cents': a['initial_cents'] + a['realized_cents'] + sum(p['unrealized_cents'] for p in opened),
                'exposure_cents': sum(price * p['quantity_units'] // engine.UNITS for p in opened),
                'today_pnl_cents': realized_today, 'risk': json.loads(a['risk_json']), 'strategy': json.loads(a['strategy_json'])}


def _close(conn, user, position, price, reason):
    price = engine.fill(price, 'SELL' if position['side']=='BUY' else 'BUY')
    result = engine.pnl(position, price)
    query(conn, "UPDATE kilas_trading_positions SET status='CLOSED',exit_cents=?,pnl_cents=?,close_reason=?,closed_at=? WHERE id=? AND user_id=? AND status='OPEN'", (price, result, reason, stamp(), position['id'], user))
    query(conn, 'UPDATE kilas_trading_accounts SET realized_cents=realized_cents+? WHERE user_id=?', (result, user))
    a=account(conn,user)
    losses=query(conn,"SELECT pnl_cents FROM kilas_trading_positions WHERE user_id=? AND status='CLOSED' ORDER BY closed_at DESC,id DESC LIMIT ?",(user,json.loads(a['risk_json'])['max_loss_streak']))
    if len(losses)==json.loads(a['risk_json'])['max_loss_streak'] and all(p['pnl_cents']<0 for p in losses):
        query(conn,'UPDATE kilas_trading_accounts SET cooldown_until=? WHERE user_id=?',((now()+timedelta(minutes=json.loads(a['risk_json'])['cooldown_minutes'])).isoformat(),user))
    return {'position_id': position['id'], 'exit_cents': price, 'pnl_cents': result, 'reason': reason,
            'entry_fee_cents':position['entry_fee_cents'],'exit_fee_cents':engine.fee(price,position['quantity_units'],position['fee_bps'])}


def _order(conn, user, a, data):
    if a['paused'] or a['killed']:
        raise engine.TradingError('Trading dijeda atau kill switch aktif. Posisi baru diblokir.')
    if not fresh(a):
        raise engine.TradingError('Snapshot simulasi kedaluwarsa. Perbarui snapshot replay dahulu.')
    if a['cooldown_until'] and now() < datetime.fromisoformat(a['cooldown_until']):
        raise engine.TradingError('Cooldown setelah losing streak aktif. Posisi baru diblokir sampai '+a['cooldown_until'])
    side = data.get('side')
    if side not in ('BUY', 'SELL'):
        raise engine.TradingError('Pilih BUY atau SELL simulasi.')
    quantity = engine.scaled(data.get('quantity'), engine.UNITS, engine.UNITS)
    stop, target = engine.scaled(data.get('stop'), 100), engine.scaled(data.get('target'), 100)
    trailing = engine.scaled(data.get('trailing_distance', '0'), 100)
    activation = engine.scaled(data.get('trailing_activation', '0'), 100)
    breakeven = engine.scaled(data.get('breakeven_activation','0'),100)
    risk = json.loads(a['risk_json'])
    bar = engine.candle(a['tick'])
    engine.quote_valid(bar,risk['max_spread_bps'])
    price = engine.fill(bar['close'],side,bar['spread_bps'])
    sign = 1 if side == 'BUY' else -1
    if not quantity or sign * (price - stop) <= 0 or sign * (target - price) <= 0 or stop <= 0:
        raise engine.TradingError('SL dan TP harus berada di sisi harga yang benar, dengan jumlah positif.')
    if trailing and (activation < trailing or trailing >= price):
        raise engine.TradingError('Aktivasi trailing harus ≥ jarak trailing dan jarak harus di bawah harga.')
    opened = positions(conn, user)
    equity = a['initial_cents'] + a['realized_cents'] + sum(engine.mark_pnl(p,bar['close'],bar['spread_bps']) for p in opened)
    exit_stop = engine.fill(stop,'SELL' if side=='BUY' else 'BUY',bar['spread_bps'])
    entry_fee = engine.fee(price,quantity)
    trade_risk = (abs(price - exit_stop) * quantity + engine.UNITS - 1) // engine.UNITS + entry_fee + engine.fee(exit_stop,quantity)
    # Risk never grows after losses or profits: initial equity is an additional ceiling.
    if equity <= 0 or trade_risk > min(equity,a['initial_cents']) * risk['risk_bps'] // 10000:
        raise engine.TradingError('Risiko SL melebihi batas risiko per posisi.')
    aggregate=sum(max(0,-engine.mark_pnl(p,p['stop_cents'],bar['spread_bps'])) for p in opened)
    if aggregate+trade_risk > equity*risk['aggregate_risk_bps']//10000:
        raise engine.TradingError('Risiko SL agregat melebihi batas akun.')
    if len(opened) >= risk['max_positions']:
        raise engine.TradingError('Jumlah posisi terbuka mencapai batas.')
    exposure = price * (quantity + sum(p['quantity_units'] for p in opened)) // engine.UNITS
    if exposure > min(risk['max_exposure_cents'], max(0, equity) * 20 // 100):
        raise engine.TradingError('Eksposur total melebihi batas 20% ekuitas atau batas nominal.')
    day = now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    daily = query(conn, "SELECT COALESCE(SUM(pnl_cents),0) AS pnl FROM kilas_trading_positions WHERE user_id=? AND status='CLOSED' AND closed_at>=?", (user, day), one=True)['pnl']
    unrealized = sum(engine.mark_pnl(p,bar['close'],bar['spread_bps']) for p in opened)
    if daily + unrealized <= -risk['daily_loss_cents']:
        raise engine.TradingError('Batas kerugian harian tercapai; posisi baru diblokir.')
    sql = 'INSERT INTO kilas_trading_positions(user_id,side,quantity_units,entry_cents,stop_cents,target_cents,trailing_cents,activation_cents,breakeven_cents,entry_fee_cents,fee_bps,opened_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)'
    params = (user, side, quantity, price, stop, target, trailing, activation, breakeven, entry_fee, engine.FEE_BPS, stamp())
    ident = query(conn, sql + ' RETURNING id', params, one=True)['id'] if db.BACKEND == 'postgres' else query(conn, sql, params)
    return {'position_id': ident, 'side': side, 'fill_cents': price, 'quantity_units': quantity,
            'stop_cents': stop, 'target_cents': target, 'risk_cents': trade_risk, 'equity_cents': equity, 'exposure_cents': exposure,
            'modeled_spread_bps':bar['spread_bps'],'modeled_fee_bps':engine.FEE_BPS,'modeled_slippage_bps':engine.SLIPPAGE_BPS,'entry_fee_cents':entry_fee}


def _configure(data):
    risk = {'risk_bps': engine.scaled(data.get('risk_percent'), 100, 100),
            'max_positions': engine.scaled(data.get('max_positions'), 1, 3),
            'max_exposure_cents': engine.scaled(data.get('max_exposure'), 100, 200000),
            'daily_loss_cents': engine.scaled(data.get('daily_loss'), 100, 50000),
            'aggregate_risk_bps':engine.scaled(data.get('aggregate_risk_percent','2'),100,200),
            'max_spread_bps':engine.scaled(data.get('max_spread_bps','20'),1,20),
            'max_loss_streak':engine.scaled(data.get('max_loss_streak','3'),1,3),
            'cooldown_minutes':engine.scaled(data.get('cooldown_minutes','5'),1,60)}
    if any(v <= 0 for v in risk.values()):
        raise engine.TradingError('Semua batas risiko harus positif.')
    cfg = {'market':engine.INSTRUMENT,'fast': engine.scaled(data.get('fast'), 1, 10), 'slow': engine.scaled(data.get('slow'), 1, 30),
           'threshold_bps': engine.scaled(data.get('threshold_bps'), 1, 100)}
    if not 2 <= cfg['fast'] < cfg['slow']:
        raise engine.TradingError('SMA cepat minimal 2 dan harus lebih kecil dari SMA lambat (maksimal 30).')
    for name, scale in [('quantity', engine.UNITS), ('stop_distance', 100), ('target_distance', 100), ('trailing_distance', 100), ('trailing_activation', 100),('breakeven_activation',100)]:
        value = engine.scaled(data.get(name,'0'), scale, engine.UNITS if name == 'quantity' else 100000000)
        if name in ('quantity', 'stop_distance', 'target_distance') and value <= 0:
            raise engine.TradingError('Jumlah, jarak SL, dan jarak TP harus positif.')
        cfg[name] = str(Decimal(value) / scale)
    if Decimal(cfg['trailing_distance']) > Decimal(cfg['trailing_activation']):
        raise engine.TradingError('Aktivasi trailing harus ≥ jarak trailing.')
    return risk, cfg


from decimal import Decimal


def _advance(conn,user,a):
    tick=a['tick']+1
    if tick>100000:
        raise engine.TradingError('Batas replay tercapai.')
    bar=engine.candle(tick)
    engine.quote_valid(bar,json.loads(a['risk_json'])['max_spread_bps'])
    closures,trailing=[],[]
    for p in positions(conn,user):
        exit_price,reason,stop=engine.protect(p,bar)
        if exit_price is not None:
            closures.append(_close(conn,user,p,exit_price,reason))
        elif stop!=p['stop_cents']:
            query(conn,'UPDATE kilas_trading_positions SET stop_cents=? WHERE id=? AND user_id=?',(stop,p['id'],user))
            trailing.append({'position_id':p['id'],'stop_cents':stop})
    query(conn,'UPDATE kilas_trading_accounts SET tick=?,generated_at=? WHERE user_id=?',(tick,stamp(),user))
    return {'next_candle':bar,'closed_positions':closures,'trailing_updates':trailing}


def _evaluate(conn,user,a,evidence):
    cfg=json.loads(a['strategy_json'])
    side,record=engine.decision(cfg,engine.candles(a['tick']))
    evidence['decision']=record
    if a['paused'] or a['killed']:
        raise engine.TradingError('Strategi dijeda atau kill switch aktif.')
    if not fresh(a):
        raise engine.TradingError('Snapshot simulasi kedaluwarsa.')
    bar=engine.candle(a['tick'])
    risk=json.loads(a['risk_json'])
    engine.quote_valid(bar,risk['max_spread_bps'])
    if not side:
        return 'NO_SIGNAL',record['explanation']
    sign=1 if side=='BUY' else -1
    price=bar['close']
    stop=price-sign*engine.scaled(cfg['stop_distance'],100)
    opened=positions(conn,user)
    equity=a['initial_cents']+a['realized_cents']+sum(engine.mark_pnl(p,price,bar['spread_bps']) for p in opened)
    budget=max(0,min(equity,a['initial_cents']))*risk['risk_bps']//10000
    entry=engine.fill(price,side,bar['spread_bps'])
    stop_fill=engine.fill(stop,'SELL' if side=='BUY' else 'BUY',bar['spread_bps'])
    per_unit=abs(entry-stop_fill)+(entry+abs(stop_fill))*engine.FEE_BPS//10000+2
    remaining=max(0,min(risk['max_exposure_cents'],equity*20//100)-price*sum(p['quantity_units'] for p in opened)//engine.UNITS)
    quantity=min(engine.scaled(cfg['quantity'],engine.UNITS,engine.UNITS),
                 max(0,budget-2)*engine.UNITS//max(1,per_unit),remaining*engine.UNITS//max(1,entry))
    evidence['sizing']={'method':'stop distance plus modeled costs; floor to micro-ounce, capped by configured quantity/exposure',
                        'risk_budget_cents':budget,'stop_distance_cents':abs(price-stop),
                        'modeled_per_ounce_risk_cents':per_unit,'quantity_units':quantity,'no_martingale':True}
    order=dict(cfg,side=side,quantity=str(Decimal(quantity)/engine.UNITS),
               stop=str(Decimal(stop)/100),target=str(Decimal(price+sign*engine.scaled(cfg['target_distance'],100))/100))
    evidence['result']=_order(conn,user,a,order)
    return 'OK','Persilangan SMA: posisi '+side+' MOCK dibuka setelah sizing dan pemeriksaan risiko.'


def act(user, action, data):
    if action not in ('order', 'close', 'protect', 'step', 'refresh', 'pause', 'resume', 'kill', 'configure', 'agent','run'):
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
        recent=query(conn, 'SELECT COUNT(*) AS n FROM kilas_trading_events WHERE user_id=? AND created_at>?', (user, (now()-timedelta(minutes=1)).isoformat()), one=True)['n']
        if action not in ('close','protect','pause','kill') and recent >= 30:
            raise engine.TradingError('Maksimal 30 aksi per menit. Tunggu sebentar.')
        price = engine.candle(a['tick'])['close']
        inputs = {'source': engine.SOURCE, 'contract':engine.CONTRACT,'source_time': engine.candle(a['tick'])['source_time'], 'generated_at': a['generated_at'], 'tick': a['tick'], 'quote_cents': price, 'request': payload}
        outcome, message = 'OK', 'Aksi simulasi selesai.'
        try:
            if action in ('order','close','protect','step','refresh','agent','run') and data.get('instrument')!=engine.INSTRUMENT:
                raise engine.TradingError('Instrumen replay berubah ke XAUUSD. Muat ulang halaman; order dari tampilan BTC lama diblokir.')
            if action in ('order', 'close', 'protect', 'step', 'refresh', 'agent','run') and str(data.get('tick')) != str(a['tick']):
                raise engine.TradingError('Replay sudah berubah di tab lain. Muat ulang dahulu.')
            if action in ('order', 'close', 'protect', 'agent','run') and not fresh(a):
                raise engine.TradingError('Snapshot simulasi kedaluwarsa. Perbarui snapshot replay dahulu.')
            if action in ('order','close','protect','agent','run'):
                engine.quote_valid(engine.candle(a['tick']),json.loads(a['risk_json'])['max_spread_bps'])
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
            elif action == 'step':
                inputs.update(_advance(conn,user,a))
                message = 'Replay maju satu candle; SL/TP, breakeven dan trailing diperiksa.'
            elif action == 'refresh':
                engine.quote_valid(engine.candle(a['tick']),json.loads(a['risk_json'])['max_spread_bps'])
                query(conn,'UPDATE kilas_trading_accounts SET generated_at=? WHERE user_id=?',(stamp(),user))
                message = 'Snapshot sintetis dibuat ulang pada candle yang sama; bukan harga live.'
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
                outcome,message=_evaluate(conn,user,a,inputs)
            elif action=='run':
                if a['paused'] or a['killed']:
                    raise engine.TradingError('Strategi dijeda atau kill switch aktif.')
                count=engine.scaled(data.get('steps','10'),1,20)
                if count<1 or a['tick']+count>100000:
                    raise engine.TradingError('Pilih 1–20 candle replay dalam satu run.')
                if recent+count+1>30:
                    raise engine.TradingError('Run melebihi batas 30 keputusan/aksi per menit. Kurangi candle atau tunggu sebentar.')
                # Bounded CPU-only transaction: no scheduler/provider/always-on worker.
                records=[]
                inputs['run_records']=records
                for _ in range(count):
                    advance=_advance(conn,user,account(conn,user))
                    current=account(conn,user)
                    evidence={'source':engine.SOURCE,'source_time':advance['next_candle']['source_time'],
                              'generated_at':current['generated_at'],'tick':current['tick'],'replay':advance}
                    candle_key='agent-candle-'+str(current['tick'])
                    prior=query(conn,'SELECT outcome,message FROM kilas_trading_events WHERE user_id=? AND operation_key=?',(user,candle_key),one=True)
                    if prior:
                        evidence['previous_decision']=prior
                        result,msg='SKIPPED','Candle ini sudah dievaluasi.'
                    else:
                        try:result,msg=_evaluate(conn,user,current,evidence)
                        except engine.TradingError as exc:result,msg='REJECTED',str(exc)
                        query(conn,'INSERT INTO kilas_trading_events(user_id,operation_key,fingerprint,action,outcome,message,inputs_json,created_at) VALUES (?,?,?,?,?,?,?,?)',
                              (user,candle_key,hashlib.sha256(('run:'+key).encode()).hexdigest(),'agent',result,msg,json.dumps(evidence),stamp()))
                    records.append({'tick':current['tick'],'outcome':result,'message':msg,'replay':advance})
                inputs['run_records']=records
                message=f'Run paper selesai: {count} candle. Keputusan dan perubahan SL/TP tercatat. Tidak ada worker yang terus berjalan.'
        except engine.TradingError as exc:
            # Validation occurs before each action's writes. Retain the rejected decision too.
            outcome, message = 'REJECTED', str(exc)
        status = 'ERROR' if outcome == 'REJECTED' else 'IDLE'
        query(conn, 'UPDATE kilas_trading_accounts SET status=?,last_error=?,updated_at=? WHERE user_id=?', (status, message if outcome == 'REJECTED' else '', stamp(), user))
        query(conn, 'INSERT INTO kilas_trading_events(user_id,operation_key,fingerprint,action,outcome,message,inputs_json,created_at) VALUES (?,?,?,?,?,?,?,?)', (user, key, fingerprint, action, outcome, message, json.dumps(inputs), stamp()))
        return {'outcome': outcome, 'message': message, 'duplicate': False}
