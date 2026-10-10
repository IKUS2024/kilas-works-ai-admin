"""Real Flask HTTP integration with synthetic DEMO SDK; no broker or paid calls."""
import copy
import io
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
import sys
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import test_kilas_trading as f
from kilas_trading import bridge, bridge_store, bridge_routes, analysis, observation
from werkzeug.serving import make_server

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('demo_collector',ROOT/'scripts/trading_demo_bridge/collector.py')
collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
HOST='https://trading.kilasworks.id'
PATH='/products/services/trading/bridge'
EXE=r'C:\SyntheticMT5\terminal64.exe'
DATA=r'C:\SyntheticData\Terminal'

def terminal(**changes):
    values=dict(connected=True,tradeapi_disabled=True,trade_allowed=False,path=r'C:\SyntheticMT5',data_path=DATA,commondata_path=r'C:\SyntheticData\Common',build=5000,name='Synthetic MT5',company='Synthetic')
    values.update(changes)
    return SimpleNamespace(**values)

def market(symbol='GOLD', tick=1780000031):
    last=tick//60*60-60
    return dict(symbol=symbol,timeframe='M1',tick=dict(time=tick,time_msc=tick*1000,bid='4195',ask='4195.5'),
                capture=dict(start_utc='2026-10-10T12:00:00Z',end_utc='2026-10-10T12:00:00.1Z',start_mono_ns=100,end_mono_ns=100000100),
                candles=[dict(time=last-60*(11-i),open='4195',high='4196',low='4194',close='4195') for i in range(12)],
                clock=None,clock_profile=None)

