"""Disposable DB and synthetic protocol only: never mic or paid provider IO."""
import base64
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch
import unittest
from datetime import timedelta
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
            with self.assertRaises(calls.CallError):call.check()
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

    def test_output_frames_continue_past_four_responses_with_metered_renewal(self):
        with self.enabled():
            call=self.make();budget.dispatch(call.capability)
            part={'inlineData':{'mimeType':'audio/pcm;rate=24000','data':base64.b64encode(PCM).decode()}}
            for turn in range(9):
                call.receive(json.dumps({'serverContent':{'modelTurn':{'parts':[part,part]},'outputTranscription':{'text':'Answer'},'turnComplete':True}}))
            snapshot=call.snapshot(0)
            self.assertEqual(snapshot['state'],'LISTENING');self.assertIsNone(snapshot['code'])
            self.assertEqual(call.turns,9);self.assertFalse(call.closed.is_set())
            self.assertEqual(call.output_bytes,18*len(PCM))
            self.assertEqual(budget.owned(self.user,call.ident)['charge_micro'],250000)
            rows=audio.f.db.query_one('SELECT COUNT(*) AS n,SUM(charge_micro) AS charge FROM kilas_vo_stt_operations WHERE user_id=? AND fingerprint=?',(self.user,hashlib.sha256(('call:'+call.ident).encode()).hexdigest()))
            self.assertEqual((rows['n'],rows['charge']),(3,750000))
            calls.end(self.user,call.ident)
            self.assertEqual(call.frames,[]);self.assertEqual(call.caption,'')
            self.assertEqual(audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs WHERE user_id=?',(self.user,))['n'],0)

    def test_bad_audio_provider_events_fail_closed_and_audio_limits_renew_funding(self):
        with self.enabled():
            call=self.make()
            for raw in ('{"error":{"message":"secret"}}','{"toolCall":{}}','{"serverContent":null}',
                        '{"serverContent":{"modelTurn":{"parts":[{"inlineData":{"mimeType":"audio/mp3","data":"eA=="}}]}}}'):
                with self.assertRaises(calls.CallError):call.receive(raw)
            budget.dispatch(call.capability);call.output_bytes=calls.OUTPUT_BYTES
            previous=call.capability
            call.receive(json.dumps({'serverContent':{'modelTurn':{'parts':[{'inlineData':{'mimeType':'audio/pcm;rate=24000','data':base64.b64encode(PCM).decode()}}]}}}))
            self.assertNotEqual(call.capability,previous);self.assertEqual(call.output_bytes,calls.OUTPUT_BYTES+len(PCM))

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
                    fixture.GeminiTests.wait(self,lambda:call.sent_bytes==len(PCM))
                    self.assertEqual(call.sent_chunks,1)
                    self.assertEqual(base64.b64decode(socket.sent[1]['realtimeInput']['audio']['data']),PCM)
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

    def test_deadline_removed_but_disconnect_and_disabled_account_still_stop(self):
        with self.enabled():
            call=self.make();budget.dispatch(call.capability);previous=call.capability
            call.last_seen=call.started+91
            with patch.object(calls,'monotonic',return_value=call.started+91):
                call.check()
                call.accept(0,PCM)
                self.assertNotEqual(call.capability,previous)
                self.assertTrue(budget.active(self.user,call.ident,call.capability))
            with patch.object(calls,'monotonic',return_value=call.last_seen+9):
                with self.assertRaises(calls.CallError) as e:call.check()
                self.assertEqual(e.exception.code,'call_network')
            audio.f.db.execute('INSERT INTO customer_auth_account_state(user_id,disabled) VALUES (?,1) ON CONFLICT(user_id) DO UPDATE SET disabled=1',(self.user,))
            self.assertNotEqual(self.post('/kilas-ai/call/'+call.ident+'/chunks/0',PCM).status_code,200)
            with self.assertRaises(calls.CallError):call.check()
            with self.assertRaises(calls.CallError):call.accept(0,PCM)

    def test_slow_policy_transaction_cannot_block_pcm_dispatch_or_provider_frames(self):
        import threading
        import time
        with self.enabled():
            call=self.make();call.ws=fixture.Socket()
            entered=threading.Event();release=threading.Event();errors=[]
            def slow(*args):
                entered.set();release.wait(2);return True
            def refresh():
                try:call.check()
                except Exception as error:errors.append(error)
            with patch.object(calls,'ready',return_value=True),patch.object(budget,'active',side_effect=slow):
                checker=threading.Thread(target=refresh,daemon=True);checker.start();self.assertTrue(entered.wait(1))
                sender=None
                try:
                    before=time.monotonic();call.accept(0,PCM)
                    self.assertLess(time.monotonic()-before,.1)
                    sender=threading.Thread(target=call.send,daemon=True);sender.start()
                    self.assertTrue(call.ws.first.wait(.2))
                    before=time.monotonic()
                    call.receive('{"serverContent":{"inputTranscription":{"text":"synthetic"}}}')
                    self.assertLess(time.monotonic()-before,.1)
                    self.assertEqual(call.input_transcript_chars,9)
                    self.assertFalse(release.is_set())
                finally:
                    release.set();checker.join(2);call.stop()
                    if sender:sender.join(2)
            self.assertEqual(errors,[])
            self.assertEqual(call.sent_bytes,len(PCM))

    def test_expired_watchdog_authorization_fails_closed_without_packet_database_io(self):
        with self.enabled():
            call=self.make();now=call.started+calls.POLICY_TTL_SECONDS+.01;call.last_seen=now
            with patch.object(calls,'monotonic',return_value=now), \
                 patch.object(calls,'ready',side_effect=AssertionError('packet queried owner')), \
                 patch.object(budget,'active',side_effect=AssertionError('packet opened transaction')):
                with self.assertRaises(calls.CallError):call.accept(0,PCM)
            self.assertEqual(call.input_bytes,0)
            self.assertEqual(call.expected,0)

    def test_end_during_policy_transaction_cannot_refresh_or_send_late_audio(self):
        import threading
        with self.enabled():
            call=self.make();entered=threading.Event();release=threading.Event();errors=[]
            until=call.authorized_until
            def slow(*args):entered.set();release.wait(2);return True
            def refresh():
                try:call.check()
                except Exception as error:errors.append(error.code)
            with patch.object(calls,'ready',return_value=True),patch.object(budget,'active',side_effect=slow):
                worker=threading.Thread(target=refresh,daemon=True);worker.start();self.assertTrue(entered.wait(1))
                call.stop();release.set();worker.join(2)
            self.assertTrue(call.closed.is_set());self.assertEqual(errors,['call_ended'])
            self.assertEqual(call.authorized_until,until)
            with self.assertRaises(calls.CallError):call.accept(0,PCM)

    def test_watchdog_result_older_than_transport_lease_cannot_reauthorize_audio(self):
        with self.enabled():
            call=self.make();now=[call.started]
            def stale(*args):now[0]+=calls.POLICY_TTL_SECONDS+.1;return True
            with patch.object(calls,'monotonic',side_effect=lambda:now[0]), \
                 patch.object(calls,'ready',return_value=True),patch.object(budget,'active',side_effect=stale):
                with self.assertRaises(calls.CallError):call.check()
                with self.assertRaises(calls.CallError):call.accept(0,PCM)
            self.assertEqual(call.authorized_until,0)
            self.assertEqual(call.input_bytes,0)

    def test_general_conversation_schema_and_server_only_key(self):
        with patch.object(calls.public_search,'configured',return_value=False):
            setup=calls.setup()['setup']
        self.assertEqual(setup['model'],'models/gemini-3.8-live')
        self.assertNotIn('translationConfig',setup['generationConfig'])
        for forbidden in ('tools','thinkingConfig'):
            self.assertNotIn(forbidden,setup)
        self.assertEqual(setup['inputAudioTranscription'],{})
        self.assertEqual(setup['realtimeInputConfig']['automaticActivityDetection']['silenceDurationMs'],1200)
        self.assertEqual(setup['sessionResumption'],{})
        self.assertEqual(calls.setup('checkpoint')['setup']['sessionResumption'],{'handle':'checkpoint'})
        self.assertIn('slidingWindow',setup['contextWindowCompression'])
        self.assertEqual(setup['generationConfig']['responseModalities'],['AUDIO'])
        self.assertEqual(setup['generationConfig']['maxOutputTokens'],1024)
        self.assertEqual(setup['realtimeInputConfig']['activityHandling'],'NO_INTERRUPTION')
        self.assertIn('new conversation',setup['systemInstruction']['parts'][0]['text'])

    def test_input_diagnostics_count_quiet_pcm_and_transcription_without_retaining_content(self):
        with self.enabled():
            call=self.make();raw=b'\x00\x01'*3200
            call.accept(0,raw)
            self.assertEqual(call.input_samples,3200)
            self.assertAlmostEqual(call.input_peak,1/128)
            self.assertAlmostEqual(call.input_energy/call.input_samples,(1/128)**2)
            call.receive(json.dumps({'serverContent':{'inputTranscription':{'text':'synthetic question'}}}))
            self.assertEqual(call.input_transcript_chars,18)
            self.assertEqual(call.frames,[])
            self.assertNotIn('synthetic question',str(vars(call)))
            with self.assertRaises(calls.CallError):call.receive('{"serverContent":{"inputTranscription":{"text":7}}}')

    def test_public_lookup_uses_normal_usage_ledger_once_and_end_clears_current_speech(self):
        import time
        from kilas_ai import ai_call_public_search as search
        with self.enabled(),patch.dict(os.environ,{'OPENAI_API_KEY':'offline-not-a-key',
                'KILAS_AI_OPENAI_WEB_MODEL':'gpt-6.1-sol','KILAS_AI_CALL_PUBLIC_SEARCH_ENABLED':'true'}):
            call=self.make();messages=[]
            class Socket:
                def send(self,raw):messages.append(json.loads(raw))
                def shutdown(self):pass
            call.ws=Socket()
            result={'text':'Synthetic public finding.','citations':[{'url':'https://example.org/news','title':'Synthetic source'}],
                    'model':'gpt-6.1-sol','usage':{'input_tokens':10,'output_tokens':3,'web_search_calls':1}}
            with patch.object(search.tools,'web_search_steps',return_value=iter([{'result':result}])) as lookup:
                call.receive(json.dumps({'voiceActivity':{'type':'ACTIVITY_START'}}))
                call.receive(json.dumps({'serverContent':{'inputTranscription':{
                    'text':'Gimana keadaan Indonesia sekarang?'}}}))
                call.receive(json.dumps({'voiceActivity':{'type':'ACTIVITY_END'}}))
                message={'toolCall':{'functionCalls':[{'id':'public-one','name':search.NAME,'args':{'country':'ID','topic':'general'}}]}}
                call.receive(json.dumps(message))
                until=time.monotonic()+2
                while call.public_search.job is not None and time.monotonic()<until:time.sleep(.01)
                self.assertIsNone(call.public_search.job)
                call.receive(json.dumps(message));lookup.assert_called_once()
            row=audio.f.db.query_one("SELECT COUNT(*) AS n,MIN(status) AS status FROM kilas_ai_usage WHERE user_id=? AND operation_key LIKE 'call-web-%' AND operation_type='WEB_SEARCH'",(self.user,))
            self.assertEqual((row['n'],row['status']),(1,'COMPLETE'))
            self.assertTrue(messages[0]['toolResponse']['functionResponses'][0]['response']['available'])
            self.assertEqual(call.frames[0]['type'],'sources')
            calls.end(self.user,call.ident)
            self.assertEqual(call.public_search.buffer,'');self.assertEqual(call.frames,[])

    def test_renewal_keeps_shared_cap_and_end_fences_every_envelope(self):
        with self.enabled():
            call=self.make();budget.dispatch(call.capability)
            before=budget.status(self.other)['remaining_micro_usd']
            previous=call.capability
            call.capability=budget.renew(previous)
            self.assertEqual(budget.owned(self.user,call.ident)['status'],'UNKNOWN')
            self.assertEqual(budget.status(self.other)['remaining_micro_usd'],before-250000)
            with self.assertRaises(budget.ledger.BudgetError):budget.renew(previous)
            calls.end(self.user,call.ident)
            self.assertFalse(budget.active(self.user,call.ident,call.capability))
            with self.assertRaises(budget.ledger.BudgetError):budget.renew(call.capability)
            self.assertEqual(audio.f.db.query_one("SELECT COUNT(*) AS n FROM kilas_vo_stt_operations WHERE user_id=? AND status IN ('RESERVED','DISPATCHED')",(self.user,))['n'],0)

    def paid_account(self):
        now=budget.usage._now()
        audio.f.db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PRO','ACTIVE',?,?)",(self.user,(now-timedelta(days=1)).isoformat(),(now+timedelta(days=29)).isoformat()))

    def test_paid_account_uses_existing_premium_capacity_not_exhausted_trial_funding(self):
        with self.enabled():
            self.paid_account()
            with patch.object(budget.native,'_spend',return_value=budget.config()['global_micro']):
                self.assertTrue(budget.status(self.user)['available'])
                self.assertEqual(budget.status(self.user)['funding'],'account')
                self.assertFalse(budget.status(self.other)['available'])
                call=self.make();budget.dispatch(call.capability)
                call.capability=budget.renew(call.capability)
            rows=audio.f.db.query_one("SELECT COUNT(*) AS n,SUM(CAST(estimated_cost_usd AS REAL)) AS cost FROM kilas_ai_usage WHERE user_id=? AND operation_type='AI_CALL' AND status='COMPLETE'",(self.user,))
            self.assertEqual((rows['n'],rows['cost']),(2,.5))
            calls.end(self.user,call.ident)
            self.assertEqual(audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs WHERE user_id=?',(self.user,))['n'],0)

    def test_paid_account_credit_exhaustion_still_blocks_new_call_and_renewal(self):
        from kilas_ai import capacity
        with self.enabled():
            self.paid_account();call=self.make();budget.dispatch(call.capability)
            now=budget.usage._now().isoformat()
            audio.f.db.execute("INSERT INTO kilas_ai_usage(user_id,operation_key,operation_type,mode,status,quota_source,estimated_cost_usd,created_at) VALUES (?,'existing-premium-spend','IMAGE_GENERATION','SMART','COMPLETE','BASE',?,?)",(self.user,str(capacity.allowance()),now))
            self.assertEqual(budget.status(self.user)['reason'],'account_credit_limit')
            with self.assertRaises(budget.ledger.BudgetError) as error:budget.renew(call.capability)
            self.assertEqual(error.exception.code,'account_credit_limit')
            calls.end(self.user,call.ident)
            with self.assertRaises(budget.ledger.BudgetError) as error:budget.claim(self.user,'f'*32)
            self.assertEqual(error.exception.code,'account_credit_limit')

    def test_existing_sponsorship_is_metered_without_resetting_the_trial_ledger(self):
        with self.enabled(),patch.object(budget.usage,'_qa_quota_exempt',return_value=True):
            with patch.object(budget.native,'_spend',return_value=budget.config()['global_micro']):
                self.assertTrue(budget.status(self.user)['available'])
                call=self.make();budget.dispatch(call.capability)
                call.capability=budget.renew(call.capability)
            self.assertEqual(self.retained(call.ident),('UNKNOWN',250000))
            self.assertTrue(budget.active(self.user,call.ident,call.capability))
            calls.end(self.user,call.ident)

    def test_account_undispatched_end_releases_only_its_own_pending_usage(self):
        with self.enabled():
            self.paid_account();call=self.make();calls.end(self.user,call.ident)
            row=audio.f.db.query_one("SELECT status,estimated_cost_usd FROM kilas_ai_usage WHERE user_id=? AND operation_key=? AND operation_type='AI_CALL'",(self.user,call.capability.key))
            self.assertEqual((row['status'],row['estimated_cost_usd']),('FAILED',None))

    def test_paid_topup_debits_are_reserved_before_dispatch_and_retained_once(self):
        from kilas_ai import capacity, topups
        with self.enabled():
            self.paid_account();now=budget.usage._now()
            audio.f.db.execute("INSERT INTO kilas_ai_usage(user_id,operation_key,operation_type,mode,status,quota_source,estimated_cost_usd,created_at) VALUES (?,'existing-premium-spend','IMAGE_GENERATION','SMART','COMPLETE','BASE',?,?)",(self.user,str(capacity.allowance()),now.isoformat()))
            order=topups.create_order(self.user,'EXTRA')
            audio.f.db.execute("UPDATE kilas_ai_topup_orders SET status='VERIFIED' WHERE id=?",(order,))
            audio.f.db.execute('INSERT INTO kilas_ai_topup_credits(order_id,user_id,total_micro,expires_at) VALUES (?,?,500000,?)',(order,self.user,(now+timedelta(days=5)).isoformat()))
            call=self.make()
            row=audio.f.db.query_one('SELECT status,reserved_micro,charged_micro FROM kilas_ai_topup_debits WHERE user_id=? AND operation_key=?',(self.user,call.capability.key))
            self.assertEqual((row['status'],row['reserved_micro'],row['charged_micro']),('PENDING',250000,0))
            budget.dispatch(call.capability);call.capability=budget.renew(call.capability)
            with self.assertRaises(budget.ledger.BudgetError) as error:budget.renew(call.capability)
            self.assertEqual(error.exception.code,'account_credit_limit')
            calls.end(self.user,call.ident);calls.end(self.user,call.ident)
            row=audio.f.db.query_one("SELECT COUNT(*) AS n,SUM(charged_micro) AS charge FROM kilas_ai_topup_debits WHERE user_id=? AND status='COMPLETE'",(self.user,))
            self.assertEqual((row['n'],row['charge']),(2,500000))

    def test_exhausted_shared_budget_denies_renewal_without_releasing_prior_cost(self):
        with self.enabled():
            call=self.make();budget.dispatch(call.capability)
            maximum=budget.config()['global_micro']
            audio.f.db.execute('UPDATE kilas_vo_stt_operations SET charge_micro=? WHERE user_id=? AND operation_key=?',(maximum,self.user,call.capability.key))
            with self.assertRaises(budget.ledger.BudgetError) as error:budget.renew(call.capability)
            self.assertEqual(error.exception.code,'budget_limit')
            calls.end(self.user,call.ident)
            self.assertEqual(self.retained(call.ident),('UNKNOWN',maximum))
            # Remove the synthetic extra charge from this disposable shared DB.
            audio.f.db.execute('UPDATE kilas_vo_stt_operations SET charge_micro=250000 WHERE user_id=? AND operation_key=?',(self.user,call.capability.key))

    def test_acknowledged_audio_does_not_accumulate_or_reset_long_call_cursor(self):
        with self.enabled():
            call=self.make();cursor=0
            for _ in range(2200):
                call.publish({'type':'turn_complete'})
                value=call.snapshot(cursor)
                self.assertEqual(value['frames'][0]['index'],cursor)
                cursor=value['next_index']
                self.assertLessEqual(len(call.frames),1)
            self.assertEqual(call.snapshot(cursor)['frames'],[])
            with self.assertRaises(calls.CallError):call.snapshot(cursor-1)

    def test_provider_expiry_requires_fresh_checkpoint_and_preserves_accepted_audio(self):
        with self.enabled():
            call=self.make();budget.dispatch(call.capability);call.ws=fixture.Socket()
            call.provider_started-=31
            call.publish({'type':'text','text':'Already delivered'})
            call.receive(json.dumps({'sessionResumptionUpdate':{'resumable':True,'newHandle':'stale'}}))
            call.receive(json.dumps({'goAway':{'timeLeft':'30s'}}))
            self.assertFalse(call.resume_pending);self.assertTrue(call.renewing.is_set())
            call.receive(json.dumps({'sessionResumptionUpdate':{'resumable':False}}))
            self.assertFalse(call.resume_pending)
            call.receive(json.dumps({'sessionResumptionUpdate':{'resumable':True,'newHandle':'fresh'}}))
            socket=fixture.Socket()
            with patch.object(native,'connect',return_value=socket) as connect:call.resume()
            self.assertEqual(connect.call_count,1)
            self.assertEqual(socket.sent[0]['setup']['sessionResumption'],{'handle':'fresh'})
            self.assertEqual(len(socket.sent),1)  # No replay of any input PCM.
            self.assertEqual(call.snapshot(0)['frames'][0]['text'],'Already delivered')
            self.assertFalse(call.renewing.is_set())
            with self.assertRaises(calls.CallError):call.receive('{"goAway":{}}')
            calls.end(self.user,call.ident)
            with patch.object(native,'connect') as connect:
                with self.assertRaises(calls.CallError):call.resume()
                connect.assert_not_called()

    def test_end_during_resumption_closes_late_socket_without_setup(self):
        with self.enabled():
            call=self.make();budget.dispatch(call.capability);call.ws=fixture.Socket()
            call.provider_started-=31
            call.receive('{"goAway":{}}')
            call.receive('{"sessionResumptionUpdate":{"resumable":true,"newHandle":"fresh"}}')
            socket=fixture.Socket()
            def connect():calls.end(self.user,call.ident);return socket
            with patch.object(native,'connect',side_effect=connect):
                with self.assertRaises(calls.CallError):call.resume()
            self.assertTrue(socket.closed);self.assertEqual(socket.sent,[])

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
