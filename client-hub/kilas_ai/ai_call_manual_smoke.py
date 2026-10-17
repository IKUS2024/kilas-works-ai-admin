"""Once-only, explicitly armed, ASR-verified synthetic manual-turn diagnostic.

This runs only in a separate child, never with a public microphone. Production
Call setup, metering and automatic VAD remain unchanged. No retries/text control.
"""
import base64
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Timer
import time
import wave

RUN = 'call-understanding-manual-20261017'
IDENT = hashlib.sha256(RUN.encode()).hexdigest()[:32]
ARM = 'KILAS_AI_CALL_SMOKE_RUN'
SERVICE = 'srv-da7ti2psrm7s73dh9i2g'
RAW_SHA = '58f4508dd47c1e57eef14c2fc150e98ae4c9631c16547af3a5562d77877e8cbc'
PAYLOAD_SHA = '4da9349665483c93631b0a32311c8b7f9ea4c4313197fc2f4e6fecf3097eb6c9'


def armed():
    try:
        expiry = datetime.fromisoformat(os.environ['KILAS_AI_CALL_SMOKE_EXPIRES_AT'].replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        return (os.environ.get(ARM) == RUN and os.environ.get('RENDER_SERVICE_ID') == SERVICE
                and expiry.tzinfo is not None and now < expiry <= now + timedelta(minutes=30))
    except (KeyError, ValueError, TypeError):
        return False


def launch():
    if not armed():
        return False
    subprocess.Popen([sys.executable, '-m', 'kilas_ai.ai_call_manual_smoke'], close_fds=True)
    return True


def fixture():
    path = Path(__file__).resolve().parents[1] / 'tests/fixtures/ai_call_synthetic/manual-apples.wav'
    with wave.open(str(path), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise ValueError('fixture_invalid')
        raw = wav.readframes(wav.getnframes())
    if len(raw) != 163520 or hashlib.sha256(raw).hexdigest() != RAW_SHA:
        raise ValueError('fixture_changed')
    return raw + bytes(16000)  # Complete speech plus exactly 500 ms zero tail.


def manual_setup(original, handle=None):
    value = original(handle)
    value['setup']['generationConfig']['maxOutputTokens'] = 128
    value['setup']['realtimeInputConfig']['automaticActivityDetection'] = {'disabled': True}
    return value


def run():
    if not armed():
        return
    os.environ[ARM] = 'off'
    from . import ai_call as calls, ai_call_budget as budget
    import db
    call = None
    timer = None
    original_connect, original_setup = calls.wire.connect, calls.setup
    began = time.monotonic()
    deadline = began + 25
    result = {'run': RUN, 'status': 'stopped_no_retry', 'synthetic_only': True,
              'provider_connections': 0, 'automatic_vad_production_changed': False,
              'input_text': '', 'response_text': '', 'events': {}, 'usage_events': [],
              'activity_events': [], 'setup_complete': False, 'turn_complete': False}
    accepted_hash, sent_hash = hashlib.sha256(), hashlib.sha256()
    sent_bytes = 0

    def tick():
        return round((time.monotonic() - began) * 1000)

    def check():
        if time.monotonic() >= deadline:
            raise ValueError('diagnostic_deadline')
        if call is not None and call.closed.is_set():
            raise ValueError('call_closed')

    class ProbeSocket:
        def __init__(self, socket):
            self.socket = socket

        def __getattr__(self, name):
            return getattr(self.socket, name)

        def send(self, payload):
            nonlocal sent_bytes
            check()
            message = json.loads(payload)
            inner = message.get('realtimeInput', {})
            answer = self.socket.send(payload)
            for key in ('activityStart', 'activityEnd'):
                if key in inner:
                    result[key + '_ms'] = tick()
            if 'audio' in inner:
                raw = base64.b64decode(inner['audio']['data'], validate=True)
                sent_hash.update(raw)
                sent_bytes += len(raw)
            return answer

        def recv(self):
            raw = self.socket.recv()
            message = calls.wire.message(raw)
            for name in message:
                key = name if name in {'setupComplete', 'serverContent', 'usageMetadata', 'sessionResumptionUpdate',
                                      'goAway', 'error', 'voiceActivity', 'voiceActivityDetectionSignal'} else 'other_top_level'
                result['events'][key] = result['events'].get(key, 0) + 1
            if 'setupComplete' in message:
                result['setup_complete'] = True
            content = message.get('serverContent', {})
            for key, field in (('inputTranscription', 'input_text'), ('outputTranscription', 'response_text')):
                text = content.get(key, {}).get('text', '')
                if isinstance(text, str):
                    result[field] = (result[field] + text)[:2048]
            if any(p.get('inlineData') for p in content.get('modelTurn', {}).get('parts', []) if isinstance(p, dict)):
                result.setdefault('first_audio_ms', tick())
            if content.get('turnComplete'):
                result['turn_complete'] = True
                result.setdefault('turn_complete_ms', tick())
            usage = message.get('usageMetadata')
            if isinstance(usage, dict) and len(result['usage_events']) < 8:
                safe = {k: v for k, v in usage.items() if k in {'promptTokenCount', 'responseTokenCount',
                        'totalTokenCount', 'cachedContentTokenCount', 'thoughtsTokenCount'} and type(v) is int and v >= 0}
                for key in ('promptTokensDetails', 'responseTokensDetails'):
                    safe[key] = [{'modality': p['modality'], 'tokenCount': p['tokenCount']} for p in usage.get(key, [])
                                 if isinstance(p, dict) and p.get('modality') in ('AUDIO', 'TEXT')
                                 and type(p.get('tokenCount')) is int and p['tokenCount'] >= 0][:4]
                result['usage_events'].append(safe)
            for key in ('voiceActivity', 'voiceActivityDetectionSignal'):
                signal_value = message.get(key)
                if isinstance(signal_value, dict) and len(result['activity_events']) < 16:
                    safe = {'at_ms': tick(), 'kind': key}
                    for field in ('voiceActivityType', 'vadSignalType'):
                        value = signal_value.get(field)
                        if isinstance(value, str) and value in {'ACTIVITY_START', 'ACTIVITY_END', 'SPEECH_START',
                                'SPEECH_END', 'VAD_SIGNAL_TYPE_SOS', 'VAD_SIGNAL_TYPE_EOS', 'START_OF_SPEECH', 'END_OF_SPEECH'}:
                            safe[field] = value
                    offset = signal_value.get('audioOffset')
                    if isinstance(offset, str) and len(offset) < 32 and all(c in '0123456789.s' for c in offset):
                        safe['audioOffset'] = offset
                    result['activity_events'].append(safe)
            return raw

    def connect_once():
        check()
        result['provider_connections'] += 1
        if result['provider_connections'] != 1:
            raise ValueError('no_second_connection')
        return ProbeSocket(original_connect())

    try:
        payload = fixture()  # Validate the exact reviewed waveform before admission.
        assert hashlib.sha256(payload).hexdigest() == PAYLOAD_SHA
        value = budget.config()
        if db.BACKEND != 'postgres' or not value:
            raise ValueError('production_policy_required')
        owner = value['allowed_owner']
        if budget.owned(owner, IDENT):
            result['status'] = 'already_attempted_no_retry'
            return
        if not budget.status(owner)['available']:
            result['status'] = 'account_unavailable_no_retry'
            return
        calls.wire.connect = connect_once
        calls.setup = lambda handle=None: manual_setup(original_setup, handle)
        print('KILAS_AI_CALL_MANUAL ' + json.dumps({'run': RUN, 'status': 'started', 'input_ms': 5610,
              'output_token_cap': 128, 'deadline_seconds': 25, 'max_connections': 1, 'max_reservations': 1}), flush=True)
        call = calls.start(owner, IDENT)
        def no_renewal():
            raise calls.CallError('call_smoke_limit')
        call.fund = no_renewal
        timer = Timer(max(0, deadline - time.monotonic()), lambda: call.stop('call_smoke_limit'))
        timer.daemon = True
        timer.start()
        cursor = 0

        def drain():
            nonlocal cursor
            check()
            cursor = call.snapshot(cursor)['next_index']

        while call.state == 'CONNECTING':
            drain(); time.sleep(.02)
        with call.send_lock:
            call.ws.send(json.dumps({'realtimeInput': {'activityStart': {}}}))
        clock = time.monotonic()
        for at in range(0, len(payload), 6400):
            raw = payload[at:at+6400]
            due = clock + (at+len(raw))/32000
            time.sleep(max(0, due-time.monotonic()))
            drain()
            call.accept(call.expected, raw)
            accepted_hash.update(raw)
        while sent_bytes < len(payload):
            drain(); time.sleep(.01)
        if sent_hash.hexdigest() != PAYLOAD_SHA:
            raise ValueError('dispatch_mismatch')
        with call.send_lock:
            call.ws.send(json.dumps({'realtimeInput': {'activityEnd': {}}}))
        until = min(deadline, time.monotonic()+8)
        while not (result['turn_complete'] and call.turns >= 1):
            drain()
            if time.monotonic() >= until:
                raise ValueError('no_audio_response')
            time.sleep(.02)
        # Usage can follow the final audio/transcript event. No more input or
        # generation requests are sent during this brief receive-only drain.
        until = min(deadline, time.monotonic()+.3)
        while not result['usage_events'] and time.monotonic() < until:
            drain(); time.sleep(.02)
        result['status'] = 'completed'
    except Exception as error:
        safe = {'diagnostic_deadline', 'no_audio_response', 'call_closed', 'dispatch_mismatch',
                'fixture_changed', 'fixture_invalid', 'production_policy_required', 'no_second_connection'}
        result['code'] = str(error) if type(error) is ValueError and str(error) in safe else 'diagnostic_failed'
    finally:
        if timer:
            timer.cancel()
        if call is not None:
            result.update(duration_ms=tick(), accepted_bytes=call.input_bytes, sent_bytes=sent_bytes,
                          sent_chunks=call.sent_chunks, queued_bytes=call.queued, output_ms=call.output_bytes/48,
                          dispatch_matches_accepted=accepted_hash.digest()==sent_hash.digest(),
                          dispatched_sha256=sent_hash.hexdigest())
            end = result.get('activityEnd_ms')
            first = result.get('first_audio_ms')
            result['first_audio_after_end_ms'] = first-end if first is not None and end is not None else None
            before = time.monotonic()
            calls.end(call.owner, call.ident)
            result['end_ms'] = round((time.monotonic()-before)*1000)
            result['post_end_frames'] = len(call.frames)
            until = time.monotonic()+3
            while time.monotonic() < until and budget.active(call.owner, call.ident, call.capability):
                time.sleep(.05)
            result['settled'] = not budget.active(call.owner, call.ident, call.capability)
        calls.wire.connect, calls.setup = original_connect, original_setup
        db._discard_cached_connection()
        print('KILAS_AI_CALL_MANUAL ' + json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    signal.alarm(30)  # Independent child-process backstop, including cleanup.
    run()
