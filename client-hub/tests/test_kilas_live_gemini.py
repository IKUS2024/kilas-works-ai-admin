"""Disposable SQLite + synthetic socket only; no real credentials or provider IO."""
import base64
import json
import io
import os
from pathlib import Path
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone, timedelta
from queue import Queue
from threading import Thread, Event
from unittest.mock import patch
import test_kilas_live_translator as fixture
import test_kilas_audio as audio
from kilas_ai import live_gemini as native, live_gemini_budget as budget
from kilas_ai import live_translator_store as sessions, audio_store


PCM = b'\x01\x00'*2400


class Socket:
    def __init__(self, hold_tail=None):
        self.incoming = Queue()
        self.incoming.put(json.dumps({'setupComplete':{}}))
        self.sent = []
        self.hold_tail = hold_tail
        self.first = Event()
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def recv(self):
        value = self.incoming.get(timeout=3)
        if value is None:
            raise OSError('synthetic socket closed')
        return value

    def send(self, value):
        value = json.loads(value)
        self.sent.append(value)
        data = value.get('realtimeInput',{})
        if data.get('audio'):
            self.incoming.put(json.dumps({'serverContent':{
                'inputTranscription':{'text':'Repeat. '}, 'outputTranscription':{'text':'Ulang. '},
                'modelTurn':{'parts':[{'inlineData':{'mimeType':'audio/pcm;rate=24000',
                                                   'data':base64.b64encode(PCM).decode()}}]}}}))
            self.first.set()
        if data.get('audioStreamEnd'):
            def tail():
                if self.hold_tail:
                    self.hold_tail.wait(2)
                self.incoming.put(json.dumps({'serverContent':{
                    'outputTranscription':{'text':'Tail'},
                    'modelTurn':{'parts':[{'inlineData':{'mimeType':'audio/pcm;rate=24000',
                                                       'data':base64.b64encode(PCM).decode()}}]},
                    'turnComplete':True}}))
            Thread(target=tail, daemon=True).start()

    def shutdown(self):
        if not self.closed:
            self.closed = True
            self.incoming.put(None)


