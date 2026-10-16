"""Bounded one-person Gemini conversation. PCM/captions live only in RAM."""
import base64
import binascii
import json
import os
from queue import Queue, Empty, Full
from threading import Event, Lock, RLock, Thread, Timer
from time import monotonic
import db
from . import ai_call_budget as budget, live_gemini as wire, live_translator_output as storage

_lock=Lock()
_calls={}
INPUT_BYTES=60*32000
OUTPUT_BYTES=60*48000
QUEUE_BYTES=8*32000
MAX_TURNS=4


class CallError(ValueError):
    def __init__(self,code='call_transport',status=503):
        super().__init__(code)
        self.code,self.status=code,status


def ready(owner):
    from .routes import enabled
    value=budget.config()
    return bool(enabled() and value and budget.native.allowed(owner,value) and storage.single_worker()
                and os.environ.get('GEMINI_API_KEY','').strip())


def setup():
    # Official conversational Live model, no translator config, tools or history.
    return {'setup':{'model':'models/'+budget.MODEL,
        'systemInstruction':{'parts':[{'text':
            'You are Kilas, a helpful voice conversation partner for one person. '
            'Discuss ideas, answer questions, and help work through problems. '
            'Respond naturally in the language the person uses, including Indonesian or English. '
            'Keep spoken answers concise but useful. Ask when something is unclear. '
            'This is a new conversation, not an automatic translation or a group meeting. '
            'You have no access to their chat history, accounts, files or external tools. '
            'Do not claim to perform external actions or to have current information you lack.'}]},
        'generationConfig':{'responseModalities':['AUDIO'],'maxOutputTokens':1024,
            'speechConfig':{'voiceConfig':{'prebuiltVoiceConfig':{'voiceName':'Kore'}}}},
        'realtimeInputConfig':{'automaticActivityDetection':{'disabled':False,
            'prefixPaddingMs':300,'silenceDurationMs':800}},
        'outputAudioTranscription':{}}}


