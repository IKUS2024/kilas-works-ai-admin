"""Real store/admission boundaries; synthetic tariffs/audio, no supplier calls."""
import json
import os
import struct
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import test_kilas_credit_wallet as foundation
import db
from kilas_ai import credit_policy as policy, credit_wallet as wallet, usage
from kilas_ai import credit_audio, audio_store as audio, live_translator_store as sessions
from kilas_ai import live_translator_output as output


TARIFFS = {
    'version':'customer-credit-v1', 'voice_allocation':'proportional_actual_duration',
    'rates':{'VOICE':{'milli':100, 'units':1},
             'TRANSLATOR':{'milli':1000, 'units':1000},
             'RECEIPT':{'milli':1000, 'units':1}},
    'limits':{
        'VOICE':{'models':['eleven_multilingual_v2','eleven_v4'], 'characters':4000, 'output_ms':600000},
        'TRANSLATOR':{'models':['gpt-6-luna','gemini-3.5-live-translate-preview','dubbing_v2'],
                      'source_ms':600000, 'output_ratio_milli':2000},
        'RECEIPT':{'models':['gpt-6-luna'], 'input_tokens':200000, 'output_tokens':2048, 'bytes':1000,'input_accounting_verified':'luna-responses-count-32k-2048-v2'},
    },
}