class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not hasattr(f.TradingTests,'user'): f.TradingTests.setUpClass()
        bridge_store.apply_release()
    def setUp(self):
        self.base=f.TradingTests('test_xauusd_contract_and_units');self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.env=patch.dict(os.environ,{'KILAS_TRADING_BRIDGE_ENABLED':'true'});self.env.start();self.addCleanup(self.env.stop)
        with bridge_store.transaction() as conn: f.store.query(conn,'DELETE FROM kilas_trading_bridges')
        bridge_routes._rates.clear()
        self.time=datetime(2026,10,10,12,tzinfo=timezone.utc)
        self.clock=patch.object(bridge,'now',lambda:self.time);self.clock.start();self.addCleanup(self.clock.stop)
        self.owner=self.client(f.TradingTests.user)
        self.local=f.app.app.test_client(use_cookies=False)
    def client(self,user=None):
        c=f.app.app.test_client()
        if user:
            with c.session_transaction(base_url=HOST) as s: s.update(user_id=user,_csrf_token='bridge-test-csrf')
        return c
    def post(self,path,data,token=None,client=None,**kwargs):
        headers={'Authorization':'Bearer '+token} if token else {}
        headers.update(kwargs.pop('headers',{}))
        return (client or self.local).post(PATH+'/'+path,base_url=HOST,json=data,headers=headers,**kwargs)
    def pair(self,symbol='GOLD'):
        return self.post('pair',dict(symbol=symbol,server=bridge.SERVER),client=self.owner,headers={'X-CSRF-Token':'bridge-test-csrf'})
    def connect(self,symbol='GOLD'):
        pair=self.pair(symbol);self.assertEqual(pair.status_code,200)
        result=self.post('exchange',dict(pair_code=pair.json['pair_code'],symbol=symbol,server=bridge.SERVER))
        self.assertEqual(result.status_code,200);return result.json
    def payload(self,conn,m=None):
        return dict(schema_version=1,sequence=conn['sequence']+1,server_challenge=conn['challenge'],message_kind='MARKET' if m else 'HEARTBEAT',server=bridge.SERVER,account_mode='DEMO' if m else 'UNKNOWN',terminal_connected=bool(m),market=m,**{k:False for k in bridge.FLAGS})
    def send(self,conn,m=None): return self.post('telemetry',self.payload(conn,m),conn['token'])
    def view(self): return self.owner.get(PATH+'/status',base_url=HOST)

    def test_default_disabled_routes_and_dashboard(self):
        with patch.dict(os.environ,{'KILAS_TRADING_BRIDGE_ENABLED':'false'}):
            self.assertEqual(self.pair().status_code,404)
            self.assertEqual(self.post('exchange',{}).status_code,404)
            self.assertEqual(self.view().status_code,200)
            self.assertEqual(bridge.status(f.TradingTests.user)['outcome'],'DISABLED')
    def test_off_revoke_preserves_auth_csrf_and_invalidates_existing_token(self):
        conn=self.connect('BTCUSD')
        with patch.dict(os.environ,{'KILAS_TRADING_BRIDGE_ENABLED':'false'}):
            self.assertEqual(self.post('revoke',{},client=self.owner).status_code,400)
            for user in (f.TradingTests.other,f.TradingTests.admin):
                self.assertEqual(self.post('revoke',{},client=self.client(user),headers={'X-CSRF-Token':'bridge-test-csrf'}).status_code,404)
            self.assertEqual(self.post('revoke',{},client=self.owner,headers={'X-CSRF-Token':'bridge-test-csrf'}).json['outcome'],'REVOKED')
            self.assertEqual(self.pair('BTCUSD').status_code,404)
            self.assertEqual(self.send(conn).status_code,404)
            view=self.view().json;self.assertTrue(view['revoked']);self.assertFalse(view['revoke_allowed'])
            self.assertTrue(view['exchange_completed']);self.assertEqual(view['last_confirmed_stage'],'EXCHANGE_ACCEPTED')
        self.assertEqual(self.send(conn).status_code,401)
        row=f.db.query_one('SELECT * FROM kilas_trading_bridges')
        for key in ('pair_hash','token_hash','challenge_hash','market_json'):self.assertIsNone(row[key])

    def test_off_status_retains_confirmed_progress_without_market_or_secrets(self):
        conn=self.connect('BTCUSD');self.assertEqual(self.send(conn,market('BTCUSD')).status_code,200)
        with patch.dict(os.environ,{'KILAS_TRADING_BRIDGE_ENABLED':'false'}):
            response=self.view();self.assertEqual(response.status_code,200)
            data=response.json;self.assertEqual(data['outcome'],'DISABLED')
            self.assertEqual(data['transport'],'DISCONNECTED');self.assertNotIn('market',data)
            self.assertEqual(data['last_confirmed_stage'],'TELEMETRY_ACCEPTED');self.assertEqual(data['accepted_messages'],1)
            self.assertEqual(data['last_error'],'NOT_RECORDED');self.assertTrue(data['revoke_allowed'])
            for key in ('token','challenge','token_hash','challenge_hash','pair_hash','pair_code'):self.assertNotIn(key,data)
            for value in (conn['token'],conn['challenge']):self.assertNotIn(value,response.get_data(as_text=True))

    def test_off_status_requires_pilot_and_tolerates_uninstalled_schema(self):
        with patch.dict(os.environ,{'KILAS_TRADING_BRIDGE_ENABLED':'false'}):
            for user in (f.TradingTests.other,f.TradingTests.admin):self.assertEqual(self.client(user).get(PATH+'/status',base_url=HOST).status_code,404)
            with patch.object(bridge_store,'transaction',side_effect=RuntimeError('synthetic-private-error')):
                data=self.view().json;self.assertEqual(data['outcome'],'DISABLED');self.assertEqual(data['history_status'],'UNAVAILABLE')
                self.assertFalse(data['revoke_allowed']);self.assertNotIn('synthetic-private-error',json.dumps(data))
    def test_pair_requires_session_csrf_and_exact_pilot(self):
        self.assertEqual(self.post('pair',{},client=self.owner).status_code,400)
        for user in (f.TradingTests.other,f.TradingTests.admin):
            self.assertEqual(self.post('pair',{'symbol':'GOLD','server':bridge.SERVER},client=self.client(user),headers={'X-CSRF-Token':'bridge-test-csrf'}).status_code,404)
        self.assertEqual(self.post('pair',{}).status_code,400)
    def test_host_guard_precedes_bearer_handler(self):
        for host in ('https://app.kilasworks.id','https://kilas-works-client-hub.onrender.com'):
            self.assertEqual(self.local.post(PATH+'/exchange',base_url=host,json={}).status_code,404)
        self.assertEqual(self.local.post(PATH+'/exchange',base_url='https://evil.test',json={}).status_code,400)
    def test_exchange_cookie_and_query_never_authorize(self):
        code=self.pair().json['pair_code'];body=dict(pair_code=code,symbol='GOLD',server=bridge.SERVER)
        self.assertEqual(self.post('exchange',body,client=self.owner).status_code,400)
        self.assertEqual(self.local.post(PATH+'/exchange?token=secret',base_url=HOST,json=body).status_code,400)
    def test_pair_secret_hashes_one_use_and_scope(self):
        code=self.pair().json['pair_code']
        wrong=self.post('exchange',dict(pair_code=code,symbol='BTCUSD',server=bridge.SERVER));self.assertEqual(wrong.status_code,401)
        body=dict(pair_code=code,symbol='GOLD',server=bridge.SERVER)
        result=self.post('exchange',body);self.assertEqual(result.status_code,200)
        self.assertEqual(self.post('exchange',body).status_code,401)
        row=f.db.query_one('SELECT * FROM kilas_trading_bridges WHERE user_id=?',(f.TradingTests.user,))
        self.assertIsNone(row['pair_hash']);self.assertEqual(row['token_hash'],bridge.digest(result.json['token']))
        self.assertNotIn(code,json.dumps(row));self.assertNotIn(result.json['token'],json.dumps(row))
        self.assertEqual(datetime.fromisoformat(row['token_expires'])-self.time,timedelta(hours=1))
        self.assertEqual(result.headers['Cache-Control'],'no-store')
    def test_pair_expires_and_rate_limit(self):
        code=self.pair().json['pair_code'];self.assertEqual(self.pair().status_code,429)
        self.time+=timedelta(minutes=5)
        self.assertEqual(self.post('exchange',dict(pair_code=code,symbol='GOLD',server=bridge.SERVER)).status_code,401)
        self.assertEqual(self.view().json['outcome'],'PAIR_EXPIRED')
    def test_repair_invalidates_previous_token(self):
        conn=self.connect();self.time+=timedelta(seconds=31)
        self.assertEqual(self.pair('BTCUSD').status_code,200)
        self.assertEqual(self.send(conn,market()).status_code,401)
    def test_token_expiry_and_revocation_clear_market(self):
        conn=self.connect();self.assertEqual(self.send(conn,market()).status_code,200)
        revoke=self.post('revoke',{},client=self.owner,headers={'X-CSRF-Token':'bridge-test-csrf'})
        self.assertEqual(revoke.status_code,200);self.assertEqual(self.send(conn).status_code,401)
        self.assertEqual(self.view().json['outcome'],'REVOKED');self.assertNotIn('market',self.view().json)
    def test_hour_expiry(self):
        conn=self.connect();self.time+=timedelta(hours=1)
        self.assertEqual(self.send(conn).status_code,401);self.assertEqual(self.view().json['outcome'],'TOKEN_EXPIRED')
    def test_token_scope_and_other_tenant_no_status_or_revoke(self):
        conn=self.connect('BTCUSD');self.assertEqual(self.send(conn,market()).status_code,409)
        self.assertEqual(self.send(conn,market('BTCUSD')).status_code,200)
        other=self.client(f.TradingTests.other)
        self.assertEqual(other.get(PATH+'/status',base_url=HOST).status_code,404)
        self.assertEqual(self.post('revoke',{},client=other,headers={'X-CSRF-Token':'bridge-test-csrf'}).status_code,404)
    def test_transport_heartbeat_and_clock_claim_never_qualify(self):
        conn=self.connect();m=market();result=self.send(conn,m);self.assertEqual(result.status_code,200)
        self.assertEqual(self.view().json['transport'],'CONNECTED')
        self.time+=timedelta(seconds=2);conn.update(result.json)
        m=market(tick=m['tick']['time']+1)
        m['clock']=dict(status='PRODUCER_CLAIM_ONLY',offset_seconds='0',uncertainty_ms='1')
        m['clock_profile']=dict(profile_id='candidate',candidate_offset_seconds=10800,evidence_ref='unverified')
        self.assertEqual(self.send(conn,m).status_code,200)
        view=self.view().json
        self.assertEqual(view['market_freshness'],'UNVERIFIED_CLOCK_PROFILE');self.assertEqual(view['source_max_age_seconds'],5)
        for k in bridge.FLAGS:self.assertIs(view[k],False)
        self.assertIsNone(analysis.market_source)
    def test_nonadvancing_and_backwards_ticks(self):
        conn=self.connect();m=market();result=self.send(conn,m);conn.update(result.json)
        self.time+=timedelta(seconds=2);result=self.send(conn,m);self.assertEqual(result.status_code,200)
        self.assertEqual(self.view().json['market_freshness'],'NONADVANCING_OR_FIRST_OBSERVATION')
        conn.update(result.json);self.time+=timedelta(seconds=2)
        self.assertEqual(self.send(conn,market(tick=m['tick']['time']-1)).status_code,409)
    def test_stale_and_disconnect_do_not_show_fresh(self):
        conn=self.connect();self.send(conn,market());self.time+=timedelta(seconds=7)
        self.assertEqual(self.view().json['transport'],'STALE');self.assertEqual(self.view().json['market_freshness'],'UNAVAILABLE_TRANSPORT_STALE')
        self.time+=timedelta(seconds=9);self.assertEqual(self.view().json['transport'],'DISCONNECTED')
    def test_terminal_failure_clears_quote(self):
        conn=self.connect();conn.update(self.send(conn,market()).json);self.time+=timedelta(seconds=2)
        self.assertEqual(self.send(conn).status_code,200);self.assertNotIn('market',self.view().json)
        self.assertEqual(self.view().json['terminal'],'DISCONNECTED_OR_UNKNOWN')
    def test_sequence_challenge_and_expiry_reject_replay(self):
        conn=self.connect();body=self.payload(conn,market());self.assertEqual(self.post('telemetry',body,conn['token']).status_code,200)
        self.time+=timedelta(seconds=2);self.assertEqual(self.post('telemetry',body,conn['token']).status_code,409)
        body['sequence']=2;self.assertEqual(self.post('telemetry',body,conn['token']).status_code,409)
    def test_old_challenge_and_rate_limit(self):
        conn=self.connect();self.time+=timedelta(seconds=10)
        self.assertEqual(self.send(conn).status_code,409)
    def test_one_second_message_limit_keeps_next_challenge(self):
        conn=self.connect();conn.update(self.send(conn,market()).json)
        body=self.payload(conn,market(tick=1780000032))
        self.assertEqual(self.post('telemetry',body,conn['token']).status_code,429)
        self.time+=timedelta(seconds=2)
        self.assertEqual(self.post('telemetry',body,conn['token']).status_code,200)
    def test_disabled_bridge_does_not_create_schema_or_credentials(self):
        with patch.dict(os.environ,{'KILAS_TRADING_BRIDGE_ENABLED':'false'}):
            with patch.object(bridge_store,'transaction',side_effect=AssertionError('no DB access')):
                self.assertEqual(bridge.status(f.TradingTests.user)['outcome'],'DISABLED')
                self.assertEqual(self.post('exchange',{}).status_code,404)
    def test_schema_unavailable_status_without_automatic_install(self):
        with patch.object(bridge_store,'transaction',side_effect=RuntimeError('private-db-sentinel')):
            r=self.view();self.assertEqual(r.status_code,200)
            self.assertEqual(r.json['outcome'],'SCHEMA_UNAVAILABLE');self.assertNotIn('private-db-sentinel',r.text)
    def test_pair_revoke_form_contract(self):
        r=self.owner.post(PATH+'/pair',base_url=HOST,data={'csrf_token':'bridge-test-csrf','symbol':'GOLD','server':bridge.SERVER})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.owner.post(PATH+'/revoke',base_url=HOST,data={'csrf_token':'bridge-test-csrf'}).status_code,200)
    def test_request_abuse_limit_bounded(self):
        for _ in range(60):self.post('exchange',{})
        self.assertEqual(self.post('exchange',{}).status_code,429)
        self.assertLessEqual(len(bridge_routes._rates),1024)
    def test_terminal_unknown_never_exposes_cached_market(self):
        conn=self.connect();body=self.payload(conn,market());body['account_mode']='UNKNOWN'
        self.assertEqual(self.post('telemetry',body,conn['token']).status_code,409)
    def test_credentials_not_in_status_or_error(self):
        conn=self.connect();r=self.view();self.assertNotIn(conn['token'],r.text);self.assertNotIn(conn['challenge'],r.text)
        self.assertEqual(self.send(dict(conn,token='x'*64)).status_code,401)
    def test_collector_transport_failure_stops_without_retry(self):
        class Broken:
            def post(self,*a,**k):raise collector.CollectorError('Transport failed')
        with self.assertRaises(collector.CollectorError):collector.Session(Broken(),'GOLD','a'*32)
    def test_collector_no_connect_mode_has_no_sdk_or_http(self):
        import sys
        with patch.object(sys,'argv',['collector','--symbol','GOLD']),patch.object(collector,'Transport',side_effect=AssertionError('no HTTP')):
            self.assertEqual(collector.main(),0)
    def test_forwarded_host_does_not_open_app_transport(self):
        r=self.local.post(PATH+'/exchange',base_url='https://app.kilasworks.id',json={},headers={'X-Forwarded-Host':'trading.kilasworks.id'})
        self.assertEqual(r.status_code,404)
    def test_capture_wall_interval_cannot_go_backwards(self):
        m=market();m['capture'].update(end_utc='2026-10-10T11:59:59.99Z',end_mono_ns=1000100)
        with self.assertRaises(bridge.Rejected):bridge.validate_market(m,'GOLD')
    def test_receipt_future_not_connected(self):
        conn=self.connect();self.send(conn,market());self.time-=timedelta(seconds=1)
        status=self.view().json
        self.assertEqual(status['transport'],'DISCONNECTED');self.assertEqual(status['outcome'],'SERVER_CLOCK_DISCONTINUITY')
        self.assertNotIn('market',status)
    def test_pair_not_valid_before_issuance(self):
        code=self.pair().json['pair_code'];self.time-=timedelta(seconds=1)
        self.assertEqual(self.post('exchange',dict(pair_code=code,symbol='GOLD',server=bridge.SERVER)).status_code,401)
    def test_token_not_valid_before_issuance(self):
        conn=self.connect();self.time-=timedelta(seconds=1)
        self.assertEqual(self.send(conn).status_code,401)
    def test_concurrent_exchange_consumes_pair_code_once(self):
        code=self.pair().json['pair_code'];body=dict(pair_code=code,symbol='GOLD',server=bridge.SERVER)
        def exchange(_):return self.post('exchange',body,client=f.app.app.test_client(use_cookies=False)).status_code
        with ThreadPoolExecutor(max_workers=2) as pool: statuses=list(pool.map(exchange,range(2)))
        self.assertEqual(sorted(statuses),[200,401])
    def test_concurrent_duplicate_telemetry_consumes_challenge_once(self):
        conn=self.connect();body=self.payload(conn,market())
        def send(_):return self.post('telemetry',body,conn['token'],client=f.app.app.test_client(use_cookies=False)).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(send,range(2)))
        self.assertEqual(sorted(statuses),[200,409])
    def test_strict_private_and_active_flag_rejection(self):
        conn=self.connect();original=self.payload(conn,market())
        for key in ('account','balance','history','tenant_id','login','specs'):
            body=copy.deepcopy(original);body[key]='PRIVATE_SENTINEL'
            response=self.post('telemetry',body,conn['token']);self.assertEqual(response.status_code,409)
            self.assertNotIn('PRIVATE_SENTINEL',response.text)
        for key in bridge.FLAGS:
            body=copy.deepcopy(original);body[key]=True;self.assertEqual(self.post('telemetry',body,conn['token']).status_code,409)
    def test_market_boundaries_capture_candles_profile_and_prices(self):
        for modify in (lambda m:m['candles'].pop(),lambda m:m['tick'].update(bid='NaN'),lambda m:m['tick'].update(time_msc=1),lambda m:m['capture'].update(end_mono_ns=0),lambda m:m['candles'][1].update(time=1),lambda m:m.update(clock_profile={'approved':True}),lambda m:m['candles'][0].update(high='1')):
            m=market();modify(m)
            with self.assertRaises(bridge.Rejected): bridge.validate_market(m,'GOLD')
    def test_invalid_size_duplicate_and_content_type(self):
        for body in ('{"pair_code":1,"pair_code":2}','{"pair_code":NaN}','bad'):
            r=self.local.post(PATH+'/exchange',base_url=HOST,data=body,content_type='application/json');self.assertEqual(r.status_code,409)
        self.assertEqual(self.local.post(PATH+'/exchange',base_url=HOST,data=' '*16385,content_type='application/json').status_code,413)
        self.assertEqual(self.local.post(PATH+'/exchange',base_url=HOST,data={}).status_code,415)
    def test_identity_revocation_and_feature_disable(self):
        conn=self.connect()
        with patch.dict(os.environ,{'KILAS_TRADING_ENABLED':'false'}):self.assertEqual(self.send(conn).status_code,401)
        with patch.dict(os.environ,{'KILAS_TRADING_BRIDGE_ENABLED':'false'}):self.assertEqual(self.send(conn).status_code,404)
    def test_existing_csrf_and_upload_unchanged(self):
        self.connect()
        self.assertEqual(self.owner.post('/products/services/trading/analyze',base_url=HOST,json={}).status_code,400)
        self.assertEqual(observation.MAX_FILE_BYTES,8192);self.assertIsNone(analysis.market_source)
    def test_migration_additive_idempotent(self):
        self.assertEqual(bridge_store.apply_release(),[])
        self.assertEqual(f.db.query_one('SELECT count(*) AS n FROM kilas_trading_accounts')['n'],0)
    def test_collector_session_end_to_end_flask_http(self):
        code=self.pair('BTCUSD').json['pair_code']
        test=self
        class HTTP:
            def post(self,path,data,token=None):
                response=test.post(path,data,token);test.assertEqual(response.status_code,200);return response.json
        session=collector.Session(HTTP(),'BTCUSD',code)
        session.send(market('BTCUSD'));self.time+=timedelta(seconds=2);session.send(market('BTCUSD',1780000032))
        self.assertEqual(self.view().json['symbol'],'BTCUSD');self.assertEqual(session.sequence,2)
        session.clear();self.assertIsNone(session.token)
    def test_sdk_facade_excludes_account_data_and_binds_identity(self):
        m=market();account=SimpleNamespace(trade_mode=0,server=bridge.SERVER,login=987654)
        sdk=SimpleNamespace(TIMEFRAME_M1=1,terminal_info=lambda:terminal(),account_info=lambda:account,symbol_info=lambda s:SimpleNamespace(name=s,visible=True),symbol_info_tick=lambda s:SimpleNamespace(**m['tick']),copy_rates_from_pos=lambda *args:m['candles'])
        sample=collector.ReadOnlyMT5(sdk,'GOLD',EXE,DATA).sample();bridge.validate_market(sample,'GOLD')
        self.assertNotIn('987654',json.dumps(sample));self.assertIsNone(sample['clock_profile'])
        reader=collector.ReadOnlyMT5(sdk,'GOLD',EXE,DATA);reader.verify();account.login=456
        with self.assertRaises(collector.CollectorError):reader.verify()
    def test_sdk_real_mode_and_enabled_trading_blocked(self):
        account=SimpleNamespace(trade_mode=2,server=bridge.SERVER,login=1)
        sdk=SimpleNamespace(terminal_info=lambda:terminal(),account_info=lambda:account)
        with self.assertRaises(collector.CollectorError):collector.ReadOnlyMT5(sdk,'GOLD',EXE,DATA).verify()
        account.trade_mode=0;sdk.terminal_info=lambda:terminal(tradeapi_disabled=False)
        with self.assertRaises(collector.CollectorError):collector.ReadOnlyMT5(sdk,'GOLD',EXE,DATA).verify()

    def synthetic_sdk(self):
        value=terminal();m=market()
        return SimpleNamespace(TIMEFRAME_M1=1,initialize=Mock(return_value=True),shutdown=Mock(),
            terminal_info=Mock(side_effect=lambda:value),
            account_info=Mock(return_value=SimpleNamespace(trade_mode=0,server=bridge.SERVER,login=1)),
            symbol_info=Mock(side_effect=lambda name:SimpleNamespace(name=name,visible=True)),
            symbol_info_tick=Mock(return_value=SimpleNamespace(**m['tick'])),
            copy_rates_from_pos=Mock(return_value=m['candles'])),value

    def test_collector_initializes_only_pinned_path_and_five_second_timeout(self):
        sdk,_=self.synthetic_sdk()
        reader=collector.initialize_terminal(sdk,'GOLD',EXE,DATA)
        sdk.initialize.assert_called_once_with(EXE,timeout=5000)
        self.assertEqual(reader.data_path,collector.windows_path(DATA))
        self.assertIsNotNone(reader.terminal_identity)

    def test_collector_initialize_failure_has_no_identity_or_market_reads(self):
        sdk,_=self.synthetic_sdk();sdk.initialize.return_value=False
        with self.assertRaises(collector.CollectorError):collector.initialize_terminal(sdk,'GOLD',EXE,DATA)
        sdk.initialize.assert_called_once_with(EXE,timeout=5000)
        sdk.terminal_info.assert_not_called();sdk.account_info.assert_not_called()
        sdk.symbol_info_tick.assert_not_called()

    def test_collector_connect_missing_pins_cannot_initialize_or_exchange(self):
        sdk,_=self.synthetic_sdk()
        for args in ([],['--terminal-path',EXE],['--terminal-data-path',DATA]):
            with self.subTest(args=args),patch.object(sys,'argv',['collector','--symbol','GOLD','--connect']+args),patch.dict(sys.modules,{'MetaTrader5':sdk}),patch.object(collector,'Transport',side_effect=AssertionError('no HTTP')):
                self.assertEqual(collector.main(),2)
        sdk.initialize.assert_not_called();sdk.shutdown.assert_not_called()

    def test_collector_connect_init_failure_shuts_down_without_pairing(self):
        sdk,_=self.synthetic_sdk();sdk.initialize.return_value=False
        with patch.object(sys,'argv',['collector','--symbol','GOLD','--connect','--terminal-path',EXE,'--terminal-data-path',DATA]),patch.dict(sys.modules,{'MetaTrader5':sdk}),patch.object(collector,'os',SimpleNamespace(name='nt')),patch.object(collector,'Path',return_value=SimpleNamespace(is_file=lambda:True,is_dir=lambda:True)),patch.object(collector,'Transport',side_effect=AssertionError('no HTTP')),patch.object(collector.getpass,'getpass',side_effect=AssertionError('no pairing')):
            self.assertEqual(collector.main(),2)
        sdk.initialize.assert_called_once_with(EXE,timeout=5000);sdk.shutdown.assert_called_once_with()

    def test_collector_rejects_ambiguous_remote_or_nonterminal_paths(self):
        for value in (None,'terminal64.exe',r'C:terminal64.exe',r'\\host\share\terminal64.exe',r'\\?\C:\MT5\terminal64.exe',r'C:\MT5\..\terminal64.exe',r'C:\MT5\terminal64.exe:stream',r'C:\MT5.\terminal64.exe',r'C:\MT5\other.exe'):
            with self.subTest(value=value),self.assertRaises(collector.CollectorError):collector.binding_paths(value,DATA)
        self.assertEqual(collector.binding_paths('c:/SYNTHETICMT5/terminal64.exe',DATA)[0],collector.windows_path(EXE))

    def test_collector_initial_terminal_install_or_data_mismatch_blocks_account_read(self):
        for field in ('path','data_path'):
            sdk,value=self.synthetic_sdk();setattr(value,field,r'C:\WrongTerminal')
            with self.subTest(field=field),self.assertRaises(collector.CollectorError):collector.initialize_terminal(sdk,'GOLD',EXE,DATA)
            sdk.account_info.assert_not_called();sdk.symbol_info_tick.assert_not_called()

    def test_collector_terminal_identity_changes_during_tick_stop_before_bars(self):
        for field,new in [('path',r'C:\OtherMT5'),('data_path',r'C:\OtherData'),('commondata_path',r'C:\OtherCommon'),('build',5001),('name','Other'),('company','Other')]:
            sdk,value=self.synthetic_sdk();reader=collector.initialize_terminal(sdk,'GOLD',EXE,DATA)
            def changed(symbol):
                setattr(value,field,new);return SimpleNamespace(**market()['tick'])
            sdk.symbol_info_tick.side_effect=changed
            with self.subTest(field=field),self.assertRaises(collector.CollectorError):reader.sample()
            sdk.copy_rates_from_pos.assert_not_called()

    def test_collector_terminal_data_changes_during_bars_never_emit_sample(self):
        sdk,value=self.synthetic_sdk();reader=collector.initialize_terminal(sdk,'GOLD',EXE,DATA)
        def changed(*args):value.data_path=r'C:\OtherData';return market()['candles']
        sdk.copy_rates_from_pos.side_effect=changed
        with self.assertRaises(collector.CollectorError):reader.sample()

    def test_collector_terminal_changes_during_account_read_stop_before_symbol(self):
        sdk,value=self.synthetic_sdk()
        def changed():value.data_path=r'C:\OtherData';return SimpleNamespace(trade_mode=0,server=bridge.SERVER,login=1)
        sdk.account_info.side_effect=changed
        with self.assertRaises(collector.CollectorError):collector.initialize_terminal(sdk,'GOLD',EXE,DATA)
        sdk.symbol_info.assert_not_called()

    def test_collector_algo_off_does_not_substitute_for_python_trade_disable(self):
        sdk,value=self.synthetic_sdk();value.trade_allowed=False;value.tradeapi_disabled=False
        with self.assertRaisesRegex(collector.CollectorError,'External Python trading is not disabled'):collector.initialize_terminal(sdk,'GOLD',EXE,DATA)
        sdk.account_info.assert_not_called()
        value.tradeapi_disabled=True
        reader=collector.initialize_terminal(sdk,'GOLD',EXE,DATA)
        sample=reader.sample();bridge.validate_market(sample,'GOLD')
        self.assertNotIn('SyntheticData',json.dumps(sample));self.assertNotIn('terminal',sample)

    def test_collector_sdk_call_allowlist_is_unchanged_and_excludes_execution(self):
        import ast
        tree=ast.parse((ROOT/'scripts/trading_demo_bridge/collector.py').read_text())
        calls={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and ((isinstance(n.func.value,ast.Name) and n.func.value.id=='sdk') or (isinstance(n.func.value,ast.Attribute) and n.func.value.attr=='sdk'))}
        self.assertEqual(calls,{'initialize','shutdown','terminal_info','account_info','symbol_info','symbol_info_tick','copy_rates_from_pos'})

    def test_pair_input_rejects_malformed_paste_without_normalization_or_echo(self):
        for value in (' '+('a'*32),'A'*32,'Kode sekali pakai: '+('a'*32),'a'*32+'\n'):
            with self.subTest(value=value),patch.object(collector.sys,'stdin',SimpleNamespace(isatty=lambda:True)),patch.object(collector.getpass,'getpass',return_value=value):
                with self.assertRaises(collector.CollectorError) as error:collector.read_pair_code()
                self.assertEqual(error.exception.code,'PAIR_INPUT_INVALID');self.assertNotIn(value,str(error.exception))
        with patch.object(collector.sys,'stdin',SimpleNamespace(isatty=lambda:True)),patch.object(collector.getpass,'getpass',return_value='a'*32):self.assertEqual(collector.read_pair_code(),'a'*32)

    def test_pair_input_has_no_echo_fallback(self):
        with patch.object(collector.sys,'stdin',SimpleNamespace(isatty=lambda:False)),patch.object(collector.getpass,'getpass') as prompt:
            with self.assertRaises(collector.CollectorError) as error:collector.read_pair_code()
            self.assertEqual(error.exception.code,'SECURE_CONSOLE_REQUIRED');prompt.assert_not_called()
        def fallback(*args):
            import warnings
            warnings.warn('synthetic-private-warning',collector.getpass.GetPassWarning)
        with patch.object(collector.sys,'stdin',SimpleNamespace(isatty=lambda:True)),patch.object(collector.getpass,'getpass',side_effect=fallback):
            with self.assertRaises(collector.CollectorError) as error:collector.read_pair_code()
            self.assertEqual(error.exception.code,'SECURE_CONSOLE_REQUIRED');self.assertNotIn('synthetic-private-warning',str(error.exception))

    def test_transport_reports_http_network_and_json_without_response_contents(self):
        import urllib.error
        secret='synthetic-private-secret'
        errors=[(urllib.error.HTTPError('https://invalid.local/?token='+secret,401,secret,{},io.BytesIO(secret.encode())),'HTTP_401'),(urllib.error.URLError(secret),'NETWORK_ERROR')]
        for failure,expected in errors:
            transport=collector.Transport();transport.opener=SimpleNamespace(open=Mock(side_effect=failure))
            with self.assertRaises(collector.CollectorError) as error:transport.post('exchange',{})
            self.assertEqual(error.exception.code,expected);self.assertNotIn(secret,str(error.exception))
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.status=200;response.headers=SimpleNamespace(get_content_type=lambda:'application/json');response.read=Mock(return_value=b'not-json-private')
        transport=collector.Transport();transport.opener=SimpleNamespace(open=Mock(return_value=response))
        with self.assertRaises(collector.CollectorError) as error:transport.post('exchange',{})
        self.assertEqual(error.exception.code,'REMOTE_RESPONSE_INVALID');self.assertNotIn('not-json-private',str(error.exception))

    def test_collector_persists_fixed_failure_stage_before_session_assignment(self):
        import tempfile
        sdk,_=self.synthetic_sdk();secret='synthetic-private-secret'
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'collector-status.json'
            def paths(value):return target if value=='collector-status.json' else SimpleNamespace(is_file=lambda:True,is_dir=lambda:True)
            output=io.StringIO()
            args=['collector','--symbol','BTCUSD','--connect','--terminal-path',EXE,'--terminal-data-path',DATA,'--diagnostic-status']
            with patch.object(sys,'argv',args),patch.dict(sys.modules,{'MetaTrader5':sdk}),patch.object(collector,'os',SimpleNamespace(name='nt')),patch.object(collector,'Path',side_effect=paths),patch.object(collector,'read_pair_code',return_value='a'*32),patch.object(collector,'Session',side_effect=collector.CollectorError(secret,'HTTP_401')),redirect_stdout(output):
                self.assertEqual(collector.main(),2)
            data=json.loads(target.read_text());self.assertEqual(data['stage'],'EXCHANGE');self.assertEqual(data['outcome'],'HTTP_401');self.assertEqual(data['sdk_shutdown'],'COMPLETED')
            self.assertLess(target.stat().st_size,1024)
            for value in (secret,'a'*32,EXE,DATA):self.assertNotIn(value,target.read_text()+output.getvalue())
            self.assertNotIn('token',data);self.assertNotIn('account',data)
            with patch.object(collector,'Path',return_value=target),self.assertRaises(collector.CollectorError):collector.Diagnostic(True)
            self.assertEqual(json.loads(target.read_text()),data)

    def test_collector_input_interrupt_is_distinct_and_never_exchanges(self):
        sdk,_=self.synthetic_sdk();output=io.StringIO()
        args=['collector','--symbol','BTCUSD','--connect','--terminal-path',EXE,'--terminal-data-path',DATA]
        with patch.object(sys,'argv',args),patch.dict(sys.modules,{'MetaTrader5':sdk}),patch.object(collector,'os',SimpleNamespace(name='nt')),patch.object(collector,'Path',return_value=SimpleNamespace(is_file=lambda:True,is_dir=lambda:True)),patch.object(collector,'read_pair_code',side_effect=KeyboardInterrupt),patch.object(collector,'Session') as exchange,redirect_stdout(output):
            self.assertEqual(collector.main(),2)
        exchange.assert_not_called();sdk.shutdown.assert_called_once_with()
        self.assertIn('stage=PAIR_INPUT outcome=INTERRUPTED',output.getvalue())

    def test_collector_read_and_telemetry_failure_keep_primary_stage_no_retry(self):
        for stage in ('MARKET_READ','TELEMETRY'):
            sdk,_=self.synthetic_sdk();session=Mock();output=io.StringIO()
            if stage=='MARKET_READ':
                sdk.symbol_info_tick.side_effect=ValueError('synthetic-private-sdk-message')
                session.send.side_effect=collector.CollectorError('synthetic-private-network-message','NETWORK_ERROR')
            else:session.send.side_effect=collector.CollectorError('synthetic-private-http-message','HTTP_409')
            args=['collector','--symbol','BTCUSD','--connect','--terminal-path',EXE,'--terminal-data-path',DATA]
            with patch.object(sys,'argv',args),patch.dict(sys.modules,{'MetaTrader5':sdk}),patch.object(collector,'os',SimpleNamespace(name='nt')),patch.object(collector,'Path',return_value=SimpleNamespace(is_file=lambda:True,is_dir=lambda:True)),patch.object(collector,'read_pair_code',return_value='a'*32),patch.object(collector,'Session',return_value=session),redirect_stdout(output):
                self.assertEqual(collector.main(),2)
            expected='UNEXPECTED_FAILURE' if stage=='MARKET_READ' else 'HTTP_409'
            self.assertIn('stage='+stage+' outcome='+expected,output.getvalue());self.assertNotIn('synthetic-private',output.getvalue())
            sdk.symbol_info_tick.assert_called_once();session.send.assert_called_once();session.clear.assert_called_once_with()

    def test_outbound_transport_real_loopback_http(self):
        code=self.pair().json['pair_code']
        server=make_server('127.0.0.1',0,f.app.app)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch.object(collector,'BASE',f'http://127.0.0.1:{server.server_port}'+PATH):
                session=collector.Session(collector.Transport(),'GOLD',code)
                session.send(market())
                self.assertEqual(self.view().json['transport'],'CONNECTED')
                session.clear()
        finally:
            server.shutdown();thread.join(timeout=2);server.server_close()

if __name__=='__main__':unittest.main()
