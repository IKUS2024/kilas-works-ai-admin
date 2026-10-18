"""Production owner Live count scope; real SQLite accounting, no provider IO."""
import io
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
    key = fixture.LiveTranslatorTests.key
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
            with transaction() as conn:
                with self.assertRaises(batch.BudgetError) as denied:
                    batch._admit(conn,self.user,{**batch.policy(),'allowed_owner':self.other},budget.RESERVE_MICRO,self.key(31),live_session=True)
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

    def test_exemption_requires_existing_explicit_owner_and_production_modes(self):
        with self.funded(),self.owner():
            config=batch.policy()
            self.assertTrue(batch.continuous_owner_live(self.user,config,self.key()))
            for changes,key in [({'allowed_owner':self.other},self.key()),({'allowed_owner':None},self.key()),({'mode':'qa'},self.key()),({},'dictate-operation-1234')]:
                self.assertFalse(batch.continuous_owner_live(self.user,{**config,**changes},key))
            with patch.dict(os.environ,{'KILAS_LIVE_TRANSLATOR_USAGE_MODE':'qa'}):self.assertFalse(batch.continuous_owner_live(self.user,config,self.key()))

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
        self.assertIn('continuous_owner_live=True',output.getvalue());self.assertNotIn('synthetic-only',output.getvalue())
        message='Batas biaya input suara periode ini tercapai. Lanjutkan tidak menambah kapasitas.'
        for locale in ['id','en','es','zh']:
            with audio.f.app.app.test_request_context('/kilas-translator/',headers={'Cookie':'kilas_language='+locale}):
                translated=ui_i18n.translate(message)
                self.assertTrue(translated);self.assertTrue(locale=='id' or translated!=message)
                error=audio.store.AudioError(message,'budget_limit',429);error.purchase_applicable=False
                self.assertNotIn('purchase_url',audio_routes.invalid(error)[0])
                customer=audio.store.AudioError('Saldo tidak cukup.','insufficient_balance',402)
                self.assertIn('purchase_url',audio_routes.invalid(customer)[0])
