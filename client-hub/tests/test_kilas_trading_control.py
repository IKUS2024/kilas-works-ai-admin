"""Control coordination security and state machines; synthetic offline transports."""
import copy
from contextlib import contextmanager
from datetime import timedelta
import json
import os
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import test_kilas_trading as f
import test_kilas_trading_bridge as fixtures
HOST=fixtures.HOST
from kilas_trading import control, control_store, bridge, bridge_store, bridge_routes
from kilas_trading.store import query

BASE='/products/services/trading/control'

class ControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixtures.BridgeTests.setUpClass();control_store.apply_release()
    def setUp(self):
        self.helper=fixtures.BridgeTests('test_default_disabled_routes_and_dashboard');self.helper.setUp();self.addCleanup(self.helper.doCleanups)
        self.flag=patch.dict(os.environ,{'KILAS_TRADING_CONTROL_ENABLED':'true'});self.flag.start();self.addCleanup(self.flag.stop)
        with bridge_store.transaction() as c:
            query(c,'DELETE FROM kilas_trading_control_receipts_v2');query(c,'DELETE FROM kilas_trading_controls_v2');query(c,'DELETE FROM kilas_trading_control_credentials_v2')
        self.readonly=self.helper.connect('BTCUSD');self.owner=self.helper.owner
        self.conn=dict(token='c'*64,challenge=self.readonly['challenge'])
        self.provision_fixture('d'*32)
        self.seq=0;self.challenge=None
    def provision_fixture(self,ident):
        with bridge_store.transaction() as c:
            query(c,'DELETE FROM kilas_trading_control_credentials_v2')
            query(c,'INSERT INTO kilas_trading_control_credentials_v2(user_id,session_id,credential_hash,scope,symbol,server,max_run_seconds,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?)',(f.TradingTests.user,ident,bridge.digest(self.conn['token']),control.SCOPE,'BTCUSD',bridge.SERVER,120,bridge.stamp(self.helper.time),bridge.stamp(self.helper.time+timedelta(minutes=30))))
    def advance(self,seconds=1):self.helper.time+=timedelta(seconds=seconds)
    def status(self):return self.owner.get(BASE+'/status',base_url=HOST).json
    def desired(self,state='OFF',instrument='BTC',lot='0.01',ident=None,revision=None,client=None,seconds=None):
        self.ident=ident or ('%032x'%(self.status()['revision']+1))
        body=dict(schema_version=2,command_id=self.ident,expected_revision=self.status()['revision'] if revision is None else revision,desired_state=state,instrument=instrument,lot=lot,run_seconds=(120 if state=='ON' else 0) if seconds is None else seconds)
        return (client or self.owner).post(BASE+'/desired',base_url=HOST,json=body,headers={'X-CSRF-Token':'bridge-test-csrf'})
    def ack(self,**updates):
        s=self.status();body=dict(revision=s['revision'],command_id=s['command_id'],actual_state='OFF',instrument=s['instrument'],lot=s['lot'],account_mode='DEMO',terminal_connected=True,position_open=False,protection_active=False,specs_verified=True,risk_allowed=True,policy_state='READY',wait_reason='NONE');body.update(updates);return body
    def sync(self,ack=None,bootstrap=False,**overrides):
        body=dict(schema_version=2,sequence=0 if bootstrap else self.seq+1,challenge=None if bootstrap else self.challenge,ack=ack);body.update(overrides)
        r=self.helper.local.post(BASE+'/sync',base_url=HOST,json=body,headers={'Authorization':'Bearer '+self.conn['token']})
        if r.status_code==200:self.seq=r.json['sequence'];self.challenge=r.json['challenge']
        return r
    def ready(self):
        self.assertEqual(self.sync(bootstrap=True).status_code,200)
        self.advance();self.assertEqual(self.sync(self.ack()).status_code,200)
    def running(self,seconds=120):
        self.ready();self.assertEqual(self.desired('ON',seconds=seconds).status_code,200)
        self.assertNotEqual(self.status()['actual_state'],'RUNNING')
        self.advance();self.assertEqual(self.sync(self.ack(actual_state='RUNNING')).status_code,200)
        self.assertEqual(self.status()['actual_state'],'RUNNING')
    def test_disabled_defaults_no_schema_or_credential_issuance(self):
        with patch.dict(os.environ,{'KILAS_TRADING_CONTROL_ENABLED':''}):
            self.assertFalse(self.status()['enabled']);self.assertEqual(self.status()['actual_state'],'UNKNOWN')
            self.assertEqual(self.desired('ON').status_code,404);self.assertEqual(self.sync(bootstrap=True).status_code,404)
            with patch.object(bridge_store,'transaction',side_effect=AssertionError('No schema access')):self.assertEqual(self.status()['effective_desired_state'],'OFF')
        self.assertFalse(self.status()['execution_authorized'])
    def test_owner_auth_csrf_support_host_and_exact_json(self):
        for user in (f.TradingTests.other,f.TradingTests.admin):
            self.assertEqual(self.helper.client(user).get(BASE+'/status',base_url=HOST).status_code,404)
        self.assertEqual(self.owner.post(BASE+'/desired',base_url=HOST,json={}).status_code,400)
        with self.owner.session_transaction(base_url=HOST) as s:s['support_business_id']=999
        self.assertEqual(self.owner.get(BASE+'/status',base_url=HOST).status_code,404)
        self.owner=self.helper.client(f.TradingTests.user)
        self.assertEqual(self.owner.post(BASE+'/desired',base_url='https://app.kilasworks.id',json={},headers={'X-CSRF-Token':'bridge-test-csrf'}).status_code,404)
        r=self.owner.post(BASE+'/desired',base_url=HOST,data='{"schema_version":1,"schema_version":1}',content_type='application/json',headers={'X-CSRF-Token':'bridge-test-csrf'})
        self.assertEqual(r.status_code,409)
        self.assertEqual(self.owner.post(BASE+'/desired',base_url=HOST,data='x'*8193,content_type='application/json',headers={'X-CSRF-Token':'bridge-test-csrf'}).status_code,413)
    def test_desired_is_idempotent_versioned_and_expiring(self):
        self.ready();r=self.desired('ON',ident='a'*32);self.assertEqual(r.status_code,200)
        expiry=r.json['run_expires_at'];revision=r.json['revision']
        again=self.desired('ON',ident='a'*32,revision=revision-1)
        self.assertEqual(again.json['outcome'],'IDEMPOTENT');self.assertEqual(again.json['run_expires_at'],expiry)
        self.assertEqual(self.desired('OFF',ident='a'*32,revision=revision-1).json['outcome'],'COMMAND_ID_CONFLICT')
        self.assertEqual(self.desired('ON',revision=0).json['outcome'],'REVISION_CONFLICT')
        self.advance(31);s=self.status();self.assertEqual(s['effective_desired_state'],'OFF');self.assertNotEqual(s['actual_state'],'RUNNING')
        self.assertEqual(self.desired('ON',ident='a'*32,revision=0).json['run_expires_at'],expiry)
    def test_actual_requires_latest_fresh_ack_and_off_keeps_protection(self):
        self.running();self.desired('OFF');self.assertNotEqual(self.status()['actual_state'],'RUNNING')
        self.advance();self.assertEqual(self.sync(self.ack(actual_state='PROTECTING',position_open=True,protection_active=True)).status_code,200)
        self.assertEqual(self.status()['actual_state'],'PROTECTING');self.assertEqual(self.status()['effective_desired_state'],'OFF')
        self.assertEqual(self.desired('OFF',lot='0.02').json['outcome'],'CONFIGURATION_LOCKED')
        self.advance(7);self.assertEqual(self.status()['actual_state'],'UNKNOWN');self.assertIsNone(self.status()['account_detail'])
    def test_instrument_and_lot_locked_active_protecting_stale_and_scope(self):
        self.running()
        for state,instrument,lot in [('ON','GOLD','0.01'),('OFF','BTC','0.02'),('OFF','GOLD','0.01')]:
            self.assertEqual(self.desired(state,instrument,lot).json['outcome'],'CONFIGURATION_LOCKED')
        self.advance(7);self.assertEqual(self.desired('OFF',lot='0.02').json['outcome'],'CONFIGURATION_LOCKED')
    def test_config_change_requires_fresh_flat_off_ack_and_does_not_approve_symbol(self):
        self.ready();self.desired('OFF');self.advance();self.sync(self.ack())
        self.assertEqual(self.desired('OFF',instrument='GOLD').status_code,200)
        self.assertEqual(self.desired('ON',instrument='GOLD').json['outcome'],'WORKER_SCOPE_UNAVAILABLE')
    def test_policy_unset_unknown_and_risk_blocks_on(self):
        for updates in ({'policy_state':'UNSET'},{'account_mode':'UNKNOWN'},{'specs_verified':False},{'risk_allowed':False},{'terminal_connected':False}):
            with self.subTest(updates=updates):
                if self.seq==0:self.sync(bootstrap=True)
                self.advance();self.assertEqual(self.sync(self.ack(**updates)).status_code,200)
                self.assertEqual(self.desired('ON').json['outcome'],'WORKER_NOT_READY')
        self.assertEqual(self.desired('OFF').status_code,200)
    def test_worker_cookie_query_host_scope_and_revocation_expiry(self):
        header={'Authorization':'Bearer '+self.conn['token']};body=dict(schema_version=2,sequence=0,challenge=None,ack=None)
        self.assertEqual(self.owner.post(BASE+'/sync',base_url=HOST,json=body,headers=header).status_code,400)
        self.assertEqual(self.helper.local.post(BASE+'/sync?x=1',base_url=HOST,json=body,headers=header).status_code,400)
        self.assertEqual(self.helper.local.post(BASE+'/sync',base_url='https://app.kilasworks.id',json=body,headers=header).status_code,404)
        with bridge_store.transaction() as c:query(c,'UPDATE kilas_trading_control_credentials_v2 SET revoked=1')
        self.assertEqual(self.sync(bootstrap=True).status_code,401)
        self.assertEqual(self.status()['effective_desired_state'],'OFF')
    def test_expired_token_and_bridge_disabled_never_running(self):
        self.running();self.advance(3601);self.assertEqual(self.sync(self.ack(actual_state='RUNNING')).status_code,401)
        self.assertEqual(self.status()['actual_state'],'UNKNOWN')
        with patch.dict(os.environ,{'KILAS_TRADING_CONTROL_ENABLED':'false'}):self.assertEqual(self.sync(bootstrap=True).status_code,404)
    def test_bootstrap_replay_and_repair_never_replays_old_on(self):
        self.running();self.assertEqual(self.sync(bootstrap=True).json['outcome'],'BOOTSTRAP_REPLAY')
        self.advance(31);self.provision_fixture('e'*32);self.seq=0;self.challenge=None
        r=self.sync(bootstrap=True);self.assertEqual(r.status_code,200);self.assertEqual(r.json['desired_state'],'OFF');self.assertIsNone(r.json['command_id'])
    def test_wrong_sequence_challenge_expired_and_backwards_clock(self):
        self.ready();self.assertEqual(self.sync(self.ack(),sequence=99).status_code,409)
        self.assertEqual(self.sync(self.ack(),challenge='f'*64).status_code,409)
        self.advance(11);self.assertEqual(self.sync(self.ack()).status_code,409)
        self.advance(-100);self.assertEqual(self.status()['actual_state'],'UNKNOWN')
    def test_real_unsafe_and_stale_ack_clear_running_without_raw_fields(self):
        self.running();self.advance();r=self.sync(self.ack(account_mode='REAL'))
        self.assertEqual(r.status_code,409);self.assertEqual(self.status()['actual_state'],'UNKNOWN');self.assertEqual(self.status()['effective_desired_state'],'OFF')
        with bridge_store.transaction() as c:self.assertIsNone(control.row_for(c,f.TradingTests.user)['ack_json'])
    def test_stale_revision_and_open_position_without_protection_rejected(self):
        self.ready();old=self.ack();self.desired('ON');self.advance();r=self.sync(old);self.assertEqual(r.status_code,200)
        self.assertEqual(r.json['desired_state'],'ON');self.assertEqual(r.json['actual_state'],'UNKNOWN')
        self.advance();self.assertEqual(self.sync(self.ack(actual_state='RUNNING')).status_code,200)
    def test_lot_types_bounds_unknown_fields_and_projection_private(self):
        for value in ('0.001','0.010','NaN','Infinity','1e-2',0.01,True,'-0.01'):
            self.assertEqual(self.desired('OFF',lot=value).status_code,409)
        self.ready();self.assertFalse(self.status()['execution_authorized'])
        text=json.dumps(self.status())
        for value in (self.conn['token'],self.conn['challenge']):self.assertNotIn(value,text)
        self.assertNotIn('account_id',text);self.assertNotIn('balance',text)
        self.advance();body=self.ack();body['raw_account']='PRIVATE';self.assertEqual(self.sync(body).status_code,409)
        with bridge_store.transaction() as c:self.assertNotIn('PRIVATE',json.dumps(control.row_for(c,f.TradingTests.user)))
    def test_concurrent_identical_command_one_revision(self):
        self.ready();body=dict(schema_version=2,command_id='a'*32,expected_revision=0,desired_state='ON',instrument='BTC',lot='0.01',run_seconds=120)
        def submit(_):return control.desired(f.TradingTests.user,copy.deepcopy(body))
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(submit,range(2)))
        self.assertEqual({r['revision'] for r in results},{1});self.assertEqual({r['outcome'] for r in results},{'DESIRED_ACCEPTED','IDEMPOTENT'})
    def test_receipts_bounded_and_evicted_old_revision_never_replayed(self):
        self.ready()
        for _ in range(66):self.assertEqual(self.desired('OFF').status_code,200)
        with bridge_store.transaction() as c:self.assertEqual(query(c,'SELECT count(*) AS n FROM kilas_trading_control_receipts_v2',one=True)['n'],64)
        self.assertEqual(self.desired('OFF',ident='%032x'%1,revision=0).json['outcome'],'REVISION_CONFLICT')
    def test_expired_on_running_ack_is_rejected_and_fences_entries(self):
        self.running(seconds=16)
        for _ in range(3):
            self.advance(4);self.assertEqual(self.sync(self.ack(actual_state='RUNNING')).status_code,200)
        self.advance(4);self.assertEqual(self.sync(self.ack(actual_state='RUNNING')).json['outcome'],'RUN_ENDED')
        self.assertEqual(self.status()['actual_state'],'UNKNOWN');self.assertEqual(self.status()['effective_desired_state'],'OFF')
    def test_open_position_requires_protection_and_locks_lot(self):
        self.ready();self.desired('ON');self.advance()
        r=self.sync(self.ack(actual_state='RUNNING',position_open=True,protection_active=False))
        self.assertEqual(r.json['outcome'],'PROTECTION_REQUIRED');self.assertEqual(self.status()['effective_desired_state'],'OFF')
    def test_account_line_fresh_metadata_only_and_default_offline(self):
        page=self.owner.get('/products/services/trading',base_url=HOST)
        self.assertIn('offline / belum terverifikasi',page.text);self.assertNotIn('XMGlobal-MT5 10',page.text)
        self.ready();page=self.owner.get('/products/services/trading',base_url=HOST)
        self.assertIn('Akun DEMO · XM · MT5 · XMGlobal-MT5 10 (laporan worker)',page.text)
        self.assertNotIn(self.conn['token'],page.text);self.assertNotIn('<details',page.text)
        self.advance(7);self.assertIn('offline / belum terverifikasi',self.owner.get('/products/services/trading',base_url=HOST).text)
    def test_concurrent_different_command_one_winner(self):
        self.ready()
        def submit(i):
            try:return control.desired(f.TradingTests.user,dict(schema_version=2,command_id=('%032x'%i),expected_revision=0,desired_state='ON',instrument='BTC',lot='0.01',run_seconds=120))['outcome']
            except bridge.Rejected as e:return e.code
        with ThreadPoolExecutor(max_workers=2) as pool:out=list(pool.map(submit,(1,2)))
        self.assertCountEqual(out,['DESIRED_ACCEPTED','REVISION_CONFLICT'])
    def test_worker_can_pull_off_while_acknowledging_previous_on(self):
        self.running();old=self.ack(actual_state='RUNNING');self.desired('OFF');self.advance()
        r=self.sync(old);self.assertEqual(r.status_code,200)
        self.assertEqual(r.json['desired_state'],'OFF');self.assertEqual(r.json['actual_state'],'UNKNOWN')
        self.advance();self.assertEqual(self.sync(self.ack()).status_code,200)
        self.assertEqual(self.status()['actual_state'],'OFF')
    def test_readonly_bearer_never_has_control_scope(self):
        r=self.helper.local.post(BASE+'/sync',base_url=HOST,json=dict(schema_version=2,sequence=0,challenge=None,ack=None),headers={'Authorization':'Bearer '+self.readonly['token']})
        self.assertEqual(r.status_code,401)
        with bridge_store.transaction() as c:query(c,'UPDATE kilas_trading_control_credentials_v2 SET credential_hash=?',(bridge.digest(self.readonly['token']),))
        r=self.helper.local.post(BASE+'/sync',base_url=HOST,json=dict(schema_version=2,sequence=0,challenge=None,ack=None),headers={'Authorization':'Bearer '+self.readonly['token']})
        self.assertEqual(r.status_code,401)
        with bridge_store.transaction() as c:query(c,'DELETE FROM kilas_trading_control_credentials_v2')
        self.assertEqual(self.sync(bootstrap=True).status_code,401)
    def test_model_strategy_and_news_unavailable_wait_without_entries(self):
        self.ready()
        for reason in ('MODEL_UNAVAILABLE','STRATEGY_UNAVAILABLE','NEWS_UNVERIFIED'):
            self.advance();r=self.sync(self.ack(actual_state='BLOCKED',policy_state='BLOCKED',risk_allowed=False,wait_reason=reason))
            self.assertEqual(r.status_code,200);self.assertEqual(r.json['wait_reason'],reason)
            self.assertEqual(r.json['effective_desired_state'],'OFF');self.assertFalse(r.json['execution_authorized'])
            self.assertEqual(self.desired('ON').json['outcome'],'WORKER_NOT_READY')
    def test_readonly_revocation_does_not_repurpose_control_authority(self):
        self.ready();bridge.revoke(f.TradingTests.user)
        with patch.dict(os.environ,{'KILAS_TRADING_BRIDGE_ENABLED':'false'}):
            self.advance();self.assertEqual(self.sync(self.ack()).status_code,200)
        self.assertFalse(self.status()['execution_authorized'])
    def test_v2_run_survives_pickup_deadline_without_extension(self):
        self.running(seconds=120);initial=self.status();deadline=initial['run_expires_at'];pickup=initial['command_expires_at']
        for _ in range(10):
            self.advance(4);self.assertEqual(self.sync(self.ack(actual_state='RUNNING')).status_code,200)
        s=self.status();self.assertEqual(s['run_status'],'ACTIVE');self.assertEqual(s['actual_state'],'RUNNING')
        self.assertEqual(s['run_expires_at'],deadline);self.assertEqual(s['command_expires_at'],pickup)
        self.assertNotIn('expires_at',s)
        self.assertEqual(self.desired('ON',seconds=120).json['outcome'],'RUN_ALREADY_ACTIVE')
        self.assertEqual(self.status()['run_expires_at'],deadline)
    def test_duration_is_explicit_approved_and_never_defaulted(self):
        self.ready()
        for value in (None,True,'60',0,-1,301,1.5):
            body=dict(schema_version=2,command_id='a'*32,expected_revision=0,desired_state='ON',instrument='BTC',lot='0.01',run_seconds=value)
            self.assertEqual(self.owner.post(BASE+'/desired',base_url=HOST,json=body,headers={'X-CSRF-Token':'bridge-test-csrf'}).json['outcome'],'INVALID_RUN_DURATION')
        with bridge_store.transaction() as c:query(c,'UPDATE kilas_trading_control_credentials_v2 SET max_run_seconds=NULL')
        self.assertEqual(self.desired('ON').json['outcome'],'RUN_DURATION_UNAPPROVED')
        with bridge_store.transaction() as c:query(c,'UPDATE kilas_trading_control_credentials_v2 SET max_run_seconds=30')
        self.assertEqual(self.desired('ON',seconds=31).json['outcome'],'RUN_DURATION_UNAPPROVED')
        self.assertEqual(self.desired('OFF',seconds=1).json['outcome'],'INVALID_RUN_DURATION')
        self.assertEqual(self.desired('ON',seconds=30).status_code,200)
    def test_scope_must_cover_entire_run_and_duplicates_do_not_extend(self):
        self.ready()
        with bridge_store.transaction() as c:query(c,'UPDATE kilas_trading_control_credentials_v2 SET expires_at=?',(bridge.stamp(self.helper.time+timedelta(seconds=20)),))
        self.assertEqual(self.desired('ON',seconds=21).json['outcome'],'INSUFFICIENT_SCOPE_LIFETIME')
        r=self.desired('ON',ident='a'*32,seconds=15);self.assertEqual(r.status_code,200)
        deadline=r.json['run_expires_at'];self.advance()
        r=self.desired('ON',ident='a'*32,revision=0,seconds=15)
        self.assertEqual(r.json['outcome'],'IDEMPOTENT');self.assertEqual(r.json['run_expires_at'],deadline)
    def test_liveness_gap_is_durable_and_cannot_be_refreshed_away(self):
        self.running();late=self.ack(actual_state='RUNNING');self.advance(7)
        self.assertEqual(self.sync(late).json['outcome'],'RUN_ENDED')
        with bridge_store.transaction() as c:
            row=control.row_for(c,f.TradingTests.user);self.assertEqual(row['run_status'],'ENDED');self.assertEqual(row['end_reason'],'WORKER_LEASE_EXPIRED')
        s=self.status();self.assertEqual(s['effective_desired_state'],'OFF');self.assertEqual(s['run_status'],'ENDED')
    def test_expired_challenge_commits_end_latch_even_without_status_read(self):
        self.running();late=self.ack(actual_state='RUNNING');self.advance(11)
        self.assertEqual(self.sync(late).json['outcome'],'REPLAY_OR_EXPIRED_CHALLENGE')
        with bridge_store.transaction() as c:self.assertEqual(control.row_for(c,f.TradingTests.user)['run_status'],'ENDED')
    def test_pending_heartbeat_cannot_extend_pickup_or_start_late(self):
        self.ready();old=self.ack();r=self.desired('ON');pickup=r.json['command_expires_at'];deadline=r.json['run_expires_at']
        for _ in range(7):
            self.advance(4);r=self.sync(old);self.assertEqual(r.status_code,200)
            self.assertEqual(r.json['run_status'],'PENDING');self.assertEqual(r.json['command_expires_at'],pickup);self.assertEqual(r.json['run_expires_at'],deadline)
        self.advance(2);r=self.sync(self.ack(actual_state='RUNNING'))
        self.assertEqual(r.json['outcome'],'RUN_ENDED')
        with bridge_store.transaction() as c:self.assertEqual(control.row_for(c,f.TradingTests.user)['end_reason'],'PICKUP_EXPIRED')
    def test_worker_restart_fences_and_old_scope_cannot_replay_on(self):
        self.running();old=self.ack(actual_state='RUNNING')
        self.assertEqual(self.sync(bootstrap=True).json['outcome'],'BOOTSTRAP_REPLAY')
        with bridge_store.transaction() as c:self.assertEqual(control.row_for(c,f.TradingTests.user)['end_reason'],'WORKER_RESTARTED')
        self.advance();self.assertEqual(self.sync(old).json['outcome'],'RUN_ENDED')
    def test_revocation_latch_committed_by_sync_not_only_status(self):
        self.running();ack=self.ack(actual_state='RUNNING')
        with bridge_store.transaction() as c:query(c,'UPDATE kilas_trading_control_credentials_v2 SET revoked=1')
        self.assertEqual(self.sync(ack).status_code,401)
        with bridge_store.transaction() as c:self.assertEqual(control.row_for(c,f.TradingTests.user)['end_reason'],'CREDENTIAL_UNAVAILABLE')
    def test_off_ack_race_never_restores_running(self):
        self.running();old=self.ack(actual_state='RUNNING');self.advance()
        def off():return self.desired('OFF').status_code
        def report():return self.sync(old).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda fn:fn(),(off,report)))
        self.assertEqual(results,[200,200]);s=self.status();self.assertEqual(s['desired_state'],'OFF');self.assertEqual(s['run_status'],'ENDED');self.assertNotEqual(s['actual_state'],'RUNNING')
    def test_v1_schema_credentials_and_commands_are_not_adopted(self):
        with bridge_store.transaction() as c:
            query(c,'DELETE FROM kilas_trading_control_credentials WHERE user_id=?',(f.TradingTests.user,))
            query(c,'DELETE FROM kilas_trading_controls WHERE user_id=?',(f.TradingTests.user,))
            query(c,'INSERT INTO kilas_trading_controls(user_id,desired_state) VALUES (?,?)',(f.TradingTests.user,'ON'))
            query(c,'INSERT INTO kilas_trading_control_credentials(user_id,session_id,credential_hash,scope,symbol,server,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?)',(f.TradingTests.user,'f'*32,bridge.digest('f'*64),'DEMO_CONTROL_COORDINATION_V1','BTCUSD',bridge.SERVER,bridge.stamp(self.helper.time),bridge.stamp(self.helper.time+timedelta(minutes=20))))
        body=dict(schema_version=2,sequence=0,challenge=None,ack=None)
        r=self.helper.local.post(BASE+'/sync',base_url=HOST,json=body,headers={'Authorization':'Bearer '+'f'*64});self.assertEqual(r.status_code,401)
        self.assertEqual(self.sync(bootstrap=True,schema_version=1).status_code,409)
        with bridge_store.transaction() as c:self.assertEqual(query(c,'SELECT desired_state FROM kilas_trading_controls WHERE user_id=?',(f.TradingTests.user,),one=True)['desired_state'],'ON')
        self.assertEqual(self.status()['desired_state'],'OFF');self.assertEqual(control_store.apply_release(),[])
    def test_schema_explicit_checksum_and_unavailable_fixed_error(self):
        self.assertEqual(control_store.apply_release(),[])
        with patch.object(control_store.Path,'read_text',return_value='SELECT 1;'):
            with self.assertRaisesRegex(RuntimeError,'control_schema_checksum_mismatch'):control_store.apply_release()
        with patch.object(bridge_store,'transaction',side_effect=RuntimeError('PRIVATE')):
            r=self.owner.get(BASE+'/status',base_url=HOST);self.assertEqual(r.status_code,503);self.assertNotIn('PRIVATE',r.text)

    @contextmanager
    def schema_sandbox(self):
        # Exercise transactional DDL on either backend, then restore the complete
        # surrounding fixture, including synthetic credentials and v1 history.
        with bridge_store.transaction() as conn:
            query(conn,'SAVEPOINT control_schema_fixture')
            @contextmanager
            def release_transaction():
                query(conn,'SAVEPOINT control_schema_release')
                try:yield conn
                except Exception:
                    query(conn,'ROLLBACK TO SAVEPOINT control_schema_release')
                    raise
                finally:query(conn,'RELEASE SAVEPOINT control_schema_release')
            try:
                with patch.object(control_store,'transaction',release_transaction):yield conn
            finally:
                query(conn,'ROLLBACK TO SAVEPOINT control_schema_fixture')
                query(conn,'RELEASE SAVEPOINT control_schema_fixture')

    def clear_control_schema(self,conn):
        for group in control_store.TABLES.values():
            for table in group:query(conn,'DROP TABLE '+table)
        for name in control_store.RELEASES:
            query(conn,'DELETE FROM kilas_trading_bridge_releases WHERE name=?',(name,))

    def test_schema_rejects_missing_base_tables_or_release_records(self):
        for table in control_store.PREREQUISITES:
            with self.subTest(table=table),self.schema_sandbox() as conn:
                query(conn,'ALTER TABLE '+table+' RENAME TO '+table+'_test_missing')
                with self.assertRaisesRegex(RuntimeError,'control_schema_prerequisite_missing'):control_store.apply_release()
                self.assertNotIn(table,control_store.tables(conn))
        from kilas_trading import schema
        for table,name in (('kilas_trading_releases',schema.NAME),('kilas_trading_bridge_releases',bridge_store.NAME)):
            with self.subTest(release=name),self.schema_sandbox() as conn:
                query(conn,'DELETE FROM '+table+' WHERE name=?',(name,))
                with self.assertRaisesRegex(RuntimeError,'control_schema_prerequisite_missing'):control_store.apply_release()
                self.assertIsNone(query(conn,'SELECT name FROM '+table+' WHERE name=?',(name,),one=True))

    def test_schema_rejects_untracked_partial_tables_without_adoption(self):
        with self.schema_sandbox() as conn:
            self.clear_control_schema(conn)
            query(conn,'CREATE TABLE kilas_trading_controls_v2 (user_id BIGINT PRIMARY KEY)')
            with self.assertRaisesRegex(RuntimeError,'control_schema_untracked_tables'):control_store.apply_release()
            self.assertNotIn('kilas_trading_controls',control_store.tables(conn))
            for name in control_store.RELEASES:
                self.assertIsNone(query(conn,'SELECT name FROM kilas_trading_bridge_releases WHERE name=?',(name,),one=True))

    def test_schema_rejects_missing_or_changed_tracked_columns(self):
        for statement in ('DROP TABLE kilas_trading_control_receipts_v2','ALTER TABLE kilas_trading_controls_v2 ADD COLUMN unexpected TEXT'):
            with self.subTest(statement=statement),self.schema_sandbox() as conn:
                query(conn,statement)
                with self.assertRaisesRegex(RuntimeError,'control_schema_shape_mismatch'):control_store.apply_release()

    def test_schema_fresh_install_idempotency_and_atomic_failure(self):
        with self.schema_sandbox() as conn:
            self.clear_control_schema(conn)
            original=control_store.query
            def fail_final_receipt(connection,sql,params=(),**kwargs):
                if sql=='INSERT INTO kilas_trading_bridge_releases VALUES (?,?)' and params[0]==control_store.NAME:
                    raise RuntimeError('synthetic_final_release_failure')
                return original(connection,sql,params,**kwargs)
            with patch.object(control_store,'query',side_effect=fail_final_receipt):
                with self.assertRaisesRegex(RuntimeError,'synthetic_final_release_failure'):control_store.apply_release()
            existing=control_store.tables(conn)
            for name,group in control_store.TABLES.items():
                self.assertFalse(existing.intersection(group))
                self.assertIsNone(query(conn,'SELECT name FROM kilas_trading_bridge_releases WHERE name=?',(name,),one=True))
            self.assertEqual(control_store.apply_release(),list(control_store.RELEASES))
            self.assertEqual(control_store.apply_release(),[])
            self.assertEqual(query(conn,'SELECT count(*) AS n FROM kilas_trading_control_credentials_v2',one=True)['n'],0)

if __name__=='__main__':unittest.main()
