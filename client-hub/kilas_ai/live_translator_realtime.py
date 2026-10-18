"""Server-key realtime relay; zero paid IO until account-specific proof exists.

Registry is only a bounded transport cache. Shared DB admission, lease and End
fences prevent duplicate dispatch; a different HTTP worker fails/pauses instead
of opening another supplier socket. A500ms watcher closes cross-worker End.
"""
import base64
from contextlib import ExitStack
import json
import os
import struct
from queue import Queue,Empty,Full
from threading import Event,Lock,Thread,Timer,BoundedSemaphore
from time import monotonic
from urllib.parse import urlencode
import db
from . import live_translator as live,live_translator_store as sessions
from . import audio_store, audio_transcription_provider as stt, live_translator_transport as transport
from . import live_translator_realtime_account as account,live_translator_realtime_budget as budget
from . import live_translator_incremental as incremental

_lock=Lock();_relays={};_slots=BoundedSemaphore(2)
MAX_AUDIO_BYTES=180*32000  #179s capture plus<=400ms retained voice pre-roll.
QUEUE_BYTES=8*32000  # Match the bounded client startup/jitter buffer; no additional paid dispatch.
COMMIT_BYTES=20*32000


def failure(code='realtime_failed'):
    return audio_store.AudioError('Input suara belum berhasil. Sesi dijeda; ucapan ini tidak diulang dalam mode lain.',code,503)


