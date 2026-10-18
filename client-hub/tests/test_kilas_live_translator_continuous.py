"""Production owner Live count scope; real SQLite accounting, no provider IO."""
import io
import hashlib
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest.mock import patch
import test_kilas_live_translator as fixture
import test_kilas_audio as audio
from kilas_ai import audio_transcription_budget as batch, live_translator_realtime_budget as budget
from kilas_ai import live_translator_realtime as rt, live_translator_store as sessions
from kilas_ai import usage
from kilas_ai.autonomous_store import transaction


class ContinuousLiveTests(unittest.TestCase):
    setUp = fixture.LiveTranslatorTests.setUp
    funded = fixture.LiveTranslatorTests.funded
    on = fixture.LiveTranslatorTests.on
    session = fixture.LiveTranslatorTests.session
    def key(self,n=1):return 'live-'+hashlib.sha256(f'{self.user}:{n}'.encode()).hexdigest()[:32]
    credit = fixture.LiveTranslatorTests.credit

    def owner(self):
        return patch.dict(os.environ, {'KILAS_VO_STT_ALLOWED_OWNER_ID': str(self.user),
            'KILAS_VO_STT_USAGE_MODE': 'owner', 'KILAS_LIVE_TRANSLATOR_USAGE_MODE': 'owner'})

    def rows(self):
        return audio.f.db.query_all('SELECT status,charge_micro,operation_key FROM kilas_vo_stt_operations WHERE user_id=? ORDER BY id', (self.user,))

    def test_25_turns_same_session_trial_member_reconnect_and_no_duplicate_settlement(self):
        with self.funded(2000000,2000000), self.on(), self.owner(), patch.object(batch.free_test,'eligible',return_value=True), patch.object(rt,'connect') as connect:
            ident=self.session()
            for i in range(25):
                key=self.key(i+1); sessions.claim(self.user,ident,key)
                cap=budget.claim(self.user,ident,key); budget.dispatch(cap)
                self.assertTrue(budget.finish(cap,True)); self.assertFalse(budget.finish(cap,True))
                sessions.finish(self.user,ident,key,True)
                # Refresh/reconnect reads the same durable outcome; no new lease.
                self.assertEqual(sessions.status(self.user,ident),{'status':'ACTIVE','processing':False})
                self.assertEqual(sessions.result(self.user,ident,key)['status'],'COMPLETED')
                with self.assertRaises(batch.BudgetError) as denied:budget.claim(self.user,ident,key)
                self.assertEqual(denied.exception.code,'duplicate_turn')
            rows=self.rows(); self.assertEqual(len(rows),25)
            self.assertEqual(sum(r['charge_micro'] for r in rows),25*budget.RESERVE_MICRO)
            self.assertTrue(all(r['status']=='COMPLETED' for r in rows)); connect.assert_not_called()
            # The same owner's other trial features retain the shared hourly cap.
            with transaction() as conn:
                with self.assertRaises(batch.BudgetError) as denied:batch.trial_admit(conn,self.user)
                self.assertEqual(denied.exception.code,'rate_limit')
            with self.assertRaises(batch.BudgetError) as denied:batch.claim(self.user,'dictate-keep-existing-limit-1234','a'*64,1000)
            self.assertEqual(denied.exception.code,'rate_limit')
            # Client-supplied live-* keys on a non-Live route do not opt in.
            with self.assertRaises(batch.BudgetError) as denied:batch.claim(self.user,self.key(32),'a'*64,1000)
            self.assertEqual(denied.exception.code,'rate_limit')
            # Auto-detect uses the validated batch Live route, with the same caps.
            _,cap=batch.claim(self.user,self.key(33),'a'*64,1000,live_session=True)
            self.assertIsNotNone(cap);batch.cancel(self.user,self.key(33))
            with patch.dict(os.environ,{'KILAS_LIVE_TRANSLATOR_USAGE_MODE':'qa'}):
                with self.assertRaises(batch.BudgetError) as denied:budget.claim(self.user,ident,self.key(30))
                self.assertEqual(denied.exception.code,'rate_limit')

    def test_exemption_requires_funded_production_mode_and_server_route_marker(self):
        with self.funded(),self.owner():
            config=batch.policy()
            self.assertTrue(batch.continuous_live(self.user,config,self.key()))
            for changes,key in [({'allowed_owner':None},self.key()),({'mode':'qa'},self.key()),({},'dictate-operation-1234')]:
                self.assertFalse(batch.continuous_live(self.user,{**config,**changes},key))
            with patch.dict(os.environ,{'KILAS_LIVE_TRANSLATOR_USAGE_MODE':'qa'}):self.assertFalse(batch.continuous_live(self.user,config,self.key()))

    def test_live_qa_four_per_day_still_denied(self):
        with self.funded(2000000,2000000), self.on(), self.owner(), patch.dict(os.environ,{'KILAS_LIVE_TRANSLATOR_USAGE_MODE':'qa'}):
            for i in range(4):
                cap=budget.claim(self.user,'c'*48,self.key(i+1)); budget.dispatch(cap); budget.finish(cap,True)
            with self.assertRaises(batch.BudgetError) as denied:budget.claim(self.user,'c'*48,self.key(5))
            self.assertEqual(denied.exception.code,'attempt_limit'); self.assertEqual(len(self.rows()),4)

    def test_cancel_before_dispatch_releases_only_zero_exposure_unknown_keeps_full_lease(self):
        with self.funded(3*budget.RESERVE_MICRO,3*budget.RESERVE_MICRO), self.on(), self.owner():
            cap=budget.claim(self.user,'c'*48,self.key()); self.assertFalse(budget.finish(cap,False)); self.assertFalse(budget.finish(cap,False))
            cap=budget.claim(self.user,'c'*48,self.key(2)); budget.dispatch(cap); self.assertFalse(budget.finish(cap,False)); self.assertFalse(budget.finish(cap,True))
            cap=budget.claim(self.user,'c'*48,self.key(3)); budget.dispatch(cap); budget.finish(cap,True)
            rows=self.rows();self.assertEqual([r['status'] for r in rows],['CANCELLED','UNKNOWN','COMPLETED'])
            self.assertEqual([r['charge_micro'] for r in rows],[0,budget.RESERVE_MICRO,budget.RESERVE_MICRO])

    def test_monthly_real_budget_denies_before_worker_and_keeps_all_history(self):
        self.credit(300)
        with self.funded(budget.RESERVE_MICRO,budget.RESERVE_MICRO),self.on(),self.owner(),patch.object(rt,'require_ready'),patch.object(rt,'connect') as connect,patch.object(rt,'Thread') as worker:
            ident=self.session(); cap=budget.claim(self.user,ident,self.key());budget.dispatch(cap);budget.finish(cap,True)
            with self.assertRaises(audio.store.AudioError) as denied:rt.start(self.user,ident,self.key(2))
            self.assertEqual(denied.exception.code,'budget_limit'); self.assertIn('periode',str(denied.exception));self.assertFalse(denied.exception.purchase_applicable)
            self.assertEqual(len(self.rows()),1);self.assertEqual(self.rows()[0]['charge_micro'],budget.RESERVE_MICRO)
            self.assertEqual(sessions.result(self.user,ident,self.key(2))['error_code'],'budget_limit')
            connect.assert_not_called();worker.assert_not_called()
            response=self.client.get('/kilas-translator/live/sessions/'+ident+'/turns/'+self.key(2))
            self.assertEqual(response.json['code'],'budget_limit');self.assertIn('periode',response.json['error']);self.assertFalse(response.json['recoverable'])

    def test_customer_audio_entitlement_still_denies_before_reservation_or_worker(self):
        with self.funded(),self.on(),self.owner(),patch.object(rt,'require_ready'),patch.object(rt,'Thread') as worker,patch.object(rt,'connect') as connect:
            ident=self.session()
            with self.assertRaises(audio.store.AudioError) as denied:rt.start(self.user,ident,self.key())
            self.assertEqual(denied.exception.code,'zero_balance')
            self.assertEqual(self.rows(),[]);worker.assert_not_called();connect.assert_not_called()

    def test_shared_concurrency_still_blocks_production_owner(self):
        with self.funded(),self.on(),self.owner(),patch.object(batch.free_test,'eligible',return_value=True):
            cap=budget.claim(self.user,'c'*48,self.key())
            with self.assertRaises(batch.BudgetError) as denied:budget.claim(self.user,'c'*48,self.key(2))
            self.assertEqual(denied.exception.code,'already_processing');budget.finish(cap,False)
            with patch.object(batch,'GLOBAL_CONCURRENCY',0):
                with self.assertRaises(batch.BudgetError) as denied:budget.claim(self.user,'c'*48,self.key(3))
                self.assertEqual(denied.exception.code,'service_busy')

    def test_calendar_renewal_uses_new_campaign_without_resetting_old_spend(self):
        with self.funded(),self.on(),self.owner(),patch.object(batch,'datetime',wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,10,31,tzinfo=timezone.utc)
            old=budget.claim(self.user,'c'*48,self.key());budget.dispatch(old);budget.finish(old,True)
            oldconfig=budget.config()
            clock.now.return_value=datetime(2026,11,1,tzinfo=timezone.utc)
            new=budget.claim(self.user,'c'*48,self.key(2));budget.finish(new,False)
            self.assertNotEqual(oldconfig['id'],budget.config()['id'])
            self.assertEqual(self.rows()[0]['charge_micro'],budget.RESERVE_MICRO);self.assertEqual(len(self.rows()),2)

    def test_nonsecret_policy_report_and_all_ui_locales(self):
        import ui_i18n
        from kilas_ai import audio_routes
        with self.funded(),self.owner(),redirect_stdout(io.StringIO()) as output:batch.live_policy_report()
        self.assertIn('continuous_entitled_live=True',output.getvalue());self.assertNotIn('synthetic-only',output.getvalue())
        message='Batas biaya input suara periode ini tercapai. Lanjutkan tidak menambah kapasitas.'
        for locale in ['id','en','es','zh']:
            with audio.f.app.app.test_request_context('/kilas-translator/',headers={'Cookie':'kilas_language='+locale}):
                translated=ui_i18n.translate(message)
                self.assertTrue(translated);self.assertTrue(locale=='id' or translated!=message)
                error=audio.store.AudioError(message,'budget_limit',429);error.purchase_applicable=False
                self.assertNotIn('purchase_url',audio_routes.invalid(error)[0])
                customer=audio.store.AudioError('Saldo tidak cukup.','insufficient_balance',402)
                self.assertIn('purchase_url',audio_routes.invalid(customer)[0])

    def settle_held(self,ident,key):
        with rt._lock:relay=rt._relays.pop((self.user,ident,key))
        try:
            budget.dispatch(relay.capability)
            self.assertTrue(budget.finish(relay.capability,True))
            self.assertFalse(budget.finish(relay.capability,True))
            sessions.finish(self.user,ident,key,True)
        finally:
            relay.close();relay.finished=True;rt._slots.release()

    def test_nonowner_paid_actual_http_admission_25_turns_without_sponsorship(self):
        self.credit(300)
        with self.funded(2000000,2000000),self.on(),self.owner(),patch.dict(os.environ,{
                'KILAS_VO_STT_ALLOWED_OWNER_ID':str(self.other),
                'KILAS_LIVE_TRANSLATOR_ALLOWED_OWNER_ID':str(self.other),
                'KILAS_APP_FREE_TEST_ENABLED':'false'}),patch.object(rt.account,'verified',return_value=True),patch.object(rt,'Thread') as workers,patch.object(rt,'connect') as provider:
            self.assertFalse(batch.free_test.eligible(self.user))
            self.assertTrue(rt.ready(self.user));self.assertFalse(batch.ready(self.user))
            ident=self.session()
            for i in range(25):
                key=self.key(i+1)
                r=self.client.post('/kilas-translator/live/sessions/'+ident+'/turns/'+key+'/input/start',data={'csrf_token':'audio-csrf'})
                self.assertEqual(r.status_code,202,r.json)
                self.settle_held(ident,key)
                self.assertEqual(sessions.status(self.user,ident),{'status':'ACTIVE','processing':False})
                self.assertEqual(sessions.result(self.user,ident,key)['status'],'COMPLETED')
            self.assertEqual(workers.call_count,25);provider.assert_not_called()
            self.assertEqual(sum(r['charge_micro'] for r in self.rows()),25*budget.RESERVE_MICRO)
            # Batch Auto accepts the same paid audience; dispatch must preserve
            # the server marker rather than fall back to an owner-only gate.
            _,cap=batch.claim(self.user,self.key(30),'a'*64,1000,live_session=True)
            batch.dispatch(cap,'a'*64,1000);self.assertTrue(batch.finish(cap,True))
            self.assertEqual(sum(r['charge_micro'] for r in self.rows()),25*budget.RESERVE_MICRO+batch.reserve_micro(1000))
            with self.assertRaises(batch.BudgetError):batch.claim(self.user,'dictate-nonowner-still-restricted-1234','b'*64,1000)

    def test_nonowner_sponsored_trial_25_turns_with_existing_dates_proof_and_funding(self):
        from kilas_ai import live_translator_realtime_check
        audio.f.db.execute("UPDATE users SET role='CLIENT_MEMBER' WHERE id=?",(self.user,))
        from auth_test_helpers import authenticate
        authenticate(self.client,__import__('repo').get_user_by_id(self.user),_csrf_token='audio-csrf')
        with self.funded(2000000,2000000),self.on(),self.owner(),patch.dict(os.environ,{
                'KILAS_VO_STT_ALLOWED_OWNER_ID':str(self.other),
                'KILAS_LIVE_TRANSLATOR_ALLOWED_OWNER_ID':str(self.other),
                'KILAS_APP_FREE_TEST_ENABLED':'true',
                'KILAS_APP_FREE_TEST_END_AT':batch.free_test.END_AT.isoformat()}),patch.object(live_translator_realtime_check,'verified',return_value=True),patch.object(rt.account,'verified',return_value=True),patch.object(rt,'Thread'),patch.object(rt,'connect') as provider:
            self.assertTrue(batch.free_test.eligible(self.user));self.assertTrue(rt.ready(self.user))
            ident=self.session()
            for i in range(25):
                key=self.key(i+1)
                response=self.client.post('/kilas-translator/live/sessions/'+ident+'/turns/'+key+'/input/start',data={'csrf_token':'audio-csrf'})
                self.assertEqual(response.status_code,202,response.json);self.settle_held(ident,key)
            self.assertEqual(len(self.rows()),25);provider.assert_not_called()
            with patch.object(live_translator_realtime_check,'verified',return_value=False):self.assertFalse(rt.ready(self.user))
            with patch.object(batch.free_test,'datetime',wraps=datetime) as clock:
                clock.now.return_value=batch.free_test.STT_END_AT
                self.assertFalse(rt.ready(self.user))
            with transaction() as conn:
                with self.assertRaises(batch.BudgetError) as denied:batch.trial_admit(conn,self.user)
                self.assertEqual(denied.exception.code,'rate_limit')

    def test_nonowner_exhausted_unentitled_and_revoked_audience_never_create_worker(self):
        with self.funded(),self.on(),self.owner(),patch.dict(os.environ,{
                'KILAS_VO_STT_ALLOWED_OWNER_ID':str(self.other),
                'KILAS_LIVE_TRANSLATOR_ALLOWED_OWNER_ID':str(self.other),
                'KILAS_APP_FREE_TEST_ENABLED':'false'}),patch.object(rt.account,'verified',return_value=True),patch.object(rt,'Thread') as workers,patch.object(rt,'connect') as provider:
            self.assertTrue(rt.ready(self.user))
            ident=self.session()
            response=self.client.post('/kilas-translator/live/sessions/'+ident+'/turns/'+self.key()+'/input/start',data={'csrf_token':'audio-csrf'})
            self.assertEqual(response.status_code,402,response.json);self.assertEqual(response.json['code'],'zero_balance')
            self.assertEqual(self.rows(),[])
            audio.f.db.execute("UPDATE users SET role='CLIENT_MEMBER' WHERE id=?",(self.user,))
            self.assertFalse(rt.ready(self.user))
            self.assertFalse(batch.live_audience(self.user,batch.policy()))
            self.assertFalse(batch.live_audience(987654321,batch.policy()))
            workers.assert_not_called();provider.assert_not_called()

    def test_shared_funding_exhaustion_stops_other_paid_and_sponsored_accounts(self):
        from kilas_ai import live_translator_realtime_check
        self.credit(300)
        with self.funded(budget.RESERVE_MICRO,budget.RESERVE_MICRO),self.on(),self.owner(),patch.dict(os.environ,{
                'KILAS_VO_STT_ALLOWED_OWNER_ID':str(self.other),
                'KILAS_LIVE_TRANSLATOR_ALLOWED_OWNER_ID':str(self.other),
                'KILAS_APP_FREE_TEST_ENABLED':'false'}),patch.object(rt.account,'verified',return_value=True),patch.object(live_translator_realtime_check,'verified',return_value=True),patch.object(rt,'Thread') as workers,patch.object(rt,'connect') as provider:
            cap=budget.claim(self.other,'c'*48,self.key(99));budget.dispatch(cap);budget.finish(cap,True)
            ident=self.session()
            for i,sponsored in enumerate([False,True]):
                with patch.dict(os.environ,{'KILAS_APP_FREE_TEST_ENABLED':str(sponsored).lower(),'KILAS_APP_FREE_TEST_END_AT':batch.free_test.END_AT.isoformat()}):
                    r=self.client.post('/kilas-translator/live/sessions/'+ident+'/turns/'+self.key(i+1)+'/input/start',data={'csrf_token':'audio-csrf'})
                    self.assertEqual(r.status_code,429,r.json);self.assertEqual(r.json['code'],'budget_limit')
                    self.assertNotIn('purchase_url',r.json);self.assertEqual(self.rows(),[])
            workers.assert_not_called();provider.assert_not_called()
