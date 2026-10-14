"""Server-key realtime relay; zero paid IO until account-specific proof exists.

Registry is only a bounded transport cache. Shared DB admission, lease and End
fences prevent duplicate dispatch; a different HTTP worker fails/pauses instead
of opening another supplier socket. A500ms watcher closes cross-worker End.
"""
import base64
from contextlib import ExitStack
import json
import os
from queue import Queue,Empty,Full
from threading import Event,Lock,Thread,Timer,BoundedSemaphore
from time import monotonic
from urllib.parse import urlencode
import db
from . import live_translator as live,live_translator_store as sessions
from . import audio_store, audio_transcription_provider as stt, live_translator_transport as transport
from . import live_translator_realtime_account as account,live_translator_realtime_budget as budget

_lock=Lock();_relays={};_slots=BoundedSemaphore(2)
MAX_AUDIO_BYTES=180*32000  #179s capture plus<=400ms retained voice pre-roll.
QUEUE_BYTES=128000
COMMIT_BYTES=20*32000


def failure(code='realtime_failed'):
    return audio_store.AudioError('Input suara belum berhasil. Sesi dijeda; ucapan ini tidak diulang dalam mode lain.',code,503)


def ready(owner):
    return live.ready(owner) and account.verified()


def require_ready(owner):
    if not ready(owner):raise failure('realtime_unverified')


def connect():
    # Lazy import: importing/testing this module never opens a paid connection.
    import websocket
    query=urlencode({'model_id':account.MODEL,'audio_format':'pcm_16000','commit_strategy':'manual',
        'include_timestamps':'false','include_language_detection':'false','no_verbatim':'false',
        'enable_logging':'true'})
    return websocket.create_connection('wss://api.elevenlabs.io/v1/speech-to-text/realtime?'+query,
        header={'xi-api-key':os.environ['ELEVENLABS_API_KEY'].strip()},timeout=5,enable_multithread=True,redirect_limit=0)


