"""Isolated owner-only Gemini Live Translate relay; default OFF, no import IO.

One fixed-target stream, not an assistant or automatic bidirectional router.
Permanent credentials stay on this server. Audio/transcripts exist only in RAM.
"""
import base64
import binascii
import json
import os
import re
from queue import Queue, Empty, Full
from threading import Event, Lock, Thread, Timer, BoundedSemaphore
from time import monotonic
import db
from . import audio_store, live_translator_store as sessions, live_translator_output as temporary
from . import live_translator as live, live_gemini_budget as budget

MODEL = budget.MODEL
VOICE = 'gemini-live-native'
URL = 'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent'
INPUT_BYTES = 60 * 32000
OUTPUT_BYTES = 90 * 48000
QUEUE_BYTES = 8 * 32000
MAX_MESSAGE = 1024 * 1024
MAX_TEXT = 4000
_lock = Lock()
_items = {}
_slots = BoundedSemaphore(2)
_sweeper_started = False


def sweep():
    while True:
        Event().wait(30)
        with _lock:
            for address in list(_items):
                relay = _items[address]
                if relay.finished and monotonic() > relay.expires:
                    del _items[address]


def failure(code='gemini_transport', status=503):
    # Never propagate supplier exceptions: they may contain headers or content.
    return audio_store.AudioError('Sesi Gemini terputus. Ucapan ini tidak diulang otomatis.', code, status)


def ready(owner):
    return budget.ready(owner) and bool(os.environ.get('GEMINI_API_KEY', '').strip()) and temporary.single_worker()


def require_ready(owner):
    if not ready(owner):
        raise failure('gemini_unavailable', 404)


def setup(target):
    # Dedicated translation guide + Live API reference, checked 2026-10-16.
    # No user instructions, tools, text input, arbitrary model or custom voice.
    return {'setup':{'model':'models/'+MODEL,
                     'generationConfig':{'responseModalities':['AUDIO'], 'maxOutputTokens':4096,
                                         'translationConfig':{'targetLanguageCode':target, 'echoTargetLanguage':False}},
                     'inputAudioTranscription':{}, 'outputAudioTranscription':{}}}


def connect():
    import websocket
    # The official Google SDK authenticates its socket through request headers.
    # No key-bearing URL, redirect, browser token or secret logging.
    return websocket.create_connection(URL, header={'x-goog-api-key':os.environ['GEMINI_API_KEY'].strip()},
                                       timeout=5, enable_multithread=True, redirect_limit=0)


def message(raw):
    # WebSocket peers may carry JSON in a text or UTF-8 binary frame. Bound
    # bytes before decoding, and never accept arbitrary binary audio here.
    if not isinstance(raw,(str,bytes)) or len(raw)>MAX_MESSAGE:
        raise failure('gemini_response_invalid')
    try:
        value=json.loads(raw.decode('utf-8') if isinstance(raw,bytes) else raw)
    except (ValueError,UnicodeError):
        raise failure('gemini_response_invalid') from None
    if not isinstance(value,dict):
        raise failure('gemini_response_invalid')
    return value


