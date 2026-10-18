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
# Internal diagnostic codes only. Never attach provider values or payloads.
VALIDATION_REASONS = frozenset((
    'message_type', 'message_size', 'message_json', 'message_object',
    'provider_error', 'provider_go_away', 'unexpected_tool_call',
    'content_shape', 'transcript_shape', 'input_language',
    'output_language', 'text_limit', 'turn_shape', 'part_shape', 'audio_shape',
    'audio_mime', 'audio_base64', 'audio_length', 'frame_limit', 'closed_stream',
    'unknown',
))
# Continuous Live Translate does not promise a turn EOF. Google's example
# uses four seconds, but that is not a semantic completion signal:
# https://github.com/google-gemini/gemini-live-api-examples/blob/3bcae1162d1bc6955672153310e4f84eba6621ff/command-line/python/translate.py
# Keep a short quiet period after a late PCM packet, within a fixed six-second
# maximum and the original paid lease. Never turn that bound into proof of EOF.
TAIL_GRACE_SECONDS = 4
TAIL_MAX_SECONDS = 6
TAIL_QUIET_SECONDS = 1.5
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


def validation_reason(error):
    """Return only a fixed internal code, never supplier-controlled metadata."""
    reason = getattr(error, 'validation_reason', None)
    return reason if (getattr(error, 'code', None) == 'gemini_response_invalid'
                      and type(reason) is str and reason in VALIDATION_REASONS) else None


def provider_status(error):
    status = getattr(error, 'provider_status', None)
    return status if (validation_reason(error) == 'provider_error'
                      and type(status) is int and 100 <= status <= 599) else None


def invalid_response(reason, status=None):
    error = failure('gemini_response_invalid')
    error.validation_reason = reason if type(reason) is str and reason in VALIDATION_REASONS else 'unknown'
    if error.validation_reason == 'provider_error' and type(status) is int and 100 <= status <= 599:
        error.provider_status = status
    return error


def ready(owner):
    return budget.ready(owner) and bool(os.environ.get('GEMINI_API_KEY', '').strip()) and temporary.single_worker()


def require_ready(owner):
    if not ready(owner):
        raise failure('gemini_unavailable', 404)


def preview_owner(owner):
    """Read-only landing access; never grants a session or paid dispatch."""
    if str(owner) != os.environ.get('KILAS_LIVE_GEMINI_QA_OWNER_ID'):
        return False
    expected = os.environ.get('KILAS_LIVE_GEMINI_QA_OWNER_EMAIL', '').strip().lower()
    if not expected:
        return False
    row = db.query_one('SELECT email,role FROM users WHERE id=?', (owner,))
    return bool(row and row['role'] == 'CLIENT_OWNER' and row['email'].strip().lower() == expected)


