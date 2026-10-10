"""Manual MT5 DEMO outbound collector. No orders, account export or persistent token."""
import argparse
from datetime import datetime, timezone
import getpass
import json
import re
import time
import urllib.request
import urllib.error

BASE = 'https://trading.kilasworks.id/products/services/trading/bridge'
SERVER = 'XMGlobal-MT5 10'
FLAGS = ('runtime_eligible','broker_execution_allowed','ai_analysis','paper_execution')
MAX_BYTES = 16384

class CollectorError(ValueError): pass

def require(ok):
    if not ok: raise CollectorError('Read-only DEMO bridge unavailable; stop and inspect locally.')
def utc(): return datetime.now(timezone.utc).isoformat()
def number(value):
    # SDK numeric fields only; no arbitrary strings or exception contents.
    result = format(float(value), '.8f').rstrip('0').rstrip('.')
    require(bool(re.fullmatch(r'\d{1,9}(?:\.\d{1,8})?',result)) and float(result)>0)
    return result

class Transport:
    def __init__(self):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs): return None
        # No browser cookies, proxy credential extraction, redirects or custom URL.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def post(self,path,data,token=None):
        require(path in ('exchange','telemetry'))
        raw = json.dumps(data,allow_nan=False,separators=(',',':')).encode('utf-8')
        require(len(raw)<=MAX_BYTES)
        headers={'Content-Type':'application/json','Accept':'application/json'}
        if token is not None: headers['Authorization']='Bearer '+token
        request=urllib.request.Request(BASE+'/'+path,data=raw,headers=headers,method='POST')
        try:
            with self.opener.open(request,timeout=5) as response:
                require(response.status==200 and response.headers.get_content_type()=='application/json')
                body=response.read(MAX_BYTES+1);require(len(body)<=MAX_BYTES)
            result=json.loads(body)
            require(type(result) is dict)
            return result
        except (OSError, ValueError, urllib.error.URLError):
            raise CollectorError('Transport failed; no automatic retry. Re-pair after inspection.') from None

class ReadOnlyMT5:
    def __init__(self,sdk,symbol):
        require(symbol in ('GOLD','BTCUSD'))
        self.sdk,self.symbol,self.identity=sdk,symbol,None
    def verify(self):
        terminal=self.sdk.terminal_info();account=self.sdk.account_info()
        require(terminal is not None and terminal.connected is True and terminal.tradeapi_disabled is True)
        require(account is not None and type(account.trade_mode) is int and account.trade_mode==0 and account.server==SERVER)
        identity=(account.login,account.server)
        require(self.identity is None or self.identity==identity)
        self.identity=identity # in-process binding only; never serialized
        specs=self.sdk.symbol_info(self.symbol)
        require(specs is not None and specs.name==self.symbol and specs.visible is True)
    def sample(self):
        start,sm=utc(),time.monotonic_ns()
        self.verify()
        tick=self.sdk.symbol_info_tick(self.symbol)
        bars=self.sdk.copy_rates_from_pos(self.symbol,self.sdk.TIMEFRAME_M1,0,13)
        self.verify()
        em,end=time.monotonic_ns(),utc()
        require(tick is not None and bars is not None and 0<em-sm<=2000000000)
        closed=[b for b in bars if int(b['time'])+60<=int(tick.time)][-12:]
        require(len(closed)==12)
        return dict(symbol=self.symbol,timeframe='M1',
                    tick=dict(time=int(tick.time),time_msc=int(tick.time_msc),bid=number(tick.bid),ask=number(tick.ask)),
                    capture=dict(start_utc=start,end_utc=end,start_mono_ns=sm,end_mono_ns=em),
                    candles=[dict(time=int(b['time']),**{k:number(b[k]) for k in ('open','high','low','close')}) for b in closed],
                    clock=None,clock_profile=None)

class Session:
    def __init__(self,transport,symbol,pair_code):
        require(symbol in ('GOLD','BTCUSD') and bool(re.fullmatch(r'[0-9a-f]{32}',pair_code)))
        self.transport,self.symbol=transport,symbol
        result=transport.post('exchange',dict(pair_code=pair_code,symbol=symbol,server=SERVER))
        require(result.get('symbol')==symbol and result.get('server')==SERVER)
        self.token=result.get('token');self.challenge=result.get('challenge');self.sequence=result.get('sequence')
        require(type(self.token) is str and re.fullmatch(r'[0-9a-f]{64}',self.token))
        require(type(self.challenge) is str and re.fullmatch(r'[0-9a-f]{64}',self.challenge) and self.sequence==0)
        self.expires_at=result.get('expires_at')
    def send(self,market=None):
        data=dict(schema_version=1,sequence=self.sequence+1,server_challenge=self.challenge,
                  message_kind='MARKET' if market is not None else 'HEARTBEAT',server=SERVER,
                  account_mode='DEMO' if market is not None else 'UNKNOWN',terminal_connected=market is not None,
                  market=market,**{k:False for k in FLAGS})
        result=self.transport.post('telemetry',data,self.token)
        require(result.get('outcome')=='RECEIVED_READ_ONLY' and result.get('sequence')==self.sequence+1)
        require(all(result.get(k) is False for k in FLAGS))
        challenge=result.get('challenge')
        require(type(challenge) is str and re.fullmatch(r'[0-9a-f]{64}',challenge))
        self.sequence+=1;self.challenge=challenge
    def clear(self):
        self.token=None;self.challenge=None

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol',choices=('GOLD','BTCUSD'),required=True)
    parser.add_argument('--connect',action='store_true',help='Explicitly approved manual connection only; no service installation.')
    parser.add_argument('--minutes',type=int,default=5,help='Bounded foreground run, 1–60 minutes.')
    args=parser.parse_args()
    if not args.connect:
        print('No connection started. Runtime pairing/MT5 access requires explicit action-time approval.');return 0
    require(1<=args.minutes<=60)
    sdk=None;session=None
    try:
        import MetaTrader5 as sdk
        require(sdk.initialize()) # existing terminal only; no login/password arguments
        reader=ReadOnlyMT5(sdk,args.symbol);reader.verify()
        code=getpass.getpass('One-use Trading pairing code (not stored): ')
        session=Session(Transport(),args.symbol,code);code=None
        deadline=time.monotonic()+args.minutes*60
        print('Read-only telemetry started. Market clock/profile unverified; all execution blocked. Ctrl+C stops.')
        while time.monotonic()<deadline:
            try: market=reader.sample()
            except Exception:
                session.send(None);raise CollectorError('Terminal read failed; stopped without retry.') from None
            session.send(market)
            time.sleep(2)
        return 0
    except (KeyboardInterrupt,Exception):
        print('Collector stopped. No automatic retry, credentials printed, or orders sent.');return 2
    finally:
        if session is not None: session.clear()
        if sdk is not None:
            try: sdk.shutdown()
            except Exception: print('SDK shutdown could not be confirmed; inspect terminal locally.')

if __name__=='__main__': raise SystemExit(main())