class GeminiTests(unittest.TestCase):
    setUp = fixture.LiveTranslatorTests.setUp
    funded = fixture.LiveTranslatorTests.funded
    on = fixture.LiveTranslatorTests.on
    credit = fixture.LiveTranslatorTests.credit
    key = fixture.LiveTranslatorTests.key

    def config(self, **extra):
        values = {'KILAS_LIVE_GEMINI_ENABLED':'true', 'KILAS_LIVE_GEMINI_BILLING_VERIFIED':'yes',
                  'KILAS_LIVE_GEMINI_ALLOWED_OWNER_ID':str(self.user),
                  'KILAS_LIVE_GEMINI_CAMPAIGN':'synthetic-gemini-'+str(self.user),
                  'KILAS_LIVE_GEMINI_BUDGET_MICRO_USD':'5000',
                  'KILAS_LIVE_GEMINI_LEASE_RESERVE_MICRO_USD':'1000',
                  'KILAS_LIVE_GEMINI_EXPIRES_AT':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
                  'GEMINI_API_KEY':'synthetic-native-key-not-real', 'KILAS_LIVE_TRANSLATOR_AUDIO_SECONDS':'600'}
        values.update(extra)
        return patch.dict(os.environ, values)

    def make(self):
        self.credit(300)
        ident = sessions.create(self.user, 'id', 'en', native.VOICE)
        # Admission is real; block its threads so the test controls the socket.
        with patch.object(native.Thread, 'start'):
            relay = native.start(self.user, ident, self.key())
        self.addCleanup(lambda:native.cancel(self.user,ident))
        self.addCleanup(lambda:native._slots.release() if not relay.finished else None)
        return relay

    def row(self):
        return audio.f.db.query_one('SELECT * FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key=?',
                                   (self.user,self.key()+'-gm'))

    def wait(self, predicate):
        until = time.monotonic()+3
        while time.monotonic()<until:
            if predicate():
                return
            time.sleep(.005)
        self.fail('Synthetic relay did not reach expected state')

    def test_off_missing_budget_or_wrong_owner_never_connects_or_claims(self):
        for extra in ({'KILAS_LIVE_GEMINI_ENABLED':'false'},
                      {'KILAS_LIVE_GEMINI_BILLING_VERIFIED':''},
                      {'KILAS_LIVE_GEMINI_BUDGET_MICRO_USD':'0'},
                      {'KILAS_LIVE_GEMINI_ALLOWED_OWNER_ID':str(self.other)},
                      {'KILAS_LIVE_GEMINI_EXPIRES_AT':'2000-01-01T00:00:00+00:00'},
                      {'GEMINI_API_KEY':''}):
            with self.config(**extra), patch.object(native,'connect') as connect:
                self.assertFalse(native.ready(self.user))
                with self.assertRaises(audio_store.AudioError):
                    native.start(self.user, 'a'*48, self.key())
                connect.assert_not_called()
                self.assertIsNone(self.row())

    def test_native_page_is_hidden_by_default_and_original_live_page_unchanged(self):
        with self.funded(), self.on(), self.config(KILAS_LIVE_GEMINI_ENABLED='false'), patch.object(native,'connect') as connect:
            self.assertEqual(self.client.get('/kilas-translator/live/gemini').status_code,404)
            original = self.client.get('/kilas-translator/live')
            self.assertEqual(original.status_code,200)
            self.assertNotIn('/static/kilas_live_gemini.mjs',original.text)
            connect.assert_not_called()

    def test_owner_landing_is_read_only_until_funding_is_ready(self):
        email=audio.f.db.query_one('SELECT email FROM users WHERE id=?',(self.user,))['email']
        with self.config(KILAS_LIVE_GEMINI_ENABLED='false',KILAS_LIVE_GEMINI_QA_OWNER_ID=str(self.user),
                         KILAS_LIVE_GEMINI_QA_OWNER_EMAIL=email), patch.object(native,'connect') as connect:
            response=self.client.get('/kilas-translator/live/gemini')
            self.assertEqual(response.status_code,200)
            self.assertIn('Rp500.000',response.text)
            self.assertNotIn('/static/kilas_live_gemini.mjs',response.text)
            self.assertNotIn('id="live-setup-form"',response.text)
            response=self.client.post('/kilas-translator/live/gemini/sessions',data={'csrf_token':'audio-csrf'})
            self.assertEqual(response.status_code,404)
            self.assertIsNone(self.row())
            with patch.dict(os.environ,{'KILAS_LIVE_GEMINI_QA_OWNER_EMAIL':'wrong@example.test'}):
                self.assertEqual(self.client.get('/kilas-translator/live/gemini').status_code,404)
            self.assertFalse(native.preview_owner(self.other))
            connect.assert_not_called()

    def lifetime(self, **extra):
        values={'KILAS_LIVE_GEMINI_POLICY':'owner_lifetime','KILAS_LIVE_GEMINI_IDR_CEILING_VERIFIED':'yes',
                'KILAS_LIVE_GEMINI_TOTAL_IDR':'500000','KILAS_LIVE_GEMINI_IDR_PER_USD_CEILING':'25000',
                'KILAS_LIVE_GEMINI_BUDGET_MICRO_USD':'20000000',
                'KILAS_LIVE_GEMINI_LEASE_RESERVE_MICRO_USD':'100000',
                'KILAS_LIVE_GEMINI_EXPIRES_AT':''}
        values.update(extra)
        return patch.dict(os.environ,values)

    def test_lifetime_budget_requires_verified_currency_bound_and_finite_total(self):
        with self.config(),self.lifetime():
            config=budget.policy()
            self.assertEqual(config['mode'],'owner_lifetime')
            self.assertEqual(config['expires_at'],'owner-lifetime-v1')
            for extra in ({'KILAS_LIVE_GEMINI_IDR_CEILING_VERIFIED':''},
                          {'KILAS_LIVE_GEMINI_IDR_PER_USD_CEILING':'0'},
                          {'KILAS_LIVE_GEMINI_BUDGET_MICRO_USD':'20000001'},
                          {'KILAS_LIVE_GEMINI_TOTAL_IDR':'500001'},
                          {'KILAS_LIVE_GEMINI_LEASE_RESERVE_MICRO_USD':'99999'},
                          {'KILAS_LIVE_GEMINI_POLICY':'unknown'}):
                with patch.dict(os.environ,extra):self.assertIsNone(budget.policy(),extra)

    def test_lifetime_budget_includes_previous_qa_unknown_cost_across_campaigns(self):
        with self.config():
            old=budget.claim(self.user,'a'*48,self.key())
            budget.dispatch(old);budget.finish(old,False)
            with self.lifetime(KILAS_LIVE_GEMINI_CAMPAIGN='standing-one',KILAS_LIVE_GEMINI_BUDGET_MICRO_USD='100000'):
                with self.assertRaises(budget.ledger.BudgetError) as caught:
                    budget.claim(self.user,'b'*48,'live-'+'b'*32)
                self.assertEqual(caught.exception.code,'budget_limit')
                with patch.dict(os.environ,{'KILAS_LIVE_GEMINI_CAMPAIGN':'standing-two'}):
                    with self.assertRaises(budget.ledger.BudgetError) as caught:
                        budget.claim(self.user,'b'*48,'live-'+'c'*32)
                    self.assertEqual(caught.exception.code,'budget_limit')
            self.assertEqual(self.row()['charge_micro'],1000)

    def test_valid_pcm_at_output_boundary_reports_limit_not_bad_format(self):
        with self.config(),patch.object(native,'OUTPUT_BYTES',len(PCM)):
            relay=self.make()
            packet=json.dumps({'serverContent':{'modelTurn':{'parts':[{'inlineData':{
                'mimeType':'audio/pcm;rate=24000','data':base64.b64encode(PCM).decode()}}]}}})
            relay.receive(packet)
            with self.assertRaises(audio_store.AudioError) as caught:relay.receive(packet)
            self.assertEqual(caught.exception.code,'gemini_output_limit')
            self.assertEqual(relay.output_bytes,len(PCM))
            self.assertEqual(relay.diagnostics()['output_rejected_bytes'],len(PCM))
            self.assertEqual(relay.diagnostics()['output_received_packets'],2)
            budget.finish(relay.capability,False);audio_store.fail(self.user,relay.job,'synthetic')

    def test_native_consent_pair_locale_and_no_secret_in_rendered_page(self):
        with self.config(), patch.object(native,'connect') as connect:
            self.credit(300)
            pages={}
            for locale in ('en','id','en'):
                self.client.set_cookie('kilas_language',locale)
                response = self.client.get('/kilas-translator/live/gemini')
                self.assertEqual(response.status_code,200)
                self.assertIn('<html lang="'+locale+'">',response.text)
                self.assertIn('One-way live translation' if locale=='en' else 'Terjemahan langsung satu arah',response.text)
                self.assertNotIn('synthetic-native-key-not-real',response.text)
                self.assertNotIn('voice_id',response.text)
                pages[locale]=response.text
            target=os.environ.get('KILAS_GEMINI_UI_FIXTURE_PATH')
            if target:
                Path(target).write_text(json.dumps(pages),encoding='utf-8')
            fields={'csrf_token':'audio-csrf','language_a':'id','language_b':'id','consent':'gemini-live-v1'}
            self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data=fields).status_code,400)
            fields.update(language_b='en',consent='yes')
            self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data=fields).status_code,400)
            fields['consent']='gemini-live-v1'
            response=self.client.post('/kilas-translator/live/gemini/sessions',data=fields)
            self.assertEqual(response.status_code,201)
            ident=response.json['session_id']
            self.addCleanup(lambda:sessions.end(self.user,ident))
            self.assertEqual(response.json['input_mode'],'gemini-live-v1')
            self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data=fields).status_code,409)
            connect.assert_not_called()

    def test_dispatch_marker_precedes_handshake_and_failure_keeps_unknown_reserve(self):
        with self.config():
            relay=self.make()
            def fail():
                self.assertEqual(self.row()['status'],'DISPATCHED')
                raise OSError('Authorization: synthetic-native-key-not-real')
            with patch.object(native,'connect',side_effect=fail):
                relay.run()
            self.assertEqual(self.row()['status'],'UNKNOWN')
            self.assertEqual(self.row()['charge_micro'],1000)
            self.assertNotIn('synthetic-native-key-not-real',str(relay.error))
            self.assertEqual(audio_store.get(self.user,relay.job)['status'],'FAILED')

    def test_utf8_binary_protocol_frames_and_setup_metadata_complete_normally(self):
        class BinarySocket(Socket):
            def recv(self):
                value=json.loads(super().recv())
                if 'setupComplete' in value:value['setupComplete']={'sessionId':'synthetic-opaque'}
                return json.dumps(value).encode('utf-8')
        with self.config():
            relay=self.make()
            gate=Event();socket=BinarySocket(gate)
            relay.accept(0,b'\x01\x00'*1600)
            relay.finish_input(1)
            def tail():
                relay.end_sent.wait(2);gate.set()
            Thread(target=tail,daemon=True).start()
            with patch.object(native,'connect',return_value=socket):relay.run()
            self.assertTrue(relay.completed.is_set())
            self.assertIsNone(relay.error)
            self.assertGreater(relay.output_bytes,0)
            self.assertEqual(self.row()['status'],'COMPLETED')

    def test_binary_protocol_rejects_non_utf8_non_object_and_oversized_frames(self):
        for raw in (b'\xff',b'[]',b'x'*(native.MAX_MESSAGE+1),None):
            with self.assertRaises(audio_store.AudioError):native.message(raw)

    def test_recorded_pcm_duration_does_not_extend_bounded_receive_window(self):
        with self.config():
            relay=self.make();base=relay.started
            def audio_for(ms):
                return json.dumps({'serverContent':{'modelTurn':{'parts':[{'inlineData':{
                    'mimeType':'audio/pcm;rate=24000','data':base64.b64encode(b'\x01\x00'*(ms*24)).decode()}}]}}})
            # A recorded timing pattern has27.750s accepted PCM after15s input.
            # Playback remains available without extending the provider socket.
            with patch.object(native,'monotonic',return_value=base+2.881):
                relay.receive(audio_for(14000));relay.receive(audio_for(13750))
            relay.end_at=base+15;relay.end_sent.set();relay.input_closed=True
            self.assertAlmostEqual(relay.drain_deadline(),base+19,places=3)
            with patch.object(native,'monotonic',return_value=base+18.999),\
                 patch.object(relay.cancelled,'wait',side_effect=[False,True]):
                relay.watch()
            self.assertIsNone(relay.error);self.assertFalse(relay.completed.is_set())
            with patch.object(native,'monotonic',return_value=base+19),\
                 patch.object(relay.cancelled,'wait',return_value=False):
                relay.watch()
            self.assertTrue(relay.completed.is_set())
            self.assertEqual(relay.completion_kind,'bounded_drain')
            self.assertFalse(relay.tail_confirmed)
            self.assertIsNone(relay.error)
            self.assertEqual(relay.output_bytes,27750*48)
            # A test's45s lease still bounds an EOS sent near that deadline.
            relay.end_at=base+43
            with patch.object(budget,'LEASE_MS',45000):
                self.assertEqual(relay.drain_deadline(),base+45)
            budget.finish(relay.capability,False);audio_store.fail(self.user,relay.job,'synthetic')

    def test_watchdog_reason_survives_recv_close_and_keeps_unknown_spend(self):
        with self.config():
            relay=self.make()
            class ClosedByWatchdog:
                calls=0
                def send(self,raw):pass
                def settimeout(self,timeout):pass
                def shutdown(self):pass
                def recv(self):
                    self.calls+=1
                    if self.calls==1:return '{"setupComplete":{}}'
                    relay.stop(native.failure('gemini_tail_timeout'))
                    raise OSError('synthetic recv closed; no supplier details')
            with patch.object(native,'connect',return_value=ClosedByWatchdog()),patch.object(native.Thread,'start'):
                relay.run()
            self.assertEqual(relay.error.code,'gemini_tail_timeout')
            self.assertEqual(relay.diagnostics()['first_error_code'],'gemini_tail_timeout')
            self.assertEqual(self.row()['status'],'UNKNOWN')
            self.assertEqual(self.row()['charge_micro'],1000)
            self.assertEqual(audio_store.get(self.user,relay.job)['error_code'],'gemini_tail_timeout')

    def test_socket_eof_after_input_end_does_not_imply_final_tail_success(self):
        with self.config():
            relay=self.make();relay.end_sent.set();relay.end_at=time.monotonic()
            class EmptyClose:
                calls=0
                def send(self,raw):pass
                def settimeout(self,timeout):pass
                def shutdown(self):pass
                def recv(self):
                    self.calls+=1
                    return '{"setupComplete":{}}' if self.calls==1 else b''
            with patch.object(native,'connect',return_value=EmptyClose()),patch.object(native.Thread,'start'):
                relay.run()
            self.assertEqual(relay.error.code,'gemini_tail_unconfirmed')
            self.assertFalse(relay.completed.is_set())
            self.assertEqual(self.row()['status'],'UNKNOWN')

    def test_fast_eos_acknowledgement_is_not_lost_before_send_returns(self):
        with self.config():
            relay=self.make();ack=Event();receivers=[]
            class FastAck:
                def send(self,raw):
                    if json.loads(raw).get('realtimeInput',{}).get('audioStreamEnd'):
                        def receive():
                            relay.receive('{"serverContent":{"turnComplete":true}}')
                            ack.set()
                        receiver=Thread(target=receive,daemon=True);receivers.append(receiver);receiver.start()
                        ack.wait(.05) # Simulate remote reply before send returns.
                def shutdown(self):pass
            relay.ws=FastAck();relay.accept(0,b'\x00\x00'*1600);relay.finish_input(1)
            sender=Thread(target=relay.send);sender.start();sender.join(2)
            for receiver in receivers:receiver.join(2)
            self.assertFalse(sender.is_alive());self.assertTrue(ack.is_set())
            self.assertTrue(relay.end_sent.is_set());self.assertTrue(relay.completed.is_set())
            budget.finish(relay.capability,False);audio_store.fail(self.user,relay.job,'synthetic')

    def test_generation_and_in_progress_or_interrupted_turns_do_not_fake_final_success(self):
        with self.config():
            relay=self.make();relay.end_sent.set();relay.end_at=time.monotonic()
            relay.receive('{"serverContent":{"generationComplete":true}}')
            self.assertFalse(relay.completed.is_set())
            relay.receive('{"serverContent":{"turnComplete":true,"interactionStatus":"IN_PROGRESS"}}')
            self.assertFalse(relay.completed.is_set())
            relay.receive('{"serverContent":{"turnComplete":true,"interrupted":true}}')
            self.assertFalse(relay.completed.is_set())
            relay.receive('{"serverContent":{"turnComplete":true,"interactionStatus":"IDLE"}}')
            self.assertTrue(relay.completed.is_set())
            self.assertEqual(relay.diagnostics()['completion_kind'],'turn_complete')
            self.assertEqual(relay.diagnostics()['generation_complete_after_end'],1)
            self.assertEqual(relay.diagnostics()['turn_complete_after_end'],3)
            budget.finish(relay.capability,False);audio_store.fail(self.user,relay.job,'synthetic')

    def test_synthetic_harness_normal_finish_and_cleanup_end_retain_success(self):
        from kilas_ai import live_gemini_smoke as smoke
        with self.config(),patch.object(native,'connect',return_value=Socket()),redirect_stdout(io.StringIO()):
            self.credit(300)
            result=smoke.session({'owner':self.user},'en','id',b'\x01\x00'*1600)
        self.assertTrue(result['terminal_turn_complete'])
        self.assertTrue(result['all_generated_pcm_read'])
        self.assertTrue(result['settled_after_end'])
        self.assertIsNone(result['code'])
        self.assertIsNone(result['protocol']['first_error_code'])
        self.assertEqual(result['post_end_output_access'],'blocked')

    def test_undispatched_end_releases_reservation_and_never_connects(self):
        with self.config():
            relay=self.make()
            sessions.end(self.user,relay.ident)
            with patch.object(native,'connect') as connect:
                relay.run()
                connect.assert_not_called()
            self.assertEqual(self.row()['status'],'CANCELLED')
            self.assertEqual(self.row()['charge_micro'],0)

    def test_streams_before_input_end_and_preserves_final_tail_repetitions_and_one_charge(self):
        tail=Event();socket=Socket(tail)
        with self.config(), patch.object(native,'connect',return_value=socket):
            relay=self.make()
            runner=Thread(target=relay.run);runner.start()
            relay.accept(0,b'\x01\x00'*3200)  # Two 100ms provider input frames.
            self.wait(lambda:len(relay.frames)==2)
            early=relay.snapshot(0)
            self.assertEqual(early['status'],'PROCESSING')
            self.assertFalse(early['input_closed'])
            self.assertEqual(early['translated_text'],'Ulang. Ulang. ')
            self.assertEqual(len(early['frames']),2)
            self.assertEqual(relay.snapshot(0)['frames'],early['frames']) # Retry-safe cursor read.
            relay.finish_input(1)
            self.wait(relay.end_sent.is_set)
            self.assertFalse(relay.finished)
            tail.set();runner.join(3);self.assertFalse(runner.is_alive())
            final=relay.snapshot(2)
            self.assertEqual(final['status'],'COMPLETED')
            self.assertEqual(final['translated_text'],'Ulang. Ulang. Tail')
            self.assertEqual(final['total_frames'],3)
            self.assertEqual([f['index'] for f in final['frames']],[2])
            self.assertTrue(final['output_closed'])
            job=audio_store.get(self.user,relay.job)
            self.assertEqual(job['actual_ms'],300)
            self.assertEqual(job['seconds_charged'],1)
            stored=audio.f.db.query_one('SELECT result_content,original_script FROM kilas_audio_jobs WHERE id=?',(relay.job,))
            self.assertIsNone(stored['result_content'])
            self.assertIsNone(stored['original_script'])
            self.assertEqual(self.row()['status'],'COMPLETED')
            self.assertEqual(self.row()['charge_micro'],1000)
            self.assertEqual(audio_store.history_page(self.user,kind='voiceover')['history_total'],0)
            self.assertEqual(socket.sent[0],native.setup('en'))

    def test_output_validation_order_limits_and_terminal_marker(self):
        with self.config():
            relay=self.make()
            for payload in ({'serverContent':{'modelTurn':{'parts':[{'inlineData':{'mimeType':'audio/pcm;rate=16000','data':'AA=='}}]}}},
                            {'serverContent':{'modelTurn':{'parts':[{'inlineData':{'mimeType':'audio/pcm;rate=24000','data':'invalid'}}]}}},
                            {'toolCall':{}}, {'goAway':{}}):
                with self.assertRaises(audio_store.AudioError):
                    relay.receive(json.dumps(payload))
            with self.assertRaises(audio_store.AudioError):relay.accept(1,b'\0\0')
            with self.assertRaises(audio_store.AudioError):relay.finish_input(0)
            relay.receive(json.dumps({'serverContent':{'turnComplete':True}}))
            self.assertFalse(relay.completed.is_set())
            relay.receive(json.dumps({'serverContent':{'interrupted':True}}))
            self.assertEqual(relay.snapshot(0)['frames'][0]['type'],'reset')
            with self.assertRaises(audio_store.AudioError):relay.snapshot(2)
            # Release the undispatched fixture without invoking the transport.
            budget.finish(relay.capability,False);audio_store.fail(self.user,relay.job,'synthetic')

    def test_cancel_after_output_settles_valid_samples_and_hides_all_frames(self):
        socket=Socket()
        with self.config(), patch.object(native,'connect',return_value=socket):
            relay=self.make();runner=Thread(target=relay.run);runner.start()
            relay.accept(0,b'\0\0'*1600)
            self.wait(lambda:len(relay.frames)==1)
            sessions.end(self.user,relay.ident);native.cancel(self.user,relay.ident)
            runner.join(3);self.assertFalse(runner.is_alive())
            self.assertEqual(audio_store.get(self.user,relay.job)['seconds_charged'],1)
            self.assertEqual(self.row()['status'],'UNKNOWN')
            self.assertEqual(self.row()['charge_micro'],1000)
            self.assertEqual(relay.frames,[])
            with self.assertRaises(audio_store.AudioError):native.owned(self.user,relay.ident,relay.key)

    def test_budget_cap_and_shared_concurrency_block_another_dispatch(self):
        with self.config():
            relay=self.make()
            other='live-'+'f'*32
            with self.assertRaises(budget.ledger.BudgetError) as error:budget.claim(self.user,relay.ident,other)
            self.assertEqual(error.exception.code,'already_processing')
            budget.dispatch(relay.capability);budget.finish(relay.capability,False)
            audio_store.fail(self.user,relay.job,'synthetic')
            with patch.dict(os.environ,{'KILAS_LIVE_GEMINI_LEASE_RESERVE_MICRO_USD':'5000'}):
                with self.assertRaises(budget.ledger.BudgetError) as error:budget.claim(self.user,relay.ident,other)
                self.assertEqual(error.exception.code,'budget_limit')

    def test_native_transport_uses_header_auth_one_fixed_origin_and_no_other_provider(self):
        with self.config(), patch('websocket.create_connection') as connection:
            native.connect()
            args, kwargs = connection.call_args
            self.assertEqual(args,(native.URL,))
            self.assertNotIn('key=',args[0])
            self.assertEqual(kwargs['header'],{'x-goog-api-key':'synthetic-native-key-not-real'})
            self.assertEqual(kwargs['redirect_limit'],0)
        with self.config(ELEVENLABS_API_KEY='',OPENAI_API_KEY=''):
            self.assertTrue(native.ready(self.user))

    def test_campaign_revocation_before_dispatch_cancels_without_connecting(self):
        with self.config():
            relay=self.make()
            audio.f.db.execute('UPDATE kilas_vo_stt_campaigns SET blocked=1 WHERE id=?',('gml-synthetic-gemini-'+str(self.user),))
            with patch.object(native,'connect') as connect:
                relay.run()
                connect.assert_not_called()
            self.assertEqual(self.row()['status'],'CANCELLED')
            self.assertEqual(self.row()['charge_micro'],0)

    def test_foreign_owner_cannot_read_push_finish_or_end_native_session(self):
        from auth_test_helpers import authenticate
        with self.config():
            relay=self.make()
            authenticate(self.client,audio.f.repo.get_user_by_id(self.other),_csrf_token='audio-csrf')
            base='/kilas-translator/live/gemini/sessions/'+relay.ident+'/turns/'+relay.key
            self.assertEqual(self.client.get(base).status_code,404)
            self.assertEqual(self.client.post(base+'/finish',data={'count':'1','csrf_token':'audio-csrf'}).status_code,404)
            self.assertEqual(self.client.post('/kilas-translator/live/sessions/'+relay.ident+'/end',data={'csrf_token':'audio-csrf'}).status_code,404)
            self.assertEqual(sessions.status(self.user,relay.ident)['status'],'ACTIVE')
            budget.finish(relay.capability,False);audio_store.fail(self.user,relay.job,'synthetic')

    def test_legacy_active_session_is_not_reset_and_csrf_still_protects_native_admission(self):
        with self.config():
            self.credit(300)
            existing=sessions.create(self.user,'id','en','kilas-male')
            self.addCleanup(lambda:sessions.end(self.user,existing))
            fields={'language_a':'id','language_b':'en','consent':'gemini-live-v1'}
            self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data=fields).status_code,400)
            fields['csrf_token']='audio-csrf'
            self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data=fields).status_code,409)
            self.assertEqual(sessions.status(self.user,existing)['status'],'ACTIVE')


if __name__=='__main__':
    unittest.main()
