"""Actual adapter/route contracts using fake SDK/feed/provider data only."""
import copy
import json
import os
import unittest
from datetime import timedelta
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import test_kilas_trading_btc_analysis as fixture
import test_kilas_trading as f
from kilas_trading import btc_sources, btc_news, btc_analysis as btc, bridge, analysis

PATH='/products/services/trading/control/btc-evidence'
class FeedReply:
    def __init__(self,body,status=200):self.body=body;self.status_code=status
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_content(self,n):yield self.body

class SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixture.BTCAnalysisTests.setUpClass()
    def setUp(self):
        self.base=fixture.BTCAnalysisTests('test_btc_model_body_no_order_and_false_runtime_by_default');self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.source=btc_sources.AcceptedSources()
        for field in ('approval_source','evidence_source','accepted_sources','runtime_authorization_source'):
            p=patch.object(btc,field,self.source);p.start();self.addCleanup(p.stop)
        flags=patch.dict(os.environ,{'KILAS_TRADING_BTC_EVIDENCE_ENABLED':'true','KILAS_TRADING_BTC_NEWS_ENABLED':'true'});flags.start();self.addCleanup(flags.stop)
        spec={k:v for k,v in self.base.evidence['spec'].items() if k not in ('id','verified')}
        self.acceptance=dict(producer_acceptance='ACCEPTED',clock_verified=True,profile_verified=True,profile_id='synthetic-clock-policy',evidence_ref='synthetic-reviewed-proof',candidate_offset_seconds=0,broker_contract_sha256=btc_sources.contract_hash(spec),policy_version=self.base.manifest['policy_version'])
        self.source.install_reviewed(self.base.manifest,self.acceptance)
        self.challenge=None
        with patch.object(btc_news.requests,'get',return_value=FeedReply(self.feed())):
            boot=self.post(self.payload(0));self.assertEqual(boot.status_code,200,boot.json)
        self.base.fixture.advance(.1)
        self.raw=self.payload(1)
    def payload(self,sequence):
        current=self.base.fixture.helper.time;seconds=int(current.timestamp());last=seconds//60*60-60
        rawmarket=dict(symbol='BTCUSD',timeframe='M1',tick=dict(time=seconds,time_msc=seconds*1000,bid='60000',ask='60010'),capture=dict(start_utc=bridge.stamp(current-timedelta(seconds=.1)),end_utc=bridge.stamp(current),start_mono_ns=100,end_mono_ns=100000100),candles=[dict(time=last-60*(11-i),open='60000',high='60020',low='59980',close='60000') for i in range(12)],clock=dict(status='PRODUCER_CLAIM_ONLY',offset_seconds='0',uncertainty_ms='1'),clock_profile={k:self.acceptance[k] for k in ('profile_id','candidate_offset_seconds','evidence_ref')})
        risk=copy.deepcopy(self.base.evidence['risk']);risk.update(captured_at=bridge.stamp(current),broker_contract_sha256=self.acceptance['broker_contract_sha256'],policy_version=self.acceptance['policy_version'])
        spec={k:v for k,v in self.base.evidence['spec'].items() if k not in ('id','verified')}
        result=dict(schema_version=2,challenge=self.challenge,session_id=self.base.request['session_id'],revision=self.base.request['revision'],command_id=self.base.request['command_id'],instrument='BTC',lot='0.01',sequence=sequence,account_mode='DEMO',terminal_connected=True,market=rawmarket,spec=spec,risk=risk)
        if sequence==0:result.update(challenge=None,market=None,spec=None,risk=None)
        return result
    def post(self,data=None,token=None,**kwargs):
        response=self.base.fixture.helper.local.post(PATH,base_url=fixture.c.HOST,json=self.raw if data is None else data,headers={'Authorization':'Bearer '+(token or self.base.fixture.conn['token'])},**kwargs)
        if response.status_code==200:self.challenge=response.json['challenge']
        return response
    def feed(self,title='Bitcoin synthetic fixture report',date=None):
        date=date or self.base.fixture.helper.time
        return f'<rss><channel><item><title>{title}</title><pubDate>{date.strftime("%a, %d %b %Y %H:%M:%S GMT")}</pubDate></item></channel></rss>'.encode()
    def collect(self):
        with patch.object(btc_news.requests,'get',return_value=FeedReply(self.feed())) as get:record=self.source.collect_news()
        get.assert_called_once_with(btc_news.URL,headers={'Accept':'application/rss+xml, application/xml','User-Agent':'KilasTradingCatalog/1'},timeout=(5,10),allow_redirects=False,stream=True)
        return record
    def review(self,news,event='LOW'):
        self.source.review_news(f.TradingTests.user,self.base.request['session_id'],dict(news_id=news['id'],policy_version=self.base.manifest['policy_version'],coverage=btc_news.COVERAGE,event_risk=event,sentiment=0,expires_at=bridge.stamp(self.base.fixture.helper.time+timedelta(seconds=60))))
    def advance(self):
        self.base.fixture.advance();self.assertEqual(self.base.fixture.sync(self.base.fixture.ack()).status_code,200)
    def evidence_only(self):
        flags=patch.dict(os.environ,{name:'false' for name in ('KILAS_TRADING_BTC_ANALYSIS_ENABLED','KILAS_TRADING_AI_ENABLED','KILAS_TRADING_BTC_NEWS_ENABLED','KILAS_TRADING_BTC_RUNTIME_ENABLED')})
        flags.start();self.addCleanup(flags.stop)
        self.source.reset()
        self.base.manifest.update(model_analysis_allowed=False,max_requests=0,max_loss_cents=0,expires_at=bridge.stamp(self.base.fixture.helper.time+timedelta(seconds=60)))
        self.base.evidence['spec']['cost_bound_cents']=None
        self.base.evidence['risk'].update(strategy_verified=False,cooldown_clear=False,loss_streak_clear=False,daily_loss_remaining_cents=0)
        self.acceptance.update(clock_verified=False,profile_verified=False,broker_contract_sha256=btc_sources.contract_hash(self.base.evidence['spec']))
        with fixture.c.bridge_store.transaction() as conn:
            fixture.c.query(conn,'UPDATE kilas_trading_control_credentials_v2 SET max_run_seconds=NULL,expires_at=?',(self.base.manifest['expires_at'],))
        self.source.install_reviewed(self.base.manifest,self.acceptance)
        self.base.fixture.advance()
        self.assertEqual(self.base.fixture.sync(self.base.fixture.ack(specs_verified=False,risk_allowed=False,policy_state='UNSET',wait_reason='STRATEGY_UNAVAILABLE')).status_code,200)
        self.challenge=None
    def test_end_to_end_autonomous_news_model_and_no_runtime_grant(self):
        trace=[];news=self.collect();self.assertEqual(news['event_risk'],'UNKNOWN');self.assertEqual(news['risk_review'],'UNREVIEWED')
        first=self.post();self.assertEqual(first.status_code,200,first.json);self.assertEqual(first.json['tick_liveness'],'UNCONFIRMED')
        trace.append(dict(stage='capture-warmup',request=copy.deepcopy(self.raw),response=first.json))
        self.advance();second_request=self.payload(2);second=self.post(second_request)
        self.assertEqual(second.status_code,200,second.json);self.assertEqual(second.json['tick_liveness'],'VERIFIED')
        self.assertEqual(second.json['risk_review'],'UNREVIEWED')
        self.base.request['evidence']=second.json['evidence'];trace.append(dict(stage='receipt-live-unreviewed-news',request=second_request,response=second.json))
        with self.base.fake():result=self.base.post();duplicate=self.base.post()
        self.assertEqual(result.json['outcome'],'PROPOSAL_READY',result.json);self.assertFalse(result.json['execution_authorized']);self.assertEqual(duplicate.json['decision_id'],result.json['decision_id']);self.assertEqual(len(self.base.calls),2)
        self.assertEqual(result.json['news_coverage'],'BTC_EDITORIAL_ONLY');self.assertEqual(result.json['decision']['news_risk'],'LOW')
        trace.append(dict(stage='autonomous-fake-model',request=copy.deepcopy(self.base.request),response=result.json))
        if os.environ.get('TRADING_BTC_TRACE_OUTPUT'):
            from pathlib import Path
            Path(os.environ['TRADING_BTC_TRACE_OUTPUT']).write_text(json.dumps(dict(fixture_only=True,external_calls=0,credentials_created=0,trace=trace),indent=2))
    def test_disabled_empty_acceptance_default_no_upload_or_calls(self):
        for name in ('KILAS_TRADING_BTC_EVIDENCE_ENABLED','KILAS_TRADING_CONTROL_ENABLED'):
            with patch.dict(os.environ,{name:'false'}):self.assertEqual(self.post().status_code,404)
        self.source.reset();self.assertEqual(self.post().status_code,409)
    def test_evidence_only_capture_with_model_news_runtime_disabled(self):
        self.evidence_only()
        with patch.object(analysis,'_http') as model,patch.object(btc_news.requests,'get') as news,patch.object(btc,'runtime_gate') as runtime:
            bootstrap=self.post(self.payload(0));self.assertEqual(bootstrap.status_code,200,bootstrap.json)
            self.base.fixture.advance(.1);first=self.post(self.payload(1))
            self.assertEqual(first.status_code,200,first.json);self.assertIsNone(first.json['evidence']['news_id'])
            self.assertFalse(first.json['execution_authorized'])
            # Even accidental global news enablement cannot fetch or attach news.
            with self.source.transaction():self.source.news=btc_news.parse(self.feed(),self.base.fixture.helper.time)
            with patch.dict(os.environ,{'KILAS_TRADING_BTC_NEWS_ENABLED':'true'}):
                self.advance();second=self.post(self.payload(2))
            self.assertEqual(second.status_code,200,second.json);self.assertIsNone(second.json['evidence']['news_id'])
            self.assertFalse(second.json['execution_authorized']);model.assert_not_called();news.assert_not_called();runtime.assert_not_called()
        self.assertEqual(self.base.fixture.status()['effective_desired_state'],'OFF')
        self.assertEqual(f.db.query_one("SELECT count(*) AS n FROM kilas_trading_events WHERE action='AI_ANALYSIS'")['n'],0)
        self.assertEqual(f.db.query_one('SELECT count(*) AS n FROM kilas_trading_positions')['n'],0)
        self.assertEqual(self.base.fixture.desired('ON').json['outcome'],'RUN_DURATION_UNAPPROVED')
    def test_evidence_only_cannot_analyze_or_install_runtime_with_flags_enabled(self):
        self.evidence_only()
        with patch.dict(os.environ,{'KILAS_TRADING_BTC_ANALYSIS_ENABLED':'true','KILAS_TRADING_AI_ENABLED':'true','KILAS_TRADING_BTC_RUNTIME_ENABLED':'true'}),patch.object(analysis,'_http') as model,patch.object(self.source,'resolve') as resolve:
            response=self.base.post();self.assertEqual(response.json['outcome'],'MODEL_SESSION_UNAPPROVED')
            model.assert_not_called();resolve.assert_not_called()
            grant=dict(user_id=f.TradingTests.user,session_id=self.base.request['session_id'],policy_version=self.base.manifest['policy_version'],expires_at=self.base.manifest['expires_at'],runtime_eligible=True,broker_execution_allowed=True,policy_replay_only=False,server=bridge.SERVER,instrument='BTC')
            with self.assertRaises(bridge.Rejected) as rejected:self.source.install_runtime_authority(f.TradingTests.user,self.base.request['session_id'],grant)
            self.assertEqual(rejected.exception.code,'RUNTIME_APPROVAL_REJECTED')
        with self.source.transaction():self.assertIsNone(self.source.sessions[(f.TradingTests.user,self.base.request['session_id'])]['runtime'])
        self.assertEqual(f.db.query_one("SELECT count(*) AS n FROM kilas_trading_events WHERE action='AI_ANALYSIS'")['n'],0)
    def test_reviewed_manifest_requires_exact_zero_or_positive_permissions(self):
        self.source.reset()
        cases=[(False,1,0),(False,0,1),(False,False,0),(False,0,False),(False,'0',0),(True,0,1),(True,1,0),(True,False,1),(True,1,False),(0,0,0),(None,0,0)]
        for allowed,requests,loss in cases:
            with self.subTest(allowed=allowed,requests=requests,loss=loss),self.assertRaises(bridge.Rejected):
                self.source.install_reviewed(dict(self.base.manifest,model_analysis_allowed=allowed,max_requests=requests,max_loss_cents=loss),self.acceptance)
        self.assertFalse(self.source.sessions)
    def test_evidence_only_requires_off_current_ack_and_null_run_authority(self):
        self.evidence_only()
        with fixture.c.bridge_store.transaction() as conn:original=fixture.c.control.row_for(conn,f.TradingTests.user)
        cases=[('desired_state','ON'),('run_status','PENDING'),('run_status','ACTIVE'),('max_run_seconds',60),('actual_state','BLOCKED'),('position_open',True),('revision',1),('command_id','f'*32)]
        for key,value in cases:
            with self.subTest(key=key,value=value):
                with fixture.c.bridge_store.transaction() as conn:
                    if key=='max_run_seconds':fixture.c.query(conn,'UPDATE kilas_trading_control_credentials_v2 SET max_run_seconds=?',(value,))
                    elif key in ('desired_state','run_status'):fixture.c.query(conn,f'UPDATE kilas_trading_controls_v2 SET {key}=?',(value,))
                    else:
                        ack=json.loads(original['ack_json']);ack[key]=value
                        fixture.c.query(conn,'UPDATE kilas_trading_controls_v2 SET ack_json=?',(json.dumps(ack),))
                self.assertEqual(self.post(self.payload(0)).json['outcome'],'EVIDENCE_ONLY_OFF_REQUIRED')
                with fixture.c.bridge_store.transaction() as conn:
                    fixture.c.query(conn,'UPDATE kilas_trading_control_credentials_v2 SET max_run_seconds=NULL')
                    fixture.c.query(conn,'UPDATE kilas_trading_controls_v2 SET desired_state=?,run_status=?,ack_json=?',(original['desired_state'],original['run_status'],original['ack_json']))
    def test_evidence_only_preserves_identity_provenance_and_expiry(self):
        self.evidence_only();self.assertEqual(self.post(self.payload(0)).status_code,200);self.base.fixture.advance(.1)
        raw=self.payload(1)
        for mutate in (lambda p:p.update(session_id='e'*32),lambda p:p.update(account_mode='REAL'),lambda p:p['spec'].update(contract_size='100'),lambda p:p['risk'].update(policy_version='f'*64),lambda p:p.update(balance=1)):
            bad=copy.deepcopy(raw);mutate(bad);self.assertEqual(self.post(bad).status_code,409)
        with patch.object(bridge.access,'PILOT_EMAIL','unapproved@example.test'):
            self.assertEqual(self.post(raw).status_code,401)
        self.assertEqual(self.post(raw,token=self.base.fixture.readonly['token']).status_code,401)
        self.assertEqual(self.post(raw).status_code,200)
        with fixture.c.bridge_store.transaction() as conn:fixture.c.query(conn,'UPDATE kilas_trading_control_credentials_v2 SET revoked=1')
        self.assertEqual(self.post(self.payload(2)).status_code,401)
        with fixture.c.bridge_store.transaction() as conn:fixture.c.query(conn,'UPDATE kilas_trading_control_credentials_v2 SET revoked=0')
        self.base.fixture.helper.time=bridge.date(self.base.manifest['expires_at'])
        self.assertEqual(self.post(self.payload(2)).status_code,401)
    def test_evidence_only_rechecks_off_before_nonce_or_capture_commit(self):
        self.evidence_only()
        original=btc.authorize
        def authorize_then_on(*args,**kwargs):
            result=original(*args,**kwargs)
            with fixture.c.bridge_store.transaction() as conn:fixture.c.query(conn,"UPDATE kilas_trading_controls_v2 SET desired_state='ON'")
            return result
        for sequence in (0,1):
            if sequence:
                with fixture.c.bridge_store.transaction() as conn:fixture.c.query(conn,"UPDATE kilas_trading_controls_v2 SET desired_state='OFF'")
                self.assertEqual(self.post(self.payload(0)).status_code,200);self.base.fixture.advance(.1)
            with patch.object(btc,'authorize',side_effect=authorize_then_on):
                self.assertEqual(self.post(self.payload(sequence)).json['outcome'],'EVIDENCE_ONLY_OFF_REQUIRED')
            with self.source.transaction():
                state=self.source.sessions[(f.TradingTests.user,self.base.request['session_id'])]
                self.assertEqual(state['sequence'],0);self.assertFalse(state['records'])
    def test_reject_account_credentials_history_real_and_unknown_fields(self):
        for name in ('account_id','balance','credentials','history','prompt'):
            self.assertEqual(self.post(dict(self.raw,**{name:'private'})).status_code,409)
        for group in ('market','spec','risk'):
            bad=copy.deepcopy(self.raw);bad[group]['balance']=1;self.assertEqual(self.post(bad).status_code,409)
        self.assertEqual(self.post(dict(self.raw,account_mode='REAL')).status_code,409)
        self.assertEqual(self.source.sessions[(f.TradingTests.user,self.base.request['session_id'])]['sequence'],0)
    def test_client_verification_claims_cannot_promote_unaccepted_profile_contract(self):
        for mutate in (lambda p:p['spec'].update(contract_size='100'),lambda p:p['risk'].update(policy_version='f'*64),lambda p:p['risk'].update(broker_contract_sha256='f'*64)):
            bad=copy.deepcopy(self.raw);mutate(bad);self.assertEqual(self.post(bad).status_code,409)
        source=btc_sources.AcceptedSources()
        for field,value in (('producer_acceptance','NOT_IMPLEMENTED'),):
            record=dict(self.acceptance,**{field:value})
            with self.assertRaises(bridge.Rejected):source.install_reviewed(self.base.manifest,record)
    def test_clock_stale_future_malformed_and_cost_precision_rejected(self):
        for mutate in (lambda p:p['market']['capture'].update(end_utc=bridge.stamp(self.base.time+timedelta(seconds=10))),lambda p:p['market']['tick'].update(bid='60000.001'),lambda p:p['risk'].update(captured_at=bridge.stamp(self.base.time-timedelta(seconds=6))),lambda p:p['risk'].update(position_open=True,protection_active=False)):
            bad=copy.deepcopy(self.raw);mutate(bad);self.assertEqual(self.post(bad).status_code,409)
    def test_sequence_capture_replay_owner_scope_and_id_isolation(self):
        news=self.collect();self.review(news);first=self.post();self.assertEqual(first.status_code,200)
        self.assertEqual(self.post().status_code,409);self.assertEqual(self.post(dict(self.raw,sequence=2)).status_code,409)
        ids=first.json['evidence']
        with self.assertRaises(bridge.Rejected):self.source.resolve(f.TradingTests.other,self.base.request['session_id'],ids)
        with self.assertRaises(bridge.Rejected):self.source.resolve(f.TradingTests.user,'e'*32,ids)
        self.assertEqual(self.post(token=self.base.fixture.readonly['token']).status_code,401)
    def test_news_refresh_review_revocation_and_session_restart_fail_closed(self):
        news=self.collect();self.review(news);first=self.post();ids=first.json['evidence']
        self.review(news,'HIGH')
        with self.assertRaises(bridge.Rejected):self.source.resolve(f.TradingTests.user,self.base.request['session_id'],ids)
        self.source.revoke(f.TradingTests.user,self.base.request['session_id'])
        with self.assertRaises(bridge.Rejected):self.source.latest(f.TradingTests.user,self.base.request['session_id'])
        with self.assertRaises(bridge.Rejected):btc_sources.AcceptedSources().session(f.TradingTests.user,self.base.request['session_id'])
    def test_memory_bound_and_expiry(self):
        self.collect()
        # Virtual seventy-second clock exercises cache capacity, not real-time
        # transport-rate limits (covered independently by bridge/control suites).
        with patch('kilas_trading.control_routes.limited',return_value=True):
            for sequence in range(1,71):
                self.assertEqual(self.post(self.payload(sequence)).status_code,200)
                self.advance()
        state=self.source.sessions[(f.TradingTests.user,self.base.request['session_id'])]
        self.assertLessEqual(len(state['records']),64)
        self.base.fixture.helper.time=self.base.time+timedelta(seconds=121)
        with self.assertRaises(bridge.Rejected):self.source.session(f.TradingTests.user,self.base.request['session_id'])
        self.assertFalse(self.source.sessions)
    def test_news_disabled_redirect_empty_stale_xml_and_bounds(self):
        with patch.dict(os.environ,{'KILAS_TRADING_BTC_NEWS_ENABLED':'false'}),patch.object(btc_news.requests,'get') as get:
            with self.assertRaises(bridge.Rejected):btc_news.collect()
            get.assert_not_called()
        for response in (FeedReply(self.feed(),302),FeedReply(b'x'*(btc_news.MAX_BYTES+1)),FeedReply(b'<!DOCTYPE rss><rss/>'),FeedReply('<!DOCTYPE rss><rss/>'.encode('utf-16'))):
            with patch.object(btc_news.requests,'get',return_value=response):
                with self.assertRaises(bridge.Rejected):btc_news.collect()
        for feed in (b'<rss>',b'<rss/>',b'<rss><channel/><channel/></rss>'):
            with self.assertRaises(bridge.Rejected):btc_news.parse(feed,self.base.time)
        for feed in (b'<rss><channel/></rss>',self.feed('Unrelated synthetic headline'),self.feed(date=self.base.time-timedelta(hours=2))):
            record=btc_news.parse(feed,self.base.time)
            self.assertEqual(record['articles'],[]);self.assertEqual(record['event_risk'],'UNKNOWN')
    def test_news_declared_coverage_safe_text_and_no_embedded_urls(self):
        record=btc_news.parse(self.feed('&lt;b&gt;Bitcoin&lt;/b&gt; &amp; data'),self.base.time)
        self.assertEqual(record['articles'][0]['title'],'Bitcoin & data');self.assertEqual(record['coverage'],'BTC_EDITORIAL_ONLY');self.assertEqual(record['event_risk'],'UNKNOWN')
        self.assertEqual(set(record['articles'][0]),{'id','published_at','title'})
    def test_normal_capture_retries_failed_news_after_shared_backoff(self):
        with self.source.transaction():
            self.source.news=None
            self.source.sessions[(f.TradingTests.user,self.base.request['session_id'])].pop('news_retry_at',None)
        with patch.object(btc_news.requests,'get',side_effect=[bridge.Rejected('NEWS_HTTP_UNAVAILABLE'),FeedReply(self.feed())]) as get,patch('kilas_trading.control_routes.limited',return_value=True):
            first=self.post();self.assertEqual(first.status_code,200,first.json)
            self.assertIsNone(first.json['evidence']['news_id']);self.assertEqual(get.call_count,1)
            for sequence in range(2,32):
                self.advance();response=self.post(self.payload(sequence))
                self.assertEqual(response.status_code,200,response.json)
                if sequence<31:self.assertIsNone(response.json['evidence']['news_id']);self.assertEqual(get.call_count,1)
            self.assertEqual(get.call_count,2);self.assertIsNotNone(response.json['evidence']['news_id'])
            self.assertFalse(response.json['execution_authorized'])
    def test_normal_capture_retries_valid_empty_news_after_backoff(self):
        with patch.object(btc_news.requests,'get',return_value=FeedReply(b'<rss><channel/></rss>')):
            empty=self.source.collect_news();self.assertEqual(empty['articles'],[])
        with patch.object(btc_news.requests,'get',return_value=FeedReply(self.feed())) as get,patch('kilas_trading.control_routes.limited',return_value=True):
            first=self.post();self.assertEqual(first.status_code,200,first.json)
            self.assertIsNotNone(first.json['evidence']['news_id']);get.assert_not_called()
            for sequence in range(2,32):
                self.advance();response=self.post(self.payload(sequence))
                self.assertEqual(response.status_code,200,response.json)
                if sequence<31:get.assert_not_called()
            get.assert_called_once()
            current=self.source.resolve(f.TradingTests.user,self.base.request['session_id'],response.json['evidence'])
            self.assertTrue(current['news']['articles']);self.assertEqual(current['news']['risk_review'],'UNREVIEWED')
            self.assertFalse(response.json['execution_authorized'])
    def test_slow_news_retry_keeps_sync_responsive_and_recovers_expired_capture(self):
        command=self.base.fixture.desired('ON');self.assertEqual(command.status_code,200)
        self.base.request.update(revision=command.json['revision'],command_id=command.json['command_id'])
        self.advance();before=self.base.fixture.status()
        with self.source.transaction():
            self.source.news=None
            self.source.sessions[(f.TradingTests.user,self.base.request['session_id'])].pop('news_retry_at',None)
        def delayed_feed(*args,**kwargs):
            for _ in range(6):self.advance()
            return FeedReply(self.feed())
        with patch.object(btc_news.requests,'get',side_effect=delayed_feed) as get:
            expired=self.post(self.payload(1))
            self.assertEqual(expired.json,{'outcome':'CAPTURE_WINDOW_EXPIRED'})
            self.assertEqual(expired.status_code,409)
            recovered=self.post(self.payload(0));self.assertEqual(recovered.status_code,200,recovered.json)
            self.assertEqual(recovered.json['sequence'],0)
            self.base.fixture.advance(.1)
            response=self.post(self.payload(1));self.assertEqual(response.status_code,200,response.json)
            self.assertIsNotNone(response.json['evidence']['news_id']);get.assert_called_once()
        after=self.base.fixture.status()
        self.assertEqual(after['run_expires_at'],before['run_expires_at'])
        self.assertEqual(after['revision'],before['revision']);self.assertEqual(after['run_status'],'ACTIVE')
        self.assertFalse(response.json['execution_authorized'])
    def test_news_retry_backoff_is_shared_between_source_instances(self):
        with self.source.transaction():
            self.source.news=None
            self.source.sessions[(f.TradingTests.user,self.base.request['session_id'])].pop('news_retry_at',None)
        other=btc_sources.AcceptedSources()
        with patch.object(btc_news.requests,'get',side_effect=[bridge.Rejected('NEWS_HTTP_UNAVAILABLE'),FeedReply(self.feed())]) as get:
            self.source.ensure_news();other.ensure_news();self.assertEqual(get.call_count,1)
            self.base.fixture.advance(30)
            other.ensure_news();self.source.ensure_news();self.assertEqual(get.call_count,2)
            self.assertTrue(self.source.news['articles'])
    def test_shared_state_survives_another_worker_and_serializes_duplicate(self):
        other=btc_sources.AcceptedSources()
        self.assertEqual(other.session(f.TradingTests.user,self.base.request['session_id']),self.base.manifest)
        def ingest(adapter):
            try:return adapter.ingest(self.base.fixture.conn['token'],copy.deepcopy(self.raw))['outcome']
            except bridge.Rejected as exc:return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(ingest,[self.source,other]))
        self.assertEqual(outcomes.count('EVIDENCE_ACCEPTED'),1);self.assertEqual(outcomes.count('EVIDENCE_REPLAY_REJECTED'),1)
        self.source.revoke(f.TradingTests.user,self.base.request['session_id'])
        with self.assertRaises(bridge.Rejected):other.session(f.TradingTests.user,self.base.request['session_id'])
    def test_receipt_liveness_accepts_unknown_absolute_clock_without_false_verification(self):
        data=copy.deepcopy(self.raw);data['market']['clock']=None;data['market']['clock_profile']=None
        data['market']['tick']['time']+=10800;data['market']['tick']['time_msc']+=10800000
        for bar in data['market']['candles']:bar['time']+=10800
        for name in ('start_utc','end_utc'):data['market']['capture'][name]=bridge.stamp(bridge.date(data['market']['capture'][name])-timedelta(hours=2))
        data['risk']['captured_at']=data['market']['capture']['end_utc']
        response=self.post(data);self.assertEqual(response.status_code,200,response.json)
        record=self.source.resolve(f.TradingTests.user,self.base.request['session_id'],response.json['evidence'])
        self.assertEqual(record['market']['time_basis'],'RECEIPT_BOUNDED');self.assertFalse(record['market']['clock_verified']);self.assertFalse(record['market']['profile_verified'])
        self.assertEqual(record['market']['quote_time'],data['market']['tick']['time'])
    def test_capture_expiry_can_recover_without_resetting_sequence_or_run(self):
        self.assertEqual(self.post().status_code,200)
        for _ in range(6):self.advance()
        self.assertEqual(self.post(self.payload(2)).json['outcome'],'CAPTURE_WINDOW_EXPIRED')
        before=self.base.fixture.status()
        recovered=self.post(self.payload(0));self.assertEqual(recovered.status_code,200);self.assertEqual(recovered.json['sequence'],1)
        self.base.fixture.advance(.1);self.assertEqual(self.post(self.payload(2)).status_code,200)
        after=self.base.fixture.status();self.assertEqual(before['run_expires_at'],after['run_expires_at']);self.assertEqual(before['revision'],after['revision'])
    def test_first_runtime_authority_with_off_ack_and_shared_concrete_grant(self):
        self.assertEqual(self.post().status_code,200);self.advance();self.assertEqual(self.post(self.payload(2)).status_code,200)
        command=self.base.fixture.desired('ON');self.assertEqual(command.status_code,200)
        self.base.request.update(revision=command.json['revision'],command_id=command.json['command_id'])
        self.advance();snapshot=self.post(self.payload(3));self.assertEqual(snapshot.status_code,200,snapshot.json)
        self.base.request['evidence']=snapshot.json['evidence']
        self.assertEqual(self.base.fixture.status()['actual_state'],'OFF')
        grant=dict(user_id=f.TradingTests.user,session_id=self.base.request['session_id'],policy_version=self.base.manifest['policy_version'],expires_at=self.base.manifest['expires_at'],runtime_eligible=True,broker_execution_allowed=True,policy_replay_only=False,server=bridge.SERVER,instrument='BTC')
        btc_sources.AcceptedSources().install_runtime_authority(f.TradingTests.user,self.base.request['session_id'],grant)
        with patch.dict(os.environ,{'KILAS_TRADING_BTC_RUNTIME_ENABLED':'true'}),self.base.fake():result=self.base.post()
        self.assertEqual(result.status_code,200,result.json);self.assertTrue(result.json['execution_authorized'],result.json)
        self.assertEqual(result.json['revision'],self.base.request['revision']);self.assertIsNotNone(result.json['authorization_expires_at'])
        self.assertLessEqual(bridge.date(result.json['authorization_expires_at']),self.base.fixture.helper.time+timedelta(seconds=5))
        self.assertFalse(self.base.fixture.status()['execution_authorized'])
        self.base.fixture.desired('OFF');self.assertEqual(self.base.post().status_code,409)
    def test_frozen_broker_tick_does_not_become_fresh_by_repeated_capture(self):
        first=self.post();self.assertEqual(first.status_code,200)
        self.advance();data=self.payload(2);second=self.post(data);self.assertEqual(second.json['tick_liveness'],'VERIFIED')
        for sequence in range(3,9):
            self.advance();next_data=self.payload(sequence);next_data['market']['tick']=copy.deepcopy(data['market']['tick']);next_data['market']['candles']=copy.deepcopy(data['market']['candles'])
            result=self.post(next_data);self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['tick_liveness'],'UNCONFIRMED')

if __name__=='__main__':unittest.main()
