"""Offline BTC session/model/risk contracts. All approvals/data/provider calls synthetic."""
import copy
import json
import os
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import threading
import test_kilas_trading as f
import test_kilas_trading_control as c
from kilas_trading import btc_analysis as btc, analysis, analysis_budget as budget, bridge, bridge_store, control, store

PATH='/products/services/trading/control/btc-analysis'

class BTCAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):c.ControlTests.setUpClass()
    def setUp(self):
        self.fixture=c.ControlTests('test_disabled_defaults_no_schema_or_credential_issuance');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.fixture.ready();self.time=self.fixture.helper.time
        self.flags=patch.dict(os.environ,{'KILAS_TRADING_BTC_ANALYSIS_ENABLED':'true','KILAS_TRADING_AI_ENABLED':'true','KILAS_TRADING_BTC_RUNTIME_ENABLED':'false','OPENAI_API_KEY':'synthetic-no-real-key'})
        self.flags.start();self.addCleanup(self.flags.stop)
        self.clock=patch.object(store,'now',lambda:self.fixture.helper.time);self.clock.start();self.addCleanup(self.clock.stop)
        self.request=dict(schema_version=2,operation_key='synthetic-operation-123',session_id='d'*32,revision=0,command_id=None,instrument='BTC',lot='0.01',evidence=dict(market_id='1'*32,news_id='2'*32,spec_id='3'*32))
        self.manifest=dict(user_id=f.TradingTests.user,session_id='d'*32,instrument='BTC',server=bridge.SERVER,created_at=bridge.stamp(self.time),expires_at=bridge.stamp(self.time+timedelta(seconds=120)),model_analysis_allowed=True,policy_version='4'*64,max_loss_cents=1000,max_requests=1)
        close=self.time.replace(second=0,microsecond=0)
        self.evidence=dict(market=dict(id='1'*32,kind='TEST_FIXTURE',provider='TRUSTED_BTC_V1',symbol='BTCUSD',timeframe='M1',captured_at=bridge.stamp(self.time),quote_time=bridge.stamp(self.time),bid_cents=6000000,ask_cents=6001000,clock_verified=True,profile_verified=True,time_basis='VERIFIED_UTC',received_at=bridge.stamp(self.time),freshness_started_at=bridge.stamp(self.time),broker_tick_msc=None,tick_advanced_at=None,candles=[dict(time=bridge.stamp(close-timedelta(minutes=11-i)),open=6000000,high=6002000,low=5998000,close=6000000) for i in range(12)]),news=dict(id='2'*32,provider='TRUSTED_NEWS_V1',as_of=bridge.stamp(self.time),valid_until=bridge.stamp(self.time+timedelta(seconds=120)),verified=True,event_risk='LOW',sentiment=0,coverage='BTC_EDITORIAL_ONLY',risk_review='SERVER_REVIEWED',articles=[dict(id='5'*32,published_at=bridge.stamp(self.time),title='Synthetic evidence, not real market news')]),spec=dict(id='3'*32,symbol='BTCUSD',verified=True,contract_size='1',volume_min='0.01',volume_max='1',volume_step='0.01',tick_cents=100,stops_distance_cents=100,cost_bound_cents=50,verified_at=bridge.stamp(self.time)),risk=dict(captured_at=bridge.stamp(self.time),position_open=False,protection_active=False,daily_loss_remaining_cents=50000,strategy_verified=True,cooldown_clear=True,loss_streak_clear=True))
        self.sources=[patch.object(btc,'approval_source',SimpleNamespace(session=lambda *a:copy.deepcopy(self.manifest))),patch.object(btc,'evidence_source',SimpleNamespace(resolve=lambda *a:copy.deepcopy(self.evidence),latest=lambda *a:copy.deepcopy(getattr(self,'latest_evidence',self.evidence)))),patch.object(btc,'runtime_authorization_source',None)]
        for p in self.sources:p.start();self.addCleanup(p.stop)
        self.calls=[]
    def reply(self,side='BUY'):
        decision=dict(decision=side,news_risk='LOW',reason='Synthetic BTC-only proposal',invalidation='Synthetic',stop_cents=5981000 if side=='BUY' else 6020000,target_cents=6041000 if side=='BUY' else 5960000)
        if side=='WAIT':decision.update(stop_cents=None,target_cents=None)
        return dict(model=budget.MODEL,service_tier='default',status='completed',usage=dict(input_tokens=800,output_tokens=400),output=[dict(type='message',content=[dict(type='output_text',text=json.dumps(decision))])])
    def send(self,method,url,key,body=None):
        self.calls.append((method,url,body));self.assertEqual(key,'synthetic-no-real-key')
        return {'id':budget.MODEL} if method=='GET' else self.reply()
    def post(self,data=None,token=None,**kwargs):
        return self.fixture.helper.local.post(PATH,base_url=c.HOST,json=self.request if data is None else data,headers={'Authorization':'Bearer '+(token or self.fixture.conn['token'])},**kwargs)
    def fake(self):return patch.object(analysis,'_http',side_effect=self.send)
    def test_btc_model_body_no_order_and_false_runtime_by_default(self):
        with self.fake():response=self.post()
        self.assertEqual(response.status_code,200,response.json);self.assertEqual(response.json['outcome'],'PROPOSAL_READY');self.assertFalse(response.json['execution_authorized'])
        self.assertEqual([x[0] for x in self.calls],['GET','POST'])
        body=self.calls[-1][2];self.assertEqual(body['model'],'gpt-6.1-sol');self.assertEqual(body['reasoning'],{'effort':'medium'});self.assertFalse(body['store']);self.assertEqual(body['tools'],[])
        self.assertIn('BTCUSD',body['instructions']);self.assertNotIn('XAUUSD',body['instructions']);self.assertEqual(set(json.loads(body['input'][0]['content'])),{'market','news'})
        self.assertIsNone(analysis.market_source);self.assertFalse(self.fixture.status()['execution_authorized'])
        self.assertEqual(f.db.query_one('SELECT count(*) AS n FROM kilas_trading_positions')['n'],0)
        self.assertNotIn('synthetic-no-real-key',response.text)
    def test_disabled_missing_sources_approval_and_credential_no_provider(self):
        for name,value in (('KILAS_TRADING_BTC_ANALYSIS_ENABLED','false'),('KILAS_TRADING_CONTROL_ENABLED','false'),('KILAS_TRADING_AI_ENABLED','false'),('OPENAI_API_KEY','')):
            with self.subTest(name=name),patch.dict(os.environ,{name:value}),self.fake():self.assertIn(self.post().status_code,(404,409))
        for name in ('evidence_source','approval_source'):
            with patch.object(btc,name,None),self.fake():self.assertEqual(self.post().status_code,409)
        self.assertFalse(self.calls)
    def test_readonly_revoked_expired_wrong_session_gold_denied(self):
        with self.fake():
            self.assertEqual(self.post(token=self.fixture.readonly['token']).status_code,401)
            for field,value in (('session_id','e'*32),('instrument','GOLD'),('revision',1),('lot','0.02')):
                body=dict(self.request,**{field:value});self.assertEqual(self.post(body).status_code,409)
            with bridge_store.transaction() as conn:store.query(conn,'UPDATE kilas_trading_control_credentials_v2 SET revoked=1')
            self.assertEqual(self.post().status_code,401)
        self.assertFalse(self.calls)
    def test_request_account_prompt_upload_and_unknown_fields_denied(self):
        with self.fake():
            for field in ('account','balance','prompt','market','news','url','credentials'):
                self.assertEqual(self.post(dict(self.request,**{field:'private'})).status_code,409)
            for value in (True,'1',1):self.assertEqual(self.post(dict(self.request,schema_version=value)).status_code,409)
        self.assertFalse(self.calls)
    def test_clock_profile_market_news_and_specs_verification_gates(self):
        cases=[('market','clock_verified',False),('market','profile_verified',False),('market','kind','MOCK'),('market','symbol','GOLD'),('market','quote_time',bridge.stamp(self.time-timedelta(seconds=6))),('news','verified',False),('news','valid_until',bridge.stamp(self.time)),('spec','verified',False)]
        with self.fake():
            for group,key,value in cases:
                before=self.evidence[group][key];self.evidence[group][key]=value
                self.assertEqual(self.post().status_code,409,(group,key));self.evidence[group][key]=before
        self.assertFalse(self.calls)
    def test_independent_risk_before_model_unknown_cost_notional_position_news(self):
        cases=[('spec','cost_bound_cents',None,'COSTS_UNKNOWN'),('spec','contract_size','100','NOTIONAL_CAP_BLOCKED'),('risk','position_open',True,'POSITION_OPEN'),('risk','strategy_verified',False,'POLICY_BLOCKED'),('spec','volume_step','0.03','VOLUME_BLOCKED')]
        with self.fake():
            for group,key,value,code in cases:
                before=self.evidence[group][key];self.evidence[group][key]=value
                self.assertEqual(self.post().json['outcome'],code);self.evidence[group][key]=before
        self.assertFalse(self.calls)
    def test_explicit_loss_approval_missing_unapproved_or_expired(self):
        with self.fake():
            for key,value in (('max_loss_cents',None),('max_loss_cents',2001),('model_analysis_allowed',False),('expires_at',bridge.stamp(self.time)),('expires_at',bridge.stamp(self.time+timedelta(seconds=301)))):
                before=self.manifest[key];self.manifest[key]=value;self.assertEqual(self.post().status_code,409);self.manifest[key]=before
        self.assertFalse(self.calls)
    def test_catalog_mismatch_zero_paid_post(self):
        with patch.object(analysis,'_http',return_value={'id':'other'}) as provider:r=self.post()
        self.assertEqual(r.json['outcome'],'MODEL_PREFLIGHT_UNAVAILABLE');self.assertEqual(provider.call_count,1)
        row=f.db.query_one("SELECT inputs_json FROM kilas_trading_events WHERE action='AI_ANALYSIS'");self.assertEqual(json.loads(row['inputs_json'])['cost_upper_micros'],0)
    def test_timeout_holds_reservation_duplicate_does_not_retry(self):
        def send(method,*args):
            self.calls.append(method)
            if method=='GET':return {'id':budget.MODEL}
            raise TimeoutError('private-timeout')
        with patch.object(analysis,'_http',side_effect=send):
            self.assertEqual(self.post().json['outcome'],'MODEL_RESULT_UNAVAILABLE');self.assertEqual(self.post().json['outcome'],'MODEL_RESULT_UNAVAILABLE')
        self.assertEqual(self.calls,['GET','POST'])
        row=f.db.query_one("SELECT inputs_json FROM kilas_trading_events WHERE action='AI_ANALYSIS'");data=json.loads(row['inputs_json']);self.assertEqual(data['cost_upper_micros'],data['reserved_micros'])
    def test_duplicate_same_no_call_changed_request_conflicts(self):
        with self.fake():
            self.assertEqual(self.post().json['outcome'],'PROPOSAL_READY');self.assertEqual(self.post().json['outcome'],'PROPOSAL_READY')
            self.request['evidence']['news_id']='6'*32;self.evidence['news']['id']='6'*32
            self.assertEqual(self.post().json['outcome'],'BTC_OPERATION_CONFLICT')
        self.assertEqual(len(self.calls),2)
    def test_post_model_new_position_stale_revocation_pause_and_flag_off(self):
        mutations=[lambda:self.evidence['risk'].update(position_open=True),lambda:self.fixture.advance(6),lambda:setattr(self,'manifest',dict(self.manifest,model_analysis_allowed=False)),lambda:f.db.execute('UPDATE kilas_trading_accounts SET paused=1'),lambda:os.environ.update(KILAS_TRADING_AI_ENABLED='false')]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                # Different fixture reset per mutation keeps budget/account independent.
                self.evidence['risk']['position_open']=False;self.fixture.helper.time=self.time;self.manifest['model_analysis_allowed']=True;os.environ['KILAS_TRADING_AI_ENABLED']='true'
                f.db.execute('DELETE FROM kilas_trading_events');f.db.execute('UPDATE kilas_trading_accounts SET paused=0')
                def send(method,*args):
                    if method=='GET':return {'id':budget.MODEL}
                    mutation();return self.reply()
                with patch.object(analysis,'_http',side_effect=send):r=self.post()
                self.assertFalse(r.json['execution_authorized']);self.assertNotEqual(r.json['outcome'],'PROPOSAL_READY')
    def test_sltp_and_loss_independent_gate(self):
        self.manifest['max_loss_cents']=100
        with self.fake():r=self.post()
        self.assertEqual(r.json['outcome'],'LOSS_CAP_BLOCKED');self.assertFalse(r.json['execution_authorized'])
        f.db.execute('DELETE FROM kilas_trading_events');self.manifest['max_loss_cents']=1000;self.evidence['spec']['tick_cents']=300
        with self.fake():r=self.post()
        self.assertEqual(r.json['outcome'],'SLTP_BLOCKED')
    def test_runtime_gate_requires_distinct_authority_and_current_live_run(self):
        with f.app.app.app_context():
            evidence=btc.validate(self.evidence,self.request);decision=json.loads(self.reply()['output'][0]['content'][0]['text'])
        self.assertEqual(self.fixture.desired('ON').status_code,200)
        self.fixture.advance();self.assertEqual(self.fixture.sync(self.fixture.ack(actual_state='RUNNING')).status_code,200)
        state=self.fixture.status();self.request.update(revision=state['revision'],command_id=state['command_id']);self.fixture.helper.time=self.time+timedelta(seconds=3)
        authority=dict(user_id=f.TradingTests.user,session_id='d'*32,command_id=self.request['command_id'],revision=self.request['revision'],policy_version='4'*64,expires_at=self.manifest['expires_at'],runtime_eligible=True,broker_execution_allowed=True,policy_replay_only=False,server=bridge.SERVER,instrument='BTC')
        source=SimpleNamespace(authorization=lambda *a:authority)
        with patch.dict(os.environ,{'KILAS_TRADING_BTC_RUNTIME_ENABLED':'true'}),patch.object(btc,'runtime_authorization_source',source):
            scope,_=btc.authorize(self.fixture.conn['token'],self.request)
            self.assertTrue(btc.runtime_gate(scope,self.manifest,self.request,evidence,decision))
            with self.fake():self.assertTrue(self.post().json['execution_authorized'])
            authority['policy_replay_only']=True;self.assertFalse(btc.runtime_gate(scope,self.manifest,self.request,evidence,decision));authority['policy_replay_only']=False
            self.fixture.desired('OFF');self.assertFalse(btc.runtime_gate(scope,self.manifest,self.request,evidence,decision))
        self.assertFalse(self.fixture.status()['execution_authorized'])
    def test_model_protocol_wrong_model_no_usage_denied(self):
        for changed in ({'model':'other'},{'usage':None}):
            f.db.execute('DELETE FROM kilas_trading_events')
            def send(method,*args):return {'id':budget.MODEL} if method=='GET' else dict(self.reply(),**changed)
            with patch.object(analysis,'_http',side_effect=send):r=self.post()
            self.assertEqual(r.json['outcome'],'MODEL_ACCOUNTING_BLOCKED');self.assertFalse(r.json['execution_authorized'])
    def test_concurrent_duplicate_and_off_do_not_wait_for_model(self):
        self.assertEqual(self.fixture.desired('ON').status_code,200);self.fixture.advance()
        self.assertEqual(self.fixture.sync(self.fixture.ack(actual_state='RUNNING')).status_code,200)
        state=self.fixture.status();self.request.update(revision=state['revision'],command_id=state['command_id'])
        entered=threading.Event();release=threading.Event();calls=[]
        def send(method,*args):
            calls.append(method)
            if method=='GET':return {'id':budget.MODEL}
            entered.set();self.assertTrue(release.wait(5));return self.reply()
        with patch.object(analysis,'_http',side_effect=send),ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(self.post);self.assertTrue(entered.wait(5))
            self.assertEqual(self.post().json['outcome'],'MODEL_RESULT_UNAVAILABLE')
            self.assertEqual(self.fixture.desired('OFF').status_code,200)
            release.set();self.assertEqual(future.result(timeout=5).json['outcome'],'POST_MODEL_GATE_BLOCKED')
        self.assertEqual(calls,['GET','POST'])
    def test_model_latency_requires_heartbeat_and_fresh_execution_quote(self):
        def send(method,*args):
            if method=='GET':return {'id':budget.MODEL}
            for _ in range(5):
                self.fixture.advance(2)
                self.assertEqual(self.fixture.sync(self.fixture.ack()).status_code,200)
            self.latest_evidence=copy.deepcopy(self.evidence)
            current=bridge.stamp(self.fixture.helper.time)
            self.latest_evidence['market'].update(id='7'*32,captured_at=current,quote_time=current)
            self.latest_evidence['risk']['captured_at']=current
            return self.reply()
        with patch.object(analysis,'_http',side_effect=send):r=self.post()
        self.assertEqual(r.json['outcome'],'PROPOSAL_READY');self.assertFalse(r.json['execution_authorized'])
    def test_pending_source_risk_change_blocks_before_paid_post(self):
        def send(method,*args):
            self.calls.append(method);self.evidence['risk']['position_open']=True
            return {'id':budget.MODEL}
        with patch.object(analysis,'_http',side_effect=send):r=self.post()
        self.assertEqual(r.json['outcome'],'MODEL_PREFLIGHT_UNAVAILABLE');self.assertEqual(self.calls,['GET'])
    def test_session_cap_and_global_budget_are_not_bypassed(self):
        with self.fake():
            self.assertEqual(self.post().json['outcome'],'PROPOSAL_READY')
            self.request['operation_key']='second-operation-123'
            self.assertEqual(self.post().json['outcome'],'MODEL_SESSION_REQUEST_CAP')
        self.assertEqual(len(self.calls),2)
        f.db.execute('DELETE FROM kilas_trading_events')
        with patch.object(budget,'DAY_CAP',1),self.fake():self.assertEqual(self.post().status_code,503)
        self.assertEqual(len(self.calls),2)
    def test_owner_identity_revocation_cannot_use_worker_route(self):
        with self.fake():
            f.db.execute('DELETE FROM oauth_identities WHERE user_id=?',(f.TradingTests.user,))
            try:self.assertEqual(self.post().status_code,401)
            finally:f.db.execute("INSERT INTO oauth_identities(provider,provider_subject,user_id,email_at_link) VALUES ('google','synthetic-paper-pilot',?,?)",(f.TradingTests.user,'irvankarnavi@gmail.com'))
        self.assertFalse(self.calls)
    def test_exact_endpoint_cookie_host_size_and_json_isolation(self):
        with self.fake():
            self.assertEqual(self.post(query_string={'x':'1'}).status_code,400)
            self.assertEqual(self.fixture.owner.post(PATH,base_url=c.HOST,json=self.request).status_code,400)
            self.assertEqual(self.fixture.helper.local.post(PATH,base_url='https://app.kilasworks.id',json=self.request).status_code,404)
            self.assertEqual(self.fixture.helper.local.post(PATH,base_url=c.HOST,data='x',headers={'Authorization':'Bearer '+self.fixture.conn['token']}).status_code,415)
            self.assertEqual(self.fixture.helper.local.post(PATH,base_url=c.HOST,data=' '*8193,content_type='application/json',headers={'Authorization':'Bearer '+self.fixture.conn['token']}).status_code,413)
        self.assertFalse(self.calls)

    def test_response_exact_identity_stable_decision_and_no_implicit_authority(self):
        with self.fake():first=self.post().json;second=self.post().json
        self.assertEqual(set(first),{'schema_version','outcome','instrument','model','reasoning','decision','news_coverage','risk_state','execution_authorized','checked_at','session_id','operation_key','revision','command_id','evidence','decision_id','authorization_expires_at'})
        self.assertEqual(first['schema_version'],2)
        for key in ('session_id','operation_key','revision','command_id','evidence'):
            self.assertEqual(first[key],self.request[key])
        self.assertEqual(first['decision_id'],second['decision_id'])
        self.assertIsNone(first['authorization_expires_at']);self.assertFalse(first['execution_authorized'])
        self.assertEqual(len(self.calls),2)

    def test_autonomous_news_assessment_preserves_unknown_high_empty_entry_blocks(self):
        self.evidence['news'].update(event_risk='UNKNOWN',risk_review='UNREVIEWED')
        for news_risk,articles,known_risk,outcome in (
            ('LOW',True,'UNKNOWN','PROPOSAL_READY'),('HIGH',True,'UNKNOWN','NEWS_RISK_BLOCKED'),
            ('UNKNOWN',True,'UNKNOWN','NEWS_RISK_BLOCKED'),('LOW',False,'UNKNOWN','NEWS_RISK_BLOCKED'),
            ('LOW',True,'HIGH','NEWS_RISK_BLOCKED')):
            with self.subTest(news_risk=news_risk,articles=articles,known_risk=known_risk):
                f.db.execute('DELETE FROM kilas_trading_events')
                news=self.evidence['news'];news['event_risk']=known_risk
                news['articles']=[dict(id='5'*32,published_at=bridge.stamp(self.time),title='Synthetic BTC news')] if articles else []
                reply=self.reply();decision=json.loads(reply['output'][0]['content'][0]['text']);decision['news_risk']=news_risk
                reply['output'][0]['content'][0]['text']=json.dumps(decision)
                with patch.object(analysis,'_http',side_effect=lambda method,*args:{'id':budget.MODEL} if method=='GET' else reply) as provider:
                    response=self.post().json
                self.assertEqual(provider.call_count,2);self.assertEqual(response['outcome'],outcome)
                self.assertFalse(response['execution_authorized']);self.assertIsNone(response['authorization_expires_at'])

    def test_missing_invalid_or_extra_model_classification_rejected(self):
        for news in (None,'GLOBAL_LOW',True):
            f.db.execute('DELETE FROM kilas_trading_events')
            reply=self.reply();decision=json.loads(reply['output'][0]['content'][0]['text'])
            if news is None:decision.pop('news_risk')
            else:decision['news_risk']=news
            reply['output'][0]['content'][0]['text']=json.dumps(decision)
            with patch.object(analysis,'_http',side_effect=lambda method,*args:{'id':budget.MODEL} if method=='GET' else reply):response=self.post().json
            self.assertEqual(response['outcome'],'POST_MODEL_GATE_BLOCKED');self.assertFalse(response['execution_authorized'])

    def test_final_off_or_revision_change_cannot_pass_prior_runtime_gate(self):
        self.assertEqual(self.fixture.desired('ON').status_code,200);self.fixture.advance()
        self.assertEqual(self.fixture.sync(self.fixture.ack()).status_code,200)
        state=self.fixture.status();self.request.update(revision=state['revision'],command_id=state['command_id'])
        authority=dict(user_id=f.TradingTests.user,session_id='d'*32,command_id=self.request['command_id'],revision=self.request['revision'],policy_version='4'*64,expires_at=self.manifest['expires_at'],runtime_eligible=True,broker_execution_allowed=True,policy_replay_only=False,server=bridge.SERVER,instrument='BTC')
        decision=json.loads(self.reply()['output'][0]['content'][0]['text'])
        for change in ({'effective_desired_state':'OFF'},{'revision':state['revision']+1},{'command_id':'f'*32}):
            with patch.object(btc,'_analyze',return_value=btc.result('PROPOSAL_READY',decision)), \
                 patch.object(btc,'runtime_gate',return_value=True), \
                 patch.object(btc,'runtime_authorization_source',SimpleNamespace(authorization=lambda *a:authority)), \
                 patch.object(control,'status',return_value=dict(state,**change)):
                response=self.post().json
            self.assertEqual(response['outcome'],'POST_MODEL_GATE_BLOCKED');self.assertFalse(response['execution_authorized'])
            self.assertIsNone(response['authorization_expires_at'])

if __name__=='__main__':unittest.main()
