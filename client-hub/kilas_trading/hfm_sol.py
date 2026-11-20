"""Owner-paired MT5 market analysis. Broker execution remains local to the EA."""
import hashlib
import json
import math
import os
import re
import secrets
import time

from flask import Response, request
import db
from . import access
from .analysis import _http
from .routes import bp

MODEL = 'gpt-6.2-sol'
MAX_CALLS = 48
SYMBOL = 'XAUUSDc'
SERVER = 'HFMarketsGlobal-Live12'
FRAMES = ('M5', 'M15', 'H1', 'H4')
SYSTEM = (
    "You review a rule-based spot gold trade candidate. Each timeframe contains six closed "
    "OHLC candles in chronological order. Check direction, trend versus rejection, volatility, "
    "spread, stop and target. Recommend BUY or SELL only if the proposed side and levels fit "
    "the evidence. Otherwise return WAIT. Do not invent news, quotes, statistics or fills."
)


def digest(token):
    return hashlib.sha256(token.encode('ascii')).hexdigest()


def issue(user, login):
    if not re.fullmatch(r'[1-9][0-9]{1,15}', login):
        raise ValueError('Invalid MT5 login')
    token = secrets.token_hex(32)
    # Rotating a device never resets its API quota.
    db.execute("""INSERT INTO hfm_sol_devices(user_id,token_hash,login,expires)
        VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET token_hash=excluded.token_hash,
        login=excluded.login,expires=excluded.expires""",
        (user, digest(token), login, int(time.time()) + 30*86400)).close()
    return token


def device(token_hash):
    if not access.enabled():
        return None
    return db.query_one("""SELECT d.* FROM hfm_sol_devices d JOIN users u ON u.id=d.user_id
        LEFT JOIN customer_auth_account_state a ON a.user_id=u.id
        WHERE d.token_hash=? AND d.expires>? AND lower(u.email)=? AND COALESCE(a.disabled,0)=0
        AND EXISTS (SELECT 1 FROM oauth_identities o WHERE o.user_id=u.id
        AND o.provider='google' AND lower(o.email_at_link)=?)""",
        (token_hash, int(time.time()), access.PILOT_EMAIL, access.PILOT_EMAIL))


def valid_price(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 < value < 1000000


def valid(data, login, now):
    if type(data) is not dict or set(data) != {'login','server','symbol','at','bar','side','bid','ask','sl','tp','frames'}:
        return False
    if (data['login'] != login or data['server'] != SERVER or data['symbol'] != SYMBOL
            or type(data['at']) is not int or not now-25 <= data['at'] <= now+5
            or type(data['bar']) is not int or not 0 < data['bar'] <= 4294967295
            or data['side'] not in ('BUY','SELL')):
        return False
    bid,ask,sl,tp = (data[k] for k in ('bid','ask','sl','tp'))
    if not all(valid_price(x) for x in (bid,ask,sl,tp)) or not 0 <= ask-bid <= .700001:
        return False
    if not (sl < bid <= ask < tp if data['side']=='BUY' else tp < bid <= ask < sl):
        return False
    frames = data['frames']
    if type(frames) is not dict or set(frames) != set(FRAMES):
        return False
    for candles in frames.values():
        if type(candles) is not list or len(candles) != 6:
            return False
        for candle in candles:
            if type(candle) is not list or len(candle)!=4 or not all(valid_price(x) for x in candle):
                return False
            o,h,l,c = candle
            if not l <= min(o,c) <= max(o,c) <= h:
                return False
    return True


def analyze(data, credential):
    market = {k:data[k] for k in ('symbol','side','bid','ask','sl','tp','frames')}
    schema = {'type':'object','properties':{'decision':{'type':'string','enum':['BUY','SELL','WAIT']}},
              'required':['decision'],'additionalProperties':False}
    payload = _http('POST','https://api.openai.com/v1/responses',credential,{
        'model':MODEL,'store':False,'instructions':SYSTEM,'input':json.dumps(market,separators=(',',':')),
        'reasoning':{'effort':'low'},'max_output_tokens':256,
        'text':{'format':{'type':'json_schema','name':'hfm_entry','strict':True,'schema':schema}}
    },timeout=(3,10))
    if payload.get('status') != 'completed' or not re.fullmatch(r'gpt-6\.2-sol(?:-\d{4}-\d{2}-\d{2})?',str(payload.get('model',''))):
        return 'WAIT'
    messages = [x for x in payload.get('output',[]) if x.get('type')=='message']
    if len(messages)!=1:
        return 'WAIT'
    content = messages[0].get('content',[])
    if len(content)!=1 or content[0].get('type')!='output_text':
        return 'WAIT'
    decision=json.loads(content[0]['text'])
    return data['side'] if decision=={'decision':data['side']} else 'WAIT'


def reply(value, status=200):
    return Response(value,status=status,mimetype='text/plain',headers={'Cache-Control':'no-store'})


@bp.record_once
def register(state):
    # Only the bearer endpoint has machine authentication. The host guard runs first.
    state.app.before_request_funcs.setdefault(None,[]).insert(0,transport)


def transport():
    if request.endpoint != 'kilas_trading.hfm_signal':
        return None
    auth=request.headers.get('Authorization','')
    if (request.method!='POST' or request.cookies or request.args or
            not re.fullmatch(r'Bearer [a-f0-9]{64}',auth)):
        return reply('WAIT',401)
    if not request.is_json or not request.content_length or request.content_length>6144:
        return reply('WAIT',400)
    try:
        token_hash=digest(auth[7:])
        record=device(token_hash)
        if not record:
            return reply('WAIT',403)
        now=int(time.time())
        data=request.get_json(silent=True)
        if not valid(data,record['login'],now):
            return reply('WAIT',400)
        key=os.environ.get('OPENAI_API_KEY','').strip()
        if not key:
            return reply('WAIT',503)
        day,slot=now//86400,now//300
        # Committed before inference, including on timeout, across processes and restarts.
        cursor=db.execute("""UPDATE hfm_sol_devices SET last_slot=?,quota_day=?,
            calls=CASE WHEN quota_day=? THEN calls+1 ELSE 1 END
            WHERE token_hash=? AND expires>? AND last_slot<? AND (quota_day<>? OR calls<?)""",
            (slot,day,day,token_hash,now,slot,day,MAX_CALLS))
        reserved=cursor.rowcount==1
        cursor.close()
        if not reserved:
            return reply('WAIT',429)
        decision=analyze(data,key)
        if int(time.time())-data['at']>25 or not device(token_hash):
            decision='WAIT'
        return reply(f"K1|{data['bar']}|{decision}")
    except Exception:
        return reply('WAIT',503)


@bp.post('/robot-hfm/signal')
def hfm_signal():
    return reply('WAIT',403)
