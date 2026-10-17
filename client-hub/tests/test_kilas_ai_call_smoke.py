"""Smoke fences only; unit tests never open a provider socket."""
from datetime import datetime, timezone, timedelta
import os
from pathlib import Path
import sys
import unittest
import contextlib
import io
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kilas_ai import ai_call_smoke as smoke


class SmokeTests(unittest.TestCase):
    def armed(self, **extra):
        values = {smoke.ARM: smoke.RUN, 'RENDER_SERVICE_ID': smoke.SERVICE,
                  'KILAS_AI_CALL_SMOKE_EXPIRES_AT': (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()}
        values.update(extra)
        return patch.dict(os.environ, values)

    def test_default_off_expired_wrong_service_and_overlong_arm_never_launch(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(smoke.subprocess, 'Popen') as child:
            self.assertFalse(smoke.launch())
            with self.armed(RENDER_SERVICE_ID='unrelated'):
                self.assertFalse(smoke.launch())
            for minutes in (-1, 31):
                with self.armed(KILAS_AI_CALL_SMOKE_EXPIRES_AT=(datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()):
                    self.assertFalse(smoke.launch())
            child.assert_not_called()

    def test_explicit_arm_only_launches_child_never_reads_or_copies_credentials(self):
        with self.armed(), patch.object(smoke.subprocess, 'Popen') as child:
            self.assertTrue(smoke.launch())
            child.assert_called_once_with([smoke.sys.executable, '-m', 'kilas_ai.ai_call_smoke'], close_fds=True)

    def test_synthetic_fixture_hashes_format_duration_and_context_answers(self):
        values = smoke.fixtures()
        self.assertEqual(len(values), 4)
        self.assertLess(sum(len(raw) for _, raw in values), 25 * 32000)
        self.assertEqual([item['answer'][0] for item, _ in values], ['lima', 'tiga', 'twelve', 'eight'])

    def test_durable_attempt_marker_prevents_provider_or_paid_admission_after_restart(self):
        from kilas_ai import ai_call as calls, ai_call_budget as budget
        import db
        with self.armed(), patch.object(db, 'BACKEND', 'postgres'), \
             patch.object(budget, 'config', return_value={'allowed_owner': 1}), \
             patch.object(budget, 'owned', return_value={'status': 'UNKNOWN'}), \
             patch.object(calls, 'start') as start, patch.object(calls.wire, 'connect') as connect, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            smoke.run()
            start.assert_not_called()
            connect.assert_not_called()
            self.assertIn('already_attempted_no_retry', output.getvalue())

    def synthetic_session(self, respond_to_audio):
        import json
        import base64
        import threading
        from kilas_ai import ai_call as calls, ai_call_budget as budget
        import db
        now=[0.0]
        samples=smoke.fixtures()[:smoke.TURNS]
        targets=[];total=2*32000
        for item,raw in samples:
            total+=len(raw);targets.append((total,item))
        class Socket:
            def __init__(self):
                self.incoming=[];self.total=0;self.at=0;self.controls=0
            def send(self,payload):
                message=json.loads(payload)
                if 'setup' in message:self.incoming.append({'setupComplete':{}})
                audio=message.get('realtimeInput',{}).get('audio')
                if audio:
                    self.total+=len(base64.b64decode(audio['data']))
                    if respond_to_audio and self.at<len(targets) and self.total>=targets[self.at][0]:
                        item=targets[self.at][1];self.at+=1
                        self.incoming.append({'serverContent':{'inputTranscription':{'text':item['heard'][0]+' synthetic-hidden'},'outputTranscription':{'text':item['answer'][0]+' synthetic-hidden'},'turnComplete':True}})
                if 'clientContent' in message:
                    self.controls+=1;self.incoming.append({'serverContent':{'outputTranscription':{'text':'ready synthetic-hidden'},'turnComplete':True}})
            def recv(self):return json.dumps(self.incoming.pop(0))
        socket=Socket();holder=[]
        class Call:
            def __init__(self,owner,ident):
                self.owner=owner;self.ident=ident;self.capability=object();self.code=None
                self.ws=calls.wire.connect();self.ws.send(json.dumps(calls.setup()));self.ws.recv()
                self.state='LISTENING';self.closed=threading.Event();self.send_lock=threading.Lock()
                self.frames=[];self.input_bytes=0;self.output_bytes=0;self.turns=0;self.expected=0
                self.sent_bytes=0;self.sent_chunks=0;self.queued=0;self.provider_messages=0;self.input_transcript_chars=0
            def snapshot(self,after):return {'frames':self.frames[after:],'next_index':len(self.frames)}
            def receive(self):
                while socket.incoming:
                    value=json.loads(self.ws.recv()).get('serverContent',{});self.provider_messages+=1
                    self.input_transcript_chars+=len(value.get('inputTranscription',{}).get('text',''))
                    self.frames.append({'index':len(self.frames),'type':'text','text':value['outputTranscription']['text']})
                    self.frames.append({'index':len(self.frames),'type':'turn_complete'})
                    self.output_bytes+=4800;self.turns+=1
            def accept(self,index,raw):
                now[0]+=.3  # Realistic slow admission: >200 ms, <500 ms batch.
                self.input_bytes+=len(raw);self.expected+=1
                self.ws.send(json.dumps({'realtimeInput':{'audio':{'data':base64.b64encode(raw).decode()}}}))
                self.sent_bytes+=len(raw);self.sent_chunks+=1;self.receive()
        def start(owner,ident):
            call=Call(owner,ident);holder.append(call);return call
        def end(owner,ident):holder[0].closed.set();holder[0].frames.clear()
        # Text control is not followed by accept; allow its queued response to
        # reach the poll loop on the next tiny injected clock tick.
        def sleep(seconds):
            now[0]+=seconds
            if holder and socket.incoming:holder[0].receive()
        with self.armed(), patch.object(db,'BACKEND','postgres'), \
             patch.object(budget,'config',return_value={'allowed_owner':1}), \
             patch.object(budget,'owned',return_value=None), \
             patch.object(budget,'status',return_value={'available':True}), \
             patch.object(budget,'active',return_value=False), \
             patch.object(calls.wire,'connect',return_value=socket), \
             patch.object(calls,'start',side_effect=start),patch.object(calls,'end',side_effect=end), \
             patch.object(smoke.time,'monotonic',side_effect=lambda:now[0]), \
             patch.object(smoke.time,'sleep',side_effect=sleep), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            smoke.run()
        self.assertNotIn('\"heard\":',output.getvalue())
        result=json.loads(output.getvalue().splitlines()[-1].split(' ',1)[1])
        return result,socket

    def test_entire_harness_retains_pacing_and_all_dispatch_bytes_with_slow_admission(self):
        result,socket=self.synthetic_session(True)
        self.assertTrue(result['all_checks_passed'])
        self.assertEqual(len(result['checks']),3)
        self.assertTrue(all(check['fixture_source']=='hash_verified_offline_synthetic' for check in result['checks']))
        self.assertTrue(result['dispatch_matches_accepted'])
        self.assertEqual(result['accepted_ms'],result['sent_ms'])
        self.assertEqual(result['provider_connections'],1)
        self.assertEqual(result['transport']['max_accept_ms'],300)
        self.assertLess(result['transport']['max_pacing_lag_ms'],350)
        self.assertTrue(result['settled']);self.assertEqual(socket.controls,0)

    def test_audio_failure_uses_one_same_socket_text_control_and_never_claims_audio_success(self):
        result,socket=self.synthetic_session(False)
        self.assertFalse(result['all_checks_passed'])
        self.assertEqual(result['checks'],[])
        self.assertTrue(result['text_control_responded']);self.assertTrue(result['text_control_expected_word'])
        self.assertEqual(result['provider_connections'],1);self.assertEqual(socket.controls,1)
        self.assertTrue(result['dispatch_matches_accepted'])
        self.assertLess(result['duration_ms'],74000)

    def test_unarmed_run_never_imports_database_or_calls_provider(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(smoke, 'fixtures') as fixtures:
            smoke.run()
            fixtures.assert_not_called()


if __name__ == '__main__':
    unittest.main()