class Relay:
    def __init__(self, owner, ident, key, info, capability, job):
        self.owner, self.ident, self.key, self.info = owner, ident, key, info
        self.capability, self.job = capability, job
        self.lock = Lock()
        self.queue = Queue(maxsize=64)
        self.cancelled, self.completed, self.end_sent = Event(), Event(), Event()
        self.finished = False
        self.error = None
        self.ws = None
        self.expected = self.accepted = self.queued = self.output_bytes = self.generation = 0
        self.frames = []
        self.source_text = self.target_text = ''
        self.input_closed = False
        self.started = self.last_input = monotonic()
        self.end_at = None
        self.first_input_at = self.first_output_at = None
        self.expires = self.started + 600

    def check(self):
        if self.cancelled.is_set():
            raise self.error or failure('turn_cancelled', 409)
        if monotonic()-self.started >= budget.LEASE_MS/1000:
            raise failure('gemini_deadline')
        require_ready(self.owner)
        info = sessions.check(self.owner, self.ident, self.key)
        if info['voice_alias'] != VOICE or info['language_b'] != self.info['language_b']:
            raise failure('gemini_session_changed', 409)
        if self.cancelled.is_set():
            raise self.error or failure('turn_cancelled', 409)

    def stop(self, error=None):
        if error is not None:
            self.error = error
        self.cancelled.set()
        if self.ws:
            try:
                self.ws.shutdown()
            except Exception:
                pass

    def accept(self, index, raw):
        self.check()
        if type(index) is not int or not isinstance(raw, bytes) or not 2 <= len(raw) <= 16000 or len(raw)%2:
            raise failure('gemini_input_invalid', 400)
        with self.lock:
            if self.input_closed or index != self.expected or self.expected >= 1000 or self.accepted+len(raw) > INPUT_BYTES:
                raise failure('gemini_input_invalid', 409)
            if self.queued+len(raw) > QUEUE_BYTES:
                raise failure('gemini_backlog')
            try:
                self.queue.put_nowait(raw)
            except Full:
                raise failure('gemini_backlog') from None
            self.expected += 1
            self.accepted += len(raw)
            self.queued += len(raw)
            self.last_input = monotonic()
            if self.first_input_at is None:
                self.first_input_at = self.last_input

    def finish_input(self, count):
        self.check()
        with self.lock:
            if type(count) is not int or count != self.expected or self.input_closed or not self.accepted:
                raise failure('gemini_input_invalid', 409)
            self.input_closed = True
            try:
                self.queue.put_nowait(None)
            except Full:
                raise failure('gemini_backlog') from None

    def send(self):
        try:
            while not self.cancelled.is_set():
                self.check()
                try:
                    raw = self.queue.get(timeout=.1)
                except Empty:
                    continue
                if raw is None:
                    self.ws.send(json.dumps({'realtimeInput':{'audioStreamEnd':True}}))
                    self.end_at = monotonic()
                    self.end_sent.set()
                    return
                with self.lock:
                    self.queued -= len(raw)
                # Forward 100ms PCM16/16k frames, including silence after speech.
                for offset in range(0, len(raw), 3200):
                    self.check()
                    self.ws.send(json.dumps({'realtimeInput':{'audio':{
                        'mimeType':'audio/pcm;rate=16000',
                        'data':base64.b64encode(raw[offset:offset+3200]).decode('ascii')}}}))
        except Exception as error:
            self.stop(error if isinstance(error, audio_store.AudioError) else failure())
        finally:
            db._discard_cached_connection()

    def watch(self):
        try:
            while not self.cancelled.wait(.25) and not self.completed.is_set():
                self.check()
                if self.end_at is not None and monotonic()-self.end_at > 15:
                    raise failure('gemini_tail_timeout')
                if not self.input_closed and monotonic()-self.last_input > 5:
                    raise failure('gemini_input_idle')
        except Exception as error:
            self.stop(error if isinstance(error, audio_store.AudioError) else failure())
        finally:
            db._discard_cached_connection()

    def receive(self, raw):
        self.check()
        try:
            value = message(raw)
            if not isinstance(value, dict) or any(k in value for k in ('error','toolCall','goAway')):
                raise ValueError()
            content = value.get('serverContent', {})
            if not isinstance(content, dict):
                raise ValueError()
            with self.lock:
                if content.get('interrupted') is True:
                    self.generation += 1
                    self.frames.append({'type':'reset', 'generation':self.generation})
                for field, target in (('inputTranscription','source_text'), ('outputTranscription','target_text')):
                    transcript = content.get(field)
                    if transcript is not None:
                        if not isinstance(transcript, dict) or not isinstance(transcript.get('text',''), str):
                            raise ValueError()
                        reported = transcript.get('languageCode')
                        if reported is not None and live.canonical_language(reported) not in (self.info['language_a'],self.info['language_b']):
                            raise ValueError()
                        text = getattr(self, target)+transcript.get('text','')
                        if len(text) > MAX_TEXT:
                            raise ValueError()
                        setattr(self, target, text)
                turn = content.get('modelTurn', {})
                if not isinstance(turn, dict) or not isinstance(turn.get('parts',[]), list):
                    raise ValueError()
                for part in turn.get('parts', []):
                    if not isinstance(part, dict):
                        raise ValueError()
                    audio = part.get('inlineData')
                    if audio is None:
                        continue
                    if (not isinstance(audio, dict) or audio.get('mimeType') != 'audio/pcm;rate=24000'
                            or not isinstance(audio.get('data'), str)):
                        raise ValueError()
                    pcm = base64.b64decode(audio['data'], validate=True)
                    if not pcm or len(pcm)%2 or self.output_bytes+len(pcm) > OUTPUT_BYTES:
                        raise ValueError()
                    self.output_bytes += len(pcm)
                    if self.first_output_at is None:
                        self.first_output_at = monotonic()
                    for offset in range(0, len(pcm), 9600):
                        self.frames.append({'type':'audio', 'generation':self.generation,
                                            'pcm':base64.b64encode(pcm[offset:offset+9600]).decode('ascii')})
                if len(self.frames) > 2000:
                    raise ValueError()
                # Never infer the final tail from wall-clock silence. Missing
                # final provider marker is a visible timeout, not false success.
                if self.end_sent.is_set() and content.get('turnComplete') is True:
                    self.completed.set()
        except (ValueError, TypeError, KeyError, binascii.Error):
            raise failure('gemini_response_invalid') from None

    def snapshot(self, after):
        # Owner/session/expiry fences apply to every response, including terminal.
        if not budget.ready(self.owner):
            raise failure('gemini_unavailable',404)
        state = sessions.result(self.owner, self.ident, self.key)
        if state['status'] == 'CANCELLED':
            raise failure('turn_cancelled', 409)
        with self.lock:
            if type(after) is not int or not 0 <= after <= len(self.frames):
                raise failure('gemini_cursor_invalid', 400)
            frames = [{'index':i, **frame} for i, frame in enumerate(self.frames[after:after+12], after)]
            return {'status':state['status'], 'frames':frames, 'next_index':after+len(frames),
                    'source_text':self.source_text, 'translated_text':self.target_text,
                    'target_language':self.info['language_b'], 'generation':self.generation,
                    'input_closed':self.input_closed, 'output_closed':self.finished,
                    'total_frames':len(self.frames) if self.finished else None,
                    'code':getattr(self.error,'code',None)}

    def run(self):
        timer = Timer(budget.LEASE_MS/1000, self.stop, args=(failure('gemini_deadline'),))
        timer.daemon = True
        success = False
        try:
            timer.start()
            self.check()
            budget.dispatch(self.capability)  # Durable before possibly billable handshake.
            self.ws = connect()
            self.check()
            self.ws.send(json.dumps(setup(self.info['language_b'])))
            value = message(self.ws.recv())
            if (not isinstance(value.get('setupComplete'),dict)
                    or any(field in value for field in ('error','toolCall','goAway'))):
                raise failure('gemini_setup_invalid')
            Thread(target=self.send, name='kilas-gemini-input', daemon=True).start()
            Thread(target=self.watch, name='kilas-gemini-fence', daemon=True).start()
            self.ws.settimeout(.5)
            import websocket
            while not self.completed.is_set():
                self.check()
                try:
                    raw = self.ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                self.receive(raw)
            self.check()
            success = True
        except Exception as error:
            self.error = error if isinstance(error, audio_store.AudioError) else failure()
        finally:
            self.stop()
            timer.cancel()
            try:
                # Settle all valid generated samples once, even when End raced
                # publication. Unheard output is never replayed or refunded.
                if self.output_bytes or success:
                    if not audio_store.finish(self.owner, self.job, None, (self.output_bytes*1000+47999)//48000,
                                              provider_id='gemini-live-native-v1'):
                        raise failure('gemini_settlement_failed')
                else:
                    audio_store.fail(self.owner, self.job, getattr(self.error,'code','gemini_transport'))
                budget.finish(self.capability, success)
                sessions.finish(self.owner, self.ident, self.key, success, self.job,
                                None if success else getattr(self.error,'code','gemini_transport'))
            except Exception:
                self.error = failure('gemini_settlement_failed')
                sessions.finish(self.owner, self.ident, self.key, False, self.job, 'gemini_settlement_failed')
            finally:
                self.finished = True
                _slots.release()
                db._discard_cached_connection()
                values = f'input_ms={self.accepted/32:.1f} output_ms={self.output_bytes/48:.1f} elapsed_ms={(monotonic()-self.started)*1000:.1f}'
                if self.first_input_at is not None and self.first_output_at is not None:
                    values += f' first_output_ms={max(0,self.first_output_at-self.first_input_at)*1000:.1f}'
                try:
                    print(f'KILAS_GEMINI_LIVE outcome={"completed" if success and self.error is None else "failed"} {values}',flush=True)
                except OSError:
                    pass


