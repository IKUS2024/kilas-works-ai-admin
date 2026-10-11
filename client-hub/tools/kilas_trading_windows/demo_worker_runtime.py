"""Bounded coordination transport/scheduling. No configured live entry point.

Standard library only. Construction does not open a connection. Real HTTPS
requires explicit endpoint authorization and a secure in-memory provider;
neither is supplied or configured by this module or its fixture CLI.
"""
import http.client
import json
import math
import re
import ssl
from queue import Queue,Empty
from threading import Event,Lock,Thread,current_thread
from time import perf_counter
from urllib.parse import urlsplit
from demo_control_v2 import PATH,strict_json,lot,WAIT

ACK_FIELDS={'revision','command_id','actual_state','instrument','lot','account_mode',
            'terminal_connected','position_open','protection_active','specs_verified',
            'risk_allowed','policy_state','wait_reason'}

def validate_request(body,*,allow_terminal_evidence=False):
    if (type(body) is not dict or set(body)!={'schema_version','sequence','challenge','ack'}
        or type(body['schema_version']) is not int or body['schema_version']!=2
        or type(body['sequence']) is not int or not 0<=body['sequence']<=2**63-1):
        raise ValueError()
    if body['sequence']==0:
        if body['challenge'] is not None or body['ack'] is not None: raise ValueError()
        return
    if type(body['challenge']) is not str or not re.fullmatch('[0-9a-f]{64}',body['challenge']): raise ValueError()
    a=body['ack']
    if type(a) is not dict or set(a)!=ACK_FIELDS: raise ValueError()
    if type(a['revision']) is not int or not 0<=a['revision']<=2**63-2: raise ValueError()
    if a['command_id'] is not None and (type(a['command_id']) is not str or not re.fullmatch('[0-9a-f]{32}',a['command_id'])): raise ValueError()
    if a['actual_state'] not in ('OFF','PROTECTING','RUNNING','BLOCKED') or a['instrument'] not in ('BTC','GOLD'): raise ValueError()
    lot(a['lot'])
    if a['account_mode'] not in ('DEMO','UNKNOWN') or a['policy_state'] not in ('UNSET','READY','BLOCKED') or a['wait_reason'] not in WAIT: raise ValueError()
    for key in ('terminal_connected','position_open','protection_active','specs_verified','risk_allowed'):
        if type(a[key]) is not bool: raise ValueError()
    if a['position_open'] and (not a['protection_active'] or a['actual_state'] not in ('PROTECTING','RUNNING')): raise ValueError()
    if a['command_id'] is None and (a['revision']!=0 and allow_terminal_evidence is not True
                                  or a['actual_state']!='OFF' or a['position_open']): raise ValueError()
    if allow_terminal_evidence is True and not (
        a['command_id'] is None and a['actual_state']=='OFF' and a['instrument']=='BTC'
        and a['account_mode']=='DEMO' and a['terminal_connected'] is True
        and a['position_open'] is False and a['protection_active'] is False
        and a['specs_verified'] is False and a['risk_allowed'] is False
        and a['policy_state']=='UNSET'): raise ValueError()
    if a['actual_state']=='RUNNING' and not (a['account_mode']=='DEMO' and a['terminal_connected']
        and a['specs_verified'] and a['risk_allowed'] and a['policy_state']=='READY' and a['wait_reason']=='NONE'): raise ValueError()


class TransportFailure(RuntimeError):
    """Fixed public reason; never include HTTP bodies, tokens or exceptions."""

TRANSPORT_CODES={'TRANSPORT_TIMEOUT','CREDENTIAL_UNAVAILABLE','HTTP_STATUS_REJECTED',
                 'HTTP_FORMAT_REJECTED','HTTP_SIZE_REJECTED'}

EVIDENCE_PATH='/products/services/trading/control/btc-evidence'
ANALYSIS_PATH='/products/services/trading/control/btc-analysis'
HTTP_PATHS=frozenset((PATH,EVIDENCE_PATH,ANALYSIS_PATH))
GOLD_EVIDENCE_PATH='/products/services/trading/control/gold-evidence'
GOLD_ANALYSIS_PATH='/products/services/trading/control/gold-analysis'
HTTP_PATHS=HTTP_PATHS|frozenset((GOLD_EVIDENCE_PATH,GOLD_ANALYSIS_PATH))
ANALYSIS_PATHS=frozenset((ANALYSIS_PATH,GOLD_ANALYSIS_PATH))