class AdapterTests(unittest.TestCase):
    fund=foundation.WalletTests.fund
    proof=foundation.WalletTests.proof

    def setUp(self):
        foundation.WalletTests.setUp(self)
        self.flags=patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'yes',
            'KILAS_CREDIT_TARIFFS_JSON':json.dumps(TARIFFS)})
        self.flags.start()
        conn=usage._connect()
        try:
            for number in ('0083','0084','0086','0090','0092','0095','0098','0110'):
                file=next((Path(__file__).parents[1]/'migrations').glob(number+'*_'+db.BACKEND+'.sql'))
                if db.BACKEND=='sqlite':conn.executescript(file.read_text())
                else:
                    with conn.cursor() as cursor:cursor.execute(file.read_text())
            conn.commit()
        finally:conn.close()
        self.addCleanup(output._items.clear)

    def tearDown(self):
        self.flags.stop()
        foundation.WalletTests.tearDown(self)

    def voice(self,key,reserve=60,script='x'*100):
        return audio.create(1,key,'voiceover','Synthetic','en','en','voice123','Synthetic',
                            script,0,None,10,reserve,credit_context=True)

    def approve(self,call):
        with self.assertRaises(policy.ConsentRequired) as caught:call()
        token=policy.persist_consent(caught.exception)
        policy.consent(1,token,True)
        return call()

    def state(self,key):
        return db.query_one('SELECT * FROM kilas_credit_admissions WHERE user_id=1 AND operation_key=?',(key,))

    def test_voice_free_then_split_duration_characters_and_unused_release(self):
        self.fund()
        job,new=self.voice('vo-free')
        self.assertTrue(new);self.assertTrue(audio.start(1,job))
        self.assertTrue(audio.finish(1,job,b'synthetic',30000))
        self.assertEqual(wallet.balance(1)['balance_milli'],2000000)
        self.assertEqual(self.state('vo-free')['free_actual'],30000)
        job,new=self.approve(lambda:self.voice('vo-split'))
        self.assertEqual(self.state('vo-split')['source'],'SPLIT')
        self.assertEqual(wallet.balance(1)['reserved_milli'],10000)
        audio.start(1,job);audio.finish(1,job,b'synthetic',40000)
        #100chars *10paid seconds /40actual seconds =25chars.
        self.assertEqual(wallet.balance(1)['balance_milli'],1997500)
        self.assertEqual(wallet.balance(1)['reserved_milli'],0)
        self.assertEqual(self.state('vo-split')['priced_actual'],25)
        self.assertFalse(self.voice('vo-split')[1])
        with self.assertRaisesRegex(audio.AudioError,'Permintaan berubah'):
            self.voice('vo-split',script='y'*100)
        self.assertEqual(audio.balance(1)['seconds'],0)

    def test_declined_consent_no_job_no_hold_and_account_isolation(self):
        self.fund()
        with self.assertRaises(policy.ConsentRequired) as caught:self.voice('declined',reserve=61)
        token=policy.persist_consent(caught.exception)
        with self.assertRaisesRegex(wallet.WalletError,'not_found'):policy.consent(2,token,True)
        policy.consent(1,token,False)
        with self.assertRaisesRegex(wallet.WalletError,'declined'):self.voice('declined',reserve=61)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs')['n'],0)
        self.assertEqual(wallet.balance(1)['reserved_milli'],0)

    def test_insufficient_credit_never_admits_audio(self):
        with self.assertRaisesRegex(wallet.WalletError,'insufficient'):self.voice('insufficient',reserve=61)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs')['n'],0)

    def test_unknown_audio_failure_held_until_authorized_fenced_reconciliation(self):
        self.fund();job,_=self.approve(lambda:self.voice('interrupted',reserve=90))
        audio.start(1,job);credit_audio.mark_audio_dispatched(1,job)
        with self.assertRaisesRegex(wallet.WalletError,'still_active'):
            policy.reconcile(1,'interrupted',3,'NOT_DELIVERED',0,'synthetic evidence')
        audio.fail(1,job,'submission_interrupted')
        self.assertEqual(self.state('interrupted')['status'],'RESERVED')
        self.assertEqual(wallet.balance(1)['reserved_milli'],10000)
        self.assertFalse(self.voice('interrupted',reserve=90)[1])
        with self.assertRaisesRegex(wallet.WalletError,'forbidden'):
            policy.reconcile(1,'interrupted',2,'NOT_DELIVERED',0,'synthetic evidence')
        for _ in range(2):policy.reconcile(1,'interrupted',3,'NOT_DELIVERED',0,'synthetic evidence')
        self.assertEqual(wallet.balance(1)['reserved_milli'],0)
        self.assertEqual(self.state('interrupted')['status'],'RELEASED')
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_reconciliations')['n'],1)

    def test_pre_dispatch_failure_releases_free_and_paid(self):
        self.fund();job,_=self.approve(lambda:self.voice('pre-dispatch',reserve=90))
        audio.fail(1,job,'voice_unavailable')
        self.assertEqual(wallet.balance(1)['available_milli'],2000000)
        self.assertEqual(self.state('pre-dispatch')['status'],'RELEASED')
        with wallet._locked(1) as conn:
            self.assertEqual(policy.remaining_in(conn,1,'VOICE',usage._now()),60000)

    def test_pcm_meter_packet_invariant_no_idle_wall_time(self):
        raw=b'\0\0'*16000+struct.pack('<h',1000)*16000+b'\0\0'*16000
        meter=credit_audio.SourceMeter()
        for index in range(0,len(raw),146):meter.feed(raw[index:index+146])
        self.assertEqual(meter.milliseconds,credit_audio.pcm_units(raw))
        self.assertEqual(meter.milliseconds,1000)
        self.assertEqual(credit_audio.pcm_units(b'\0\0'*160000),0)
        with self.assertRaises(wallet.WalletError):meter.feed(b'x')

    def test_translator_both_directions_share_free_source_not_idle(self):
        first=sessions.create(1,'id','en','kilas-female')
        sessions.claim(1,first,'live-first',credit_maximum_ms=180000)
        credit_audio.source(1,'live-first',struct.pack('<h',1000)*16000)
        with wallet._locked(1) as conn:credit_audio.finish_turn_in(conn,1,'live-first',True)
        sessions.end(1,first)
        second=sessions.create(1,'en','id','kilas-female')
        sessions.claim(1,second,'live-second',credit_maximum_ms=179000)
        credit_audio.source(1,'live-second',b'\0\0'*32000)
        sessions.finish(1,second,'live-second',True)
        with wallet._locked(1) as conn:
            self.assertEqual(policy.remaining_in(conn,1,'TRANSLATOR',usage._now()),179000)
        self.assertEqual(self.state('live-second')['actual_units'],0)
        with self.assertRaises(audio.AudioError):sessions.claim(2,second,'foreign',credit_maximum_ms=1000)
        with self.assertRaises(audio.AudioError):sessions.claim(1,second,'live-second',credit_maximum_ms=1000)

    def test_translator_split_reservation_and_output_cap(self):
        self.fund()
        policy.admit(1,'already-free','TRANSLATOR',170000,'a'*64)
        policy.finish(1,'already-free',170000,success=True)
        ident=sessions.create(1,'id','en','kilas-female')
        self.approve(lambda:sessions.claim(1,ident,'live-split',credit_maximum_ms=20000))
        credit_audio.source_units(1,'live-split',15000,'b'*64)
        credit_audio.dispatched(1,'live-split')
        with wallet._locked(1) as conn:
            usage._query(conn,'UPDATE kilas_credit_translation_links SET output_ms=30001 WHERE user_id=1 AND operation_key=?',('live-split',))
        with self.assertRaisesRegex(wallet.WalletError,'output_cap'):sessions.finish(1,ident,'live-split',True)
        self.assertEqual(self.state('live-split')['status'],'RESERVED')
        with wallet._locked(1) as conn:
            usage._query(conn,'UPDATE kilas_credit_translation_links SET output_ms=30000 WHERE user_id=1 AND operation_key=?',('live-split',))
        sessions.finish(1,ident,'live-split',True)
        self.assertEqual(self.state('live-split')['free_actual'],10000)
        self.assertEqual(wallet.balance(1)['balance_milli'],1995000)
        self.assertEqual(wallet.balance(1)['reserved_milli'],0)

    def test_accepted_translation_audio_child_survives_cutoff_rollback(self):
        ident=sessions.create(1,'id','en','kilas-female')
        sessions.claim(1,ident,'accepted-parent',credit_maximum_ms=1000)
        credit_audio.source_units(1,'accepted-parent',1000,'a'*64)
        with patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'no','KILAS_CREDIT_CUTOFF_CANDIDATE_ENABLED':'yes'}):
            job,new=audio.create(1,'accepted-parent-audio','voiceover','Synthetic','id','en','voice123','Synthetic','Translated text',0,None,1,2,credit_context=True,live_session=(ident,'accepted-parent'))
            self.assertTrue(new);self.assertEqual(audio.balance(1)['seconds'],0)
            self.assertTrue(audio.start(1,job));audio.finish(1,job,b'synthetic',1000)
            sessions.finish(1,ident,'accepted-parent',True)
        self.assertEqual(self.state('accepted-parent')['status'],'CAPTURED')
        self.assertEqual(self.state('accepted-parent')['actual_units'],1000)
        self.assertEqual(wallet.balance(1)['balance_milli'],0)

    def test_concurrent_free_admission_cannot_replenish_quota(self):
        def reserve(index):
            try:return policy.admit(1,'parallel-'+str(index),'VOICE',60000,'a'*64)
            except wallet.WalletError:return None
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(reserve,range(8)))
        self.assertEqual(sum(result is not None for result in results),1)

    def test_historical_audio_duration_not_recounted_after_restart_or_wallet_capture(self):
        # Old purchased/sponsored usage counts toward allowance only; no conversion/debit.
        with patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'no'}), patch.object(usage,'_qa_quota_exempt',return_value=True):
            job,_=self.voice('old-success',reserve=60)
            audio.start(1,job);audio.finish(1,job,b'synthetic',20000)
        self.assertEqual(self.voice('old-success',reserve=60),(job,False))
        job,_=self.voice('new-success',reserve=40)
        audio.start(1,job);audio.finish(1,job,b'synthetic',10000)
        for _ in range(2):
            with wallet._locked(1) as conn:
                foundation.schema.apply(conn)
                self.assertEqual(policy.remaining_in(conn,1,'VOICE',usage._now()),30000)
        self.assertEqual(wallet.balance(1)['balance_milli'],0)

    def test_quote_is_bound_to_input_tariff_and_expiry(self):
        from datetime import timedelta
        self.fund()
        with self.assertRaises(policy.ConsentRequired) as caught:
            policy.admit(1,'immutable','TRANSLATOR',180001,'a'*64)
        first=caught.exception.token;policy.consent(1,first,True)
        with self.assertRaises(policy.ConsentRequired) as caught:
            policy.admit(1,'immutable','TRANSLATOR',180001,'b'*64)
        self.assertNotEqual(first,caught.exception.token)
        # Changed same-price payload cannot consume approval for the old payload.
        self.assertEqual(db.query_one('SELECT status FROM kilas_credit_consents WHERE token=?',(first,))['status'],'APPROVED')
        altered=json.loads(json.dumps(TARIFFS));altered['rates']['TRANSLATOR']['milli']=2000
        with patch.dict(os.environ,{'KILAS_CREDIT_TARIFFS_JSON':json.dumps(altered)}):
            with self.assertRaises(policy.ConsentRequired) as caught:
                policy.admit(1,'immutable','TRANSLATOR',180001,'a'*64)
            self.assertNotEqual(first,caught.exception.token)
        with patch.object(usage,'_now',return_value=usage._now()+timedelta(minutes=21)):
            with self.assertRaisesRegex(wallet.WalletError,'expired'):policy.admit(1,'immutable','TRANSLATOR',180001,'a'*64)
        self.assertEqual(wallet.balance(1)['reserved_milli'],0)

    def test_captured_audio_never_releases_on_late_failure(self):
        self.fund();job,_=self.approve(lambda:self.voice('captured-late',reserve=90))
        audio.start(1,job);audio.finish(1,job,b'synthetic',90000)
        before=wallet.balance(1)
        with self.assertRaisesRegex(wallet.WalletError,'settlement_conflict'):audio.fail(1,job,'provider_failed')
        self.assertEqual(before,wallet.balance(1))
        self.assertEqual(audio.get(1,job)['status'],'COMPLETED')

    def test_recorded_translator_consent_binds_source_bytes(self):
        self.fund();ident=sessions.create(1,'id','en','kilas-female')
        call=lambda digest:sessions.claim(1,ident,'source-bound',credit_maximum_ms=180001,credit_payload_digest=digest)
        with self.assertRaises(policy.ConsentRequired) as caught:call('a'*64)
        token=policy.persist_consent(caught.exception);policy.consent(1,token,True)
        with self.assertRaises(policy.ConsentRequired):call('b'*64)
        self.assertIsNone(self.state('source-bound'))
        self.assertEqual(wallet.balance(1)['reserved_milli'],0)

    def test_unknown_translator_end_holds_until_fenced_reconciliation(self):
        self.fund();ident=sessions.create(1,'id','en','kilas-female')
        self.approve(lambda:sessions.claim(1,ident,'unknown-root',credit_maximum_ms=180001))
        credit_audio.dispatched(1,'unknown-root')
        with self.assertRaisesRegex(wallet.WalletError,'still_active'):
            policy.reconcile(1,'unknown-root',3,'NOT_DELIVERED',0,'synthetic outcome record')
        sessions.end(1,ident)
        sessions.finish(1,ident,'unknown-root',False,code='gemini_transport')
        self.assertEqual(self.state('unknown-root')['status'],'RESERVED')
        policy.reconcile(1,'unknown-root',3,'NOT_DELIVERED',0,'synthetic outcome record')
        self.assertEqual(self.state('unknown-root')['status'],'RELEASED')
        self.assertEqual(wallet.balance(1)['reserved_milli'],0)

    def test_parallel_translator_settlement_captures_once(self):
        self.fund();ident=sessions.create(1,'id','en','kilas-female')
        self.approve(lambda:sessions.claim(1,ident,'parallel-finish',credit_maximum_ms=200000))
        credit_audio.source_units(1,'parallel-finish',190000,'a'*64)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _:sessions.finish(1,ident,'parallel-finish',True),range(12)))
        self.assertEqual(wallet.balance(1)['balance_milli'],1990000)
        self.assertEqual(wallet.balance(1)['reserved_milli'],0)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_credit_events WHERE event_key=?",('capture:parallel-finish',))['n'],1)

    def test_upload_translation_uses_speech_units_keeps_full_media_duration(self):
        job,_=audio.create(1,'upload-translation','translate','Synthetic','id','en','','','',3000,b'synthetic',3,3,credit_context=True,credit_source_ms=1000)
        audio.start(1,job)
        audio.finish(1,job,b'synthetic',3000,credit_output_ms=1500)
        self.assertEqual(self.state('upload-translation')['actual_units'],1000)
        self.assertEqual(audio.get(1,job)['actual_ms'],3000)
        self.assertEqual(wallet.balance(1)['balance_milli'],0)
        with self.assertRaisesRegex(wallet.WalletError,'meter_missing'):
            audio.create(1,'missing-source','translate','Synthetic','id','en','','','',3000,b'synthetic',3,3,credit_context=True)

    def test_work_image_retry_keeps_logical_key_and_pins_actual_model(self):
        from kilas_ai.agent_workers import image_worker
        model='gpt-image-2.5-sunburst'
        job={'user_id':1,'checkpoint_json':'{}'}
        step={'idempotency_key':'stable-work-image','attempts':1,'action':'generate'}
        with patch.dict(os.environ,{'KILAS_AI_OPENAI_IMAGE_MODEL':model}),patch.object(image_worker.chat_offering,'for_job',return_value=None),patch.object(usage,'reserve',side_effect=usage.UsageLimit('synthetic stop before provider')) as reserve,patch.object(image_worker.tools,'image') as provider:
            for attempt in (1,2):
                with self.assertRaises(usage.UsageLimit):image_worker.run(job,{**step,'attempts':attempt},{'prompt':'Synthetic 2K image'})
                self.assertEqual(reserve.call_args.args[2],'stable-work-image')
                self.assertEqual(reserve.call_args.kwargs['profile']['image_model'],model)
            provider.assert_not_called()

    def test_voice_model_change_after_quote_requires_new_approval(self):
        self.fund()
        with self.assertRaises(policy.ConsentRequired) as caught:self.voice('model-bound',reserve=90)
        token=policy.persist_consent(caught.exception);policy.consent(1,token,True)
        with wallet._locked(1) as conn:
            now=usage._now().isoformat()
            usage._query(conn,"INSERT INTO kilas_audio_personal_voices(user_id,voice_id) VALUES (1,'voice123')")
            usage._query(conn,"INSERT INTO kilas_audio_saved_voices(user_id,name,voice_id,operation_key,consent_at,updated_at) VALUES (1,'Synthetic','voice123','synthetic-save',?,?)",(now,now))
        with self.assertRaises(policy.ConsentRequired) as caught:self.voice('model-bound',reserve=90)
        self.assertNotEqual(token,caught.exception.token)
        self.assertEqual(wallet.balance(1)['reserved_milli'],0)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs')['n'],0)


if __name__=='__main__':unittest.main()
