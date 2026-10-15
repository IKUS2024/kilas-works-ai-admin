"""Session-only Live output; no paid requests and no historical content purge."""
import math
import unittest
from unittest.mock import patch
import test_kilas_audio as audio
import test_kilas_live_translator as base
import test_kilas_live_translator_whole as whole
from test_kilas_audio_history import AudioHistoryTests
from kilas_ai import live_translator as live,live_translator_store as sessions
from kilas_ai import live_translator_output as temporary,live_translator_segments as segments


class SessionOutputTests(unittest.TestCase):
    setUp=base.LiveTranslatorTests.setUp
    funded=base.LiveTranslatorTests.funded
    on=base.LiveTranslatorTests.on
    credit=base.LiveTranslatorTests.credit
    session=base.LiveTranslatorTests.session
    key=base.LiveTranslatorTests.key
    context=whole.WholeTests.context
    response=whole.WholeTests.response
    process=whole.WholeTests.process
    path=whole.WholeTests.path

    @classmethod
    def setUpClass(cls):cls.raw=audio.mp3(1.4)

    def complete(self,ident,key,text='Complete first sentence. Complete final sentence.'):
        info=sessions.claim(self.user,ident,key)
        def chunks():
            row=audio.f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE user_id=? ORDER BY id DESC LIMIT 1',(self.user,))
            self.assertEqual(row['content_origin'],'live_session')
            for field in ('script','original_script','source_content','result_content'):self.assertIsNone(row[field])
            yield self.raw
        response=self.response(chunks)
        with self.context(text),patch.object(segments.transport,'request',return_value=response) as request:
            job=self.process(ident,key,info)
        request.assert_called_once()
        return job

    def test_complete_text_audio_and_charge_exist_only_in_active_session(self):
        self.credit(300);ident=self.session();key=self.key();job=self.complete(ident,key)
        body=self.client.get(self.path(ident,key)).json
        self.assertEqual(body['status'],'COMPLETED')
        self.assertTrue(body['translated_text'].endswith('final sentence.'))
        result=self.client.get(body['audio_url']);self.assertEqual(result.data,self.raw)
        self.assertEqual(result.headers['Cache-Control'],'private, no-store')
        row=audio.f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE id=?',(job,))
        for field in ('script','original_script','source_content','result_content'):self.assertIsNone(row[field])
        self.assertEqual(row['seconds_charged'],math.ceil(row['actual_ms']/1000))
        self.assertGreater(row['initial_reserved_seconds'],0)
        self.assertEqual(audio.store.history(self.user),[])
        for suffix in ('','/result','/script'):
            self.assertEqual(self.client.get('/kilas-translator/jobs/'+str(job)+suffix).status_code,404)
        sessions.end(self.user,ident)
        self.assertIsNone(temporary.get(self.user,ident,key))
        self.assertEqual(self.client.get(body['audio_url']).status_code,404)
        self.assertEqual(audio.f.db.query_one('SELECT seconds_charged FROM kilas_audio_jobs WHERE id=?',(job,))['seconds_charged'],row['seconds_charged'])

    def test_expiry_and_worker_loss_fail_closed_without_paid_regeneration(self):
        self.credit(300);ident=self.session();key=self.key();job=self.complete(ident,key)
        expires=temporary.get(self.user,ident,key)['expires']
        with patch.object(temporary,'monotonic',return_value=expires+1),patch.object(segments.transport,'request') as paid:
            body=self.client.get(self.path(ident,key)).json
            self.assertEqual(body['code'],'session_output_expired')
            self.assertEqual(self.client.get(self.path(ident,key)+'/audio').status_code,404)
            self.assertEqual(self.client.get(self.path(ident,key)).json['status'],'FAILED')
            paid.assert_not_called()
        self.assertEqual(audio.store.get(self.user,job)['status'],'COMPLETED')

    def test_next_turn_discards_prior_output_without_touching_other_sessions(self):
        self.credit(300);ident=self.session();first=self.key();self.complete(ident,first)
        temporary.begin(self.other,'other-session','other-turn')
        self.addCleanup(temporary.discard,self.other,'other-session')
        second=self.key(2);self.complete(ident,second)
        self.assertIsNone(temporary.get(self.user,ident,first))
        self.assertIsNotNone(temporary.get(self.user,ident,second))
        self.assertIsNotNone(temporary.get(self.other,'other-session','other-turn'))
        sessions.end(self.user,ident)
        self.assertIsNotNone(temporary.get(self.other,'other-session','other-turn'))

    def test_unavailable_process_storage_stops_before_any_provider_dispatch(self):
        self.credit(300);ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key)
        with self.context('A complete sentence.'),patch.dict('os.environ',{'WEB_CONCURRENCY':'2'}),patch.object(segments.transport,'request') as paid,patch.object(live,'translation') as translate:
            with self.assertRaises(audio.store.AudioError) as error:self.process(ident,key,info)
        self.assertEqual(error.exception.code,'session_storage_unavailable')
        paid.assert_not_called();translate.assert_not_called()

    def test_temporary_capacity_failure_is_before_paid_work(self):
        self.credit(300);ident=self.session();key=self.key()
        with self.context('Complete text.'),patch.object(temporary,'MAX_ENTRIES',0),patch.object(segments.transport,'request') as paid,patch.object(live,'translation') as translate:
            with self.assertRaises(audio.store.AudioError) as error:sessions.claim(self.user,ident,key)
        self.assertEqual(error.exception.code,'session_storage_busy')
        paid.assert_not_called();translate.assert_not_called()

    def test_duplicate_worker_cannot_cancel_or_discard_the_original_turn(self):
        self.credit(300);ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key)
        temporary.activate(self.user,ident,key)
        with self.context('Complete text.'),patch.object(live,'translation') as translate:
            with self.assertRaises(audio.store.AudioError) as error:self.process(ident,key,info)
        self.assertEqual(error.exception.code,'duplicate_turn');translate.assert_not_called()
        self.assertEqual(sessions.result(self.user,ident,key)['status'],'PROCESSING')
        self.assertIsNotNone(temporary.get(self.user,ident,key))

    def test_failed_live_output_keeps_the_same_conservative_audio_allowance(self):
        self.credit(300);ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key)
        text='Complete first sentence. Complete final sentence.'
        expected=live.audio_service.estimate(text)[1]
        with self.context(text),patch.object(segments,'speech',side_effect=live.audio_provider.ProviderError('provider_timeout')):
            with self.assertRaises(live.audio_provider.ProviderError):self.process(ident,key,info)
        row=audio.f.db.query_one('SELECT status,initial_reserved_seconds,original_script FROM kilas_audio_jobs WHERE user_id=?',(self.user,))
        self.assertEqual(row['status'],'FAILED');self.assertEqual(row['initial_reserved_seconds'],expected);self.assertIsNone(row['original_script'])
        with patch.object(live.free_test,'eligible',return_value=False),patch.dict('os.environ',{'KILAS_LIVE_TRANSLATOR_AUDIO_SECONDS':str(expected)}):
            live.require_audio_allowance(self.user,0)
            with self.assertRaises(audio.store.AudioError) as error:live.require_audio_allowance(self.user,1)
            self.assertEqual(error.exception.code,'live_audio_limit')

    def test_segmented_compatibility_keeps_all_bytes_in_ram_and_same_settlement(self):
        self.credit(300);ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key)
        text=('This first sentence preserves the complete meaning and every important detail without abbreviation. '
              'This final sentence also remains complete and is delivered in full before the utterance finishes.')
        def speech(*args,**kwargs):
            row=audio.f.db.query_one('SELECT script,original_script,source_content,result_content FROM kilas_audio_jobs WHERE user_id=?',(self.user,))
            for name in row.keys():self.assertIsNone(row[name])
            return self.raw
        with self.context(text),patch.object(segments,'speech',side_effect=speech) as paid:
            job=live.process(self.user,ident,key,None,info,committed_text='Complete source.',stream_output=True)
        self.assertGreater(paid.call_count,1)
        body=self.client.get(self.path(ident,key)).json
        self.assertEqual(body['status'],'COMPLETED');self.assertEqual(body['translated_text'],text)
        self.assertEqual(len(body['segments']),paid.call_count)
        for part in body['segments']:self.assertEqual(self.client.get(part['audio_url']).data,self.raw)
        self.assertEqual(self.client.get(body['audio_url']).status_code,200)
        row=audio.f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE id=?',(job,))
        for name in ('script','original_script','source_content','result_content'):self.assertIsNone(row[name])
        self.assertEqual(row['seconds_charged'],math.ceil(row['actual_ms']/1000))


