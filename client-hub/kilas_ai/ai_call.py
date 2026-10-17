"""One-person Gemini conversation with bounded buffers and renewable funding."""
import base64
import binascii
import json
import os
import math
import struct
from queue import Queue, Empty, Full
from threading import Event, Lock, RLock, Thread, Timer
from time import monotonic
import db
from . import ai_call_budget as budget, live_gemini as wire, live_translator_output as storage
from . import ai_call_public_search as public_search
from .ai_call_timing import TurnTiming

_lock=Lock()
_calls={}
INPUT_BYTES=60*32000
OUTPUT_BYTES=60*48000
QUEUE_BYTES=8*32000
MAX_TURNS=4
POLICY_TTL_SECONDS=3


class CallError(ValueError):
    def __init__(self,code='call_transport',status=503):
        super().__init__(code)
        self.code,self.status=code,status


def ready(owner):
    from .routes import enabled
    value=budget.config()
    return bool(enabled() and value and budget.native.allowed(owner,value) and storage.single_worker()
                and os.environ.get('GEMINI_API_KEY','').strip())


def setup(handle=None):
    # Separate conversational session; public lookup never imports chat history.
    value = {'setup':{'model':'models/'+budget.MODEL,
        'systemInstruction':{'parts':[{'text':
            'You are Kilas, a helpful voice conversation partner for one person. '
            'Discuss ideas, answer questions, and help work through problems. '
            'Respond naturally in the language the person uses, including Indonesian or English. '
            'Keep spoken answers concise but useful. Remember the details, constraints, decisions and references from earlier turns in this call. '
            'Answer the latest question in that context; follow-up questions may omit details already given. '
            'Answer directly in clear, natural short sentences, using relevant facts and examples when helpful. '
            'Distinguish uncertainty from established knowledge and avoid repetitive generic replies or canned menus. '
            'Ask for clarification only when a missing detail changes the answer; use the available context instead of asking the person to repeat it. '
            'Wait silently for intelligible speech; silence, noise and playback echo are not requests. '
            'Never invent words or a topic from unclear audio. If speech is partly clear, briefly state the specific part you understood and ask only for the missing detail. '
            'If nothing is intelligible, ask once briefly for a clearer repeat, then wait for speech. '
            'This is a new conversation, not an automatic translation or a group meeting. '
            'You have no access to their chat history, accounts or files. '
            + public_search.instructions() +
            'Do not claim to perform external actions or to have current information you lack.'}]},
        'generationConfig':{'responseModalities':['AUDIO'],'maxOutputTokens':1024,
            'speechConfig':{'voiceConfig':{'prebuiltVoiceConfig':{'voiceName':'Kore'}}}},
        'realtimeInputConfig':{'activityHandling':'NO_INTERRUPTION','automaticActivityDetection':{'disabled':False,
            'prefixPaddingMs':300,'silenceDurationMs':1200,'startOfSpeechSensitivity':'START_SENSITIVITY_HIGH',
            'endOfSpeechSensitivity':'END_SENSITIVITY_LOW'}},
        'inputAudioTranscription':{},'outputAudioTranscription':{},
        'contextWindowCompression':{'triggerTokens':12000,'slidingWindow':{'targetTokens':6000}},
        'sessionResumption':{'handle':handle} if handle else {}}}
    if public_search.configured():
        value['setup']['tools'] = [public_search.declaration()]
    return value


