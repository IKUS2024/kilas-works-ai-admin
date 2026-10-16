"""Disposable DB and synthetic protocol only: never mic or paid provider IO."""
import base64
import json
import os
from pathlib import Path
from unittest.mock import patch
import unittest
import test_kilas_live_gemini as fixture
from kilas_ai import ai_call as calls, ai_call_budget as budget, ai_call_readiness
from kilas_ai import live_gemini as native, live_translator_store as sessions

audio=fixture.audio
PCM=b'\x01\0'*2400


class CallTests(unittest.TestCase):
    setUp=fixture.GeminiTests.setUp
    config=fixture.GeminiTests.config
    shared=fixture.GeminiTests.shared
    lifetime=fixture.GeminiTests.lifetime
    login_other=fixture.GeminiTests.login_other

    def enabled(self):
        from contextlib import ExitStack
        stack=ExitStack()
        stack.enter_context(self.config(KILAS_LIVE_GEMINI_ENABLED='false',KILAS_AI_CALL_ENABLED='true',KILAS_AI_ENABLED='true'))
        stack.enter_context(self.shared())
        self.addCleanup(stack.close)
        with budget.transaction() as conn:budget.ledger._campaign(conn,budget.config()['base'])
        return stack

    def make(self,ident=None):
        ident=ident or format(self.user,'032x')
        with patch.object(calls.Thread,'start'):call=calls.start(self.user,ident)
        self.addCleanup(lambda:calls._calls.pop((self.user,ident),None))
        self.addCleanup(lambda:calls.end(self.user,ident))
        return call

    def post(self,path,data=None):
        return self.client.post(path,headers={'X-CSRF-Token':'audio-csrf'},data=data)

    def retained(self,ident):
        row=budget.owned(self.user,ident)
        return row['status'],row['charge_micro']

    def test_gate_is_separate_and_readiness_never_admits_or_calls_provider(self):
        with self.enabled(),patch.object(native,'connect') as connect:
            self.assertIsNone(budget.native.policy())
            self.assertTrue(calls.ready(self.user));self.assertTrue(calls.ready(self.other))
            before=audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_vo_stt_operations')['n']
            for _ in range(2):
                report=ai_call_readiness.report()
                self.assertTrue(report['configured_ready']);self.assertFalse(report['model_access_verified'])
                self.assertTrue(report['nonowner']['configured_ready'])
                self.assertTrue(self.client.get('/kilas-ai/call/readiness').json['available'])
            self.assertEqual(audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_vo_stt_operations')['n'],before)
            with patch.dict(os.environ,{'KILAS_AI_CALL_ENABLED':'false'}):
                self.assertFalse(calls.ready(self.user))
                with self.assertRaises(calls.CallError):calls.start(self.user,'a'*32)
            connect.assert_not_called()

    def test_existing_source_campaign_is_required_and_blocking_revokes_call(self):
        with self.enabled():
            base=budget.config()['base']['id']
            audio.f.db.execute('DELETE FROM kilas_vo_stt_campaigns WHERE id=?',(base,))
            with self.assertRaises(budget.ledger.BudgetError):budget.claim(self.user,'b'*32)
            with budget.transaction() as conn:budget.ledger._campaign(conn,budget.config()['base'])
            call=self.make();self.assertTrue(budget.active(self.user,call.ident))
            audio.f.db.execute('UPDATE kilas_vo_stt_campaigns SET blocked=1 WHERE id=?',(base,))
            self.assertFalse(calls.ready(self.user) and self.client.get('/kilas-ai/call/readiness').json['available'])
            with self.assertRaises(budget.ledger.BudgetError):call.check()
            # End still settles owned leases under a revoked policy.
            calls.end(self.user,call.ident)
            self.assertEqual(self.retained(call.ident),('CANCELLED',0))

    def test_call_campaign_block_is_reported_and_stops_next_send(self):
        with self.enabled():
            call=self.make();budget.dispatch(call.capability)
            audio.f.db.execute('UPDATE kilas_vo_stt_campaigns SET blocked=1 WHERE id=?',(budget.config()['id'],))
            self.assertFalse(budget.status(self.other)['available'])
            with self.assertRaises(calls.CallError):call.accept(0,PCM)
            calls.end(self.user,call.ident)
            self.assertEqual(self.retained(call.ident),('UNKNOWN',250000))

    def test_dispatch_retains_full_existing_reserve_and_end_before_start_fences_late_admission(self):
        with self.enabled():
            budget.end(self.user,'b'*32)
            with self.assertRaises(budget.ledger.BudgetError):budget.claim(self.user,'b'*32)
            call=self.make();budget.dispatch(call.capability)
            with patch.dict(os.environ,{'KILAS_AI_CALL_ENABLED':'false'}):calls.end(self.user,call.ident)
            self.assertEqual(self.retained(call.ident),('UNKNOWN',250000))
            budget.finish(call.capability)
            self.assertEqual(budget.owned(self.user,call.ident)['charge_micro'],250000)
            self.assertFalse(call.ws)

    def test_old_history_and_new_calls_share_one_cap_without_campaign_reset(self):
        with self.enabled():
            initial=budget.status(self.user)['remaining_micro_usd']
            call=self.make();budget.dispatch(call.capability);calls.end(self.user,call.ident)
            self.assertEqual(budget.status(self.other)['remaining_micro_usd'],initial-250000)
            with patch.dict(os.environ,{'KILAS_LIVE_GEMINI_ENABLED':'true'}):
                self.assertEqual(budget.native.status(self.other)['remaining_micro_usd'],initial-250000)
            row=budget.owned(self.user,call.ident)
            audio.f.db.execute('UPDATE kilas_vo_stt_operations SET charge_micro=? WHERE user_id=? AND operation_key=?',(row['charge_micro']+initial-250000,self.user,budget.key(call.ident)))
            self.assertEqual(budget.status(self.other)['reason'],'budget_limit')
            with self.assertRaises(budget.ledger.BudgetError):budget.claim(self.other,'b'*32)
            # Remove only the synthetic extra charge; never a production ledger.
            audio.f.db.execute('UPDATE kilas_vo_stt_operations SET charge_micro=250000 WHERE user_id=? AND operation_key=?',(self.user,budget.key(call.ident)))

    def test_csrf_owner_and_concurrent_operation_fences(self):
        with self.enabled(),patch.object(native,'connect') as connect:
            path='/kilas-ai/call/'+'a'*32
            self.assertIn(self.client.post(path).status_code,(400,403))
            call=self.make()
            path='/kilas-ai/call/'+call.ident
            for suffix in ('','/chunks/0','/end'):
                self.assertIn(self.client.post(path+suffix).status_code,(400,403))
            with self.assertRaises(budget.ledger.BudgetError) as error:budget.claim(self.user,'c'*32)
            self.assertEqual(error.exception.code,'already_processing')
            self.login_other('CLIENT_OWNER')
            self.assertEqual(self.client.get(path).status_code,404)
            self.assertEqual(self.post(path+'/end').status_code,404)
            self.assertEqual(self.post(path+'/chunks/0',PCM).status_code,404)
            self.assertFalse(call.closed.is_set())
            connect.assert_not_called()

    def test_server_accepts_sequential_bounded_pcm_only(self):
        with self.enabled():
            call=self.make();call.accept(0,PCM)
            self.assertEqual(call.expected,1)
            for index,raw in ((0,PCM),(1,b'x'),(1,PCM*4)):
                with self.assertRaises(calls.CallError):call.accept(index,raw)
            for i in range(1,53):call.accept(i,PCM)
            with self.assertRaises(calls.CallError) as error:call.accept(53,PCM)
            self.assertEqual(error.exception.code,'call_backlog')

    def test_output_frames_all_parts_transcript_and_four_turn_limit(self):
        with self.enabled():
            call=self.make()
            part={'inlineData':{'mimeType':'audio/pcm;rate=24000','data':base64.b64encode(PCM).decode()}}
            for turn in range(4):
                call.receive(json.dumps({'serverContent':{'modelTurn':{'parts':[part,part]},'outputTranscription':{'text':'Answer'},'turnComplete':True}}))
            snapshot=call.snapshot(0)
            self.assertEqual(snapshot['state'],'CLOSED');self.assertEqual(snapshot['code'],'call_limit')
            self.assertEqual(sum(x['type']=='audio' for x in snapshot['frames']),8)
            self.assertEqual(call.output_bytes,8*len(PCM))
            self.assertEqual(sum(x['type']=='turn_complete' for x in snapshot['frames']),4)
            calls.end(self.user,call.ident)
            self.assertEqual(call.frames,[]);self.assertEqual(call.caption,'')
            self.assertEqual(audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs WHERE user_id=?',(self.user,))['n'],0)

    def test_bad_audio_provider_events_and_output_overflow_fail_closed(self):
        with self.enabled():
            call=self.make()
            for raw in ('{"error":{"message":"secret"}}','{"toolCall":{}}','{"serverContent":null}',
                        '{"serverContent":{"modelTurn":{"parts":[{"inlineData":{"mimeType":"audio/mp3","data":"eA=="}}]}}}'):
                with self.assertRaises(calls.CallError):call.receive(raw)
            call.output_bytes=calls.OUTPUT_BYTES
            with self.assertRaises(calls.CallError):call.receive(json.dumps({'serverContent':{'modelTurn':{'parts':[{'inlineData':{'mimeType':'audio/pcm;rate=24000','data':base64.b64encode(PCM).decode()}}]}}}))

    def test_end_during_connection_never_sends_setup_and_keeps_dispatch_charge(self):
        with self.enabled():
            call=self.make();socket=fixture.Socket()
            def connect():calls.end(self.user,call.ident);return socket
            with patch.object(native,'connect',side_effect=connect):call.run()
            self.assertEqual(socket.sent,[]);self.assertTrue(socket.closed)
            self.assertEqual(self.retained(call.ident),('UNKNOWN',250000))

    def test_dispatch_before_handshake_failure_and_no_retry(self):
        with self.enabled():
            call=self.make()
            def connect():
                self.assertEqual(budget.owned(self.user,call.ident)['status'],'DISPATCHED')
                raise OSError('synthetic secret not exposed')
            with patch.object(native,'connect',side_effect=connect) as mocked:call.run()
            self.assertEqual(mocked.call_count,1)
            self.assertEqual(call.code,'call_transport')
            self.assertEqual(self.retained(call.ident),('UNKNOWN',250000))

    def test_synthetic_duplex_handshake_stream_and_owner_end(self):
        with self.enabled():
            call=self.make();socket=fixture.Socket()
            with patch.object(native,'connect',return_value=socket):
                worker=fixture.Thread(target=call.run,daemon=True);worker.start()
                try:
                    fixture.GeminiTests.wait(self,lambda:call.state=='LISTENING')
                    call.accept(0,PCM)
                    self.assertTrue(socket.first.wait(2))
                    fixture.GeminiTests.wait(self,lambda:bool(call.frames))
                    result=self.client.get('/kilas-ai/call/'+call.ident)
                    self.assertEqual(result.status_code,200)
                    self.assertEqual(result.headers['Cache-Control'],'private, no-store')
                    self.assertTrue(any(frame['type']=='audio' for frame in result.json['frames']))
                    self.assertEqual(socket.sent[0]['setup']['model'],'models/gemini-3.8-live')
                    self.assertEqual(socket.sent[1]['realtimeInput']['audio']['mimeType'],'audio/pcm;rate=16000')
                    self.assertNotIn('synthetic-native-key-not-real',result.text)
                    # The same form-token End is used by page-exit sendBeacon.
                    response=self.client.post('/kilas-ai/call/'+call.ident+'/end',data={'csrf_token':'audio-csrf'})
                    self.assertEqual(response.status_code,200)
                finally:
                    calls.end(self.user,call.ident);worker.join(3)
                self.assertFalse(worker.is_alive());self.assertTrue(socket.closed)
                self.assertEqual(self.retained(call.ident),('UNKNOWN',250000))

    def test_end_stops_socket_before_database_settlement(self):
        with self.enabled():
            call=self.make();call.ws=fixture.Socket()
            def settle(*args):self.assertTrue(call.closed.is_set());self.assertTrue(call.ws.closed)
            with patch.object(budget,'end',side_effect=settle):calls.end(self.user,call.ident)

    def test_deadline_disconnect_and_disabled_account_close_before_next_audio(self):
        with self.enabled():
            call=self.make()
            with patch.object(calls,'monotonic',return_value=call.started+91):
                with self.assertRaises(calls.CallError) as e:call.accept(0,PCM)
                self.assertEqual(e.exception.code,'call_limit')
            with patch.object(calls,'monotonic',return_value=call.last_seen+9):
                with self.assertRaises(calls.CallError) as e:call.check()
                self.assertEqual(e.exception.code,'call_network')
            audio.f.db.execute('INSERT INTO customer_auth_account_state(user_id,disabled) VALUES (?,1) ON CONFLICT(user_id) DO UPDATE SET disabled=1',(self.user,))
            with self.assertRaises(calls.CallError):call.accept(0,PCM)

    def test_general_conversation_schema_and_server_only_key(self):
        setup=calls.setup()['setup']
        self.assertEqual(setup['model'],'models/gemini-3.8-live')
        self.assertNotIn('translationConfig',setup['generationConfig'])
        for forbidden in ('tools','thinkingConfig','sessionResumption','inputAudioTranscription'):
            self.assertNotIn(forbidden,setup)
        self.assertEqual(setup['generationConfig']['responseModalities'],['AUDIO'])
        self.assertEqual(setup['generationConfig']['maxOutputTokens'],1024)
        self.assertEqual(setup['realtimeInputConfig']['activityHandling'],'NO_INTERRUPTION')
        self.assertIn('new conversation',setup['systemInstruction']['parts'][0]['text'])

    def test_real_templates_localized_button_beside_send_without_provider_io(self):
        pages={}
        with self.enabled(),patch.object(native,'connect') as connect:
            for locale in ('en','id','es','zh'):
                self.client.set_cookie('kilas_language',locale)
                response=self.client.get('/kilas-ai',follow_redirects=True)
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.text.count('id="ai-call-dialog"'),1)
                self.assertIn('data-ai-call-launch',response.text)
                self.assertIn('Start AI call' if locale=='en' else 'Mulai panggilan AI' if locale=='id' else 'Iniciar llamada de IA' if locale=='es' else '开始AI通话',response.text)
                self.assertNotIn('synthetic-native-key-not-real',response.text)
                pages[locale]=response.text
            self.assertIsNone(sessions.active(self.user));connect.assert_not_called()
        target=os.environ.get('KILAS_AI_CALL_UI_FIXTURE_PATH')
        if target:Path(target).write_text(json.dumps(pages),encoding='utf-8')


if __name__=='__main__':unittest.main()
