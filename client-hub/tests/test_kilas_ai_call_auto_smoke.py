"""Offline fences for the single automatic diagnostic; no provider/DB IO."""
import base64
import contextlib
import copy
from datetime import datetime, timezone, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from threading import Event, Lock
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kilas_ai import ai_call_auto_smoke as smoke, ai_call as calls, ai_call_budget as budget
import db


class AutoSmokeTests(unittest.TestCase):
    def arm(self):
        return patch.dict(os.environ, {smoke.ARM: smoke.RUN, 'RENDER_SERVICE_ID': smoke.SERVICE,
            'KILAS_AI_CALL_SMOKE_EXPIRES_AT': (datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat()})

    def test_default_off_and_invalid_expiry_never_launch(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(smoke.subprocess, 'Popen') as popen:
            self.assertFalse(smoke.launch())
            with self.arm(), patch.dict(os.environ, {'KILAS_AI_CALL_SMOKE_EXPIRES_AT': 'invalid'}):
                self.assertFalse(smoke.launch())
            popen.assert_not_called()

    def test_browser_fixture_hash_and_unmodified_normal_setup(self):
        payload = smoke.fixture()
        self.assertEqual(len(payload),236800)
        self.assertEqual(hashlib.sha256(payload).hexdigest(),smoke.RAW_SHA)
        value = calls.setup()['setup']
        self.assertFalse(value['realtimeInputConfig']['automaticActivityDetection']['disabled'])
        self.assertEqual(value['generationConfig']['maxOutputTokens'],1024)

    def test_durable_once_marker_prevents_new_admission(self):
        with self.arm(), patch.object(db, 'BACKEND', 'postgres'), \
             patch.object(budget, 'config', return_value={'allowed_owner': 1}), \
             patch.object(budget, 'owned', return_value={'status': 'UNKNOWN'}), \
             patch.object(calls, 'start') as start, contextlib.redirect_stdout(io.StringIO()) as output:
            smoke.run()
        start.assert_not_called()
        self.assertIn('already_attempted_no_retry', output.getvalue())

    def scenario(self, respond):
        now = [0.0]
        holder = []
        class Socket:
            def __init__(self):
                self.incoming = []; self.pcm = bytearray(); self.messages = []; self.lead = False; self.responded = False
            def send(self, raw):
                value = json.loads(raw); self.messages.append(value)
                if 'setup' in value: self.incoming.append({'setupComplete': {}})
                inner = value.get('realtimeInput', {})
                if 'audio' in inner:
                    self.pcm.extend(base64.b64decode(inner['audio']['data']))
                    if now[0]+1e-8 < len(self.pcm)/32000: self.lead = True
                if len(self.pcm)>=204800 and respond and not self.responded:
                    self.responded=True
                    self.incoming.extend([{'serverContent': {'inputTranscription': {'text': 'I have three apples. I buy two more apples. How many apples do I have?'},
                        'outputTranscription': {'text': 'You have five apples.'}, 'modelTurn': {'parts': [{'inlineData': {'data':'synthetic'}}]}, 'turnComplete': True}},
                        {'usageMetadata': {'promptTokenCount': 500, 'responseTokenCount': 30, 'totalTokenCount': 530}}])
            def recv(self): return json.dumps(self.incoming.pop(0))
        socket = Socket()
        class Call:
            def __init__(self, owner, ident):
                self.owner = owner; self.ident = ident; self.capability = object()
                self.state = 'LISTENING'; self.closed = Event(); self.send_lock = Lock()
                self.frames = []; self.input_bytes = self.sent_chunks = self.queued = self.output_bytes = self.expected = self.turns = 0
                self.ws = calls.wire.connect(); self.ws.send(json.dumps(calls.setup())); self.ws.recv()
            def snapshot(self, cursor):
                while socket.incoming:
                    message = json.loads(self.ws.recv())
                    if message.get('serverContent', {}).get('turnComplete'):
                        self.turns += 1; self.output_bytes += 4800
                return {'next_index': 0}
            def accept(self, index, raw):
                self.ws.send(json.dumps({'realtimeInput': {'audio': {'mimeType': 'audio/pcm;rate=16000', 'data': base64.b64encode(raw).decode()}}}))
                self.input_bytes += len(raw); self.expected += 1; self.sent_chunks += 1
        def start(owner, ident):
            call = Call(owner, ident); holder.append(call); return call
        def end(*args): holder[0].closed.set(); holder[0].frames.clear()
        def sleep(seconds): now[0] += seconds
        with self.arm(), patch.object(db, 'BACKEND', 'postgres'), \
             patch.object(budget, 'config', return_value={'allowed_owner': 1}), \
             patch.object(budget, 'owned', return_value=None), patch.object(budget, 'status', return_value={'available': True}), \
             patch.object(budget, 'active', return_value=False), patch.object(calls.wire, 'connect', return_value=socket), \
             patch.object(calls, 'start', side_effect=start), patch.object(calls, 'end', side_effect=end), \
             patch.object(smoke, 'Timer'), patch.object(smoke.time, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(smoke.time, 'sleep', side_effect=sleep), contextlib.redirect_stdout(io.StringIO()) as output:
            smoke.run()
        return json.loads(output.getvalue().splitlines()[-1].split(' ', 1)[1]), socket

    def test_automatic_response_stops_immediately_without_markers_or_search(self):
        before=calls.setup()
        result,socket=self.scenario(True)
        self.assertEqual(calls.setup(),before)
        self.assertEqual(result['status'],'completed')
        self.assertTrue(result['automatic_vad']);self.assertEqual(result['output_token_cap'],1024)
        self.assertEqual(result['provider_connections'],1)
        self.assertEqual(result['accepted_bytes'],204800)
        self.assertLess(result['accepted_bytes'],len(smoke.fixture()))
        self.assertTrue(result['complete_speech_dispatched'])
        self.assertTrue(result['dispatch_matches_accepted']);self.assertTrue(result['settled'])
        self.assertEqual(result['manual_markers'],0);self.assertEqual(result['search_attempts'],0)
        self.assertFalse(socket.lead)
        self.assertFalse(any('clientContent' in m for m in socket.messages))
        self.assertFalse(any(set(m.get('realtimeInput',{})) & {'activityStart','activityEnd','audioStreamEnd'} for m in socket.messages))
        self.assertEqual(result['first_audio_after_speech_ms'],1400)
        self.assertIn('five apples',result['response_text'])

    def test_no_response_has_one_socket_and_no_fallback_or_renewal(self):
        result,socket=self.scenario(False)
        self.assertEqual(result['code'],'input_fence')
        self.assertEqual(result['provider_connections'],1)
        self.assertTrue(result['settled']);self.assertLess(result['duration_ms'],25000)
        self.assertEqual(result['manual_markers'],0);self.assertEqual(result['search_attempts'],0)
        self.assertFalse(any('clientContent' in m for m in socket.messages))


if __name__ == '__main__':
    unittest.main()
