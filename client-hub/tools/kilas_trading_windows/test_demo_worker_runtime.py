import tempfile
import time
import unittest
from dataclasses import replace
from datetime import timedelta
from threading import Event,Thread
from demo_control_v2 import V2Client,V2Journal,FixtureScope
from demo_worker_runtime import BoundedControlHTTP,TransportFailure,CoordinationWorker
from demo_runtime_fixtures import FakeServer
from test_demo_control_v2 import NOW
import test_demo_control_v2 as v2
from test_demo_auto_controller import Clock,FakeBroker
from demo_auto_controller import Controller,Position
from decimal import Decimal as D

BOOT={'schema_version':2,'sequence':0,'challenge':None,'ack':None}

class TransportTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock(); self.clock.now=0; self.server=FakeServer(self.clock)
    def transport(self,**kwargs):
        args=dict(endpoint='https://fixture.invalid',credential_provider=lambda:'fixture-only-noncredential',
                  endpoint_authorized=True,connection_factory=self.server.factory,total_timeout=.5)
        args.update(kwargs); return BoundedControlHTTP(**args)
    def test_default_never_connects(self):
        t=self.transport(endpoint_authorized=False)
        with self.assertRaisesRegex(TransportFailure,'NOT_AUTHORIZED'): t.post('/products/services/trading/control/sync',BOOT)
        self.assertEqual(self.server.connections,[])
    def test_exact_https_request_sanitized_fixture_capture(self):
        raw=self.transport().post('/products/services/trading/control/sync',BOOT)
        self.assertIn(b'BOOTSTRAPPED',raw)
        req=self.server.requests[0]
        self.assertEqual((req['method'],req['path']),('POST','/products/services/trading/control/sync'))
        self.assertNotIn('Cookie',req['header_names']); self.assertTrue(req['bearer_header_present'])
        self.assertTrue(self.server.connections[0].closed)
    def test_endpoint_path_payload_and_credentials_rejected_before_connection(self):
        for endpoint in ('http://fixture.invalid','https://fixture.invalid?token=x','https://a:b@fixture.invalid',
                         'https://fixture.invalid/extra','https://fixture.invalid:444'):
            with self.subTest(endpoint=endpoint),self.assertRaises(TransportFailure):
                self.transport(endpoint=endpoint).post('/products/services/trading/control/sync',BOOT)
        for body in (dict(BOOT,account_balance='private'),dict(BOOT,sequence=True)):
            with self.assertRaises(TransportFailure): self.transport().post('/products/services/trading/control/sync',body)
        with self.assertRaises(TransportFailure):
            self.transport(credential_provider=lambda:'not-a-credential\r\nInjected: yes').post('/products/services/trading/control/sync',BOOT)
        self.assertEqual(self.server.connections,[])
    def test_http_redirect_auth_and_server_errors_no_retry(self):
        for status in (301,401,409,429,503):
            self.server.status=status; before=len(self.server.connections)
            t=self.transport()
            with self.assertRaisesRegex(TransportFailure,'HTTP_STATUS_REJECTED'): t.post('/products/services/trading/control/sync',BOOT)
            self.assertEqual(len(self.server.connections),before+1)
            with self.assertRaisesRegex(TransportFailure,'UNRESOLVED'): t.post('/products/services/trading/control/sync',BOOT)
    def test_wrong_mime_encoding_size_and_invalid_json(self):
        for headers in ({'Content-Type':'text/html'},{'Content-Type':'application/json','Content-Encoding':'gzip'},
                        {'Content-Type':'application/json','Content-Length':'8193'},
                        {'Content-Type':'application/json','Content-Length':'1'}):
            self.server.headers=headers
            with self.assertRaises(TransportFailure): self.transport().post('/products/services/trading/control/sync',BOOT)
    def test_total_deadline_including_header_stall(self):
        self.server.stall=True; t=self.transport(total_timeout=.08); started=time.perf_counter()
        with self.assertRaisesRegex(TransportFailure,'TRANSPORT_TIMEOUT'): t.post('/products/services/trading/control/sync',BOOT)
        self.assertLess(time.perf_counter()-started,.5)
        self.assertEqual(len(self.server.requests),1)
        with self.assertRaises(TransportFailure): t.post('/products/services/trading/control/sync',BOOT)
        self.assertEqual(len(self.server.requests),1)
    def test_slow_drip_does_not_reset_timeout(self):
        self.server.delay=.02; t=self.transport(total_timeout=.09); started=time.perf_counter()
        with self.assertRaisesRegex(TransportFailure,'TRANSPORT_TIMEOUT'): t.post('/products/services/trading/control/sync',BOOT)
        self.assertLess(time.perf_counter()-started,.5)
    def test_slow_secure_provider_cannot_send_after_watchdog(self):
        release=Event()
        def provider(): release.wait(1); return 'fixture-only-noncredential'
        t=self.transport(total_timeout=.06,credential_provider=provider)
        with self.assertRaisesRegex(TransportFailure,'TRANSPORT_TIMEOUT'): t.post('/products/services/trading/control/sync',BOOT)
        release.set(); time.sleep(.03)
        self.assertEqual(self.server.connections,[])
    def test_private_error_is_redacted(self):
        def provider(): raise RuntimeError('private-secret-sentinel')
        with self.assertRaisesRegex(TransportFailure,'^TRANSPORT_FAILED$'):
            self.transport(credential_provider=provider).post('/products/services/trading/control/sync',BOOT)