def start(owner, ident, key):
    global _sweeper_started
    require_ready(owner)
    if not isinstance(key,str) or not re.fullmatch(r'live-[a-f0-9]{32}',key):
        raise failure('gemini_input_invalid',400)
    if not _slots.acquire(blocking=False):
        raise failure('service_busy', 429)
    capability = job = None
    claimed = False
    try:
        info = sessions.claim(owner, ident, key)
        claimed = True
        if info['voice_alias'] != VOICE:
            raise failure('gemini_session_changed', 409)
        audio_store.require_balance(owner)
        live.require_audio_allowance(owner, 90)
        capability = budget.claim(owner, ident, key)
        job, new = audio_store.create(owner, key+'-audio', 'voiceover', 'Live Translator',
                                     info['language_a'], info['language_b'], VOICE, 'Gemini Live',
                                     '', 0, None, 90, 90, live_session=(ident,key))
        if not new or not audio_store.start(owner, job):
            raise failure('duplicate_turn', 409)
        relay = Relay(owner, ident, key, info, capability, job)
        with _lock:
            now = monotonic()
            for address in list(_items):
                previous = _items[address]
                if previous.finished and (previous.expires < now or address[:2] == (owner, ident)):
                    del _items[address]
            if len(_items) >= 4:
                raise failure('session_storage_busy')
            _items[(owner,ident,key)] = relay
            if not _sweeper_started:
                Thread(target=sweep, name='kilas-gemini-expiry', daemon=True).start()
                _sweeper_started = True
        Thread(target=relay.run, name='kilas-gemini-live', daemon=True).start()
        return relay
    except Exception as error:
        if capability:
            budget.finish(capability, False)
        if job:
            audio_store.fail(owner, job, 'gemini_admission_failed')
        if claimed:
            sessions.finish(owner, ident, key, False, job, getattr(error,'code','gemini_admission_failed'))
            temporary.discard(owner, ident, key)
        _slots.release()
        if isinstance(error, budget.ledger.BudgetError):
            raise failure(error.code, error.status) from None
        raise


def owned(owner, ident, key):
    sessions.result(owner, ident, key)
    with _lock:
        relay = _items.get((owner,ident,key))
    if not relay or monotonic() > relay.expires:
        # A restart/other worker never opens another paid socket for this key.
        raise failure('gemini_output_expired', 409)
    return relay


def cancel(owner, ident, key=None):
    temporary.discard(owner, ident, key)
    with _lock:
        addresses = [a for a in _items if a[:2] == (owner,ident) and (key is None or a[2] == key)]
        for address in addresses:
            relay = _items.pop(address)
            relay.stop(failure('turn_cancelled', 409))
            with relay.lock:
                relay.frames.clear()
                relay.source_text = relay.target_text = ''
