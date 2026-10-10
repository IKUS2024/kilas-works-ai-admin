"""Manual MT5 DEMO outbound collector. No orders, account export or persistent token."""
import argparse
from datetime import datetime, timezone
import getpass
import json
import ntpath
import os
from pathlib import Path
import re
import time
import urllib.request
import urllib.error

BASE = 'https://trading.kilasworks.id/products/services/trading/bridge'
SERVER = 'XMGlobal-MT5 10'
FLAGS = ('runtime_eligible','broker_execution_allowed','ai_analysis','paper_execution')
MAX_BYTES = 16384
INITIALIZE_TIMEOUT_MS = 5000

class CollectorError(ValueError): pass

def require(ok, message='Read-only DEMO bridge unavailable; stop and inspect locally.'):
    if not ok: raise CollectorError(message)

def windows_path(value):
    """Explicit local absolute paths only; no expansion, discovery or aliases."""
    require(type(value) is str and 0 < len(value) <= 512)
    drive, tail = ntpath.splitdrive(value)
    require(bool(re.fullmatch(r'[A-Za-z]:',drive)) and tail.startswith(('\\','/')))
    require(not any(ord(c)<32 or c in ':*?"<>|' for c in tail))
    parts = tail.replace('/','\\').split('\\')[1:]
    require(all(p not in ('.','..') and not p.endswith((' ','.')) for p in parts if p))
    return ntpath.normcase(ntpath.normpath(value))

def binding_paths(terminal_path, data_path):
    executable, data = windows_path(terminal_path), windows_path(data_path)
    require(ntpath.basename(executable) in ('terminal.exe','terminal64.exe','metatrader.exe','metatrader64.exe'))
    return executable, data

def initialize_terminal(sdk, symbol, terminal_path, data_path):
    require(symbol in ('GOLD','BTCUSD'))
    executable, data = binding_paths(terminal_path,data_path)
    # No automatic terminal discovery, login/password/server or portable override.
    require(sdk.initialize(terminal_path,timeout=INITIALIZE_TIMEOUT_MS) is True,
            'Pinned terminal initialization failed or timed out; stopped without retry.')
    reader = ReadOnlyMT5(sdk, symbol, executable, data)
    reader.verify()
    return reader
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
    def __init__(self,sdk,symbol,terminal_path,data_path):
        require(symbol in ('GOLD','BTCUSD'))
        self.executable,self.data_path=binding_paths(terminal_path,data_path)
        self.sdk,self.symbol,self.identity,self.terminal_identity=sdk,symbol,None,None
    def verify_terminal(self):
        terminal=self.sdk.terminal_info()
        require(terminal is not None and terminal.connected is True)
        require(terminal.tradeapi_disabled is True,
                'External Python trading is not disabled; owner-approved terminal setting review required.')
        installation = windows_path(terminal.path)
        data = windows_path(terminal.data_path)
        common = windows_path(terminal.commondata_path)
        require(installation==ntpath.dirname(self.executable) and data==self.data_path,
                'Terminal installation/data path mismatch; stopped without discovery or switching.')
        require(type(terminal.build) is int and terminal.build>0)
        require(all(type(v) is str and 0<len(v)<=128 for v in (terminal.name,terminal.company)))
        identity=(installation,data,common,terminal.build,terminal.name,terminal.company)
        require(self.terminal_identity is None or self.terminal_identity==identity,
                'Terminal identity changed during read-only access; stopped.')
        self.terminal_identity=identity # process memory only; no path/identity export
    def verify(self):
        self.verify_terminal()
        account=self.sdk.account_info()
        self.verify_terminal()
        require(account is not None and type(account.trade_mode) is int and account.trade_mode==0 and account.server==SERVER)
        identity=(account.login,account.server)
        require(self.identity is None or self.identity==identity)
        self.identity=identity # in-process binding only; never serialized
        specs=self.sdk.symbol_info(self.symbol)
        require(specs is not None and specs.name==self.symbol and specs.visible is True)
        self.verify_terminal()
    def sample(self):
        start,sm=utc(),time.monotonic_ns()
        self.verify()
        tick=self.sdk.symbol_info_tick(self.symbol)
        self.verify_terminal()
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
    parser.add_argument('--terminal-path',help='Approved absolute Windows terminal EXE path; required with --connect.')
    parser.add_argument('--terminal-data-path',help='Approved absolute Windows terminal data directory; required with --connect.')
    args=parser.parse_args()
    if not args.connect:
        print('No connection started. Runtime pairing/MT5 access requires explicit action-time approval.');return 0
    sdk=None;session=None
    try:
        require(1<=args.minutes<=60)
        binding_paths(args.terminal_path,args.terminal_data_path)
        require(os.name=='nt' and Path(args.terminal_path).is_file() and Path(args.terminal_data_path).is_dir(),
                'Approved Windows terminal executable/data directory unavailable; no SDK initialization attempted.')
        import MetaTrader5 as sdk
        reader=initialize_terminal(sdk,args.symbol,args.terminal_path,args.terminal_data_path)
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
    except CollectorError as exc:
        print(str(exc));return 2 # only fixed local messages; no SDK exception/paths
    except (KeyboardInterrupt,Exception):
        print('Collector stopped. No automatic retry, credentials printed, or orders sent.');return 2
    finally:
        if session is not None: session.clear()
        if sdk is not None:
            try: sdk.shutdown()
            except Exception: print('SDK shutdown could not be confirmed; inspect terminal locally.')

if __name__=='__main__': raise SystemExit(main())
