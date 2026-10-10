"""Manual proposal-only analyst. Production has no data source and inference defaults off."""
import hashlib
import json
import os
import time
from datetime import datetime, timezone
import requests
from flask import current_app, has_app_context
from . import analysis_budget as budget, store, engine

# Server-injected adapter only. No client snapshot upload, scheduled runs or broker connection.
market_source = None
MODEL_URL='https://api.openai.com/v1/models/'+budget.MODEL
RESPONSE_URL='https://api.openai.com/v1/responses'
MAX_REPLY_BYTES=65536
SYSTEM=('Analyze ONLY the supplied XAUUSD market snapshot. Return a selective BUY/SELL/WAIT proposal '
        'with grounded reasons and invalidation. WAIT when evidence is insufficient. You have no broker, '
        'account, balance or order tools. Never claim an order ran, live profitability or guaranteed returns. '
        'TEST_FIXTURE inputs are synthetic test evidence, not real market analysis. Prices are integer USD cents per ounce.')
SCHEMA={'type':'object','additionalProperties':False,
        'properties':{'decision':{'type':'string','enum':['BUY','SELL','WAIT']},
                      'reason':{'type':'string','maxLength':400},'invalidation':{'type':'string','maxLength':240},
                      'stop_cents':{'type':['integer','null']},'target_cents':{'type':['integer','null']}},
        'required':['decision','reason','invalidation','stop_cents','target_cents']}


class Unavailable(budget.GuardError):
    pass


def enabled():
    return os.environ.get('KILAS_TRADING_AI_ENABLED','').lower()=='true'


def availability():
    reason=''
    if market_source is None:reason='Feed demo read-only belum tersedia. Replay MOCK tidak dikirim ke AI.'
    elif not enabled():reason='Inference belum diaktifkan; izin sumber data/setup masih diperlukan.'
    elif not os.environ.get('OPENAI_API_KEY','').strip():reason='Credential model aplikasi tidak tersedia.'
    else:
        try:budget.policy()
        except budget.GuardError as exc:reason=str(exc)
    return {'outcome':'UNAVAILABLE' if reason else 'READY','message':reason or 'Analisis manual; proposal saja, tanpa order.',
            'model':budget.MODEL,'reasoning':budget.EFFORT,'monthly_usd':'5.00','daily_usd':'0.25','max_daily_requests':10}


def _date(value):
    if not isinstance(value,str) or len(value)>40:raise Unavailable('Timestamp sumber tidak valid.')
    try:
        date=datetime.fromisoformat(value.replace('Z','+00:00'))
        if date.tzinfo is None:raise ValueError()
        return date
    except ValueError:raise Unavailable('Timestamp sumber harus UTC/timezone yang valid.') from None


