"""Synthetic offline Gold contracts. No broker, provider, credential or order IO."""
import copy
import json
import os
import unittest
from types import SimpleNamespace
from datetime import timedelta
from unittest.mock import patch
import test_kilas_trading_btc_analysis as fixture
import test_kilas_trading as f
from kilas_trading import btc_analysis as btc, btc_sources, btc_news, bridge, analysis, analysis_budget as budget

PATH='/products/services/trading/control/gold-analysis'
EVIDENCE_PATH='/products/services/trading/control/gold-evidence'

class GoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixture.BTCAnalysisTests.setUpClass()
    def setUp(self):
        self.base=fixture.BTCAnalysisTests('test_btc_model_body_no_order_and_false_runtime_by_default')
        self.base.setUp();self.addCleanup(self.base.doCleanups)
        flags=patch.dict(os.environ,{'KILAS_TRADING_GOLD_ANALYSIS_ENABLED':'true','KILAS_TRADING_GOLD_EVIDENCE_ENABLED':'true','KILAS_TRADING_GOLD_RUNTIME_ENABLED':'false','KILAS_TRADING_BTC_ANALYSIS_ENABLED':'false'})
        flags.start();self.addCleanup(flags.stop)
        with fixture.c.bridge_store.transaction() as conn:
            fixture.c.query(conn,"UPDATE kilas_trading_control_credentials_v2 SET symbol='GOLD'")
            fixture.c.query(conn,"UPDATE kilas_trading_controls_v2 SET instrument='GOLD'")
        self.base.fixture.advance()
        self.assertEqual(self.base.fixture.sync(self.base.fixture.ack()).status_code,200)
        self.now=self.base.fixture.helper.time
        self.base.request['instrument']='GOLD';self.base.manifest['instrument']='GOLD'
        market=self.base.evidence['market'];market.update(symbol='GOLD',provider='TRUSTED_GOLD_V1',bid_cents=418700,ask_cents=418800,captured_at=bridge.stamp(self.now),quote_time=bridge.stamp(self.now))
        for bar in market['candles']:bar.update(open=418700,high=418900,low=418500,close=418700)
        # Deliberately synthetic 10 oz/lot contract exercises under-cap proposals.
        # The owner's reported 100 oz/lot minimum is tested separately as BLOCKED.
        self.base.evidence['spec'].update(symbol='GOLD',contract_size='10',tick_cents=1,stops_distance_cents=10)
        self.base.evidence['news']=self.news()
        self.base.evidence['risk']['captured_at']=bridge.stamp(self.now)
        self.calls=[]
    def news(self):
        return dict(id='2'*32,provider='TRUSTED_GOLD_NEWS_V1',as_of=bridge.stamp(self.now),valid_until=bridge.stamp(self.now+timedelta(seconds=120)),verified=True,event_risk='LOW',sentiment=0,coverage='GOLD_MACRO_CALENDAR',risk_review='SERVER_REVIEWED',articles=[dict(id='5'*32,published_at=bridge.stamp(self.now),title='Synthetic Gold macro evidence; not market news')],calendar=dict(provider='TRUSTED_GOLD_CALENDAR_V1',as_of=bridge.stamp(self.now),valid_until=bridge.stamp(self.now+timedelta(seconds=120)),coverage_start_at=bridge.stamp(self.now-timedelta(seconds=1800)),coverage_end_at=bridge.stamp(self.now+timedelta(seconds=1800)),verified=True,event_risk='LOW',events=[]))
    def reply(self,side='BUY'):
        reply=self.base.reply(side)
        decision=dict(decision=side,news_risk='LOW',reason='Synthetic Gold proposal',invalidation='Synthetic',stop_cents=418000 if side=='BUY' else 419500,target_cents=420400 if side=='BUY' else 417100)
        if side=='WAIT':decision.update(stop_cents=None,target_cents=None)
        reply['output'][0]['content'][0]['text']=json.dumps(decision)
        return reply
    def fake(self,side='BUY',reply=None):
        def send(method,url,key,body=None):
            self.calls.append((method,url,body))
            self.assertEqual(key,'synthetic-no-real-key')
            return {'id':budget.MODEL} if method=='GET' else copy.deepcopy(reply if reply is not None else self.reply(side))
        return patch.object(analysis,'_http',side_effect=send)
    def post(self,data=None,path=PATH,token=None,**kwargs):
        return self.base.fixture.helper.local.post(path,base_url=fixture.c.HOST,json=self.base.request if data is None else data,headers={'Authorization':'Bearer '+(token or self.base.fixture.conn['token'])},**kwargs)
    def clear(self):f.db.execute('DELETE FROM kilas_trading_events');self.calls.clear()
    def test_structured_buy_sell_wait_and_no_execution(self):
        for side,outcome in [('BUY','PROPOSAL_READY'),('SELL','PROPOSAL_READY'),('WAIT','MODEL_WAIT')]:
            self.clear()
            with self.fake(side):result=self.post()
            self.assertEqual(result.status_code,200,result.json);self.assertEqual(result.json['outcome'],outcome)
            self.assertEqual(result.json['instrument'],'GOLD');self.assertEqual(result.json['news_coverage'],'GOLD_MACRO_CALENDAR')
            self.assertFalse(result.json['execution_authorized']);self.assertIsNone(result.json['authorization_expires_at'])
            body=self.calls[-1][2];self.assertEqual(body['model'],'gpt-6.1-sol');self.assertEqual(body['reasoning'],{'effort':'medium'})
            self.assertEqual(body['tools'],[]);self.assertFalse(body['store']);self.assertIn('GOLD',body['instructions'])
            self.assertEqual(f.db.query_one('SELECT count(*) AS n FROM kilas_trading_positions')['n'],0)
            self.assertIsNone(analysis.market_source)
    def test_news_calendar_missing_stale_unreviewed_or_event_blocks_before_model(self):
        original=copy.deepcopy(self.base.evidence)
        cases=[('NEWS_STALE',lambda n:n.update(valid_until=bridge.stamp(self.now))),('CALENDAR_STALE',lambda n:n['calendar'].update(valid_until=bridge.stamp(self.now))),('GOLD_NEWS_UNREVIEWED',lambda n:n.update(risk_review='UNREVIEWED')),('NEWS_RISK_BLOCKED',lambda n:n.update(articles=[])),('CALENDAR_UNVERIFIED',lambda n:n['calendar'].update(verified=False)),('CALENDAR_COVERAGE_INSUFFICIENT',lambda n:n['calendar'].update(coverage_end_at=bridge.stamp(self.now+timedelta(seconds=899)))),('CALENDAR_EVENT_BLOCKED',lambda n:n['calendar'].update(events=[dict(id='6'*32,at=bridge.stamp(self.now),currency='USD',impact='HIGH',title='Synthetic release')]))]
        for outcome,mutate in cases:
            self.base.evidence=copy.deepcopy(original);mutate(self.base.evidence['news'])
            with self.fake():r=self.post()
            self.assertEqual(r.json['outcome'],outcome,r.json);self.assertEqual(self.calls,[])
            self.assertFalse(r.json.get('execution_authorized',False))
        with patch.object(btc.evidence_source,'resolve',side_effect=bridge.Rejected('NEWS_UNAVAILABLE')),self.fake():
            self.assertEqual(self.post().json['outcome'],'NEWS_UNAVAILABLE')
        self.assertEqual(self.calls,[])
    def test_mapping_schema_and_freshness_fail_closed(self):
        original=copy.deepcopy(self.base.evidence)
        for field,value in [('symbol','XAUUSD'),('provider','TRUSTED_BTC_V1'),('quote_time',bridge.stamp(self.now-timedelta(seconds=6))),('captured_at',bridge.stamp(self.now+timedelta(seconds=1)))]:
            self.base.evidence=copy.deepcopy(original);self.base.evidence['market'][field]=value
            with self.fake():self.assertEqual(self.post().status_code,409)
            self.assertEqual(self.calls,[])
        self.base.evidence=copy.deepcopy(original);self.base.evidence['spec']['symbol']='BTCUSD'
        with self.fake():self.assertEqual(self.post().json['outcome'],'SPECS_UNVERIFIED')
        self.base.evidence=copy.deepcopy(original);self.base.evidence['news']['calendar']['account']='private'
        with self.fake():self.assertEqual(self.post().status_code,409)
        self.assertEqual(self.calls,[])
    def test_actual_gold_minimum_notional_unknown_cost_volume_and_policy_block(self):
        original=copy.deepcopy(self.base.evidence)
        for outcome,part,field,value in [('NOTIONAL_CAP_BLOCKED','spec','contract_size','100'),('COSTS_UNKNOWN','spec','cost_bound_cents',None),('VOLUME_BLOCKED','spec','volume_min','0.02'),('POLICY_BLOCKED','risk','strategy_verified',False),('POSITION_OPEN','risk','position_open',True)]:
            self.base.evidence=copy.deepcopy(original);self.base.evidence[part][field]=value
            with self.fake():r=self.post()
            self.assertEqual(r.json['outcome'],outcome,r.json);self.assertEqual(self.calls,[])
        self.assertEqual(fixture.btc.engine.RISK['max_exposure_cents'],200000)
    def test_independent_sltp_tick_distance_and_loss_both_sides(self):
        for side in ('BUY','SELL'):
            for stop,outcome in [(418800 if side=='BUY' else 418700,'POST_MODEL_GATE_BLOCKED'),(418795 if side=='BUY' else 418705,'SLTP_BLOCKED'),(400000 if side=='BUY' else 438000,'LOSS_CAP_BLOCKED')]:
                self.clear();reply=self.reply(side);d=json.loads(reply['output'][0]['content'][0]['text']);d['stop_cents']=stop;reply['output'][0]['content'][0]['text']=json.dumps(d)
                with self.fake(reply=reply):r=self.post()
                self.assertEqual(r.json['outcome'],outcome,r.json);self.assertFalse(r.json['execution_authorized'])
        self.clear();self.base.evidence['spec']['tick_cents']=3
        with self.fake():self.assertEqual(self.post().json['outcome'],'SLTP_BLOCKED')
    def test_timeout_ambiguous_malformed_duplicate_no_retry(self):
        for problem in ('timeout','multiple','invalid','usage','duplicate-json'):
            self.clear();reply=self.reply()
            if problem=='multiple':reply['output']*=2
            if problem=='invalid':reply['output'][0]['content'][0]['text']='{"decision":"BUY"}'
            if problem=='duplicate-json':reply['output'][0]['content'][0]['text']=reply['output'][0]['content'][0]['text'].replace('{','{"decision":"SELL",',1)
            if problem=='usage':reply.pop('usage')
            if problem=='timeout':
                def send(method,*args):
                    self.calls.append(method)
                    if method=='GET':return {'id':budget.MODEL}
                    raise TimeoutError('Synthetic timeout')
                fake=patch.object(analysis,'_http',side_effect=send)
            else:fake=self.fake(reply=reply)
            with fake:r=self.post();duplicate=self.post()
            self.assertNotEqual(r.json['outcome'],'PROPOSAL_READY',r.json)
            self.assertEqual(duplicate.json['outcome'],'MODEL_RESULT_UNAVAILABLE');self.assertEqual(len(self.calls),2)
            self.assertFalse(duplicate.json['execution_authorized'])
        self.clear()
        with self.fake():r=self.post();duplicate=self.post()
        self.assertEqual(r.json['decision_id'],duplicate.json['decision_id']);self.assertEqual(len(self.calls),2)
        changed=copy.deepcopy(self.base.request);changed['evidence']['market_id']='9'*32
        with self.fake():self.assertEqual(self.post(changed).status_code,409)
        self.assertEqual(len(self.calls),2)
    def test_ambiguous_provider_transport_holds_cost_and_never_retries_gold(self):
        fixture.check_ambiguous_provider_transport(self,self.post,self.reply())
    def test_transport_flag_credential_instrument_cookie_host_size_isolation(self):
        with patch.dict(os.environ,{'KILAS_TRADING_GOLD_ANALYSIS_ENABLED':'false'}),self.fake():self.assertEqual(self.post().status_code,404)
        with self.fake():
            self.assertEqual(self.base.post().status_code,404)
            self.assertEqual(self.post(token=self.base.fixture.readonly['token']).status_code,401)
            wrong=copy.deepcopy(self.base.request);wrong['instrument']='BTC';self.assertEqual(self.post(wrong).status_code,409)
            self.assertEqual(self.post(path=PATH+'?q=1').status_code,400)
            client=self.base.fixture.helper.client(f.TradingTests.user)
            self.assertEqual(client.post(PATH,base_url=fixture.c.HOST,json=self.base.request,headers={'Authorization':'Bearer '+self.base.fixture.conn['token']}).status_code,400)
            self.assertEqual(self.base.fixture.helper.local.post(PATH,base_url='https://app.kilasworks.id',json=self.base.request,headers={'Authorization':'Bearer '+self.base.fixture.conn['token']}).status_code,404)
            self.assertEqual(self.base.fixture.helper.local.post(PATH,base_url=fixture.c.HOST,data='x'*8193,content_type='application/json',headers={'Authorization':'Bearer '+self.base.fixture.conn['token']}).status_code,413)
        self.assertEqual(self.calls,[])
    def test_runtime_flags_and_authority_do_not_cross_instruments(self):
        scope=dict(user_id=f.TradingTests.user,session_id=self.base.request['session_id'])
        authority=dict(scope,command_id=None,revision=0,policy_version=self.base.manifest['policy_version'],expires_at=self.base.manifest['expires_at'],runtime_eligible=True,broker_execution_allowed=True,policy_replay_only=False,server=bridge.SERVER,instrument='BTC')
        with patch.object(btc,'runtime_authorization_source',SimpleNamespace(authorization=lambda *args:copy.deepcopy(authority))):
            with patch.dict(os.environ,{'KILAS_TRADING_BTC_RUNTIME_ENABLED':'true','KILAS_TRADING_GOLD_RUNTIME_ENABLED':'false'}):
                self.assertFalse(btc.runtime_gate(scope,self.base.manifest,self.base.request,self.base.evidence,json.loads(self.reply()['output'][0]['content'][0]['text'])))
            with patch.dict(os.environ,{'KILAS_TRADING_GOLD_RUNTIME_ENABLED':'true'}):
                self.assertFalse(btc.runtime_gate(scope,self.base.manifest,self.base.request,self.base.evidence,json.loads(self.reply()['output'][0]['content'][0]['text'])))
                authority['instrument']='GOLD'
                self.assertFalse(btc.runtime_gate(scope,self.base.manifest,self.base.request,self.base.evidence,json.loads(self.reply()['output'][0]['content'][0]['text'])))
    def test_revoked_owner_or_credential_cannot_analyze_gold(self):
        with self.fake():
            f.db.execute('DELETE FROM oauth_identities WHERE user_id=?',(f.TradingTests.user,))
            try:self.assertEqual(self.post().status_code,401)
            finally:f.db.execute("INSERT INTO oauth_identities(provider,provider_subject,user_id,email_at_link) VALUES ('google','synthetic-paper-pilot',?,?)",(f.TradingTests.user,'irvankarnavi@gmail.com'))
            with fixture.c.bridge_store.transaction() as conn:fixture.c.query(conn,'UPDATE kilas_trading_control_credentials_v2 SET revoked=1')
            self.assertEqual(self.post().status_code,401)
        self.assertEqual(self.calls,[])
    def source(self,evidence_only=False):
        source=btc_sources.AcceptedSources()
        for field in ('approval_source','evidence_source','accepted_sources','runtime_authorization_source'):
            p=patch.object(btc,field,source);p.start();self.addCleanup(p.stop)
        if evidence_only:
            self.base.manifest.update(model_analysis_allowed=False,max_requests=0,max_loss_cents=0)
            self.base.evidence['spec']['cost_bound_cents']=None
            self.base.evidence['risk'].update(strategy_verified=False,cooldown_clear=False,loss_streak_clear=False,daily_loss_remaining_cents=0)
            with fixture.c.bridge_store.transaction() as conn:fixture.c.query(conn,'UPDATE kilas_trading_control_credentials_v2 SET max_run_seconds=NULL')
            self.base.fixture.advance();self.base.fixture.sync(self.base.fixture.ack(specs_verified=False,risk_allowed=False,policy_state='UNSET',wait_reason='STRATEGY_UNAVAILABLE'))
        acceptance=dict(producer_acceptance='ACCEPTED',clock_verified=False,profile_verified=False,profile_id='synthetic-unverified',evidence_ref='synthetic-proof',candidate_offset_seconds=10800,broker_contract_sha256=btc_sources.contract_hash(self.base.evidence['spec']),policy_version=self.base.manifest['policy_version'])
        source.install_reviewed(self.base.manifest,acceptance);return source,acceptance
    def capture(self,sequence,challenge,acceptance):
        now=self.base.fixture.helper.time;seconds=int(now.timestamp());last=seconds//60*60-60
        market=dict(symbol='GOLD',timeframe='M1',tick=dict(time=seconds,time_msc=seconds*1000,bid='4187',ask='4188'),capture=dict(start_utc=bridge.stamp(now-timedelta(seconds=.1)),end_utc=bridge.stamp(now),start_mono_ns=100,end_mono_ns=100000100),candles=[dict(time=last-60*(11-i),open='4187',high='4189',low='4185',close='4187') for i in range(12)],clock=dict(status='PRODUCER_CLAIM_ONLY',offset_seconds='0',uncertainty_ms='1'),clock_profile={k:acceptance[k] for k in ('profile_id','candidate_offset_seconds','evidence_ref')})
        spec={k:v for k,v in self.base.evidence['spec'].items() if k not in ('id','verified')}
        risk=dict(self.base.evidence['risk'],captured_at=bridge.stamp(now),broker_contract_sha256=acceptance['broker_contract_sha256'],policy_version=acceptance['policy_version'])
        result=dict(schema_version=2,session_id=self.base.request['session_id'],revision=0,command_id=None,instrument='GOLD',lot='0.01',sequence=sequence,challenge=challenge,account_mode='DEMO',terminal_connected=True,market=market,spec=spec,risk=risk)
        if sequence==0:result.update(challenge=None,market=None,spec=None,risk=None)
        return result
    def test_source_has_no_gold_fetch_and_missing_news_remains_blocked(self):
        source,acceptance=self.source()
        with patch.object(btc_news.requests,'get',side_effect=AssertionError('No Gold provider configured')),self.fake():
            source.ensure_news()
            boot=self.post(self.capture(0,None,acceptance),path=EVIDENCE_PATH);self.assertEqual(boot.status_code,200,boot.json)
            self.base.fixture.advance(.1)
            capture=self.post(self.capture(1,boot.json['challenge'],acceptance),path=EVIDENCE_PATH)
        self.assertEqual(capture.status_code,200,capture.json);self.assertIsNone(capture.json['evidence']['news_id']);self.assertFalse(capture.json['execution_authorized'])
        with self.assertRaises(bridge.Rejected) as rejected:source.collect_news()
        self.assertEqual(rejected.exception.code,'NEWS_COVERAGE_REJECTED');self.assertEqual(self.calls,[])
    def test_reviewed_gold_source_hash_mapping_persistence_and_news_revocation(self):
        source,acceptance=self.source();source.install_reviewed_gold_news(f.TradingTests.user,self.base.request['session_id'],self.news())
        boot=self.post(self.capture(0,None,acceptance),path=EVIDENCE_PATH)
        self.base.fixture.advance(.1);raw=self.capture(1,boot.json['challenge'],acceptance)
        result=self.post(raw,path=EVIDENCE_PATH);self.assertEqual(result.status_code,200,result.json)
        resolved=btc_sources.AcceptedSources().resolve(f.TradingTests.user,self.base.request['session_id'],result.json['evidence'])
        self.assertEqual(resolved['market']['provider'],'TRUSTED_GOLD_V1');self.assertFalse(resolved['market']['profile_verified']);self.assertFalse(resolved['market']['clock_verified'])
        self.assertEqual(resolved['spec']['symbol'],'GOLD');self.assertEqual(resolved['news']['coverage'],'GOLD_MACRO_CALENDAR')
        altered=self.news();altered['calendar']['event_risk']='HIGH';source.install_reviewed_gold_news(f.TradingTests.user,self.base.request['session_id'],altered)
        with self.assertRaises(bridge.Rejected) as rejected:source.resolve(f.TradingTests.user,self.base.request['session_id'],result.json['evidence'])
        self.assertEqual(rejected.exception.code,'NEWS_REVIEW_EXPIRED')
        bad=copy.deepcopy(raw);bad['instrument']='BTC';self.assertEqual(self.post(bad,path=EVIDENCE_PATH).status_code,409)
    def test_gold_evidence_only_zero_authority_no_model_or_runtime(self):
        source,acceptance=self.source(evidence_only=True)
        with patch.dict(os.environ,{'KILAS_TRADING_GOLD_ANALYSIS_ENABLED':'false','KILAS_TRADING_AI_ENABLED':'false'}),self.fake():
            boot=self.post(self.capture(0,None,acceptance),path=EVIDENCE_PATH)
            self.base.fixture.advance(.1);result=self.post(self.capture(1,boot.json['challenge'],acceptance),path=EVIDENCE_PATH)
        self.assertEqual(result.status_code,200,result.json);self.assertFalse(result.json['execution_authorized']);self.assertEqual(self.calls,[])
        self.assertEqual(self.base.fixture.desired('ON',instrument='GOLD').json['outcome'],'WORKER_NOT_READY')
        with self.fake():self.assertEqual(self.post().json['outcome'],'MODEL_SESSION_UNAPPROVED')
        self.assertEqual(self.calls,[])

    def test_gold_capture_to_fake_analysis_duplicate_remains_proposal_only(self):
        source,acceptance=self.source();source.install_reviewed_gold_news(f.TradingTests.user,self.base.request['session_id'],self.news())
        boot=self.post(self.capture(0,None,acceptance),path=EVIDENCE_PATH)
        self.base.fixture.advance(.1);first=self.post(self.capture(1,boot.json['challenge'],acceptance),path=EVIDENCE_PATH)
        self.assertEqual(first.status_code,200,first.json)
        self.base.fixture.advance();self.assertEqual(self.base.fixture.sync(self.base.fixture.ack()).status_code,200)
        second=self.post(self.capture(2,first.json['challenge'],acceptance),path=EVIDENCE_PATH)
        self.assertEqual(second.status_code,200,second.json);self.assertEqual(second.json['tick_liveness'],'VERIFIED')
        self.base.request['evidence']=second.json['evidence']
        with self.fake('SELL'):result=self.post();duplicate=self.post()
        self.assertEqual(result.json['outcome'],'PROPOSAL_READY',result.json)
        self.assertEqual(result.json['decision_id'],duplicate.json['decision_id']);self.assertFalse(result.json['execution_authorized']);self.assertEqual(len(self.calls),2)
        self.base.fixture.advance(.1)
        raw=self.capture(3,second.json['challenge'],acceptance);raw['spec']['contract_size']='100'
        self.assertEqual(self.post(raw,path=EVIDENCE_PATH).json['outcome'],'BROKER_CONTRACT_MISMATCH')

if __name__=='__main__':unittest.main()
