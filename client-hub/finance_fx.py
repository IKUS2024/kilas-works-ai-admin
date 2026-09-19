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
