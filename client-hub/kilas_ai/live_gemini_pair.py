"""Two opposing native translation streams under one owned, funded turn.

Each socket has one fixed target and disables target-language echo. Identical
input goes to both; no classifier, extra provider, text prompt or voice change.
Output is held until both sockets close, then grouped into contiguous streams
in order of first accepted PCM. This prevents alternating word chunks; it does
not establish semantic order when a single utterance mixes both languages.
"""
import base64
import json
import re
from queue import Empty
from threading import Thread, Timer
from time import monotonic

import db
from . import audio_store, live_gemini as native, live_gemini_budget as budget
from . import live_translator as live, live_translator_store as sessions
from . import live_translator_output as temporary

VOICE = 'gemini-live-two-way'  # Server session marker; acoustic voice is unchanged.
INPUT_MODE = 'gemini-live-two-way-v1'
OUTPUT_ORDER = 'stream_runs_after_close'
failure = native.failure
require_ready = native.require_ready


def ready(owner):
    """Landing/admission preview only; active checks use require_ready above."""
    try:
        return native.ready(owner) and bool(budget.status(owner, streams=2).get('available'))
    except Exception:
        return False


class Stream(native.Relay):
    """Protocol parser only; never owns admission, dispatch or settlement."""
    def __init__(self, pair, target):
        super().__init__(pair.owner, pair.ident, pair.key, pair.info, None, None,
                         lease_started=pair.started)
        self.pair, self.target = pair, target
        self.cancelled = pair.cancelled
        self.stopped = False

    @property
    def error(self):
        # receive() rechecks cancellation inside its parser lock. A parent
        # failure racing that check must not become a false explicit End.
        parent = self.__dict__.get('pair')
        return parent.error if parent is not None else self.__dict__.get('_error')

    @error.setter
    def error(self, value):
        self._error = value

    def check(self):
        self.pair.check()

    def receive(self, raw):
        value = native.message(raw)
        content = value.get('serverContent', {})
        if isinstance(content, dict):
            transcript = content.get('outputTranscription')
            if isinstance(transcript, dict) and transcript.get('languageCode') is not None:
                if live.canonical_language(transcript['languageCode']) != self.target:
                    raise failure('gemini_response_invalid')
        super().receive(raw)

    def accept_pcm(self, pcm):
        # The child lock is held by receive. Aggregate admission happens before
        # either child stores PCM, so two simultaneous packets cannot exceed90s.
        pair = self.pair
        with pair.lock:
            if pair.cancelled.is_set():
                raise pair.error or failure('turn_cancelled', 409)
            pair.received_packets += 1
            if pair.output_bytes+len(pcm) > native.OUTPUT_BYTES:
                pair.rejected_output_bytes += len(pcm)
                self.received_packets += 1
                self.rejected_output_bytes += len(pcm)
                raise failure('gemini_output_limit', 429)
            super().accept_pcm(pcm)
            pair.output_bytes += len(pcm)
            pair.last_output_at = self.last_output_at
            if pair.first_output_at is None:
                pair.first_output_at = self.first_output_at
            if self.target not in pair.output_order:
                pair.output_order.append(self.target)

    def state(self):
        with self.lock:
            return {'target_language':self.target, 'generation':self.generation,
                    'completion_kind':self.completion_kind, 'tail_confirmed':self.tail_confirmed,
                    'output_closed':self.stopped,
                    'source_text':self.source_text, 'translated_text':self.target_text}