def validate_snapshot(raw):
    fields={'connected','kind','provider','symbol','timeframe','captured_at','quote_time','bid_cents','ask_cents','candles'}
    if not isinstance(raw,dict) or set(raw)!=fields:
        raise Unavailable('Snapshot harus market-only; account/balance/credential atau field lain ditolak.')
    if raw['connected'] is not True:raise Unavailable('Sumber disconnected; tidak memanggil AI.')
    fixture=raw['kind']=='TEST_FIXTURE'
    if raw['kind']!='DEMO' and not (fixture and has_app_context() and current_app.testing):
        raise Unavailable('Hanya sumber DEMO disetujui; fixture tidak boleh dipakai di produksi.')
    if raw['symbol']!='XAUUSD' or raw['timeframe'] not in ('M1','M5','M15'):
        raise Unavailable('Simbol/timeframe belum didukung. Mapping broker harus ditinjau.')
    provider=raw['provider']
    import re
    if not isinstance(provider,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}',provider):
        raise Unavailable('Identitas sumber belum valid.')
    for k in ('captured_at','quote_time'):
        age=(store.now()-_date(raw[k])).total_seconds()
        if not 0<=age<=120:raise Unavailable('Snapshot/quote stale atau koneksi belum valid. Tidak memanggil AI.')
    bid,ask=raw['bid_cents'],raw['ask_cents']
    if any(type(x)!=int or not 0<x<=100000000 for x in (bid,ask)) or ask<bid or (ask-bid)*10000>20*((ask+bid)//2):
        raise Unavailable('Harga/spread sumber tidak memenuhi batas deterministik.')
    bars=raw['candles'];interval={'M1':60,'M5':300,'M15':900}[raw['timeframe']]
    if not isinstance(bars,list) or not 12<=len(bars)<=48:
        raise Unavailable('Perlu 12–48 closed candle; tidak ada candle yang diinventasikan.')
    last=None
    for bar in bars:
        if not isinstance(bar,dict) or set(bar)!={'time','open','high','low','close'}:
            raise Unavailable('Field candle tidak valid.')
        t=_date(bar['time'])
        prices=[bar[k] for k in ('open','high','low','close')]
        if any(type(x)!=int or not 0<x<=100000000 for x in prices) or bar['low']>min(prices) or bar['high']<max(prices):
            raise Unavailable('Nilai OHLC tidak valid.')
        if last is not None and (t-last).total_seconds()!=interval:
            raise Unavailable('Urutan/jarak closed candle tidak valid.')
        last=t
    # `time` is the bar CLOSE time, normalized by the eventual trusted connector.
    age=(_date(raw['quote_time'])-last).total_seconds()
    if not 0<=age<interval+5:raise Unavailable('Candle terakhir belum selaras dengan quote terbaru.')
    encoded=json.dumps(raw,sort_keys=True,allow_nan=False)
    if len(encoded.encode())>10000:raise Unavailable('Snapshot terlalu besar.')
    normalized=json.loads(encoded)
    for field in ('captured_at','quote_time'):normalized[field]=_date(normalized[field]).astimezone(timezone.utc).isoformat()
    for bar in normalized['candles']:bar['time']=_date(bar['time']).astimezone(timezone.utc).isoformat()
    return normalized


def _body(snapshot):
    body={'model':budget.MODEL,'reasoning':{'effort':budget.EFFORT},'service_tier':'default',
          'instructions':SYSTEM,'input':[{'role':'user','content':json.dumps(snapshot,sort_keys=True)}],
          'max_output_tokens':budget.OUTPUT_BOUND,'store':False,'tools':[],
          'text':{'format':{'type':'json_schema','name':'trading_market_proposal','strict':True,'schema':SCHEMA}}}
    # Byte-level upper bound includes every serialized field/schema, plus 2048 framing tokens.
    # At least one UTF-8 byte per text token; reject before reservation/network if bound is exceeded.
    size=len(json.dumps(body,ensure_ascii=True,allow_nan=False).encode())
    if size>budget.BODY_BYTE_LIMIT or size+2048>budget.INPUT_BOUND:
        raise Unavailable('Batas input konservatif terlampaui; tidak memanggil model.')
    return body


def _read(response):
    response.raise_for_status()
    # Redirects are disabled by caller; 3xx is not a successful protocol response.
    if response.status_code!=200:raise Unavailable('Provider tidak tersedia.')
    chunks=[];size=0;started=time.monotonic()
    for part in response.iter_content(4096):
        size+=len(part)
        if size>MAX_REPLY_BYTES or time.monotonic()-started>60:
            raise Unavailable('Batas respons provider terlampaui.')
        chunks.append(part)
    return json.loads(b''.join(chunks),parse_constant=lambda value:(_ for _ in ()).throw(ValueError('nonfinite')))


def _http(method,url,key,body=None,*,status_sink=None,timeout=(5,45)):
    # No new credential, configurable destination, retries, fallback model or provider tools.
    with requests.request(method,url,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},
                          json=body,timeout=timeout,allow_redirects=False,stream=True) as response:
        if status_sink is not None:status_sink(response.status_code)
        return _read(response)


