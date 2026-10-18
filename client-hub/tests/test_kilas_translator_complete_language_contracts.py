"""Exhaustive local route contracts. Synthetic text/audio is NOT language QA."""
import io
import json
import os
import unittest
from urllib.parse import urlparse,parse_qs
from unittest.mock import Mock,MagicMock,patch
import test_kilas_live_translator as f
from kilas_ai import translator_languages as languages,audio_provider as provider
from kilas_ai import live_translator as live,live_translator_store as sessions,live_translator_segments as segments
from kilas_ai import audio_transcription_provider as stt,audio_transcription_budget as budget
from kilas_ai import audio_branded_voices as voices,providers,usage,model_policy,live_translator_realtime as realtime


def response(raw):
    result=MagicMock(status_code=200)
    result.__enter__.return_value=result
    result.iter_content.side_effect=lambda *args:[raw]
    return result


class AllLanguageContracts(unittest.TestCase):
    def test_all_ordered_pairs_and_both_exact_voice_aliases(self):
        pairs=0
        for alias,owner,ident,name in voices.SOURCES:
            with patch.object(voices.db,'query_one',side_effect=lambda sql,args:{'voice_id':'syntheticMale123' if args[1]==5 else 'syntheticFemale123'}):
                chosen=voices.resolve(alias)
                self.assertEqual(chosen['id'],'syntheticMale123' if ident==5 else 'syntheticFemale123')
            for a in languages.CLASSIC:
                self.assertEqual(live.canonical_language(a),a)
                for b in languages.CLASSIC-{a}:
                    sessions.require_pair(a,b,voice=alias)
                    schema=live.translation_format(a,b)['json_schema']['schema']
                    self.assertEqual(set(schema['properties']['target_language']['enum']),{a,b,'unknown'})
                    pairs+=1
        self.assertEqual(pairs,83*82*2)
        self.assertEqual(set(languages._STT_CODES.values()),languages.STT)
        for code,canonical in languages._STT_CODES.items():self.assertEqual(languages.canonical(code),canonical)
        self.assertEqual(languages.canonical('in'),'id');self.assertEqual(languages.canonical('cmn'),'zh')
        self.assertNotIn('in',languages.CLASSIC);self.assertNotIn('auto',languages.CLASSIC)

    def test_all_languages_both_directions_both_voices_actual_adapter_formats(self):
        import test_kilas_audio as audio
        case={};chains=0
        raw=audio.wav(1)
        stt_response=response(json.dumps({'text':'Synthetic source text.'}).encode())
        openai_response=response(b'')
        stream_response=response(b'synthetic-mp3')
        def events(*args,**kwargs):
            return iter([{'choices':[{'delta':{'content':json.dumps({'source_language':case['source'],'target_language':case['target'],'text':'Synthetic translated text.'})},'finish_reason':'stop'}]}, {'usage':{'prompt_tokens':20,'completion_tokens':18}}])
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic','ELEVENLABS_API_KEY':'synthetic','KILAS_LIVE_TRANSLATOR_VERIFIED_PROJECT':'proj_synthetic'}),patch.object(languages,'classic_names',return_value=languages.names(languages.CLASSIC)),patch.object(budget,'dispatch'),patch.object(budget,'finish',return_value=True),patch.object(stt.transport,'post',return_value=stt_response) as asr,patch.object(usage,'reserve',return_value=(None,['CHAT'])),patch.object(live,'_finish_translation'),patch.object(providers.requests,'post',return_value=openai_response) as llm,patch.object(providers,'_events',side_effect=events),patch.object(provider,'request',return_value=(b'synthetic-mp3','synthetic')) as speech,patch.object(segments.transport,'request',return_value=stream_response) as stream:
            for code in sorted(languages.CLASSIC):
                anchor='en' if code!='en' else 'id'
                for source,target in ((code,anchor),(anchor,code)):
                    for voice in ('syntheticMale123','syntheticFemale123'):
                        case.update(source=source,target=target)
                        text=stt.transcribe(raw,Mock())
                        self.assertEqual(asr.call_args.kwargs['data']['model_id'],'scribe_v2')
                        self.assertNotIn('language_code',asr.call_args.kwargs['data'])
                        translated=live.translation(9,'contract-'+str(chains),text,source,target,lambda:None)
                        body=llm.call_args.kwargs['json']
                        self.assertEqual(body['model'],model_policy.LUNA)
                        self.assertEqual(body['response_format'],live.translation_format(source,target))
                        self.assertEqual(translated['target_language'],target)
                        provider.speech(translated['text'],voice,target,translator=True)
                        self.assertEqual(speech.call_args.args,('POST','/text-to-speech/'+voice))
                        self.assertEqual(speech.call_args.kwargs['json']['language_code'],target)
                        self.assertEqual(speech.call_args.kwargs['json']['model_id'],'eleven_v4')
                        self.assertEqual(segments.speech(translated['text'],voice,lambda:None,lambda:None,language=target),b'synthetic-mp3')
                        self.assertTrue(stream.call_args.args[1].endswith('/'+voice+'/stream'))
                        self.assertEqual(stream.call_args.kwargs['json']['language_code'],target)
                        chains+=1
            self.assertEqual(chains,332)
            self.assertEqual([asr.call_count,llm.call_count,speech.call_count,stream.call_count],[332]*4)
        with patch.dict(os.environ,{'ELEVENLABS_API_KEY':'synthetic'}),patch('websocket.create_connection',return_value=Mock()) as connect:
            realtime.connect()
            query=parse_qs(urlparse(connect.call_args.args[0]).query)
            self.assertEqual(query['model_id'],['scribe_v2_realtime'])
            self.assertNotIn('language_code',query)

    def test_complete_explicit_names_for_all_four_locales_and_no_alias_duplicates(self):
        for locale,rows in languages._LOCALIZED.items():
            self.assertIn(locale,('id','en','es','zh'))
            for code in languages.NAMES:
                self.assertTrue(rows[code].strip());self.assertNotEqual(rows[code],code)
        self.assertEqual(languages.NAMES['oc'],'Occitan');self.assertEqual(languages.NAMES['or'],'Odia')

    def test_auto_uses_actual_asr_response_fields_without_invented_confidence(self):
        import test_kilas_audio as audio
        for fields in ({'language_code':'jav','language_probability':.98},{'language_code':'jav'}):
            with patch.dict(os.environ,{'ELEVENLABS_API_KEY':'synthetic'}),patch.object(budget,'dispatch'),patch.object(budget,'finish',return_value=True),patch.object(stt.transport,'post',return_value=response(json.dumps({'text':'Synthetic text.',**fields}).encode())):
                value=stt.transcribe(audio.wav(),Mock(),detect_language=True)
                self.assertEqual(value['language_code'],'jav')
                self.assertEqual(value['language_probability'],fields.get('language_probability'))
        with patch.object(languages,'classic_names',return_value=languages.names(languages.CLASSIC)):
            for iso,code in languages._STT_CODES.items():
                if code in languages.CLASSIC:
                    self.assertEqual(languages.detected_source({'language_code':iso,'language_probability':.98},'en' if code!='en' else 'id'),code)


