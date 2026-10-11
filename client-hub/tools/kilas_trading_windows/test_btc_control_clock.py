"""Offline tests of real coordination parsing and receipt-bound clock math."""
import copy
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import test_demo_control_v2 as fixtures
from btc_server_clock import ServerClock, ServerClockError
from demo_control_v2 import V2Client, V2Journal, ControlScope
from demo_auto_controller import Controller, Position
from test_demo_auto_controller import FakeBroker, Clock, Policy


class ClockTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock(); self.clock.now=0
        self.server=ServerClock(clock=self.clock)

    def test_upper_charges_full_rtt_and_margin_not_pc_utc(self):
        self.clock.now=.4
        self.server.observe(0,.4,fixtures.NOW)
        self.assertGreaterEqual((self.server.upper_now()-fixtures.NOW).total_seconds(),.45)
        self.assertLess(self.server.deadline(fixtures.NOW+timedelta(seconds=5)),4.96)
        self.assertEqual(self.server.lower_now(),fixtures.NOW-timedelta(seconds=.05))

    def test_fast_heartbeat_not_model_latency_sets_current_time(self):
        self.server.observe(0,0,fixtures.NOW)
        for at in (2,4,6,8):
            self.clock.now=at+.01
            self.server.observe(at,at+.01,fixtures.NOW+timedelta(seconds=at))
        self.assertLess((self.server.upper_now()-fixtures.NOW).total_seconds(),8.1)

    def test_lower_bound_requires_definite_expiry(self):
        self.server.observe(0,0,fixtures.NOW)
        expiry=fixtures.NOW+timedelta(seconds=1)
        self.clock.now=.96
        self.assertGreater(self.server.upper_now(),expiry)
        self.assertLess(self.server.lower_now(),expiry)
        self.clock.now=1.1
        self.assertGreater(self.server.lower_now(),expiry)

    def test_stale_sample_cannot_grant_but_can_measure_fixed_expiry(self):
        self.server.observe(0,0,fixtures.NOW); self.clock.now=3
        self.assertFalse(self.server.fresh())
        with self.assertRaisesRegex(ServerClockError,'STALE'): self.server.upper_now()
        self.assertGreater(self.server.upper_now(require_fresh=False),fixtures.NOW+timedelta(seconds=3))

    def test_unavailable_and_slow_samples_reject(self):
        self.assertFalse(self.server.ready)
        with self.assertRaisesRegex(ServerClockError,'UNAVAILABLE'): self.server.upper_now()
        self.clock.now=1.6
        with self.assertRaisesRegex(ServerClockError,'TOO_SLOW'): self.server.observe(0,1.6,fixtures.NOW)
        self.assertFalse(self.server.ready)

    def test_regression_and_discontinuity_poison_clock(self):
        for timestamp in (fixtures.NOW-timedelta(seconds=1),fixtures.NOW+timedelta(seconds=20)):
            with self.subTest(timestamp=timestamp):
                self.clock.now=0; self.server=ServerClock(clock=self.clock)
                self.server.observe(0,0,fixtures.NOW); self.clock.now=2
                with self.assertRaisesRegex(ServerClockError,'DISCONTINUITY'):
                    self.server.observe(2,2,timestamp)
                self.assertFalse(self.server.fresh())

    def test_qpc_regression_poison_clock(self):
        self.clock.now=1; self.server.observe(1,1,fixtures.NOW)
        self.clock.now=0
        with self.assertRaisesRegex(ServerClockError,'DISCONTINUITY'): self.server.upper_now()

    def test_concurrent_send_intervals_and_late_parsing_are_valid(self):
        # Evidence began earlier, but server received it after the control call.
        self.clock.now=.2
        self.server.observe(.1,.2,fixtures.NOW+timedelta(seconds=.15))
        self.clock.now=.5
        self.server.upper_now()
        self.server.observe(0,.4,fixtures.NOW+timedelta(seconds=.3))
        self.assertTrue(self.server.fresh())

    def test_nonfinite_and_unaware_timestamp_reject(self):
        for sent,received,stamp in ((float('nan'),0,fixtures.NOW),(0,0,fixtures.NOW.replace(tzinfo=None))):
            with self.subTest(sent=sent):
                server=ServerClock(clock=self.clock)
                with self.assertRaises(ServerClockError): server.observe(sent,received,stamp)

    def test_overlapping_older_server_reply_is_discarded_without_poison(self):
        self.clock.now=.3
        newest=fixtures.NOW+timedelta(seconds=.2)
        self.server.observe(.1,.3,newest)
        before=self.server.upper_now()
        self.clock.now=.5
        # Evidence reached server first, then returned after the newer sync.
        result=self.server.observe(0,.5,fixtures.NOW+timedelta(seconds=.1))
        self.assertGreaterEqual(result,before)
        self.assertTrue(self.server.fresh())
        self.assertEqual(self.server._sample,(.1,.3,newest))

    def test_overlapping_late_parser_cannot_replace_newer_sample(self):
        self.clock.now=.5
        self.server.observe(.2,.5,fixtures.NOW+timedelta(seconds=.3))
        self.clock.now=.6
        self.server.observe(.1,.4,fixtures.NOW+timedelta(seconds=.2))
        self.assertTrue(self.server.fresh())
        self.assertEqual(self.server._sample[0],.2)

    def test_overlapping_but_impossible_timestamp_still_poisons(self):
        self.clock.now=.3
        self.server.observe(.1,.3,fixtures.NOW+timedelta(seconds=.2))
        self.clock.now=.5
        with self.assertRaisesRegex(ServerClockError,'DISCONTINUITY'):
            self.server.observe(0,.5,fixtures.NOW-timedelta(seconds=5))
        self.assertFalse(self.server.ready)


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.clock=Clock(); self.clock.now=0
        self.broker=FakeBroker(self.clock)
        self.policy=Policy('UNAPPROVED_FIXTURE',120,1,D('2'),1.5,D('2'),D('2000'),D('1'))
        self.controller=Controller(self.broker,fixtures.FakeModel(),self.policy,clock=self.clock)
        self.port=fixtures.Port(self.clock)
        self.journal=V2Journal(self.tmp.name+'/control.sqlite')
        self.scope=ControlScope('a'*32,'BTC',fixtures.NOW+timedelta(seconds=1800),120)
        self.server_clock=ServerClock(clock=self.clock)
        self.readiness={'ready':True,'entry_authorized':False,'wait_reason':'NONE'}
        self.wall=fixtures.NOW-timedelta(days=300)
        self.client=V2Client(self.port,self.journal,self.controller,scope=self.scope,
            clock=self.clock,now=lambda:self.wall,server_clock=self.server_clock,
            readiness=lambda:self.readiness.copy())

    def sync(self,at=0):
        self.clock.now=at; self.broker.s=replace(self.broker.s,receipt_at=at)
        return self.client.sync(self.broker.snapshot())

    def activate(self):
        self.assertFalse(self.sync()['ended'])
        self.assertFalse(self.sync(2)['ended'])
        self.readiness['entry_authorized']=True
        self.controller.start()
        self.assertTrue(self.controller.on)

    def test_clock_independent_of_absolute_pc_wall_and_backward_wall(self):
        self.assertFalse(self.sync()['ended'])
        self.wall-=timedelta(days=1)
        self.assertFalse(self.sync(2)['ended'])
        self.assertTrue(self.server_clock.ready)

    def test_ready_ack_precedes_grant_without_claiming_running(self):
        self.sync(); self.assertIsNone(self.client.last_ack_context)
        self.sync(2)
        ack=self.port.calls[-1][1]['ack']
        self.assertEqual((ack['policy_state'],ack['risk_allowed'],ack['wait_reason']),('READY',True,'NONE'))
        self.assertEqual(ack['actual_state'],'BLOCKED')
        self.assertFalse(self.controller.on)
        self.assertEqual(self.client.last_ack_context,('a'*32,1,'a'*32,'BTC','0.01'))

    def test_control_false_preserves_separately_eligible_controller(self):
        self.activate()
        self.assertEqual(self.client.heartbeat()['actual_state'],'RUNNING')
        self.assertFalse(self.client.projection['execution_authorized'])
        self.assertFalse(self.sync(4)['ended'])
        self.assertTrue(self.controller.on)
        self.assertEqual(self.port.calls[-1][1]['ack']['actual_state'],'RUNNING')

    def test_readiness_never_starts_controller_or_claims_running_alone(self):
        self.sync(); self.sync(2); self.readiness['entry_authorized']=True
        self.assertFalse(self.controller.on)
        self.assertEqual(self.client.ack()['actual_state'],'BLOCKED')

    def test_lost_authority_stops_immediately_preserving_protection(self):
        self.activate()
        self.broker.s=replace(self.broker.s,positions=(Position('synthetic','BUY',D('80'),True,D('110')),))
        self.client.snapshot=self.broker.s
        self.readiness['entry_authorized']=False
        result=self.client.heartbeat()
        self.assertFalse(self.controller.on)
        self.assertEqual(result['actual_state'],'PROTECTING')
        self.assertEqual(self.broker.sent,[])

    def test_off_response_revokes_grant_and_ack_context(self):
        self.activate()
        self.port.modify=lambda p:p.update(desired_state='OFF',effective_desired_state='OFF',revision=2,
            command_id='b'*32,run_seconds=0,run_expires_at=None,run_started_at=None,
            worker_lease_expires_at=None,run_status='ENDED',end_reason='OFF_REQUESTED')
        result=self.sync(4)
        self.assertEqual(result['end_reason'],'OFF_REQUESTED')
        self.assertIsNone(self.client.last_ack_context)
        self.assertFalse(self.controller.on)

    def test_invalid_readiness_fails_closed(self):
        self.activate(); self.readiness['entry_authorized']='true'
        self.client.heartbeat()
        self.assertFalse(self.controller.on)
        self.assertEqual(self.client.ack()['wait_reason'],'RISK_BLOCKED')

    def test_stale_sample_revokes_authority_without_renewing_run(self):
        self.activate(); hard=self.client.hard
        self.clock.now=5
        self.client.heartbeat()
        self.assertFalse(self.controller.on)
        self.assertEqual(self.client.hard,hard)

    def test_fixed_hard_deadline_cannot_slide_with_samples(self):
        self.sync(); initial=self.client.hard
        for at in range(2,30,2): self.assertFalse(self.sync(at)['ended'])
        self.assertLessEqual(self.client.hard,initial)

    def test_late_response_cannot_renew_expired_lease(self):
        self.sync(); self.port.delay=4
        result=self.sync(2)
        self.assertEqual(result['end_reason'],'WORKER_LEASE_EXPIRED')

    def test_regressing_server_sample_is_rejected(self):
        self.sync()
        self.port.modify=lambda p:p.update(received_at=fixtures.stamp(fixtures.NOW-timedelta(seconds=1)))
        self.assertTrue(self.sync(2)['ended'])
        self.assertFalse(self.controller.on)

    def test_scope_expiry_uses_server_receipt_time(self):
        self.client.scope=replace(self.scope,expires_at=fixtures.NOW)
        result=self.sync()
        self.assertTrue(result['ended'])
        self.assertFalse(self.controller.on)

    def test_projection_true_remains_invalid_even_when_provider_ready(self):
        self.port.modify=lambda p:p.update(execution_authorized=True)
        self.assertTrue(self.sync()['ended'])
        self.assertFalse(self.controller.on)

    def test_unvalidated_response_does_not_seed_clock(self):
        self.port.modify=lambda p:p.update(secret='must-not-appear')
        self.assertTrue(self.sync()['ended'])
        self.assertFalse(self.server_clock.ready)

    def test_timeout_stops_and_does_not_replay_consumed_control_nonce(self):
        self.activate()
        def timeout(path,body):
            raise TimeoutError('synthetic timeout')
        self.port.post=timeout
        result=self.sync(4)
        self.assertTrue(result['ended'])
        self.assertFalse(self.controller.on)
        self.assertIsNone(self.client.challenge)
        self.assertIsNone(self.client.last_ack_context)

    def test_restart_cannot_reactivate_previous_on(self):
        self.sync(); self.sync(2)
        self.client=V2Client(self.port,self.journal,self.controller,scope=self.scope,
            clock=self.clock,now=lambda:self.wall,server_clock=ServerClock(clock=self.clock),
            readiness=lambda:self.readiness.copy())
        self.assertEqual(self.sync(4)['end_reason'],'WORKER_RESTARTED')
        self.assertFalse(self.controller.on)

    def test_final_stop_ack_supports_server_clock_without_utc_pc_proof(self):
        self.sync(); self.sync(2)
        self.client.stop('OFF_REQUESTED'); self.clock.now=4
        self.port.modify=lambda p:p.update(effective_desired_state='OFF',run_status='ENDED',end_reason='OFF_REQUESTED')
        snapshot=replace(self.broker.s,receipt_at=4)
        result=self.client.final_stop_ack(snapshot)
        self.assertTrue(result['final_stop_acknowledged'])
        self.assertFalse(self.controller.on)
        self.assertEqual(self.port.calls[-1][1]['ack']['actual_state'],'OFF')


if __name__=='__main__': unittest.main()
