"""Documented routes/account discovery and native payloads; paid IO forbidden."""
import io
import unittest
from unittest.mock import Mock,patch
import test_kilas_live_translator as fixture
from kilas_ai import translator_languages as languages,audio_provider as provider
from kilas_ai import live_gemini as native,live_gemini_pair as pair,live_translator_segments as segments,live_translator_store as sessions


class CatalogTests(unittest.TestCase):
    def setUp(self):
        languages._cache=None;languages._until=0

    def catalogue(self,codes=languages.CLASSIC):
        return [{'model_id':'eleven_v4','can_do_text_to_speech':True,'requires_alpha_access':False,
                 'languages':[{'language_id':code,'name':languages.NAMES[code]} for code in codes]}]

    def test_exact_distinct_counts_and_unchanged_unrelated_list(self):
        self.assertEqual([len(x) for x in (languages.NATIVE,languages.V4,languages.STT,languages.DUBBING,languages.CLASSIC)],[76,84,100,93,83])
        self.assertEqual(len(languages.NATIVE|languages.DUBBING|languages.CLASSIC),108)
        self.assertEqual(len(provider.LANGUAGES),18)
        self.assertEqual(languages.CLASSIC,languages.V4&languages.STT)
        self.assertNotIn('cmn',languages.DUBBING);self.assertNotIn('nb',languages.NATIVE)

    def test_account_intersection_cache_and_no_inference(self):
        with patch.object(provider,'configured',return_value=True),patch.object(provider,'request',return_value=self.catalogue({'id','en','ja'})) as request:
            self.assertEqual(set(languages.classic_names()),{'id','en','ja'});languages.classic_names()
            request.assert_called_once_with('GET','/models')
            languages._until=0;languages.classic_names();self.assertEqual(request.call_count,2)

    def test_all_catalogue_languages_intersect_speech_support_and_native_wire_routes(self):
        with patch.object(provider,'configured',return_value=True),patch.object(provider,'request',return_value=self.catalogue(languages.NAMES)) as request:
            self.assertEqual(set(languages.classic_names()),languages.CLASSIC)
            for code in languages.NAMES:
                other='en' if code!='en' else 'id'
                if code in languages.CLASSIC:
                    languages.require_classic(code,other);languages.require_classic(other,code)
                    self.assertEqual(languages.speech_payload('Synthetic text',code)['language_code'],code)
                else:
                    for a,b in ((code,other),(other,code)):
                        with self.assertRaises(ValueError):languages.require_classic(a,b)
            request.assert_called_once_with('GET','/models')
        for a in languages.NATIVE:
            self.assertEqual(native.setup(a)['setup']['generationConfig']['translationConfig']['targetLanguageCode'],languages.native_wire(a))
            for b in languages.NATIVE-{a}:sessions.require_pair(a,b,voice='gemini-live-two-way')

    def test_missing_alpha_malformed_and_failed_catalogue_never_fallback(self):
        for data in ([],{},[{'model_id':'eleven_v3','can_do_text_to_speech':True}],
                     [{'model_id':'eleven_v4','can_do_text_to_speech':False}],
                     [{'model_id':'eleven_v4','can_do_text_to_speech':True,'requires_alpha_access':True}],
                     [{'model_id':'eleven_v4','can_do_text_to_speech':True,'languages':None}]):
            languages._cache=None
            with patch.object(provider,'configured',return_value=True),patch.object(provider,'request',return_value=data):self.assertEqual(languages.classic_names(),{})
        languages._cache=None
        with patch.object(provider,'configured',return_value=True),patch.object(provider,'request',side_effect=provider.ProviderError()) as request:
            self.assertEqual(languages.classic_names(),{});self.assertEqual(languages.classic_names(),{});request.assert_called_once()

    def test_native_exact_model_wire_codes_and_alias_validation(self):
        for public,wire in [('jv','jv'),('zh','zh-Hans'),('pt','pt-PT')]:
            setup=native.setup(public)['setup'];self.assertEqual(setup['model'],'models/gemini-3.5-live-translate-preview')
            self.assertEqual(setup['generationConfig']['translationConfig'],{'targetLanguageCode':wire,'echoTargetLanguage':False})
        self.assertEqual(languages.canonical('zh-Hant'),'zh');self.assertEqual(languages.canonical('pt-BR'),'pt')
        self.assertEqual(languages.canonical('nb'),'no')
        with self.assertRaises(ValueError):native.setup('yo')

    def test_v4_settings_and_exact_original_voice_no_tags_or_voice_mutation(self):
        with patch.object(languages,'classic_names',return_value=languages.names(languages.CLASSIC)),patch.object(provider,'request',return_value=(b'synthetic','request')) as request:
            provider.speech('Natural spoken words.','exactOriginalVoice123','th',translator=True)
            self.assertEqual(request.call_args.args,('POST','/text-to-speech/exactOriginalVoice123'))
            payload=request.call_args.kwargs['json']
            self.assertEqual(payload,{'text':'Natural spoken words.','model_id':'eleven_v4','language_code':'th','voice_settings':{'stability':0.5,'similarity_boost':0.75},'apply_text_normalization':'auto'})
            with self.assertRaises(ValueError):languages.speech_payload('text','am')
            self.assertEqual(request.call_count,1)

    def test_translator_stream_uses_same_v4_contract_once(self):
        context=Mock();response=Mock(status_code=200);response.iter_content.return_value=iter([b'first',b'second']);context.__enter__=Mock(return_value=response);context.__exit__=Mock(return_value=False)
        with patch.dict(provider.os.environ,{'ELEVENLABS_API_KEY':'synthetic'}),patch.object(languages,'classic_names',return_value=languages.names(languages.CLASSIC)),patch.object(segments.transport,'request',return_value=context) as request:
            self.assertEqual(segments.speech('Hello','exactOriginalVoice123',Mock(),Mock(),language='vi',previous='before'),b'firstsecond')
            request.assert_called_once();payload=request.call_args.kwargs['json']
            self.assertEqual(payload['model_id'],'eleven_v4');self.assertEqual(payload['language_code'],'vi')
            self.assertNotIn('previous_text',payload);self.assertNotIn('style',payload['voice_settings'])