def validate_path_request(path,body):
    if path==PATH:
        validate_request(body)
    else:
        # Keep the existing coordination client independently importable. These
        # validators share the real BTC client schema, not fixture projections.
        from btc_integration_protocol import validate_evidence_request,validate_analysis_request
        if path==EVIDENCE_PATH: validate_evidence_request(body)
        elif path==ANALYSIS_PATH: validate_analysis_request(body)
        elif path==GOLD_EVIDENCE_PATH: validate_evidence_request(body,instrument='GOLD')
        elif path==GOLD_ANALYSIS_PATH: validate_analysis_request(body,instrument='GOLD')
        else: raise ValueError()


class BoundedControlHTTP:
    """Three independent request lanes; an ambiguous lane cannot be replayed.

    Analysis may take longer than a capture/lease refresh. Its watchdog and
    unresolved state therefore never hold the sync or evidence lane. The caller
    must stop entries after any uncertainty and continue protection/control.
    """
    transport_implemented=True
    inspect_sync_error_outcomes=False
    def __init__(self,endpoint=None,credential_provider=None,*,endpoint_authorized=False,
                 connection_factory=None,total_timeout=1.5,analysis_timeout=30.,clock=perf_counter):
        if type(total_timeout) not in (int,float) or not math.isfinite(total_timeout) or not .05<=total_timeout<=2:
            raise TransportFailure('TRANSPORT_CONFIGURATION_INVALID')
        if type(analysis_timeout) not in (int,float) or not math.isfinite(analysis_timeout) or not .05<=analysis_timeout<=60:
            raise TransportFailure('TRANSPORT_CONFIGURATION_INVALID')
        self.endpoint,self.provider=endpoint,credential_provider
        self.authorized=endpoint_authorized is True
        self.factory=connection_factory
        self.timeout,self.clock=total_timeout,clock
        self.analysis_timeout=analysis_timeout
        self.locks={path:Lock() for path in HTTP_PATHS}
        self.unresolved_paths=set()
        self.lock=self.locks[PATH]  # Existing coordination-only API.

    @property
    def unresolved(self):
        return self.path_unresolved(PATH)

    def path_unresolved(self,path):
        return path in self.unresolved_paths

    def reset_evidence_after_expiry(self, *, instrument='BTC'):
        """Allow a fresh evidence bootstrap after the old nonce has expired.

        The protocol client must first prove nonce expiry from its conservative
        authenticated server clock, while keeping original session/run bounds.
        This method neither retries nor sends anything. An abandoned HTTP worker
        remains abandoned; clearing this lane never restores that request.
        Sync and analysis uncertainty deliberately have no reset operation.
        """
        from demo_integration_instruments import wire_profile
        path=wire_profile(instrument).evidence_path
        lane_lock=self.locks[path]
        if not lane_lock.acquire(False):
            raise TransportFailure('TRANSPORT_BUSY_OR_PATH_INVALID')
        try:
            was_unresolved=path in self.unresolved_paths
            self.unresolved_paths.discard(path)
            return was_unresolved
        finally: lane_lock.release()

    def _request_checkpoint(self,path):
        """Subclass capability/lifetime guard, also checked after blocking work."""

    def _validate_path_request(self,path,body):
        validate_path_request(path,body)

    def _response_diagnostic(self,path,status,outcome=None):
        """Optional sink for a safe status and known outcome, never raw data.

        Runs in the HTTP worker thread. The default retains nothing. Subclasses
        may opt into bounded sync error-body parsing with the class flag above;
        this hook cannot authorize a request or alter its outcome.
        """

    def _report_response_diagnostic(self,path,status,outcome=None):
        if type(status) is not int or not 100<=status<=599: return
        try:
            if outcome is not None:
                from btc_integration_protocol import BLOCKED_OUTCOMES
                allowed=BLOCKED_OUTCOMES|{'BOOTSTRAPPED','ACK_ACCEPTED','CAPTURE_CHALLENGE_ISSUED',
                                         'EVIDENCE_ACCEPTED','PROPOSAL_READY'}
                if type(outcome) is not str or outcome not in allowed: return
            self._response_diagnostic(path,status,outcome)
        except Exception:
            # Diagnostics are optional and may never leak an exception, grant
            # authority, retry a request, or replace its normal transport result.
            pass

    def post(self,path,body):
        self._request_checkpoint(path)
        if path not in HTTP_PATHS: raise TransportFailure('TRANSPORT_BUSY_OR_PATH_INVALID')
        if self.path_unresolved(path): raise TransportFailure('TRANSPORT_UNRESOLVED')
        if not self.authorized or not callable(self.provider):
            raise TransportFailure('TRANSPORT_NOT_AUTHORIZED')
        lane_lock=self.locks[path]
        if not lane_lock.acquire(False):
            raise TransportFailure('TRANSPORT_BUSY_OR_PATH_INVALID')
        try:
            if self.path_unresolved(path): raise TransportFailure('TRANSPORT_UNRESOLVED')
            try:
                parsed=urlsplit(self.endpoint)
                if (parsed.scheme!='https' or not parsed.hostname or parsed.port not in (None,443)
                    or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment):
                    raise ValueError()
                payload=json.dumps(body,ensure_ascii=True,allow_nan=False,separators=(',',':')).encode('utf8')
                frozen_body=strict_json(payload)
                self._validate_path_request(path,frozen_body)
            except Exception: raise TransportFailure('TRANSPORT_CONFIGURATION_INVALID') from None
            timeout=self.analysis_timeout if path in ANALYSIS_PATHS else self.timeout
            start=self.clock(); deadline=start+timeout
            done=Queue(maxsize=1); abandoned=Event(); connection={}
            def left():
                self._request_checkpoint(path)
                remaining=deadline-self.clock()
                if abandoned.is_set() or remaining<=0: raise TransportFailure('TRANSPORT_TIMEOUT')
                c=connection.get('value')
                if c is not None:
                    c.timeout=remaining
                    if getattr(c,'sock',None) is not None: c.sock.settimeout(remaining)
                return remaining
            def work():
                c=None
                try:
                    # Runs inside the absolute watchdog bound, including secure
                    # handoff/provider latency and TLS/DNS connect. No retries.
                    left()
                    token=self.provider()
                    # Old sync-only fake factories use descriptive synthetic
                    # tokens. Every native HTTPS request and both BTC lanes
                    # require the real contract's exact bearer shape.
                    token_pattern=(r'[!-~]{1,4096}' if path==PATH and self.factory is not None
                                   else r'[0-9a-f]{64}')
                    if type(token) is not str or not re.fullmatch(token_pattern,token):
                        raise TransportFailure('CREDENTIAL_UNAVAILABLE')
                    remaining=left()
                    factory=self.factory or http.client.HTTPSConnection
                    c=factory(parsed.hostname,port=443,timeout=remaining,context=ssl.create_default_context())
                    connection['value']=c
                    left(); c.connect(); left()  # A late DNS/TLS result must not send.
                    headers={'Authorization':'Bearer '+token,'Content-Type':'application/json; charset=utf-8',
                             'Accept':'application/json','Accept-Encoding':'identity','Connection':'close'}
                    c.request('POST',path,body=payload,headers=headers)
                    del token,headers
                    left(); response=c.getresponse(); left()
                    self._report_response_diagnostic(path,response.status)
                    # Preserve the legacy sync behavior. New BTC paths also
                    # validate the contract's fixed error envelope, then discard
                    # its contents; even an unknown code can never grant entry.
                    if response.status!=200 and path==PATH and self.inspect_sync_error_outcomes is not True:
                        raise TransportFailure('HTTP_STATUS_REJECTED')
                    content_type=response.getheader('Content-Type','')
                    if content_type.lower().replace(' ','') not in ('application/json','application/json;charset=utf-8'):
                        raise TransportFailure('HTTP_FORMAT_REJECTED')
                    if response.getheader('Content-Encoding','identity').lower()!='identity':
                        raise TransportFailure('HTTP_FORMAT_REJECTED')
                    declared=response.getheader('Content-Length')
                    if declared is not None and (not re.fullmatch('[0-9]{1,8}',declared) or int(declared)>8192):
                        raise TransportFailure('HTTP_SIZE_REJECTED')
                    chunks=[]; size=0
                    while True:
                        left(); part=response.read(min(1024,8193-size)); left()
                        if not part: break
                        chunks.append(part); size+=len(part)
                        if size>8192: raise TransportFailure('HTTP_SIZE_REJECTED')
                    raw=b''.join(chunks)
                    if declared is not None and int(declared)!=len(raw): raise TransportFailure('HTTP_SIZE_REJECTED')
                    try: decoded=strict_json(raw)
                    except Exception: raise TransportFailure('HTTP_FORMAT_REJECTED') from None
                    left()
                    if response.status!=200:
                        if (set(decoded)!={'outcome'} or type(decoded['outcome']) is not str
                            or not re.fullmatch(r'[A-Z][A-Z0-9_]*',decoded['outcome'])):
                            raise TransportFailure('HTTP_FORMAT_REJECTED')
                        self._report_response_diagnostic(path,response.status,decoded['outcome'])
                        raise TransportFailure('HTTP_STATUS_REJECTED')
                    if 'outcome' in decoded:
                        self._report_response_diagnostic(path,response.status,decoded['outcome'])
                    if not abandoned.is_set(): done.put_nowait((raw,None))
                except Exception as exc:
                    code=str(exc) if isinstance(exc,TransportFailure) and str(exc) in TRANSPORT_CODES else 'TRANSPORT_FAILED'
                    if not abandoned.is_set(): done.put_nowait((None,code))
                finally:
                    if c is not None:
                        try: c.close()
                        except Exception: pass
            Thread(target=work,name='demo-http-'+path.rsplit('/',1)[1],daemon=True).start()
            try: raw,error=done.get(timeout=max(0,deadline-self.clock()))
            except Empty:
                self.unresolved_paths.add(path)
                abandoned.set()
                c=connection.get('value')
                if c is not None:
                    # Closing the socket interrupts an outstanding normal TLS
                    # read. DNS may finish later; left() prevents a late POST.
                    sock=getattr(c,'sock',None)
                    if sock is not None:
                        try: sock.close()
                        except Exception: pass
                raise TransportFailure('TRANSPORT_TIMEOUT') from None
            if self.clock()>=deadline:
                self.unresolved_paths.add(path); abandoned.set()
                raise TransportFailure('TRANSPORT_TIMEOUT')
            if error:
                self.unresolved_paths.add(path); raise TransportFailure(error) from None
            return raw
        finally: lane_lock.release()


