"""Actual v2 client/HTTP/parser/MT5 adapter stack against offline collaborators.

No native MT5 import, socket, credential store, model provider or live order.
The injected SDK records simulated broker calls; HTTP connections stay in memory.
"""
import copy
import inspect
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from btc_evidence_capture import BTCMarketCapture
from btc_integration_client import BTCIntegrationClient, DecisionJournal
from btc_integration_protocol import ANALYSIS_PATH, EVIDENCE_PATH, decision_id
from btc_server_clock import ServerClock
from demo_auto_controller import Blocked, Controller
from demo_control_v2 import PATH, FixtureScope, V2Client, V2Journal, strict_json
from demo_worker_runtime import BoundedControlHTTP
from mt5_demo_adapter import Journal, MT5DemoAdapter
from test_mt5_demo_adapter import FakeSDK, policy
import test_demo_control_v2 as control_fixture


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def advance(self, seconds): self.now += seconds
    def utc(self): return control_fixture.NOW + timedelta(seconds=self.now)
    def ns(self): return 1_000_000_000 + round(self.now * 1_000_000_000)


class CaptureSDK(FakeSDK):
    TIMEFRAME_M1 = 1

    def __init__(self, clock):
        super().__init__()
        self.clock = clock
        self.frozen = False
        self.tick.time = int(control_fixture.NOW.timestamp()) + 1
        self.tick.time_msc = self.tick.time * 1000
        self.rate_reads = 0

    def symbol_info_tick(self, symbol):
        if not self.frozen:
            self.tick.time_msc += 1
            self.tick.time = self.tick.time_msc // 1000
        return self.tick

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        if (symbol, timeframe, start, count) != ('BTCUSD', self.TIMEFRAME_M1, 1, 12):
            raise AssertionError('Unexpected simulated rates request')
        self.rate_reads += 1
        self.clock.advance(.02)
        last = self.tick.time // 60 * 60 - 60
        return [dict(time=last - (11 - i) * 60, open=1000., high=1001., low=999., close=1000.)
                for i in range(12)]


class MemoryResponse:
    status = 200

    def __init__(self, body):
        self.data = json.dumps(body, separators=(',', ':'), allow_nan=False).encode()
        self.offset = 0

    def getheader(self, name, default=None):
        return {'Content-Type': 'application/json', 'Content-Length': str(len(self.data))}.get(name, default)

    def read(self, count):
        part = self.data[self.offset:self.offset + count]
        self.offset += len(part)
        return part


class MemoryConnection:
    sock = None

    def __init__(self, server, **kwargs):
        self.server = server
        self.timeout = kwargs['timeout']
        self.path = self.body = None

    def connect(self): pass
    def close(self): pass

    def request(self, method, path, *, body, headers):
        if method != 'POST' or headers['Content-Type'] != 'application/json; charset=utf-8':
            raise AssertionError('Unexpected simulated HTTP request')
        # Never retain bearer headers, including the synthetic test value.
        self.path, self.body = path, strict_json(body)

    def getresponse(self):
        return MemoryResponse(self.server.handle(self.path, self.body))


