"""Activated native adapter with real ledgers and an entirely synthetic socket."""
import json
import os
import unittest
from unittest.mock import patch
import test_kilas_live_gemini as fixture
from test_kilas_credit_adapters import TARIFFS
from kilas_ai import credit_wallet_schema as schema, usage, credit_policy as policy
from kilas_ai import live_gemini as native, live_translator_store as sessions, audio_store
from kilas_ai import live_translator as classic, live_translator_segments as segments
from kilas_ai import audio_service, audio_provider, audio_transcription_budget


class NativeCreditTests(unittest.TestCase):
    setUp=fixture.GeminiTests.setUp
    config=fixture.GeminiTests.config
    key=fixture.GeminiTests.key
    funded=fixture.fixture.LiveTranslatorTests.funded
    on=fixture.fixture.LiveTranslatorTests.on
    signal=fixture.fixture.LiveTranslatorTests.signal
    transcribe=fixture.fixture.LiveTranslatorTests.transcribe
    stream=fixture.fixture.LiveTranslatorTests.stream

    @classmethod
    def setUpClass(cls):cls.audio=fixture.audio.mp3(.6)

    def install(self):
        conn=usage._connect()
        try:schema.apply(conn);conn.commit()
        finally:conn.close()
        flags=patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'yes','KILAS_CREDIT_TARIFFS_JSON':json.dumps(TARIFFS)})
        flags.start();self.addCleanup(flags.stop)

    def test_synthetic_native_completion_uses_source_duration_without_legacy_seconds(self):
        self.install()
        with self.config():
            ident=sessions.create(self.user,'id','en',native.VOICE)
            with patch.object(native.Thread,'start'):relay=native.start(self.user,ident,self.key())
            self.addCleanup(lambda:native._slots.release() if not relay.finished else None)
            relay.accept(0,b'\xe8\x03'*1600);relay.finish_input(1)
            with patch.object(native,'connect',return_value=fixture.Socket()) as connect:relay.run()
            self.assertEqual(connect.call_count,1)
            self.assertTrue(relay.finished)
            self.assertIsNone(relay.error)
            self.assertEqual(audio_store.get(self.user,relay.job)['status'],'COMPLETED')
            self.assertEqual(audio_store.balance(self.user)['seconds'],0)
            row=fixture.audio.f.db.query_one('SELECT status,actual_units,free_actual FROM kilas_credit_admissions WHERE user_id=? AND operation_key=?',(self.user,self.key()))
            self.assertEqual((row['status'],row['actual_units'],row['free_actual']),('CAPTURED',100,100))
            with patch.object(native,'connect') as connect:
                with self.assertRaises(audio_store.AudioError):native.start(self.user,ident,self.key())
                connect.assert_not_called()

    def test_product_free_allowance_cannot_override_missing_supplier_funding(self):
        self.install()
        with self.config(KILAS_LIVE_GEMINI_BUDGET_MICRO_USD='0'),patch.object(native,'connect') as connect:
            with self.assertRaises(audio_store.AudioError):native.start(self.user,'a'*48,self.key())
            connect.assert_not_called()
            row=fixture.audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_admissions WHERE user_id=?',(self.user,))
            self.assertEqual(row['n'],0)

    def test_classic_segmented_pipeline_settles_one_customer_operation(self):
        self.install()
        events=[{'type':'delta','text':json.dumps({'text':'Hello. How are you?','source_language':'id','target_language':'en'})},{'type':'usage','input_tokens':20,'output_tokens':18},{'type':'finish','reason':'stop'}]
        with self.funded(),self.on(),patch.object(fixture.fixture.branded,'resolve',return_value=fixture.fixture.VOICE),patch.object(classic.stt,'transcribe',side_effect=self.transcribe),patch.object(classic.providers,'_openai',return_value=(event for event in events)),patch.object(segments,'speech',return_value=self.audio):
            ident=sessions.create(self.user,'id','en','kilas-male')
            info=sessions.claim(self.user,ident,self.key(),credit_maximum_ms=1000)
            job=classic.process(self.user,ident,self.key(),self.signal(),info,stream_output=True)
            self.assertEqual(audio_store.get(self.user,job)['status'],'COMPLETED')
            self.assertEqual(audio_store.balance(self.user)['seconds'],0)
            row=fixture.audio.f.db.query_one('SELECT actual_units,status FROM kilas_credit_admissions WHERE user_id=? AND operation_key=?',(self.user,self.key()))
            self.assertEqual((row['status'],row['actual_units']),('CAPTURED',1000))
            self.assertEqual(fixture.audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_admissions WHERE user_id=?',(self.user,))['n'],1)

    def test_already_accepted_legacy_turn_keeps_its_existing_path(self):
        self.install()
        with patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'no'}):
            ident=sessions.create(self.user,'id','en','kilas-male')
            sessions.claim(self.user,ident,self.key())
        profile={'credit_legacy_parent':self.key(),'model':'gpt-6-luna','output_tokens':32,'input_token_bound':32}
        _,operations=usage.reserve(self.user,None,self.key()+'-text','FAST','CHAT',profile=profile)
        self.assertEqual(operations,('CHAT',))
        usage.finish(self.user,self.key()+'-text',operations,success=True,model='gpt-6-luna',provider='openai',usage={'input_tokens':1,'output_tokens':1})
        self.assertEqual(fixture.audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_admissions WHERE user_id=?',(self.user,))['n'],0)
        with self.assertRaises(usage.UsageLimit):usage.reserve(self.other,None,'foreign-legacy','FAST','CHAT',profile=profile)

    def test_voice_wallet_cannot_override_supplier_guard(self):
        self.install()
        job,_=audio_store.create(self.user,'credit-voice-funding','voiceover','Synthetic','en','en','voice123','Synthetic','Test',0,None,1,10,credit_context=True)
        with patch.object(audio_service.stt,'require_subscription_credit',side_effect=audio_transcription_budget.BudgetError('provider_credit_exhausted')),patch.object(audio_provider,'speech') as provider:
            audio_service.submit(self.user,job);provider.assert_not_called()
        self.assertEqual(audio_store.get(self.user,job)['status'],'FAILED')
        row=fixture.audio.f.db.query_one('SELECT status FROM kilas_credit_admissions WHERE user_id=? AND operation_key=?',(self.user,'credit-voice-funding'))
        self.assertEqual(row['status'],'RELEASED')

    def test_voice_service_success_settles_actual_duration_once(self):
        self.install()
        job,_=audio_store.create(self.user,'credit-voice-success','voiceover','Synthetic','en','en','voice123','Synthetic','Test',0,None,1,10,credit_context=True)
        with patch.object(audio_service.stt,'require_subscription_credit'),patch.object(audio_provider,'speech',return_value=(self.audio,'synthetic')) as provider:
            audio_service.submit(self.user,job);audio_service.submit(self.user,job)
            provider.assert_called_once()
        row=fixture.audio.f.db.query_one('SELECT status,actual_units FROM kilas_credit_admissions WHERE user_id=? AND operation_key=?',(self.user,'credit-voice-success'))
        self.assertEqual(row['status'],'CAPTURED');self.assertGreater(row['actual_units'],0)
        self.assertEqual(audio_store.balance(self.user)['seconds'],0)


if __name__=='__main__':unittest.main()