class CoordinationWorker:
    """Independent heartbeat and sync threads; no model work in either.

    Snapshot provider must be bounded, read-only and independent of analysis.
    HTTP itself is bounded. No daemon/service/session/power settings are changed.
    """
    def __init__(self,client,snapshot_provider,*,sync_interval=2.,heartbeat_interval=.05):
        if not 1<=sync_interval<=2 or not .01<=heartbeat_interval<=.25:
            raise ValueError('WORKER_CONFIGURATION_INVALID')
        self.client,self.snapshot_provider=client,snapshot_provider
        self.interval,self.heartbeat_interval=sync_interval,heartbeat_interval
        self.close_requested=Event(); self.finished=Event(); self.threads=[]
        self.failure=None

    def start(self):
        if self.threads: raise ValueError('WORKER_ALREADY_STARTED')
        self.client.controller.stop()
        self.threads=[Thread(target=self._heartbeat,name='demo-heartbeat',daemon=True),
                      Thread(target=self._coordination,name='demo-coordination',daemon=True)]
        for t in self.threads: t.start()
        return self

    def _heartbeat(self):
        while not self.finished.is_set():
            try: self.client.heartbeat()
            except Exception:
                self.failure='HEARTBEAT_FAILED'; self.client.stop('UNSAFE_ACK')
            self.finished.wait(self.heartbeat_interval)

    def _coordination(self):
        try:
            while True:
                if self.close_requested.is_set() and not self.client.ended:
                    self.client.stop('OFF_REQUESTED')
                if self.client.ended:
                    # Honor the protocol minimum between POST starts, including
                    # an OFF received from the immediately preceding response.
                    previous=self.client.last_started
                    if previous is not None:
                        self.finished.wait(max(0,1-(self.client.clock()-previous)))
                    try: self.client.final_stop_ack(self.snapshot_provider())
                    except Exception: self.failure='FINAL_ACK_UNAVAILABLE'
                    break
                try: self.client.sync(self.snapshot_provider())
                except Exception:
                    self.failure='SNAPSHOT_UNAVAILABLE'; self.client.stop('UNSAFE_ACK')
                if self.client.ended: continue
                self.close_requested.wait(self.interval)
        finally:
            self.client.controller.stop(); self.finished.set()

    def stop(self,timeout=3.):
        deadline=perf_counter()+min(max(timeout,0),3.)
        self.client.stop('OFF_REQUESTED'); self.close_requested.set()
        self.finished.wait(max(0,deadline-perf_counter()))
        for t in self.threads:
            if t is not current_thread(): t.join(max(0,deadline-perf_counter()))
        return self.finished.is_set() and all(not t.is_alive() for t in self.threads)

    def status(self):
        return dict(self.client.status(),worker_finished=self.finished.is_set(),
                    worker_failure=self.failure,model_work_scheduled=False)
