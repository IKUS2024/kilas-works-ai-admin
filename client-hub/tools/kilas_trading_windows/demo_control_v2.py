"""V2 coordination, inert unless reviewed readiness is explicitly supplied.

Control responses never grant execution. A separate bounded BTC analysis grant
may preserve an already eligible controller through the injected readiness seam.
"""
import hashlib
import json
import math
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Lock
from time import perf_counter
from ai_market_news_contract import utc
from demo_auto_controller import Snapshot
from btc_server_clock import ServerClockError
from demo_integration_instruments import wire_profile

PATH='/products/services/trading/control/sync'
SCOPE='DEMO_BOUNDED_RUN_COORDINATION_V2'
PROJECTION={'schema_version','enabled','desired_state','effective_desired_state','actual_state',
 'actual_state_source','worker_fresh','revision','command_id','instrument','lot','issued_at',
 'command_expires_at','run_seconds','run_expires_at','run_started_at','worker_lease_expires_at',
 'run_status','end_reason','received_at','ack_received_at','execution_authorized','off_behavior',
 'wait_reason','account_detail'}
WAIT={'NONE','MODEL_UNAVAILABLE','STRATEGY_UNAVAILABLE','NEWS_UNVERIFIED','RISK_BLOCKED',
      'DEMO_UNVERIFIED','TRANSPORT_UNAVAILABLE'}
END={'NONE','OFF_REQUESTED','SESSION_REPLACED','WORKER_RESTARTED','CREDENTIAL_UNAVAILABLE',
     'CLOCK_DISCONTINUITY','RUN_DEADLINE','PICKUP_EXPIRED','WORKER_LEASE_EXPIRED','UNSAFE_ACK'}
ACCOUNT={'account_mode':'DEMO','broker':'XM','platform':'MT5','server':'XMGlobal-MT5 10',
         'verification':'WORKER_REPORT_ONLY'}


class Rejected(ValueError): pass


def need(ok):
    if not ok: raise Rejected('CONTROL_V2_REJECTED')


def integer(value,maximum=2**63-1):
    need(type(value) is int and 0<=value<=maximum)


def lot(value):
    need(type(value) is str and re.fullmatch(r'(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{0,7}[1-9])?',value))
    need(Decimal('.01')<=Decimal(value)<=Decimal('100000000'))
    return value


def strict_json(raw):
    def finite_float(value):
        parsed=float(value); need(math.isfinite(parsed)); return parsed
    def pairs(items):
        out={}
        for k,v in items:
            need(k not in out and k not in ('__proto__','constructor','prototype'))
            out[k]=v
        return out
    if isinstance(raw,(str,bytes)):
        encoded=raw.encode('utf-8') if isinstance(raw,str) else raw
        need(len(encoded)<=8192)
        result=json.loads(encoded.decode('utf-8'),object_pairs_hook=pairs,
                          parse_float=finite_float,
                          parse_constant=lambda _: (_ for _ in ()).throw(Rejected('NONFINITE')))
    else:
        # Dict injection is a fixture seam; a real transport must pass raw UTF8.
        need(type(raw) is dict)
        encoded=json.dumps(raw,allow_nan=False).encode('utf-8'); need(len(encoded)<=8192)
        result=json.loads(encoded,object_pairs_hook=pairs)
    need(type(result) is dict)
    return result


@dataclass(frozen=True)
class FixtureScope:
    """Non-secret metadata seam. Not a credential or an approval generator."""
    session_id: str
    instrument: str
    expires_at: datetime
    max_run_seconds: int | None
    name: str=SCOPE


# Metadata only; neither name creates a credential, reviewed acceptance or grant.
ControlScope=FixtureScope


