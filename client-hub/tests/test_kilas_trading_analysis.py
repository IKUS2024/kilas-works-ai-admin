"""Fixture-only analyst tests. All outbound transport is forbidden except explicit fake responses."""
import copy
import json
import os
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import test_kilas_trading as f
from kilas_trading import analysis, analysis_budget as budget, store

NOW=datetime(2026,10,6,9,0,5,tzinfo=timezone.utc)


def fixture_snapshot():
    end=NOW.replace(second=0)
    return {'connected':True,'kind':'TEST_FIXTURE','provider':'fixture_only','symbol':'XAUUSD','timeframe':'M1',
            'captured_at':(NOW-timedelta(seconds=1)).isoformat(),'quote_time':(NOW-timedelta(seconds=1)).isoformat(),
            'bid_cents':250000,'ask_cents':250100,
            'candles':[{'time':(end-timedelta(minutes=11-i)).isoformat(),'open':249900+i*5,
                        'high':250000+i*5,'low':249800+i*5,'close':249950+i*5} for i in range(12)]}


def reply(side='WAIT'):
    decision={'decision':side,'reason':'Fixture-only model response. No real inference.','invalidation':'Fixture invalidation.',
              'stop_cents':None if side=='WAIT' else 249000 if side=='BUY' else 251000,
              'target_cents':None if side=='WAIT' else 251500 if side=='BUY' else 248500}
    return {'model':budget.MODEL,'service_tier':'default','status':'completed',
            'usage':{'input_tokens':500,'output_tokens':400},
            'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(decision)}]}]}


class FakeSource:
    def __init__(self):self.data=fixture_snapshot()
    def snapshot(self,user):return copy.deepcopy(self.data)


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not hasattr(f.TradingTests,'user'):f.TradingTests.setUpClass()
        cls.user=f.TradingTests.user;cls.other=f.TradingTests.other;cls.admin=f.TradingTests.admin

    def setUp(self):
        self.clock=patch.object(store,'now',return_value=NOW);self.clock.start();self.addCleanup(self.clock.stop)
        self.fixture=f.TradingTests('test_xauusd_contract_and_units');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.client=self.fixture.client
        self.flags=patch.dict(os.environ,{'KILAS_TRADING_AI_ENABLED':'true','OPENAI_API_KEY':'fixture-key-never-real'})
        self.flags.start();self.addCleanup(self.flags.stop)
        self.source=FakeSource();self.source_patch=patch.object(analysis,'market_source',self.source)
        self.source_patch.start();self.addCleanup(self.source_patch.stop)
        store.snapshot(self.user)

    def call(self,key=None):
        with f.app.app.app_context():
            return analysis.analyze(self.user,{'operation_key':key or uuid.uuid4().hex})

    def fake(self,post=None):
        def send(method,url,key,body=None):
            self.assertEqual(key,'fixture-key-never-real')
            return {'id':budget.MODEL} if method=='GET' else copy.deepcopy(post or reply())
        return patch.object(analysis,'_http',side_effect=send)

    def record(self):
        row=f.db.query_one("SELECT * FROM kilas_trading_events WHERE action='AI_ANALYSIS' ORDER BY id DESC LIMIT 1")
        return row,json.loads(row['inputs_json'])

    def test_no_feed_disabled_missing_key_or_stale_policy_no_network(self):
        for overrides in ({'market_source':None},{'flag':'false'},{'key':''},{'expired':True}):
            with patch.object(analysis,'market_source',None if 'market_source' in overrides else self.source),patch.dict(os.environ,{'KILAS_TRADING_AI_ENABLED':overrides.get('flag','true'),'OPENAI_API_KEY':overrides.get('key','fixture-key-never-real')}),patch.object(store,'now',return_value=NOW+timedelta(days=8) if overrides.get('expired') else NOW):
                self.assertEqual(self.call()['outcome'],'UNAVAILABLE')
        self.assertEqual(f.db.query_one("SELECT count(*) AS n FROM kilas_trading_events WHERE action='AI_ANALYSIS'")['n'],0)

    def test_source_invalid_stale_real_and_account_data_denied(self):
        for change in ({'connected':False},{'kind':'REAL'},{'balance':10000},{'password':'not-for-model'},{'quote_time':(NOW-timedelta(seconds=121)).isoformat()},{'bid_cents':True},{'ask_cents':260000}):
            self.source.data=dict(fixture_snapshot(),**change)
            self.assertEqual(self.call()['outcome'],'UNAVAILABLE')
        self.source.data=fixture_snapshot();self.source.data['candles'][-1]['time']=NOW.isoformat()
        self.assertEqual(self.call()['outcome'],'UNAVAILABLE')
        f.app.app.config['TESTING']=False
        try:self.assertEqual(self.call()['outcome'],'UNAVAILABLE')
        finally:f.app.app.config['TESTING']=True

    def test_manual_wait_buy_sell_proposals_never_execute(self):
        for side in ('WAIT','BUY','SELL'):
            self.source.data['provider']='fixture_'+side
            with self.fake(reply(side)):
                r=self.call();self.assertEqual(r['outcome'],'WAIT' if side=='WAIT' else 'OK')
                self.assertEqual(r['analysis']['decision'],side);self.assertEqual(r['source_kind'],'TEST_FIXTURE')
                self.assertTrue(r['proposal_only']);self.assertLess(r['cost_upper_micros'],r['reserved_micros'])
            self.assertEqual(store.snapshot(self.user)['positions'],[])

    def test_retries_and_same_candle_dedup_do_not_bill_again(self):
        key=uuid.uuid4().hex
        with self.fake() as http:
            first=self.call(key);second=self.call(key);third=self.call()
            self.assertEqual(http.call_count,2) # one catalog GET + one inference-shaped FAKE POST
            self.assertTrue(second['duplicate']);self.assertTrue(third['duplicate'])
            self.assertEqual(first['analysis'],third['analysis'])
        self.assertEqual(f.db.query_one("SELECT count(*) AS n FROM kilas_trading_events WHERE action='AI_ANALYSIS'")['n'],1)

    def test_concurrency_one_inflight_and_paper_controls_do_not_wait_for_http(self):
        entered=threading.Event();release=threading.Event();post_calls=[]
        def send(method,url,key,body=None):
            if method=='GET':return {'id':budget.MODEL}
            post_calls.append(1);entered.set();self.assertTrue(release.wait(5));return reply()
        with patch.object(analysis,'_http',side_effect=send),ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(self.call)
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.call()['outcome'],'PENDING') # same closed candle returns held reservation
            self.source.data['provider']='different_fixture'
            with self.assertRaises(budget.GuardError):self.call()
            self.fixture.act('pause') # account lock released during provider wait
            release.set();self.assertEqual(future.result(timeout=5)['outcome'],'WAIT')
        self.assertEqual(len(post_calls),1)

    def test_timeout_holds_full_reservation_and_retry_has_no_network(self):
        def send(method,url,key,body=None):
            if method=='GET':return {'id':budget.MODEL}
            raise analysis.requests.Timeout('fixture-only')
        with patch.object(analysis,'_http',side_effect=send):r=self.call()
        self.assertEqual(r['outcome'],'ERROR');self.assertEqual(r['cost_upper_micros'],r['reserved_micros'])
        self.assertTrue(self.call()['duplicate']) # forbidden transport would fail if retried

    def test_nonbillable_preflight_failure_and_kill_never_post(self):
        with patch.object(analysis,'_http',return_value={'id':'gpt-6-astra'}) as http:r=self.call()
        self.assertEqual(r['outcome'],'UNAVAILABLE');self.assertEqual(r['cost_upper_micros'],0);self.assertEqual(http.call_count,1)
        self.source.data['provider']='second_fixture'
        def send(method,url,key,body=None):
            self.assertEqual(method,'GET');self.fixture.act('kill');return {'id':budget.MODEL}
        with patch.object(analysis,'_http',side_effect=send):r=self.call()
        self.assertEqual(r['outcome'],'UNAVAILABLE');self.assertEqual(r['cost_upper_micros'],0)

    def test_daily_monthly_attempt_caps_include_reservations(self):
        amount=budget.cost_micros(budget.policy(),budget.INPUT_BOUND,budget.OUTPUT_BOUND)
        self.assertEqual(amount,77000)
        for i in range(3):
            self.source.data['provider']='timeout_fixture_'+str(i)
            with patch.object(analysis,'_http',side_effect=lambda method,*args: {'id':budget.MODEL} if method=='GET' else (_ for _ in ()).throw(analysis.requests.Timeout())):self.call()
        self.source.data['provider']='fourth_fixture'
        with self.assertRaises(budget.GuardError):self.call()
        # UTC month cap independent of pilot's Kilas AI QA exemption.
        with patch.object(budget,'DAY_CAP',10000000),patch.object(budget,'DAY_REQUESTS',1000),patch.object(budget,'MONTH_CAP',231000):
            with self.assertRaises(budget.GuardError):self.call()
        with patch.object(budget,'DAY_CAP',10000000),patch.object(budget,'DAY_REQUESTS',3):
            with self.assertRaises(budget.GuardError):self.call()

    def test_unknown_usage_and_invalid_decision_still_accounted(self):
        p=reply();p.pop('usage')
        with self.fake(p):r=self.call()
        self.assertEqual(r['cost_upper_micros'],r['reserved_micros'])
        self.source.data['provider']='invalid_decision_fixture'
        p=reply('BUY');data=json.loads(p['output'][0]['content'][0]['text']);data['stop_cents']=260000
        p['output'][0]['content'][0]['text']=json.dumps(data)
        with self.fake(p):r=self.call()
        self.assertEqual(r['outcome'],'WAIT');self.assertIsNone(r['analysis']);self.assertGreater(r['cost_upper_micros'],0)

    def test_unknown_model_tier_or_usage_overrun_blocks_later_calls(self):
        for bad in ({'model':'gpt-6-astra'},{'service_tier':'priority'},{'usage':{'input_tokens':500,'output_tokens':budget.OUTPUT_BOUND+1}}):
            # fresh isolated ledger per invariant case
            f.db.execute("DELETE FROM kilas_trading_events WHERE action='AI_ANALYSIS'")
            p=dict(reply(),**bad)
            with self.fake(p):r=self.call()
            self.assertEqual(r['outcome'],'ERROR');self.assertIsNone(r['analysis'])
            self.source.data['provider']='after_invariant_fixture'
            with self.assertRaises(budget.GuardError):self.call()
            self.source.data['provider']='fixture_only'

    def test_request_privacy_and_model_payload_pinned(self):
        with f.app.app.app_context():
            with self.assertRaises(budget.GuardError):analysis.analyze(self.user,{'operation_key':uuid.uuid4().hex,'balance':10000})
        captured=[]
        def send(method,url,key,body=None):
            if method=='GET':return {'id':budget.MODEL}
            captured.append(body);return reply()
        with patch.object(analysis,'_http',side_effect=send):self.call()
        body=captured[0];self.assertEqual(body['model'],'gpt-6.1-sol');self.assertEqual(body['reasoning'],{'effort':'medium'})
        self.assertEqual(body['tools'],[]);self.assertFalse(body['store']);self.assertEqual(body['service_tier'],'default')
        text=json.dumps(body)
        for secret in ('irvankarnavi@gmail.com','fixture-key-never-real','initial_cents','realized_cents','account_info','margin_free'):
            self.assertNotIn(secret,text)
        _,evidence=self.record();self.assertEqual(evidence['input_bound'],budget.INPUT_BOUND)
        self.assertLess(evidence['input_bytes']+2048,budget.INPUT_BOUND)

    def test_permission_csrf_no_feed_http_and_paper_regression(self):
        body={'operation_key':uuid.uuid4().hex}
        self.assertEqual(self.client.post('/products/services/trading/analyze',json=body).status_code,400)
        for user in (self.other,self.admin):
            c=self.fixture.login(user)
            self.assertEqual(c.post('/products/services/trading/analyze',json=body,headers={'X-CSRF-Token':'paper-csrf'}).status_code,404)
            with self.assertRaises(PermissionError):
                with f.app.app.app_context():analysis.analyze(user,body)
        with patch.object(analysis,'market_source',None):
            r=self.client.post('/products/services/trading/analyze',json=body,headers={'X-CSRF-Token':'paper-csrf'})
            self.assertEqual(r.status_code,503);self.assertEqual(r.json['outcome'],'UNAVAILABLE')
        self.assertEqual(self.fixture.order()['outcome'],'OK')
        p=store.snapshot(self.user)['positions'][0]
        self.assertEqual(self.fixture.act('protect',position_id=str(p['id']),stop=str(p['stop_cents']/100),target=str(p['target_cents']/100))['outcome'],'OK')
        self.assertEqual(self.fixture.act('close',position_id=str(p['id']))['outcome'],'OK')
        self.assertEqual(store.snapshot(self.user)['positions'],[])

    def test_missing_or_modified_rate_proof_fail_closed(self):
        from pathlib import Path
        with patch.object(budget,'POLICY_PATH',Path('/tmp/no-such-kilas-trading-rate-proof')):
            self.assertEqual(self.call()['outcome'],'UNAVAILABLE')
        with patch.object(budget.POLICY_PATH.__class__,'read_text',return_value=json.dumps(dict(budget.policy(),output_usd_per_million='0.01'))):
            self.assertEqual(self.call()['outcome'],'UNAVAILABLE')

    def test_crashed_pending_reservation_survives_month_change(self):
        snap=fixture_snapshot();identity='fixture-crash-reservation'
        budget.reserve(self.user,budget.request_key(uuid.uuid4().hex),identity,{'source_kind':'TEST_FIXTURE'})
        with patch.object(store,'now',return_value=NOW.replace(month=11)):
            # Check ledger directly with a reviewed fixture policy, not an expired public tariff.
            with patch.object(budget,'policy',return_value=json.loads(budget.POLICY_PATH.read_text())):
                with self.assertRaises(budget.GuardError):budget.reserve(self.user,budget.request_key(uuid.uuid4().hex),'new-month-fixture',{})
        _,evidence=self.record();self.assertEqual(evidence['cost_upper_micros'],77000)

    def test_malformed_response_and_late_stale_quote_account_usage(self):
        bad=reply();bad['output']=['malformed fixture']
        with self.fake(bad):r=self.call()
        self.assertEqual(r['outcome'],'WAIT');self.assertGreater(r['cost_upper_micros'],0)
        self.source.data['provider']='late_response_fixture'
        def send(method,url,key,body=None):
            if method=='GET':return {'id':budget.MODEL}
            self.clock.stop()
            self.late_clock=patch.object(store,'now',return_value=NOW+timedelta(seconds=121))
            self.late_clock.start();self.addCleanup(self.late_clock.stop)
            return reply('BUY')
        with patch.object(analysis,'_http',side_effect=send):r=self.call()
        self.assertEqual(r['outcome'],'WAIT');self.assertIsNone(r['analysis']);self.assertGreater(r['cost_upper_micros'],0)

    def test_cached_decision_expires_and_timezone_dedup(self):
        with self.fake() as http:
            self.call()
            for field in ('captured_at','quote_time'):
                self.source.data[field]=datetime.fromisoformat(self.source.data[field]).astimezone(timezone(timedelta(hours=7))).isoformat()
            for bar in self.source.data['candles']:
                bar['time']=datetime.fromisoformat(bar['time']).astimezone(timezone(timedelta(hours=7))).isoformat()
            self.assertTrue(self.call()['duplicate']);self.assertEqual(http.call_count,2)
            with patch.object(store,'now',return_value=NOW+timedelta(seconds=121)):
                row=f.db.query_one("SELECT * FROM kilas_trading_events WHERE action='AI_ANALYSIS'")
                r=budget.result(row,True);self.assertTrue(r['cached_stale']);self.assertIsNone(r['analysis'])
        _,evidence=self.record();self.assertEqual(evidence['market_snapshot']['symbol'],'XAUUSD')
        self.assertNotIn('balance',evidence['market_snapshot'])

    def test_http_bounded_redirects_no_fallback(self):
        class Response:
            status_code=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def raise_for_status(self):pass
            def iter_content(self,n):return iter([json.dumps({'id':budget.MODEL}).encode()])
        # Replace the forbidden Session.request with one explicitly bounded local fake.
        with patch('requests.sessions.Session.request',return_value=Response()) as transport:
            self.assertEqual(analysis._http('GET',analysis.MODEL_URL,'fixture-key-never-real')['id'],budget.MODEL)
            self.assertFalse(transport.call_args.kwargs['allow_redirects'])
            self.assertTrue(transport.call_args.kwargs['stream'])
            self.assertEqual(transport.call_count,1)
        with self.assertRaises(budget.GuardError):analysis._body({'payload':'x'*17000})


if __name__=='__main__':unittest.main(verbosity=2)
