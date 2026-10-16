"""Disposable SQLite + synthetic socket only; no real credentials or provider IO."""
import base64
import json
import os
from pathlib import Path
import time
import unittest
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
