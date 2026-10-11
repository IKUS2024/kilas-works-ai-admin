"""Real local decoding, persistent fences and accounting; synthetic providers only."""
import hashlib
import io
import json
import os
import unittest
from unittest.mock import patch
import test_kilas_audio as audio
import test_kilas_audio_video_script as video
from kilas_ai import live_translator as live, live_translator_store as sessions
from kilas_ai import audio_branded_voices as branded, audio_transcription_budget as budget, audio_store
from kilas_ai import audio_provider, model_policy, providers, usage

VOICE={'alias':'kilas-male','id':'syntheticMale123','name':'Kilas Male','style':'Natural'}


class LiveTranslatorTests(unittest.TestCase):
    setUp=audio.AudioTests.setUp
    funded=video.VideoScriptTests.funded
    credit=audio.AudioTests.credit
    @classmethod
    def setUpClass(cls):cls.audio=audio.mp3()

    def on(self):
        return patch.dict(os.environ,{'KILAS_LIVE_TRANSLATOR_ENABLED':'true','KILAS_LIVE_TRANSLATOR_VERIFIED_MODEL':model_policy.LUNA,'KILAS_LIVE_TRANSLATOR_VERIFIED_STT':budget.MODEL,'KILAS_LIVE_TRANSLATOR_REFERENCE_VERIFIED':'yes','OPENAI_API_KEY':'synthetic-only'})

    def transcribe(self,pcm,capability):
        _,ms=live.stt.normalize(pcm);budget.dispatch(capability,hashlib.sha256(pcm).hexdigest(),ms);budget.finish(capability,True);return 'Halo, apa kabar?'

    def stream(self,*args,**kwargs):
        yield {'type':'delta','text':json.dumps({'text':'Hello, how are you?','source_language':'id','target_language':'en'})}
        yield {'type':'usage','input_tokens':20,'output_tokens':18}
        yield {'type':'finish','reason':'stop'}

    def key(self,n=1):return 'live-'+str(self.user*10+n).zfill(32)
    def signal(self):
        import wave,struct,math
        data=io.BytesIO()
        with wave.open(data,'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b''.join(struct.pack('<h',int(2000*math.sin(i*2*math.pi*440/16000))) for i in range(16000)))
        return data.getvalue()
    def session(self):return sessions.create(self.user,'id','en','kilas-male')
    def claim(self,ident,key=None):return sessions.claim(self.user,ident,key or self.key())

    def test_default_off_missing_verification_or_reference_denies_before_mic_pipeline(self):
        with patch.object(live.stt,'transcribe') as stt,patch.object(providers,'_openai') as ai,patch.object(audio_provider,'speech') as tts:
            self.assertFalse(live.ready())
            r=self.client.post('/kilas-translator/live/sessions',data={'csrf_token':'audio-csrf','consent':'yes','language_a':'id','language_b':'en','voice':'kilas-male'})
            self.assertEqual(r.status_code,503);stt.assert_not_called();ai.assert_not_called();tts.assert_not_called()
            with self.funded(),self.on():
                self.assertTrue(live.ready())
                for name in ('KILAS_LIVE_TRANSLATOR_VERIFIED_MODEL','KILAS_LIVE_TRANSLATOR_VERIFIED_STT','KILAS_LIVE_TRANSLATOR_REFERENCE_VERIFIED'):
                    with patch.dict(os.environ,{name:''}):self.assertFalse(live.ready())
                with patch.dict(os.environ,{'KILAS_VOICE_VIDEO_SCRIPT_ENABLED':'false'}):self.assertFalse(live.ready())

    def test_pair_consent_voice_owner_and_concurrent_session_checks(self):
        self.credit(300)
        fields={'csrf_token':'audio-csrf','language_a':'id','language_b':'en','voice':'kilas-male','consent':'yes'}
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE):
            self.assertEqual(self.client.post('/kilas-translator/live/sessions',data={**fields,'consent':'no'}).status_code,400)
            self.assertEqual(self.client.post('/kilas-translator/live/sessions',data={**fields,'language_b':'id'}).status_code,400)
            response=self.client.post('/kilas-translator/live/sessions',data=fields);self.assertEqual(response.status_code,201)
            ident=response.json['session_id'];self.assertNotIn(VOICE['id'],response.text)
            self.assertEqual(self.client.post('/kilas-translator/live/sessions',data=fields).status_code,409)
            with self.client.session_transaction() as state:state['user_id']=self.other
            self.assertEqual(self.client.post('/kilas-translator/live/sessions/'+ident+'/end',data={'csrf_token':'audio-csrf'}).status_code,404)
            with self.client.session_transaction() as state:state['user_id']=self.user
            self.assertEqual(self.client.post('/kilas-translator/live/sessions/'+ident+'/end',data={'csrf_token':'audio-csrf'}).status_code,200)
            with patch.dict(os.environ,{'KILAS_LIVE_TRANSLATOR_ENABLED':'false'}):self.assertEqual(self.client.post('/kilas-translator/live/sessions/'+ident+'/end',data={'csrf_token':'audio-csrf'}).status_code,200)

    def test_bidirectional_existing_accounting_no_clone_no_ids_or_transcript_response(self):
        self.credit(300)
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(live.stt,'transcribe',side_effect=self.transcribe) as stt,patch.object(providers,'_openai',side_effect=self.stream) as ai,patch.object(audio_provider,'speech',return_value=(self.audio,'synthetic-request')) as tts,patch.object(audio_provider,'clone_voice') as clone:
            ident=self.session();key=self.key();info=self.claim(ident,key);job=live.process(self.user,ident,key,self.signal(),info)
            self.assertEqual(sessions.result(self.user,ident,key)['status'],'COMPLETED');self.assertEqual(audio_store.get(self.user,job)['seconds_charged'],2)
            self.assertEqual(tts.call_args.args[1],VOICE['id']);self.assertEqual(tts.call_args.args[2],'en');self.assertEqual(ai.call_args.args[0],model_policy.LUNA)
            def reverse(*args,**kwargs):
                yield {'type':'delta','text':json.dumps({'text':'Selamat pagi.','source_language':'en','target_language':'id'})}
                yield {'type':'finish','reason':'stop'}
            ai.side_effect=reverse;key2=self.key(2);info=self.claim(ident,key2);live.process(self.user,ident,key2,self.signal(),info)
            self.assertEqual(tts.call_args.args[2],'id');self.assertEqual(stt.call_count,2);clone.assert_not_called()
            response=self.client.get('/kilas-translator/live/sessions/'+ident+'/turns/'+key2)
            self.assertEqual(set(response.json),{'status','audio_url'});self.assertNotIn(VOICE['id'],response.text)
            self.assertEqual(self.client.get(response.json['audio_url']).status_code,200)
            with self.assertRaises(audio_store.AudioError):self.claim(ident,key)
            self.assertEqual(stt.call_count,2)
            rows=audio.f.db.query_all('SELECT input_tokens,status FROM kilas_ai_usage WHERE user_id=?',(self.user,));self.assertEqual(len(rows),2)
            self.assertNotIn('Halo',str(audio.f.db.query_all('SELECT * FROM kilas_live_translator_turns')))

    def test_silent_audio_never_dispatches_provider(self):
        self.credit(300)
        import wave
        data=io.BytesIO()
        with wave.open(data,'wb') as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\0'*(32000))
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(live.stt,'transcribe') as stt,patch.object(providers,'_openai') as ai,patch.object(audio_provider,'speech') as tts:
            ident=self.session();info=self.claim(ident)
            with self.assertRaises(audio_store.AudioError) as error:live.process(self.user,ident,self.key(),data.getvalue(),info)
            self.assertEqual(error.exception.code,'no_speech');stt.assert_not_called();ai.assert_not_called();tts.assert_not_called()
            self.assertEqual(sessions.result(self.user,ident,self.key())['error_code'],'no_speech')

    def test_end_during_stt_fences_translation_and_audio(self):
        self.credit(300)
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(providers,'_openai') as ai,patch.object(audio_provider,'speech') as tts:
            ident=self.session();info=self.claim(ident)
            def stop(pcm,cap):
                text=self.transcribe(pcm,cap);sessions.end(self.user,ident);return text
            with patch.object(live.stt,'transcribe',side_effect=stop):
                with self.assertRaises(audio_store.AudioError):live.process(self.user,ident,self.key(),self.signal(),info)
            ai.assert_not_called();tts.assert_not_called();self.assertEqual(sessions.result(self.user,ident,self.key())['status'],'CANCELLED')
            with self.assertRaises(audio_store.AudioError):self.claim(ident,self.key(2))
            self.assertEqual(audio_store.balance(self.user)['available'],300)

    def test_end_during_translation_fences_tts_and_retains_usage(self):
        self.credit(300)
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(live.stt,'transcribe',side_effect=self.transcribe),patch.object(audio_provider,'speech') as tts:
            ident=self.session();info=self.claim(ident)
            def stop(*args,**kwargs):
                sessions.end(self.user,ident);yield {'type':'delta','text':'{}'}
            with patch.object(providers,'_openai',side_effect=stop):
                with self.assertRaises(audio_store.AudioError):live.process(self.user,ident,self.key(),self.signal(),info)
            tts.assert_not_called();self.assertEqual(sessions.result(self.user,ident,self.key())['status'],'CANCELLED')
            self.assertEqual(audio.f.db.query_one('SELECT status FROM kilas_ai_usage WHERE user_id=?',(self.user,))['status'],'FAILED')

    def test_end_during_dispatched_tts_blocks_playback_without_rewriting_accounting(self):
        self.credit(300)
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(live.stt,'transcribe',side_effect=self.transcribe),patch.object(providers,'_openai',side_effect=self.stream):
            ident=self.session();info=self.claim(ident)
            def stop(*args,**kwargs):sessions.end(self.user,ident);return self.audio,'synthetic-request'
            with patch.object(audio_provider,'speech',side_effect=stop) as tts:
                with self.assertRaises(audio_store.AudioError):live.process(self.user,ident,self.key(),self.signal(),info)
            self.assertEqual(tts.call_count,1);self.assertEqual(audio_store.balance(self.user)['available'],298)
            self.assertEqual(sessions.result(self.user,ident,self.key())['status'],'CANCELLED')
            self.assertEqual(self.client.get('/kilas-translator/live/sessions/'+ident+'/turns/'+self.key()+'/audio').status_code,404)

    def test_provider_failure_and_out_of_pair_never_tts_or_repeat(self):
        self.credit(300)
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(live.stt,'transcribe',side_effect=self.transcribe),patch.object(audio_provider,'speech') as tts:
            ident=self.session();info=self.claim(ident)
            with patch.object(providers,'_openai',side_effect=providers.ProviderError('synthetic-network')):
                with self.assertRaises(audio_store.AudioError):live.process(self.user,ident,self.key(),self.signal(),info)
            tts.assert_not_called();self.assertEqual(sessions.result(self.user,ident,self.key())['status'],'FAILED')
            with self.assertRaises(audio_store.AudioError):self.claim(ident,self.key())
            info=self.claim(ident,self.key(2))
            def wrong(*args,**kwargs):
                yield {'type':'delta','text':json.dumps({'text':'Bonjour','source_language':'fr','target_language':'en'})}
                yield {'type':'finish','reason':'stop'}
            with patch.object(providers,'_openai',side_effect=wrong):
                with self.assertRaises(audio_store.AudioError):live.process(self.user,ident,self.key(2),self.signal(),info)
            tts.assert_not_called()

    def test_http_enqueue_poll_duplicate_and_csrf_with_real_local_audio_decode(self):
        self.credit(300)
        class Inline:
            def submit(self,callback):callback()
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(live.stt,'transcribe',side_effect=self.transcribe) as stt,patch.object(providers,'_openai',side_effect=self.stream),patch.object(audio_provider,'speech',return_value=(self.audio,'synthetic-request')),patch.object(live,'_EXECUTOR',Inline()):
            ident=self.session();key=self.key();url='/kilas-translator/live/sessions/'+ident+'/turns/'+key
            def body():return {'csrf_token':'audio-csrf','recording':(io.BytesIO(self.signal()),'recording.wav','audio/wav')}
            self.assertEqual(self.client.post(url,data={'recording':(io.BytesIO(self.signal()),'recording.wav','audio/wav')}).status_code,400)
            response=self.client.post(url,data=body());self.assertEqual(response.status_code,202,response.text)
            result=self.client.get(url);self.assertEqual(result.json['status'],'COMPLETED',result.text)
            self.assertEqual(self.client.post(url,data=body()).status_code,409);self.assertEqual(stt.call_count,1)
            self.assertEqual(self.client.get(result.json['audio_url']).mimetype,'audio/mpeg')

    def test_expired_session_and_foreign_turn_are_rejected(self):
        ident=self.session();self.claim(ident)
        with self.assertRaises(audio_store.AudioError):sessions.result(self.other,ident,self.key())
        audio.f.db.execute('UPDATE kilas_live_translator_sessions SET expires_at=? WHERE id=?',('2000-01-01T00:00:00+00:00',ident))
        with self.assertRaises(audio_store.AudioError):self.claim(ident,self.key(2))
        self.assertEqual(sessions.result(self.user,ident,self.key())['status'],'CANCELLED')


if __name__=='__main__':unittest.main()