class Pair(native.Relay):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.discarded = False
        self.output_order = []
        self.streams = {target:Stream(self, target)
                        for target in (self.info['language_a'], self.info['language_b'])}
        self.workers = []

    def check(self):
        if self.cancelled.is_set():
            raise self.error or failure('turn_cancelled', 409)
        if monotonic()-self.started >= budget.LEASE_MS/1000:
            raise failure('gemini_deadline')
        require_ready(self.owner)
        info = sessions.check(self.owner, self.ident, self.key)
        if (info['voice_alias'] != VOICE or any(info[name] != self.info[name]
                                               for name in ('language_a', 'language_b'))):
            raise failure('gemini_session_changed', 409)
        if self.cancelled.is_set():
            raise self.error or failure('turn_cancelled', 409)

    def close_socket(self):
        for stream in self.streams.values():
            stream.close_socket()

    def stop(self, error=None):
        discard = getattr(error, 'code', None) in ('turn_cancelled', 'session_ended')
        if discard:
            with self.error_lock:
                self.discarded = True
        super().stop(error)
        if discard:
            for stream in self.streams.values():
                with stream.lock:
                    stream.frames.clear()
                    stream.source_text = stream.target_text = ''

    def send(self):
        try:
            while not self.cancelled.is_set():
                self.check()
                try:
                    raw = self.queue.get(timeout=.1)
                except Empty:
                    continue
                if raw is None:
                    for stream in self.streams.values():
                        self.check()
                        with stream.lock:
                            stream.ws.send(json.dumps({'realtimeInput':{'audioStreamEnd':True}}))
                            stream.end_at = monotonic()
                            stream.end_sent.set()
                    with self.lock:
                        self.end_at = monotonic()
                        self.end_sent.set()
                    return
                with self.lock:
                    self.queued -= len(raw)
                for offset in range(0, len(raw), 3200):
                    packet = raw[offset:offset+3200]
                    value = json.dumps({'realtimeInput':{'audio':{
                        'mimeType':'audio/pcm;rate=16000',
                        'data':base64.b64encode(packet).decode('ascii')}}})
                    for stream in self.streams.values():
                        self.check()
                        stream.ws.send(value)
                        with stream.lock:
                            stream.sent_bytes += len(packet)
                            stream.sent_packets += 1
                    with self.lock:
                        self.sent_bytes += len(packet)  # One accepted capture, delivered to both.
                        self.sent_packets += 1
        except Exception as error:
            self.stop(error if isinstance(error, audio_store.AudioError) else failure())
        finally:
            db._discard_cached_connection()

    def receive_stream(self, stream):
        import websocket
        try:
            while not self.cancelled.is_set() and not stream.completed.is_set():
                self.check()
                if stream.finish_drain():
                    break
                try:
                    raw = stream.ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                except Exception:
                    if stream.completed.is_set() and not self.cancelled.is_set():
                        break
                    raise failure('gemini_tail_unconfirmed' if stream.end_sent.is_set() else 'gemini_transport') from None
                if raw in ('', b''):
                    if stream.completed.is_set() and not self.cancelled.is_set():
                        break
                    raise failure('gemini_tail_unconfirmed' if stream.end_sent.is_set() else 'gemini_transport')
                stream.receive(raw)
        except Exception as error:
            self.stop(error if isinstance(error, audio_store.AudioError) else failure())
        finally:
            stream.close_socket()
            with stream.lock:
                stream.stopped = True
            db._discard_cached_connection()

    def watch(self):
        try:
            while not self.cancelled.wait(.25) and not self.completed.is_set():
                self.check()
                for stream in self.streams.values():
                    stream.finish_drain()
                if not self.input_closed and monotonic()-self.last_input > 5:
                    raise failure('gemini_input_idle')
        except Exception as error:
            if not self.completed.is_set():
                self.stop(error if isinstance(error, audio_store.AudioError) else failure())
        finally:
            db._discard_cached_connection()

    def snapshot(self, after):
        result = super().snapshot(after)
        # Child parsers never acquire the pair lock while state() holds it.
        # Keep the lock order child->pair everywhere that needs both.
        states = {target:stream.state() for target, stream in self.streams.items()}
        result.update(input_mode=INPUT_MODE, translation_mode='two_way', output_order=OUTPUT_ORDER,
                      target_language=None, target_languages=list(self.streams), streams=states)
        if result['output_closed'] and result['status'] == 'PROCESSING':
            # A failed durable settlement must keep admission fenced, while
            # still letting this owned client drain accepted local PCM once.
            result.update(status='FAILED', code='gemini_settlement_failed')
        return result

    def publish(self, frames):
        with self.error_lock, self.lock:
            if not self.discarded:
                self.frames = frames
            self.finished = True

    def diagnostics(self):
        result = super().diagnostics()
        result['streams'] = {target:stream.diagnostics() for target, stream in self.streams.items()}
        result['output_order'] = list(self.output_order)
        return result

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
            budget.dispatch(self.capability)  # One durable pair marker before either socket.
            self.check()
            for stream in self.streams.values():
                self.check()
                stream.ws = native.connect()
                self.check()
                stream.ws.send(json.dumps(native.setup(stream.target)))
                value = native.message(stream.ws.recv())
                if (not isinstance(value.get('setupComplete'), dict)
                        or any(name in value for name in ('error', 'toolCall', 'goAway'))):
                    raise failure('gemini_setup_invalid')
                stream.ws.settimeout(.5)
            for target, stream in self.streams.items():
                worker = Thread(target=self.receive_stream, args=(stream,),
                                name='kilas-gemini-pair-'+target, daemon=True)
                self.workers.append(worker)
                worker.start()
            for action in (self.send, self.watch):
                worker = Thread(target=action, name='kilas-gemini-pair-fence', daemon=True)
                self.workers.append(worker)
                worker.start()
            while not self.cancelled.wait(.05):
                self.check()
                if all(stream.stopped and stream.completed.is_set() for stream in self.streams.values()):
                    self.tail_confirmed = all(stream.tail_confirmed for stream in self.streams.values())
                    self.completion_kind = 'turn_complete' if self.tail_confirmed else 'bounded_drain'
                    self.completed.set()
                    success = True
                    break
        except Exception as error:
            self.stop(error if isinstance(error, audio_store.AudioError) else failure())
        finally:
            self.stop()
            timer.cancel()
            for worker in self.workers:
                if worker.ident is not None:
                    worker.join(timeout=1)
            for stream in self.streams.values():
                with stream.lock:
                    stream.stopped = True  # Includes an unopened/failed setup leg.
            with self.error_lock:
                success = success and self.error is None
            try:
                # Every valid accepted sample is settled once, including a
                # failed pair's buffered output. No retry, replay or refund.
                if self.output_bytes or success:
                    if not audio_store.finish(self.owner, self.job, None,
                            (self.output_bytes*1000+47999)//48000, provider_id='gemini-live-native-v1'):
                        raise failure('gemini_settlement_failed')
                else:
                    audio_store.fail(self.owner, self.job, getattr(self.error, 'code', 'gemini_transport'))
                budget.finish(self.capability, success)
                sessions.finish(self.owner, self.ident, self.key, success, self.job,
                                None if success else getattr(self.error, 'code', 'gemini_transport'))
            except Exception:
                with self.error_lock:
                    self.error = failure('gemini_settlement_failed')
                    if self.first_error is None:
                        self.first_error = self.error
                try:
                    sessions.finish(self.owner, self.ident, self.key, False, self.job, 'gemini_settlement_failed')
                except Exception:
                    pass  # Keep capacity charged; an unavailable ledger cannot grant renewal.
            finally:
                # Publish only complete contiguous stream runs, after both
                # sockets stop and settlement ends. Never alternate word PCM.
                frames = []
                for target in self.output_order + [key for key in self.streams if key not in self.output_order]:
                    stream = self.streams[target]
                    with stream.lock:
                        frames.extend({'stream_id':target, 'target_language':target, **frame}
                                      for frame in stream.frames)
                self.publish(frames)
                native._slots.release()
                native._slots.release()
                db._discard_cached_connection()
                try:
                    print('KILAS_GEMINI_PAIR '+json.dumps({
                        'outcome':'completed' if success and self.error is None else 'failed',
                        'input_ms':round(self.accepted/32, 1), 'output_ms':round(self.output_bytes/48, 1),
                        'completion_kind':self.completion_kind, 'tail_confirmed':self.tail_confirmed,
                        'code':getattr(self.error, 'code', None),
                        'first_code':getattr(self.first_error, 'code', None)}), flush=True)
                except OSError:
                    pass


def start(owner, ident, key):
    require_ready(owner)
    if not isinstance(key, str) or not re.fullmatch(r'live-[a-f0-9]{32}', key):
        raise failure('gemini_input_invalid', 400)
    acquired = 0
    for _ in range(2):
        if not native._slots.acquire(blocking=False):
            for _ in range(acquired):
                native._slots.release()
            raise failure('service_busy', 429)
        acquired += 1
    capability = job = None
    claimed = False
    try:
        info = sessions.claim(owner, ident, key)
        claimed = True
        if info['voice_alias'] != VOICE:
            raise failure('gemini_session_changed', 409)
        audio_store.require_balance(owner)
        live.require_audio_allowance(owner, 90)
        lease_started = monotonic()
        capability = budget.claim(owner, ident, key, streams=2)
        job, new = audio_store.create(owner, key+'-audio', 'voiceover', 'Live Translator',
                                     info['language_a'], info['language_b'], VOICE, 'Gemini Live',
                                     '', 0, None, 90, 90, live_session=(ident, key))
        if not new or not audio_store.start(owner, job):
            raise failure('duplicate_turn', 409)
        relay = Pair(owner, ident, key, info, capability, job, lease_started=lease_started)
        with native._lock:
            now = monotonic()
            for address in list(native._items):
                previous = native._items[address]
                if previous.finished and (previous.expires < now or address[:2] == (owner, ident)):
                    del native._items[address]
            if len(native._items) >= 4:
                raise failure('session_storage_busy')
            native._items[(owner, ident, key)] = relay
            if not native._sweeper_started:
                Thread(target=native.sweep, name='kilas-gemini-expiry', daemon=True).start()
                native._sweeper_started = True
        Thread(target=relay.run, name='kilas-gemini-pair', daemon=True).start()
        return relay
    except Exception as error:
        code = getattr(error, 'code', 'gemini_admission_failed')
        cleanups = []
        if capability:
            cleanups.append(lambda:budget.finish(capability, False))
        if job:
            cleanups.append(lambda:audio_store.fail(owner, job, 'gemini_admission_failed'))
        if claimed:
            cleanups.append(lambda:sessions.finish(owner, ident, key, False, job, code))
            cleanups.append(lambda:temporary.discard(owner, ident, key))
        failed = False
        try:
            for cleanup in cleanups:
                try:
                    cleanup()
                except Exception:
                    failed = True
        finally:
            for _ in range(acquired):
                native._slots.release()
        if failed:
            raise failure('gemini_settlement_failed') from None
        if isinstance(error, budget.ledger.BudgetError):
            raise failure(error.code, error.status) from None
        raise


def owned(owner, ident, key):
    relay = native.owned(owner, ident, key)
    if not isinstance(relay, Pair):
        raise failure('gemini_session_changed', 409)
    return relay


def cancel(owner, ident, key=None):
    native.cancel(owner, ident, key)
