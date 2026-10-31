"""Dependability contracts on real routes/SQLite; no paid providers or fake confidence."""
import io,json,time,threading,unittest,uuid
from unittest.mock import patch
from werkzeug.datastructures import FileStorage
from werkzeug.serving import make_server
import requests
import test_kilas_copilot as fixture
from kilas_ai import copilot,copilot_jobs,providers


class DependabilityTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.CopilotTests();self.case.setUp();self.case.premium()
        self.client=self.case.client;self.owner=self.case.owner;self.ident=self.case.ident

    def submit(self,key=None,**options):
        return self.client.post(f'/kilas-ai/copilot/sessions/{self.ident}/{key or self.case.key}/process',data={'audio':(io.BytesIO(fixture.recording()),'recording.wav','audio/wav'),'consent':'yes','csrf_token':'copilot-csrf',**options})

    def failed_translation(self):
        with patch.object(copilot,'configured',return_value=True),patch.object(copilot,'transcribe',return_value='Where did you study?'),patch.object(copilot,'text_stream',side_effect=[fixture.answer('I studied at … (fill in yourself).'),fixture.answer('{bad json')]):
            return fixture.await_operation(self.client,self.submit(translate='yes',target='id')).json

    def test_primary_survives_translation_failure_and_recovery_does_not_regenerate_it(self):
        view=self.failed_translation();self.assertEqual(view['state'],'complete')
        turn=view['result']['turn'];self.assertEqual(turn['translation_error'],'incomplete_translation')
        self.assertEqual(len(copilot.turns(self.owner,self.ident)),1)
        self.assertEqual(view['primary']['reply'],turn['reply'])
        retry=uuid.uuid4().hex;url=f'/kilas-ai/copilot/sessions/{self.ident}/{self.case.key}/translation/{retry}'
        output=json.dumps({'source_translation':'Sekolah di mana?','reply_translation':'Saya bersekolah di … (isi sendiri).'})
        with patch.object(copilot,'configured',return_value=True),patch.object(copilot,'transcribe',side_effect=AssertionError('STT retry forbidden')),patch.object(copilot,'text_stream',side_effect=lambda *a,**k:fixture.answer(output)) as provider:
            response=self.client.post(url,data={'csrf_token':'copilot-csrf'});self.assertEqual(response.status_code,202)
            result=fixture.await_operation(self.client,response).json
            self.assertEqual(result['state'],'complete');self.assertEqual(provider.call_count,1)
            self.assertEqual(json.loads(provider.call_args.args[1]),{'source':turn['source'],'reply':turn['reply']})
            self.assertEqual(self.client.post(url,data={'csrf_token':'copilot-csrf'}).status_code,400)
            self.assertEqual(provider.call_count,1)
        saved=copilot.turns(self.owner,self.ident);self.assertEqual(len(saved),1)
        self.assertEqual(saved[0]['id'],turn['id']);self.assertEqual(saved[0]['reply'],turn['reply'])
        self.assertEqual(saved[0]['translation_status'],'complete')

    def test_recovery_owner_csrf_and_duplicate_fences(self):
        self.failed_translation();other=self.case.client_for(self.case.other);key=uuid.uuid4().hex
        path=f'/kilas-ai/copilot/sessions/{self.ident}/{self.case.key}/translation/{key}'
        self.assertEqual(other.post(path,data={'csrf_token':'copilot-csrf'}).status_code,404)
        self.assertEqual(self.client.post(path).status_code,400)
        entered=threading.Event();release=threading.Event()
        def provider(*a,**k):entered.set();release.wait(3);yield from fixture.answer('{}')
        with patch.object(copilot,'configured',return_value=True),patch.object(copilot,'text_stream',side_effect=provider):
            accepted=self.client.post(path,data={'csrf_token':'copilot-csrf'});self.assertEqual(accepted.status_code,202)
            self.assertTrue(entered.wait(2))
            self.assertEqual(other.get(accepted.json['status_url']).status_code,404)
            self.assertEqual(self.client.post(path,data={'csrf_token':'copilot-csrf'}).status_code,409)
            release.set();fixture.await_operation(self.client,accepted)

    def test_single_sync_http_worker_stays_responsive_while_provider_is_waiting(self):
        entered=threading.Event();release=threading.Event()
        def stt(_):entered.set();release.wait(4);return 'Thanks.'
        server=make_server('127.0.0.1',0,self.case.app,threaded=False)
        threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
        cookie=self.client.get_cookie('session')
        try:
            with patch.object(copilot,'configured',return_value=True),patch.object(copilot,'transcribe',side_effect=stt),patch.object(copilot,'text_stream',side_effect=AssertionError('Canceled before reply')):
                response=requests.post(origin+f'/kilas-ai/copilot/sessions/{self.ident}/{self.case.key}/process',cookies={cookie.key:cookie.value},data={'csrf_token':'copilot-csrf','consent':'yes'},files={'audio':('recording.wav',fixture.recording(),'audio/wav')},timeout=2)
                self.assertEqual(response.status_code,202);self.assertTrue(entered.wait(2))
                start=time.monotonic();health=requests.get(origin+'/healthz',timeout=1)
                self.assertEqual(health.status_code,200);self.assertLess(time.monotonic()-start,1)
                status=requests.get(origin+response.json()['status_url'],cookies={cookie.key:cookie.value},timeout=1)
                self.assertEqual(status.json()['state'],'processing')
                stopped=requests.post(origin+f'/kilas-ai/copilot/sessions/{self.ident}/{self.case.key}/cancel',cookies={cookie.key:cookie.value},data={'csrf_token':'copilot-csrf'},timeout=1)
                self.assertEqual(stopped.status_code,200);release.set()
                deadline=time.monotonic()+2
                while time.monotonic()<deadline:
                    final=requests.get(origin+response.json()['status_url'],cookies={cookie.key:cookie.value},timeout=1)
                    if final.json()['state']!='processing':break
                    time.sleep(.01)
                self.assertEqual(final.json()['state'],'failed')
        finally:release.set();server.shutdown()
        self.assertEqual(copilot.turns(self.owner,self.ident),[])

    def test_context_keeps_older_evidence_and_latest_tail_correction_without_claiming_ownership(self):
        prior=[{'source':'You told me your school is SMA Nusantara.','reply':'suggestion'}]+[{'source':'turn '+str(i),'reply':'suggestion'} for i in range(8)]
        context=copilot.reply_context('Where did I study?',prior)
        self.assertIn('SMA Nusantara',context);self.assertIn('heard_other_or_unattributed_speaker',context)
        long='x'*3500+' Correction: your appointment is Monday, not Friday.'
        context=copilot.reply_context('Which day?', [{'source':long,'reply':'I can go Friday.'}])
        self.assertIn('Monday',context);self.assertIn('heard_truncated',context)
        capped=copilot.reply_context('界'*4000,[{'source':long,'reply':'suggestion'}]*20,at_limit=True)
        self.assertLessEqual(len(capped.encode('utf-8')),24000);self.assertTrue(json.loads(capped)['recording_quality']['duration_limit_reached'])
        for phrase in ('Their I/my/saya/aku refers to them','not the human listener','Latest explicit corrections win'):
            self.assertIn(phrase,copilot.SYSTEM)

    def test_preferences_survive_reload_independent_of_app_locale_and_are_owned(self):
        path=f'/kilas-ai/copilot/sessions/{self.ident}/preferences'
        data={'csrf_token':'copilot-csrf','style':'profesional','target':'ja','translate':'yes'}
        self.assertEqual(self.client.post(path,data=data).status_code,200)
        self.client.set_cookie('kilas_language','en');page=self.client.get(f'/kilas-ai/copilot/sessions/{self.ident}').text
        self.assertIn('id="copilot-style" type="hidden" value="profesional"',page)
        self.assertIn('<option value="ja" selected>',page);self.assertIn('type="checkbox" checked',page)
        self.assertEqual(self.case.client_for(self.case.other).post(path,data=data).status_code,404)
        self.assertEqual(self.client.post(path,data={**data,'target':'invalid'}).status_code,400)
        self.assertEqual(copilot.preferences(self.owner,self.ident)['target'],'ja')

    def test_heavily_clipped_audio_is_rejected_before_billing_but_quiet_speech_is_retained(self):
        raw=bytearray(fixture.recording());raw[44:]=b'\xff\x7f'*16000
        with self.assertRaisesRegex(copilot.CopilotError,'clipped_audio'):
            copilot.audio(FileStorage(stream=io.BytesIO(raw),filename='clipped.wav',content_type='audio/wav'))
        self.assertFalse(copilot.audio(FileStorage(stream=io.BytesIO(fixture.recording()),filename='recording.wav',content_type='audio/wav'))[1])
        with patch.object(copilot.usage,'reserve') as reserve,patch.object(copilot,'transcribe') as stt:
            response=self.client.post(f'/kilas-ai/copilot/sessions/{self.ident}/{self.case.key}/process',data={'audio':(io.BytesIO(raw),'clipped.wav','audio/wav'),'consent':'yes','csrf_token':'copilot-csrf'})
            self.assertEqual(response.status_code,422);self.assertEqual(response.json['code'],'clipped_audio');reserve.assert_not_called();stt.assert_not_called()

    def test_one_query_status_and_throttled_checks_preserve_forced_cancellation(self):
        copilot.claim(self.owner,self.ident,self.case.key,'synthetic')
        with patch.object(fixture.db,'query_one',wraps=fixture.db.query_one) as query:
            self.assertTrue(copilot.active(self.owner,self.ident,self.case.key));self.assertEqual(query.call_count,1)
        with patch.object(copilot,'active',return_value=True) as active:
            control=copilot.TurnControl(self.owner,self.ident,self.case.key)
            for _ in range(100):control.check()
            self.assertEqual(active.call_count,1)
            control.deadline=time.monotonic()-1
            with self.assertRaisesRegex(copilot.ControlError,'processing_timeout'):control.check()
        control=copilot.TurnControl(self.owner,self.ident,self.case.key,lambda:True)
        with self.assertRaisesRegex(copilot.ControlError,'cancelled'):control.check()

    def test_transport_deadline_observes_comment_or_unterminated_trickle_and_closes_response(self):
        class Guard:
            count=0
            def check(self,force=False):
                self.count+=1
                if self.count>6:raise copilot.ControlError('processing_timeout')
            def timeout(self,*a):return (.1,.1)
        class Response:
            closed=False
            encoding='utf-8'
            def __enter__(self):return self
            def __exit__(self,*args):self.closed=True
            def raise_for_status(self):pass
            def iter_content(self,chunk_size):yield from [b':',b'h',b'e',b'a',b'r',b't',b'b',b'e',b'a',b't']
        response=Response()
        with patch.object(providers.requests,'post',return_value=response) as post:
            with self.assertRaisesRegex(copilot.ControlError,'processing_timeout'):
                list(providers._openai('gpt-6-luna','synthetic-key',[],'SMART',profile={'output_tokens':1024,'effort':'low'},stream_guard=Guard()))
        self.assertTrue(response.closed);self.assertEqual(post.call_args.kwargs['timeout'],(.1,.1))

    def test_completed_primary_and_accounting_are_recoverable_after_registry_expiry(self):
        view=self.failed_translation();url=f'/kilas-ai/copilot/sessions/{self.ident}/{self.case.key}/status'
        with copilot_jobs._lock:copilot_jobs._jobs.pop((self.owner,self.ident,self.case.key),None)
        restored=self.client.get(url);self.assertEqual(restored.json['result']['turn']['reply'],view['result']['turn']['reply'])
        row=fixture.db.query_one('SELECT status,input_tokens,output_tokens,estimated_cost_usd FROM kilas_ai_usage WHERE user_id=? AND operation_key=?',(self.owner,copilot.key(self.case.key)))
        self.assertEqual(row['status'],'COMPLETE');self.assertEqual(row['input_tokens'],200);self.assertEqual(row['output_tokens'],40)
        self.assertEqual(float(row['estimated_cost_usd']),.18)

    def test_cancel_during_translation_preserves_primary_and_never_recaptures(self):
        entered=threading.Event();release=threading.Event()
        def provider(system,content,**options):
            if system.startswith('Translate'):
                entered.set();release.wait(3)
                yield from fixture.answer('{}')
            else:yield from fixture.answer('I studied at … (fill in yourself).')
        with patch.object(copilot,'configured',return_value=True),patch.object(copilot,'transcribe',return_value='Where did you study?') as stt,patch.object(copilot,'text_stream',side_effect=provider):
            accepted=self.submit(translate='yes',target='id');self.assertTrue(entered.wait(2))
            self.assertEqual(len(copilot.turns(self.owner,self.ident)),1)
            canceled=self.client.post(f'/kilas-ai/copilot/sessions/{self.ident}/{self.case.key}/cancel',data={'csrf_token':'copilot-csrf'})
            self.assertEqual(canceled.status_code,200);release.set();result=fixture.await_operation(self.client,accepted).json
            self.assertEqual(result['state'],'complete');self.assertEqual(stt.call_count,1)
            self.assertEqual(copilot.turns(self.owner,self.ident)[0]['translation_status'],'cancelled')

    def test_restart_recovers_primary_and_does_not_replay_audio_or_lock_next_action(self):
        copilot.claim(self.owner,self.ident,self.case.key,'synthetic')
        copilot.update(self.owner,self.ident,self.case.key,'primary_complete','Saved reply',source='Heard source',target='en',style='santai',translation_status='pending',worker_id='retired-worker')
        with patch.object(copilot,'transcribe',side_effect=AssertionError('No audio replay')):
            response=self.client.get(f'/kilas-ai/copilot/sessions/{self.ident}/{self.case.key}/status')
        self.assertEqual(response.json['state'],'complete');self.assertEqual(response.json['result']['turn']['reply'],'Saved reply')
        self.assertEqual(response.json['result']['turn']['translation_error'],'interrupted_operation')
        self.assertEqual(copilot.turns(self.owner,self.ident)[0]['translation_status'],'failed')
        copilot.claim(self.owner,self.ident,uuid.uuid4().hex,'new-explicit-action')

if __name__=='__main__':unittest.main()