def _decision(payload,snapshot):
    output=payload.get('output')
    if not isinstance(output,list) or any(not isinstance(b,dict) or b.get('type') not in ('message','reasoning') for b in output):
        raise ValueError('invalid_output')
    messages=[b for b in output if b.get('type')=='message']
    if len(messages)!=1:raise ValueError('missing_message')
    content=messages[0].get('content',[])
    if not isinstance(content,list) or len(content)!=1 or not isinstance(content[0],dict) or content[0].get('type')!='output_text':raise ValueError('invalid_content')
    data=json.loads(content[0]['text'],parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite')))
    if not isinstance(data,dict) or set(data)!=set(SCHEMA['required']):raise ValueError('invalid_schema')
    side=data['decision']
    if side not in ('BUY','SELL','WAIT'):raise ValueError('invalid_side')
    if not isinstance(data['reason'],str) or not 1<=len(data['reason'])<=400 or not isinstance(data['invalidation'],str) or len(data['invalidation'])>240:
        raise ValueError('invalid_explanation')
    stop,target=data['stop_cents'],data['target_cents']
    if side=='WAIT':
        if stop is not None or target is not None:raise ValueError('wait_cannot_order')
    else:
        price=snapshot['ask_cents'] if side=='BUY' else snapshot['bid_cents'];sign=1 if side=='BUY' else -1
        if any(type(x)!=int or x<=0 or x>100000000 for x in (stop,target)) or sign*(price-stop)<=0 or sign*(target-price)<=0 or abs(price-stop)*100>price*5:
            raise ValueError('invalid_protection')
    return data


def analyze(user,request):
    allowed={'operation_key','csrf_token','tick','instrument'}
    if not isinstance(request,dict) or not set(request)<=allowed:
        raise Unavailable('Client tidak boleh memasok snapshot/account atau prompt model.')
    key=budget.request_key(request.get('operation_key'))
    # Authorization and durable retry lookup happen before source/credential access.
    prior=budget.previous(user,key)
    if prior:return prior
    state=availability()
    if state['outcome']!='READY':return dict(state,proposal_only=True)
    try:snapshot=validate_snapshot(market_source.snapshot(user))
    except (requests.RequestException,OSError,engine.TradingError,ValueError,TypeError,KeyError):
        return {'outcome':'UNAVAILABLE','message':'Sumber market tidak tersedia/valid; tidak ada model/order yang dijalankan.','proposal_only':True}
    body=_body(snapshot)
    identity=[snapshot['kind'],snapshot['provider'],snapshot['symbol'],snapshot['timeframe'],snapshot['candles'][-1]['time'],budget.MODEL,budget.EFFORT,'market-proposal-v1']
    fingerprint=hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    meta={'snapshot_hash':hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode()).hexdigest(),
          'source_kind':snapshot['kind'],'provider':snapshot['provider'],'symbol':'XAUUSD',
          'timeframe':snapshot['timeframe'],'quote_time':snapshot['quote_time'],
          'last_candle':snapshot['candles'][-1]['time'],'market_snapshot':snapshot,
          'prompt_version':'market-proposal-v1','input_bytes':len(json.dumps(body,ensure_ascii=True).encode())}
    prior,card=budget.reserve(user,key,fingerprint,meta)
    if prior:return prior
    credential=os.environ.get('OPENAI_API_KEY','').strip()
    # Non-inference project-model preflight, before any billable POST.
    try:
        catalog=_http('GET',MODEL_URL,credential)
        if not isinstance(catalog,dict) or catalog.get('id')!=budget.MODEL:raise ValueError('model_unavailable')
        validate_snapshot(snapshot);budget.policy()
        with store.locked(user) as conn:
            a=store.account(conn,user)
            if a['paused'] or a['killed'] or not enabled():raise ValueError('disabled')
    except (requests.RequestException,engine.TradingError,ValueError,TypeError,KeyError):
        return budget.finish(user,key,outcome='UNAVAILABLE',message='Model/feed/preflight belum valid; tidak ada inference.',not_sent=True)
    try:
        payload=_http('POST',RESPONSE_URL,credential,body)
    except (requests.RequestException,engine.TradingError,ValueError,TypeError,KeyError):
        return budget.finish(user,key,outcome='ERROR',message='Hasil provider tidak pasti. Reservasi maksimum ditahan; tidak ada retry/order.')
    if not isinstance(payload,dict):
        return budget.finish(user,key,outcome='ERROR',message='Respons provider tidak valid; reservasi ditahan.')
    invariant=(payload.get('model')==budget.MODEL and payload.get('service_tier')=='default')
    usage=payload.get('usage')
    try:
        if not invariant or payload.get('status')!='completed':raise ValueError('incomplete')
        decision=_decision(payload,snapshot)
        validate_snapshot(snapshot);budget.policy()
        with store.locked(user) as conn:
            account=store.account(conn,user)
            if account['paused'] or account['killed'] or not enabled():raise ValueError('paused')
        outcome='WAIT' if decision['decision']=='WAIT' else 'OK'
        message='Proposal '+decision['decision']+' dari model; tidak ada order. '+('Input TEST_FIXTURE, bukan market nyata.' if snapshot['kind']=='TEST_FIXTURE' else 'Data DEMO; eksekusi tetap paper-only dan belum dihubungkan.')
    except (engine.TradingError,ValueError,TypeError,KeyError):
        decision=None;outcome='WAIT';message='Proposal tidak memenuhi schema/proteksi/freshness atau analisis dijeda. Tidak ada order.'
    return budget.finish(user,key,outcome=outcome,message=message,decision=decision,usage=usage,invariant_ok=invariant)