class MemoryServer:
    def __init__(self, clock):
        self.clock = clock
        self.control = control_fixture.Port(clock)
        self.calls = []
        self.accepted_sequence = 0
        self.previous_tick = None
        self.news = True
        self.model_calls = 0
        self.model_cache = {}
        self.analysis_started = threading.Event()
        self.analysis_release = None
        self.analysis_mutation = None
        self.authorization_seconds = 2.
        self.execution_authorized = True
        self.off = False
        self.drop_next_evidence_response = False

    def factory(self, host, **kwargs):
        if host != 'offline.invalid': raise AssertionError('Unexpected host')
        return MemoryConnection(self, **kwargs)

    def stamp(self, seconds=0):
        return control_fixture.stamp(self.clock.utc() + timedelta(seconds=seconds))

    def handle(self, path, body):
        self.calls.append((path, copy.deepcopy(body)))
        if path == PATH:
            response = self.control.response(body)
            if self.off:
                response.update(desired_state='OFF', effective_desired_state='OFF',
                    actual_state='OFF', revision=2, command_id='b' * 32,
                    issued_at=self.stamp(), command_expires_at=self.stamp(),
                    run_seconds=0, run_expires_at=None, run_started_at=None,
                    worker_lease_expires_at=None, run_status='ENDED', end_reason='OFF_REQUESTED')
            return response
        if path == EVIDENCE_PATH:
            bootstrap = body['challenge'] is None
            response = dict(schema_version=2,
                outcome='CAPTURE_CHALLENGE_ISSUED' if bootstrap else 'EVIDENCE_ACCEPTED',
                sequence=self.accepted_sequence if bootstrap else body['sequence'],
                challenge=f'{100 + self.accepted_sequence + (0 if bootstrap else 1):064x}',
                challenge_expires_at=self.stamp(5), received_at=self.stamp(), execution_authorized=False)
            if not bootstrap:
                tick = body['market']['tick']['time_msc']
                verified = self.previous_tick is not None and tick > self.previous_tick
                self.previous_tick = tick
                self.accepted_sequence = body['sequence']
                response.update(session_id=body['session_id'],
                    evidence={'market_id': f'{self.accepted_sequence:032x}',
                              'spec_id': '3' * 32, 'news_id': '4' * 32 if self.news else None},
                    coverage='BTC_EDITORIAL_ONLY', risk_review='UNREVIEWED',
                    tick_liveness='VERIFIED' if verified else 'UNCONFIRMED')
            if self.drop_next_evidence_response:
                self.drop_next_evidence_response = False
                raise TimeoutError('Simulated response loss after server acceptance')
            return response
        if path != ANALYSIS_PATH: raise AssertionError('Unexpected path')
        self.analysis_started.set()
        if self.analysis_release is not None and not self.analysis_release.wait(2):
            raise TimeoutError('Offline analysis release missing')
        identifier = decision_id(body)
        if identifier not in self.model_cache:
            self.model_calls += 1
            self.model_cache[identifier] = dict(decision='BUY', reason='Offline contract test',
                invalidation='Offline invalidation', stop_cents=90000, target_cents=120000, news_risk='LOW')
        response = dict(schema_version=2, outcome='PROPOSAL_READY', instrument='BTC',
            model='gpt-6.1-sol', reasoning='medium', decision=copy.deepcopy(self.model_cache[identifier]),
            news_coverage='BTC_EDITORIAL_ONLY', risk_state='PASSED',
            execution_authorized=self.execution_authorized, checked_at=self.stamp(),
            session_id=body['session_id'], operation_key=body['operation_key'], revision=body['revision'],
            command_id=body['command_id'], evidence=copy.deepcopy(body['evidence']), decision_id=identifier,
            authorization_expires_at=self.stamp(self.authorization_seconds) if self.execution_authorized else None)
        if self.analysis_mutation: self.analysis_mutation(response)
        return response


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        self.server = MemoryServer(self.clock)
        self.sdk = CaptureSDK(self.clock)
        self.adapter = MT5DemoAdapter(self.sdk, Journal(Path(self.tmp.name) / 'broker.sqlite'),
            policy(), execute=True, clock=self.clock, wall=self.clock)
        for _ in range(3): self.adapter.snapshot()
        self.controller = Controller(self.adapter, None, policy().controller, clock=self.clock)
        self.transport = BoundedControlHTTP('https://offline.invalid', lambda: 'e' * 64,
            endpoint_authorized=True, connection_factory=self.server.factory, clock=self.clock)
        self.server_clock = ServerClock(clock=self.clock)
        self.control = V2Client(self.transport, V2Journal(Path(self.tmp.name) / 'control.sqlite'),
            self.controller, scope=FixtureScope('f' * 32, 'BTC', control_fixture.NOW + timedelta(seconds=1800), 120),
            clock=self.clock, now=self.clock.utc, server_clock=self.server_clock)
        self.collector = BTCMarketCapture(self.adapter,
            lambda snapshot: dict(daily_loss_remaining_cents=200, strategy_verified=True,
                                  cooldown_clear=True, loss_streak_clear=True),
            cost_bound_cents=0, policy_version='d' * 64, clock_ns=self.clock.ns, now=self.clock.utc)
        self.decision_file = Path(self.tmp.name) / 'decisions.sqlite'
        self.client = BTCIntegrationClient(self.control, self.transport, self.collector,
            DecisionJournal(self.decision_file), readiness_provider=lambda: True,
            activation_enabled=True, clock=self.clock)

    def sync(self, advance=0):
        self.clock.advance(advance)
        return self.control.sync(self.adapter.snapshot())

    def prepare(self):
        self.assertFalse(self.sync()['ended'])
        self.assertFalse(self.sync(2.1)['ended'])
        self.assertTrue(self.client.active())
        self.assertIsNotNone(self.control.last_ack_context)
        self.assertEqual(self.client.capture_once()['outcome'], 'CAPTURE_CHALLENGE_ISSUED')
        self.assertEqual(self.client.capture_once()['tick_liveness'], 'UNCONFIRMED')
        self.assertEqual(self.client.capture_once()['tick_liveness'], 'VERIFIED')

    def decision_count(self):
        db = sqlite3.connect(self.decision_file)
        try:
            return db.execute('SELECT count(*) FROM btc_decisions').fetchone()[0]
        finally:
            db.close()

    def inference_thread(self):
        self.server.analysis_release = threading.Event()
        results = []
        thread = threading.Thread(target=lambda: results.append(self.client.analyze_once('offline-operation-123')))
        thread.start()
        def release_and_join():
            self.server.analysis_release.set()
            thread.join(2)
        self.addCleanup(release_and_join)
        self.assertTrue(self.server.analysis_started.wait(1))
        return thread, results

    def test_actual_transport_stack_enters_once_preserves_sltp_and_consumes_decision(self):
        self.prepare()
        response = self.client.analyze_once('offline-operation-123')
        self.assertIsNotNone(response, (self.client.status(), self.controller.status()))
        self.assertEqual(len(self.sdk.checks), 1)
        self.assertEqual(len(self.sdk.sends), 1)
        self.assertEqual((self.sdk.positions[0].sl, self.sdk.positions[0].tp), (900., 1200.))
        self.assertEqual(self.decision_count(), 1)
        self.assertEqual(self.server.model_calls, 1)
        self.assertFalse(self.controller.on)
        self.assertFalse(self.client.status()['execution_authorized'])
        self.assertEqual({path for path, _ in self.server.calls}, {PATH, EVIDENCE_PATH, ANALYSIS_PATH})
        acks = [body['ack'] for path, body in self.server.calls if path == PATH and body['ack']]
        self.assertEqual(acks[0]['actual_state'], 'BLOCKED')
        self.assertTrue(acks[0]['risk_allowed'])
        self.assertEqual(acks[0]['policy_state'], 'READY')

    def test_cached_decision_consumption_survives_new_journal_instance(self):
        self.prepare()
        self.assertIsNotNone(self.client.analyze_once('offline-operation-123'))
        self.sdk.exit(loss=0)
        self.adapter.snapshot()
        self.client.decisions = DecisionJournal(self.decision_file)
        self.client.analyze_once('offline-operation-123')
        self.assertEqual((len(self.sdk.sends), self.decision_count(), self.server.model_calls), (1, 1, 1))
        request = next(body for path, body in self.server.calls if path == ANALYSIS_PATH)
        with self.assertRaisesRegex(Blocked, 'DECISION_ALREADY_CONSUMED'):
            DecisionJournal(self.decision_file).consume(request['session_id'], decision_id(request), request)

    def test_default_activation_flag_blocks_even_valid_server_true(self):
        self.assertIs(inspect.signature(BTCIntegrationClient).parameters['activation_enabled'].default, False)
        self.client.activation_enabled = False
        self.prepare()
        self.client.analyze_once('offline-operation-123')
        self.assertEqual((self.sdk.sends, self.sdk.checks, self.decision_count()), ([], [], 0))

    def test_server_false_result_does_not_grant_entry(self):
        self.prepare(); self.server.execution_authorized = False
        response = self.client.analyze_once('offline-operation-123')
        self.assertIsNotNone(response)
        self.assertIsNone(self.client.failure)
        self.assertEqual(self.client.last_outcome, 'PROPOSAL_READY')
        self.assertEqual(self.sdk.sends, [])

    def test_first_tick_never_requests_analysis(self):
        self.sync(); self.sync(2.1); self.client.capture_once()
        self.client.capture_once()
        self.client.analyze_once('offline-operation-123')
        self.assertEqual(self.server.model_calls, 0)
        self.assertEqual(self.sdk.sends, [])

    def test_missing_news_with_advancing_ticks_never_requests_analysis(self):
        self.server.news = False
        self.prepare()
        self.client.analyze_once('offline-operation-123')
        self.assertEqual(self.server.model_calls, 0)
        self.assertEqual(self.sdk.sends, [])

    def test_frozen_ticks_cannot_establish_server_liveness(self):
        self.sync(); self.sync(2.1); self.client.capture_once()
        self.sdk.frozen = True
        self.assertEqual(self.client.capture_once()['tick_liveness'], 'UNCONFIRMED')
        self.assertEqual(self.client.capture_once()['tick_liveness'], 'UNCONFIRMED')
        self.client.analyze_once('offline-operation-123')
        self.assertEqual((self.server.model_calls, self.sdk.sends), (0, []))

    def test_off_during_analysis_vetoes_late_result(self):
        self.prepare(); thread, results = self.inference_thread()
        self.server.off = True
        stopped = self.sync(1.1)
        self.assertTrue(stopped['ended'])
        self.assertEqual(stopped['end_reason'], 'OFF_REQUESTED')
        self.server.analysis_release.set(); thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [None])
        self.assertEqual((self.sdk.checks, self.sdk.sends, self.decision_count()), ([], [], 0))

    def test_fast_sync_and_capture_continue_during_slow_analysis(self):
        self.prepare(); thread, results = self.inference_thread()
        original_hard = self.control.hard
        self.assertFalse(self.sync(2.)['ended'])
        self.assertEqual(self.client.capture_once()['tick_liveness'], 'VERIFIED')
        self.assertFalse(self.sync(2.)['ended'])
        self.assertEqual(self.client.capture_once()['tick_liveness'], 'VERIFIED')
        self.assertLessEqual(self.control.hard, original_hard)
        self.server.authorization_seconds = 1.
        self.server.analysis_release.set(); thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertIsNotNone(results[0], (self.client.status(), self.controller.status()))
        self.assertEqual(len(self.sdk.sends), 1)
        self.assertEqual(self.client.sequence, 4)

    def test_analysis_timeout_ends_entries_but_independent_sync_lane_works(self):
        self.transport.analysis_timeout = .05
        self.prepare(); thread, results = self.inference_thread()
        thread.join(.3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [None])
        self.assertTrue(self.transport.path_unresolved(ANALYSIS_PATH))
        self.assertFalse(self.transport.path_unresolved(PATH))
        self.assertFalse(self.sync(1.1)['ended'])
        self.server.analysis_release.set()
        self.assertEqual((self.sdk.sends, self.decision_count()), ([], 0))

    def test_authorization_cannot_extend_known_capture_or_control_bounds(self):
        self.prepare()
        self.server.authorization_seconds = 20.
        self.client.analyze_once('offline-operation-123')
        self.assertEqual((self.sdk.checks, self.sdk.sends, self.decision_count()), ([], [], 0))

    def test_future_analysis_check_time_cannot_replace_fast_server_clock(self):
        self.prepare()
        self.server.analysis_mutation = lambda r: r.update(checked_at=self.server.stamp(1))
        self.client.analyze_once('offline-operation-123')
        self.assertEqual((self.sdk.checks, self.sdk.sends, self.decision_count()), ([], [], 0))

    def test_expired_authorization_cannot_start_controller(self):
        self.prepare()
        self.server.authorization_seconds = .01  # Below conservative scheduling margin.
        self.client.analyze_once('offline-operation-123')
        self.assertEqual((self.sdk.checks, self.sdk.sends, self.decision_count()), ([], [], 0))

    def test_lease_expiry_during_analysis_cannot_be_revived(self):
        self.prepare(); thread, results = self.inference_thread()
        self.clock.advance(6.1); self.control.heartbeat()
        self.server.analysis_release.set(); thread.join(1)
        self.assertEqual(results, [None])
        self.assertTrue(self.control.ended)
        self.assertEqual(self.control.end_reason, 'WORKER_LEASE_EXPIRED')
        self.assertEqual(self.sdk.sends, [])

    def test_mismatched_echoed_model_evidence_rejects_before_consumption(self):
        self.prepare()
        self.server.analysis_mutation = lambda r: r['evidence'].update(market_id='9' * 32)
        self.client.analyze_once('offline-operation-123')
        self.assertEqual((self.sdk.sends, self.decision_count()), ([], 0))

    def test_risk_excess_sltp_never_reaches_broker_check(self):
        self.prepare()
        self.server.analysis_mutation = lambda r: r['decision'].update(stop_cents=70000)
        self.client.analyze_once('offline-operation-123')
        self.assertEqual((self.sdk.checks, self.sdk.sends), ([], []))
        self.assertEqual(self.decision_count(), 1)

    def test_live_notional_cap_overrides_server_true(self):
        self.prepare()
        self.sdk.tick.bid = 299999.9; self.sdk.tick.ask = 300000.
        self.server.analysis_mutation = lambda r: r['decision'].update(stop_cents=29990000, target_cents=30020000)
        self.client.analyze_once('offline-operation-123')
        self.assertEqual((self.sdk.checks, self.sdk.sends), ([], []))

    def test_broker_contract_change_after_analysis_evidence_blocks_entry(self):
        self.prepare()
        self.sdk.info.trade_contract_size = 2
        self.client.analyze_once('offline-operation-123')
        self.assertEqual((self.sdk.checks, self.sdk.sends), ([], []))

    def test_readiness_revocation_during_order_check_prevents_send(self):
        self.prepare()
        original = self.sdk.order_check
        def changed(request):
            result = original(request)
            self.client.readiness_provider = lambda: False
            return result
        self.sdk.order_check = changed
        self.client.analyze_once('offline-operation-123')
        self.assertEqual((len(self.sdk.checks), self.sdk.sends, self.decision_count()), (1, [], 1))

    def test_new_accepted_risk_deterioration_during_local_quote_prevents_send(self):
        self.prepare()
        original = self.sdk.order_calc_profit
        accepted = []
        def changed(*args):
            result = original(*args)
            if not accepted:
                self.collector.risk_provider = lambda _: dict(daily_loss_remaining_cents=0,
                    strategy_verified=True, cooldown_clear=True, loss_streak_clear=True)
                accepted.append(self.client.capture_once())
            return result
        self.sdk.order_calc_profit = changed
        self.client.analyze_once('offline-operation-123')
        self.assertEqual(accepted[0]['outcome'], 'EVIDENCE_ACCEPTED')
        self.assertEqual((self.sdk.checks, self.sdk.sends, self.decision_count()), ([], [], 1))

    def test_unknown_costs_override_even_server_true(self):
        self.collector.cost_bound_cents = None
        self.prepare()
        self.client.analyze_once('offline-operation-123')
        self.assertIsNone(self.client.latest['spec']['cost_bound_cents'])
        self.assertEqual((self.sdk.checks, self.sdk.sends), ([], []))

    def test_hard_run_expiry_during_analysis_prevents_entry(self):
        expiry = control_fixture.stamp(control_fixture.NOW + timedelta(seconds=3))
        self.server.control.modify = lambda p: p.update(run_seconds=3, run_expires_at=expiry,
            command_expires_at=expiry, worker_lease_expires_at=expiry)
        self.prepare(); thread, results = self.inference_thread()
        self.clock.advance(1); self.control.heartbeat()
        self.server.analysis_release.set(); thread.join(1)
        self.assertEqual(results, [None])
        self.assertEqual(self.control.end_reason, 'RUN_DEADLINE')
        self.assertEqual(self.sdk.sends, [])

    def test_off_after_entry_keeps_existing_broker_sltp(self):
        self.prepare()
        self.assertIsNotNone(self.client.analyze_once('offline-operation-123'))
        self.server.off = True
        status = self.sync(1.1)
        self.assertEqual(status['end_reason'], 'OFF_REQUESTED')
        self.assertTrue(status['protection_active'])
        self.assertEqual((self.sdk.positions[0].sl, self.sdk.positions[0].tp), (900., 1200.))
        self.assertEqual(len(self.sdk.sends), 1)

    def test_changed_evidence_cannot_reuse_operation_key(self):
        self.prepare()
        self.server.execution_authorized = False
        self.assertIsNotNone(self.client.analyze_once('offline-operation-123'))
        self.assertEqual(self.client.capture_once()['outcome'], 'EVIDENCE_ACCEPTED')
        self.assertIsNone(self.client.analyze_once('offline-operation-123'))
        self.assertEqual((self.server.model_calls, self.sdk.sends), (1, []))

    def test_model_wait_does_not_poison_later_current_proposal(self):
        self.prepare()
        def wait(response):
            response.update(outcome='MODEL_WAIT', risk_state='BLOCKED', execution_authorized=False,
                            authorization_expires_at=None)
            response['decision'].update(decision='WAIT', stop_cents=None, target_cents=None, news_risk='UNKNOWN')
        self.server.analysis_mutation = wait
        self.assertEqual(self.client.analyze_once('offline-operation-123')['outcome'], 'MODEL_WAIT')
        self.assertIsNone(self.client.failure)
        self.assertEqual(self.sdk.sends, [])
        self.server.analysis_mutation = None
        self.assertIsNotNone(self.client.analyze_once('offline-operation-456'))
        self.assertEqual((self.server.model_calls, len(self.sdk.sends)), (2, 1))

    def advance_with_sync(self, count):
        for _ in range(count):
            self.assertFalse(self.sync(2.)['ended'])

    def test_expired_present_nonce_bootstraps_current_sequence_without_run_renewal(self):
        self.prepare()
        hard, prior_sequence = self.control.hard, self.client.sequence
        self.advance_with_sync(3)
        response = self.client.capture_once()
        self.assertEqual((response['outcome'], response['sequence']), ('CAPTURE_CHALLENGE_ISSUED', prior_sequence))
        self.assertIsNone(self.client.latest)
        self.assertEqual(self.client.capture_once()['sequence'], prior_sequence + 1)
        self.assertLessEqual(self.control.hard, hard)
        self.assertEqual(self.sdk.sends, [])

    def test_lost_normal_response_recovers_advanced_sequence_and_recaptures(self):
        self.prepare()
        hard = self.control.hard
        self.server.drop_next_evidence_response = True
        self.assertIsNone(self.client.capture_once())
        self.assertEqual((self.client.sequence, self.server.accepted_sequence), (2, 3))
        self.assertTrue(self.transport.path_unresolved(EVIDENCE_PATH))
        evidence_posts = len([1 for path, _ in self.server.calls if path == EVIDENCE_PATH])
        self.assertIsNone(self.client.capture_once())
        self.assertEqual(len([1 for path, _ in self.server.calls if path == EVIDENCE_PATH]), evidence_posts)
        self.advance_with_sync(6)
        response = self.client.capture_once()
        self.assertEqual((response['outcome'], response['sequence']), ('CAPTURE_CHALLENGE_ISSUED', 3))
        self.assertFalse(self.transport.path_unresolved(EVIDENCE_PATH))
        self.assertIsNone(self.client.latest)
        self.assertEqual(self.client.capture_once()['sequence'], 4)
        captures = [body for path, body in self.server.calls if path == EVIDENCE_PATH and body['market'] is not None]
        self.assertEqual([body['sequence'] for body in captures], [1, 2, 3, 4])
        self.assertEqual(len({body['challenge'] for body in captures}), 4)
        self.assertLessEqual(self.control.hard, hard)
        self.assertEqual(self.sdk.sends, [])

    def test_lost_bootstrap_recovers_without_old_data_or_deadline_extension(self):
        self.sync(); self.sync(2.1)
        hard = self.control.hard
        self.server.drop_next_evidence_response = True
        self.assertIsNone(self.client.capture_once())
        self.assertEqual(self.sdk.rate_reads, 0)
        self.assertIsNone(self.client.capture_once())
        self.advance_with_sync(3)
        response = self.client.capture_once()
        self.assertEqual((response['outcome'], response['sequence']), ('CAPTURE_CHALLENGE_ISSUED', 0))
        self.assertEqual(self.client.capture_once()['sequence'], 1)
        self.assertEqual(self.sdk.rate_reads, 1)
        self.assertLessEqual(self.control.hard, hard)

    def test_missing_news_rechecks_with_new_capture_then_allows_proposal(self):
        self.server.news = False
        self.prepare()
        self.assertIsNone(self.client.analyze_once('offline-operation-123'))
        self.assertEqual(self.server.model_calls, 0)
        self.assertIsNone(self.client.failure)
        self.server.news = True
        self.assertEqual(self.client.capture_once()['outcome'], 'EVIDENCE_ACCEPTED')
        self.assertIsNotNone(self.client.analyze_once('offline-operation-456'))
        self.assertEqual((self.server.model_calls, len(self.sdk.sends)), (1, 1))


if __name__ == '__main__':
    unittest.main()