class DetectionContracts(unittest.TestCase):
    setUp=f.LiveTranslatorTests.setUp
    credit=f.LiveTranslatorTests.credit
    funded=f.LiveTranslatorTests.funded
    on=f.LiveTranslatorTests.on
    key=f.LiveTranslatorTests.key
    signal=f.LiveTranslatorTests.signal
    transcribe=f.LiveTranslatorTests.transcribe

    @classmethod
    def setUpClass(cls):cls.audio=f.audio.mp3()

    def test_auto_admission_uses_batch_and_target_is_required_native_rejects_auto(self):
        self.credit(300)
        fields={'csrf_token':'audio-csrf','language_a':'auto','language_b':'en','voice':'kilas-male','consent':'yes'}
        with self.funded(),self.on(),patch.object(voices,'resolve',return_value=f.VOICE),patch.object(realtime,'ready',return_value=True),patch.object(provider,'speech') as paid:
            result=self.client.post('/kilas-translator/live/sessions',data=fields)
            self.assertEqual(result.status_code,201);self.assertEqual(result.json['input_mode'],'batch')
            sessions.end(self.user,result.json['session_id'])
            self.assertEqual(self.client.post('/kilas-translator/live/sessions',data={**fields,'language_b':''}).status_code,400)
            self.assertEqual(self.client.post('/kilas-translator/live/sessions',data={**fields,'language_b':'auto'}).status_code,400)
            paid.assert_not_called()
        with self.assertRaises(ValueError):sessions.require_pair('auto','en',voice='gemini-live-two-way')

    def turn(self,metadata,*,reverse=False,provider_error=False):
        ident=sessions.create(self.user,'auto','en','kilas-male');key=self.key();info=sessions.claim(self.user,ident,key)
        def transcribe(pcm,capability,**kwargs):
            self.assertTrue(kwargs['detect_language'])
            self.transcribe(pcm,capability)
            if provider_error:raise budget.BudgetError('transcription_failed')
            return {'text':'Synthetic original.',**metadata}
        def translation(*args,**kwargs):
            self.assertEqual(args[3:5],('jv','en'))
            return {'text':'Synthetic translated.','source_language':'en' if reverse else 'jv','target_language':'jv' if reverse else 'en'}
        with patch.object(voices,'resolve',return_value=f.VOICE),patch.object(stt,'transcribe',side_effect=transcribe),patch.object(live,'translation',side_effect=translation) as llm,patch.object(provider,'speech',return_value=(self.audio,'synthetic')) as tts:
            try:
                job=live.process(self.user,ident,key,self.signal(),info)
                self.assertEqual(f.audio.f.db.query_one('SELECT target_language FROM kilas_audio_jobs WHERE id=?',(job,))['target_language'],'en')
                self.assertEqual(tts.call_args.args[1],f.VOICE['id']);self.assertTrue(tts.call_args.kwargs['translator'])
                ready=self.client.get('/kilas-translator/live/sessions/'+ident+'/turns/'+key)
                self.assertEqual(ready.status_code,200)
                audio_url=ready.json['audio_url']
                downloaded=self.client.get(audio_url)
                self.assertEqual(downloaded.status_code,200,downloaded.status)
                self.assertEqual(downloaded.data,self.audio)
                self.assertEqual(downloaded.mimetype,'audio/mpeg')
                self.assertEqual(self.client.get(audio_url).data,self.audio)
                chunk=self.client.get(audio_url,headers={'Range':'bytes=0-15'})
                self.assertEqual(chunk.status_code,206);self.assertEqual(chunk.data,self.audio[:16])
                self.assertEqual(chunk.headers['Content-Range'],'bytes 0-15/'+str(len(self.audio)))
                from auth_test_helpers import authenticate
                foreign=self.client.application.test_client()
                authenticate(foreign,f.audio.f.repo.get_user_by_id(self.other),_csrf_token='audio-csrf')
                self.assertEqual(foreign.get(audio_url).status_code,404)
                f.audio.f.db.execute('UPDATE kilas_live_translator_sessions SET language_b=? WHERE id=?',('auto',ident))
                self.assertEqual(self.client.get(audio_url).status_code,400)
                f.audio.f.db.execute('UPDATE kilas_live_translator_sessions SET language_b=? WHERE id=?',('en',ident))
                self.assertEqual(self.client.get(audio_url).data,self.audio)
                from kilas_ai import live_translator_output as temporary
                temporary.discard(self.user,ident,key)
                expired=self.client.get(audio_url)
                self.assertEqual(expired.status_code,410);self.assertEqual(expired.json['code'],'session_output_expired')
                self.assertEqual(tts.call_count,1);self.assertEqual(llm.call_count,1)
            except ValueError as error:
                if getattr(error,'code',None) in ('detection_uncertain','detected_language_unsupported','detected_language_is_target'):
                    result=self.client.get('/kilas-translator/live/sessions/'+ident+'/turns/'+key)
                    self.assertEqual(result.json['code'],error.code)
                    self.assertNotIn('Permintaan belum berhasil',result.json['error'])
                    self.assertIn('bahasa',result.json['error'].lower())
                raise
            finally:
                self.last_calls=(llm.call_count,tts.call_count)
                sessions.end(self.user,ident)
            return llm.call_count,tts.call_count

    def test_real_detected_metadata_normalizes_three_letter_source_and_keeps_voice(self):
        self.credit(300)
        with self.funded(),self.on():self.assertEqual(self.turn({'language_code':'jav','language_probability':0.98}),(1,1))

    def test_uncertain_unsupported_target_and_provider_errors_never_reach_llm_or_tts(self):
        self.credit(300)
        cases=[({'language_code':'eng','language_probability':.99},'detected_language_is_target'),({'language_code':'amh','language_probability':.99},'detected_language_unsupported'),({'language_code':'jav','language_probability':.3},'detection_uncertain'),({'language_code':'jav'},'detection_uncertain'),({'language_code':'unknown','language_probability':.99},'detection_uncertain')]
        with self.funded(),self.on(),patch.object(budget,'DAILY_ATTEMPTS',20):
            for index,(metadata,code) in enumerate(cases):
                self.key=lambda index=index:'live-'+str(self.user*100+index).zfill(32)
                with patch.object(live,'translation') as llm,patch.object(provider,'speech') as tts:
                    with self.assertRaises(ValueError) as error:self.turn(metadata)
                    self.assertEqual(error.exception.code,code);self.assertEqual(self.last_calls,(0,0))
            self.key=lambda:'live-'+str(self.user*100+99).zfill(32)
            with self.assertRaises(ValueError) as error:self.turn({},provider_error=True)
            self.assertEqual(error.exception.code,'transcription_failed');self.assertEqual(self.last_calls,(0,0))
            self.key=lambda:'live-'+str(self.user*100+100).zfill(32)
            with self.assertRaises(ValueError) as error:self.turn({'language_code':'jav','language_probability':.99},reverse=True)
            self.assertEqual(error.exception.code,'translation_language_mismatch');self.assertEqual(self.last_calls,(1,0))


if __name__=='__main__':unittest.main()
