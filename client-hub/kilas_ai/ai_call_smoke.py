"""Default-off, once-only synthetic Call smoke in a separate process.

Uses the existing provider credential, feature policy and normal Call metering.
No retries, policy overrides or private microphone input. Only this hash-verified
synthetic run reports bounded synthetic text for explicitly requested semantic review.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import base64
import math
import struct
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import wave

RUN = 'call-understanding-final-20261017'
TURNS = 3
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
        path = folder / item.get('clear_file', item['id'] + '.wav')
        if hashlib.sha256(path.read_bytes()).hexdigest() != item.get('clear_sha256',item['sha256']):
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
              'device_microphone_verified': False, 'device_playback_verified': False,
              'synthetic_only':True,'core_revision':'83bf993','turns_requested':TURNS}
    try:
        result['stage'] = 'fixtures'
        samples = fixtures()[:TURNS]  # Validate all input hashes BEFORE paid admission.
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
        observed = {'heard': '', 'usage_micro': 0, 'setup_complete':False,
                    'events':{}, 'sent_bytes':0, 'sent_chunks':0, 'max_send_gap_ms':0,
                    'max_socket_send_ms':0, 'max_accept_ms':0, 'max_pacing_lag_ms':0}
        epoch=time.monotonic()
        last_sent=None
        accepted_hash=hashlib.sha256()
        sent_hash=hashlib.sha256()

        class ProbeSocket:
            def __init__(self, socket):
                self.socket = socket

            def __getattr__(self, name):
                return getattr(self.socket, name)

            def send(self, payload):
                nonlocal last_sent
                before=time.monotonic()
                result=self.socket.send(payload)
                after=time.monotonic()
                observed['max_socket_send_ms']=max(observed['max_socket_send_ms'],round((after-before)*1000))
                message=json.loads(payload)
                audio=message.get('realtimeInput',{}).get('audio')
                if audio:
                    pcm=base64.b64decode(audio['data'],validate=True)
                    sent_hash.update(pcm)
                    observed['sent_bytes']+=len(pcm);observed['sent_chunks']+=1
                    observed.setdefault('first_send_ms',round((after-epoch)*1000))
                    if last_sent is not None:
                        observed['max_send_gap_ms']=max(observed['max_send_gap_ms'],round((after-last_sent)*1000))
                    last_sent=after
                return result

            def recv(self):
                try:raw = self.socket.recv()
                except Exception as error:
                    if type(error).__name__=='WebSocketTimeoutException':
                        observed['receive_timeouts']=observed.get('receive_timeouts',0)+1
                    else:observed['receive_failed']=True
                    raise
                message = calls.wire.message(raw)
                now=round((time.monotonic()-epoch)*1000)
                for name in ('setupComplete','serverContent','usageMetadata','sessionResumptionUpdate','goAway','error','voiceActivity'):
                    if name in message:
                        observed['events'][name]=observed['events'].get(name,0)+1
                        observed.setdefault('first_'+name+'_ms',now)
                if isinstance(message.get('setupComplete'),dict):observed['setup_complete']=True
                error=message.get('error',{})
                if isinstance(error,dict) and type(error.get('code')) is int:observed['provider_error_code']=error['code']
                content=message.get('serverContent',{})
                for name in ('inputTranscription','outputTranscription','modelTurn','turnComplete','generationComplete'):
                    if name in content:
                        observed['events'][name]=observed['events'].get(name,0)+1
                        observed.setdefault('first_'+name+'_ms',now)
                if any(part.get('inlineData') for part in content.get('modelTurn',{}).get('parts',[]) if isinstance(part,dict)):
                    if observed.get('turn_first_audio_ms') is None:observed['turn_first_audio_ms']=now
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
        report({'status':'started','max_provider_connections':1,'max_reservations':1,'max_duration_seconds':74,'max_input_seconds':55})
        result['stage'] = 'admission'
        call = calls.start(owner, IDENT)
        def no_renewal():
            raise calls.CallError('call_smoke_limit')
        call.fund = no_renewal  # Child-only fence: at most ONE normal reservation.
        began = time.monotonic()
        deadline = began + 74  # Before normal 80s metering renewal.
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

        # Match browser batching. One sample-clock spans all calls to send;
        # time spent in admission checks is measured rather than added as sleep.
        sample_clock=time.monotonic()
        sample_bytes=0
        def send(raw):
            nonlocal sample_bytes
            for offset in range(0,len(raw),16000):
                drain()
                packet=raw[offset:offset+16000]
                if call.input_bytes+len(packet)>55*32000:raise ValueError('smoke_input_fence')
                due=sample_clock+sample_bytes/32000
                time.sleep(max(0,due-time.monotonic()))
                observed['max_pacing_lag_ms']=max(observed['max_pacing_lag_ms'],round(max(0,time.monotonic()-due)*1000))
                before=time.monotonic();call.accept(call.expected,packet)
                observed['max_accept_ms']=max(observed['max_accept_ms'],round((time.monotonic()-before)*1000))
                accepted_hash.update(packet);sample_bytes+=len(packet)
                time.sleep(max(0,sample_clock+sample_bytes/32000-time.monotonic()))

        result['stage'] = 'handshake'
        while call.state == 'CONNECTING':
            drain()
            time.sleep(.05)
        sample_clock=time.monotonic()
        send(bytes(32000 * 2))
        result['initial_silence_no_response'] = call.output_bytes == 0 and completed == 0
        for item, raw in samples:
            result['stage'] = item['id']
            output = ''
            heard_start = len(observed['heard'])
            previous = completed
            first = time.monotonic();observed['turn_first_audio_ms']=None
            send(raw)
            input_ended=time.monotonic()
            response_deadline=min(deadline,time.monotonic()+12)
            while completed == previous:
                if time.monotonic()>=response_deadline:raise ValueError('smoke_no_audio_response')
                send(bytes(16000))  # Continuous silence, as the browser sends.
            heard = observed['heard'][heard_start:].casefold()
            response = output.casefold()
            result['checks'].append({
                'fixture': item['id'],
                'heard_expected_subject': any(word in heard for word in item['heard']),
                'relevant_answer': any(word in response for word in item['answer']),
                'response_ms': round((time.monotonic() - first) * 1000),
                'output_chars': len(output),
                # This private child accepts only the prevalidated offline WAVs.
                # No public microphone route can reach this reporting path.
                # These bounded texts enable semantic review of SYNTHETIC turns.
                'fixture_source':'hash_verified_offline_synthetic',
                'synthetic_input_text':observed['heard'][heard_start:][:1024],
                'synthetic_response_text':output[:1024],
                'first_audio_ms':None if observed.get('turn_first_audio_ms') is None else round(observed['turn_first_audio_ms']-(first-epoch)*1000),
                'first_audio_from_input_end_ms':None if observed.get('turn_first_audio_ms') is None else round(observed['turn_first_audio_ms']-(input_ended-epoch)*1000),
            })
        result['stage'] = 'non_speech'
        previous = completed
        previous_bytes = call.output_bytes
        # Quiet non-speech + silence should not elicit an invented question or
        # a repetitive generic response. No private audio is ever used here.
        noise = b''.join(struct.pack('<h', int(40 * math.sin(i * .37))) for i in range(16000))
        send(noise + bytes(32000 * 3))
        result['non_speech_no_response'] = call.output_bytes == previous_bytes and completed == previous
        # Account for the sender thread finishing the last accepted silence
        # packet; do not mistake an unsent End tail for speech corruption.
        until=min(deadline,time.monotonic()+1)
        while call.sent_bytes<call.input_bytes and time.monotonic()<until:
            drain();time.sleep(.05)
        result.update(status='completed', input_ms=round(call.input_bytes / 32),
                      output_ms=round(call.output_bytes / 48), turns=call.turns,
                      duration_ms=round((time.monotonic() - began) * 1000),
                      observed_token_estimate_micro=observed['usage_micro'])
        result['all_checks_passed'] = (result['initial_silence_no_response']
                                      and result['non_speech_no_response']
                                      and len(result['checks']) == TURNS
                                      and all(check['heard_expected_subject'] and check['relevant_answer']
                                              for check in result['checks']))
    except Exception as error:
        safe={'smoke_deadline','smoke_no_audio_response','smoke_input_fence','fixture_invalid','fixture_changed','call_closed','production_policy_required'}
        result['code']=str(error) if isinstance(error,ValueError) and str(error) in safe else 'smoke_failed'
        if call is not None and call.code in {'call_provider','call_transport','call_output_invalid','call_smoke_limit'}:
            result['code']=call.code
        # One same-socket text control ONLY after the first audio failure. It
        # distinguishes output transport from audio recognition; never counts
        # as a successful audio turn or repeats the speech fixture.
        if (call is not None and result.get('code')=='smoke_no_audio_response'
                and not result['checks'] and not call.closed.is_set()):
            result['text_control_attempted']=True
            try:
                output='';previous=completed
                with call.send_lock:
                    call.ws.send(json.dumps({'clientContent':{'turns':[{'role':'user','parts':[{'text':'Say only the word ready.'}]}],'turnComplete':True}}))
                until=min(deadline,time.monotonic()+8)
                while completed==previous and time.monotonic()<until:
                    drain();time.sleep(.1)
                result['text_control_responded']=completed>previous
                result['text_control_expected_word']='ready' in output.casefold()
            except Exception:result['text_control_responded']=False
        # Never report exceptions, credentials, provider text or transcripts.
        result['all_checks_passed'] = False
    finally:
        if call is not None:
            # Record safe evidence BEFORE End erases the output. No words or
            # exception messages are retained by this report.
            safe_observed={key:value for key,value in observed.items() if key!='heard'}
            result['transport']=safe_observed
            result.update(accepted_ms=round(call.input_bytes/32),sent_ms=round(call.sent_bytes/32),
                          sent_chunks=call.sent_chunks,queued_ms=round(call.queued/32),
                          provider_messages=call.provider_messages,heard_chars=call.input_transcript_chars,
                          output_ms=round(call.output_bytes/48),turns=call.turns,
                          duration_ms=round((time.monotonic()-began)*1000),
                          dispatch_matches_accepted=accepted_hash.digest()==sent_hash.digest())
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
    signal.alarm(88)
    run()