class Call:
    def __init__(self,owner,ident,capability,started=None):
        self.owner,self.ident,self.capability=owner,ident,capability
        self.started=monotonic() if started is None else started
        self.last_seen=monotonic();self.lock=RLock();self.send_lock=Lock();self.closed=Event()
        self.queue=Queue(maxsize=64);self.ws=None;self.state='CONNECTING';self.code=None
        self.input_bytes=0;self.output_bytes=0;self.queued=0;self.expected=0
        self.frames=[];self.caption='';self.turns=0;self.interruptions=0;self.timer=None
        self.frame_base=0;self.frame_next=0
        self.funded_at=self.started;self.funded_input=0;self.funded_output=0;self.funded_turns=0
        self.renewing=Event();self.resume_handle=None;self.go_away=False;self.resume_pending=False
        self.provider_started=self.started
        self.input_energy=0;self.input_samples=0;self.input_peak=0;self.input_transcript_chars=0
        self.sent_bytes=0;self.sent_chunks=0;self.provider_messages=0
        self.public_search = public_search.PublicSearch(self)
        self.turn_timing = TurnTiming()
        # Claim has just authorized this capability. The provider worker also
        # rechecks it before setup; only the watchdog renews this short lease.
        self.authorized_until=self.started+POLICY_TTL_SECONDS

    def transport_check(self,*,require_policy=True):
        """In-memory PCM/frame fence; database work only at funding boundaries."""
        from .routes import enabled
        if self.closed.is_set():raise CallError('call_ended',409)
        if monotonic()-self.last_seen>8:raise CallError('call_network',409)
        if not (enabled() and budget.config() and storage.single_worker()
                and os.environ.get('GEMINI_API_KEY','').strip()):raise CallError('call_unavailable')
        with self.lock:
            if self.closed.is_set():raise CallError('call_ended',409)
            if self.go_away and monotonic()>=self.go_away_deadline:raise CallError('call_provider')
            if require_policy and monotonic()>self.authorized_until:raise CallError('call_unavailable')
            # This rare metering boundary still performs normal durable funding
            # before any input/output can exceed the current allowance.
            if monotonic()-self.funded_at>=budget.RENEW_SECONDS:self.fund()

    def check(self):
        """Fresh admission/watchdog authorization, outside the audio lock.

        A fresh PostgreSQL transaction on every packet and provider frame can
        stall the speech clock. The watchdog rechecks every second; stalled or
        revoked authorization fails closed within the short transport lease.
        """
        self.transport_check(require_policy=False)
        checked_at=monotonic()
        with self.lock:capability=self.capability
        try:
            if not ready(self.owner):raise CallError('call_unavailable')
            if not budget.active(self.owner,self.ident,capability):raise CallError('call_ended',409)
        except Exception:
            with self.lock:
                # A concurrently renewed capability was independently authorized
                # by normal funding. A stale check must not revoke that result.
                if capability is not self.capability:return
                self.authorized_until=0
            raise
        with self.lock:
            if self.closed.is_set():raise CallError('call_ended',409)
            if capability is self.capability:
                if monotonic()-checked_at>POLICY_TTL_SECONDS:
                    self.authorized_until=0;raise CallError('call_unavailable')
                self.authorized_until=checked_at+POLICY_TTL_SECONDS

    def fund(self):
        # Caller holds the Call lock; End cannot interleave a new reservation.
        if self.closed.is_set():raise CallError('call_ended',409)
        self.capability=budget.renew(self.capability)
        self.funded_at=monotonic();self.funded_input=self.input_bytes
        self.funded_output=self.output_bytes;self.funded_turns=self.turns
        self.authorized_until=monotonic()+POLICY_TTL_SECONDS

    def stop(self,code='call_ended',*,erase=False):
        with self.lock:
            first=not self.closed.is_set()
            self.closed.set();self.state='CLOSED'
            self.resume_handle=None;self.resume_pending=False
            if first:self.code=code
            if erase:self.frames.clear();self.caption=''
        self.public_search.cancel()
        if self.ws:
            try:self.ws.shutdown()
            except Exception:pass
        if first:
            def purge():
                with self.lock:self.frames.clear();self.caption=''
                with _lock:
                    if _calls.get((self.owner,self.ident)) is self:_calls.pop((self.owner,self.ident),None)
            timer=Timer(10,purge);timer.daemon=True;timer.start()

    def accept(self,index,raw):
        self.transport_check()
        if type(index) is not int or not isinstance(raw,bytes) or not 2<=len(raw)<=16000 or len(raw)%2:raise CallError('call_input_invalid',400)
        with self.lock:
            if self.closed.is_set():raise CallError('call_ended',409)
            if index!=self.expected:raise CallError('call_input_invalid',409)
            if self.input_bytes-self.funded_input+len(raw)>INPUT_BYTES:self.fund()
            if self.queued+len(raw)>QUEUE_BYTES:raise CallError('call_backlog',409)
            try:self.queue.put_nowait(raw)
            except Full:raise CallError('call_backlog',409) from None
            # Non-content diagnostics only; no PCM or transcript is persisted.
            samples=[value[0]/32768 for value in struct.iter_unpack('<h',raw)]
            self.input_energy+=sum(value*value for value in samples);self.input_samples+=len(samples)
            self.input_peak=max(self.input_peak,max(abs(value) for value in samples))
            self.expected+=1;self.input_bytes+=len(raw);self.queued+=len(raw)
            self.last_seen=monotonic()

    def publish(self,value):
        if len(self.frames)>=2048:raise CallError('call_output_invalid')
        self.frames.append({'index':self.frame_next,**value});self.frame_next+=1

    def receive(self,raw):
        value=wire.message(raw)
        if 'error' in value:raise CallError('call_provider')
        activity = value.get('voiceActivity')
        if isinstance(activity,dict):
            self.turn_timing.activity(activity.get('type'))
            self.public_search.activity(activity.get('type'))
        if 'toolCall' in value and not self.public_search.handle(value['toolCall']):raise CallError('call_provider')
        cancellation = value.get('toolCallCancellation')
        if cancellation is not None:
            ids = cancellation.get('ids') if isinstance(cancellation, dict) else None
            if not isinstance(ids, list) or len(ids)>128 or any(not isinstance(i,str) or len(i)>256 for i in ids):
                raise CallError('call_output_invalid')
            self.public_search.cancel(ids)
        content=value.get('serverContent',{})
        if not isinstance(content,dict):raise CallError('call_output_invalid')
        with self.lock:
            if self.closed.is_set():return
            self.provider_messages+=1
            if 'goAway' in value:
                if not isinstance(value['goAway'],dict) or monotonic()-self.provider_started<30:
                    raise CallError('call_provider')
                # Pause unsent PCM. Only a NEW resumable checkpoint after the
                # provider's expiry warning can move this same conversation.
                self.go_away=True;self.go_away_deadline=monotonic()+30
                self.resume_handle=None;self.renewing.set()
            update=value.get('sessionResumptionUpdate')
            if update is not None:
                if not isinstance(update,dict):raise CallError('call_provider')
                handle=update.get('newHandle')
                if update.get('resumable') is True and isinstance(handle,str) and 0<len(handle)<=8192:
                    if self.go_away:
                        self.resume_handle=handle;self.resume_pending=True
                else:self.resume_handle=None;self.resume_pending=False
            if content.get('interrupted') is True:
                self.turn_timing.boundary()
                self.interruptions+=1;self.publish({'type':'reset'});self.caption=''
            turn=content.get('modelTurn',{})
            if not isinstance(turn,dict) or not isinstance(turn.get('parts',[]),list):raise CallError('call_output_invalid')
            for part in turn.get('parts',[]):
                if not isinstance(part,dict):raise CallError('call_output_invalid')
                audio=part.get('inlineData')
                if audio is None:continue
                if (not isinstance(audio,dict) or audio.get('mimeType')!='audio/pcm;rate=24000'
                        or not isinstance(audio.get('data'),str)):raise CallError('call_output_invalid')
                try:pcm=base64.b64decode(audio['data'],validate=True)
                except (ValueError,binascii.Error):raise CallError('call_output_invalid') from None
                if not pcm or len(pcm)%2:raise CallError('call_output_invalid')
                self.turn_timing.audio()
                if self.output_bytes-self.funded_output+len(pcm)>OUTPUT_BYTES or self.turns-self.funded_turns>=MAX_TURNS:self.fund()
                self.output_bytes+=len(pcm);self.state='SPEAKING'
                for at in range(0,len(pcm),9600):self.publish({'type':'audio','pcm':base64.b64encode(pcm[at:at+9600]).decode('ascii')})
            heard=content.get('inputTranscription')
            if heard is not None:
                if not isinstance(heard,dict) or not isinstance(heard.get('text',''),str) or len(heard.get('text',''))>4000:
                    raise CallError('call_output_invalid')
                self.input_transcript_chars+=len(heard.get('text',''))
                # Live inputTranscription has no required "finished" field.
                # It is delivered independently from activity and tool events.
                self.public_search.observe(heard.get('text',''))
            transcript=content.get('outputTranscription')
            if transcript is not None:
                if not isinstance(transcript,dict) or not isinstance(transcript.get('text',''),str):raise CallError('call_output_invalid')
                self.caption+=transcript.get('text','')
                if len(self.caption)>4000:raise CallError('call_output_invalid')
                self.publish({'type':'text','text':self.caption})
            if content.get('turnComplete') is True and content.get('interactionStatus')!='IN_PROGRESS':
                self.turn_timing.boundary()
                self.public_search.turn_complete()
                self.turns+=1;self.publish({'type':'turn_complete'});self.caption='';self.state='LISTENING'

    def snapshot(self,after):
        with self.lock:
            if type(after) is not int or not self.frame_base<=after<=self.frame_next:raise CallError('call_cursor_invalid',400)
            self.last_seen=monotonic()
            # The next client cursor acknowledges prior frames. Drop consumed
            # audio so a long call retains only the bounded outstanding backlog.
            del self.frames[:after-self.frame_base];self.frame_base=after
            frames=[dict(x) for x in self.frames[:24]]
            return {'state':self.state,'code':self.code,'frames':frames,'next_index':after+len(frames),
                    'total_frames':self.frame_next}

    def send(self):
        try:
            while not self.closed.is_set():
                try:raw=self.queue.get(timeout=.1)
                except Empty:continue
                self.transport_check()
                with self.lock:self.queued-=len(raw)
                while not self.closed.is_set():
                    if self.renewing.is_set():
                        if self.closed.wait(.05):return
                        continue
                    with self.send_lock:
                        if self.closed.is_set():return
                        if self.renewing.is_set():continue
                        self.ws.send(json.dumps({'realtimeInput':{'audio':{
                            'mimeType':'audio/pcm;rate=16000','data':base64.b64encode(raw).decode('ascii')}}}))
                        with self.lock:self.sent_bytes+=len(raw);self.sent_chunks+=1
                        break
        except Exception as error:self.stop(getattr(error,'code','call_transport'))
        finally:db._discard_cached_connection()

    def watch(self):
        try:
            while not self.closed.wait(1):self.check()
        except Exception as error:self.stop(getattr(error,'code','call_transport'))
        finally:db._discard_cached_connection()

    def run(self):
        try:
            self.check();budget.dispatch(self.capability);self.check()
            self.ws=wire.connect();self.check()
            self.ws.send(json.dumps(setup()))
            hello=wire.message(self.ws.recv())
            if not isinstance(hello.get('setupComplete'),dict) or any(k in hello for k in ('error','toolCall','goAway')):raise CallError('call_provider')
            self.check();self.ws.settimeout(.5)
            with self.lock:self.state='LISTENING'
            Thread(target=self.send,name='kilas-call-input',daemon=True).start()
            Thread(target=self.watch,name='kilas-call-fence',daemon=True).start()
            import websocket
            while not self.closed.is_set():
                if self.resume_pending:self.resume()
                try:raw=self.ws.recv()
                except websocket.WebSocketTimeoutException:continue
                if not raw:raise CallError('call_transport')
                self.transport_check();self.receive(raw)
        except Exception as error:
            code=getattr(error,'code','call_transport')
            self.stop(code if code.startswith('call_') or code in ('budget_limit','account_credit_limit') else 'call_transport')
        finally:
            self.stop()
            # Release queued raw input promptly even after a failed handshake.
            while True:
                try:self.queue.get_nowait()
                except Empty:break
            try:budget.finish(self.capability)
            except Exception:print('KILAS_AI_CALL settlement=unknown',flush=True)
            db._discard_cached_connection()
            safe_reasons={'call_ended','call_network','call_unavailable','call_backlog','budget_limit','account_credit_limit',
                          'call_input_invalid','call_output_invalid','call_provider','call_transport'}
            reason=self.code if self.code in safe_reasons else 'call_transport'
            print(f'KILAS_AI_CALL closed=true reason={reason} input_ms={self.input_bytes/32:.1f} sent_ms={self.sent_bytes/32:.1f} sent_chunks={self.sent_chunks} provider_messages={self.provider_messages} output_ms={self.output_bytes/48:.1f} interruptions={self.interruptions} turns={self.turns} input_rms={math.sqrt(self.input_energy/max(1,self.input_samples)):.5f} input_peak={self.input_peak:.5f} heard_chars={self.input_transcript_chars}',flush=True)
            # Counts and enumerated outcomes only; no text, function IDs, queries
            # or customer/account identifiers are included.
            print('KILAS_AI_CALL_SEARCH '+json.dumps(self.public_search.diagnostic(),sort_keys=True),flush=True)
            print('KILAS_AI_CALL_TIMING '+json.dumps(self.turn_timing.report(),sort_keys=True),flush=True)

    def resume(self):
        # Exactly one supported handoff per provider warning, with no reconnect
        # on network errors and no replay of already dispatched mic/output PCM.
        with self.send_lock:
            self.check()
            with self.lock:
                if not self.resume_pending or not self.resume_handle:raise CallError('call_provider')
                handle=self.resume_handle;self.resume_handle=None;self.resume_pending=False
            self.ws.shutdown()
            socket=wire.connect()
            with self.lock:
                self.ws=socket
                if self.closed.is_set():socket.shutdown();raise CallError('call_ended',409)
            self.check();socket.send(json.dumps(setup(handle)))
            hello=wire.message(socket.recv())
            if not isinstance(hello.get('setupComplete'),dict) or any(k in hello for k in ('error','toolCall','goAway')):
                raise CallError('call_provider')
            self.check();socket.settimeout(.5)
            self.provider_started=monotonic();self.go_away=False;self.renewing.clear()


def start(owner,ident):
    began=monotonic()
    if not ready(owner):raise CallError('call_unavailable')
    with _lock:
        if (owner,ident) in _calls:raise CallError('duplicate_turn',409)
        if len(_calls)>=16:raise CallError('service_busy',429)
    capability=budget.claim(owner,ident)
    call=Call(owner,ident,capability,began)
    with _lock:_calls[(owner,ident)]=call
    try:Thread(target=call.run,name='kilas-ai-call',daemon=True).start()
    except Exception:
        call.stop(erase=True);budget.finish(capability)
        raise CallError('call_unavailable') from None
    return call


def get(owner,ident):
    budget.key(ident)
    with _lock:call=_calls.get((owner,ident))
    if call:return call
    if not budget.owned(owner,ident):raise CallError('not_owned',404)
    return None


def end(owner,ident):
    with _lock:call=_calls.get((owner,ident))
    if call:call.stop(erase=True)
    budget.end(owner,ident)