class V2Journal:
    """Separate v2 durable intent/stop records. Never stores bearer/challenge."""
    def __init__(self,filename):
        self.filename=str(filename)
        with self.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS v2_binding(id INTEGER PRIMARY KEY CHECK(id=1), digest TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS v2_commands(session TEXT,id TEXT,revision INTEGER,fingerprint TEXT,'
                      'state TEXT,reason TEXT,PRIMARY KEY(session,id),UNIQUE(session,revision))')
            c.execute('CREATE TABLE IF NOT EXISTS v2_session(id INTEGER PRIMARY KEY CHECK(id=1),session TEXT)')

    @contextmanager
    def db(self):
        c=sqlite3.connect(self.filename,timeout=2); c.execute('PRAGMA synchronous=FULL')
        try:
            with c: yield c
        finally: c.close()

    def recover(self,session):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            prior=c.execute('SELECT session FROM v2_session WHERE id=1').fetchone()
            reason='WORKER_RESTARTED' if prior and prior[0]==session else 'SESSION_REPLACED'
            c.execute("UPDATE v2_commands SET state='ENDED',reason=? WHERE state IN ('PENDING','ACTIVE')",(reason,))
            c.execute('INSERT OR REPLACE INTO v2_session VALUES(1,?)',(session,))

    def bind(self,binding):
        need(binding is not None)
        hashed=hashlib.sha256(repr(binding).encode()).hexdigest()
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            previous=c.execute('SELECT digest FROM v2_binding WHERE id=1').fetchone()
            need(previous is None or previous[0]==hashed)
            c.execute('INSERT OR IGNORE INTO v2_binding VALUES(1,?)',(hashed,))

    def observe(self,session,p):
        if p['command_id'] is None: return False
        fields=('revision','command_id','desired_state','instrument','lot','issued_at','command_expires_at','run_seconds','run_expires_at')
        fingerprint=hashlib.sha256(json.dumps({k:p[k] for k in fields},sort_keys=True).encode()).hexdigest()
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            prior=c.execute('SELECT revision,fingerprint,state,reason FROM v2_commands WHERE session=? AND id=?',
                            (session,p['command_id'])).fetchone()
            highest=c.execute('SELECT max(revision) FROM v2_commands WHERE session=?',(session,)).fetchone()[0]
            if prior:
                need(prior[0:2]==(p['revision'],fingerprint) and p['revision']==highest)
                if prior[2]=='ENDED': return False
                need(not (prior[2]=='ACTIVE' and p['run_status']=='PENDING'))
            else:
                need(highest is None or p['revision']>highest)
                c.execute('INSERT INTO v2_commands VALUES(?,?,?,?,?,?)',
                          (session,p['command_id'],p['revision'],fingerprint,p['run_status'],p['end_reason']))
            c.execute('UPDATE v2_commands SET state=?,reason=? WHERE session=? AND id=?',
                      (p['run_status'],p['end_reason'],session,p['command_id']))
            return True

    def end(self,session,command,reason):
        if command is None: return
        with self.db() as c:
            # Once ended, retain first stop reason; no refresh can clear it.
            c.execute("UPDATE v2_commands SET state='ENDED',reason=? WHERE session=? AND id=? AND state!='ENDED'",
                      (reason,session,command))

    def record(self,session,command):
        with self.db() as c:
            return c.execute('SELECT state,reason FROM v2_commands WHERE session=? AND id=?',(session,command)).fetchone()


class V2Client:
    def __init__(self,port,journal,controller,*,scope=None,clock=perf_counter,
                 now=lambda:datetime.now(timezone.utc),clock_verified=False,
                 server_clock=None,readiness=None,instrument='BTC'):
        self.instrument=wire_profile(instrument).instrument
        self.port,self.journal,self.controller=port,journal,controller
        self.scope,self.clock,self.now=scope,clock,now
        self.clock_verified=clock_verified
        self.server_clock,self.readiness=server_clock,readiness
        need(readiness is None or callable(readiness))
        self.last_ack_context=None
        self.sequence=0; self.challenge=None; self.challenge_deadline=None
        self.projection=None; self.snapshot=None; self.last_started=None
        self.local_verified=False
        self.hard=None; self.soft=None; self.pickup=None; self.last_wall=None; self.last_mono=None
        self.started_at=None; self.ended=False; self.end_reason='NONE'
        self.wait_reason='STRATEGY_UNAVAILABLE'; self.inflight=Lock()
        self.heartbeat_serial=Lock()
        self.final_ack_attempted=False; self.final_acknowledged=False
        self.controller.stop()  # Bootstrap/restart must stop entries first.
        if scope is not None:
            need(type(scope.session_id) is str and 1<=len(scope.session_id)<=80)
            if server_clock is not None: need(re.fullmatch('[0-9a-f]{32}',scope.session_id))
            need(scope.name==SCOPE and scope.instrument in ('BTC','GOLD')
                 and isinstance(scope.expires_at,datetime) and scope.expires_at.tzinfo is not None)
            need(scope.max_run_seconds is None or type(scope.max_run_seconds) is int and 1<=scope.max_run_seconds<=300)
            self.journal.recover(scope.session_id)

    def stop(self,reason):
        need(reason in END)
        self.controller.stop(); self.ended=True
        self.last_ack_context=None
        if self.end_reason=='NONE': self.end_reason=reason
        if self.scope and self.projection:
            self.journal.end(self.scope.session_id,self.projection['command_id'],self.end_reason)

    def coordination_allowed(self):
        return not self.ended

    def terminal_evidence_projection(self,p):
        # Only the separate read-only evidence subclass supports this state.
        return False

    def idle_evidence_projection(self,p):
        return False

    def heartbeat(self):
        """Must run independently of market/model/network work, including POST."""
        # Read/check/update the clock pair atomically relative to another
        # heartbeat; concurrent callers must not look like a backward clock.
        with self.heartbeat_serial:
            return self._heartbeat()

    def _heartbeat(self):
        at,mono=self.now(),self.clock()
        if (self.last_wall is not None and (mono<self.last_mono or
                (self.server_clock is None and at<self.last_wall))):
            self.stop('CLOCK_DISCONTINUITY')
        self.last_wall,self.last_mono=at,mono
        if self.server_clock is not None:
            if self.server_clock.ready:
                try: at=self.server_clock.upper_now(require_fresh=False)
                except ServerClockError: self.stop('CLOCK_DISCONTINUITY'); at=None
            else: at=None
        if self.scope and at is not None and at>=self.scope.expires_at: self.stop('CREDENTIAL_UNAVAILABLE')
        if self.hard is not None and mono>=self.hard: self.stop('RUN_DEADLINE')
        if self.soft is not None and mono>=self.soft: self.stop('WORKER_LEASE_EXPIRED')
        if self.pickup is not None and self.projection and self.projection['run_status']=='PENDING' and mono>=self.pickup:
            self.stop('PICKUP_EXPIRED')
        if self.challenge_deadline is not None and mono>=self.challenge_deadline: self.stop('CREDENTIAL_UNAVAILABLE')
        if self.projection and at is not None:
            p=self.projection
            if p['run_expires_at'] and at>=utc(p['run_expires_at']): self.stop('RUN_DEADLINE')
            if p['worker_lease_expires_at'] and at>=utc(p['worker_lease_expires_at']): self.stop('WORKER_LEASE_EXPIRED')
            if p['run_status']=='PENDING' and at>=utc(p['command_expires_at']): self.stop('PICKUP_EXPIRED')
        if not self.entry_eligible(): self.controller.stop()
        return self.status()

    def readiness_state(self):
        """Fast local facts only; never performs inference or transport."""
        fallback={'ready':False,'entry_authorized':False,'wait_reason':self.wait_reason}
        if self.readiness is None or self.ended: return fallback
        try:
            state=self.readiness()
            need(type(state) is dict and set(state)=={'ready','entry_authorized','wait_reason'})
            need(type(state['ready']) is bool and type(state['entry_authorized']) is bool
                 and state['wait_reason'] in WAIT)
            need(not state['entry_authorized'] or state['ready'])
            need(not state['ready'] or state['wait_reason']=='NONE')
            return state
        except Exception:
            return {'ready':False,'entry_authorized':False,'wait_reason':'RISK_BLOCKED'}

    def entry_eligible(self):
        """Control veto only; the separate BTC authority performs final checks."""
        if self.instrument!='BTC': return False  # Gold proposals/evidence only.
        p=self.projection
        if (self.ended or not p or not self.local_verified or
                not p['enabled'] or p['desired_state']!='ON' or p['effective_desired_state']!='ON'
                or p['run_status']!='ACTIVE' or not p['worker_fresh']): return False
        now=self.clock()
        if self.hard is None or self.soft is None or now>=min(self.hard,self.soft): return False
        if self.server_clock is not None and not self.server_clock.fresh(): return False
        return self.readiness_state()['entry_authorized'] is True

    def scope_current(self):
        if self.scope is None: return False
        if self.server_clock is None: return self.clock_verified and self.now()<self.scope.expires_at
        return (not self.server_clock.ready or
                self.server_clock.upper_now(require_fresh=False)<self.scope.expires_at)

    def local(self,s):
        self.local_verified=False
        # Preserve the last observed position facts even when verification fails.
        if isinstance(s,Snapshot): self.snapshot=s
        need(isinstance(s,Snapshot) and s.identity.mode=='DEMO' and s.identity.server=='XMGlobal-MT5 10'
             and s.identity.currency=='USD' and s.identity.company=='XM Global Limited'
             and s.terminal_binding_verified is True and s.symbol==wire_profile(self.instrument).symbol)
        need(s.connected is True and math.isfinite(s.receipt_at)
             and 0<=self.clock()-s.receipt_at<1.5 and s.liveness_verified is True)
        need(len(s.positions)<=1 and s.pending_orders==0)
        need(all(p.owned and p.stop is not None and p.stop>0 and p.target is not None and p.target>0 for p in s.positions))
        self.journal.bind(s.identity.binding)
        s.specs.validate(self.controller.lot)
        self.snapshot=s
        self.local_verified=True
        return s

    def ack(self):
        s,p=self.snapshot,self.projection
        present=bool(s.positions)
        need(p['command_id'] is not None or not present)
        state=self.readiness_state()
        running=self.entry_eligible() and self.controller.status()['state']=='ON'
        actual='PROTECTING' if present else 'RUNNING' if running else 'BLOCKED' if p and p['desired_state']=='ON' else 'OFF'
        return {'revision':p['revision'],'command_id':p['command_id'],'actual_state':actual,
                'instrument':self.instrument,'lot':lot(str(self.controller.lot)),'account_mode':'DEMO',
                'terminal_connected':s.connected,'position_open':present,'protection_active':present,
                'specs_verified':True,'risk_allowed':state['ready'],'policy_state':'READY' if state['ready'] else 'UNSET',
                'wait_reason':state['wait_reason']}

    def validate(self,p):
        need(set(p)==PROJECTION); integer(p['schema_version']); need(p['schema_version']==2)
        for k in ('enabled','worker_fresh','execution_authorized'): need(type(p[k]) is bool)
        need(p['execution_authorized'] is False and p['actual_state_source']=='WORKER_ACK_NOT_BROKER_ATTESTATION')
        need(p['desired_state'] in ('ON','OFF') and p['effective_desired_state'] in ('ON','OFF'))
        need(p['actual_state'] in ('OFF','PROTECTING','RUNNING','BLOCKED','UNKNOWN'))
        need(p['wait_reason'] in WAIT|{'CONTROL_DISABLED','WORKER_OFFLINE'})
        need(p['run_status'] in ('NONE','PENDING','ACTIVE','ENDED') and p['end_reason'] in END)
        need(p['instrument'] in ('BTC','GOLD') and p['instrument']==self.scope.instrument)
        lot(p['lot']); integer(p['revision'],2**63-2); integer(p['run_seconds'],300)
        need(p['off_behavior']=='STOP_ENTRIES_KEEP_PROTECTION')
        need(p['account_detail'] is None or p['account_detail']==ACCOUNT)
        if p['account_detail'] is not None: need(p['worker_fresh'])
        if p['actual_state']=='RUNNING':
            need(p['desired_state']=='ON' and p['effective_desired_state']=='ON'
                 and p['run_status']=='ACTIVE' and p['worker_fresh']
                 and p['wait_reason']=='NONE' and p['account_detail']==ACCOUNT)
        for k in ('issued_at','command_expires_at','run_expires_at','run_started_at','worker_lease_expires_at','received_at','ack_received_at'):
            if p[k] is not None: utc(p[k])
        need(p['received_at'] is not None)
        if self.server_clock is None: need(utc(p['received_at'])<=self.now())
        if p['ack_received_at'] is not None: need(utc(p['ack_received_at'])<=utc(p['received_at']))
        command=p['command_id']
        if command is None:
            if self.idle_evidence_projection(p): return
            need(p['revision']==0 and p['desired_state']=='OFF' and p['effective_desired_state']=='OFF'
                 and p['run_seconds']==0 and p['run_status']=='NONE' and p['end_reason']=='NONE'
                 and all(p[k] is None for k in ('issued_at','command_expires_at','run_expires_at','run_started_at','worker_lease_expires_at')))
            return
        need(type(command) is str and re.fullmatch('[0-9a-f]{32}',command))
        need(p['issued_at'] is not None and utc(p['issued_at'])<=utc(p['received_at']))
        if p['desired_state']=='ON':
            need(p['run_status'] in ('PENDING','ACTIVE','ENDED'))
            need(type(self.scope.max_run_seconds) is int and 1<=p['run_seconds']<=self.scope.max_run_seconds<=300)
            issued,hard=utc(p['issued_at']),utc(p['run_expires_at'])
            need((hard-issued).total_seconds()==p['run_seconds'] and hard<=self.scope.expires_at)
            pickup=utc(p['command_expires_at'])
            need(pickup==min(issued+timedelta(seconds=30),hard))
            if p['run_status'] in ('PENDING','ACTIVE'):
                need(p['end_reason']=='NONE' and p['worker_lease_expires_at'] is not None)
                lease=utc(p['worker_lease_expires_at'])
                reference=utc(p['ack_received_at'] or p['received_at'])
                need(reference<lease<=min(reference+timedelta(seconds=6),hard,self.scope.expires_at))
                if p['run_status']=='ACTIVE':
                    need(p['run_started_at'] is not None and issued<=utc(p['run_started_at'])<=pickup)
                    need(utc(p['run_started_at'])<=utc(p['received_at']))
                else: need(p['run_started_at'] is None)
            if p['run_status']=='ENDED': need(p['end_reason']!='NONE' and p['effective_desired_state']=='OFF')
        else:
            need(p['run_seconds']==0 and p['effective_desired_state']=='OFF')

    def deadline(self,value,start_mono,start_wall):
        if self.server_clock is not None: return self.server_clock.deadline(value) if value else None
        # Anchor to request start; never add a fresh 6/10/30s after latency.
        return start_mono+(utc(value)-start_wall).total_seconds() if value else None

    def sync(self,snapshot):
        if not self.inflight.acquire(False): self.stop('UNSAFE_ACK'); return self.status()
        try:
            self.heartbeat()
            need(self.coordination_allowed() and (self.clock_verified or self.server_clock is not None)
                 and self.scope is not None and self.scope.name==SCOPE
                 and self.scope.instrument==self.instrument and self.scope_current())
            self.local(snapshot)
            if self.last_started is not None: need(self.clock()-self.last_started>=1)
            if self.sequence==0: body={'schema_version':2,'sequence':0,'challenge':None,'ack':None}
            else:
                need(self.challenge is not None and self.clock()<self.challenge_deadline)
                body={'schema_version':2,'sequence':self.sequence,'challenge':self.challenge,'ack':self.ack()}
            integer(self.sequence); need(len(json.dumps(body).encode())<=8192)
            start_mono,start_wall=self.clock(),self.now(); self.last_started=start_mono
            used_challenge=self.challenge
            self.challenge=None  # A possibly delivered POST consumes it; never retry.
            raw=self.port.post(PATH,body)
            receive_mono=self.clock()
            # If a response arrives after any previously known expiry it is late,
            # even if it contains a fresh-looking challenge/lease or newer ACK.
            self.heartbeat(); need(self.coordination_allowed())
            need(self.clock()>=start_mono)
            if self.server_clock is None: need(self.now()>=start_wall)
            r=strict_json(raw)
            need(set(r)==PROJECTION|{'outcome','sequence','challenge','challenge_expires_at'})
            need(r['outcome']==('BOOTSTRAPPED' if self.sequence==0 else 'ACK_ACCEPTED'))
            integer(r['sequence']); need(r['sequence']==self.sequence)
            need(type(r['challenge']) is str and re.fullmatch('[0-9a-f]{64}',r['challenge']) and r['challenge']!=used_challenge)
            p={k:r[k] for k in PROJECTION}; self.validate(p)
            reference=utc(p['received_at'])
            challenge_exp=utc(r['challenge_expires_at'])
            need(0<(challenge_exp-reference).total_seconds()<=10)
            if self.server_clock is not None:
                self.server_clock.observe(start_mono,receive_mono,p['received_at'])
                need(self.scope_current())
            challenge_deadline=self.deadline(r['challenge_expires_at'],start_mono,start_wall)
            need(self.clock()<challenge_deadline)
            previous=self.projection
            if previous and previous['run_status'] in ('PENDING','ACTIVE') and p['desired_state']=='ON':
                need(p['command_id']==previous['command_id'])
            observed=self.journal.observe(self.scope.session_id,p)
            self.projection=p
            ack=body['ack']
            self.last_ack_context=(self.scope.session_id,p['revision'],p['command_id'],p['instrument'],p['lot']) if (
                ack is not None and all(ack[k]==p[k] for k in ('revision','command_id','instrument','lot'))) else None
            if p['command_id'] is not None and not observed:
                self.stop('WORKER_RESTARTED'); return self.status()
            new_hard=self.deadline(p['run_expires_at'],start_mono,start_wall)
            if self.hard is not None and new_hard is not None and previous and previous['command_id']==p['command_id']:
                # UTC and monotonic clocks are checked independently. Duplicate
                # replies cannot lengthen the fixed hard deadline.
                new_hard=min(self.hard,new_hard)
            self.hard=new_hard
            self.pickup=self.deadline(p['command_expires_at'],start_mono,start_wall)
            self.soft=self.deadline(p['worker_lease_expires_at'],start_mono,start_wall)
            if self.started_at is not None and p['run_started_at'] is not None: need(self.started_at==p['run_started_at'])
            if p['run_started_at'] is not None: self.started_at=p['run_started_at']
            self.challenge=r['challenge']; self.challenge_deadline=challenge_deadline; self.sequence+=1
            if not p['enabled']: self.stop('CREDENTIAL_UNAVAILABLE')
            elif self.terminal_evidence_projection(p):
                # Evidence can report OFF while the trading run stays ended.
                self.ended=True; self.end_reason=p['end_reason']; self.controller.stop()
            elif p['run_status']=='ENDED': self.stop(p['end_reason'])
            elif p['desired_state']=='OFF' and p['command_id'] is not None: self.stop('OFF_REQUESTED')
            self.wait_reason=self.readiness_state()['wait_reason'] if self.readiness is not None else 'STRATEGY_UNAVAILABLE'
            if not self.entry_eligible(): self.controller.stop()
            self.heartbeat()
            return self.status()
        except Exception:
            self.wait_reason='TRANSPORT_UNAVAILABLE'; self.stop('UNSAFE_ACK')
            return self.status()
        finally: self.inflight.release()

    def final_stop_ack(self,snapshot):
        """One bounded stop-state report; never renews a lease or revives intent.

        A live, unused challenge and still-valid scoped credential are required.
        Scope/challenge expiry or an ambiguous POST ends reporting without retry.
        Broker protection is retained even if this report cannot be delivered.
        """
        if not self.inflight.acquire(False): return self.status()
        try:
            if self.final_ack_attempted: return self.status()
            self.final_ack_attempted=True
            if not self.ended: self.stop('OFF_REQUESTED')
            self.heartbeat()
            need((self.clock_verified or self.server_clock is not None) and self.scope and self.scope.name==SCOPE
                 and self.end_reason!='CLOCK_DISCONTINUITY'
                 and self.scope_current() and self.projection is not None
                 and self.sequence>0 and self.challenge and self.clock()<self.challenge_deadline)
            self.local(snapshot)
            if self.last_started is not None: need(self.clock()-self.last_started>=1)
            ack=self.ack()
            ack['actual_state']='PROTECTING' if snapshot.positions else 'OFF'
            body={'schema_version':2,'sequence':self.sequence,'challenge':self.challenge,'ack':ack}
            previous=self.projection
            self.last_started=self.clock(); start_mono=self.last_started
            used_challenge=self.challenge; self.challenge=None
            raw=self.port.post(PATH,body)
            receive_mono=self.clock()
            self.heartbeat()
            need(self.scope_current() and self.clock()<self.challenge_deadline)
            r=strict_json(raw)
            need(set(r)==PROJECTION|{'outcome','sequence','challenge','challenge_expires_at'}
                 and r['outcome']=='ACK_ACCEPTED' and type(r['sequence']) is int and r['sequence']==self.sequence)
            need(type(r['challenge']) is str and re.fullmatch('[0-9a-f]{64}',r['challenge'])
                 and r['challenge']!=used_challenge)
            need(0<(utc(r['challenge_expires_at'])-utc(r['received_at'])).total_seconds()<=10)
            p={k:r[k] for k in PROJECTION}; self.validate(p)
            need(p['command_id']==previous['command_id'] and p['revision']==previous['revision']
                 and p['effective_desired_state']=='OFF'
                 and (self.idle_evidence_projection(p) or
                      (p['run_status']=='ENDED' if p['command_id'] is not None else p['run_status']=='NONE')))
            if self.server_clock is not None:
                self.server_clock.observe(start_mono,receive_mono,p['received_at'])
                need(self.scope_current())
            # Only receipt success is recorded. Returned challenges/deadlines and
            # model/entry state never replace the stopped local session.
            self.final_acknowledged=True
            return self.status()
        except Exception:
            self.wait_reason='TRANSPORT_UNAVAILABLE'
            return self.status()
        finally: self.inflight.release()

    def status(self):
        present=bool(self.snapshot and self.snapshot.positions)
        protected=present and all(p.owned and p.stop and p.target for p in self.snapshot.positions)
        running=self.entry_eligible() and self.controller.status()['state']=='ON'
        return {'schema_version':2,'actual_state':'PROTECTING' if protected else 'RUNNING' if running else 'BLOCKED'
                    if self.ended and self.end_reason!='OFF_REQUESTED' else 'OFF',
                'controller_state':self.controller.status()['state'],'position_open':present,
                'protection_active':bool(protected),'ended':self.ended,'end_reason':self.end_reason,
                'position_facts_source':'LAST_LOCAL_OBSERVATION',
                'local_evidence_verified':self.local_verified,
                'local_observation_fresh':bool(self.local_verified and self.snapshot and self.snapshot.connected is True
                    and 0<=self.clock()-self.snapshot.receipt_at<1.5),
                'wait_reason':self.wait_reason,'execution_authorized':False,'actual_inference_performed':False,
                'final_stop_ack_attempted':self.final_ack_attempted,
                'final_stop_acknowledged':self.final_acknowledged,
                'network_transport_installed':bool(getattr(self.port,'transport_implemented',False)),
                'credentials_provisioned_by_client':False,
                'status_source':'LOCAL_DEMO_OBSERVATION_NOT_BROKER_ATTESTATION'}
