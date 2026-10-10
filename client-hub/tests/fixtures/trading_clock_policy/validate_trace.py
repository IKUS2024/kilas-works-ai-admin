"""Offline standalone copy of cb288c6 clock/profile source policy; no network or execution."""
from datetime import datetime,timezone
class TradingError(ValueError): pass


def utc(value):
    try:
        if not isinstance(value, str) or len(value) > 40: raise ValueError()
        at = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if at.tzinfo is None or at.utcoffset().total_seconds() != 0: raise ValueError()
        return at
    except (ValueError, TypeError): raise TradingError('Explicit UTC required.') from None

"""Explicit, reviewed broker-clock profiles only. No active profile, inference or source promotion."""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

APIS=('symbol_info_tick','copy_rates_from_pos')
SERVERS=('XMGlobal-MT5','XMGlobal-MT5 10')

@dataclass(frozen=True)
class OffsetWindow:
    start_utc: str
    end_utc: str
    offset_seconds: int

@dataclass(frozen=True)
class BrokerTimeProfile:
    profile_id: str
    server: str
    apis: tuple
    windows: tuple
    evidence_ref: str
    approval_ref: str
    approved: bool = False

    def validated_windows(self):
        # Approval fields are trusted server-owned configuration, never upload/model fields.
        if self.approved is not True or self.server not in SERVERS:
            raise TradingError('Explicit approved XMGlobal-MT5 time profile required.')
        if any(not isinstance(v,str) or not 1<=len(v)<=200 or not v.isprintable()
               for v in (self.profile_id,self.evidence_ref,self.approval_ref)):
            raise TradingError('Bounded approval/provenance references required.')
        if (type(self.apis)!=tuple or not self.apis or len(self.apis)>2
            or any(api not in APIS for api in self.apis) or len(set(self.apis))!=len(self.apis)
            or type(self.windows)!=tuple or not 1<=len(self.windows)<=16):
            raise TradingError('Explicit bounded API/window scope required.')
        result=[]
        for window in self.windows:
            if type(window) is not OffsetWindow or type(window.offset_seconds)!=int or window.offset_seconds not in (7200,10800):
                raise TradingError('Explicit reported GMT+2/+3 window only; no guessed rule.')
            start,end=utc(window.start_utc),utc(window.end_utc)
            if start>=end: raise TradingError('Nonempty half-open UTC validity window required.')
            result.append((start,end,window.offset_seconds))
        result.sort()
        if any(left[1]>right[0] for left,right in zip(result,result[1:])):
            raise TradingError('Overlapping UTC profile windows rejected.')
        return result