class HistorySeparationTests(unittest.TestCase):
    setUp=audio.AudioTests.setUp
    seed=AudioHistoryTests.seed

    def test_mixed_legacy_new_and_title_collision_are_reversibly_filtered(self):
        voice=self.seed(5)
        audio.f.db.execute("UPDATE kilas_audio_jobs SET title='Live Translator',operation_key='live-not-a-real-turn-audio' WHERE id=?",(voice[0],))
        old=self.seed(1)[0];ident=sessions.create(self.user,'id','en','kilas-male')
        self.addCleanup(sessions.end,self.user,ident)
        key='live-'+str(self.user).zfill(32);sessions.claim(self.user,ident,key)
        audio.f.db.execute("UPDATE kilas_audio_jobs SET operation_key=?,title='Different title',original_script='Legacy source',result_content=? WHERE id=?",(key+'-audio',b'legacy-file-kept',old))
        sessions.finish(self.user,ident,key,True,old)
        marker=self.seed(1)[0]
        audio.f.db.execute("UPDATE kilas_audio_jobs SET content_origin='live_session',original_script=NULL WHERE id=?",(marker,))
        upload=self.seed(1)[0];audio.f.db.execute("UPDATE kilas_audio_jobs SET mode='translate' WHERE id=?",(upload,))
        count=audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs WHERE user_id=?',(self.user,))['n']
        first=audio.store.history_page(self.user);second=audio.store.history_page(self.user,2)
        self.assertEqual((first['history_total'],first['history_page_count'],len(first['history']),len(second['history'])),(5,2,4,1))
        self.assertEqual({row['id'] for row in first['history']+second['history']},set(voice))
        self.assertEqual(audio.store.history_page(self.user,kind='translate')['history'][0]['id'],upload)
        self.assertEqual(self.client.get('/kilas-translator/jobs/'+str(old)).status_code,404)
        self.assertEqual(self.client.get('/kilas-translator/jobs/'+str(voice[0])).status_code,200)
        row=audio.f.db.query_one('SELECT original_script,result_content FROM kilas_audio_jobs WHERE id=?',(old,))
        self.assertEqual(row['original_script'],'Legacy source');self.assertEqual(bytes(row['result_content']),b'legacy-file-kept')
        self.assertEqual(audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs WHERE user_id=?',(self.user,))['n'],count)


if __name__=='__main__':unittest.main()
