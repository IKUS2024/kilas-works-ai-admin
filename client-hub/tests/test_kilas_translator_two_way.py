"""Explicit-pair contracts with synthetic audio/providers; no spoken-language QA."""
import hashlib
import json
import os
import unittest
from unittest.mock import patch
import test_kilas_live_translator as f
from kilas_ai import live_translator as live,live_translator_store as sessions
from kilas_ai import audio_branded_voices as voices,audio_provider,providers,audio_store


class TwoWayTests(unittest.TestCase):
    setUp=f.LiveTranslatorTests.setUp
    credit=f.LiveTranslatorTests.credit
    funded=f.LiveTranslatorTests.funded
    on=f.LiveTranslatorTests.on
    session=f.LiveTranslatorTests.session
    signal=f.LiveTranslatorTests.signal
    transcribe=f.LiveTranslatorTests.transcribe
    @classmethod
    def setUpClass(cls):cls.audio=f.audio.mp3()
    def key(self,n=1):return 'live-'+hashlib.sha256(f'{self.user}:pair:{n}'.encode()).hexdigest()[:32]
    def production(self):
        return patch.dict(os.environ,{'KILAS_VO_STT_ALLOWED_OWNER_ID':str(self.user),'KILAS_VO_STT_USAGE_MODE':'owner','KILAS_LIVE_TRANSLATOR_USAGE_MODE':'owner'})
    def stream(self,*args,**kwargs):
        text=json.loads(args[2][0]['content'])['source_text']
        result=self.expected[text]
        self.assertIn('never infer direction',kwargs['system'])
        self.assertIn('Never guess a source language',kwargs['system'])
        yield {'type':'delta','text':json.dumps(result)}
        yield {'type':'usage','input_tokens':20,'output_tokens':18}
        yield {'type':'finish','reason':'stop'}

    def test_alternating_then_repeated_direction_and_reconnect_same_pair(self):
        self.credit(300)
        inputs=['Saya ingin ke pasar.','Where is the station?','I need a ticket.','Terima kasih.']
        pairs=[('id','en'),('en','id'),('en','id'),('id','en')]
        outputs=['I want to go to the market.','Di mana stasiunnya?','Saya perlu tiket.','Thank you.']
        self.expected={text:dict(text=out,source_language=a,target_language=b) for text,(a,b),out in zip(inputs,pairs,outputs)}
        pending=iter(inputs)
        def stt(pcm,cap):self.transcribe(pcm,cap);return next(pending)
        with self.funded(2000000,2000000),self.on(),self.production(),patch.object(voices,'resolve',return_value=f.VOICE),patch.object(live.stt,'transcribe',side_effect=stt) as recognition,patch.object(providers,'_openai',side_effect=self.stream) as llm,patch.object(audio_provider,'speech',return_value=(self.audio,'synthetic')) as tts:
            ident=self.session()
            for n,(source,target) in enumerate(pairs,1):
                key=self.key(n);info=sessions.claim(self.user,ident,key)
                live.process(self.user,ident,key,self.signal(),info)
                result=self.client.get(f'/kilas-translator/live/sessions/{ident}/turns/{key}').json
                self.assertEqual((result['source_language'],result['target_language']),(source,target))
                self.assertEqual(self.client.get(result['audio_url']).data,self.audio)
                self.assertEqual(tts.call_args.args[1:3],(f.VOICE['id'],target))
                # Same durable session/pair, including a refresh/read and repeated direction.
                self.assertEqual(sessions.status(self.user,ident),{'status':'ACTIVE','processing':False})
                self.assertEqual(sessions.result(self.user,ident,key)['status'],'COMPLETED')
                with self.assertRaises(audio_store.AudioError):sessions.claim(self.user,ident,key)
            self.assertEqual((recognition.call_count,llm.call_count,tts.call_count),(4,4,4))
            row=f.audio.f.db.query_one('SELECT language_a,language_b FROM kilas_live_translator_sessions WHERE id=?',(ident,))
            self.assertEqual((row['language_a'],row['language_b']),('id','en'))

    def test_ambiguous_out_of_pair_no_tts_then_valid_turn_recovers(self):
        self.credit(300)
        self.expected={'ambiguous':dict(text='',source_language='unknown',target_language='unknown'),
                       'outside':dict(text='Untrusted result',source_language='fr',target_language='en'),
                       'valid':dict(text='Terima kasih.',source_language='en',target_language='id')}
        pending=iter(self.expected)
        def stt(pcm,cap):self.transcribe(pcm,cap);return next(pending)
        with self.funded(2000000,2000000),self.on(),self.production(),patch.object(voices,'resolve',return_value=f.VOICE),patch.object(live.stt,'transcribe',side_effect=stt),patch.object(providers,'_openai',side_effect=self.stream),patch.object(audio_provider,'speech',return_value=(self.audio,'synthetic')) as tts:
            ident=self.session()
            for n,code in enumerate(('translation_ambiguous','translation_language_mismatch'),1):
                key=self.key(n);info=sessions.claim(self.user,ident,key)
                with self.assertRaises(audio_store.AudioError) as error:live.process(self.user,ident,key,self.signal(),info)
                self.assertEqual(error.exception.code,code);tts.assert_not_called()
                self.assertEqual(sessions.result(self.user,ident,key)['status'],'FAILED')
            key=self.key(3);info=sessions.claim(self.user,ident,key)
            live.process(self.user,ident,key,self.signal(),info)
            self.assertEqual(tts.call_count,1);self.assertEqual(tts.call_args.args[2],'id')

    def test_auto_new_session_and_legacy_new_turn_rejected_without_provider_or_guess(self):
        self.credit(300)
        with self.funded(),self.on(),patch.object(live.stt,'transcribe') as stt,patch.object(providers,'_openai') as llm,patch.object(audio_provider,'speech') as tts:
            fields={'csrf_token':'audio-csrf','language_a':'auto','language_b':'en','voice':'kilas-male','consent':'yes'}
            response=self.client.post('/kilas-translator/live/sessions',data=fields)
            self.assertEqual(response.status_code,400);self.assertEqual(response.json['code'],'invalid_language_pair')
            with self.assertRaises(audio_store.AudioError):sessions.create(self.user,'auto','en','kilas-male')
            ident=self.session()
            f.audio.f.db.execute('UPDATE kilas_live_translator_sessions SET language_a=? WHERE id=?',('auto',ident))
            with self.assertRaises(audio_store.AudioError) as denied:sessions.claim(self.user,ident,self.key())
            self.assertEqual(denied.exception.code,'invalid_language_pair')
            self.assertEqual(sessions.active(self.user)['session_id'],ident)
            self.assertIsNone(f.audio.f.db.query_one('SELECT status FROM kilas_live_translator_turns WHERE operation_key=?',(self.key(),)))
            stt.assert_not_called();llm.assert_not_called();tts.assert_not_called()
            self.assertEqual(self.client.post('/kilas-translator/live/sessions/'+ident+'/end',data={'csrf_token':'audio-csrf'}).status_code,200)
