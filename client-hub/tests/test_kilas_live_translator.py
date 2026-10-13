"""Real local decoding, persistent fences and accounting; synthetic providers only."""
import hashlib
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch, MagicMock
import test_kilas_audio as audio
import test_kilas_audio_video_script as video
from kilas_ai import live_translator as live, live_translator_store as sessions
from kilas_ai import audio_branded_voices as branded, audio_transcription_budget as budget, audio_store
from kilas_ai import audio_provider, model_policy, providers, usage
from kilas_ai import live_translator_segments as segments

VOICE={'alias':'kilas-male','id':'syntheticMale123','name':'Kilas Male','style':'Natural'}


class LiveTranslatorTests(unittest.TestCase):
    def setUp(self):
        audio.AudioTests.setUp(self)
        self.subscription_credit_check=live.stt.require_subscription_credit
        funding=patch.object(live.stt,'require_subscription_credit')
        funding.start();self.addCleanup(funding.stop)
    funded=video.VideoScriptTests.funded
    credit=audio.AudioTests.credit
    @classmethod
    def setUpClass(cls):cls.audio=audio.mp3()

    def on(self):
        return patch.dict(os.environ,{'KILAS_LIVE_TRANSLATOR_ENABLED':'true','KILAS_LIVE_TRANSLATOR_VERIFIED_MODEL':model_policy.LUNA,'KILAS_LIVE_TRANSLATOR_VERIFIED_STT':budget.MODEL,'KILAS_LIVE_TRANSLATOR_REFERENCE_VERIFIED':'yes','KILAS_LIVE_TRANSLATOR_VERIFIED_PROJECT':'proj_synthetic','KILAS_LIVE_TRANSLATOR_ALLOWED_OWNER_ID':str(self.user),'KILAS_LIVE_TRANSLATOR_AUDIO_SECONDS':'120','KILAS_LIVE_TRANSLATOR_USAGE_MODE':'qa','OPENAI_API_KEY':'synthetic-only'})

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
                self.assertTrue(live.ready(self.user));self.assertFalse(live.ready());self.assertFalse(live.ready(self.other))
                for name in ('KILAS_LIVE_TRANSLATOR_VERIFIED_MODEL','KILAS_LIVE_TRANSLATOR_VERIFIED_STT','KILAS_LIVE_TRANSLATOR_REFERENCE_VERIFIED','KILAS_LIVE_TRANSLATOR_VERIFIED_PROJECT','KILAS_LIVE_TRANSLATOR_ALLOWED_OWNER_ID','KILAS_LIVE_TRANSLATOR_AUDIO_SECONDS'):
                    with patch.dict(os.environ,{name:''}):self.assertFalse(live.ready(self.user))
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

    def test_owner_session_discovery_is_read_only_private_and_can_recover_when_flag_off(self):
        ident=self.session();before=dict(audio.f.db.query_one('SELECT status,expires_at FROM kilas_live_translator_sessions WHERE id=?',(ident,)))
        with patch.dict(os.environ,{'KILAS_LIVE_TRANSLATOR_ENABLED':'false'}),patch.object(live.stt,'transcribe') as stt,patch.object(audio_provider,'speech') as tts:
            response=self.client.get('/kilas-translator/live/sessions/active')
            self.assertEqual(response.status_code,200);self.assertEqual(response.headers['Cache-Control'],'private, no-store')
            self.assertEqual(response.json['session']['session_id'],ident)
            self.assertFalse(response.json['session']['processing'])
            self.assertIsNone(response.json['session']['expires_in_seconds']);self.assertIsNone(response.json['session']['expires_at'])
            self.assertEqual(set(response.json['session']),{'session_id','expires_at','expires_in_seconds','processing'})
            with self.client.session_transaction() as state:state['user_id']=self.other
            self.assertEqual(self.client.get('/kilas-translator/live/sessions/active').json,{'session':None})
            self.assertEqual(self.client.post('/kilas-translator/live/sessions/'+ident+'/end',data={'csrf_token':'audio-csrf'}).status_code,404)
            stt.assert_not_called();tts.assert_not_called()
        self.assertEqual(dict(audio.f.db.query_one('SELECT status,expires_at FROM kilas_live_translator_sessions WHERE id=?',(ident,))),before)

    def test_new_session_has_no_age_limit_and_still_requires_explicit_owner_end(self):
        from datetime import timedelta
        ident=self.session();now=usage._now()
        self.assertEqual(audio.f.db.query_one('SELECT expires_at FROM kilas_live_translator_sessions WHERE id=?',(ident,))['expires_at'],'')
        with patch.object(usage,'_now',return_value=now+timedelta(days=365)):
            self.assertEqual(sessions.active(self.user)['session_id'],ident)
            self.assertIsNone(sessions.active(self.user)['expires_in_seconds'])
            self.claim(ident);self.assertEqual(sessions.check(self.user,ident,self.key())['language_a'],'id')
            self.assertEqual(sessions.status(self.user,ident),{'status':'ACTIVE','processing':True})
            with self.assertRaises(audio_store.AudioError) as duplicate:self.session()
            self.assertEqual(duplicate.exception.code,'session_busy')
        sessions.end(self.user,ident);self.assertEqual(sessions.status(self.user,ident)['status'],'ENDED')

    def test_turn_cancel_is_owner_csrf_scoped_idempotent_and_blocks_late_admission(self):
        ident=self.session();key=self.key();url='/kilas-translator/live/sessions/'+ident+'/turns/'+key+'/cancel'
        with patch.object(live.stt,'transcribe') as stt,patch.object(audio_provider,'speech') as tts:
            self.assertEqual(self.client.post(url).status_code,400)
            with self.client.session_transaction() as state:state['user_id']=self.other
            self.assertEqual(self.client.post(url,data={'csrf_token':'audio-csrf'}).status_code,404)
            with self.client.session_transaction() as state:state['user_id']=self.user
            for _ in range(2):
                response=self.client.post(url,data={'csrf_token':'audio-csrf'});self.assertEqual(response.status_code,200)
                self.assertEqual(response.json,{'status':'CANCELLED'});self.assertEqual(response.headers['Cache-Control'],'private, no-store')
            with self.assertRaises(audio_store.AudioError) as late:self.claim(ident,key)
            self.assertEqual(late.exception.code,'duplicate_turn')
            self.assertEqual(sessions.status(self.user,ident),{'status':'ACTIVE','processing':False})
            self.claim(ident,self.key(2));stt.assert_not_called();tts.assert_not_called()

    def test_turn_cancel_during_dispatched_stt_keeps_accounting_and_blocks_later_paid_stages(self):
        self.credit(300);ident=self.session();info=self.claim(ident)
        def cancel_after_stt(pcm,capability):
            text=self.transcribe(pcm,capability);sessions.cancel_turn(self.user,ident,self.key());return text
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(live.stt,'transcribe',side_effect=cancel_after_stt),patch.object(providers,'_openai') as ai,patch.object(audio_provider,'speech') as tts:
            with self.assertRaises(audio_store.AudioError) as stopped:live.process(self.user,ident,self.key(),self.signal(),info)
            self.assertEqual(stopped.exception.code,'turn_cancelled');ai.assert_not_called();tts.assert_not_called()
        self.assertEqual(sessions.result(self.user,ident,self.key())['status'],'CANCELLED')
        self.assertEqual(budget.owned(self.user,self.key())['status'],'COMPLETED')
        self.assertEqual(sessions.status(self.user,ident)['status'],'ACTIVE')
        self.assertEqual(audio_store.balance(self.user)['available'],300)

    def test_completed_turn_cancel_preserves_output_and_lightweight_private_reads(self):
        self.credit(300);ident=self.session();info=self.claim(ident)
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(live.stt,'transcribe',side_effect=self.transcribe),patch.object(providers,'_openai',side_effect=self.stream),patch.object(audio_provider,'speech',return_value=(self.audio,'synthetic-request')):
            job=live.process(self.user,ident,self.key(),self.signal(),info)
        before=audio_store.get(self.user,job);self.assertEqual(sessions.cancel_turn(self.user,ident,self.key()),'COMPLETED')
        self.assertEqual(audio_store.get(self.user,job),before)
        prefix='/kilas-translator/live/sessions/'+ident+'/turns/'+self.key()
        statements=[]
        original=audio.f.db.query_one
        def query(sql,*args,**kwargs):statements.append(sql);return original(sql,*args,**kwargs)
        with patch.object(audio.f.db,'query_one',side_effect=query):
            response=self.client.get(prefix);self.assertEqual(response.status_code,200);self.assertEqual(response.json['translated_text'],'Hello, how are you?')
            download=self.client.get(response.json['audio_url']);self.assertEqual(download.status_code,200)
        self.assertEqual(download.data,self.audio);self.assertEqual(download.headers['Cache-Control'],'private, no-store')
        live_reads=[s for s in statements if 'kilas_live_translator' in s or s.startswith('SELECT source_language,target_language,original_script')]
        self.assertEqual(len(live_reads),3,'Completed metadata + audio use three bounded reads, formerly six.')
        self.assertNotIn('result_content',live_reads[1])
        audio.f.db.execute('UPDATE kilas_audio_jobs SET user_id=? WHERE id=?',(self.other,job))
        self.assertEqual(self.client.get(prefix).status_code,404);self.assertEqual(self.client.get(prefix+'/audio').status_code,404)

    def test_session_status_never_exposes_another_owner_or_dispatches_providers(self):
        ident=self.session();url='/kilas-translator/live/sessions/'+ident
        with patch.object(live.stt,'transcribe') as stt,patch.object(audio_provider,'speech') as tts:
            response=self.client.get(url);self.assertEqual(response.json,{'status':'ACTIVE','processing':False});self.assertEqual(response.headers['Cache-Control'],'private, no-store')
            with self.client.session_transaction() as state:state['user_id']=self.other
            self.assertEqual(self.client.get(url).status_code,404);stt.assert_not_called();tts.assert_not_called()

    def test_explicit_recovery_end_is_csrf_protected_idempotent_cancels_turn_without_new_dispatch(self):
        ident=self.session();key=self.key();self.claim(ident,key)
        self.assertTrue(self.client.get('/kilas-translator/live/sessions/active').json['session']['processing'])
        with patch.object(live.stt,'transcribe') as stt,patch.object(audio_provider,'speech') as tts:
            self.assertEqual(self.client.post('/kilas-translator/live/sessions/'+ident+'/end').status_code,400)
            self.assertEqual(sessions.result(self.user,ident,key)['status'],'PROCESSING')
            for _ in range(2):self.assertEqual(self.client.post('/kilas-translator/live/sessions/'+ident+'/end',data={'csrf_token':'audio-csrf'}).status_code,200)
            self.assertEqual(self.client.get('/kilas-translator/live/sessions/active').json,{'session':None})
            self.assertEqual(sessions.result(self.user,ident,key),{'status':'CANCELLED'})
            stt.assert_not_called();tts.assert_not_called()
        self.assertEqual(audio.f.db.query_one('SELECT status FROM kilas_live_translator_sessions WHERE id=?',(ident,))['status'],'ENDED')
        newer=self.session();self.assertNotEqual(newer,ident)
        sessions.end(self.user,ident)
        self.assertEqual(self.client.get('/kilas-translator/live/sessions/active').json['session']['session_id'],newer)

    def test_expired_session_discovery_allows_fresh_admission_without_deleting_history(self):
        ident=self.session()
        audio.f.db.execute('UPDATE kilas_live_translator_sessions SET expires_at=? WHERE id=?',('2000-01-01T00:00:00+00:00',ident))
        self.assertIsNone(sessions.active(self.user))
        newer=self.session();self.assertNotEqual(newer,ident)
        self.assertEqual(audio.f.db.query_one('SELECT status FROM kilas_live_translator_sessions WHERE id=?',(ident,))['status'],'ACTIVE')

    def test_invalid_language_pair_rejected_before_balance_voice_and_session_writes(self):
        fields={'csrf_token':'audio-csrf','language_a':'id','language_b':'en','voice':'kilas-male','consent':'yes'}
        with self.funded(),self.on(),patch.object(branded,'resolve') as voice,patch.object(audio_store,'require_balance') as balance,patch.object(sessions,'create') as create:
            for a,b in (('id','id'),('en','en'),('id','unknown'),('unknown','en'),('', 'en'),('id',None)):
                with self.subTest(a=a,b=b):
                    response=self.client.post('/kilas-translator/live/sessions',data={**fields,'language_a':a,'language_b':b})
                    self.assertEqual(response.status_code,400)
                    self.assertIn('dua bahasa yang berbeda',response.json['error'])
            voice.assert_not_called();balance.assert_not_called();create.assert_not_called()

    def test_direct_session_creation_rejects_invalid_saved_pairs_without_writes(self):
        for a,b in (('id','id'),('id','missing'),(None,'en'),([], 'en')):
            with self.subTest(a=a,b=b),patch.object(sessions,'transaction') as transaction:
                with self.assertRaises(audio_store.AudioError) as error:sessions.create(self.user,a,b,'kilas-male')
                self.assertEqual(error.exception.code,'invalid_language_pair')
                transaction.assert_not_called()

    def test_legacy_duplicate_or_removed_pair_blocks_turns_readback_and_providers_but_can_end(self):
        for index,(a,b) in enumerate((('id','id'),('missing','en')),start=1):
            with self.subTest(a=a,b=b):
                ident=self.session();key=self.key(index*3);self.claim(ident,key)
                audio.f.db.execute('UPDATE kilas_live_translator_sessions SET language_a=?,language_b=? WHERE id=?',(a,b,ident))
                with self.funded(),self.on(),patch.object(live.stt,'transcribe') as stt,patch.object(providers,'_openai') as ai,patch.object(audio_provider,'speech') as tts,patch.object(live.audio_media,'voice_sample') as decode:
                    for call in (lambda:self.claim(ident,self.key(2)),lambda:sessions.check(self.user,ident,key),lambda:sessions.result(self.user,ident,key),lambda:live.enqueue(self.user,ident,self.key(2),None)):
                        with self.assertRaises(audio_store.AudioError) as error:call()
                        self.assertEqual(error.exception.code,'invalid_language_pair')
                    for suffix in ('','/audio'):
                        response=self.client.get('/kilas-translator/live/sessions/'+ident+'/turns/'+key+suffix)
                        self.assertEqual(response.status_code,400)
                    stt.assert_not_called();ai.assert_not_called();tts.assert_not_called();decode.assert_not_called()
                sessions.end(self.user,ident)
                self.assertEqual(sessions.result(self.user,ident,key),{'status':'CANCELLED'})

    def test_translator_markup_excludes_default_duplicates_and_keeps_privacy_and_feature_tabs(self):
        from html.parser import HTMLParser
        class SelectParser(HTMLParser):
            def __init__(self):super().__init__();self.current=None;self.fields={}
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag=='select':self.current=attrs['name'];self.fields[self.current]={'attrs':attrs,'options':{}}
                if tag=='option' and self.current:self.fields[self.current]['options'][attrs['value']]=attrs
            def handle_endtag(self,tag):
                if tag=='select':self.current=None
        with self.funded(),self.on(),patch.object(branded,'public_choices',return_value=[VOICE]):
            html=self.client.get('/kilas-translator/live').text
        parser=SelectParser();parser.feed(html)
        for name,chosen,excluded in (('language_a','id','en'),('language_b','en','id')):
            field=parser.fields[name]
            self.assertIn('required',field['attrs']);self.assertNotIn('aria-describedby',field['attrs'])
            self.assertIn('selected',field['options'][chosen]);self.assertIn('disabled',field['options'][excluded])
            self.assertNotIn('disabled',field['options'][chosen])
        self.assertIn('class="kilas-live-page"',html)
        self.assertNotIn('live-pair-help',html);self.assertNotIn('Privasi &amp; pemrosesan audio',html)
        self.assertNotIn('ElevenLabs',html);self.assertNotIn('OpenAI',html)
        self.assertIn('href="/privacy#audio-processing"',html)
        self.assertLess(html.index('kilas_live_translator.css'),html.index('</head>'))
        self.assertIn('id="live-recovery" hidden',html)
        self.assertIn('id="live-session-status" class="live-session-status" role="status" aria-live="polite"',html)
        self.assertIn('name="consent" value="yes" required',html)
        for label in ('AI Chat','Translator','Voice Over','Finance'):self.assertIn(label,html)

    def test_owner_restricted_preview_propagates_owner_without_opening_other_accounts(self):
        self.credit(300)
        fields={'csrf_token':'audio-csrf','language_a':'id','language_b':'en','voice':'kilas-male','consent':'yes'}
        with self.funded(),self.on(),patch.dict(os.environ,{'KILAS_VO_STT_ALLOWED_OWNER_ID':str(self.user)}),patch.object(branded,'resolve',return_value=VOICE),patch.object(live.audio_media,'voice_sample') as decode:
            self.assertTrue(live.ready(self.user));self.assertFalse(live.ready());self.assertFalse(live.ready(self.other))
            page=self.client.get('/kilas-translator/live')
            self.assertIn('data-ready="true"',page.text)
            self.assertNotIn('kilas-translator-pending',page.text)
            response=self.client.post('/kilas-translator/live/sessions',data=fields)
            self.assertEqual(response.status_code,201,response.text)
            with self.client.session_transaction() as state:state['user_id']=self.other
            self.assertIn('data-ready="false"',self.client.get('/kilas-translator/live').text)
            self.assertEqual(self.client.post('/kilas-translator/live/sessions',data=fields).status_code,503)
            with self.assertRaises(audio_store.AudioError) as error:live.enqueue(self.other,response.json['session_id'],self.key(),None)
            self.assertEqual(error.exception.code,'translator_unavailable');decode.assert_not_called()

    def test_bidirectional_existing_accounting_no_clone_no_ids_or_transcript_response(self):
        self.credit(300)
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(live.stt,'transcribe',side_effect=self.transcribe) as stt,patch.object(providers,'_openai',side_effect=self.stream) as ai,patch.object(audio_provider,'speech',return_value=(self.audio,'synthetic-request')) as tts,patch.object(audio_provider,'clone_voice') as clone:
            ident=self.session();key=self.key();info=self.claim(ident,key);job=live.process(self.user,ident,key,self.signal(),info)
            self.assertEqual(sessions.result(self.user,ident,key)['status'],'COMPLETED');self.assertEqual(audio_store.get(self.user,job)['seconds_charged'],2)
            self.assertEqual(tts.call_args.args[1],VOICE['id']);self.assertEqual(tts.call_args.args[2],'en');self.assertEqual(ai.call_args.args[0],model_policy.LUNA)
            self.assertEqual(ai.call_args.kwargs['project'],'proj_synthetic')
            def reverse(*args,**kwargs):
                yield {'type':'delta','text':json.dumps({'text':'Selamat pagi.','source_language':'en','target_language':'id'})}
                yield {'type':'finish','reason':'stop'}
            ai.side_effect=reverse;key2=self.key(2);info=self.claim(ident,key2);live.process(self.user,ident,key2,self.signal(),info)
            self.assertEqual(tts.call_args.args[2],'id');self.assertEqual(stt.call_count,2);clone.assert_not_called()
            response=self.client.get('/kilas-translator/live/sessions/'+ident+'/turns/'+key2)
            self.assertEqual(set(response.json),{'status','audio_url','translated_text','source_language','target_language'});self.assertNotIn(VOICE['id'],response.text)
            self.assertEqual(response.json['translated_text'],'Selamat pagi.')
            self.assertEqual(response.json['source_language'],'en');self.assertEqual(response.json['target_language'],'id')
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
        with self.funded(),self.on(),patch.dict(os.environ,{'KILAS_VO_STT_ALLOWED_OWNER_ID':str(self.user)}),patch.object(branded,'resolve',return_value=VOICE),patch.object(live.stt,'transcribe',side_effect=self.transcribe) as stt,patch.object(providers,'_openai',side_effect=self.stream),patch.object(segments,'speech',return_value=self.audio) as tts,patch.object(live,'_EXECUTOR',Inline()):
            ident=self.session();key=self.key();url='/kilas-translator/live/sessions/'+ident+'/turns/'+key
            def body():return {'csrf_token':'audio-csrf','recording':(io.BytesIO(self.signal()),'recording.wav','audio/wav')}
            self.assertEqual(self.client.post(url,data={'recording':(io.BytesIO(self.signal()),'recording.wav','audio/wav')}).status_code,400)
            response=self.client.post(url,data=body());self.assertEqual(response.status_code,202,response.text)
            result=self.client.get(url);self.assertEqual(result.json['status'],'COMPLETED',result.text)
            self.assertEqual(self.client.post(url,data=body()).status_code,409);self.assertEqual(stt.call_count,1)
            tts.assert_called_once();self.assertEqual(tts.call_args.args[0],'Hello, how are you?')
            self.assertEqual(self.client.get(result.json['audio_url']).mimetype,'audio/mpeg')

    def test_expired_session_and_foreign_turn_are_rejected(self):
        ident=self.session();self.claim(ident)
        with self.assertRaises(audio_store.AudioError):sessions.result(self.other,ident,self.key())
        audio.f.db.execute('UPDATE kilas_live_translator_sessions SET expires_at=? WHERE id=?',('2000-01-01T00:00:00+00:00',ident))
        with self.assertRaises(audio_store.AudioError):self.claim(ident,self.key(2))
        self.assertEqual(sessions.result(self.user,ident,self.key())['status'],'CANCELLED')

    def test_read_fence_reuses_connection_and_keeps_owner_turn_expiry_and_end_checks(self):
        ident=self.session();info=self.claim(ident)
        with patch.object(usage,'_connect',side_effect=AssertionError('Read fence opened a write connection')),patch.object(audio.f.db,'query_one',wraps=audio.f.db.query_one) as query:
            for _ in range(20):self.assertEqual(sessions.check(self.user,ident,self.key()),info)
            self.assertEqual(query.call_count,20)
            for owner,session_id,key,code in ((self.other,ident,self.key(),'session_unavailable'),(self.user,'missing',self.key(),'session_unavailable'),(self.user,ident,self.key(2),'turn_cancelled')):
                with self.assertRaises(audio_store.AudioError) as error:sessions.check(owner,session_id,key)
                self.assertEqual(error.exception.code,code)
        for status in ('FAILED','COMPLETED','CANCELLED'):
            audio.f.db.execute('UPDATE kilas_live_translator_turns SET status=? WHERE operation_key=?',(status,self.key()))
            with self.assertRaises(audio_store.AudioError) as error:sessions.check(self.user,ident,self.key())
            self.assertEqual(error.exception.code,'turn_cancelled')
        audio.f.db.execute("UPDATE kilas_live_translator_turns SET status='PROCESSING' WHERE operation_key=?",(self.key(),))
        # End commits in another worker; the existing read connection sees it immediately.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as worker:worker.submit(sessions.end,self.user,ident).result(timeout=5)
        with self.assertRaises(audio_store.AudioError) as error:sessions.check(self.user,ident,self.key())
        self.assertEqual(error.exception.code,'session_ended')

    def test_active_expired_read_fence_and_single_query_processing_timeout(self):
        ident=self.session();self.claim(ident)
        with patch.object(audio.f.db,'query_one',wraps=audio.f.db.query_one) as query:
            self.assertEqual(sessions.result(self.user,ident,self.key())['status'],'PROCESSING')
            self.assertEqual(query.call_count,1)
        audio.f.db.execute('UPDATE kilas_live_translator_turns SET created_at=? WHERE operation_key=?',('2000-01-01T00:00:00+00:00',self.key()))
        with patch.object(audio.f.db,'query_one',wraps=audio.f.db.query_one) as query:
            self.assertEqual(sessions.result(self.user,ident,self.key()),{'status':'FAILED','error_code':'processing_interrupted'})
            self.assertEqual(query.call_count,1)
        audio.f.db.execute('UPDATE kilas_live_translator_sessions SET expires_at=? WHERE id=?',('2000-01-01T00:00:00+00:00',ident))
        with self.assertRaises(audio_store.AudioError) as error:sessions.check(self.user,ident,self.key())
        self.assertEqual(error.exception.code,'session_ended')

    def pg_read_fixture(self,status='ACTIVE'):
        # Real DB helper/placeholder mapping, fake driver transport: no PG socket.
        from datetime import timedelta
        row=(status,(usage._now()+timedelta(minutes=10)).isoformat(),'id','en','kilas-male','PROCESSING')
        connection=MagicMock();connection.closed=0
        cursor=connection.cursor.return_value
        cursor.description=[(name,) for name in ('session_status','expires_at','language_a','language_b','voice_alias','turn_status')]
        cursor.fetchone.return_value=row
        return connection

    def test_closed_postgres_cached_read_connection_is_replaced_and_committed(self):
        import psycopg2
        from threading import local
        from types import SimpleNamespace
        old=self.pg_read_fixture();old.closed=1;fresh=self.pg_read_fixture();cache=local();cache.conn=old
        driver=SimpleNamespace(connect=MagicMock(return_value=fresh),OperationalError=psycopg2.OperationalError,InterfaceError=psycopg2.InterfaceError)
        with patch.object(audio.f.db,'BACKEND','postgres'),patch.object(audio.f.db,'_local',cache),patch.object(audio.f.db,'psycopg2',driver,create=True):
            for _ in range(3):self.assertEqual(sessions.check(self.user,'synthetic',self.key())['voice_alias'],'kilas-male')
            self.assertIs(cache.conn,fresh)
        old.close.assert_called_once();driver.connect.assert_called_once()
        self.assertEqual(fresh.commit.call_count,3);self.assertEqual(fresh.cursor.return_value.close.call_count,3)
        self.assertIn('t.operation_key=%s',fresh.cursor.return_value.execute.call_args.args[0])
        self.assertEqual(fresh.cursor.return_value.execute.call_args.args[1],(self.key(),'synthetic',self.user))

    def test_half_open_postgres_read_retries_once_and_sees_committed_end(self):
        import psycopg2
        from threading import local
        from types import SimpleNamespace
        broken=self.pg_read_fixture();broken.cursor.return_value.execute.side_effect=psycopg2.OperationalError('synthetic disconnected read')
        ended=self.pg_read_fixture('ENDED');cache=local();cache.conn=broken
        driver=SimpleNamespace(connect=MagicMock(return_value=ended),OperationalError=psycopg2.OperationalError,InterfaceError=psycopg2.InterfaceError)
        with patch.object(audio.f.db,'BACKEND','postgres'),patch.object(audio.f.db,'_local',cache),patch.object(audio.f.db,'psycopg2',driver,create=True):
            with self.assertRaises(audio_store.AudioError) as error:sessions.check(self.user,'synthetic',self.key())
            self.assertEqual(error.exception.code,'session_ended')
        broken.rollback.assert_called_once();broken.close.assert_called_once();ended.commit.assert_called_once();driver.connect.assert_called_once()
        self.assertEqual(broken.cursor.return_value.execute.call_count,1);self.assertEqual(ended.cursor.return_value.execute.call_count,1)

    def test_postgres_read_failure_is_bounded_and_never_retries_non_connection_error(self):
        import psycopg2
        from threading import local
        from types import SimpleNamespace
        for error,expected_reconnects in ((psycopg2.OperationalError('synthetic read failed'),1),(ValueError('synthetic non-connection error'),0)):
            with self.subTest(error=type(error).__name__):
                first=self.pg_read_fixture();second=self.pg_read_fixture();cache=local();cache.conn=first
                first.cursor.return_value.execute.side_effect=error;second.cursor.return_value.execute.side_effect=error
                driver=SimpleNamespace(connect=MagicMock(return_value=second),OperationalError=psycopg2.OperationalError,InterfaceError=psycopg2.InterfaceError)
                with patch.object(audio.f.db,'BACKEND','postgres'),patch.object(audio.f.db,'_local',cache),patch.object(audio.f.db,'psycopg2',driver,create=True):
                    with self.assertRaises(type(error)):sessions.check(self.user,'synthetic',self.key())
                self.assertEqual(driver.connect.call_count,expected_reconnects)
                self.assertEqual(first.cursor.return_value.execute.call_count,1)
                self.assertEqual(second.cursor.return_value.execute.call_count,expected_reconnects)

    def test_late_old_session_finish_or_end_cannot_mutate_new_active_session(self):
        old=self.session();self.claim(old);sessions.end(self.user,old)
        new=self.session();new_key=self.key(2);new_info=self.claim(new,new_key)
        with self.assertRaises(audio_store.AudioError):sessions.finish(self.user,old,self.key(),True)
        sessions.finish(self.user,old,self.key(),False,code='late-worker');sessions.end(self.user,old)
        with self.assertRaises(audio_store.AudioError):sessions.check(self.user,old,self.key())
        self.assertEqual(sessions.result(self.user,old,self.key())['status'],'CANCELLED')
        self.assertEqual(sessions.check(self.user,new,new_key),new_info)
        self.assertEqual(sessions.result(self.user,new,new_key)['status'],'PROCESSING')
        self.assertFalse(audio.f.db.get_connection().in_transaction)

    def test_end_when_translation_stream_closes_fences_tts_and_keeps_completed_usage(self):
        self.credit(300)
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(live.stt,'transcribe',side_effect=self.transcribe),patch.object(audio_provider,'speech') as tts:
            ident=self.session();info=self.claim(ident)
            def stream(*args,**kwargs):
                yield from self.stream(*args,**kwargs)
                sessions.end(self.user,ident)
            with patch.object(providers,'_openai',side_effect=stream):
                with self.assertRaises(audio_store.AudioError):live.process(self.user,ident,self.key(),self.signal(),info)
            tts.assert_not_called();self.assertEqual(audio_store.balance(self.user)['available'],300)
            self.assertEqual(sessions.result(self.user,ident,self.key())['status'],'CANCELLED')
            self.assertEqual(audio.f.db.query_one('SELECT status FROM kilas_ai_usage WHERE user_id=?',(self.user,))['status'],'COMPLETE')

    def test_fragmented_translation_checks_every_event_without_per_event_connections(self):
        ident=self.session();self.claim(ident);payload=json.dumps({'text':'Hello, how are you?','source_language':'id','target_language':'en'});checked=[]
        def check():
            live.require_ready(self.user);sessions.check(self.user,ident,self.key());checked.append(True)
        def fragmented(*args,**kwargs):
            for char in payload:yield {'type':'delta','text':char}
            yield {'type':'usage','input_tokens':20,'output_tokens':18}
            yield {'type':'finish','reason':'stop'}
        with self.funded(),self.on(),patch.object(providers,'_openai',side_effect=fragmented),patch.object(usage,'_connect',wraps=usage._connect) as connect:
            self.assertEqual(live.translation(self.user,self.key(),'Halo','id','en',check)['text'],'Hello, how are you?')
            # Only usage reservation and settlement need fresh write connections.
            self.assertEqual(connect.call_count,2);self.assertEqual(len(checked),len(payload)+3)

    def test_latency_summary_separates_credit_stt_translation_and_audio_without_content(self):
        self.credit(300);clock=[0.0];output=io.StringIO();credits=[]
        def credit():credits.append(True);clock[0]+=.25
        def transcribe(pcm,cap):clock[0]+=.75;return self.transcribe(pcm,cap)
        def stream(*args,**kwargs):clock[0]+=1.5;yield from self.stream(*args,**kwargs)
        def speech(*args,**kwargs):clock[0]+=2.0;return self.audio,'synthetic-request'
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(live,'monotonic',side_effect=lambda:clock[0]),patch.object(live.stt,'require_subscription_credit',side_effect=credit),patch.object(live.stt,'transcribe',side_effect=transcribe),patch.object(providers,'_openai',side_effect=stream),patch.object(audio_provider,'speech',side_effect=speech),redirect_stdout(output):
            ident=self.session();info=self.claim(ident);live.process(self.user,ident,self.key(),self.signal(),info)
        log=output.getvalue();self.assertEqual(len(credits),2)
        for part in ('outcome=completed','credit_stt_ms=250.0','stt_ms=750.0','translation_ms=1500.0','translation_first_delta_ms=1500.0','translation_fences_ms=0.0','credit_tts_ms=250.0','audio_submit_ms=2000.0','backend_ms=4750.0'):self.assertIn(part,log)
        for private in ('Halo','Hello',ident,self.key(),VOICE['id'],'synthetic-only','synthetic-request','proj_synthetic'):self.assertNotIn(private,log)

    def test_failed_stage_is_timed_and_diagnostic_io_cannot_block_processing(self):
        self.credit(300);clock=[0.0];output=io.StringIO()
        def deny():clock[0]+=.5;raise budget.BudgetError('provider_credit_exhausted',402)
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(live,'monotonic',side_effect=lambda:clock[0]),patch.object(live.stt,'require_subscription_credit',side_effect=deny),patch.object(live.stt,'transcribe') as stt,redirect_stdout(output):
            ident=self.session();info=self.claim(ident)
            with self.assertRaises(budget.BudgetError):live.process(self.user,ident,self.key(),self.signal(),info)
        stt.assert_not_called();self.assertIn('outcome=failed',output.getvalue());self.assertIn('credit_stt_ms=500.0',output.getvalue())
        with patch('builtins.print',side_effect=BrokenPipeError()):live._log_latency({},0,False)

    def test_translation_validation_failures_are_settled_once_with_private_safe_diagnostics(self):
        self.credit(300)
        valid={'text':'private-translated-phrase','source_language':'id','target_language':'en'}
        cases=[('invalid_json','private invalid json','stop'),('invalid_shape',json.dumps([valid]),'stop'),
               ('invalid_shape','null','stop'),('invalid_text',json.dumps({**valid,'text':['private']}),'stop'),
               ('invalid_language_pair',json.dumps({**valid,'source_language':['private']}),'stop'),
               ('invalid_language_pair',json.dumps({**valid,'source_language':'fr'}),'stop'),
               ('incomplete_response',json.dumps(valid),'length')]
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(segments,'speech') as tts,patch.object(live.stt,'transcribe') as stt:
            ident=self.session()
            for index,(reason,payload,finish) in enumerate(cases,100):
                key=self.key(index);info=self.claim(ident,key);output=io.StringIO()
                events=[{'type':'delta','text':payload},{'type':'usage','input_tokens':21,'output_tokens':19},{'type':'finish','reason':finish}]
                with patch.object(providers,'_openai',return_value=(event for event in events)) as provider,redirect_stdout(output):
                    with self.assertRaises(audio_store.AudioError) as failed:live.process(self.user,ident,key,None,info,committed_text='private-source-phrase',whole_output=True)
                self.assertEqual(failed.exception.code,'translation_failed');self.assertEqual(provider.call_count,1)
                self.assertEqual(sessions.result(self.user,ident,key)['error_code'],'translation_failed')
                record=audio.f.db.query_one('SELECT status,input_tokens,output_tokens FROM kilas_ai_usage WHERE user_id=? AND operation_key=?',(self.user,key+'-text'))
                self.assertEqual((record['status'],record['input_tokens'],record['output_tokens']),('FAILED',21,19))
                log=output.getvalue();self.assertIn('failure_stage=translation_ms',log);self.assertIn('failure_code=translation_failed',log)
                self.assertIn('translation_failure_reason='+reason,log);self.assertIn('translation_events=3.0',log)
                self.assertIn('translation_settlement_ms=',log)
                for private in ('private',ident,key,VOICE['id'],'proj_synthetic','synthetic-only'):self.assertNotIn(private,log)
            tts.assert_not_called();stt.assert_not_called()

    def test_provider_and_accounting_failures_have_distinct_safe_stages_without_retries(self):
        self.credit(300)
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(segments,'speech') as tts:
            ident=self.session();key=self.key();info=self.claim(ident,key);output=io.StringIO()
            with patch.object(providers,'_openai',side_effect=providers.ProviderError('private-provider-body')) as provider,redirect_stdout(output):
                with self.assertRaises(audio_store.AudioError):live.process(self.user,ident,key,None,info,committed_text='private-source')
            self.assertEqual(provider.call_count,1);self.assertIn('translation_failure_reason=provider_error',output.getvalue());self.assertNotIn('private',output.getvalue())
            key=self.key(2);info=self.claim(ident,key);output=io.StringIO()
            with patch.object(providers,'_openai',side_effect=self.stream) as provider,patch.object(usage,'finish',side_effect=RuntimeError('private-accounting-body')),redirect_stdout(output):
                with self.assertRaises(RuntimeError):live.process(self.user,ident,key,None,info,committed_text='private-source')
            self.assertEqual(provider.call_count,1);tts.assert_not_called()
            self.assertIn('failure_stage=translation_settlement_ms',output.getvalue());self.assertIn('translation_failure_reason=accounting_error',output.getvalue())
            self.assertNotIn('private',output.getvalue());self.assertEqual(sessions.result(self.user,ident,key)['status'],'FAILED')

    def test_diagnostics_never_echo_arbitrary_error_codes_or_reasons(self):
        output=io.StringIO()
        with redirect_stdout(output):live._log_latency({'failure_stage':'private-stage','translation_failure_reason':'private-body'},0,False,'private-code')
        self.assertIn('failure_stage=between_stages failure_code=other_failure',output.getvalue());self.assertNotIn('private',output.getvalue())

    def test_live_owner_qa_does_not_use_up_dictation_allowance_and_stops_at_four(self):
        with self.funded(),patch.dict(os.environ,{'KILAS_VO_STT_USAGE_MODE':'owner','KILAS_VO_STT_ALLOWED_OWNER_ID':str(self.user),'KILAS_LIVE_TRANSLATOR_USAGE_MODE':'qa'}):
            pcm=self.signal();digest=hashlib.sha256(pcm).hexdigest();_,ms=live.stt.normalize(pcm)
            for n in range(2):
                _,cap=budget.claim(self.user,'dictate-'+str(n).zfill(32),digest,ms)
                budget.dispatch(cap,digest,ms);budget.finish(cap,True)
            for n in range(4):
                _,cap=budget.claim(self.user,self.key(n),digest,ms)
                budget.dispatch(cap,digest,ms);budget.finish(cap,True)
            with self.assertRaises(budget.BudgetError) as error:budget.claim(self.user,self.key(9),digest,ms)
            self.assertEqual(error.exception.code,'attempt_limit')
            _,cap=budget.claim(self.user,'dictate-normal-use-1234567890',digest,ms)
            self.assertIsNotNone(cap);budget.cancel(self.user,cap.key)
            with self.assertRaises(budget.BudgetError):budget.claim(self.other,self.key(8),digest,ms)

    def test_credit_denial_before_stt_and_after_translation_never_dispatches_next_stage(self):
        self.credit(300)
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(live.stt,'transcribe',side_effect=self.transcribe) as stt,patch.object(providers,'_openai',side_effect=self.stream) as ai,patch.object(audio_provider,'speech') as tts:
            ident=self.session();info=self.claim(ident)
            with patch.object(live.stt,'require_subscription_credit',side_effect=budget.BudgetError('provider_credit_exhausted',402)):
                with self.assertRaises(budget.BudgetError):live.process(self.user,ident,self.key(),self.signal(),info)
            stt.assert_not_called();ai.assert_not_called();tts.assert_not_called()
            self.assertIn('Kapasitas layanan suara tidak cukup',self.client.get('/kilas-translator/live/sessions/'+ident+'/turns/'+self.key()).json['error'])
            info=self.claim(ident,self.key(2))
            with patch.object(live.stt,'require_subscription_credit',side_effect=[None,budget.BudgetError('provider_credit_exhausted',402)]):
                with self.assertRaises(budget.BudgetError):live.process(self.user,ident,self.key(2),self.signal(),info)
            self.assertEqual(stt.call_count,1);self.assertEqual(ai.call_count,1);tts.assert_not_called()
            self.assertEqual(audio_store.balance(self.user)['available'],300)

    def pooled_response(self,body=None,raw=None):
        response=MagicMock();response.__enter__.return_value=response;response.status_code=200
        response.json.return_value=body;response.headers={'request-id':'synthetic-request'}
        response.iter_content.return_value=[raw if raw is not None else json.dumps(body).encode()]
        return response

    def subscription(self,used=0):
        return {'tier':'creator','status':'active','max_credit_limit_extension':0,
                'allowed_to_extend_character_limit':False,'can_extend_character_limit':False,
                'character_count':used,'character_limit':100}

    def test_turn_reuses_provider_client_but_reads_credit_fresh_before_each_paid_stage(self):
        from kilas_ai import live_translator_transport as transport
        self.credit(300);client=MagicMock()
        client.get.side_effect=[self.pooled_response(self.subscription()),self.pooled_response(self.subscription())]
        client.post.return_value=self.pooled_response({'text':'Halo, apa kabar?'})
        client.request.return_value=self.pooled_response(raw=self.audio)
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(live.stt,'require_subscription_credit',wraps=self.subscription_credit_check),patch.object(providers,'_openai',side_effect=self.stream),patch.object(transport.requests,'Session',return_value=client) as factory:
            ident=self.session();key=self.key();info=self.claim(ident,key)
            job=live.process(self.user,ident,key,self.signal(),info)
            self.assertEqual(audio_store.get(self.user,job)['status'],'COMPLETED')
            self.assertEqual(sessions.result(self.user,ident,key)['status'],'COMPLETED')
        factory.assert_called_once();self.assertEqual(client.get.call_count,2)
        client.post.assert_called_once();client.request.assert_called_once();client.close.assert_called_once()
        self.assertEqual([call[0] for call in client.method_calls],['get','post','get','request','close'])
        self.assertEqual(client.request.call_args.args[0],'POST')
        self.assertEqual(client.request.call_args.kwargs['json']['model_id'],'eleven_multilingual_v2')
        for call in client.get.call_args_list:
            self.assertEqual(call.args[0],'https://api.elevenlabs.io/v1/user/subscription')
            self.assertFalse(call.kwargs['allow_redirects'])

    def test_pooled_credit_exhaustion_after_stt_denies_tts_without_retry_or_cached_approval(self):
        from kilas_ai import live_translator_transport as transport
        self.credit(300);client=MagicMock()
        client.get.side_effect=[self.pooled_response(self.subscription()),self.pooled_response(self.subscription(100))]
        client.post.return_value=self.pooled_response({'text':'Halo, apa kabar?'})
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(live.stt,'require_subscription_credit',wraps=self.subscription_credit_check),patch.object(providers,'_openai',side_effect=self.stream),patch.object(transport.requests,'Session',return_value=client):
            ident=self.session();key=self.key();info=self.claim(ident,key)
            with self.assertRaises(budget.BudgetError) as error:live.process(self.user,ident,key,self.signal(),info)
            self.assertEqual(error.exception.code,'provider_credit_exhausted')
        self.assertEqual(client.get.call_count,2);client.post.assert_called_once()
        client.request.assert_not_called();client.close.assert_called_once()
        self.assertEqual(audio_store.balance(self.user)['available'],300)

    def test_verified_project_is_sent_only_for_explicit_live_translation(self):
        response=MagicMock();response.__enter__.return_value=response
        with patch.object(providers.requests,'post',return_value=response) as transport,patch.object(providers,'_events',return_value=iter([])):
            list(providers._openai(model_policy.LUNA,'synthetic-only',[{'role':'user','content':'Hello'}],'FAST',project='proj_synthetic'))
            self.assertEqual(transport.call_args.kwargs['headers']['OpenAI-Project'],'proj_synthetic')
            list(providers._openai(model_policy.LUNA,'synthetic-only',[{'role':'user','content':'Hello'}],'FAST'))
            self.assertNotIn('OpenAI-Project',transport.call_args.kwargs['headers'])

    def test_end_closes_openai_stream_and_records_cancelled_work(self):
        closed=[]
        def stream(*args,**kwargs):
            try:yield {'type':'delta','text':'{}'}
            finally:closed.append(True)
        def check():
            if closed:raise AssertionError('Unexpected subsequent call')
            check.calls+=1
            if check.calls==2:raise audio_store.AudioError('Sesi berakhir.','session_ended',409)
        check.calls=0
        with self.on(),patch.object(providers,'_openai',side_effect=stream):
            with self.assertRaises(audio_store.AudioError):live.translation(self.user,self.key(),'Halo','id','en',check)
        self.assertEqual(closed,[True])
        self.assertEqual(audio.f.db.query_one('SELECT status FROM kilas_ai_usage WHERE user_id=?',(self.user,))['status'],'FAILED')

    def test_existing_owner_audio_exemption_still_has_finite_live_output_allowance(self):
        with self.funded(),self.on(),patch.object(branded,'resolve',return_value=VOICE),patch.object(live.stt,'transcribe',side_effect=self.transcribe) as stt,patch.object(providers,'_openai',side_effect=self.stream),patch.object(audio_provider,'speech',return_value=(self.audio,'synthetic-request')),patch.object(usage,'_qa_quota_exempt',return_value=True):
            ident=self.session();info=self.claim(ident)
            job=live.process(self.user,ident,self.key(),self.signal(),info)
            self.assertEqual(audio_store.get(self.user,job)['seconds_charged'],0)
            self.assertEqual(audio_store.balance(self.user)['seconds'],0)
            with patch.dict(os.environ,{'KILAS_LIVE_TRANSLATOR_AUDIO_SECONDS':'1'}):
                info=self.claim(ident,self.key(2))
                with self.assertRaises(audio_store.AudioError) as error:live.process(self.user,ident,self.key(2),self.signal(),info)
                self.assertEqual(error.exception.code,'live_audio_limit')
            self.assertEqual(stt.call_count,1)


    def test_translation_profile_is_purpose_bound_without_smaller_output_budget(self):
        for text in ('Halo','Please give a brief answer','SQL debug architecture analysis without budget must only maximum ' * 80,'你好' * 1900):
            with self.subTest(text=text[:30]):
                original=model_policy.chat_profile([{'role':'user','content':text}])
                profile=live.translation_profile(text)
                self.assertEqual(profile['model'],model_policy.LUNA)
                self.assertEqual(profile['effort'],'low')
                self.assertGreaterEqual(profile['output_tokens'],max(3500,original['output_tokens']))
                self.assertEqual(model_policy.chat_profile([{'role':'user','content':text}]),original)

    def test_translation_reservation_and_actual_request_share_same_private_profile(self):
        text='Please analyze SQL strategy without risk must only use this budget.'
        payload=json.dumps({'text':'Hello, how are you?','source_language':'id','target_language':'en'})
        response=MagicMock();response.__enter__.return_value=response
        events=[{'choices':[{'delta':{'content':payload},'finish_reason':'stop'}]}, {'usage':{'prompt_tokens':20,'completion_tokens':18}}]
        with self.funded(),self.on(),patch.object(usage,'reserve',wraps=usage.reserve) as reserve,patch.object(providers.requests,'post',return_value=response) as request,patch.object(providers,'_events',return_value=iter(events)):
            self.assertEqual(live.translation(self.user,self.key(),text,'id','en',lambda:None)['text'],'Hello, how are you?')
        profile=reserve.call_args.kwargs['profile'];body=request.call_args.kwargs['json']
        self.assertEqual(body['model'],profile['model']);self.assertEqual(body['reasoning_effort'],profile['effort']);self.assertEqual(body['max_completion_tokens'],profile['output_tokens'])
        self.assertEqual(body['messages'][1]['content'],text);self.assertIn('faithfully',body['messages'][0]['content']);self.assertEqual(request.call_count,1)
        row=audio.f.db.query_one('SELECT mode,status,model FROM kilas_ai_usage WHERE user_id=?',(self.user,))
        self.assertEqual(row['mode'],'FAST');self.assertEqual(row['status'],'COMPLETE');self.assertEqual(row['model'],model_policy.LUNA)

    def test_regular_chat_keeps_original_reasoning_profile(self):
        messages=[{'role':'user','content':'Discuss my vacation.'}];original=model_policy.chat_profile(messages)
        response=MagicMock();response.__enter__.return_value=response
        with patch.object(providers.requests,'post',return_value=response) as request,patch.object(providers,'_events',return_value=iter([])):
            list(providers._openai(model_policy.LUNA,'synthetic-only',messages,'FAST'))
        self.assertEqual(request.call_args.kwargs['json']['reasoning_effort'],original['effort'])
        self.assertEqual(request.call_args.kwargs['json']['max_completion_tokens'],original['output_tokens'])


    def test_long_translation_is_returned_in_full_with_stop_and_language_validation(self):
        translated='你好。مرحبا؟ Words without punctuation ' * 100
        def stream(*args,**kwargs):
            value=json.dumps({'text':translated,'source_language':'id','target_language':'en'})
            for index in range(0,len(value),17):yield {'type':'delta','text':value[index:index+17]}
            yield {'type':'finish','reason':'stop'}
        with self.funded(),self.on(),patch.object(providers,'_openai',side_effect=stream):
            result=live.translation(self.user,self.key(),'Long speech about SQL strategy without risk','id','en',lambda:None)
        self.assertEqual(result['text'],translated.strip())


if __name__=='__main__':unittest.main()
