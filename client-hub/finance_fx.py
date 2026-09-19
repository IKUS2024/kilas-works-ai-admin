"""Reference FX estimates; never an executable buy/sell quote."""
from datetime import datetime,timezone
from decimal import Decimal,ROUND_HALF_UP
import threading,time,requests
SUPPORTED=('IDR','USD','SGD','MYR','EUR','GBP','AUD','JPY','CNY','HKD','THB')
_TTL=3600
_cache=None
_lock=threading.Lock()

def snapshot(currencies):
    wanted=tuple(c for c in SUPPORTED if c in set(currencies or ()))
    if not wanted or wanted==('IDR',):
        return {'rates':{'IDR':1.0},'date':datetime.now(timezone.utc).date().isoformat(),'source':'IDR','stale':False}
    global _cache
    with _lock:
        if _cache and time.time()-_cache['fetched_at']<_TTL:return dict(_cache)
        try:
            response=requests.get('https://api.frankfurter.dev/v1/latest',
                params={'base':'IDR','symbols':','.join(c for c in wanted if c!='IDR')},timeout=(2,4))
            response.raise_for_status();payload=response.json();raw=payload.get('rates') or {};rates={'IDR':1.0}
            for code in wanted:
                if code!='IDR' and code in raw and float(raw[code])>0:rates[code]=1.0/float(raw[code])
            if len(rates)<len(wanted):raise ValueError('missing_rate')
            _cache={'rates':rates,'date':str(payload.get('date') or ''),'source':'Frankfurter','stale':False,'fetched_at':time.time()}
            return dict(_cache)
        except Exception:
            if _cache:
                result=dict(_cache);result['stale']=True;return result
            return {'rates':{'IDR':1.0},'date':'','source':'unavailable','stale':True}

def to_idr(amount_minor,currency,fx):
    if currency=='IDR':return int(amount_minor)
    rate=(fx or {}).get('rates',{}).get(currency)
    if not rate:return None
    major=Decimal(amount_minor)/(Decimal(1) if currency=='JPY' else Decimal(100))
    return int((major*Decimal(str(rate))).quantize(Decimal('1'),rounding=ROUND_HALF_UP))


def minor_scale(currency):
    if currency not in SUPPORTED: raise ValueError('unsupported_currency')
    return Decimal(1) if currency in ('IDR','JPY') else Decimal(100)

def major(amount_minor,currency):
    return Decimal(int(amount_minor))/minor_scale(currency)

def reference_pair(from_currency,to_currency,fx):
    if from_currency not in SUPPORTED or to_currency not in SUPPORTED or from_currency==to_currency:return None
    rates=(fx or {}).get('rates',{})
    a=rates.get(from_currency);b=rates.get(to_currency)
    if not a or not b:return None
    return Decimal(str(a))/Decimal(str(b))

def format_money(amount_minor,currency):
    symbols={'IDR':'Rp','USD':'US$','SGD':'S$','MYR':'RM','EUR':'€','GBP':'£','AUD':'A$','JPY':'¥','CNY':'CN¥','HKD':'HK$','THB':'฿'}
    if currency not in SUPPORTED:raise ValueError('unsupported_currency')
    value=major(amount_minor,currency);sign='-' if value<0 else '';value=abs(value)
    if currency in ('IDR','JPY'):text=f"{int(value):,}";text=text.replace(',','.') if currency=='IDR' else text
    else:text=f"{value:,.2f}"
    return sign+symbols[currency]+text
