"""Learning release gates. Synthetic media and mocked paid providers only."""
import hashlib
import io
import json
import os
import unittest
from datetime import timedelta
from unittest.mock import patch
import test_kilas_audio as fixture
import test_kilas_audio_video_script as video_fixture
from kilas_ai import learning, learning_store as store, learning_phrases, learning_schema, learning_realtime as realtime
from kilas_ai import audio_store, audio_transcription_budget as budget, usage, providers, model_policy

VOICE={'alias':'kilas-male','id':'syntheticMale123','name':'Kilas Male','style':'Natural'}
db=fixture.f.db


class LearningTests(unittest.TestCase):
    setUp=fixture.AudioTests.setUp
    credit=fixture.AudioTests.credit
    funded=video_fixture.VideoScriptTests.funded

    @classmethod
    def setUpClass(cls):
        cls.audio=fixture.mp3(.4)

    def on(self):
        return patch.dict(os.environ,{'KILAS_LEARNING_ENABLED':'true','OPENAI_API_KEY':'synthetic-only',
               'KILAS_LEARNING_REALTIME_ENABLED':'true','KILAS_LEARNING_REALTIME_BILLING_VERIFIED':'creator-included-scribe-realtime-20261013',
               'KILAS_LEARNING_REALTIME_BUDGET_MICRO_USD':'60000','KILAS_VO_STT_ALLOWED_OWNER_ID':str(self.user),
               'KILAS_LIVE_TRANSLATOR_VERIFIED_MODEL':model_policy.LUNA,'KILAS_LIVE_TRANSLATOR_VERIFIED_STT':budget.MODEL,
               'KILAS_LIVE_TRANSLATOR_REFERENCE_VERIFIED':'yes','KILAS_LIVE_TRANSLATOR_VERIFIED_PROJECT':'proj_synthetic'})

    def session(self,**settings):
        return store.create(self.user,'start-synthetic-'+str(self.user),'en','id',settings.get('level','beginner'),'kilas-male')[0]

    def turn(self,ident,greeting=True):
        key='learn-'+ident+('-greeting' if greeting else '-answer')
        store.claim(self.user,ident,key,'greeting' if greeting else hashlib.sha256(fixture.wav(1)).hexdigest())
        return key

    def stream(self,*args,**kwargs):
        yield {'type':'delta','text':'Halo. '}
        yield {'type':'delta','text':'Mari belajar. '}
        yield {'type':'usage','input_tokens':30,'output_tokens':12}
        yield {'type':'finish','reason':'stop'}

    def run_tutor(self,ident,key,transcript=None,stream=None,speech=None):
        with self.funded(),self.on(),patch.object(learning.voices,'resolve',return_value=VOICE),patch.object(learning.stt,'require_subscription_credit'),patch.object(providers,'_openai',side_effect=stream or self.stream),patch.object(learning,'speech',side_effect=speech or (lambda *a,**k:self.audio)):
            learning.run(self.user,ident,key,transcript)

    def test_settings_greeting_focus_native_mode_level_contract(self):
        for target in store.TARGETS:
            settings={'target':target,'native':'id','level':'intermediate'}
            text=learning.instructions(settings,True)
            self.assertIn('FIRST greeting only',text)
            self.assertIn('Indonesia',text)
            self.assertIn('intermediate',text)
            self.assertIn('correct gently',text)
            self.assertIn('full immersion',text)
            self.assertIn('Never claim to assess pronunciation',text)
            self.assertNotIn('FIRST greeting',learning.instructions(settings,False))
        with self.assertRaises(store.Error):
            store.create(self.user,'invalid-setting-123','fr','id','beginner','kilas-male')

    def test_page_deep_link_refresh_navigation_without_provider_dispatch(self):
        with self.client.session_transaction() as state:state['active_product']='finance'
        with patch.object(learning.voices,'public_choices',return_value=[VOICE]),patch.object(learning,'queue') as paid:
            for _ in range(2):
                response=self.client.get('/kilas-learning')
                self.assertEqual(response.status_code,200)
                self.assertIn('Learning',response.text)
                self.assertIn('data-call hidden',response.text)
                self.assertNotIn('id="live-translation"',response.text)
                self.assertNotIn(VOICE['id'],response.text)
                for label in ('AI Chat','Translator','Learning','Voice Over','Finance'):
                    self.assertIn('<span>'+label+'</span>',response.text)
            paid.assert_not_called()
        guest=fixture.f.app.app.test_client()
        self.assertEqual(guest.get('/kilas-learning').status_code,302)
        self.assertEqual(guest.post('/kilas-learning/sessions').status_code,400)

    def test_start_idempotent_greeting_queued_once_consent_and_csrf(self):
        self.credit(500)
        fields={'csrf_token':'audio-csrf','consent':'yes','start_key':'start-synthetic-'+str(self.user),'target':'en','native':'id','level':'beginner','voice':'kilas-male'}
        with self.funded(),self.on(),patch.object(learning.voices,'resolve',return_value=VOICE),patch.object(learning._executor,'submit') as worker:
            self.assertEqual(self.client.post('/kilas-learning/sessions',data={**fields,'consent':'no'}).status_code,400)
            self.assertEqual(self.client.post('/kilas-learning/sessions',data={**fields,'csrf_token':'wrong'}).status_code,400)
            first=self.client.post('/kilas-learning/sessions',data=fields)
            second=self.client.post('/kilas-learning/sessions',data=fields)
            self.assertEqual(first.status_code,201)
            self.assertEqual(first.json['turn'],second.json['turn'])
            self.assertEqual(worker.call_count,1)
            learning._slots.release() # Mock executor did not run its finally.
            self.assertEqual(self.client.post('/kilas-learning/sessions',data={**fields,'level':'advanced'}).status_code,409)

    def test_shared_navigation_does_not_require_an_unregistered_learning_route(self):
        from flask import render_template
        from unittest.mock import Mock
        app=fixture.f.app.app
        original=app.jinja_env.globals['url_for']
        def isolated_url(endpoint,**values):
            if endpoint.startswith('kilas_learning.'):
                raise AssertionError('Unregistered Learning endpoint must not be resolved')
            return original(endpoint,**values)
        with app.test_request_context('/products/start'):
            with patch.dict(app.jinja_env.globals,{'url_for':isolated_url}):
                html=render_template('kilas_ai/_home_task_selector.html',kilas_learning_registered=False,ui_t=lambda text:text,request=Mock(blueprint='kilas_ai'))
            self.assertNotIn('<span>Learning</span>',html)
            self.assertIn('AI Chat',html);self.assertIn('Voice Over',html)

    def test_early_phrase_streaming_full_order_private_output_and_accounting(self):
        self.credit(500);ident=self.session();key=self.turn(ident);spoken=[]
        def stream(*args,**kwargs):
            self.assertIn('FIRST greeting only',kwargs['system'])
            self.assertEqual(kwargs['project'],'proj_synthetic')
            yield {'type':'delta','text':'Halo. '}
            # The first clip is already published while the model answer is unfinished.
            self.assertEqual(len(store.state(self.user,ident,key)['clips']),1)
            self.assertEqual(store.state(self.user,ident,key)['status'],'PROCESSING')
            yield {'type':'delta','text':'Mari belajar. '}
            yield {'type':'usage','input_tokens':20,'output_tokens':12}
            yield {'type':'finish','reason':'stop'}
        self.run_tutor(ident,key,stream=stream,speech=lambda text,*a:spoken.append(text) or self.audio)
        state=store.state(self.user,ident,key)
        self.assertEqual(state['status'],'COMPLETED')
        self.assertEqual(''.join(spoken),'Halo. Mari belajar.')
        self.assertEqual([c['index'] for c in state['clips']],[0,1])
        self.assertNotIn('Halo',str(state))
        self.assertLess(state['timings']['first_published_audio_ms'],state['timings']['completed_ms'])
        ledger=db.query_one('SELECT j.* FROM kilas_audio_jobs j JOIN kilas_learning_turns t ON t.audio_job_id=j.id WHERE t.id=?',(key,))
        self.assertEqual(ledger['status'],'COMPLETED')
        self.assertEqual(ledger['seconds_charged'],(ledger['actual_ms']+999)//1000)
        self.assertEqual(ledger['reserved_seconds'],0)
        self.assertEqual(audio_store.balance(self.user)['seconds'],500-ledger['seconds_charged'])
        self.assertTrue(ledger['result_content'])

    def test_stt_then_contextual_tutor_and_no_second_greeting(self):
        self.credit(500);ident=self.session();greet=self.turn(ident)
        self.run_tutor(ident,greet)
        key=self.turn(ident,False)
        def stream(*args,**kwargs):
            self.assertNotIn('FIRST greeting',kwargs['system'])
            self.assertIn('Saya ingin belajar sapaan.',str(args[2]))
            self.assertIn('Halo.',str(args[2]))
            yield from self.stream()
        self.run_tutor(ident,key,'Saya ingin belajar sapaan.',stream=stream)
        self.assertEqual(store.state(self.user,ident,key)['status'],'COMPLETED')
        self.assertIsNone(db.query_one('SELECT id FROM kilas_vo_stt_operations WHERE user_id=?',(self.user,)))

    def test_end_during_tts_preserves_cost_but_no_late_audio_or_more_requests(self):
        self.credit(500);ident=self.session();key=self.turn(ident);calls=[]
        def stop(text,*args):
            calls.append(text);store.end(self.user,ident);return self.audio
        self.run_tutor(ident,key,speech=stop)
        state=store.state(self.user,ident,key)
        self.assertTrue(state['ended']);self.assertEqual(state['status'],'CANCELLED');self.assertEqual(state['clips'],[])
        self.assertEqual(len(calls),1)
        self.assertLess(audio_store.balance(self.user)['seconds'],500)
        with self.assertRaises(store.Error):store.clip(self.user,ident,key,0)
        self.assertIsNone(db.query_one('SELECT output_text FROM kilas_learning_turns WHERE id=?',(key,))['output_text'])

    def test_end_before_pipeline_has_no_paid_dispatch(self):
        self.credit(500);ident=self.session();key=self.turn(ident);store.end(self.user,ident)
        with patch.object(providers,'_openai') as ai,patch.object(learning,'speech') as tts:
            learning.run(self.user,ident,key)
            ai.assert_not_called();tts.assert_not_called()

    def test_cancel_start_tombstone_and_cross_owner_fences(self):
        store.cancel_start(self.user,'start-synthetic-'+str(self.user))
        with self.assertRaises(store.Error):self.session()
        ident=store.create(self.user,'another-start-key-'+str(self.user),'zh','en','advanced','kilas-female')[0]
        key=self.turn(ident)
        for action in (lambda:store.session(self.other,ident),lambda:store.state(self.other,ident,key),lambda:store.clip(self.other,ident,key,0),lambda:store.end(self.other,ident)):
            with self.assertRaises(store.Error) as caught:action()
            self.assertEqual(caught.exception.status,404)

    def test_provider_credit_gate_and_internal_balance_fail_before_dispatch(self):
        ident=self.session();key=self.turn(ident)
        with self.funded(),self.on(),patch.object(learning.voices,'resolve',return_value=VOICE),patch.object(learning.stt,'require_subscription_credit') as credit,patch.object(providers,'_openai') as ai:
            learning.run(self.user,ident,key)
            ai.assert_not_called();credit.assert_not_called()
        self.assertEqual(store.state(self.user,ident,key)['error_code'],'zero_balance')

    def test_provider_credit_failure_never_dispatches_tts_or_retries(self):
        self.credit(500);ident=self.session();key=self.turn(ident)
        with self.funded(),self.on(),patch.object(learning.voices,'resolve',return_value=VOICE),patch.object(providers,'_openai',side_effect=self.stream),patch.object(learning.stt,'require_subscription_credit',side_effect=budget.BudgetError('provider_credit_exhausted',402)) as credit,patch.object(learning,'speech') as tts:
            learning.run(self.user,ident,key)
            self.assertEqual(credit.call_count,1);tts.assert_not_called()
        self.assertFalse(store.claim(self.user,ident,key,'greeting'))

    def test_incomplete_response_timeout_never_claims_complete_or_retries(self):
        self.credit(500);ident=self.session();key=self.turn(ident)
        self.run_tutor(ident,key,stream=lambda *a,**k:iter([{'type':'delta','text':'Halo. '},{'type':'finish','reason':'length'}]))
        self.assertEqual(store.state(self.user,ident,key)['status'],'FAILED')
        self.assertEqual(store.state(self.user,ident,key)['error_code'],'incomplete_response')
        self.assertFalse(store.claim(self.user,ident,key,'greeting'))
        db.execute("UPDATE kilas_learning_turns SET status='PROCESSING',created_at=? WHERE id=?",((usage._now()-timedelta(minutes=4)).isoformat(),key))
        self.assertEqual(store.state(self.user,ident,key)['status'],'FAILED')
        with self.assertRaises(store.Error):store.check(self.user,ident,key)

    def test_daily_cost_guard_counts_dispatched_unknown_clips(self):
        self.credit(500);ident=self.session();key=self.turn(ident)
        job,_=audio_store.create(self.user,key+'-audio','voiceover','Learning','id','en',VOICE['id'],VOICE['name'],'Learning',0,None,1,0)
        audio_store.start(self.user,job)
        db.execute('INSERT INTO kilas_learning_clips(turn_id,sequence,chars,dispatched_at) VALUES (?,?,?,?)',(key,0,6000,usage._now().isoformat()))
        with self.assertRaises(store.Error) as error:store.dispatch_clip(self.user,ident,key,1,'Hi',job)
        self.assertEqual(error.exception.code,'learning_audio_limit')

    def admit(self,ident,key):
        with patch.object(learning._executor,'submit') as worker:
            self.assertTrue(realtime.begin(self.user,ident,key))
            self.assertFalse(realtime.begin(self.user,ident,key))
            self.assertEqual(worker.call_count,1)
        learning._slots.release()

    def test_realtime_admission_chunk_order_duplicates_commit_cancel_and_ownership(self):
        ident=self.session();key='learn-realtime-synthetic-123'
        with self.funded(),self.on():
            self.admit(ident,key)
            realtime.append(self.user,ident,key,0,b'\x01\x00'*4000)
            realtime.append(self.user,ident,key,0,b'\x01\x00'*4000)
            for owner,index,pcm in ((self.other,1,b'00'),(self.user,2,b'00'),(self.user,0,b'11')):
                with self.assertRaises(store.Error):realtime.append(owner,ident,key,index,pcm)
            self.assertEqual(len(realtime.take(self.user,ident,key)[0]),8000)
            self.assertEqual(realtime.take(self.user,ident,key),(None,False))
            realtime.commit(self.user,ident,key)
            self.assertEqual(realtime.take(self.user,ident,key),(None,True))
            realtime.cancel(self.user,ident,key)
            with self.assertRaises(store.Error):realtime.take(self.user,ident,key)
            self.assertEqual(store.state(self.user,ident,key)['status'],'CANCELLED')

    def test_cancel_before_admission_and_end_clear_pcm_without_paid_connections(self):
        ident=self.session();key='learn-realtime-cancel-1234'
        with self.funded(),self.on(),patch.object(learning._executor,'submit') as work:
            realtime.cancel(self.user,ident,key)
            self.assertFalse(realtime.begin(self.user,ident,key));work.assert_not_called()
            other='learn-realtime-ended-1234';self.admit(ident,other)
            realtime.append(self.user,ident,other,0,b'00')
            store.end(self.user,ident)
            self.assertIsNone(db.query_one('SELECT pcm FROM kilas_learning_input_chunks WHERE turn_id=?',(other,))['pcm'])
            with patch.object(realtime.websocket,'create_connection') as connect:
                with self.assertRaises(store.Error):realtime.transcribe(self.user,ident,other,connect=connect)
                connect.assert_not_called()

    def test_realtime_stable_final_only_streams_before_commit_and_closes(self):
        ident=self.session();key='learn-realtime-final-1234';sent=[];closed=[]
        class Socket:
            def settimeout(inner,value):pass
            def send(inner,value):sent.append(json.loads(value))
            def close(inner):closed.append(True)
            def recv(inner):
                if len(sent)==1:
                    realtime.append(self.user,ident,key,1,b'22');realtime.commit(self.user,ident,key)
                    return json.dumps({'message_type':'partial_transcript','text':'UNSTABLE'})
                if len(sent)==2:return json.dumps({'message_type':'committed_transcript','text':'Saya ingin'})
                return json.dumps({'message_type':'committed_transcript','text':'belajar bahasa.'})
        with self.funded(),self.on(),patch.object(realtime.stt,'require_subscription_credit'):
            self.admit(ident,key);realtime.append(self.user,ident,key,0,b'00')
            text,timings=realtime.transcribe(self.user,ident,key,connect=lambda *a,**k:Socket())
            self.assertEqual(text,'Saya ingin belajar bahasa.')
            self.assertNotIn('UNSTABLE',text);self.assertEqual(len(sent),3)
            self.assertFalse(sent[0].get('commit',False));self.assertTrue(sent[-1]['commit'])
            self.assertGreaterEqual(timings['stt_result_ms'],timings['utterance_end_ms'])
            self.assertEqual(closed,[True])

    def test_no_paid_socket_without_audio_and_no_retry_on_provider_failure(self):
        ident=self.session();key='learn-realtime-empty-1234';clock=[0]
        def wait(seconds):clock[0]+=seconds
        with self.funded(),self.on(),patch.object(realtime.stt,'require_subscription_credit'):
            self.admit(ident,key)
            with patch.object(realtime.websocket,'create_connection') as connect:
                with self.assertRaises(store.Error) as caught:realtime.transcribe(self.user,ident,key,connect=connect,now=lambda:clock[0],wait=wait)
                self.assertEqual(caught.exception.code,'empty_speech');connect.assert_not_called()
            realtime.append(self.user,ident,key,0,b'00')
            with patch.object(realtime.websocket,'create_connection',side_effect=OSError('synthetic transport')) as connect:
                with self.assertRaises(store.Error):realtime.transcribe(self.user,ident,key,connect=connect)
                self.assertEqual(connect.call_count,1)
            row=db.query_one('SELECT dispatched,charge_micro FROM kilas_learning_inputs WHERE turn_id=?',(key,))
            self.assertEqual(row['dispatched'],1);self.assertEqual(row['charge_micro'],realtime.RESERVE_MICRO)

    def test_realtime_api_csrf_bounded_chunks_and_no_legacy_upload_route(self):
        ident=self.session();key='learn-realtime-route-1234'
        url='/kilas-learning/sessions/'+ident+'/input'
        with self.funded(),self.on(),patch.object(learning._executor,'submit'):
            self.assertEqual(self.client.post(url,data={'operation_key':key}).status_code,400)
            self.assertEqual(self.client.post(url,data={'csrf_token':'audio-csrf','operation_key':key}).status_code,202)
            learning._slots.release()
            response=self.client.post(url+'/'+key+'/chunks/0',data={'csrf_token':'audio-csrf','chunk':(io.BytesIO(b'00'),'chunk.pcm')})
            self.assertEqual(response.status_code,200)
            self.assertEqual(self.client.post('/kilas-learning/sessions/'+ident+'/turns',data={'csrf_token':'audio-csrf'}).status_code,404)

    def test_additive_schema_is_idempotent_and_kill_switch_blocks_new_work(self):
        learning_schema.apply_release();learning_schema.apply_release()
        with self.funded(),self.on():
            self.assertTrue(learning.ready(self.user))
            for values in ({'KILAS_LEARNING_ENABLED':'false'},{'KILAS_LEARNING_REALTIME_ENABLED':'false'},{'KILAS_LEARNING_REALTIME_BUDGET_MICRO_USD':'0'},{'KILAS_VO_STT_ALLOWED_OWNER_ID':str(self.other)},{'KILAS_LEARNING_REALTIME_BILLING_VERIFIED':''}):
                with patch.dict(os.environ,values):self.assertFalse(learning.ready(self.user))

    def test_session_continues_past_old_expiry_and_forty_turns(self):
        ident=self.session()
        db.execute('UPDATE kilas_learning_sessions SET expires_at=? WHERE id=?',((usage._now()-timedelta(days=1)).isoformat(),ident))
        for index in range(45):
            key='learning-long-turn-'+str(index)
            self.assertTrue(store.claim(self.user,ident,key,'realtime'))
            store.finish(self.user,ident,key,'practice','example',{})
        self.assertEqual(store.current(self.user),ident)
        self.assertFalse(store.state(self.user,ident)['ended'])
        self.assertLessEqual(len(store.context(self.user,ident)),18)
        store.end(self.user,ident)
        self.assertIsNone(store.current(self.user))
        with self.assertRaises(store.Error):store.claim(self.user,ident,'learning-ended-turn','realtime')

    def test_initial_explanation_choice_survives_rolling_context_without_duplicates(self):
        ident=self.session()
        for index in range(12):
            key='learning-memory-turn-'+str(index)
            store.claim(self.user,ident,key,'realtime')
            store.finish(self.user,ident,key,'Explain in Spanish' if index==0 else 'practice '+str(index),'example',{})
        messages=store.context(self.user,ident)
        self.assertEqual(messages[0],{'role':'user','content':'Explain in Spanish'})
        self.assertEqual(sum(m['content']=='Explain in Spanish' for m in messages),1)
        self.assertEqual(len(messages),18)
        self.assertIn('latest preference',learning.instructions(store.session(self.user,ident),False))

    def test_stale_input_recovery_clears_pcm_without_refunding_dispatched_cost(self):
        ident=self.session();old='learning-stale-turn-1234'
        store.claim(self.user,ident,old,'realtime')
        stamp=(usage._now()-timedelta(minutes=4)).isoformat()
        db.execute('UPDATE kilas_learning_turns SET created_at=? WHERE id=?',(stamp,old))
        db.execute("INSERT INTO kilas_learning_inputs(turn_id,status,dispatched,charge_micro,created_at) VALUES (?,'STREAMING',1,4875,?)",(old,stamp))
        db.execute('INSERT INTO kilas_learning_input_chunks VALUES (?,0,?,?)',(old,'synthetic',b'00'))
        self.assertEqual(store.state(self.user,ident,old)['status'],'FAILED')
        self.assertTrue(store.claim(self.user,ident,'learning-recovery-turn','realtime'))
        row=db.query_one('SELECT status,charge_micro FROM kilas_learning_inputs WHERE turn_id=?',(old,))
        self.assertEqual(row['status'],'FAILED');self.assertEqual(row['charge_micro'],4875)
        self.assertIsNone(db.query_one('SELECT pcm FROM kilas_learning_input_chunks WHERE turn_id=?',(old,))['pcm'])

    def test_cancelled_tts_turn_cannot_publish_late_audio_but_preserves_charge(self):
        self.credit(500);ident=self.session();key=self.turn(ident)
        def cancel(text,*args):
            realtime.cancel(self.user,ident,key)
            return self.audio
        self.run_tutor(ident,key,speech=cancel)
        self.assertEqual(store.state(self.user,ident,key)['status'],'CANCELLED')
        self.assertEqual(store.state(self.user,ident,key)['clips'],[])
        self.assertLess(audio_store.balance(self.user)['seconds'],500)

    def test_compact_call_ui_preserves_consent_and_has_no_provider_description(self):
        with patch.object(learning.voices,'public_choices',return_value=[VOICE]):
            html=self.client.get('/kilas-learning').text
        self.assertIn('aria-label="Akhiri sesi"',html)
        self.assertIn('name="consent" value="yes" required',html)
        self.assertIn('/privacy#audio-processing',html)
        self.assertNotIn('ElevenLabs',html);self.assertNotIn('OpenAI',html)
        self.assertNotIn('30 menit',html);self.assertNotIn('40 giliran',html)

    def test_independent_language_level_and_branded_voice_choices(self):
        for target in store.TARGETS:
            for native in store.NATIVES:
                for level in store.LEVELS:
                    for voice in ('kilas-male','kilas-female'):
                        start='learning-choices-'+target+'-'+native+'-'+level+'-'+voice
                        ident,_=store.create(self.user,start,target,native,level,voice)
                        settings=store.session(self.user,ident)
                        self.assertEqual((settings['target'],settings['native'],settings['level'],settings['voice']),(target,native,level,voice))
                        self.assertIn(store.NATIVES[native],learning.instructions(settings,True))
                        store.end(self.user,ident)

    def test_readiness_report_is_nonconsuming_boolean_evidence_without_secrets(self):
        with self.funded(),self.on(),patch.object(providers,'_openai') as tutor,patch.object(learning.requests,'post') as tts,patch.object(realtime.websocket,'create_connection') as stt:
            report=learning.readiness()
            self.assertTrue(report['ready']);self.assertTrue(all(type(value) is bool for key,value in report.items() if key not in ('learning_budget_micro','existing_account_budget_micro')))
            self.assertEqual(report['learning_budget_micro'],60000)
            self.assertNotIn('synthetic',json.dumps(report));self.assertNotIn(str(self.user),json.dumps(report))
            for env,gate in [('KILAS_LEARNING_REALTIME_ENABLED','realtime_enabled'),('KILAS_LEARNING_REALTIME_BILLING_VERIFIED','billing_marker_verified'),('KILAS_LEARNING_REALTIME_BUDGET_MICRO_USD','learning_budget_valid')]:
                with patch.dict(os.environ,{env:''}):
                    report=learning.readiness();self.assertFalse(report[gate]);self.assertFalse(report['ready'])
            with patch.object(learning_schema,'print',create=True) as output:
                learning_schema.report_readiness()
                self.assertTrue(output.call_args.args[0].startswith('KILAS_LEARNING_READINESS '))
            tutor.assert_not_called();tts.assert_not_called();stt.assert_not_called()

    def test_readiness_diagnostic_failure_cannot_interrupt_service_startup(self):
        with patch.object(learning,'readiness',side_effect=ValueError('synthetic')),patch.object(learning_schema,'print',create=True) as output:
            learning_schema.report_readiness()
            self.assertIn('"report_available": false',output.call_args.args[0])
        with patch.object(learning_schema,'print',side_effect=OSError('closed output'),create=True):
            learning_schema.report_readiness()


class PhraseTests(unittest.TestCase):
    def test_every_character_survives_arbitrary_deltas_and_stable_boundaries(self):
        text='Hello, Dr. Irvan. This costs 3.50. 你好！¿Cómo estás? Bien.'
        for size in (1,2,7,20,100):
            phrases=learning_phrases.Phrases();parts=[]
            for at in range(0,len(text),size):parts+=phrases.feed(text[at:at+size])
            parts+=phrases.feed('',final=True)
            self.assertEqual(''.join(parts),text)
            self.assertEqual(phrases.pending,'')
    def test_ascii_end_of_delta_is_not_a_boundary(self):
        phrases=learning_phrases.Phrases()
        self.assertEqual(phrases.feed('The number is 3.'),[])
        self.assertEqual(phrases.feed('50. Next '),['The number is 3.50.'])


if __name__=='__main__':unittest.main()
