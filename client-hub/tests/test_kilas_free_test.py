"""Shared fixed-end sponsorship with synthetic accounts/media and zero provider IO."""
import hashlib
import json
import os
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
import test_kilas_learning as fixture
from kilas_ai import free_test, usage, learning, learning_realtime, learning_store
from kilas_ai import audio_store, audio_service, audio_transcription_budget as budget
from kilas_ai import live_translator as live, live_translator_realtime_budget as realtime_budget
from kilas_ai import live_translator_realtime_check as proof

db=fixture.db
NOW=datetime(2026,10,13,12,tzinfo=timezone.utc)


class FreeTestTests(unittest.TestCase):
    def test_streamed_translator_trial_reads_proof_without_per_event_write_connections(self):
        from kilas_ai import providers, live_translator_store as sessions
        with self.trial():
            self.verified()
            ident=sessions.create(self.user,'id','en','kilas-male');key='live-'+str(self.user).zfill(32)
            sessions.claim(self.user,ident,key)
            payload=json.dumps({'text':'Hello.','source_language':'id','target_language':'en'})
            def stream(*args,**kwargs):
                for character in payload:yield {'type':'delta','text':character}
                yield {'type':'finish','reason':'stop'}
            def fence():live.require_ready(self.user);sessions.check(self.user,ident,key)
            with patch.object(providers,'_openai',side_effect=stream) as provider,patch.object(usage,'_connect',wraps=usage._connect) as connection:
                self.assertEqual(live.translation(self.user,key,'Halo.','id','en',fence)['text'],'Hello.')
                self.assertEqual(connection.call_count,2,'Only reservation and settlement open write connections, never streamed proof reads.')
                provider.assert_called_once()
            db.execute("UPDATE kilas_realtime_checks SET status='UNKNOWN' WHERE approval=?",(proof.APPROVAL,))
            self.assertFalse(live.ready(self.user))

    def setUp(self):
        fixture.LearningTests.setUp(self)
        self.addCleanup(self.cleanup_journals)

    def cleanup_journals(self):
        # Only this test's synthetic accounts; production journals are never touched.
        turns=db.query_all('SELECT t.id FROM kilas_learning_turns t JOIN kilas_learning_sessions s ON s.id=t.session_id WHERE s.user_id IN (?,?)',(self.user,self.other))
        for row in turns:
            for table in ('kilas_learning_input_chunks','kilas_learning_inputs','kilas_learning_clips'):
                db.execute('DELETE FROM '+table+' WHERE turn_id=?',(row['id'],))
            db.execute('DELETE FROM kilas_learning_turns WHERE id=?',(row['id'],))
        db.execute('DELETE FROM kilas_learning_sessions WHERE user_id IN (?,?)',(self.user,self.other))
        db.execute('DELETE FROM kilas_vo_stt_operations WHERE user_id IN (?,?)',(self.user,self.other))

    session=fixture.LearningTests.session
    turn=fixture.LearningTests.turn
    audio=b'synthetic-audio'

    def trial(self, now=NOW):
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return now if tz else now.replace(tzinfo=None)
        from contextlib import ExitStack
        stack=ExitStack()
        stack.enter_context(patch.dict(os.environ,{'KILAS_APP_FREE_TEST_ENABLED':'true',
            'KILAS_APP_FREE_TEST_END_AT':free_test.END_AT.isoformat(),
            'KILAS_VOICE_VIDEO_SCRIPT_ENABLED':'true','KILAS_VO_STT_USAGE_MODE':'owner',
            'KILAS_VO_STT_ALLOWED_OWNER_ID':str(self.other),'KILAS_VO_STT_CAMPAIGN':'trial-'+str(self.user),
            'KILAS_VO_STT_GLOBAL_BUDGET_MICRO_USD':'90000','KILAS_VO_STT_ACCOUNT_BUDGET_MICRO_USD':'90000',
            'KILAS_VO_STT_PRICE_VERSION':budget.PRICE_VERSION,
            'KILAS_LIVE_TRANSLATOR_ENABLED':'true','KILAS_LIVE_TRANSLATOR_ALLOWED_OWNER_ID':str(self.other),
            'KILAS_LIVE_TRANSLATOR_USAGE_MODE':'owner','KILAS_LIVE_TRANSLATOR_AUDIO_SECONDS':'1',
            'KILAS_LEARNING_ENABLED':'true','KILAS_LEARNING_REALTIME_ENABLED':'true',
            'KILAS_LEARNING_REALTIME_BILLING_VERIFIED':'creator-included-scribe-realtime-20261013',
            'KILAS_LEARNING_REALTIME_BUDGET_MICRO_USD':'4875',
            'KILAS_LIVE_TRANSLATOR_VERIFIED_MODEL':learning.model_policy.LUNA,
            'KILAS_LIVE_TRANSLATOR_VERIFIED_STT':budget.MODEL,'KILAS_LIVE_TRANSLATOR_REFERENCE_VERIFIED':'yes',
            'KILAS_LIVE_TRANSLATOR_VERIFIED_PROJECT':'proj_synthetic','OPENAI_API_KEY':'synthetic-only'}))
        stack.enter_context(patch.object(free_test,'datetime',Clock))
        stack.enter_context(patch.object(budget,'datetime',Clock))
        stack.enter_context(patch.object(usage,'datetime',Clock))
        return stack

    def verified(self):
        # Actual persisted verification parser, never an account/provider request.
        config=budget.policy()
        with audio_store.locked(self.other) as conn:
            conn.executescript((Path(__file__).parents[1]/'migrations/0094_kilas_realtime_check_sqlite.sql').read_text())
            budget._campaign(conn,config)
            config={**config,'id':config['id']+'-rt-check'}
            budget._campaign(conn,config)
            usage._query(conn,'DELETE FROM kilas_realtime_checks WHERE approval=?',(proof.APPROVAL,))
            usage._query(conn,"INSERT INTO kilas_realtime_checks(approval,user_id,key_digest,campaign,source_digest,model,status,expected_pcm_ms,before_used,before_limit,after_used,after_limit,accepted,attributed,window_start_ms,actual_wire_ms,sent_pcm_ms,before_overage_kind,result,created_at) VALUES (?,?,?,?,?,?,'VERIFIED',5000,10,1000,12,1000,1,1,0,3862,5000,'usd','committed',?)",(proof.APPROVAL,self.other,proof.digest(),config['id'],proof.SOURCE,'scribe_v2_realtime',NOW.isoformat()))
        self.assertTrue(proof.verified())

    def job(self,key='trial-audio-synthetic',user=None):
        user=user or self.user
        return audio_store.create(user,key,'voiceover','Synthetic','id','en','syntheticVoice','Kilas Male','Hello',0,None,2,10)[0]

    def test_fixed_cutoff_and_fail_closed_configuration(self):
        with self.trial():
            self.assertTrue(free_test.active(free_test.END_AT-timedelta(microseconds=1)))
            self.assertFalse(free_test.active(free_test.END_AT))
            self.assertFalse(free_test.active(free_test.END_AT+timedelta(days=1)))
            self.assertFalse(free_test.active(NOW.replace(tzinfo=None)))
            for value in ('2026-12-12T16:59:00Z','2027-01-01T00:00:00Z','bad','2026-12-11T16:59:00'):
                with patch.dict(os.environ,{'KILAS_APP_FREE_TEST_END_AT':value}):self.assertFalse(free_test.active(NOW))
            with patch.dict(os.environ,{'KILAS_APP_FREE_TEST_ENABLED':'false'}):self.assertFalse(free_test.active(NOW))

    def test_all_real_accounts_without_subscription_or_role_mutation(self):
        with self.trial():
            for user in (self.user,self.other):
                self.assertTrue(free_test.eligible(user))
                self.assertTrue(usage.qa_exempt(user))
                self.assertEqual(usage.effective_plan(user)['plan'],'FREE')
                self.assertEqual(audio_store.balance(user)['seconds'],0)
                self.assertTrue(audio_store.require_balance(user)['exempt'])
            for invalid in (None,0,-1,True,'9',99999999):self.assertFalse(free_test.eligible(invalid))
            db.execute("UPDATE users SET role='CLIENT_MEMBER' WHERE id=?",(self.user,))
            self.assertTrue(free_test.eligible(self.user))
            self.assertEqual(db.query_one('SELECT role FROM users WHERE id=?',(self.user,))['role'],'CLIENT_MEMBER')

    def test_anonymous_invalid_role_session_and_admin_connector_isolation(self):
        with self.trial(),patch.object(learning.voices,'public_choices',return_value=[fixture.VOICE]):
            for url in ('/kilas-ai','/kilas-translator?mode=voiceover','/kilas-learning'):
                self.assertEqual(self.client.get(url,follow_redirects=True).status_code,200)
                self.assertEqual(fixture.fixture.f.app.app.test_client().get(url).status_code,302)
            db.execute("UPDATE users SET role='CLIENT_MEMBER' WHERE id=?",(self.user,))
            self.assertEqual(self.client.get('/kilas-learning').status_code,403)
            with self.client.session_transaction() as state:state['role']='CLIENT_MEMBER'
            self.assertEqual(self.client.get('/kilas-learning').status_code,200)
            self.assertEqual(self.client.get('/kilas-ai/agent/connections/google/callback').status_code,404)
            self.assertNotEqual(self.client.get('/admin/kilas-ai').status_code,200)

    def test_verified_provider_funding_opens_nonowner_without_changing_allowlist(self):
        with self.trial():
            self.verified()
            for user in (self.user,self.other):
                self.assertTrue(budget.ready(user));self.assertTrue(learning.ready(user));self.assertTrue(live.ready(user))
            self.assertEqual(budget.policy()['allowed_owner'],self.other)
            self.assertFalse(budget.ready(99999999))
            with patch.dict(os.environ,{'ELEVENLABS_API_KEY':'different-synthetic-key'}):
                self.assertFalse(budget.ready(self.user));self.assertFalse(learning.ready(self.user))
            db.execute("UPDATE kilas_realtime_checks SET status='UNKNOWN' WHERE approval=?",(proof.APPROVAL,))
            self.assertFalse(budget.ready(self.user));self.assertFalse(live.ready(self.user))

    def test_separate_funding_expiry_stops_speech_without_stopping_app_trial(self):
        with self.trial():self.verified()
        with self.trial(free_test.STT_END_AT):
            self.assertTrue(free_test.eligible(self.user))
            self.assertTrue(audio_store.require_balance(self.user)['exempt'])
            self.assertIsNone(budget.policy())
            self.assertFalse(budget.ready(self.user));self.assertFalse(learning.ready(self.user));self.assertFalse(live.ready(self.user))
            with self.assertRaises(budget.BudgetError):budget.claim(self.user,'dictate-synthetic-123',hashlib.sha256(b'x').hexdigest(),1000)

    def test_app_expiry_restores_nonowner_balance_and_account_gates(self):
        with self.trial(free_test.END_AT):
            self.assertFalse(usage.qa_exempt(self.user))
            with self.assertRaises(audio_store.AudioError):audio_store.require_balance(self.user)
            self.assertFalse(learning.ready(self.user));self.assertFalse(live.ready(self.user))

    def test_trial_chat_records_real_usage_and_keeps_burst_and_concurrency(self):
        with self.trial(),patch.object(usage,'_cost_guard',side_effect=AssertionError('ordinary product gate called')):
            for n in range(12):
                key='trial-chat-'+str(n)
                _,ops=usage.reserve(self.user,None,key,'SMART','CHAT')
                usage.finish(self.user,key,ops,success=True,provider='openai',model=learning.model_policy.LUNA,usage={'input_tokens':30,'output_tokens':12})
            row=db.query_one("SELECT input_tokens,output_tokens,estimated_cost_usd FROM kilas_ai_usage WHERE user_id=? AND operation_key='trial-chat-11'",(self.user,))
            self.assertEqual((row['input_tokens'],row['output_tokens']),(30,12));self.assertGreater(float(row['estimated_cost_usd']),0)
            for n in range(3):usage.reserve(self.user,None,'trial-pending-'+str(n),'FAST','CHAT')
            with self.assertRaises(usage.UsageLimit):usage.reserve(self.user,None,'trial-concurrent-block','FAST','CHAT')
            with patch.dict(os.environ,{'KILAS_AI_BURST_PER_MINUTE':'1'}):
                with self.assertRaises(usage.UsageLimit):usage.reserve(self.user,None,'trial-burst-block','FAST','CHAT')

    def test_audio_sponsorship_settles_once_after_expiry_and_is_user_bound(self):
        with self.trial():
            job=self.job();self.assertTrue(audio_store.start(self.user,job))
            self.assertEqual(self.job(),job)
            with audio_store.locked(self.user) as conn:
                self.assertTrue(free_test.sponsored_audio(conn,self.user,job))
                self.assertFalse(free_test.sponsored_audio(conn,self.other,job))
        with self.trial(free_test.END_AT):
            self.assertTrue(audio_store.finish(self.user,job,self.audio,2400))
            self.assertFalse(audio_store.finish(self.user,job,self.audio,2400))
            row=audio_store.get(self.user,job)
            self.assertEqual((row['actual_ms'],row['seconds_charged']),(2400,0))
            self.assertIsNone(audio_store.get(self.other,job))
            with self.assertRaises(audio_store.AudioError):self.job('trial-post-expiry-new')

    def test_trial_audio_keeps_concurrency_and_requests_cannot_forge_sponsorship(self):
        with self.trial():
            job=self.job()
            with self.assertRaises(audio_store.AudioError) as error:self.job('trial-another-synthetic')
            self.assertEqual(error.exception.code,'busy')
        with patch.dict(os.environ,{'KILAS_APP_FREE_TEST_ENABLED':'false'}):
            with audio_store.locked(self.user) as conn:
                self.assertFalse(free_test.sponsored_audio(conn,self.user,job+10000))
            with self.assertRaises(audio_store.AudioError):self.job('trial-forged-prefix',self.other)

    def test_learning_trial_removes_daily_product_cap_and_retains_actual_duration(self):
        with self.trial():
            sid=self.session();turn=self.turn(sid);job=self.job();audio_store.start(self.user,job)
            db.execute('INSERT INTO kilas_learning_clips(turn_id,sequence,chars,dispatched_at) VALUES (?,?,?,?)',(turn,0,6000,usage._now().isoformat()))
            learning_store.dispatch_clip(self.user,sid,turn,1,'Hello',job)
        with self.trial(free_test.END_AT):
            learning_store.commit_clip(self.user,sid,turn,1,job,self.audio,2400)
            self.assertEqual(audio_store.get(self.user,job)['seconds_charged'],0)
            self.assertEqual(audio_store.get(self.user,job)['actual_ms'],2400)
            with self.assertRaises(learning_store.Error):learning_store.dispatch_clip(self.user,sid,turn,2,'New speech',job)
            with self.assertRaises(learning_store.Error):learning_store.state(self.other,sid)

    def test_learning_admission_uses_shared_financial_guard_and_keeps_hourly_limit(self):
        with self.trial():
            self.verified();sid=self.session()
            with patch.object(learning._executor,'submit'):
                self.assertTrue(learning_realtime.begin(self.user,sid,'trial-learning-input-123'))
                learning._slots.release()
            config=budget.policy()
            with audio_store.locked(self.other) as conn:
                usage._query(conn,"INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at) VALUES (?,?,?,'x','UNKNOWN',85000,1000,'x',?)",(self.other,'trial-used-financial',config['id'],NOW.isoformat()))
            learning_realtime.cancel(self.user,sid,'trial-learning-input-123')
            with self.assertRaises(learning_store.Error) as error:learning_realtime.begin(self.user,sid,'trial-learning-limit-123')
            self.assertEqual(error.exception.code,'learning_stt_limit')

    def test_learning_personal_product_allowance_is_removed_but_twenty_per_hour_remains(self):
        with self.trial():
            self.verified();sid=self.session()
            with patch.object(learning._executor,'submit'):
                for n in range(2):
                    key='trial-learning-two-'+str(n)
                    self.assertTrue(learning_realtime.begin(self.user,sid,key));learning._slots.release()
                    learning_realtime.cancel(self.user,sid,key)
            total=db.query_one('SELECT SUM(i.charge_micro) AS n FROM kilas_learning_inputs i JOIN kilas_learning_turns t ON t.id=i.turn_id WHERE t.session_id=?',(sid,))['n']
            self.assertGreater(total,4875)
            config=budget.policy()
            with audio_store.locked(self.user) as conn:
                for n in range(18):
                    usage._query(conn,"INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at) VALUES (?,?,?,'x','CANCELLED',0,0,'x',?)",(self.user,'trial-rate-'+str(n),config['id'],NOW.isoformat()))
            with self.assertRaises(budget.BudgetError) as error:learning_realtime.begin(self.user,sid,'trial-hourly-denied')
            self.assertEqual(error.exception.code,'rate_limit')

    def test_daily_stt_product_attempts_removed_and_hourly_guard_preserved(self):
        with self.trial():
            self.verified();config=budget.policy()
            with audio_store.locked(self.user) as conn:
                for n in range(121):
                    usage._query(conn,"INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at) VALUES (?,?,?,'x','CANCELLED',0,0,'x',?)",(self.user,'dictate-old-'+str(n),config['id'],(NOW-timedelta(hours=2)).isoformat()))
            _,lease=budget.claim(self.user,'dictate-unlimited-product',hashlib.sha256(b'x').hexdigest(),1000)
            budget.dispatch(lease,hashlib.sha256(b'x').hexdigest(),1000)
            self.assertTrue(budget.finish(lease,True))

    def test_existing_server_budget_block_and_ambiguous_costs_are_not_bypassed(self):
        with self.trial():
            self.verified();config=budget.policy()
            db.execute('UPDATE kilas_vo_stt_campaigns SET blocked=1 WHERE id=?',(config['id'],))
            with self.assertRaises(budget.BudgetError) as error:budget.claim(self.user,'dictate-blocked-funding',hashlib.sha256(b'x').hexdigest(),1000)
            self.assertEqual(error.exception.code,'campaign_blocked')

    def test_expiry_cannot_dispatch_old_realtime_lease_but_can_settle_it(self):
        with self.trial():
            self.verified();lease=realtime_budget.claim(self.user,'synthetic-sid','live-'+'d'*32)
            realtime_budget.dispatch(lease)
        with self.trial(free_test.STT_END_AT):
            with self.assertRaises(budget.BudgetError):realtime_budget.dispatch(lease)
            self.assertTrue(realtime_budget.finish(lease,True))
            row=db.query_one('SELECT charge_micro FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key=?',(self.user,lease.key))
            self.assertEqual(row['charge_micro'],realtime_budget.RESERVE_MICRO)

    def test_realtime_leases_nonowner_nonce_single_dispatch_and_cross_account_denial(self):
        with self.trial():
            self.verified();sid=self.session();key='live-'+'a'*32
            lease=realtime_budget.claim(self.user,sid,key)
            realtime_budget.dispatch(lease)
            with self.assertRaises(budget.BudgetError):realtime_budget.dispatch(lease)
            forged=budget.Reservation(self.other,lease.key,lease.lease)
            with self.assertRaises(budget.BudgetError):realtime_budget.dispatch(forged)
            self.assertTrue(realtime_budget.finish(lease,True))
            self.assertFalse(realtime_budget.finish(lease,True))

    def test_shared_financial_guard_counts_learning_when_admitting_translator(self):
        with self.trial():
            self.verified();sid=self.session();turn=self.turn(sid)
            db.execute("INSERT INTO kilas_learning_inputs(turn_id,status,charge_micro,created_at) VALUES (?,'FAILED',89000,?)",(turn,NOW.isoformat()))
            with self.assertRaises(budget.BudgetError) as error:realtime_budget.claim(self.other,'synthetic-sid','live-'+'b'*32)
            self.assertEqual(error.exception.code,'budget_limit')

    def test_audio_generation_still_stops_on_provider_credit_failure(self):
        # Provider IO is mocked at the existing prepaid guard; no paid QA call.
        with self.trial():
            job=self.job()
            with patch.object(learning.stt,'require_subscription_credit',side_effect=budget.BudgetError('provider_credit_exhausted',402)),patch.object(audio_service.provider,'speech') as paid:
                audio_service.submit(self.user,job)
                paid.assert_not_called()
            self.assertEqual(audio_store.get(self.user,job)['error_code'],'provider_credit_exhausted')


if __name__=='__main__':unittest.main()
