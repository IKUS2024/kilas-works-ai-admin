"""Exactly two approved synthetic tests; separate process, never a public route.

Default OFF. No import IO, automatic retries, fixture generation or secret output.
The web worker never enables Gemini: only this short-lived child sets its policy.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import wave
from datetime import datetime, timezone, timedelta

RUN = 'gmlqa20261016b'
SERVICE = 'srv-da7ti2psrm7s73dh9i2g'
ARM = 'KILAS_LIVE_GEMINI_QA_ARM'
FIXTURES = {
    'id':'3751b3b407c81b5f6398f1dcccc4ad21fbaffda3912e51f6aabe12f760714fc9',
    'en':'955455943bd45b9ca13b375030f75b49e9515d477ab26a65ed3e6731df3e0e8a',
}


def config():
    try:
        mode=os.environ.get(ARM)
        if mode not in (RUN,RUN+'-remaining-en-id') or os.environ.get('RENDER_SERVICE_ID') != SERVICE:
            return None
        owner = int(os.environ['KILAS_LIVE_GEMINI_QA_OWNER_ID'])
        email = os.environ['KILAS_LIVE_GEMINI_QA_OWNER_EMAIL'].strip().lower()
        expiry = datetime.fromisoformat(os.environ['KILAS_LIVE_GEMINI_QA_EXPIRES_AT'].replace('Z','+00:00'))
        now = datetime.now(timezone.utc)
        if not 0 < owner <= 10**9 or '@' not in email or expiry.tzinfo is None or not now < expiry <= now+timedelta(minutes=30):
            return None
        return {'owner':owner, 'email':email, 'expiry':expiry.astimezone(timezone.utc).isoformat(),
                'remaining':mode==RUN+'-remaining-en-id'}
    except (KeyError, ValueError, TypeError, OverflowError):
        return None


def launch():
    if not config():
        return False
    # Inherit the installed runtime environment without reading/copying any
    # secret value in the web worker, command line, files or logs.
    try:
        subprocess.Popen([sys.executable,'-m','kilas_ai.live_gemini_smoke'], close_fds=True)
    except OSError:
        report({'run':RUN,'status':'launch_failed_no_retry'})
        return False
    return True


def fixture(language):
    path = Path(__file__).resolve().parents[1]/'tests'/'fixtures'/'gemini_live_synthetic'/(language+'.wav')
    if hashlib.sha256(path.read_bytes()).hexdigest() != FIXTURES[language]:
        raise ValueError('fixture_changed')
    with wave.open(str(path),'rb') as wav:
        if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate(),wav.getnframes()) != (1,2,16000,240000):
            raise ValueError('fixture_invalid')
        return wav.readframes(240000)


def report(value):
    print('KILAS_GEMINI_QA '+json.dumps(value,separators=(',',':')),flush=True)


def tail_word(text, language):
    words=re.findall(r'\w+',text.casefold()) if isinstance(text,str) else []
    return bool(words and words[-1]=={'id':'air','en':'water'}[language])


def passed(result):
    # These are backend fixture checks, never an audible/Android quality claim.
    return bool(not result.get('code') and result.get('setup_complete')
                and result.get('input_ms')==15000 and result.get('output_ms',0)>0
                and result.get('streamed_before_input_finished')
                and result.get('source_tail_word_confirmed') and result.get('target_tail_word_confirmed')
                and result.get('terminal_turn_complete') and result.get('all_generated_pcm_read')
                and result.get('settled_after_end') and result.get('post_end_frames')==0
                and result.get('post_end_output_access')=='blocked'
                and 0<=result.get('backend_end_ms',float('inf'))<2000)


def production_policy_check(owner):
    # Only nonsecret policy names; never inspect GEMINI_API_KEY. This child-only
    # parse does not enable the public service or admit/dispatch any request.
    from . import live_gemini_budget as budget
    names=('BILLING_VERIFIED','ALLOWED_OWNER_ID','CAMPAIGN','BUDGET_MICRO_USD',
           'LEASE_RESERVE_MICRO_USD','EXPIRES_AT')
    present={name:bool(os.environ.get('KILAS_LIVE_GEMINI_'+name)) for name in names}
    flag='KILAS_LIVE_GEMINI_ENABLED';previous=os.environ.get(flag)
    try:
        os.environ[flag]='true'
        valid=budget.ready(owner)
    finally:
        if previous is None:os.environ.pop(flag,None)
        else:os.environ[flag]=previous
    return {'nonsecret_fields_present':present,'valid_for_owner_if_enabled':valid}


class ProbeSocket:
    """Observe real transport, preserving bytes/protocol and suppressing errors."""
    def __init__(self, socket, observation):
        self.socket, self.observation = socket, observation

    def __getattr__(self, name):
        return getattr(self.socket,name)

    def recv(self):
        try:
            raw = self.socket.recv()
        except Exception as error:
            if type(error).__name__ == 'WebSocketConnectionClosedException':
                self.observation['socket_closed'] = True
            raise
        if raw in ('',b''):
            self.observation['socket_closed'] = True
        self.observation.setdefault('first_frame_type',type(raw).__name__)
        if isinstance(raw,(str,bytes)) and len(raw) <= 1024*1024:
            value = json.loads(raw)
            if isinstance(value,dict):
                types=self.observation.setdefault('message_types',[])
                for name in ('setupComplete','serverContent','error','usageMetadata','goAway'):
                    if name in value and name not in types:types.append(name)
                content=value.get('serverContent')
                if isinstance(content,dict):
                    counters=self.observation.setdefault('server_terminal_events',{})
                    for field in ('generationComplete','turnComplete','interrupted','waitingForInput'):
                        if content.get(field) is True:counters[field]=counters.get(field,0)+1
                    status=content.get('interactionStatus')
                    if status in ('IDLE','IN_PROGRESS','REQUIRES_ACTION','INTERACTION_STATUS_UNSPECIFIED'):
                        self.observation['last_interaction_status']=status
                if 'setupComplete' in value:
                    self.observation['setup_complete'] = True
                error = value.get('error')
                if isinstance(error,dict) and type(error.get('code')) is int:
                    self.observation['provider_error_code'] = error['code']
                    message = error.get('message','')
                    if isinstance(message,str):
                        self.observation['provider_error_fields'] = [field for field in (
                            'translationConfig','inputAudioTranscription','outputAudioTranscription',
                            'maxOutputTokens','targetLanguageCode','echoTargetLanguage') if field in message]
                usage = value.get('usageMetadata')
                if isinstance(usage,dict):
                    event = {key:usage[key] for key in ('promptTokenCount','responseTokenCount','totalTokenCount')
                             if type(usage.get(key)) is int and 0 <= usage[key] <= 10**7}
                    events = self.observation['usage_snapshots']
                    if event:
                        events.append(event)
                    if len(events)>64:
                        raise ValueError('usage_limit')
                    # Conservative SUM of reported observations (not an invoice;
                    # snapshots may be cumulative). Stop before further input.
                    cost = sum(e.get('promptTokenCount',0)*7+e.get('responseTokenCount',0)*42 for e in events)
                    self.observation['observed_token_estimate_micro'] = (cost+1)//2
                    if cost >= 180000:  # $0.09, within the approved $0.10 lease.
                        raise ValueError('usage_limit')
        return raw


def once(configured):
    """Durable unpaid run marker: restart/duplicate invocation never dispatches."""
    import db
    from . import live_gemini_budget as budget, usage
    from .autonomous_store import transaction
    if db.BACKEND != 'postgres':
        raise ValueError('production_postgres_required')
    owner = configured['owner']
    with transaction() as conn:
        budget.ledger._campaign(conn,budget.policy())
        budget.ledger._owner(conn,owner)
        row = usage._query(conn,'SELECT email,role FROM users WHERE id=?',(owner,),one=True)
        if not row or row[0].strip().lower()!=configured['email'] or row[1]!='CLIENT_OWNER':
            raise ValueError('owner_mismatch')
        remaining=configured.get('remaining',False)
        marker = 'gemini-qa-'+RUN+('-remaining' if remaining else '')
        if budget.ledger._row(conn,owner,marker):
            return False
        # Read-only detection; never End/reset a legitimate owner's session.
        if usage._query(conn,"SELECT 1 FROM kilas_live_translator_sessions WHERE user_id=? AND status='ACTIVE' AND (expires_at='' OR expires_at>?)",(owner,datetime.now(timezone.utc).isoformat()),one=True):
            raise ValueError('owner_session_busy')
        if remaining:
            first='live-'+hashlib.sha256((RUN+'id'+'en').encode()).hexdigest()[:32]
            second='live-'+hashlib.sha256((RUN+'en'+'id').encode()).hexdigest()[:32]
            # Reconcile only this known failed setup after its child has exited.
            # Retain the entire estimate; no credit/refund and no provider IO.
            usage._query(conn,"UPDATE kilas_vo_stt_operations SET status='UNKNOWN',finished_at=? WHERE user_id=? AND campaign=? AND operation_key=? AND status='DISPATCHED' AND created_at<? AND EXISTS(SELECT 1 FROM kilas_audio_jobs j JOIN kilas_live_translator_turns t ON t.audio_job_id=j.id JOIN kilas_live_translator_sessions s ON s.id=t.session_id WHERE j.user_id=? AND t.operation_key=? AND j.status='FAILED' AND j.error_code='gemini_setup_invalid' AND j.actual_ms=0 AND s.status='ENDED')",
                         (datetime.now(timezone.utc).isoformat(),owner,budget.policy()['id'],first+'-gm',
                          (datetime.now(timezone.utc)-timedelta(seconds=120)).isoformat(),owner,first))
            previous=budget.ledger._row(conn,owner,first+'-gm')
            failed=usage._query(conn,"SELECT 1 FROM kilas_audio_jobs WHERE user_id=? AND operation_key=? AND status='FAILED' AND error_code='gemini_setup_invalid' AND actual_ms=0",(owner,first+'-audio'),one=True)
            if (not budget.ledger._row(conn,owner,'gemini-qa-'+RUN) or not previous
                    or previous[1]!=budget.policy()['id'] or previous[3]!='UNKNOWN'
                    or previous[4]!=budget.policy()['reserve'] or not failed
                    or budget.ledger._row(conn,owner,second+'-gm')):
                raise ValueError('remaining_test_not_available')
        usage._query(conn,"INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at,finished_at) VALUES (?,?,?,?,'CANCELLED',0,0,?,?,?)",
                     (owner,marker,budget.policy()['id'],hashlib.sha256(RUN.encode()).hexdigest(),'unpaid-run-marker',
                      datetime.now(timezone.utc).isoformat(),datetime.now(timezone.utc).isoformat()))
    return True


def session(configured, source, target, raw):
    import db
    from . import live_gemini as native, live_translator_store as sessions
    observation = {'direction':source+'-'+target, 'usage_snapshots':[], 'setup_complete':False,
                   'provider_connection':False, 'audible_measured':False}
    original = native.connect
    def observed_connect():
        started = time.monotonic()
        try:
            socket = original()
        except Exception as error:
            status = getattr(error,'status_code',None)
            if type(status) is int:
                observation['handshake_status'] = status
            raise
        observation.update(provider_connection=True,connect_ms=round((time.monotonic()-started)*1000,1))
        return ProbeSocket(socket,observation)
    native.connect = observed_connect
    owner = configured['owner']
    ident = sessions.create(owner,source,target,native.VOICE)
    key = 'live-'+hashlib.sha256((RUN+source+target).encode()).hexdigest()[:32]
    relay = None
    try:
        relay = native.start(owner,ident,key)
        # Real-time paced synthetic PCM only, no browser, device or microphone.
        started = time.monotonic()
        for index, offset in enumerate(range(0,len(raw),16000)):
            if relay.finished:
                break
            relay.accept(index,raw[offset:offset+16000])
            time.sleep(max(0,started+(index+1)*.5-time.monotonic()))
        input_finished_at=time.monotonic()
        if not relay.finished:
            relay.finish_input(relay.expected)
        deadline = started+45
        while not relay.finished and time.monotonic()<deadline:
            time.sleep(.05)
        if not relay.finished:
            relay.stop(native.failure('gemini_deadline'))
            # completed is a provider-marker event, not settlement completion.
            settled_by=time.monotonic()+2
            while not relay.finished and time.monotonic()<settled_by:
                time.sleep(.05)
        after = received = 0
        if relay.finished:
            while after<len(relay.frames):
                value = relay.snapshot(after)
                for frame in value['frames']:
                    if frame['type']=='audio':
                        received += len(base64.b64decode(frame['pcm'],validate=True))
                after = value['next_index']
        observation.update(input_ms=relay.accepted/32,output_ms=relay.output_bytes/48,
                           terminal_turn_complete=relay.completed.is_set(),settled=relay.finished,
                           output_cursor=after,total_frames=len(relay.frames),
                           all_generated_pcm_read=received==relay.output_bytes,
                           source_text=relay.source_text,translated_text=relay.target_text,
                           code=getattr(relay.error,'code',None))
        observation.update(streamed_before_input_finished=relay.first_output_at is not None and relay.first_output_at<input_finished_at,
                           input_stream_ms=round((input_finished_at-started)*1000,1),
                           source_tail_word_confirmed=tail_word(relay.source_text,source),
                           target_tail_word_confirmed=tail_word(relay.target_text,target),
                           first_audible_ms=None)
        if relay.first_output_at is not None and relay.first_input_at is not None:
            observation['backend_first_pcm_ms'] = round((relay.first_output_at-relay.first_input_at)*1000,1)
        if relay.end_at is not None:
            observation['finish_to_settled_ms'] = round((time.monotonic()-relay.end_at)*1000,1)
        # Persist token observations as an estimate alongside retained admission
        # allowance. Supplier billing/credit consumption remains unverified.
        events = observation['usage_snapshots']
        if events:
            db.execute('UPDATE kilas_vo_stt_operations SET input_tokens=?,output_tokens=?,actual_estimate_micro=? WHERE user_id=? AND operation_key=? AND campaign=?',
                       (sum(e.get('promptTokenCount',0) for e in events),sum(e.get('responseTokenCount',0) for e in events),
                        observation['observed_token_estimate_micro'],owner,key+'-gm','gml-'+RUN))
        return observation
    finally:
        protocol_before_end=relay.diagnostics() if relay else None
        error_before_end=getattr(relay.error,'code',None) if relay else None
        ended = time.monotonic()
        sessions.end(owner,ident)
        native.cancel(owner,ident)
        observation['backend_end_ms'] = round((time.monotonic()-ended)*1000,1)
        # A failed input check can race the relay's durable settlement. Allow
        # settlement to finish before this test process exits its daemon threads.
        settlement_deadline=time.monotonic()+10
        while relay is not None and not relay.finished and time.monotonic()<settlement_deadline:
            time.sleep(.05)
        observation['settled_after_end']=relay.finished if relay else False
        if relay is not None:
            observation['protocol']=protocol_before_end
            # Explicit cleanup End must not reclassify an already-settled success
            # as a failed provider turn. Keep cleanup state separate.
            observation.setdefault('code',error_before_end)
        observation['post_end_frames'] = len(relay.frames) if relay else 0
        try:
            native.owned(owner,ident,key)
        except native.audio_store.AudioError:
            observation['post_end_output_access'] = 'blocked'
        else:
            observation['post_end_output_access'] = 'unexpectedly_available'
        native.connect = original
        observation['backend_checks_passed']=passed(observation)
        report(observation)


def run():
    configured = config()
    if configured is None:
        return
    os.environ[ARM] = 'off'
    production=production_policy_check(configured['owner'])
    # These nonsecret values affect this child process only. The public web
    # service remains OFF; the approved campaign has exactly two $0.10 leases.
    os.environ.update({'KILAS_LIVE_GEMINI_ENABLED':'true','KILAS_LIVE_GEMINI_BILLING_VERIFIED':'yes',
                       'KILAS_LIVE_GEMINI_ALLOWED_OWNER_ID':str(configured['owner']),
                       'KILAS_LIVE_GEMINI_CAMPAIGN':RUN,'KILAS_LIVE_GEMINI_BUDGET_MICRO_USD':'200000',
                       'KILAS_LIVE_GEMINI_LEASE_RESERVE_MICRO_USD':'100000',
                       'KILAS_LIVE_GEMINI_EXPIRES_AT':configured['expiry']})
    from . import live_gemini as native, live_gemini_budget as budget
    original_limits = native.INPUT_BYTES,native.OUTPUT_BYTES,budget.LEASE_MS
    native.INPUT_BYTES, native.OUTPUT_BYTES = 15*32000,30*48000
    budget.LEASE_MS = 45000
    original_setup = native.setup
    def bounded_setup(target):
        value = original_setup(target)
        value['setup']['generationConfig']['maxOutputTokens'] = 512
        return value
    native.setup = bounded_setup
    try:
        samples = {language:fixture(language) for language in FIXTURES}
        if not once(configured):
            report({'run':RUN,'status':'already_attempted_no_retry'})
            return
        signal.alarm(105)  # Process-level backstop; restart cannot repeat marker.
        directions=(('en','id'),) if configured['remaining'] else (('id','en'),('en','id'))
        report({'run':RUN,'status':'started','max_sessions':len(directions),'allowance_micro':200000,
                'existing_production_policy':production})
        outcomes=[]
        for source,target in directions:
            result = session(configured,source,target,samples[source])
            outcomes.append({'direction':source+'-'+target,'passed':passed(result)})
            # Each authorized direction is independent and runs at most once.
            # A failed outcome is reported; it is never retried or regenerated.
        report({'run':RUN,'status':'completed_checks','outcomes':outcomes,
                'all_backend_checks_passed':all(outcome['passed'] for outcome in outcomes)})
    except Exception as error:
        # Never print exception text/traceback: supplier errors can contain keys.
        code = getattr(error,'code',None)
        report({'run':RUN,'status':'stopped_no_retry','code':code if isinstance(code,str) else 'qa_failed'})
    finally:
        signal.alarm(0)
        os.environ['KILAS_LIVE_GEMINI_ENABLED'] = 'false'
        native.INPUT_BYTES,native.OUTPUT_BYTES,budget.LEASE_MS = original_limits
        native.setup = original_setup


if __name__ == '__main__':
    run()