class Call:
    def __init__(self,owner,ident,capability,started=None):
        self.owner,self.ident,self.capability=owner,ident,capability
        self.started=monotonic() if started is None else started
        self.last_seen=monotonic();self.lock=RLock();self.send_lock=Lock();self.closed=Event()
        self.queue=Queue(maxsize=64);self.ws=None;self.state='CONNECTING';self.code=None
        self.input_bytes=0;self.output_bytes=0;self.queued=0;self.expected=0
        self.frames=[];self.caption='';self.turns=0;self.timer=None

    def check(self):
        if self.closed.is_set():raise CallError('call_ended',409)
        if monotonic()>=self.started+budget.LEASE_SECONDS:raise CallError('call_limit',409)
        if monotonic()-self.last_seen>8:raise CallError('call_network',409)
        if not ready(self.owner):raise CallError('call_unavailable')
        if not budget.active(self.owner,self.ident):raise CallError('call_ended',409)
        if self.closed.is_set():raise CallError('call_ended',409)

    def stop(self,code='call_ended',*,erase=False):
        with self.lock:
            first=not self.closed.is_set()
            self.closed.set();self.state='CLOSED'
            if first:self.code=code
            if erase:self.frames.clear();self.caption=''
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
        self.check()
        if type(index) is not int or not isinstance(raw,bytes) or not 2<=len(raw)<=16000 or len(raw)%2:raise CallError('call_input_invalid',400)
        with self.lock:
            if self.closed.is_set():raise CallError('call_ended',409)
            if index!=self.expected or self.expected>=1000:raise CallError('call_input_invalid',409)
            if self.input_bytes+len(raw)>INPUT_BYTES:raise CallError('call_limit',409)
            if self.queued+len(raw)>QUEUE_BYTES:raise CallError('call_backlog',409)
            try:self.queue.put_nowait(raw)
            except Full:raise CallError('call_backlog',409) from None
            self.expected+=1;self.input_bytes+=len(raw);self.queued+=len(raw)
            self.last_seen=monotonic()

    def publish(self,value):
        if len(self.frames)>=2048:raise CallError('call_output_invalid')
        self.frames.append({'index':len(self.frames),**value})

    def receive(self,raw):
        value=wire.message(raw)
        if any(k in value for k in ('error','toolCall','goAway')):raise CallError('call_provider')
        content=value.get('serverContent',{})
        if not isinstance(content,dict):raise CallError('call_output_invalid')
        with self.lock:
            if self.closed.is_set():return
            if content.get('interrupted') is True:
                self.publish({'type':'reset'});self.caption=''
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
                if not pcm or len(pcm)%2 or self.output_bytes+len(pcm)>OUTPUT_BYTES:raise CallError('call_limit')
                if self.turns>=MAX_TURNS:raise CallError('call_limit')
                self.output_bytes+=len(pcm);self.state='SPEAKING'
                for at in range(0,len(pcm),9600):self.publish({'type':'audio','pcm':base64.b64encode(pcm[at:at+9600]).decode('ascii')})
            transcript=content.get('outputTranscription')
            if transcript is not None:
                if not isinstance(transcript,dict) or not isinstance(transcript.get('text',''),str):raise CallError('call_output_invalid')
                self.caption+=transcript.get('text','')
                if len(self.caption)>4000:raise CallError('call_output_invalid')
                self.publish({'type':'text','text':self.caption})
            if content.get('turnComplete') is True and content.get('interactionStatus')!='IN_PROGRESS':
                self.turns+=1;self.publish({'type':'turn_complete'});self.caption='';self.state='LISTENING'
                if self.turns>=MAX_TURNS:self.stop('call_limit')

    def snapshot(self,after):
        with self.lock:
            if type(after) is not int or not 0<=after<=len(self.frames):raise CallError('call_cursor_invalid',400)
            self.last_seen=monotonic()
            frames=[dict(x) for x in self.frames[after:after+24]]
            return {'state':self.state,'code':self.code,'frames':frames,'next_index':after+len(frames),
                    'total_frames':len(self.frames),'remaining_seconds':max(0,int(self.started+90-monotonic()))}

    def send(self):
        try:
            while not self.closed.is_set():
                try:raw=self.queue.get(timeout=.1)
                except Empty:continue
                self.check()
                with self.lock:self.queued-=len(raw)
                with self.send_lock:
                    if self.closed.is_set():return
                    self.ws.send(json.dumps({'realtimeInput':{'audio':{
                        'mimeType':'audio/pcm;rate=16000','data':base64.b64encode(raw).decode('ascii')}}}))
        except Exception as error:self.stop(getattr(error,'code','call_transport'))
        finally:db._discard_cached_connection()

    def watch(self):
        try:
            while not self.closed.wait(1):self.check()
        except Exception as error:self.stop(getattr(error,'code','call_transport'))
        finally:db._discard_cached_connection()

    def run(self):
        self.timer=Timer(max(0,self.started+90-monotonic()),self.stop,args=('call_limit',))
        self.timer.daemon=True;self.timer.start()
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
                try:raw=self.ws.recv()
                except websocket.WebSocketTimeoutException:continue
                if not raw:raise CallError('call_transport')
                self.check();self.receive(raw)
        except Exception as error:
            code=getattr(error,'code','call_transport')
            self.stop(code if code.startswith('call_') else 'call_transport')
        finally:
            self.stop();self.timer.cancel()
            # Release queued raw input promptly even after a failed handshake.
            while True:
                try:self.queue.get_nowait()
                except Empty:break
            try:budget.finish(self.capability)
            except Exception:print('KILAS_AI_CALL settlement=unknown',flush=True)
            db._discard_cached_connection()
            print(f'KILAS_AI_CALL closed=true input_ms={self.input_bytes/32:.1f} output_ms={self.output_bytes/48:.1f}',flush=True)


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