def log_input(success,error,started,timings):
    known={'turn_cancelled','session_ended','no_speech','realtime_input_idle','realtime_queue_full',
        'realtime_commit_timeout','realtime_commit_unexpected','realtime_response_invalid',
        'realtime_transport','realtime_deadline','realtime_text_limit','realtime_provider_error',
        'realtime_quota','provider_credit_check_failed','provider_credit_exhausted',
        'realtime_budget_unsettled'}
    code=getattr(error,'code',None)
    code='none' if success else code if isinstance(code,str) and code in known else 'other_failure'
    stages=' '.join(f'{name}={timings[name]:.1f}' for name in
        ('credit_stt_ms','input_connect_ms','input_finalize_ms','input_early_commits') if name in timings)
    # Fixed enums/numeric timings only; never text, audio, IDs, keys or provider errors.
    try:print(f'KILAS_LIVE_INPUT outcome={"completed" if success else "failed"} code={code} {stages} elapsed_ms={(monotonic()-started)*1000:.1f}',flush=True)
    except OSError:pass


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
        self.partial='';self.partial_at=None;self.quiet_bytes=0;self.early_commits=0
        self.clause_cursor=0;self.clause_count=0
        self.incremental=incremental.Clauses(owner,ident,key,info) if incremental.enabled() else None

    def check(self):
        if self.closed.is_set():raise self.error or failure('turn_cancelled')
        if monotonic()-self.started>=budget.LEASE_MS/1000:raise failure('realtime_deadline')
        live.check_session(self.owner,self.ident,self.key)
        if self.incremental:self.incremental.raise_error()
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
            if self.incremental:self.incremental.freeze()
            try:self.queue.put_nowait(None)
            except Full:raise failure('realtime_queue_full') from None

    def close(self,error=None):
        if error is not None:self.error=error
        if error is not None and self.incremental:self.incremental.cancel()
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
                        self.partial='';self.partial_at=None
                    try:self.acks.put_nowait(text.strip())
                    except Full:raise failure('realtime_commit_unexpected') from None
                elif kind=='partial_transcript':
                    text=value.get('text')
                    if not isinstance(text,str) or len(text)>4000:raise failure('realtime_response_invalid')
                    # A candidate may trigger a bounded commit, NEVER translation.
                    # Only the subsequent provider ACK authorizes clause work.
                    with self.lock:
                        if not self.pending_ack and text.strip()!=self.partial:
                            self.partial=text.strip();self.partial_at=monotonic()
                elif kind not in ('committed_transcript_with_timestamps','edited_transcript','warning'):
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
        if text:
            self.pieces.append(text)
            if len(' '.join(self.pieces))>4000:raise failure('realtime_text_limit')
            if self.incremental and not self.final:
                # An incomplete ACK is combined with following committed text
                # before its FIRST translation, never replayed as a paid prefix.
                candidate=' '.join(self.pieces[self.clause_cursor:])
                previous=' '.join(self.pieces[:self.clause_cursor])[-400:]
                if self.incremental.offer(self.clause_count,candidate,previous):
                    self.clause_cursor=len(self.pieces);self.clause_count+=1
        self.since_commit=0;self.quiet_bytes=0

    def observe_audio(self,raw):
        # Same .015 RMS threshold as existing capture, 200 ms PCM windows. This
        # only finds internal boundaries; silence endpoint/min speech stay intact.
        for at in range(0,len(raw),6400):
            block=raw[at:at+6400]
            square=sum(v[0]*v[0] for v in struct.iter_unpack('<h',block))
            if square/(len(block)//2)>=(.015*32768)**2:self.quiet_bytes=0
            else:self.quiet_bytes+=len(block)

    def early_boundary(self):
        if not self.incremental or self.final or self.early_commits>=2 or self.since_commit<3*32000:return False
        with self.lock:
            sentence=self.partial.endswith(('.', '!', '?', '。', '！', '？')) and self.partial_at is not None and monotonic()-self.partial_at>=.4
        # At most two extra commits on the SAME STT lease. No extra connection,
        # input replay or VAD/provider/model switch. An ACK may still be incomplete
        # and is retained whole rather than translated as a cut-off clause.
        return sentence or self.quiet_bytes>=int(.6*32000)

    def run(self):
        success=False;connection=ExitStack();timings={};input_error=None
        try:
            # Keep both fresh credit reads on one relay-owned HTTPS connection.
            # Setup belongs inside the same failure/ledger/slot cleanup as STT.
            connection.enter_context(transport.turn_connection())
            self.arm_deadline()
            Thread(target=self.watch,name='kilas-realtime-fence',daemon=True).start()
            self.check()
            with live._timed(timings,'credit_stt_ms'):stt.require_subscription_credit()
            self.check()
            budget.dispatch(self.capability)  # Unknown handshake cost is durable.
            with live._timed(timings,'input_connect_ms'):self.ws=connect()
            self.check();self.ws.settimeout(8)
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
                    if self.incremental:self.observe_audio(piece)
                    if self.since_commit==COMMIT_BYTES:self.send(b'',True);self.acknowledge()
                if self.early_boundary():
                    self.early_commits+=1;self.send(b'',True);self.acknowledge()
            self.check();text=' '.join(self.pieces).strip()
            if not text:raise failure('no_speech')
            if not budget.finish(self.capability,True):raise failure('realtime_budget_unsettled')
            success=True;self.close()
            self.deadline.cancel()  # Output has its separate180s processing window.
            # No microphone/paid STT fallback; the existing complete translation
            # and one billed whole-utterance output consume this stable whole text.
            finalized=monotonic()
            timings['input_finalize_ms']=(finalized-self.final_at)*1000
            timings['input_early_commits']=self.early_commits
            log_input(True,None,self.started,timings)
            live.process(self.owner,self.ident,self.key,None,self.info,whole_output=True,committed_text=text,
                started=self.final_at,incremental=self.incremental,timings={'realtime_input_ms':self.sent/32,
                    'realtime_transport_ms':(finalized-self.started)*1000,
                    'realtime_finalize_ms':(finalized-self.final_at)*1000,
                    'realtime_commits':len(self.pieces)})
        except Exception as error:
            input_error=error
            self.close(error)
            if not success:budget.finish(self.capability,False)
            sessions.finish(self.owner,self.ident,self.key,False,code=getattr(error,'code','realtime_failed'))
        finally:
            if not success:log_input(False,input_error,self.started,timings)
            self.close();self.finished=True
            if self.deadline:self.deadline.cancel()
            if self.incremental:self.incremental.cancel()
            with _lock:_relays.pop((self.owner,self.ident,self.key),None)
            try:_slots.release();db._discard_cached_connection()
            finally:connection.close()


def start(owner,ident,key):
    require_ready(owner)
    if not _slots.acquire(blocking=False):raise failure('service_busy')
    capability=None;claimed=False
    try:
        info=sessions.claim(owner,ident,key);claimed=True
        if info['voice_alias']=='gemini-live-native' or info['language_a']=='auto':raise failure('realtime_unverified')
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
