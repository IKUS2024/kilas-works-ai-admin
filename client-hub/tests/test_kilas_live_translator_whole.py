"""Offline one-request whole output, real local MP3 measurement and disposable accounting."""
import json,math,os,unittest
from contextlib import ExitStack
from threading import Event,Thread
from unittest.mock import patch,MagicMock
import requests
import test_kilas_live_translator as fixture
import test_kilas_audio as audio
from kilas_ai import live_translator as live,live_translator_store as sessions
from kilas_ai import live_translator_segments as segments,audio_store,providers

class WholeTests(unittest.TestCase):
 setUp=fixture.LiveTranslatorTests.setUp
 funded=fixture.LiveTranslatorTests.funded
 on=fixture.LiveTranslatorTests.on
 credit=fixture.LiveTranslatorTests.credit
 session=fixture.LiveTranslatorTests.session
 key=fixture.LiveTranslatorTests.key
 @classmethod
 def setUpClass(cls):cls.raw=audio.mp3(1.4)
 def context(self,text,source='id',target='en'):
  stack=ExitStack();stack.enter_context(self.funded());stack.enter_context(self.on());stack.enter_context(patch.dict(os.environ,{'KILAS_LIVE_TRANSLATOR_AUDIO_SECONDS':'3600'}));stack.enter_context(patch.object(fixture.branded,'resolve',return_value=fixture.VOICE))
  events=[{'type':'delta','text':json.dumps({'text':text,'source_language':source,'target_language':target})},{'type':'finish','reason':'stop'}]
  stack.enter_context(patch.object(providers,'_openai',return_value=(event for event in events)));return stack
 def response(self,chunks):
  response=MagicMock();response.status_code=200;response.__enter__.return_value=response;response.iter_content.side_effect=lambda _:chunks();return response
 def process(self,ident,key,info):return live.process(self.user,ident,key,None,info,committed_text='Stable complete source utterance.',whole_output=True,stream_output=True)
 def path(self,ident,key):return '/kilas-translator/live/sessions/'+ident+'/turns/'+key
 def test_full_variable_text_one_model_voice_request_one_exact_result_and_charge(self):
  texts=['Hello. Goodbye.','Repeated words. Repeated words. 最后一句 كاملة.',('Whole utterance. '*250)[:3999]+'x']
  self.credit(4000)
  for index,text in enumerate(texts):
   with self.subTest(length=len(text)),self.context(text,'en','id'):
    ident=self.session();key=self.key(index+1);info=sessions.claim(self.user,ident,key)
    response=self.response(lambda:iter([self.raw[:50],self.raw[50:]]))
    with patch.object(segments.transport,'request',return_value=response) as request,patch.object(live.stt,'transcribe') as stt,patch.object(segments,'_join') as join,patch.object(live.audio_provider,'speech') as alternate:
     job=self.process(ident,key,info)
    request.assert_called_once();payload=request.call_args.kwargs['json'];self.assertEqual(payload['text'],text);self.assertEqual(payload['model_id'],'eleven_v4');self.assertNotIn('speed',payload['voice_settings']);self.assertEqual(payload['language_code'],'id');self.assertEqual(request.call_args.args[0],'POST');self.assertIn('/text-to-speech/'+fixture.VOICE['id']+'/stream',request.call_args.args[1]);stt.assert_not_called();join.assert_not_called();alternate.assert_not_called()
    row=audio.f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE id=?',(job,));self.assertEqual(row['status'],'COMPLETED');self.assertIsNone(row['result_content']);self.assertIsNone(row['original_script']);self.assertEqual(row['seconds_charged'],math.ceil(row['actual_ms']/1000));self.assertGreater(row['seconds_charged'],0)
    result=self.client.get(self.path(ident,key)).json;self.assertEqual(result['translated_text'],text);self.assertNotIn('segments',result);self.assertEqual(self.client.get(result['audio_url']).data,self.raw);sessions.end(self.user,ident)
 def test_delayed_second_transport_chunk_never_publishes_prefix_or_dispatches_again(self):
  available,release=Event(),Event();jobs=[];errors=[];text='First sentence. Final sentence with repeated repeated words.'
  def chunks():
   yield self.raw[:60];available.set();release.wait(3);yield self.raw[60:]
  with self.context(text):
   self.credit(300);ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key);response=self.response(chunks)
   def worker():
    try:jobs.append(self.process(ident,key,info))
    except BaseException as error:errors.append(error)
   with patch.object(segments.transport,'request',return_value=response) as request:
    thread=Thread(target=worker);thread.start();self.assertTrue(available.wait(2));progress=self.client.get(self.path(ident,key)).json;self.assertEqual(progress,{'status':'PROCESSING'});self.assertEqual(self.client.get(self.path(ident,key)+'/audio').status_code,404);self.assertEqual(self.client.get(self.path(ident,key)+'/audio/segments/0').status_code,404);self.assertEqual(request.call_count,1);release.set();thread.join(3);self.assertFalse(thread.is_alive());self.assertEqual(errors,[]);request.assert_called_once()
   self.assertEqual(len(jobs),1);self.assertEqual(self.client.get(self.path(ident,key)).json['translated_text'],text)
 def test_conversational_request_keeps_each_approved_voice_and_complete_text_without_global_voice_edits(self):
  samples=[('kilas-male','syntheticMale123','en','id','Tidak, jangan kirim 2 kg tanggal 03/04. Nama saya Dr. Arif. Benar?'),
           ('kilas-female','syntheticFemale456','id','en','No, I didn’t say $1,250.50—I said €15.20, twice. Really?')]
  self.credit(300)
  for index,(alias,voice,source,target,text) in enumerate(samples,5):
   with self.context(text,source,target),patch.object(fixture.branded,'resolve',return_value={'id':voice,'name':alias,'alias':alias}):
    ident=sessions.create(self.user,'id','en',alias);key=self.key(index);info=sessions.claim(self.user,ident,key)
    before=[dict(row) for row in audio.f.db.query_all('SELECT * FROM kilas_audio_saved_voices')]
    response=self.response(lambda:iter([self.raw]))
    with patch.object(segments.transport,'request',return_value=response) as request,patch.object(live.audio_provider,'speech') as shared_speech,patch.object(live.audio_provider,'clone_voice') as clone:
     job=self.process(ident,key,info)
    request.assert_called_once();shared_speech.assert_not_called();clone.assert_not_called()
    self.assertIn('/text-to-speech/'+voice+'/stream',request.call_args.args[1])
    payload=request.call_args.kwargs['json'];self.assertEqual(payload['text'],text);self.assertEqual(payload['model_id'],'eleven_v4')
    self.assertEqual(payload['voice_settings'],{'stability':0.5,'similarity_boost':0.75})
    self.assertEqual(payload['apply_text_normalization'],'auto')
    self.assertEqual(payload['language_code'],target)
    for unsupported in ('previous_text','next_text','seed','use_pvc_as_ivc','audio_effects'):self.assertNotIn(unsupported,payload)
    self.assertNotIn('optimize_streaming_latency',request.call_args.kwargs['params'])
    row=audio.f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE id=?',(job,));self.assertEqual(row['voice_id'],voice);self.assertIsNone(row['original_script']);self.assertIsNone(row['result_content'])
    self.assertEqual(row['seconds_charged'],math.ceil(row['actual_ms']/1000));self.assertEqual(self.client.get(self.path(ident,key)).json['translated_text'],text)
    self.assertEqual([dict(row) for row in audio.f.db.query_all('SELECT * FROM kilas_audio_saved_voices')],before);sessions.end(self.user,ident)
  # The Live-only override must not become a saved/global Voice Over setting.
  with patch.object(live.audio_provider,'request',return_value=(self.raw,'synthetic-request')) as request:
   live.audio_provider.speech('Ordinary Voice Over.','syntheticMale123','en')
   self.assertEqual(request.call_args.kwargs['json'],{'text':'Ordinary Voice Over.','model_id':'eleven_multilingual_v2'})
   live.audio_provider.speech('Naskah suara pribadi.','syntheticMale123','id',personal=True)
   self.assertEqual(request.call_args.kwargs['json'],{'text':'Naskah suara pribadi.','model_id':'eleven_v4','language_code':'id','voice_settings':{'stability':0.5,'similarity_boost':0.75}})
 def test_end_during_transport_read_closes_response_without_audio_publication_or_second_request(self):
  available,release=Event(),Event();errors=[]
  def chunks():
   yield self.raw[:60];available.set();release.wait(3);yield self.raw[60:]
  with self.context('Complete first sentence. Complete last sentence.'):
   self.credit(300);ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key);response=self.response(chunks)
   def worker():
    try:self.process(ident,key,info)
    except BaseException as error:errors.append(error)
   with patch.object(segments.transport,'request',return_value=response) as request:
    thread=Thread(target=worker);thread.start();self.assertTrue(available.wait(2));sessions.end(self.user,ident);release.set();thread.join(3);self.assertFalse(thread.is_alive());request.assert_called_once();self.assertEqual(len(errors),1);self.assertIn(errors[0].code,('turn_cancelled','session_unavailable','session_ended'));response.__exit__.assert_called_once()
   self.assertEqual(self.client.get(self.path(ident,key)+'/audio').status_code,404);row=audio.f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE user_id=?',(self.user,));self.assertEqual(row['status'],'FAILED');self.assertIsNone(row['original_script']);self.assertIsNone(row['result_content'])
 def test_end_after_complete_response_settles_valid_paid_output_once_but_never_exposes_it(self):
  with self.context('One full utterance. Every word remains present.'):
   self.credit(300);ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key)
   def complete(*args,**kwargs):sessions.end(self.user,ident);return self.raw
   with patch.object(segments,'speech',side_effect=complete) as speech,patch.object(audio_store,'finish',wraps=audio_store.finish) as finish:
    with self.assertRaises(audio_store.AudioError):self.process(ident,key,info)
    speech.assert_called_once();finish.assert_called_once()
   row=audio.f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE user_id=?',(self.user,));self.assertEqual(row['status'],'COMPLETED');self.assertEqual(row['seconds_charged'],math.ceil(row['actual_ms']/1000));self.assertGreater(row['seconds_charged'],0);self.assertEqual(sessions.result(self.user,ident,key)['status'],'CANCELLED');self.assertEqual(self.client.get(self.path(ident,key)+'/audio').status_code,404)
 def test_transport_tail_failure_records_failure_and_never_falls_back_to_another_paid_request(self):
  def chunks():yield self.raw[:50];raise requests.ConnectionError('Synthetic tail lost')
  with self.context('First sentence. Last sentence.'):
   self.credit(300);ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key);response=self.response(chunks)
   with patch.object(segments.transport,'request',return_value=response) as request,patch.object(live.audio_provider,'speech') as alternate:
    with self.assertRaises(live.audio_provider.ProviderError):self.process(ident,key,info)
    request.assert_called_once();alternate.assert_not_called();response.__exit__.assert_called_once()
   self.assertEqual(sessions.result(self.user,ident,key)['status'],'FAILED');self.assertEqual(self.client.get(self.path(ident,key)+'/audio').status_code,404)
 def test_cached_client_sentence_opt_in_is_ignored_for_new_server_admission(self):
  with self.funded(),self.on(),patch.object(live,'enqueue') as enqueue:
   ident=self.session();response=self.client.post(self.path(ident,self.key()),data={'csrf_token':'audio-csrf','stream_output':'sentences-v1'})
   self.assertEqual(response.status_code,202);enqueue.assert_called_once();self.assertTrue(enqueue.call_args.kwargs['whole_output']);self.assertFalse(enqueue.call_args.kwargs.get('stream_output',False))

 def test_known_case_insensitive_regional_metadata_is_canonicalized_only_within_selected_pair(self):
  text='Every fact remains: 2 kg, 03/04, no delivery. Repeated repeated words.'
  samples=[('id','en',' ID-id ','EN-us'),('en','id','en-GB','id-ID'),
           ('zh','en','zh-Hans','en-US'),('pt','en','pt-BR','en-CA')]
  self.credit(300)
  for index,(source,target,source_tag,target_tag) in enumerate(samples,50):
   with self.subTest(source=source_tag,target=target_tag),self.context(text,source_tag,target_tag):
    ident=sessions.create(self.user,source,target,'kilas-male');key=self.key(index);info=sessions.claim(self.user,ident,key)
    response=self.response(lambda:iter([self.raw]))
    with patch.object(segments.transport,'request',return_value=response) as request:
     job=self.process(ident,key,info)
    request.assert_called_once();self.assertEqual(request.call_args.kwargs['json']['text'],text)
    row=audio.f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE id=?',(job,));self.assertEqual((row['source_language'],row['target_language']),(source,target));self.assertIsNone(row['original_script'])
    result=self.client.get(self.path(ident,key)).json;self.assertEqual((result['source_language'],result['target_language']),(source,target));self.assertEqual(result['translated_text'],text);sessions.end(self.user,ident)

 def test_empty_unknown_translation_keeps_no_speech_and_never_dispatches_tts(self):
  self.credit(300)
  with self.context('','unknown','unknown'):
   ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key)
   with patch.object(segments.transport,'request') as request:
    with self.assertRaises(audio_store.AudioError) as failed:self.process(ident,key,info)
    self.assertEqual(failed.exception.code,'no_speech');request.assert_not_called()
   self.assertEqual(sessions.result(self.user,ident,key)['error_code'],'no_speech')

if __name__=='__main__':unittest.main()