class FinalAckTests(unittest.TestCase):
    setUp=v2.Tests.setUp
    make=v2.Tests.make
    sync=v2.Tests.sync
    def test_final_stop_ack_delivered_once_without_renewal(self):
        self.sync(); self.sync(2); self.client.stop('OFF_REQUESTED')
        self.port.modify=lambda p:p.update(effective_desired_state='OFF',run_status='ENDED',end_reason='UNSAFE_ACK')
        self.clock.now=3; self.broker.s=replace(self.broker.s,receipt_at=3)
        before=self.client.hard
        result=self.client.final_stop_ack(self.broker.s)
        self.assertTrue(result['final_stop_acknowledged']); self.assertEqual(result['actual_state'],'OFF')
        self.assertEqual(self.port.calls[-1][1]['ack']['actual_state'],'OFF')
        self.assertTrue(result['ended']); self.assertEqual(self.client.hard,before)
        count=len(self.port.calls); self.client.final_stop_ack(self.broker.s); self.assertEqual(len(self.port.calls),count)
    def test_final_protecting_ack_and_failure_retains_sltp(self):
        self.sync(); self.sync(2)
        self.broker.s=replace(self.broker.s,positions=(Position('private-fixture','BUY',D('80'),True,D('110')),),receipt_at=3)
        self.clock.now=3
        self.port.modify=lambda p:p.update(effective_desired_state='OFF',run_status='ENDED',end_reason='UNSAFE_ACK')
        result=self.client.final_stop_ack(self.broker.s)
        self.assertTrue(result['final_stop_acknowledged']); self.assertEqual(self.port.calls[-1][1]['ack']['actual_state'],'PROTECTING')
        self.assertEqual(self.broker.tightened,[])
    def test_final_response_cannot_restore_active(self):
        self.sync(); self.sync(2); self.clock.now=3; self.broker.s=replace(self.broker.s,receipt_at=3)
        result=self.client.final_stop_ack(self.broker.s)
        self.assertFalse(result['final_stop_acknowledged']); self.assertTrue(result['ended'])
        self.assertFalse(self.controller.on)
    def test_consumed_ambiguous_post_challenge_not_reused_for_final_ack(self):
        self.sync(); self.clock.now=2
        def fail(path,body): self.port.calls.append((path,body)); raise RuntimeError('private-error')
        self.port.post=fail; self.sync(2); count=len(self.port.calls)
        self.clock.now=3; self.client.final_stop_ack(replace(self.broker.s,receipt_at=3))
        self.assertEqual(len(self.port.calls),count)
    def test_expired_scope_prevents_final_report(self):
        self.sync(); self.clock.now=1800
        count=len(self.port.calls); result=self.client.final_stop_ack(replace(self.broker.s,receipt_at=1800))
        self.assertFalse(result['final_stop_acknowledged']); self.assertEqual(len(self.port.calls),count)

class RealClock:
    def __init__(self): self.start=time.perf_counter()
    @property
    def now(self): return time.perf_counter()-self.start
    def __call__(self): return self.now

class SchedulerTests(unittest.TestCase):
    def test_analysis_wait_does_not_starve_control_or_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock=RealClock(); broker=FakeBroker(clock); controller=Controller(broker,clock=clock)
            server=FakeServer(clock)
            port=BoundedControlHTTP('https://fixture.invalid',lambda:'fixture-only-noncredential',
                endpoint_authorized=True,connection_factory=server.factory,total_timeout=.5)
            scope=FixtureScope('fixture-scheduler','BTC',NOW+timedelta(seconds=1800),120)
            client=V2Client(port,V2Journal(tmp+'/v2.sqlite'),controller,scope=scope,clock=clock,
                now=lambda:NOW+timedelta(seconds=clock.now),clock_verified=True)
            def snapshot(): broker.s=replace(broker.s,receipt_at=clock()); return broker.snapshot()
            worker=CoordinationWorker(client,snapshot,sync_interval=1,heartbeat_interval=.02)
            producer_release=Event(); producer_started=Event()
            def canned_producer_wait(): producer_started.set(); producer_release.wait(10)
            producer=Thread(target=canned_producer_wait,daemon=True); producer.start()
            worker.start()
            try:
                self.assertTrue(producer_started.wait(.2))
                limit=time.perf_counter()+9
                while len(server.calls)<8 and time.perf_counter()<limit: time.sleep(.01)
                self.assertGreaterEqual(len(server.calls),8)
                self.assertTrue(producer.is_alive()); self.assertFalse(client.ended)
                self.assertGreater(client.soft,12); self.assertFalse(controller.on)
                self.assertEqual(broker.sent,[])
                self.assertTrue(worker.stop())
                self.assertTrue(client.final_acknowledged)
            finally: producer_release.set(); worker.stop(); producer.join(.2)
    def test_independent_heartbeat_stops_while_snapshot_waits(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock=Clock(); clock.now=0; broker=FakeBroker(clock); controller=Controller(broker,clock=clock)
            server=FakeServer(clock); scope=FixtureScope('fixture-blocked','BTC',NOW+timedelta(seconds=1800),120)
            client=V2Client(server,V2Journal(tmp+'/v2.sqlite'),controller,scope=scope,clock=clock,
                now=lambda:NOW+timedelta(seconds=clock.now),clock_verified=True)
            client.sync(broker.s); entered=Event(); release=Event()
            def snapshot(): entered.set(); release.wait(2); return replace(broker.s,receipt_at=clock())
            clock.now=2; worker=CoordinationWorker(client,snapshot,heartbeat_interval=.01).start()
            try:
                self.assertTrue(entered.wait(.3)); clock.now=6
                limit=time.perf_counter()+.5
                while not client.ended and time.perf_counter()<limit: time.sleep(.005)
                self.assertEqual(client.end_reason,'WORKER_LEASE_EXPIRED')
                self.assertFalse(controller.on); self.assertEqual(broker.sent,[])
            finally: release.set(); worker.stop()

if __name__=='__main__': unittest.main()