def normalize(raw_time,raw_time_msc=None,*,profile,server,api):
    if type(profile) is not BrokerTimeProfile: raise TradingError('No approved broker time profile configured.')
    windows=profile.validated_windows()
    if server!=profile.server or api not in profile.apis: raise TradingError('Profile server/API scope mismatch.')
    if type(raw_time)!=int or not 0<raw_time<10**15:
        raise TradingError('Raw server seconds must be a positive integer.')
    if raw_time_msc is not None and (type(raw_time_msc)!=int or not 0<raw_time_msc<10**15 or raw_time_msc//1000!=raw_time):
        raise TradingError('Raw seconds/milliseconds mismatch.')
    if api=='copy_rates_from_pos' and raw_time_msc is not None: raise TradingError('Candle API has raw seconds only; semantics unverified.')
    try:
        encoded=datetime.fromtimestamp(raw_time,timezone.utc)
        if raw_time_msc is not None: encoded+=timedelta(milliseconds=raw_time_msc%1000)
        candidates=[(encoded-timedelta(seconds=offset),start,end,offset) for start,end,offset in windows
                    if start<=encoded-timedelta(seconds=offset)<end]
    except (ValueError,OverflowError,OSError): raise TradingError('Raw time outside supported datetime range.') from None
    if len(candidates)!=1: raise TradingError('Unknown validity window or ambiguous DST timestamp; normalization blocked.')
    event,start,end,offset=candidates[0]
    return dict(raw_time=raw_time,raw_time_msc=raw_time_msc,server=server,api=api,
                normalized_time_utc=event.isoformat(),applied_offset_seconds=offset,
                profile_id=profile.profile_id,evidence_ref=profile.evidence_ref,approval_ref=profile.approval_ref,
                validity_start_utc=start.isoformat(),validity_end_utc=end.isoformat(),
                source_time_status='profile_normalized_not_verified',freshness='unknown',
                candle_time_semantics='unverified' if api=='copy_rates_from_pos' else None,
                ai_analysis=False,paper_execution=False)

"""Same-cycle operational NTP error model, explicitly unauthenticated and paper-only."""
import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

REFERENCE_HOSTS=('time.windows.com',)
MAX_CYCLE_SECONDS=4
MAX_CONSUMPTION_SECONDS=1
MAX_UNCERTAINTY_SECONDS=Decimal('.750')
LOCAL_PRECISION_SECONDS=Decimal('.050') # Covers sub-threshold wall/monotonic capture discrepancy.
DRIFT_SECONDS_PER_SECOND=Decimal('.001') # Explicit short-cycle assumption, not measured oscillator guarantee.
PACKET_FIELDS={'reference_host','resolved_ips','request_peer','response_peer','request_port','response_port','version','mode','leap','stratum',
               'request_ntp_hex','originate_ntp_hex','transmit_ntp_hex','receive_ntp_hex','reference_ntp_hex','client_send_utc','client_receive_utc',
               'client_send_mono_ns','client_receive_mono_ns','server_receive_utc','server_transmit_utc',
               'reference_utc','root_delay_seconds','root_dispersion_seconds','precision_log2'}


def dec(v):
    try:
        if type(v) not in (str,int) or len(str(v))>32: raise ValueError()
        value=Decimal(v)
        if not value.is_finite(): raise ValueError()
        return value
    except (ValueError,ArithmeticError): raise TradingError('Finite exact clock numeric evidence required.') from None


def mono(v):
    if type(v)!=int or not 0<=v<2**63: raise TradingError('Monotonic nanoseconds required.')
    return v


def seconds(delta): return Decimal(delta.days*86400+delta.seconds)+Decimal(delta.microseconds)/1000000


def stamp_matches(token,wall,tolerance=Decimal('.000001')):
    sec=int(token[:8],16);fraction=Decimal(int(token[8:],16))/2**32
    unix=seconds(wall-utc('1970-01-01T00:00:00Z'))
    era=int(((unix+2208988800-sec)/2**32).to_integral_value(rounding='ROUND_HALF_EVEN'))
    return abs(Decimal(sec+era*2**32-2208988800)+fraction-unix)<=tolerance


def packet(p):
    if not isinstance(p,dict) or set(p)!=PACKET_FIELDS: raise TradingError('Complete NTP packet evidence required; no inferred metadata.')
    if type(p['request_port'])!=int or type(p['response_port'])!=int or p['request_port']!=123 or p['response_port']!=123:
        raise TradingError('NTP request/response endpoint must be UDP123.')
    if p['reference_host'] not in REFERENCE_HOSTS: raise TradingError('Reference is outside paper allowlist.')
    try:
        if not isinstance(p['resolved_ips'],(list,tuple)) or not 1<=len(p['resolved_ips'])<=16: raise ValueError()
        addresses=[str(ipaddress.ip_address(v)) for v in p['resolved_ips']]
        if str(ipaddress.ip_address(p['request_peer'])) not in addresses or p['request_peer']!=p['response_peer']: raise ValueError()
    except (ValueError,TypeError): raise TradingError('Response peer must match captured resolution/request peer.') from None
    if any(type(p[k])!=int for k in ('version','mode','leap','stratum','precision_log2')) or p['version'] not in (3,4) or p['mode']!=4 or p['leap'] not in (0,1,2) or not 1<=p['stratum']<=15:
        raise TradingError('Invalid/unsynchronized NTP header.')
    for key in ('request_ntp_hex','originate_ntp_hex','transmit_ntp_hex','receive_ntp_hex','reference_ntp_hex'):
        if not isinstance(p[key],str) or not re.fullmatch('[0-9a-f]{16}',p[key]) or int(p[key],16)==0: raise TradingError('Nonzero exact NTP timestamp tokens required.')
    if p['originate_ntp_hex']!=p['request_ntp_hex']: raise TradingError('NTP response does not echo this request.')
    t1,t2,t3,t4=[utc(p[k]) for k in ('client_send_utc','server_receive_utc','server_transmit_utc','client_receive_utc')]
    if not stamp_matches(p['request_ntp_hex'],t1,LOCAL_PRECISION_SECONDS): raise TradingError('Request token/time differs from acquisition trace.')
    if not stamp_matches(p['transmit_ntp_hex'],t3) or not stamp_matches(p['receive_ntp_hex'],t2) or not stamp_matches(p['reference_ntp_hex'],utc(p['reference_utc'])):
        raise TradingError('Decoded remote timestamps disagree with packet bytes.')
    m1,m4=mono(p['client_send_mono_ns']),mono(p['client_receive_mono_ns'])
    elapsed=Decimal(m4-m1)/1000000000
    if not 0<elapsed<=Decimal('.600') or abs(seconds(t4-t1)-elapsed)>Decimal('.050'): raise TradingError('RTT too large or wall clock jumped.')
    processing=seconds(t3-t2)
    if processing<0 or processing>elapsed or not 0<=seconds(t3-utc(p['reference_utc']))<=86400: raise TradingError('Invalid remote/reference timestamps.')
    delay=elapsed-processing
    root_delay,dispersion=dec(p['root_delay_seconds']),dec(p['root_dispersion_seconds'])
    if root_delay<0 or dispersion<0 or root_delay/2+dispersion>Decimal('.100') or not -60<=p['precision_log2']<=0: raise TradingError('Reference uncertainty exceeds paper policy.')
    precision=Decimal(2)**p['precision_log2']
    if precision>LOCAL_PRECISION_SECONDS: raise TradingError('Server timestamp precision too coarse.')
    offset=(seconds(t2-t1)+seconds(t3-t4))/2
    error=delay/2+root_delay/2+dispersion+LOCAL_PRECISION_SECONDS+precision
    return dict(offset=offset,error=error,start=m1,end=m4,wall_start=t1,wall_end=t4,transmit=p['transmit_ntp_hex'])

@dataclass(frozen=True)
class SameCycleClock:
    offset_seconds: Decimal
    uncertainty_seconds: Decimal
    expires_mono_ns: int
    evidence_id: str

    def corrected(self,wall): return utc(wall)+timedelta(microseconds=int(self.offset_seconds*1000000))


def qualify_cycle(before,after,*,acquired_start_utc,acquired_end_utc,acquired_start_mono_ns,acquired_end_mono_ns,decision_utc,decision_mono_ns):
    left,right=packet(before),packet(after)
    start,end,decision=mono(acquired_start_mono_ns),mono(acquired_end_mono_ns),mono(decision_mono_ns)
    if before['reference_host']!=after['reference_host'] or left['transmit']==right['transmit'] or before['request_ntp_hex']==after['request_ntp_hex']:
        raise TradingError('Distinct same-reference bracketing replies required; duplicate acknowledgement rejected.')
    if not left['end']<=start<=end<=right['start'] or not right['end']<=decision<=right['end']+MAX_CONSUMPTION_SECONDS*10**9:
        raise TradingError('NTP pair must bracket acquisition; expired/cross-cycle evidence rejected.')
    span=Decimal(right['end']-left['start'])/1000000000
    if span>MAX_CYCLE_SECONDS or Decimal(end-start)/1000000000>2: raise TradingError('Cycle/acquisition exceeds bounded drift interval.')
    marks=[(left['start'],left['wall_start']),(left['end'],left['wall_end']),(start,utc(acquired_start_utc)),(end,utc(acquired_end_utc)),(right['start'],right['wall_start']),(right['end'],right['wall_end']),(decision,utc(decision_utc))]
    anchor_m,anchor_w=marks[0]
    if any(abs(seconds(w-anchor_w)-Decimal(m-anchor_m)/1000000000)>Decimal('.050') for m,w in marks):
        raise TradingError('Cumulative wall/monotonic discrepancy exceeds capture allowance.')
    for (m1,w1),(m2,w2) in zip(marks,marks[1:]):
        if abs(seconds(w2-w1)-Decimal(m2-m1)/1000000000)>Decimal('.050'): raise TradingError('Wall/monotonic step, suspend or reversed wall time.')
    low1,high1=left['offset']-left['error'],left['offset']+left['error']
    low2,high2=right['offset']-right['error'],right['offset']+right['error']
    if max(low1,low2)>min(high1,high2) or abs(left['offset']-right['offset'])>Decimal('.250'): raise TradingError('Clock references disagree; no measured lease.')
    low,high=min(low1,low2),max(high1,high2)
    offset=(low+high)/2
    drift=DRIFT_SECONDS_PER_SECOND*Decimal(right['end']+MAX_CONSUMPTION_SECONDS*10**9-left['start'])/1000000000
    error=(high-low)/2+drift
    if error>MAX_UNCERTAINTY_SECONDS: raise TradingError('Total model uncertainty exceeds 750ms.')
    evidence=hashlib.sha256(json.dumps(dict(before=before,after=after,start=start,end=end),sort_keys=True).encode()).hexdigest()
    return SameCycleClock(offset,error,right['end']+MAX_CONSUMPTION_SECONDS*10**9,evidence)

"""Read-only fixture source contract; proposed thresholds grant no runtime profile/analysis authority."""
from datetime import timedelta

FIXTURE_MAX_AGE_SECONDS=5
FIXTURE_MAX_ACQUISITION_SECONDS=2
FIXTURE_MAX_CLOCK_UNCERTAINTY_MS=250

class ReadOnlyFixtureSource:
    def __init__(self,*,profile,server):
        self.profile=profile;self.server=server;self.connected=False;self.previous=None
        self.floor=None;self.validated=None;self.used_cycles=set();self.clock_deadline=None;self.clock_decision=None

    def connect(self):
        self.connected=True;self.previous=None;self.validated=None;self.clock_deadline=None;self.clock_decision=None
        return {'status':'WAIT','reason':'Connection is not freshness; two advancing observations required.'}

    def disconnect(self):
        self.connected=False;self.previous=None;self.validated=None;self.clock_deadline=None;self.clock_decision=None
        return {'status':'UNAVAILABLE','ai_analysis':False,'paper_execution':False}

    def observe_cycle(self,sample,candle_times,*,before,after,decision_utc,decision_mono_ns):
        self.validated=None;self.clock_deadline=None;self.clock_decision=None
        try:
            if not self.connected: raise TradingError('Disconnected; new same-cycle proof required.')
            if type(self.profile) is not BrokerTimeProfile: raise TradingError('Explicit session profile required.')
            windows=self.profile.validated_windows()
            if self.server!='XMGlobal-MT5 10' or len(windows)!=1 or windows[0][2]!=10800 or (windows[0][1]-windows[0][0]).total_seconds()>1200:
                raise TradingError('One approved server10 +3h session window, at most20minutes, required.')
            mono_fields={'acquired_start_mono_ns','acquired_end_mono_ns'}
            if not isinstance(sample,dict) or set(sample)!={'kind','time','time_msc','acquired_start_utc','acquired_end_utc'}|mono_fields: raise TradingError('Complete same-cycle acquisition evidence required.')
            clock=qualify_cycle(before,after,acquired_start_utc=sample['acquired_start_utc'],acquired_end_utc=sample['acquired_end_utc'],
                                acquired_start_mono_ns=sample['acquired_start_mono_ns'],acquired_end_mono_ns=sample['acquired_end_mono_ns'],decision_utc=decision_utc,decision_mono_ns=decision_mono_ns)
            if not windows[0][0]<=clock.corrected(decision_utc)<windows[0][1]: raise TradingError('Session profile expired/not yet valid.')
            if clock.evidence_id in self.used_cycles: raise TradingError('Clock cycle already consumed; no reference reuse.')
            if len(self.used_cycles)>=64: raise TradingError('Bounded paper clock-cycle limit reached.')
            self.used_cycles.add(clock.evidence_id)
            event=utc(normalize(sample['time'],sample['time_msc'],profile=self.profile,server=self.server,api='symbol_info_tick')['normalized_time_utc'])
            decision_age=(clock.corrected(decision_utc)-event).total_seconds()
            if decision_age+float(clock.uncertainty_seconds)>FIXTURE_MAX_AGE_SECONDS or decision_age+float(clock.uncertainty_seconds)<0:
                raise TradingError('Five-second freshness must hold when consuming the source, not only at acquisition.')
            corrected={k:v for k,v in sample.items() if k not in mono_fields}
            for key in ('acquired_start_utc','acquired_end_utc'): corrected[key]=clock.corrected(sample[key]).isoformat()
            result=self.observe(corrected,candle_times,clock_verified=True,clock_uncertainty_ms=int((clock.uncertainty_seconds*1000).to_integral_value(rounding='ROUND_CEILING')),clock_evidence_ref=clock.evidence_id,_same_cycle=True)
            if result['status']!='UNAVAILABLE':
                result.update(clock_assurance='UNAUTHENTICATED_OPERATIONAL_PAPER_ONLY',clock_offset_seconds=str(clock.offset_seconds),
                              raw_acquired_start_utc=sample['acquired_start_utc'],raw_acquired_end_utc=sample['acquired_end_utc'],clock_expires_mono_ns=clock.expires_mono_ns)
            if result['status']=='READ_ONLY_VALIDATED_FIXTURE':
                self.clock_deadline=clock.expires_mono_ns;self.clock_decision=(decision_mono_ns,utc(decision_utc),clock)
            return result
        except (TradingError,ValueError,TypeError,KeyError):
            self.previous=None
            return {'status':'UNAVAILABLE','reason':'Incomplete/invalid/expired same-cycle clock evidence.','ai_analysis':False,'paper_execution':False}

    def snapshot_cycle(self,*,decision_utc,decision_mono_ns):
        try:
            if not self.connected or self.validated is None or self.clock_deadline is None or type(decision_mono_ns)!=int:
                raise TradingError('No qualified source cycle.')
            prior,wall,clock=self.clock_decision
            if not prior<=decision_mono_ns<=self.clock_deadline or abs((utc(decision_utc)-wall).total_seconds()-(decision_mono_ns-prior)/10**9)>.050:
                raise TradingError('Source cycle expired or clock changed.')
            window=self.profile.validated_windows()[0]
            if not window[0]<=clock.corrected(decision_utc)<window[1]: raise TradingError('Session profile expired.')
            age=(clock.corrected(decision_utc)-utc(self.validated['tick']['normalized_time_utc'])).total_seconds()
            if not 0<=age+float(clock.uncertainty_seconds)<=FIXTURE_MAX_AGE_SECONDS:
                raise TradingError('Source became stale before lease expiry.')
            return dict(self.validated)
        except (TradingError,ValueError,TypeError):
            self.validated=None;self.previous=None;self.clock_deadline=None;self.clock_decision=None
            return {'status':'UNAVAILABLE','reason':'Source cycle expired/unqualified; reacquire bracketed evidence.','ai_analysis':False,'paper_execution':False}

    def observe(self,sample,candle_times,*,clock_verified=False,clock_uncertainty_ms=None,clock_evidence_ref=None,_same_cycle=False):
        self.validated=None;self.clock_deadline=None;self.clock_decision=None
        try:
            if not self.connected: raise TradingError('Disconnected; no source observation accepted.')
            if (clock_verified is not True or type(clock_uncertainty_ms)!=int or not 0<=clock_uncertainty_ms<=(750 if _same_cycle else FIXTURE_MAX_CLOCK_UNCERTAINTY_MS)
                or not isinstance(clock_evidence_ref,str) or not 1<=len(clock_evidence_ref)<=200): raise TradingError('Bounded verified fixture clock uncertainty/provenance required.')
            fields={'kind','time','time_msc','acquired_start_utc','acquired_end_utc'}
            if not isinstance(sample,dict) or set(sample)!=fields or sample['kind']!='TEST_FIXTURE': raise TradingError('Read-only fixture acquisition schema only.')
            start,end=utc(sample['acquired_start_utc']),utc(sample['acquired_end_utc'])
            if not 0<=(end-start).total_seconds()<=FIXTURE_MAX_ACQUISITION_SECONDS: raise TradingError('Acquisition interval invalid/too long.')
            tick=normalize(sample['time'],sample['time_msc'],profile=self.profile,server=self.server,api='symbol_info_tick')
            event=utc(tick['normalized_time_utc']);age=(end-event).total_seconds()
            uncertainty=clock_uncertainty_ms/1000
            if (age+uncertainty<0 if _same_cycle else age<0) or age+uncertainty>FIXTURE_MAX_AGE_SECONDS:
                raise TradingError('Demonstrably future/stale event outside qualified clock interval.')
            if self.floor is not None and sample['time_msc']<=self.floor: raise TradingError('Cached/nonadvancing tick; no fresh reconnect proof.')
            if self.previous is not None and start<self.previous: raise TradingError('Acquisition order went backwards.')
            self.floor=sample['time_msc']
            if self.previous is None:
                self.previous=end
                return {'status':'WAIT','reason':'First bounded observation; await advancing tick.'}
            self.previous=end
            if not isinstance(candle_times,list) or not 12<=len(candle_times)<=49: raise TradingError('Need 12–48 closed M1 candles; at most one forming candidate.')
            closed=[];prior=None
            for raw in candle_times:
                bar=normalize(raw,profile=self.profile,server=self.server,api='copy_rates_from_pos')
                opened=utc(bar['normalized_time_utc'])
                if opened.second or opened.microsecond or (prior is not None and (opened-prior).total_seconds()!=60): raise TradingError('M1 candle open times not aligned/contiguous.')
                prior=opened;close=opened+timedelta(seconds=60)
                if close<=event: closed.append(dict(raw_time=raw,open_time_candidate_utc=opened.isoformat(),close_time_candidate_utc=close.isoformat()))
                elif opened>event: raise TradingError('Future candle open time.')
            if not 12<=len(closed)<=48 or not 0<=(event-utc(closed[-1]['close_time_candidate_utc'])).total_seconds()<60:
                raise TradingError('Closed candle history stale/incomplete.')
            # OPEN semantics are a fixture hypothesis here, not a broker-verified claim.
            self.validated=dict(status='READ_ONLY_VALIDATED_FIXTURE',tick=tick,closed_candles=closed,
                                acquired_start_utc=start.isoformat(),acquired_end_utc=end.isoformat(),clock_uncertainty_ms=clock_uncertainty_ms,clock_evidence_ref=clock_evidence_ref,
                                ai_analysis=False,paper_execution=False,candle_semantics='FIXTURE_OPEN_TIME_HYPOTHESIS',clock_borderline=age<0)
            return self.validated
        except (TradingError,ValueError,TypeError,KeyError) as exc:
            self.previous=None
            return {'status':'UNAVAILABLE','reason':str(exc),'ai_analysis':False,'paper_execution':False}

def main():
    import argparse
    parser=argparse.ArgumentParser(description='Offline clock/source-policy replay; no broker/model/network access.')
    parser.add_argument('trace');args=parser.parse_args()
    try:
        trace=json.loads(open(args.trace,encoding='utf-8').read())
        if trace['schema_version']!=1: raise TradingError('Unsupported trace version.')
        p=dict(trace['profile']);p['apis']=tuple(p['apis']);p['windows']=tuple(OffsetWindow(**w) for w in p['windows'])
        profile=BrokerTimeProfile(**p)
        source=ReadOnlyFixtureSource(profile=profile,server=profile.server);source.connect()
        results=[]
        for cycle in trace['cycles']:
            sample=dict(cycle['sample']);input_kind=sample['kind']
            if input_kind not in ('TEST_FIXTURE','DEMO_OBSERVATION'): raise TradingError('Market-only fixture/DEMO observation replay only.')
            # Actual observation provenance is retained; this offline copy cannot promote a real source.
            sample['kind']='TEST_FIXTURE'
            result=source.observe_cycle(sample,cycle['candle_times'],before=cycle['before'],after=cycle['after'],
                                        decision_utc=cycle['decision_utc'],decision_mono_ns=cycle['decision_mono_ns'])
            results.append(dict(result,input_kind=input_kind,policy_replay_only=True))
        print(json.dumps(dict(policy_commit='cb288c63b76b763b07cbca63cf85cb3f9d4364a5',results=results),indent=2))
        return 0 if results and results[-1]['status']=='READ_ONLY_VALIDATED_FIXTURE' else 2
    except (KeyError,TypeError,ValueError,OSError) as exc:
        print(json.dumps({'status':'UNAVAILABLE','policy_replay_only':True,'reason':str(exc),'ai_analysis':False,'paper_execution':False}))
        return 2

if __name__=='__main__':
    raise SystemExit(main())