class Relay:
    def __init__(self,owner,ident,key,info,capability):
        self.owner,self.ident,self.key,self.info,self.capability=owner,ident,key,info,capability
        self.queue=Queue(maxsize=64);self.acks=Queue(maxsize=1);self.lock=Lock();self.closed=Event()
        self.ws=None;self.expected=0;self.accepted=0;self.queued_bytes=0;self.final=False
        self.pending_ack=False;self.error=None;self.pieces=[];self.sent=0;self.since_commit=0
        self.started=monotonic();self.last_chunk=self.started;self.final_at=None;self.finished=False;self.deadline=None

    def check(self):
        if self.closed.is_set():raise self.error or failure('turn_cancelled')
        if monotonic()-self.started>=budget.LEASE_MS/1000:raise failure('realtime_deadline')
        live.require_ready(self.owner);sessions.check(self.owner,self.ident,self.key)
        if self.closed.is_set():raise self.error or failure('turn_cancelled')

    def arm_deadline(self):
        # Independent of potentially slow database fences. This is a transport
        # interruption, never a claim about unknown supplier billing minimums.
        self.deadline=Timer(max(0,budget.LEASE_MS/1000-(monotonic()-self.started)),self.close,args=(failure('realtime_deadline'),))
        self.deadline.daemon=True;self.deadline.start()

    def accept(self,index,raw):
        if type(index) is not int or not isinstance(raw,bytes) or not 2<=len(raw)<=32000 or len(raw)%2:raise failure('realtime_chunk_invalid')
        with self.lock:
            self.check()
            if self.final or index!=self.expected or self.expected>=2000 or self.accepted+len(raw)>MAX_AUDIO_BYTES:raise failure('realtime_chunk_invalid')
            if self.queued_bytes+len(raw)>QUEUE_BYTES:raise failure('realtime_queue_full')
            try:self.queue.put_nowait(raw)
            except Full:raise failure('realtime_queue_full') from None
            self.expected+=1;self.accepted+=len(raw);self.queued_bytes+=len(raw);self.last_chunk=monotonic()

    def commit(self,count):
        with self.lock:
            self.check()
            if type(count) is not int or count!=self.expected or self.final or not self.accepted:raise failure('realtime_chunk_invalid')
            self.final=True;self.final_at=monotonic()
            try:self.queue.put_nowait(None)
            except Full:raise failure('realtime_queue_full') from None

    def close(self,error=None):
        if error is not None:self.error=error
        self.closed.set()
        ws=self.ws
        if ws:
            try:ws.shutdown()  # Interrupt blocked recv; no heartbeat/paid idle loop.
            except Exception:pass

    def watch(self):
        try:
            while not self.closed.wait(.5):
                self.check()
                if not self.final and monotonic()-self.last_chunk>5:raise failure('realtime_input_idle')
        except Exception as error:self.close(error)
        finally:db._discard_cached_connection()

    def receive(self):
        try:
            while not self.closed.is_set():
                raw=self.ws.recv()
                if not isinstance(raw,str) or len(raw)>65536:raise failure('realtime_response_invalid')
                value=json.loads(raw);kind=value.get('message_type')
                if kind=='committed_transcript':
                    text=value.get('text')
                    if not isinstance(text,str) or len(text)>4000:raise failure('realtime_response_invalid')
                    with self.lock:
                        if not self.pending_ack:raise failure('realtime_commit_unexpected')
                        self.pending_ack=False
                    try:self.acks.put_nowait(text.strip())
                    except Full:raise failure('realtime_commit_unexpected') from None
                elif kind not in ('partial_transcript','committed_transcript_with_timestamps','edited_transcript','warning'):
                    # No terms acceptance, alternate paid request or hidden retry.
                    raise failure('realtime_quota' if kind=='quota_exceeded' else 'realtime_provider_error')
        except Exception as error:
            if not self.closed.is_set():self.close(error if isinstance(error,audio_store.AudioError) else failure('realtime_transport'))

    def send(self,raw,commit=False):
        self.check()
        if commit:
            with self.lock:
                if self.pending_ack:raise failure('realtime_commit_unexpected')
                self.pending_ack=True
        self.ws.send(json.dumps({'message_type':'input_audio_chunk','audio_base_64':base64.b64encode(raw).decode(),'sample_rate':16000,'commit':commit}))

    def acknowledge(self):
        deadline=monotonic()+8
        while True:
            self.check()
            try:text=self.acks.get(timeout=.1);break
            except Empty:
                if monotonic()>=deadline:raise failure('realtime_commit_timeout')
        if text:self.pieces.append(text)
        if len(' '.join(self.pieces))>4000:raise failure('realtime_text_limit')
        self.since_commit=0

    def run(self):
        success=False;connection=ExitStack()
        try:
            # Keep both fresh credit reads on one relay-owned HTTPS connection.
            # Setup belongs inside the same failure/ledger/slot cleanup as STT.
            connection.enter_context(transport.turn_connection())
            self.arm_deadline()
            Thread(target=self.watch,name='kilas-realtime-fence',daemon=True).start()
            self.check();stt.require_subscription_credit();self.check()
            budget.dispatch(self.capability)  # Unknown handshake cost is durable.
            self.ws=connect();self.check();self.ws.settimeout(8)
            raw=self.ws.recv()
            if not isinstance(raw,str) or len(raw)>65536:raise failure('realtime_response_invalid')
            started=json.loads(raw)
            config=started.get('config',{})
            if started.get('message_type')!='session_started' or config.get('model_id')!=account.MODEL or config.get('audio_format')!='pcm_16000' or config.get('sample_rate')!=16000:raise failure('realtime_response_invalid')
            Thread(target=self.receive,name='kilas-realtime-reader',daemon=True).start()
            while True:
                self.check()
                try:raw=self.queue.get(timeout=.1)
                except Empty:
                    if monotonic()-self.last_chunk>5:raise failure('realtime_input_idle')
                    continue
                if raw is None:
                    if self.since_commit:
                        self.send(b'',True);self.acknowledge()
                    break
                with self.lock:self.queued_bytes-=len(raw)
                # Each payload is<=1s. Commit exactly20s, below provider's36s
                # auto boundary; wait its sole ack BEFORE any following bytes.
                offset=0
                while offset<len(raw):
                    count=min(len(raw)-offset,COMMIT_BYTES-self.since_commit)
                    piece=raw[offset:offset+count];self.send(piece);self.sent+=count;self.since_commit+=count;offset+=count
                    if self.since_commit==COMMIT_BYTES:self.send(b'',True);self.acknowledge()
            self.check();text=' '.join(self.pieces).strip()
            if not text:raise failure('no_speech')
            if not budget.finish(self.capability,True):raise failure('realtime_budget_unsettled')
            success=True;self.close()
            self.deadline.cancel()  # Output has its separate180s processing window.
            # No microphone/paid STT fallback; the existing complete translation
            # and one billed whole-utterance output consume this stable whole text.
            finalized=monotonic()
            live.process(self.owner,self.ident,self.key,None,self.info,whole_output=True,committed_text=text,
                started=self.final_at,timings={'realtime_input_ms':self.sent/32,
                    'realtime_transport_ms':(finalized-self.started)*1000,
                    'realtime_finalize_ms':(finalized-self.final_at)*1000,
                    'realtime_commits':len(self.pieces)})
        except Exception as error:
            self.close(error)
            if not success:budget.finish(self.capability,False)
            sessions.finish(self.owner,self.ident,self.key,False,code=getattr(error,'code','realtime_failed'))
        finally:
            self.close();self.finished=True
            if self.deadline:self.deadline.cancel()
            with _lock:_relays.pop((self.owner,self.ident,self.key),None)
            try:_slots.release();db._discard_cached_connection()
            finally:connection.close()


def start(owner,ident,key):
    require_ready(owner)
    if not _slots.acquire(blocking=False):raise failure('service_busy')
    capability=None;claimed=False
    try:
        info=sessions.claim(owner,ident,key);claimed=True
        audio_store.require_balance(owner);live.require_audio_allowance(owner)
        capability=budget.claim(owner,ident,key)
        relay=Relay(owner,ident,key,info,capability)
        with _lock:_relays[(owner,ident,key)]=relay
        Thread(target=relay.run,name='kilas-realtime-turn',daemon=True).start()
        return relay
    except Exception as error:
        if capability:budget.finish(capability,False)
        if claimed:sessions.finish(owner,ident,key,False,code=getattr(error,'code','realtime_failed'))
        _slots.release()
        if isinstance(error,budget.batch.BudgetError):
            raise audio_store.AudioError('Batas input suara belum mengizinkan ucapan berikutnya. Sesi dijeda.',error.code,error.status) from None
        raise


def owned(owner,ident,key):
    sessions.check(owner,ident,key)
    with _lock:relay=_relays.get((owner,ident,key))
    if not relay:
        # Routing to another worker is a truthful failure, not another handshake.
        sessions.cancel_turn(owner,ident,key)
        raise failure('realtime_worker_unavailable')
    return relay


def cancel(owner,ident,key=None):
    with _lock:relays=[r for (user,session,operation),r in _relays.items() if user==owner and session==ident and (key is None or operation==key)]
    for relay in relays:relay.close(failure('turn_cancelled'))
