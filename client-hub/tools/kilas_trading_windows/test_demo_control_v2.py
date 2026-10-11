"""Exact v2 fixture protocol; no network, credentials, SDK or paid inference."""
import copy
import json
import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
from demo_control_v2 import V2Client,V2Journal,FixtureScope,ACCOUNT,Rejected,strict_json,lot
from demo_auto_controller import Controller,Position
from test_demo_auto_controller import FakeBroker,Clock,Policy

NOW=datetime(2026,10,10,12,tzinfo=timezone.utc)
def stamp(t): return t.isoformat().replace('+00:00','Z')

class FakeModel:
    calls=0
    def decision(self,s):
        self.calls+=1
        raise AssertionError('Inference forbidden in fixture-only v2')
    def protective_stop(self,s,p): return None

class Port:
    def __init__(self,clock): self.clock=clock; self.calls=[]; self.modify=None; self.delay=0; self.started=None; self.release=None
    def response(self,body):
        at=NOW+timedelta(seconds=self.clock.now)
        active=body['sequence']>0
        p=dict(schema_version=2,enabled=True,desired_state='ON',effective_desired_state='ON',
          actual_state='BLOCKED',actual_state_source='WORKER_ACK_NOT_BROKER_ATTESTATION',
          worker_fresh=True,revision=1,command_id='a'*32,instrument='BTC',lot='0.01',
          issued_at=stamp(NOW),command_expires_at=stamp(NOW+timedelta(seconds=30)),
          run_seconds=120,run_expires_at=stamp(NOW+timedelta(seconds=120)),
          run_started_at=stamp(NOW+timedelta(seconds=2)) if active else None,
          worker_lease_expires_at=stamp(min(at+timedelta(seconds=6),NOW+timedelta(seconds=120))),
          run_status='ACTIVE' if active else 'PENDING',end_reason='NONE',received_at=stamp(at),
          ack_received_at=stamp(at),execution_authorized=False,
          off_behavior='STOP_ENTRIES_KEEP_PROTECTION',wait_reason='STRATEGY_UNAVAILABLE',account_detail=ACCOUNT.copy(),
          outcome='ACK_ACCEPTED' if active else 'BOOTSTRAPPED',sequence=body['sequence'],
          challenge=f"{body['sequence']+1:064x}",challenge_expires_at=stamp(at+timedelta(seconds=10)))
        if self.modify: self.modify(p)
        return p
    def post(self,path,body):
        self.calls.append((path,copy.deepcopy(body)))
        if self.started:
            self.started.set()
            if not self.release.wait(2): raise RuntimeError('Fixture timeout')
        self.clock.now+=self.delay
        return self.response(body)

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.clock=Clock(); self.clock.now=0
        self.broker=FakeBroker(self.clock); self.model=FakeModel()
        policy=Policy('UNAPPROVED_FIXTURE',120,1,D('2'),1.5,D('2'),D('2000'),D('1'))
        self.controller=Controller(self.broker,self.model,policy,clock=self.clock)
        self.port=Port(self.clock); self.journal=V2Journal(self.tmp.name+'/v2.sqlite')
        self.scope=FixtureScope('fixture-session','BTC',NOW+timedelta(seconds=1800),120)
        self.client=self.make()
    def make(self,**changes):
        args=dict(scope=self.scope,clock=self.clock,now=lambda:NOW+timedelta(seconds=self.clock.now),clock_verified=True)
        args.update(changes)
        return V2Client(self.port,self.journal,self.controller,**args)
    def sync(self,at=None):
        if at is not None: self.clock.now=at
        self.broker.s=replace(self.broker.s,receipt_at=self.clock())
        result=self.client.sync(self.broker.snapshot()); self.controller.poll()
        self.assertFalse(self.controller.on); self.assertEqual(self.broker.sent,[])
        self.assertEqual(self.model.calls,0); self.assertFalse(result['execution_authorized'])
        return result
    def test_on_intent_and_running_server_claim_never_activate(self):
        self.port.modify=lambda p:p.update(actual_state='RUNNING' if p['run_status']=='ACTIVE' else 'BLOCKED',
            wait_reason='NONE' if p['run_status']=='ACTIVE' else 'STRATEGY_UNAVAILABLE')
        self.assertFalse(self.sync()['ended']); self.assertFalse(self.sync(2)['ended'])
        ack=self.port.calls[-1][1]['ack']
        self.assertEqual(ack['actual_state'],'BLOCKED'); self.assertFalse(ack['risk_allowed'])
    def test_off_with_open_protection_preserves_position(self):
        self.broker.s=replace(self.broker.s,positions=(Position('private-ticket','BUY',D('80'),True,D('110')),))
        self.sync(); self.sync(2)
        self.assertEqual(self.port.calls[-1][1]['ack']['actual_state'],'PROTECTING')
        self.port.modify=lambda p:p.update(desired_state='OFF',effective_desired_state='OFF',revision=2,
            command_id='b'*32,run_seconds=0,run_expires_at=None,run_started_at=None,
            worker_lease_expires_at=None,run_status='ENDED',end_reason='OFF_REQUESTED')
        result=self.sync(4)
        self.assertTrue(result['ended']); self.assertEqual(result['actual_state'],'PROTECTING')
        self.assertEqual(self.client.ack()['revision'],2)
        self.assertEqual(self.client.ack()['actual_state'],'PROTECTING')
        self.assertEqual(self.broker.tightened,[]); self.assertEqual(len(self.broker.s.positions),1)
    def test_restart_fences_persisted_on(self):
        self.sync(); self.client=self.make(); result=self.sync(2)
        self.assertTrue(result['ended']); self.assertEqual(self.journal.record('fixture-session','a'*32),('ENDED','WORKER_RESTARTED'))
    def test_new_session_fences_old(self):
        self.sync(); self.client=self.make(scope=replace(self.scope,session_id='fixture-new-session'))
        self.assertEqual(self.journal.record('fixture-session','a'*32),('ENDED','SESSION_REPLACED'))
    def test_expired_lease_is_sticky_and_no_retry(self):
        self.sync(); self.clock.now=6
        self.assertEqual(self.client.heartbeat()['end_reason'],'WORKER_LEASE_EXPIRED')
        calls=len(self.port.calls); self.sync(7); self.assertEqual(len(self.port.calls),calls)
    def test_expiry_during_pending_response_late_ack_cannot_revive(self):
        self.sync(); self.clock.now=2
        self.port.started=threading.Event(); self.port.release=threading.Event()
        self.broker.s=replace(self.broker.s,receipt_at=2)
        thread=threading.Thread(target=lambda:self.client.sync(self.broker.s)); thread.start()
        self.assertTrue(self.port.started.wait(1)); self.clock.now=6
        self.client.heartbeat(); self.port.release.set(); thread.join(2)
        self.assertFalse(thread.is_alive()); self.assertEqual(self.client.status()['end_reason'],'WORKER_LEASE_EXPIRED')
        self.assertEqual(self.journal.record('fixture-session','a'*32),('ENDED','WORKER_LEASE_EXPIRED'))
    def test_full_initial_request_latency_subtracted(self):
        # Fixed server receipt and lease, despite a delayed first response.
        original=self.port.response
        self.port.delay=7
        def response(body):
            p=original(body); p['received_at']=stamp(NOW); p['ack_received_at']=stamp(NOW)
            p['worker_lease_expires_at']=stamp(NOW+timedelta(seconds=6))
            p['challenge_expires_at']=stamp(NOW+timedelta(seconds=10)); return p
        self.port.response=response
        self.assertEqual(self.sync()['end_reason'],'WORKER_LEASE_EXPIRED')
    def test_active_past_pickup_with_fresh_leases(self):
        self.sync()
        for at in range(2,34,2): self.assertFalse(self.sync(at)['ended'])
        self.assertEqual(self.client.hard,120); self.assertEqual(self.client.started_at,stamp(NOW+timedelta(seconds=2)))
    def test_hard_deadline_not_renewed(self):
        self.sync()
        for at in range(2,120,2): self.sync(at)
        self.clock.now=120; self.assertEqual(self.client.heartbeat()['end_reason'],'RUN_DEADLINE')
    def test_account_change_blocks_before_transport(self):
        self.sync(); before=len(self.port.calls)
        self.broker.s=replace(self.broker.s,identity=replace(self.broker.s.identity,binding='another-private'))
        self.assertTrue(self.sync(2)['ended']); self.assertEqual(len(self.port.calls),before)
    def test_real_or_wrong_server_or_disconnected(self):
        for changes in ({'mode':'REAL'},{'server':'wrong'}):
            self.broker.s=replace(self.broker.s,identity=replace(self.broker.s.identity,**changes))
            self.assertTrue(self.sync()['ended']); self.assertEqual(self.port.calls,[])
        self.client=self.make(); self.broker.s=replace(FakeBroker(self.clock).s,connected=False)
        self.assertTrue(self.sync()['ended']); self.assertEqual(self.port.calls,[])
    def test_unknown_field_and_legacy_alias_rejected(self):
        self.port.modify=lambda p:p.update(expires_at=p['run_expires_at'])
        self.assertEqual(self.sync()['end_reason'],'UNSAFE_ACK')
    def test_execution_true_rejected(self):
        self.port.modify=lambda p:p.update(execution_authorized=True)
        self.assertTrue(self.sync()['ended'])
    def test_scope_missing_cap_or_clock_blocks(self):
        self.client=self.make(scope=replace(self.scope,max_run_seconds=None)); self.assertTrue(self.sync()['ended'])
        self.client=self.make(clock_verified=False); before=len(self.port.calls)
        self.sync(); self.assertEqual(len(self.port.calls),before)
    def test_bad_types_and_account_detail(self):
        for key,value in [('revision',True),('worker_fresh',1),('lot','0.010'),('account_detail',dict(ACCOUNT,balance=1))]:
            with self.subTest(key=key):
                p=self.port.response({'sequence':0}); p[key]=value
                with self.assertRaises((Rejected,ValueError,TypeError)): self.client.validate({k:v for k,v in p.items() if k not in ('outcome','sequence','challenge','challenge_expires_at')})
    def test_strict_raw_json(self):
        for raw in ('{"x":1,"x":2}','{"x":NaN}','{"x":1e999}','{"__proto__":{}}','{"x":{"constructor":0}}','{"x":"'+('a'*8192)+'"}'):
            with self.subTest(raw=raw[:40]),self.assertRaises((Rejected,ValueError)): strict_json(raw)
        for value in ('01','0.010','1e-2',' 0.01',0.01,'100000001','0.001','0.??'):
            with self.subTest(value=value),self.assertRaises(Rejected): lot(value)
    def test_backward_clock_stops(self):
        self.sync(); self.sync(2); self.clock.now=1
        self.assertEqual(self.client.heartbeat()['end_reason'],'CLOCK_DISCONTINUITY')
    def test_scope_expiry(self):
        self.client=self.make(scope=replace(self.scope,expires_at=NOW))
        self.assertEqual(self.sync()['end_reason'],'CREDENTIAL_UNAVAILABLE'); self.assertEqual(self.port.calls,[])
    def test_server_error_no_automatic_retry(self):
        self.port.response=lambda _:dict(outcome='CONFLICT')
        self.sync(); calls=len(self.port.calls); self.sync(2); self.assertEqual(len(self.port.calls),calls)
    def test_stale_observation_not_reported_fresh(self):
        self.sync(); self.clock.now=2
        self.assertFalse(self.client.status()['local_observation_fresh'])
    def test_duplicate_mutation_and_active_regression_stop(self):
        self.sync(); self.sync(2)
        self.port.modify=lambda p:p.update(run_status='PENDING',run_started_at=None)
        self.assertTrue(self.sync(4)['ended'])
    def test_pending_pickup_is_fixed_not_renewed_by_prior_acks(self):
        self.port.modify=lambda p:p.update(run_status='PENDING',run_started_at=None)
        self.sync()
        for at in range(2,30,2): self.assertFalse(self.sync(at)['ended'])
        self.clock.now=30
        self.assertEqual(self.client.heartbeat()['end_reason'],'PICKUP_EXPIRED')
    def test_changed_fixed_duration_and_started_timestamp_rejected(self):
        self.sync(); self.sync(2)
        self.port.modify=lambda p:p.update(run_started_at=stamp(NOW+timedelta(seconds=3)))
        self.assertTrue(self.sync(4)['ended'])
    def test_bootstrap_null_command_cannot_ack_open_as_flat(self):
        self.broker.s=replace(self.broker.s,positions=(Position('local-private','BUY',D('80'),True,D('110')),))
        self.port.modify=lambda p:p.update(desired_state='OFF',effective_desired_state='OFF',revision=0,
            command_id=None,issued_at=None,command_expires_at=None,run_seconds=0,
            run_expires_at=None,run_started_at=None,worker_lease_expires_at=None,run_status='NONE',end_reason='NONE')
        self.sync(); count=len(self.port.calls)
        result=self.sync(2)
        self.assertTrue(result['ended']); self.assertEqual(result['actual_state'],'PROTECTING')
        self.assertEqual(len(self.port.calls),count)
    def test_fake_mt5_adapter_controller_model_chain_no_check_send_inference(self):
        from test_mt5_demo_adapter import FakeSDK
        from mt5_demo_adapter import MT5DemoAdapter,Journal
        sdk=FakeSDK()
        adapter=MT5DemoAdapter(sdk,Journal(self.tmp.name+'/adapter.sqlite'),clock=self.clock,wall=self.clock)
        self.controller=Controller(adapter,self.model,clock=self.clock)
        self.client=self.make()
        for _ in range(3): snapshot=adapter.snapshot()
        result=self.client.sync(snapshot); self.controller.poll()
        self.assertFalse(result['ended']); self.assertFalse(adapter.execute)
        self.assertEqual((sdk.checks,sdk.sends,self.model.calls),([],[],0))
        self.clock.now=2; self.client.sync(adapter.snapshot()); self.controller.poll()
        self.assertEqual((sdk.checks,sdk.sends,self.model.calls),([],[],0))
    def test_active_on_cannot_be_replaced_with_new_on(self):
        self.sync(); self.sync(2)
        self.port.modify=lambda p:p.update(command_id='c'*32,revision=2)
        self.assertEqual(self.sync(4)['end_reason'],'UNSAFE_ACK')
    def test_inconsistent_running_claim_rejected(self):
        self.port.modify=lambda p:p.update(actual_state='RUNNING')
        self.assertTrue(self.sync()['ended'])
    def test_expired_challenge_not_used_and_no_bootstrap_retry(self):
        # Null OFF projection has no run/lease; challenge expires independently.
        self.port.modify=lambda p:p.update(desired_state='OFF',effective_desired_state='OFF',revision=0,
            command_id=None,issued_at=None,command_expires_at=None,run_seconds=0,
            run_expires_at=None,run_started_at=None,worker_lease_expires_at=None,run_status='NONE',end_reason='NONE')
        self.sync(); calls=len(self.port.calls); self.clock.now=10
        self.assertEqual(self.client.heartbeat()['end_reason'],'CREDENTIAL_UNAVAILABLE')
        self.sync(12); self.assertEqual(len(self.port.calls),calls)

if __name__=='__main__': unittest.main()
