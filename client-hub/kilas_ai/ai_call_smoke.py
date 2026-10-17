"""Default-off, once-only synthetic Call smoke in a separate process.

Uses the existing provider credential, feature policy and normal Call metering.
No retries, policy overrides, private microphone input, or transcript logging.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import wave

RUN = 'call-understanding-20261017'
IDENT = hashlib.sha256(RUN.encode()).hexdigest()[:32]
ARM = 'KILAS_AI_CALL_SMOKE_RUN'
SERVICE = 'srv-da7ti2psrm7s73dh9i2g'


def armed():
    try:
        expiry = datetime.fromisoformat(os.environ['KILAS_AI_CALL_SMOKE_EXPIRES_AT'].replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        return (os.environ.get(ARM) == RUN and os.environ.get('RENDER_SERVICE_ID') == SERVICE
                and expiry.tzinfo is not None and now < expiry <= now + timedelta(minutes=30))
    except (KeyError, ValueError, TypeError):
        return False


def report(value):
    print('KILAS_AI_CALL_SMOKE ' + json.dumps({'run': RUN, **value}, sort_keys=True), flush=True)


def launch():
    if not armed():
        return False
    try:
        subprocess.Popen([sys.executable, '-m', 'kilas_ai.ai_call_smoke'], close_fds=True)
        return True
    except OSError:
        report({'status': 'launch_failed_no_retry'})
        return False


def fixtures():
    folder = Path(__file__).resolve().parents[1] / 'tests/fixtures/ai_call_synthetic'
    manifest = json.loads((folder / 'manifest.json').read_text())
    result = []
    for item in manifest:
        path = folder / (item['id'] + '.wav')
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('fixture_changed')
        with wave.open(str(path), 'rb') as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
                raise ValueError('fixture_invalid')
            if not 0 < wav.getnframes() <= 12 * 16000:
                raise ValueError('fixture_invalid')
            result.append((item, wav.readframes(wav.getnframes())))
    if [item['id'] for item, _ in result] != ['id-first', 'id-followup', 'en-first', 'en-followup']:
        raise ValueError('fixture_invalid')
    return result


def run():
    if not armed():
        return
    os.environ[ARM] = 'off'
    from . import ai_call as calls, ai_call_budget as budget
    import db
    call = None
    original = calls.wire.connect
    result = {'status': 'stopped_no_retry', 'provider_connections': 0, 'checks': [],
              'device_microphone_verified': False, 'device_playback_verified': False}
    try:
        result['stage'] = 'fixtures'
        samples = fixtures()  # Validate all synthetic input BEFORE paid admission.
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
        observed = {'heard': '', 'usage_micro': 0}

        class ProbeSocket:
            def __init__(self, socket):
                self.socket = socket

            def __getattr__(self, name):
                return getattr(self.socket, name)

            def recv(self):
                raw = self.socket.recv()
                message = calls.wire.message(raw)
                heard = message.get('serverContent', {}).get('inputTranscription', {}).get('text', '')
                if isinstance(heard, str):
                    observed['heard'] = (observed['heard'] + heard)[-8000:]
                usage = message.get('usageMetadata', {})
                # Conservative sum, potentially cumulative: this is a stop
                # fence, never a claim about the supplier's final invoice.
                if isinstance(usage, dict):
                    observed['usage_micro'] += (int(usage.get('promptTokenCount', 0)) * 7
                                               + int(usage.get('responseTokenCount', 0)) * 42 + 1) // 2
                    if observed['usage_micro'] >= 200000:
                        raise ValueError('smoke_cost_fence')
                return raw

        def connect_once():
            result['provider_connections'] += 1
            if result['provider_connections'] != 1:
                raise ValueError('no_second_connection')
            return ProbeSocket(original())

        calls.wire.connect = connect_once
        # A fixed operation ID is a durable once marker. Normal claim's unique
        # constraint prevents parallel workers/restarts from paying twice.
        report({'status':'started','max_provider_connections':1,'max_reservations':1,'max_duration_seconds':70,'max_input_seconds':55})
        result['stage'] = 'admission'
        call = calls.start(owner, IDENT)
        def no_renewal():
            raise calls.CallError('call_smoke_limit')
        call.fund = no_renewal  # Child-only fence: at most ONE normal reservation.
        began = time.monotonic()
        deadline = began + 70  # Before normal 80s metering renewal.
        cursor = 0
        output = ''
        completed = 0

        def drain():
            nonlocal cursor, output, completed
            if time.monotonic() >= deadline:
                raise ValueError('smoke_deadline')
            value = call.snapshot(cursor)
            cursor = value['next_index']
            for frame in value['frames']:
                if frame['type'] == 'text':
                    output = frame['text']
                elif frame['type'] == 'turn_complete':
                    completed += 1
            if call.closed.is_set():
                raise ValueError('call_closed')

        def send(raw):
            start = time.monotonic()
            for index, offset in enumerate(range(0, len(raw), 6400)):
                drain()
                if call.input_bytes + min(6400, len(raw) - offset) > 55 * 32000:
                    raise ValueError('smoke_input_fence')
                call.accept(call.expected, raw[offset:offset + 6400])
                time.sleep(max(0, start + (index + 1) * .2 - time.monotonic()))

        result['stage'] = 'handshake'
        while call.state == 'CONNECTING':
            drain()
            time.sleep(.05)
        send(bytes(32000 * 2))
        result['initial_silence_no_response'] = call.output_bytes == 0 and completed == 0
        for item, raw in samples:
            result['stage'] = item['id']
            output = ''
            heard_start = len(observed['heard'])
            previous = completed
            first = time.monotonic()
            send(raw)
            while completed == previous:
                send(bytes(6400))  # Continuous silence, as the browser sends.
            heard = observed['heard'][heard_start:].casefold()
            response = output.casefold()
            result['checks'].append({
                'fixture': item['id'],
                'heard_expected_subject': any(word in heard for word in item['heard']),
                'relevant_answer': any(word in response for word in item['answer']),
                'response_ms': round((time.monotonic() - first) * 1000),
                'output_chars': len(output),
            })
        result['stage'] = 'non_speech'
        previous = completed
        previous_bytes = call.output_bytes
        # Quiet non-speech + silence should not elicit an invented question or
        # a repetitive generic response. No private audio is ever used here.
        import struct
        import math
        noise = b''.join(struct.pack('<h', int(40 * math.sin(i * .37))) for i in range(16000))
        send(noise + bytes(32000 * 3))
        result['non_speech_no_response'] = call.output_bytes == previous_bytes and completed == previous
        result.update(status='completed', input_ms=round(call.input_bytes / 32),
                      output_ms=round(call.output_bytes / 48), turns=call.turns,
                      duration_ms=round((time.monotonic() - began) * 1000),
                      observed_token_estimate_micro=observed['usage_micro'])
        result['all_checks_passed'] = (result['initial_silence_no_response']
                                      and result['non_speech_no_response']
                                      and len(result['checks']) == 4
                                      and all(check['heard_expected_subject'] and check['relevant_answer']
                                              for check in result['checks']))
    except Exception as error:
        safe={'smoke_deadline','smoke_input_fence','fixture_invalid','fixture_changed','call_closed','production_policy_required'}
        result['code']=str(error) if isinstance(error,ValueError) and str(error) in safe else 'smoke_failed'
        if call is not None and call.code in {'call_provider','call_transport','call_output_invalid','call_smoke_limit'}:
            result['code']=call.code
        # Never report exceptions, credentials, provider text or transcripts.
        result['all_checks_passed'] = False
    finally:
        if call is not None:
            before = time.monotonic()
            calls.end(call.owner, call.ident)
            result['end_ms'] = round((time.monotonic() - before) * 1000)
            result['post_end_frames'] = len(call.frames)
            until = time.monotonic() + 3
            while time.monotonic() < until and budget.active(call.owner, call.ident, call.capability):
                time.sleep(.05)
            result['settled'] = not budget.active(call.owner, call.ident, call.capability)
        calls.wire.connect = original
        db._discard_cached_connection()
        report(result)


if __name__ == '__main__':
    # Process backstop if an unexpected library operation blocks cleanup.
    signal.alarm(78)
    run()