def setup(target):
    # Dedicated translation guide + Live API reference, checked 2026-10-16.
    # No user instructions, tools, text input, arbitrary model or custom voice.
    from .translator_languages import native_wire,NATIVE
    if target not in NATIVE:raise failure('invalid_language_pair',400)
    return {'setup':{'model':'models/'+MODEL,
                     'generationConfig':{'responseModalities':['AUDIO'], 'maxOutputTokens':4096,
                                         'translationConfig':{'targetLanguageCode':native_wire(target), 'echoTargetLanguage':False}},
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
    if not isinstance(raw,(str,bytes)):
        raise invalid_response('message_type')
    if len(raw)>MAX_MESSAGE:
        raise invalid_response('message_size')
    try:
        value=json.loads(raw.decode('utf-8') if isinstance(raw,bytes) else raw)
    except (ValueError,UnicodeError):
        raise invalid_response('message_json') from None
    if not isinstance(value,dict):
        raise invalid_response('message_object')
    return value


class Relay:
    def __init__(self, owner, ident, key, info, capability, job, lease_started=None):
        self.owner, self.ident, self.key, self.info = owner, ident, key, info
        self.capability, self.job = capability, job
        self.lock = Lock()
        self.error_lock = Lock()
        self.queue = Queue(maxsize=64)
        self.cancelled, self.completed, self.end_sent = Event(), Event(), Event()
        self.finished = False
        self.run_started = False
        self.error = None
        self.first_error = None
        self.validation_reason = None
        self.provider_status = None
        self.ws = None
        self.expected = self.accepted = self.queued = self.output_bytes = self.generation = 0
        self.frames = []
        self.source_text = self.target_text = ''
        self.input_closed = False
        self.last_input = monotonic()
        self.started = self.last_input if lease_started is None else lease_started
        self.end_at = None
        self.generation_complete_count = self.turn_complete_count = 0
        self.post_end_generation_complete = self.post_end_turn_complete = 0
        self.completion_kind = None
        self.tail_confirmed = False
        self.first_input_at = self.first_output_at = None
        self.sent_bytes = self.sent_packets = self.received_packets = self.rejected_output_bytes = 0
        self.interruption_count = 0
        self.last_output_at = None
        self.expires = self.started + 600

    def check(self):
        if self.cancelled.is_set():
            raise self.error or failure('turn_cancelled', 409)
        if monotonic() >= self.started+budget.LEASE_MS/1000:
            raise failure('gemini_deadline')
        require_ready(self.owner)
        info = sessions.check(self.owner, self.ident, self.key)
        if info['voice_alias'] != VOICE or info['language_b'] != self.info['language_b']:
            raise failure('gemini_session_changed', 409)
        if self.cancelled.is_set():
            raise self.error or failure('turn_cancelled', 409)

    def stop(self, error=None):
        if error is not None:
            with self.error_lock:
                # A watchdog/cancel closes recv(). That secondary close must
                # never replace the first bounded failure with "transport".
                if self.error is None and not self.finished:
                    self.error = error
                    self.first_error = error
        self.cancelled.set()
        self.close_socket()

    def close_socket(self):
        if self.ws:
            try:
                self.ws.shutdown()
            except Exception:
                pass

    def drain_deadline(self):
        with self.lock:
            return self._drain_deadline()

    def _drain_deadline(self):
        if self.end_at is None:
            return None
        quiet_after = (self.last_output_at if self.last_output_at is not None else self.end_at)+TAIL_QUIET_SECONDS
        return min(self.started+budget.LEASE_MS/1000, self.end_at+TAIL_MAX_SECONDS,
                   max(self.end_at+TAIL_GRACE_SECONDS, quiet_after))

    def finish_drain(self):
        """Close the local receive window without inventing a provider EOF."""
        with self.error_lock:
            with self.lock:
                now = monotonic()
                if (self.completed.is_set() or self.cancelled.is_set() or self.error is not None
                        or self.end_at is None or now < self._drain_deadline()
                        or now >= self.started+budget.LEASE_MS/1000):
                    return False
                self.completion_kind = 'bounded_drain'
                self.completed.set()
        # Wake a blocking recv; its resulting close is expected only while the
        # local completion is still free of cancellation or a prior failure.
        self.close_socket()
        return True

    def diagnostics(self):
        with self.lock:
            return {'end_sent':self.end_sent.is_set(),
                    'generation_complete_count':self.generation_complete_count,
                    'turn_complete_count':self.turn_complete_count,
                    'interruption_count':self.interruption_count,
                    'generation_complete_after_end':self.post_end_generation_complete,
                    'turn_complete_after_end':self.post_end_turn_complete,
                    'completion_kind':self.completion_kind,
                    'tail_confirmed':self.tail_confirmed,
                    'tail_code':'gemini_tail_unconfirmed' if self.completion_kind == 'bounded_drain' else None,
                    'input_accepted_bytes':self.accepted, 'input_sent_bytes':self.sent_bytes,
                    'input_sent_packets':self.sent_packets, 'output_accepted_bytes':self.output_bytes,
                    'output_received_packets':self.received_packets,
                    'output_rejected_bytes':self.rejected_output_bytes,
                    'last_output_after_start_ms':None if self.last_output_at is None else round((self.last_output_at-self.started)*1000,1),
                    'first_error_code':getattr(self.first_error,'code',None)}

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
                    # Publish the sent state before a fast EOS acknowledgement
                    # can acquire receive's lock. Never hold this for normal PCM.
                    with self.lock:
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
                    with self.lock:
                        self.sent_bytes += len(raw[offset:offset+3200])
                        self.sent_packets += 1
        except Exception as error:
            self.stop(error if isinstance(error, audio_store.AudioError) else failure())
        finally:
            db._discard_cached_connection()

    def watch(self):
        try:
            while not self.cancelled.wait(.25) and not self.completed.is_set():
                self.check()
                if self.finish_drain():
                    return
                if not self.input_closed and monotonic()-self.last_input > 5:
                    raise failure('gemini_input_idle')
        except Exception as error:
            if not self.completed.is_set():
                self.stop(error if isinstance(error, audio_store.AudioError) else failure())
        finally:
            db._discard_cached_connection()

    def receive(self, raw):
        self.check()
        try:
            with self.lock:
                if self.cancelled.is_set():
                    raise self.error or failure('turn_cancelled',409)
                if self.completed.is_set():
                    return
                # Completion and admission share one boundary: a packet that
                # recv returns after the bounded drain closed is ignored in full.
                value = message(raw)
                if 'error' in value:
                    envelope = value['error']
                    raise invalid_response('provider_error', envelope.get('code') if isinstance(envelope, dict) else None)
                if 'toolCall' in value:
                    raise invalid_response('unexpected_tool_call')
                if 'goAway' in value:
                    raise invalid_response('provider_go_away')
                content = value.get('serverContent', {})
                if not isinstance(content, dict):
                    raise invalid_response('content_shape')
                self.validate_content(content)
                if content.get('interrupted') is True:
                    self.interruption_count += 1
                    self.generation += 1
                    self.frames.append({'type':'reset', 'generation':self.generation})
                for field, target in (('inputTranscription','source_text'), ('outputTranscription','target_text')):
                    transcript = content.get(field)
                    if transcript is not None:
                        if not isinstance(transcript, dict) or not isinstance(transcript.get('text',''), str):
                            raise invalid_response('transcript_shape')
                        reported = transcript.get('languageCode')
                        if reported is not None and live.canonical_language(reported) not in (self.info['language_a'],self.info['language_b']):
                            raise invalid_response('input_language' if field == 'inputTranscription' else 'output_language')
                        text = getattr(self, target)+transcript.get('text','')
                        if len(text) > MAX_TEXT:
                            raise invalid_response('text_limit')
                        setattr(self, target, text)
                turn = content.get('modelTurn', {})
                if not isinstance(turn, dict) or not isinstance(turn.get('parts',[]), list):
                    raise invalid_response('turn_shape')
                for part in turn.get('parts', []):
                    if not isinstance(part, dict):
                        raise invalid_response('part_shape')
                    audio = part.get('inlineData')
                    if audio is None:
                        continue
                    if not isinstance(audio, dict) or not isinstance(audio.get('data'), str):
                        raise invalid_response('audio_shape')
                    if audio.get('mimeType') != 'audio/pcm;rate=24000':
                        raise invalid_response('audio_mime')
                    try:
                        pcm = base64.b64decode(audio['data'], validate=True)
                    except (ValueError, binascii.Error):
                        raise invalid_response('audio_base64') from None
                    if not pcm or len(pcm)%2:
                        raise invalid_response('audio_length')
                    self.accept_pcm(pcm)
                if len(self.frames) > 2000:
                    raise invalid_response('frame_limit')
                if content.get('generationComplete') is True:
                    self.generation_complete_count += 1
                    self.post_end_generation_complete += int(self.end_sent.is_set())
                if content.get('turnComplete') is True:
                    self.turn_complete_count += 1
                    self.post_end_turn_complete += int(self.end_sent.is_set())
                    # Preserve a real terminal marker separately from the
                    # bounded local stop used by this continuous interpreter.
                    if (self.end_sent.is_set() and content.get('interrupted') is not True
                            and content.get('interactionStatus') != 'IN_PROGRESS'):
                        self.completion_kind = 'turn_complete'
                        self.tail_confirmed = True
                        self.completed.set()
        except audio_store.AudioError as error:
            self.note_validation(error)
            raise
        except (ValueError, TypeError, KeyError, binascii.Error):
            error = invalid_response('unknown')
            self.note_validation(error)
            raise error from None

    def validate_content(self, content):
        """Additional stream constraints, inside the active parser lock."""

    def note_validation(self, error):
        reason = validation_reason(error)
        if reason is not None:
            with self.lock:
                if self.validation_reason is None:
                    self.validation_reason = reason
                    self.provider_status = provider_status(error)

    def accept_pcm(self, pcm):
        """Accept validated PCM while receive holds the relay lock."""
        self.received_packets += 1
        if self.output_bytes+len(pcm) > OUTPUT_BYTES:
            self.rejected_output_bytes += len(pcm)
            raise failure('gemini_output_limit', 429)
        self.output_bytes += len(pcm)
        self.last_output_at = monotonic()
        if self.first_output_at is None:
            self.first_output_at = self.last_output_at
        for offset in range(0, len(pcm), 9600):
            self.frames.append({'type':'audio', 'generation':self.generation,
                                'pcm':base64.b64encode(pcm[offset:offset+9600]).decode('ascii')})

    def snapshot(self, after):
        # Owner/session/expiry fences apply to every response, including terminal.
        if not budget.ready(self.owner):
            raise failure('gemini_unavailable',404)
        with self.lock:
            # Read the durable status while holding the same publication lock
            # as finished. An old PROCESSING read cannot pair with closed PCM.
            state = sessions.result(self.owner, self.ident, self.key)
            if state['status'] == 'CANCELLED':
                raise failure('turn_cancelled', 409)
            if type(after) is not int or not 0 <= after <= len(self.frames):
                raise failure('gemini_cursor_invalid', 400)
            frames = [{'index':i, **frame} for i, frame in enumerate(self.frames[after:after+12], after)]
            return {'status':state['status'], 'frames':frames, 'next_index':after+len(frames),
                    'source_text':self.source_text, 'translated_text':self.target_text,
                    'target_language':self.info['language_b'], 'generation':self.generation,
                    'input_closed':self.input_closed, 'output_closed':self.finished,
                    'total_frames':len(self.frames) if self.finished else None,
                    'completion_kind':self.completion_kind, 'tail_confirmed':self.tail_confirmed,
                    'tail_code':'gemini_tail_unconfirmed' if self.completion_kind == 'bounded_drain' else None,
                    'code':getattr(self.error,'code',None)}

    def run(self):
        with self.lock:
            if self.run_started:
                return
            self.run_started = True
        timer = Timer(max(0, self.started+budget.LEASE_MS/1000-monotonic()),
                      self.stop, args=(failure('gemini_deadline'),))
        timer.daemon = True
        success = False
        try:
            timer.start()
            self.check()
            budget.dispatch(self.capability)  # Durable before possibly billable handshake.
            self.check()  # End may commit while the durable dispatch waits.
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
                if self.finish_drain():
                    break
                try:
                    raw = self.ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                except Exception:
                    if self.completed.is_set() and not self.cancelled.is_set():
                        break
                    raise failure('gemini_tail_unconfirmed' if self.end_sent.is_set() else 'gemini_transport') from None
                if raw in ('',b''):
                    if self.completed.is_set() and not self.cancelled.is_set():
                        break
                    raise failure('gemini_tail_unconfirmed' if self.end_sent.is_set() else 'gemini_transport')
                self.receive(raw)
            self.check()
            success = True
        except Exception as error:
            self.stop(error if isinstance(error, audio_store.AudioError) else failure())
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
                with self.error_lock:
                    self.error = failure('gemini_settlement_failed')
                    if self.first_error is None:
                        self.first_error = self.error
                sessions.finish(self.owner, self.ident, self.key, False, self.job, 'gemini_settlement_failed')
            finally:
                with self.error_lock, self.lock:
                    self.finished = True
                _slots.release()
                db._discard_cached_connection()
                values = f'input_ms={self.accepted/32:.1f} output_ms={self.output_bytes/48:.1f} elapsed_ms={(monotonic()-self.started)*1000:.1f}'
                values += f' code={getattr(self.error,"code",None) or "none"} first_code={getattr(self.first_error,"code",None) or "none"}'
                values += f' validation_reason={validation_reason(self.first_error) or "none"}'
                values += f' provider_status={provider_status(self.first_error) or "none"}'
                values += f' generation_complete={self.generation_complete_count} turn_complete={self.turn_complete_count}'
                values += f' interruptions={self.interruption_count}'
                if self.end_at is not None:
                    values += f' post_eos_ms={max(0,monotonic()-self.end_at)*1000:.1f}'
                    if self.last_output_at is not None:
                        values += f' last_output_after_eos_ms={(self.last_output_at-self.end_at)*1000:.1f}'
                values += f' completion_kind={self.completion_kind or "none"} tail_confirmed={str(self.tail_confirmed).lower()}'
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
        # Include admission/DB delay in the hard lease; never let the shared
        # ledger's stale-operation fence expire while this socket is live.
        lease_started = monotonic()
        capability = budget.claim(owner, ident, key)
        job, new = audio_store.create(owner, key+'-audio', 'voiceover', 'Live Translator',
                                     info['language_a'], info['language_b'], VOICE, 'Gemini Live',
                                     '', 0, None, 90, 90, live_session=(ident,key))
        if not new or not audio_store.start(owner, job):
            raise failure('duplicate_turn', 409)
        relay = Relay(owner, ident, key, info, capability, job, lease_started=lease_started)
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
        error_code = getattr(error,'code','gemini_admission_failed')
        cleanups = []
        if capability:
            cleanups.append(lambda:budget.finish(capability, False))
        if job:
            cleanups.append(lambda:audio_store.fail(owner, job, 'gemini_admission_failed'))
        if claimed:
            cleanups.append(lambda:sessions.finish(owner, ident, key, False, job, error_code))
            cleanups.append(lambda:temporary.discard(owner, ident, key))
        cleanup_failed = False
        try:
            for cleanup in cleanups:
                try:
                    cleanup()
                except Exception:
                    cleanup_failed = True
        finally:
            _slots.release()
        if cleanup_failed:
            raise failure('gemini_settlement_failed') from None
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
