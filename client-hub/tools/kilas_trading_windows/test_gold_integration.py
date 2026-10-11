"""Gold wire/producer/control/proposal regressions; fake SDK/HTTP only."""
import copy
import json
import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

from btc_evidence_capture import BTCMarketCapture
from btc_integration_client import BTCIntegrationClient, DecisionJournal, build_gold_proposal_worker
from btc_integration_protocol import (validate_evidence_request,validate_analysis_request,
    parse_analysis_response,contract_hash,decision_id,BtcRejected)
from btc_server_clock import ServerClock
from demo_auto_controller import Controller,Blocked
from demo_control_v2 import V2Client,V2Journal,FixtureScope,PATH
from demo_integration_instruments import wire_profile
from demo_worker_runtime import BoundedControlHTTP,GOLD_EVIDENCE_PATH,GOLD_ANALYSIS_PATH,TransportFailure
from mt5_demo_adapter import MT5DemoAdapter,Journal
from test_btc_integration_client import Clock,CaptureSDK,MemoryServer,ANALYSIS_PATH,EVIDENCE_PATH
from test_mt5_demo_adapter import policy
import test_demo_control_v2 as cf


class GoldSDK(CaptureSDK):
    def __init__(self,clock):
        super().__init__(clock)
        self.info.name='GOLD'; self.info.trade_contract_size=100
        self.tick.bid=4194.6; self.tick.ask=4195.59
    def copy_rates_from_pos(self,symbol,timeframe,start,count):
        assert (symbol,timeframe,start,count)==('GOLD',self.TIMEFRAME_M1,1,12)
        self.rate_reads+=1; self.clock.advance(.02)
        last=self.tick.time//60*60-60
        return [dict(time=last-(11-i)*60,open=4195.,high=4196.,low=4194.,close=4195.) for i in range(12)]


class GoldServer(MemoryServer):
    def __init__(self,clock):
        super().__init__(clock); self.execution_authorized=False
        self.review='SERVER_REVIEWED'
    def handle(self,path,body):
        if path==PATH:
            response=super().handle(path,body); response['instrument']='GOLD'; return response
        assert path in (GOLD_EVIDENCE_PATH,GOLD_ANALYSIS_PATH)
        original=copy.deepcopy(body)
        if path==GOLD_ANALYSIS_PATH:
            body=copy.deepcopy(body); body['instrument']='BTC'
        response=super().handle(EVIDENCE_PATH if path==GOLD_EVIDENCE_PATH else ANALYSIS_PATH,body)
        self.calls[-1]=(path,original)
        if path==GOLD_EVIDENCE_PATH and 'coverage' in response:
            response.update(coverage='GOLD_MACRO_CALENDAR',risk_review=self.review)
        if path==GOLD_ANALYSIS_PATH:
            response.update(instrument='GOLD',news_coverage='GOLD_MACRO_CALENDAR',
                            decision_id=decision_id(original,instrument='GOLD'))
        return response


class GoldIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.clock=Clock(); self.sdk=GoldSDK(self.clock); self.server=GoldServer(self.clock)
        self.a=MT5DemoAdapter(self.sdk,Journal(Path(self.tmp.name)/'broker.sqlite'),policy(),
                              instrument='GOLD',clock=self.clock,wall=self.clock)
        for _ in range(3):self.a.snapshot()
        self.ctrl=Controller(self.a,None,policy().controller,clock=self.clock)
        self.http=BoundedControlHTTP('https://offline.invalid',lambda:'e'*64,endpoint_authorized=True,
                                    connection_factory=self.server.factory,clock=self.clock)
        self.control=V2Client(self.http,V2Journal(Path(self.tmp.name)/'control.sqlite'),self.ctrl,
            scope=FixtureScope('f'*32,'GOLD',cf.NOW+timedelta(seconds=1800),120),instrument='GOLD',
            clock=self.clock,now=self.clock.utc,server_clock=ServerClock(clock=self.clock))
        self.capture=BTCMarketCapture(self.a,lambda _:dict(daily_loss_remaining_cents=200,
            strategy_verified=True,cooldown_clear=True,loss_streak_clear=True),instrument='GOLD',
            cost_bound_cents=0,policy_version='d'*64,clock_ns=self.clock.ns,now=self.clock.utc)
        self.client=BTCIntegrationClient(self.control,self.http,self.capture,
            DecisionJournal(Path(self.tmp.name)/'decision.sqlite'),readiness_provider=lambda:True,
            instrument='GOLD',clock=self.clock)
    def prepare(self):
        self.assertFalse(self.control.sync(self.a.snapshot())['ended'])
        self.clock.advance(2.1)
        self.assertFalse(self.control.sync(self.a.snapshot())['ended'])
        self.assertEqual(self.client.capture_once()['outcome'],'CAPTURE_CHALLENGE_ISSUED')
        self.assertEqual(self.client.capture_once()['tick_liveness'],'UNCONFIRMED')
        self.assertEqual(self.client.capture_once()['tick_liveness'],'VERIFIED')
    def tearDown(self):
        self.assertEqual(self.sdk.checks,[]); self.assertEqual(self.sdk.sends,[])
        self.assertFalse(self.a.execute); self.assertFalse(self.ctrl.on)
    def test_actual_gold_contract_capture_and_ack_without_entries(self):
        self.prepare()
        evidence=self.server.calls[-1][1]
        self.assertEqual(evidence['market']['symbol'],'GOLD')
        self.assertEqual(evidence['spec']['contract_size'],'100')
        self.assertEqual(evidence['risk']['broker_contract_sha256'],contract_hash(evidence['spec'],instrument='GOLD'))
        self.assertIsNone(evidence['market']['clock']); self.assertIsNone(evidence['market']['clock_profile'])
        self.assertEqual(self.control.ack()['instrument'],'GOLD')
        self.assertFalse(self.control.entry_eligible()); self.assertFalse(self.client.authority_valid())
    def test_current_minimum_gold_notional_blocks_before_analysis_post(self):
        self.prepare(); before=len(self.server.calls)
        self.assertIsNone(self.client.analyze_once())
        self.assertEqual(self.client.last_outcome,'NOTIONAL_CAP_BLOCKED')
        self.assertEqual(len(self.server.calls),before); self.assertEqual(self.server.model_calls,0)
    def test_unknown_cost_blocks_before_analysis_post(self):
        self.capture.cost_bound_cents=None
        self.prepare(); before=len(self.server.calls)
        self.assertIsNone(self.client.analyze_once())
        self.assertEqual(self.client.last_outcome,'COSTS_UNKNOWN'); self.assertEqual(len(self.server.calls),before)
    def test_reviewed_small_exposure_fixture_returns_proposal_without_activation(self):
        self.sdk.tick.ask=1900.; self.sdk.tick.bid=1899.9
        self.prepare()
        result=self.client.analyze_once()
        self.assertEqual(result['outcome'],'PROPOSAL_READY')
        self.assertEqual(result['instrument'],'GOLD'); self.assertFalse(result['execution_authorized'])
        self.assertEqual(self.server.calls[-1][0],GOLD_ANALYSIS_PATH)
        self.assertIsNone(self.client.grant); self.assertIsNone(self.client.pending_signal)
    def test_unreviewed_gold_macro_news_blocks_before_analysis_post(self):
        self.sdk.tick.ask=1900.; self.sdk.tick.bid=1899.9; self.server.review='UNREVIEWED'
        self.prepare(); before=len(self.server.calls)
        self.assertIsNone(self.client.analyze_once())
        self.assertEqual(self.client.last_outcome,'GOLD_NEWS_UNREVIEWED'); self.assertEqual(len(self.server.calls),before)
    def test_unexpected_gold_execution_grant_is_rejected(self):
        self.sdk.tick.ask=1900.; self.sdk.tick.bid=1899.9
        self.server.execution_authorized=True
        self.prepare(); self.assertIsNone(self.client.analyze_once())
        self.assertFalse(self.client.authority_valid()); self.assertIsNone(self.client.grant)
    def test_gold_activation_requested_is_rejected_before_worker_assembly(self):
        with self.assertRaisesRegex(Blocked,'GOLD_RUNTIME_UNREVIEWED'):
            build_gold_proposal_worker(self.a,control_ledger=Path(self.tmp.name)/'newc',
                                      decision_ledger=Path(self.tmp.name)/'newd',activation_enabled=True)
    def test_wrong_wire_symbol_and_btc_route_reject_before_http(self):
        self.prepare(); body=copy.deepcopy(self.server.calls[-1][1]); before=len(self.server.calls)
        with self.assertRaises(BtcRejected):validate_evidence_request(body)
        body['market']['symbol']='XAUUSD'
        with self.assertRaises(BtcRejected):validate_evidence_request(body,instrument='GOLD')
        with self.assertRaises(TransportFailure):self.http.post(EVIDENCE_PATH,body)
        self.assertEqual(len(self.server.calls),before)
    def test_contract_change_during_gold_capture_is_rejected(self):
        original=self.sdk.copy_rates_from_pos
        def changed(*args):
            result=original(*args); self.sdk.info.trade_contract_size=1; return result
        self.sdk.copy_rates_from_pos=changed
        with self.assertRaises(Blocked):self.capture.collect()
    def test_gold_blocked_calendar_outcomes_are_strictly_instrument_bound(self):
        self.sdk.tick.ask=1900.; self.sdk.tick.bid=1899.9; self.prepare()
        response=self.client.analyze_once(); request=self.server.calls[-1][1]
        response.update(outcome='CALENDAR_EVENT_BLOCKED',risk_state='BLOCKED',decision=None)
        self.assertEqual(parse_analysis_response(response,request,instrument='GOLD')['outcome'],'CALENDAR_EVENT_BLOCKED')
        with self.assertRaises(BtcRejected):parse_analysis_response(response,request)
    def test_duplicate_gold_response_fields_never_adopt_a_proposal(self):
        self.sdk.tick.ask=1900.; self.sdk.tick.bid=1899.9; self.prepare()
        response=self.client.analyze_once(); request=self.server.calls[-1][1]
        raw=json.dumps(response).replace('"instrument":','"instrument":"BTC","instrument":',1)
        with self.assertRaises(BtcRejected):parse_analysis_response(raw,request,instrument='GOLD')
    def test_missing_provider_is_inert_and_creates_no_connection(self):
        fresh=MT5DemoAdapter(self.sdk,Journal(Path(self.tmp.name)/'otherb'),policy(),
                             instrument='GOLD',clock=self.clock,wall=self.clock)
        worker=build_gold_proposal_worker(fresh,control_ledger=Path(self.tmp.name)/'otherc',
                                         decision_ledger=Path(self.tmp.name)/'otherd')
        self.assertEqual(worker.threads,[])
        self.assertFalse(worker.integration.status()['execution_authorized'])
        self.assertIsNone(worker.integration.transport.provider)
        self.assertEqual(self.server.calls,[])


if __name__=='__main__':unittest.main()