class RouteTests(unittest.TestCase):
    setUp=fixture.LiveTranslatorTests.setUp
    credit=fixture.LiveTranslatorTests.credit
    funded=fixture.LiveTranslatorTests.funded
    on=fixture.LiveTranslatorTests.on
    audio=b'synthetic'

    def test_classic_extended_pair_and_unsupported_pair_before_paid_work(self):
        self.credit(300)
        fields={'csrf_token':'audio-csrf','language_a':'id','language_b':'jv','voice':'kilas-male','consent':'yes'}
        with self.funded(),self.on(),patch.object(fixture.branded,'resolve',return_value=fixture.VOICE),patch.object(provider,'speech') as paid:
            response=self.client.post('/kilas-translator/live/sessions',data=fields)
            self.assertEqual(response.status_code,201,response.text);paid.assert_not_called()
            sessions.end(self.user,response.json['session_id'])
            self.assertEqual(self.client.post('/kilas-translator/live/sessions',data={**fields,'language_b':'am'}).status_code,400)
            with patch.object(languages,'classic_names',return_value={}):self.assertEqual(self.client.post('/kilas-translator/live/sessions',data=fields).status_code,503)

    def test_native_extended_pair_keeps_provider_and_rejects_classic_only_language(self):
        self.credit(300)
        fields={'csrf_token':'audio-csrf','language_a':'id','language_b':'am','translation_mode':'two_way','consent':pair.INPUT_MODE,'output_order':pair.OUTPUT_ORDER}
        with patch.object(pair,'ready',return_value=True),patch.object(native,'connect') as connect:
            response=self.client.post('/kilas-translator/live/gemini/sessions',data=fields)
            self.assertEqual(response.status_code,201,response.text);connect.assert_not_called()
            sessions.end(self.user,response.json['session_id'])
            self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data={**fields,'language_b':'bs'}).status_code,400)

    def test_uploaded_dubbing_expanded_target_one_submission(self):
        self.credit(300)
        with patch.object(provider,'dub',return_value='proj_synthetic') as dub:
            response=self.client.post('/kilas-translator/jobs',data={'csrf_token':'audio-csrf','operation_key':'expanded-dubbing-key-1234','mode':'translate','source_language':'id','language':'zu','file':(io.BytesIO(fixture.audio.wav()),'synthetic.wav')})
        self.assertEqual(response.status_code,201,response.text);self.assertEqual(dub.call_count,1);self.assertEqual(dub.call_args.args[2],'zu')


if __name__=='__main__':unittest.main()
