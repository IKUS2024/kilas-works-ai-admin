"""Offline real codec/ledger tests, synthetic providers; no browser or paid requests."""
import io
import json
import math
import os
import unittest
from contextlib import ExitStack
from unittest.mock import patch,Mock
import test_kilas_audio as audio
import test_kilas_live_translator as fixture
from kilas_ai import live_translator_segments as segments
from kilas_ai import live_translator as live,live_translator_store as sessions,audio_store as store,audio_service as service,usage


class SegmentTests(unittest.TestCase):
    setUp=fixture.LiveTranslatorTests.setUp
    credit=fixture.LiveTranslatorTests.credit
    session=fixture.LiveTranslatorTests.session
    claim=fixture.LiveTranslatorTests.claim
    key=fixture.LiveTranslatorTests.key
    on=fixture.LiveTranslatorTests.on
    funded=fixture.LiveTranslatorTests.funded
    signal=fixture.LiveTranslatorTests.signal
    transcribe=fixture.LiveTranslatorTests.transcribe
    @classmethod
    def setUpClass(cls):cls.audio=audio.mp3(.6);cls.long=audio.mp3(2.4)

    def manual(self,total=2,ceiling=30):
        self.credit(300);ident=self.session();key=self.key();self.claim(ident,key)
        text=' '.join('This is committed sentence number '+str(i)+' with enough stable context to speak clearly.' for i in range(total))
        job,_=store.create(self.user,key+'-audio','voiceover','Live Translator','id','en','syntheticMale123','Kilas Male',text,0,None,5,ceiling,original_script=text)
        segments.attach(self.user,ident,key,job,total,ceiling)
        return ident,key,job

    def row(self,job):return audio.f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE id=?',(job,))
    def url(self,ident,key,index=None):return '/kilas-translator/live/sessions/'+ident+'/turns/'+key+('/audio/segments/'+str(index) if index is not None else '')
    def committed(self,ident,key,job,index=0):
        segments.dispatch(self.user,ident,key,job,index);segments.commit_clip(self.user,job,index,self.audio)

    def test_sentence_boundaries_preserve_short_multilingual_abbreviations_and_tail(self):
        for text in ('Hi. Bye.','Hallo! Apa kabar?','你好。今天很好！再见。','مرحبا؟ كيف حالك؟','Dr. Smith is here. Mr. Jones follows.','The value is 3.14. This is stable.','A. Smith speaks. Another sentence.','Unpunctuated text '*180):
            with self.subTest(text=text[:25]):
                parts=segments.sentences(text);self.assertEqual(''.join(parts),text);self.assertTrue(1<=len(parts)<=8)
        self.assertEqual(segments.sentences('Hi. Bye.'),['Hi. ','Bye.'])
        self.assertEqual(len(segments.sentences('Dr. Smith is here. Mr. Jones follows.')),2)
        self.assertEqual(len(segments.sentences('Unpunctuated text '*180)),1)
        text=''.join('This is a complete committed sentence number '+str(i)+'. ' for i in range(40))
        self.assertEqual(len(segments.sentences(text)),8);self.assertEqual(''.join(segments.sentences(text)),text)

    def test_invalid_text_and_manifest_reject_boolean_types_offsets_and_duration(self):
        for text in ('',None,'x'*4001):
            with self.assertRaises(store.AudioError):segments.sentences(text)
        valid={'version':1,'total':2,'ceiling_ms':30000,'dispatched':1,'clips':[{'offset':14,'bytes':10,'ms':600}]}
        for changes in ({'version':True},{'total':True},{'dispatched':3},{'ceiling_ms':True},{'clips':[{'offset':15,'bytes':10,'ms':600}]},{'clips':[{'offset':14,'bytes':-1,'ms':600}]},{'clips':[{'offset':14,'bytes':10,'ms':True}]},{'clips':[{'offset':14,'bytes':10,'ms':30001}]}):
            with self.subTest(changes=changes),self.assertRaises(store.AudioError):segments.manifest(segments.PREFIX+json.dumps({**valid,**changes}))

    def test_cumulative_rounding_single_job_durable_dispatch_and_completed_download(self):
        ident,key,job=self.manual(total=3)
        segments.dispatch(self.user,ident,key,job,0)
        before=self.row(job);self.assertEqual(segments.manifest(before['provider_id'])['dispatched'],1);self.assertEqual(before['seconds_charged'],0)
        segments.commit_clip(self.user,job,0,self.audio)
        first=self.row(job);self.assertEqual(first['actual_ms'],600);self.assertEqual(first['seconds_charged'],1);self.assertEqual(first['reserved_seconds'],29)
        self.committed(ident,key,job,1);self.committed(ident,key,job,2);self.assertEqual(self.row(job)['seconds_charged'],2);segments.complete(self.user,job)
        final=self.row(job);self.assertEqual(final['seconds_charged'],math.ceil(final['actual_ms']/1000));self.assertEqual(final['seconds_charged'],2)
        self.assertGreaterEqual(final['actual_ms'],1800);self.assertGreaterEqual(final['actual_ms'],audio.media.mp3_duration(bytes(final['result_content'])))
        self.assertEqual(final['reserved_seconds'],0);self.assertEqual(final['status'],'COMPLETED');self.assertEqual(store.balance(self.user)['seconds'],298)
        sessions.finish(self.user,ident,key,True,job)
        self.assertEqual(self.client.get(self.url(ident,key,1)).data,self.audio)
        self.assertEqual(self.client.get(self.url(ident,key)+'/audio').status_code,404)  # Legacy archived bytes are retained but not offered as a saved Live result.
        self.assertEqual(self.client.get(self.url(ident,key)).json['audio_url'],self.url(ident,key)+'/audio')
        with self.assertRaises(store.AudioError):segments.complete(self.user,job)
        self.assertEqual(store.balance(self.user)['seconds'],298)
        with self.assertRaises(store.AudioError):segments.dispatch(self.user,ident,key,job,3)

    def test_long_clip_above_twenty_megabyte_decoded_pcm_still_joins_at_44100(self):
        ident,key,job=self.manual(ceiling=280)
        raw=audio.mp3(245);segments.dispatch(self.user,ident,key,job,0);segments.commit_clip(self.user,job,0,raw)
        self.committed(ident,key,job,1);segments.complete(self.user,job)
        row=self.row(job);self.assertEqual(row['status'],'COMPLETED');self.assertGreaterEqual(row['actual_ms'],245600)
        self.assertGreaterEqual(row['actual_ms'],audio.media.mp3_duration(bytes(row['result_content'])))
        self.assertEqual(row['seconds_charged'],math.ceil(row['actual_ms']/1000))

    def test_first_clip_is_private_and_visible_while_later_provider_audio_not_finished(self):
        ident,key,job=self.manual();self.committed(ident,key,job)
        response=self.client.get(self.url(ident,key));self.assertEqual(response.json['status'],'PROCESSING');self.assertEqual(len(response.json['segments']),1);self.assertNotIn('audio_url',response.json)
        sample=self.client.get(self.url(ident,key,0));self.assertEqual(sample.status_code,200);self.assertEqual(sample.data,self.audio);self.assertEqual(sample.headers['Cache-Control'],'private, no-store')
        self.assertEqual(self.client.get(self.url(ident,key,1)).status_code,404)
        self.assertEqual(self.client.get(self.url(ident,key)+'/audio').status_code,404)
        from auth_test_helpers import authenticate
        authenticate(self.client,__import__('repo').get_user_by_id(self.other),_csrf_token='audio-csrf')
        self.assertEqual(self.client.get(self.url(ident,key,0)).status_code,404)

    def test_cancel_after_paid_clip_keeps_charge_releases_tail_and_blocks_further_dispatch(self):
        ident,key,job=self.manual();self.committed(ident,key,job);sessions.cancel_turn(self.user,ident,key)
        with self.assertRaises(store.AudioError):segments.dispatch(self.user,ident,key,job,1)
        store.fail(self.user,job,'turn_cancelled');row=self.row(job)
        self.assertEqual(row['seconds_charged'],1);self.assertEqual(row['actual_ms'],600);self.assertEqual(row['reserved_seconds'],0)
        self.assertEqual(segments.manifest(row['provider_id'])['dispatched'],1);self.assertEqual(store.balance(self.user)['seconds'],299)
        self.assertEqual(self.client.get(self.url(ident,key,0)).status_code,404)
        self.assertNotIn('segments',self.client.get(self.url(ident,key)).json)

    def test_end_after_dispatch_and_valid_response_commit_records_cost_but_hides_audio(self):
        ident,key,job=self.manual();segments.dispatch(self.user,ident,key,job,0);sessions.end(self.user,ident)
        segments.commit_clip(self.user,job,0,self.audio);store.fail(self.user,job,'session_ended')
        self.assertEqual(self.row(job)['seconds_charged'],1);self.assertEqual(self.client.get(self.url(ident,key,0)).status_code,404)
        self.assertEqual(self.client.get(self.url(ident,key)).json,{'status':'CANCELLED'})

    def test_ambiguous_paid_dispatch_preserves_unknown_marker_without_charge_or_retry(self):
        ident,key,job=self.manual();segments.dispatch(self.user,ident,key,job,0);store.fail(self.user,job,'provider_transport')
        self.assertEqual(self.row(job)['seconds_charged'],0);self.assertEqual(self.row(job)['reserved_seconds'],0)
        self.assertEqual(segments.manifest(self.row(job)['provider_id'])['dispatched'],1)
        with self.assertRaises(store.AudioError):segments.dispatch(self.user,ident,key,job,0)
        with patch.dict(os.environ,{'KILAS_LIVE_TRANSLATOR_AUDIO_SECONDS':'1'}),self.assertRaises(store.AudioError):live.require_audio_allowance(self.user)

    def test_duplicate_out_of_order_and_wrong_measured_duration_do_not_debit_twice(self):
        ident,key,job=self.manual();self.committed(ident,key,job)
        for action in (lambda:segments.dispatch(self.user,ident,key,job,0),lambda:segments.commit_clip(self.user,job,0,self.audio),lambda:segments.commit_clip(self.user,job,1,self.audio,1)):
            with self.assertRaises(store.AudioError):action()
        self.assertEqual(self.row(job)['seconds_charged'],1);self.assertEqual(store.balance(self.user)['seconds'],299)

    def test_corrupted_framed_blob_never_reads_or_completes(self):
        ident,key,job=self.manual();self.committed(ident,key,job)
        audio.f.db.execute('UPDATE kilas_audio_jobs SET source_content=? WHERE id=?',(b'KWSEG1\0',job))
        self.assertEqual(self.client.get(self.url(ident,key,0)).status_code,503)
        with self.assertRaises(store.AudioError):segments.complete(self.user,job)

    def test_aggregate_byte_limit_rejects_before_debit_and_leaves_dispatch_marker(self):
        ident,key,job=self.manual();segments.dispatch(self.user,ident,key,job,0)
        with patch.object(segments,'MAX_BYTES',100),self.assertRaises(store.AudioError):segments.commit_clip(self.user,job,0,self.audio)
        self.assertEqual(self.row(job)['seconds_charged'],0);self.assertEqual(segments.manifest(self.row(job)['provider_id'])['dispatched'],1)

    def test_exempt_owner_still_has_original_finite_admitted_audio_ceiling(self):
        with patch.object(usage,'_qa_quota_exempt',return_value=True):
            ident,key,job=self.manual(ceiling=1);self.assertEqual(self.row(job)['reserved_seconds'],0)
            segments.dispatch(self.user,ident,key,job,0)
            with self.assertRaises(store.AudioError) as error:segments.commit_clip(self.user,job,0,self.long)
            self.assertEqual(error.exception.code,'output_exceeds_reservation');self.assertEqual(self.row(job)['seconds_charged'],0)
            store.fail(self.user,job,error.exception.code);self.assertEqual(segments.manifest(self.row(job)['provider_id'])['dispatched'],1)
            self.assertEqual(self.client.get(self.url(ident,key,0)).status_code,404)

    def test_progress_rechecks_cancel_after_manifest_query(self):
        ident,key,job=self.manual();self.committed(ident,key,job);state=sessions.result(self.user,ident,key)
        with patch.object(sessions,'result',return_value={'status':'CANCELLED'}):self.assertIsNone(segments.progress(self.user,ident,key,state))

    def test_clip_rechecks_end_after_blob_query(self):
        ident,key,job=self.manual();self.committed(ident,key,job);state=sessions.result(self.user,ident,key)
        with patch.object(sessions,'result',side_effect=[state,{'status':'CANCELLED'}]),self.assertRaises(store.AudioError):segments.clip(self.user,ident,key,0)

    def context(self,text):
        stack=ExitStack();stack.enter_context(self.funded());stack.enter_context(self.on());stack.enter_context(patch.object(fixture.branded,'resolve',return_value=fixture.VOICE));stack.enter_context(patch.object(live.stt,'transcribe',side_effect=self.transcribe))
        events=[{'type':'delta','text':json.dumps({'text':text,'source_language':'id','target_language':'en'})},{'type':'finish','reason':'stop'}]
        stack.enter_context(patch.object(live.providers,'_openai',return_value=(event for event in events)));return stack

    def test_real_process_publishes_before_second_synthetic_tts_then_settles_once(self):
        self.credit(300);ident=self.session();key=self.key();info=self.claim(ident,key);seen=[];timings={}
        def speech(text,voice,check,on_first_byte,**context):
            check();on_first_byte();seen.append(text)
            if len(seen)==2:
                response=self.client.get(self.url(ident,key));self.assertEqual(response.json['status'],'PROCESSING');self.assertEqual(len(response.json['segments']),1);self.assertEqual(self.client.get(self.url(ident,key,0)).data,self.audio)
            return self.audio
        with self.context('Hello. How are you?'),patch.object(segments,'speech',side_effect=speech),patch.object(live.audio_provider,'speech') as ordinary:
            job=live.process(self.user,ident,key,self.signal(),info,stream_output=True,timings=timings);ordinary.assert_not_called()
        self.assertEqual(seen,['Hello.','How are you?']);self.assertEqual(self.row(job)['seconds_charged'],2);self.assertEqual(sessions.result(self.user,ident,key)['status'],'COMPLETED')
        self.assertIn('first_tts_byte_ms',timings);self.assertIn('first_published_clip_ms',timings);self.assertLessEqual(timings['first_tts_byte_ms'],timings['first_published_clip_ms'])

    def test_short_single_sentence_and_older_client_choose_buffered_before_dispatch(self):
        for negotiated,text in ((True,'Hello.'),(False,'Hello. How are you?')):
            # Separate synthetic owners keep each accounting/admission fixture isolated.
            self.user=audio.f.repo.create_user(self.id()+str(negotiated)+'@example.test','hash');self.credit(300);ident=self.session();key=self.key();info=self.claim(ident,key)
            with self.context(text),patch.object(segments,'speech') as streamed,patch.object(live.audio_provider,'speech',return_value=(self.audio,'synthetic')) as ordinary:
                job=live.process(self.user,ident,key,self.signal(),info,stream_output=negotiated);streamed.assert_not_called();ordinary.assert_called_once()
            self.assertFalse(self.row(job)['provider_id'].startswith(segments.PREFIX))

    def test_real_process_second_stream_failure_preserves_partial_charge_no_fallback(self):
        self.credit(300);ident=self.session();key=self.key();info=self.claim(ident,key)
        with self.context('Hello. How are you?'),patch.object(segments,'speech',side_effect=[self.audio,store.AudioError('Unavailable','stream_unavailable',503)]),patch.object(live.audio_provider,'speech') as ordinary:
            with self.assertRaises(store.AudioError):live.process(self.user,ident,key,self.signal(),info,stream_output=True)
            ordinary.assert_not_called()
        row=audio.f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE user_id=?',(self.user,));self.assertEqual(row['seconds_charged'],1);self.assertEqual(row['reserved_seconds'],0);self.assertEqual(segments.manifest(row['provider_id'])['dispatched'],2)
        self.assertEqual(sessions.result(self.user,ident,key)['status'],'FAILED');self.assertEqual(self.client.get(self.url(ident,key,0)).status_code,404)

    def test_http_adapter_same_model_format_no_retry_and_checks_end_during_read(self):
        response=Mock(status_code=200);response.iter_content.return_value=[b'first',b'second'];context=Mock();context.__enter__=Mock(return_value=response);context.__exit__=Mock(return_value=False)
        first=Mock();check=Mock()
        with patch.object(segments.transport,'request',return_value=context) as request:
            self.assertEqual(segments.speech('Hello',fixture.VOICE['id'],check,first,previous='Earlier',following='Later'),b'firstsecond')
            request.assert_called_once();payload=request.call_args.kwargs;self.assertEqual(payload['json']['model_id'],'eleven_multilingual_v2');self.assertEqual(payload['params']['output_format'],'mp3_44100_128');self.assertNotIn('language_code',payload['json']);self.assertEqual(payload['json']['previous_text'],'Earlier');first.assert_called_once()
        with patch.object(segments.transport,'request',return_value=context) as request,self.assertRaises(store.AudioError):
            segments.speech('Hello',fixture.VOICE['id'],Mock(side_effect=[None,store.AudioError('End','session_ended')]),Mock())
        request.assert_called_once();self.assertTrue(context.__exit__.called)

    def test_http_unsupported_or_transport_ambiguity_never_reposts(self):
        for status in (404,405,402,403):
            response=Mock(status_code=status);context=Mock();context.__enter__=Mock(return_value=response);context.__exit__=Mock(return_value=False)
            with self.subTest(status=status),patch.object(segments.transport,'request',return_value=context) as request,self.assertRaises(store.AudioError):segments.speech('Hello',fixture.VOICE['id'],Mock(),Mock())
            request.assert_called_once()
        with patch.object(segments.transport,'request',side_effect=segments.requests.Timeout()) as request,self.assertRaises(live.audio_provider.ProviderError):segments.speech('Hello',fixture.VOICE['id'],Mock(),Mock())
        request.assert_called_once()

    def test_postgres_segment_blob_writes_are_bounded_and_settlement_atomic(self):
        # SQL contract only, no remote/native PostgreSQL or production data is touched.
        from contextlib import nullcontext
        data={'version':1,'total':2,'ceiling_ms':30000,'dispatched':1,'clips':[]};conn=object()
        def query(c,sql,params=(),one=False):
            self.assertIs(c,conn)
            if sql.startswith('SELECT status'):return ('PROCESSING',segments._encode(data),0,0,30,len(segments.MAGIC),'standard')
            return None
        with patch.object(store,'locked',return_value=nullcontext(conn)),patch.object(usage,'_query',side_effect=query) as statements,patch.object(store,'_balance',return_value=300),patch.object(usage,'_qa_quota_exempt',return_value=False),patch.object(audio.f.db,'BACKEND','postgres'),patch.object(segments.media,'mp3_duration',return_value=600):
            segments.commit_clip(self.user,1,0,b'x'*(1200*1024))
            writes=[call for call in statements.call_args_list if 'source_content=source_content || ?' in call.args[1]]
            self.assertGreater(len(writes),1);self.assertTrue(all(len(call.args[2][0])<=512*1024 for call in writes));self.assertTrue(any('seconds=seconds-?' in call.args[1] for call in statements.call_args_list))


if __name__=='__main__':unittest.main()
