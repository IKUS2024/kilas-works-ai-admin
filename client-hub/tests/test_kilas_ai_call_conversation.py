"""Call opening/control regressions with synthetic sockets; no provider/DB IO.

SDK validation checks accepted message shape, never model speech, semantic
understanding, actual interruption quality, or acoustic echo cancellation.
"""
import base64
import json
from pathlib import Path
import struct
import sys
from threading import Event, Thread
from time import monotonic
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kilas_ai import ai_call as calls, ai_call_conversation as conversation


class Socket:
    def __init__(self,hello=None):
        self.hello={'setupComplete':{}} if hello is None else hello
        self.messages=[];self.closed=False;self.on_send=lambda value:None
    def send(self,raw):
        value=json.loads(raw);self.messages.append(value);self.on_send(value)
    def recv(self):
        if self.hello is None:raise OSError('synthetic end')
        hello=self.hello;self.hello=None;return json.dumps(hello)
    def settimeout(self,value):self.timeout=value
    def shutdown(self):self.closed=True


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.timer=patch.object(calls,'Timer').start()
        self.discard=patch.object(calls.db,'_discard_cached_connection').start()
        # Most cases isolate ordering/once behavior. The real settle interval
        # is tested below with a fake clock, never a blocking wall-clock sleep.
        patch.object(calls,'OPENING_SETTLE_SECONDS',0).start()
        self.addCleanup(patch.stopall)

    def call(self,*,provider_ready=False):
        value=calls.Call(1,'a'*32,object());value.ws=Socket()
        def transport_check(**options):
            if value.closed.is_set():raise calls.CallError('call_ended',409)
        value.transport_check=Mock(side_effect=transport_check)
        value.check=Mock(side_effect=transport_check)
        value.provider_ready=provider_ready
        return value

    def openings(self,call):
        return [value['clientContent'] for value in call.ws.messages if 'clientContent' in value]

    def test_exact_indonesian_copy_and_one_opening_per_call_after_both_ready_fences(self):
        call=self.call()
        self.assertFalse(call.snapshot(0)['provider_ready'])
        call.client_ready('id');self.assertEqual(call.ws.messages,[])
        call.provider_ready=True;self.assertTrue(call._maybe_greet())
        self.assertTrue(call.snapshot(0)['provider_ready'])
        call.client_ready('id');call.client_ready('en');self.assertFalse(call._maybe_greet())
        self.assertEqual(call.opening_language,'id')
        opening=self.openings(call);self.assertEqual(len(opening),1)
        self.assertTrue(opening[0]['turnComplete'])
        self.assertEqual(opening[0]['turns'][0]['parts'][0]['text'].split('\n',1)[1],
            'Halo, aku asisten AI dari Kilas. Aku bisa nemenin kamu latihan interview, belajar bahasa, '
            'ngebahas pekerjaan, atau ide yang lagi kamu pikirkan. Kamu lagi butuh yang mana?')
        self.assertEqual(call.greeting_state,'sent')

    def test_provider_ready_alone_never_greets_direct_diagnostic_calls(self):
        call=self.call(provider_ready=True)
        call.accept(0,bytes(320));self.assertFalse(call._maybe_greet())
        self.assertEqual(call.ws.messages,[])
        self.assertEqual(call.greeting_state,'pending')

    def test_opening_settle_is_nonblocking_and_gives_streamed_speech_priority(self):
        for veto in (None,'activity','transcript','end','handoff'):
            with self.subTest(veto=veto):
                now=[100.0]
                with patch.object(calls,'OPENING_SETTLE_SECONDS',.5),patch.object(calls,'monotonic',side_effect=lambda:now[0]):
                    call=self.call(provider_ready=True);call.client_ready('id')
                    self.assertEqual(call.ws.messages,[]);self.assertEqual(call.opening_ready_at,100.5)
                    now[0]=100.49;call.client_ready('id');self.assertFalse(call._maybe_greet())
                    self.assertEqual(call.opening_ready_at,100.5)
                    if veto=='activity':call.receive('{"voiceActivity":{"type":"ACTIVITY_START"}}')
                    elif veto=='transcript':call.receive('{"serverContent":{"inputTranscription":{"text":"A quiet question"}}}')
                    elif veto=='end':call.stop()
                    elif veto=='handoff':call.provider_ready=False;call.renewing.set()
                    now[0]=100.51
                    self.assertEqual(call._maybe_greet(),veto is None)
                    self.assertEqual(len(self.openings(call)),int(veto is None))

    def test_connection_or_unsent_backlog_cannot_consume_opening_settle(self):
        now=[100.0]
        with patch.object(calls,'OPENING_SETTLE_SECONDS',.5),patch.object(calls,'monotonic',side_effect=lambda:now[0]):
            call=self.call();call.client_ready('id');self.assertIsNone(call.opening_ready_at)
            now[0]=110.0;call.provider_ready=True;call.queued=320
            self.assertFalse(call._maybe_greet());self.assertIsNone(call.opening_ready_at)
            call.queued=0;self.assertFalse(call._maybe_greet());self.assertEqual(call.opening_ready_at,110.5)
            now[0]=110.49;self.assertFalse(call._maybe_greet())
            now[0]=110.51;self.assertTrue(call._maybe_greet());self.assertEqual(len(self.openings(call)),1)

    def test_four_app_locales_and_invalid_or_untyped_ready_flags(self):
        for language in ('id','en','es','zh'):
            with self.subTest(language=language):
                call=self.call(provider_ready=True);call.client_ready(language)
                self.assertEqual(len(self.openings(call)),1)
                self.assertIn(conversation.GREETINGS[language],str(self.openings(call)))
        for language,flag in (('xx',False),([],False),('en',1),('en','false'),('en',None)):
            with self.subTest(language=language,flag=flag):
                call=self.call(provider_ready=True)
                with self.assertRaises(calls.CallError):call.client_ready(language,user_started_speaking=flag)
                self.assertFalse(call.client_is_ready);self.assertEqual(call.ws.messages,[])

    def test_first_user_signal_transcript_or_browser_flag_permanently_wins_race(self):
        for event in ('browser','activity','transcript'):
            with self.subTest(event=event):
                call=self.call(provider_ready=True)
                if event=='activity':call.receive('{"voiceActivity":{"type":"ACTIVITY_START"}}')
                elif event=='transcript':call.receive('{"serverContent":{"inputTranscription":{"text":"Interview buat peran designer"}}}')
                call.client_ready('id',user_started_speaking=event=='browser')
                call.client_ready('en');self.assertFalse(call._maybe_greet())
                self.assertEqual(call.greeting_state,'skipped');self.assertEqual(call.ws.messages,[])
                self.assertTrue(call.opening_user_started)

    def test_quiet_pcm_is_not_a_request_and_buffered_audio_is_sent_before_opening(self):
        call=self.call(provider_ready=True);quiet=struct.pack('<h',1)*160
        call.accept(0,quiet);call.accept(1,bytes(320))
        call.client_ready('id');self.assertEqual(call.ws.messages,[])
        self.assertEqual(call.greeting_state,'pending')
        def sent(value):
            if 'clientContent' in value:call.closed.set()
        call.ws.on_send=sent
        call.send()
        self.assertEqual([next(iter(value)) for value in call.ws.messages],['realtimeInput','realtimeInput','clientContent'])
        self.assertEqual(base64.b64decode(call.ws.messages[0]['realtimeInput']['audio']['data']),quiet)
        self.assertEqual(call.queued,0);self.assertEqual(call.sent_chunks,2)
        self.assertEqual(len(self.openings(call)),1)

    def test_conditioned_ambient_pcm_is_not_mistaken_for_known_user_speech(self):
        call=self.call(provider_ready=True)
        # Existing frontend conditioning can multiply raw .002 room noise by
        # eight. The server must not interpret that post-gain RMS as speech.
        conditioned=struct.pack('<h',round(.002*8*32768))*3200
        call.accept(0,conditioned);call.client_ready('id',user_started_speaking=False)
        call.ws.on_send=lambda value:call.closed.set() if 'clientContent' in value else None
        call.send()
        self.assertEqual(base64.b64decode(call.ws.messages[0]['realtimeInput']['audio']['data']),conditioned)
        self.assertFalse(call.opening_user_started);self.assertEqual(len(self.openings(call)),1)

    def test_audio_dequeued_but_waiting_to_send_still_blocks_opening(self):
        call=self.call(provider_ready=True);call.accept(0,bytes(320))
        blocked=Event();release=Event()
        original_check=call.transport_check
        def transport_check(**options):
            original_check(**options)
            if not blocked.is_set():blocked.set();release.wait(2)
        call.transport_check=Mock(side_effect=transport_check)
        call.ws.on_send=lambda value:call.closed.set() if 'clientContent' in value else None
        sender=Thread(target=call.send,daemon=True);sender.start();self.assertTrue(blocked.wait(1))
        try:
            call.client_ready('en');self.assertEqual(call.ws.messages,[])
            self.assertEqual(call.queued,320)
        finally:release.set();sender.join(2)
        self.assertFalse(sender.is_alive())
        self.assertEqual([next(iter(value)) for value in call.ws.messages],['realtimeInput','clientContent'])

    def test_concurrent_duplicate_ready_requests_send_only_one_opening(self):
        call=self.call(provider_ready=True)
        workers=[Thread(target=lambda:call.client_ready('id')) for _ in range(12)]
        for worker in workers:worker.start()
        for worker in workers:worker.join(1)
        self.assertEqual(len(self.openings(call)),1)

    def test_blocked_opening_socket_cannot_hold_pcm_snapshot_or_end(self):
        call=self.call(provider_ready=True);entered=Event();release=Event()
        call.ws.on_send=lambda value:(entered.set(),release.wait(2))
        worker=Thread(target=lambda:call.client_ready('id'),daemon=True);worker.start()
        self.assertTrue(entered.wait(1))
        try:
            before=monotonic();call.accept(0,bytes(320));self.assertLess(monotonic()-before,.1)
            before=monotonic();call.snapshot(0);self.assertLess(monotonic()-before,.1)
            before=monotonic();call.client_ready('id');self.assertLess(monotonic()-before,.1)
            before=monotonic();call.stop();self.assertLess(monotonic()-before,.1)
            self.assertFalse(call.provider_ready);self.assertTrue(call.ws.closed)
        finally:release.set();worker.join(1)
        self.assertFalse(worker.is_alive());self.assertEqual(len(self.openings(call)),1)

    def test_setup_failure_never_exposes_readiness_or_sends_opening(self):
        for hello in ({'error':{'code':'synthetic'}},{'setupComplete':None},{'setupComplete':{},'goAway':{}}):
            with self.subTest(hello=hello):
                call=self.call();socket=Socket(hello);call.client_ready('id')
                with patch.object(calls.budget,'dispatch'),patch.object(calls.budget,'finish'),\
                     patch.object(calls.wire,'connect',return_value=socket),patch.object(calls.Thread,'start'):
                    call.run()
                self.assertEqual(call.code,'call_provider');self.assertFalse(call.provider_ready)
                self.assertEqual([next(iter(value)) for value in socket.messages],['setup'])

    def test_valid_setup_can_open_only_after_checked_hello_and_new_call_can_open_again(self):
        for _ in range(2):
            call=self.call();socket=Socket();call.client_ready('id')
            def send(value):
                if 'setup' in value:self.assertFalse(call.provider_ready)
                else:self.assertTrue(call.provider_ready)
            socket.on_send=send
            with patch.object(calls.budget,'dispatch'),patch.object(calls.budget,'finish'),\
                 patch.object(calls.wire,'connect',return_value=socket),patch.object(calls.Thread,'start'):
                call.run()
            self.assertEqual([next(iter(value)) for value in socket.messages],['setup','clientContent'])
            self.assertEqual(call.greeting_state,'sent');self.assertFalse(call.snapshot(0)['provider_ready'])

    def test_funding_provider_resume_and_interruption_do_not_reintroduce(self):
        call=self.call(provider_ready=True);call.client_ready('id')
        old=call.ws
        with patch.object(calls.budget,'renew',return_value=object()):call.fund()
        call.receive('{"serverContent":{"interrupted":true}}')
        self.assertEqual(call.frames,[{'index':0,'type':'reset'}])
        socket=Socket();call.resume_pending=True;call.resume_handle='offline-checkpoint';call.renewing.set()
        socket.on_send=lambda value:self.assertFalse(call.provider_ready)
        with patch.object(calls.wire,'connect',return_value=socket):call.resume()
        call.client_ready('id')
        self.assertTrue(old.closed);self.assertTrue(call.provider_ready)
        self.assertEqual(len(old.messages),1)
        self.assertEqual([next(iter(value)) for value in socket.messages],['setup'])
        self.assertEqual(socket.messages[0]['setup']['sessionResumption'],{'handle':'offline-checkpoint'})

    def test_provider_rejected_opening_fails_closed_and_is_not_retried(self):
        call=self.call(provider_ready=True)
        call.ws.send=Mock(side_effect=OSError('synthetic failure'))
        with self.assertRaises(calls.CallError):call.client_ready('id')
        self.assertTrue(call.closed.is_set());self.assertFalse(call.provider_ready)
        self.assertEqual(call.greeting_state,'sent');self.assertFalse(call._maybe_greet())
        call.ws.send.assert_called_once()

    def test_interrupted_event_discards_its_output_tail_but_keeps_input(self):
        call=self.call(provider_ready=True);call.client_ready('id')
        call.caption='old opening';call.state='SPEAKING'
        pcm=b'\x01\x00'*160
        call.receive(json.dumps({'serverContent':{'interrupted':True,
            'inputTranscription':{'text':'Mau latihan interview'},
            'outputTranscription':{'text':'stale opening tail'},
            'modelTurn':{'parts':[{'inlineData':{'mimeType':'audio/pcm;rate=24000',
                'data':base64.b64encode(pcm).decode()}}]}}}))
        self.assertEqual(call.frames,[{'index':0,'type':'reset'}]);self.assertEqual(call.caption,'')
        self.assertEqual(call.state,'LISTENING');self.assertEqual(call.interruptions,1)
        self.assertEqual(call.input_transcript_chars,21);self.assertEqual(call.output_bytes,len(pcm))
        call.client_ready('id');self.assertEqual(len(self.openings(call)),1)

    def test_model_answer_already_under_way_blocks_late_opening(self):
        call=self.call(provider_ready=True)
        call.receive('{"serverContent":{"outputTranscription":{"text":"A useful response"}}}')
        call.client_ready('id')
        self.assertEqual(call.greeting_state,'skipped');self.assertEqual(self.openings(call),[])

    def test_canceled_turn_completion_preserves_new_users_public_search_request(self):
        call=self.call(provider_ready=True);call.client_ready('id')
        call.receive('{"voiceActivity":{"type":"ACTIVITY_START"}}')
        new_request='Gimana keadaan Indonesia sekarang?'
        call.receive(json.dumps({'serverContent':{'interrupted':True,'turnComplete':True,
            'inputTranscription':{'text':new_request}}}))
        self.assertEqual(call.public_search.buffer,new_request)
        self.assertEqual(call.public_search.topic,'general')
        self.assertTrue(call.public_search.speaking);self.assertTrue(call.public_search.input_active)
        self.assertEqual(call.frames,[{'index':0,'type':'reset'}]);self.assertEqual(call.turns,0)
        # Provider completion and input transcription are independently ordered.
        call.receive('{"serverContent":{"turnComplete":true}}')
        self.assertEqual(call.public_search.buffer,new_request);self.assertEqual(call.public_search.topic,'general')
        self.assertTrue(call.public_search.speaking);self.assertEqual(call.turns,0)
        # A later actual response may finish that request normally.
        call.receive('{"voiceActivity":{"type":"ACTIVITY_END"}}')
        call.receive('{"serverContent":{"outputTranscription":{"text":"A new answer"},"turnComplete":true}}')
        self.assertEqual(call.public_search.buffer,'');self.assertFalse(call.public_search.input_active)
        self.assertEqual(call.turns,1);self.assertEqual(call.frames[-1]['type'],'turn_complete')

    def test_guidance_and_search_policy_remain_in_same_native_conversation(self):
        with patch.object(calls.public_search,'configured',return_value=True):setup=calls.setup()['setup']
        text=setup['systemInstruction']['parts'][0]['text']
        for requirement in ('exactly one focused','contextually relevant guiding question','Do not force a category menu',
                            'Never introduce yourself again','language the person actually speaks','source organizations',
                            'Never invent words','no access to their chat history'):
            self.assertIn(requirement,text)
        self.assertEqual(setup['tools'],[calls.public_search.declaration()])
        self.assertEqual(setup['realtimeInputConfig']['activityHandling'],'START_OF_ACTIVITY_INTERRUPTS')

    def test_installed_google_sdk_accepts_opening_and_activity_enum_offline(self):
        try:from google.genai import types
        except ImportError:self.skipTest('Optional provider SDK unavailable; no network install or provider call')
        for language in conversation.GREETINGS:
            value=types.LiveClientMessage.model_validate(conversation.opening(language))
            self.assertEqual(value.model_dump(by_alias=True,exclude_none=True),conversation.opening(language))
        self.assertEqual(types.ActivityHandling('START_OF_ACTIVITY_INTERRUPTS').value,'START_OF_ACTIVITY_INTERRUPTS')


if __name__=='__main__':unittest.main()
