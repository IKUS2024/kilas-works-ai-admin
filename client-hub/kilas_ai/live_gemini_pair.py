"""Two opposing native translation streams under one owned, funded turn.

Each socket has one fixed target and disables target-language echo. Identical
input goes to both; no classifier, extra provider, text prompt or voice change.
Progressive sessions publish the first PCM stream immediately and hold the
other until that receiver closes. Legacy sessions retain whole-turn output
holding. Both preserve contiguous stream runs, without claiming semantic order
when a single utterance mixes both languages.
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

LEGACY_VOICE = 'gemini-live-two-way'
LEGACY_INPUT_MODE = 'gemini-live-two-way-v1'
LEGACY_OUTPUT_ORDER = 'stream_runs_after_close'
VOICE = 'gemini-live-two-way-progressive'  # Server marker; acoustic voice is unchanged.
INPUT_MODE = 'gemini-live-two-way-v2'
OUTPUT_ORDER = 'progressive_stream_runs'
VOICES = (LEGACY_VOICE, VOICE)
failure = native.failure
require_ready = native.require_ready


def protocol(info):
    """Select wire behavior only from the admitted server session marker."""
    if info.get('voice_alias') not in VOICES:
        raise failure('gemini_session_changed', 409)
    progressive = info['voice_alias'] == VOICE
    return {'input_mode':INPUT_MODE if progressive else LEGACY_INPUT_MODE,
            'translation_mode':'two_way',
            'output_order':OUTPUT_ORDER if progressive else LEGACY_OUTPUT_ORDER,
            'streams':[info['language_a'], info['language_b']]}


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
        self.published = 0

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
        try:
            super().receive(raw)
        finally:
            self.pair.publish_stream(self)

    def validate_content(self, content):
        # The base parser holds the child lock and has already fenced completion.
        transcript = content.get('outputTranscription')
        if isinstance(transcript, dict) and transcript.get('languageCode') is not None:
            if live.canonical_language(transcript['languageCode']) != self.target:
                raise native.invalid_response('output_language')

    def accept_pcm(self, pcm):
        # The child lock is held by receive. Aggregate admission happens before
        # either child stores PCM, so two simultaneous packets cannot exceed90s.
        pair = self.pair
        with pair.lock:
            if pair.cancelled.is_set():
                raise pair.error or failure('turn_cancelled', 409)
            if self.stopped:
                raise native.invalid_response('closed_stream')
            pair.received_packets += 1
            if pair.output_bytes+len(pcm) > native.OUTPUT_BYTES:
                pair.rejected_output_bytes += len(pcm)
                self.received_packets += 1
                self.rejected_output_bytes += len(pcm)
                raise failure('gemini_output_limit', 429)
            super().accept_pcm(pcm)
            pair.output_bytes += len(pcm)
            if not any(pcm):
                pair.silent_output_bytes += len(pcm)
                return
            pair.last_output_at = self.last_output_at
            if pair.first_output_at is None:
                pair.first_output_at = self.first_output_at
            if not pair.progressive and self.target not in pair.output_order:
                pair.output_order.append(self.target)
            pair._publish_stream_locked(self)

    def state(self):
        with self.lock:
            return {'target_language':self.target, 'generation':self.generation,
                    'completion_kind':self.completion_kind, 'tail_confirmed':self.tail_confirmed,
                    'output_closed':self.stopped,
                    'source_text':self.source_text, 'translated_text':self.target_text}


class Pair(native.Relay):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.progressive = self.info['voice_alias'] == VOICE
        self.discarded = False
        self.first_publication_at = None
        self.output_order = []
        self.streams = {target:Stream(self, target)
                        for target in (self.info['language_a'], self.info['language_b'])}
        self.workers = []

    def check(self):
        if self.cancelled.is_set():
            raise self.error or failure('turn_cancelled', 409)
        if monotonic() >= self.started+budget.LEASE_MS/1000:
            raise failure('gemini_deadline')
        require_ready(self.owner)
        info = sessions.check(self.owner, self.ident, self.key)
        if (info['voice_alias'] not in VOICES or info['voice_alias'] != self.info['voice_alias']
                or any(info[name] != self.info[name]
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
            with self.lock:
                self.frames.clear()

    def _publish_stream_locked(self, stream):
        """Append a permitted stream delta while child and pair locks are held."""
        if not self.progressive or self.discarded:
            return
        # A suppressed target can send low nonzero comfort noise as well as
        # zero padding. Translation captions distinguish a speaking stream
        # without throwing away quiet speech or trusting noise amplitude.
        # Hold early PCM until its caption arrives; all raw bytes stay metered.
        if not stream.target_text.strip():
            return
        if stream.frames and stream.target not in self.output_order:
            self.output_order.append(stream.target)
        primary = self.output_order[0] if self.output_order else None
        if primary is None:
            if not all(item.stopped for item in self.streams.values()):
                return  # Reset-only traffic cannot select a primary language.
        elif stream.target != primary and not self.streams[primary].stopped:
            return
        pending = stream.frames[stream.published:]
        if pending and self.first_publication_at is None:
            self.first_publication_at = monotonic()
        self.frames.extend({'stream_id':stream.target, 'target_language':stream.target, **frame}
                           for frame in pending)
        stream.published = len(stream.frames)

    def publish_stream(self, stream):
        with stream.lock, self.lock:
            self._publish_stream_locked(stream)

    def stream_stopped(self, stream):
        # Flush the final primary delta BEFORE stopped permits secondary output.
        # Every operation that needs both locks uses child->pair consistently.
        with stream.lock, self.lock:
            self._publish_stream_locked(stream)
            stream.stopped = True
        order = self.output_order + [target for target in self.streams if target not in self.output_order]
        for target in order:
            self.publish_stream(self.streams[target])

    def send(self):
        try:
            while not self.cancelled.is_set():
                self.check()
                try:
                    raw = self.queue.get(timeout=.1)
                except Empty:
                    continue
                if raw is None:
                    self.pad_input_end()
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
                    self.send_packet(raw[offset:offset+3200])
        except Exception as error:
            self.stop(error if isinstance(error, audio_store.AudioError) else failure())
        finally:
            db._discard_cached_connection()

    def send_packet(self, packet):
        value=json.dumps({'realtimeInput':{'audio':{
            'mimeType':'audio/pcm;rate=16000', 'data':base64.b64encode(packet).decode('ascii')}}})
        for stream in self.streams.values():
            self.check()
            stream.ws.send(value)
            with stream.lock:
                stream.sent_bytes += len(packet)
                stream.sent_packets += 1
        with self.lock:
            self.sent_bytes += len(packet)
            self.sent_packets += 1

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
            self.stream_stopped(stream)
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
        result.update(protocol(self.info))
        result.update(target_language=None, target_languages=list(self.streams), streams=states)
        if result['output_closed'] and result['status'] == 'PROCESSING':
            # A failed durable settlement must keep admission fenced, while
            # still letting this owned client drain accepted local PCM once.
            result.update(status='FAILED', code='gemini_settlement_failed')
        return result

    def publish(self, frames):
        with self.error_lock, self.lock:
            if not self.discarded:
                # Existing cursor entries stay immutable. Progressive output is
                # already the same contiguous prefix of the final stream runs.
                if frames and self.first_publication_at is None:
                    self.first_publication_at = monotonic()
                self.frames.extend(frames[len(self.frames):])
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
                try:
                    value = native.message(stream.ws.recv())
                except audio_store.AudioError as error:
                    stream.note_validation(error)
                    raise
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
                self.stream_stopped(stream)  # Includes an unopened/failed setup leg.
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
                from .live_gemini_usage import combine
                evidence = combine([stream.usage_evidence.verified(self.sent_bytes, stream.output_bytes, stream.tail_confirmed)
                                    for stream in self.streams.values()]) if success else None
                if evidence is None:
                    budget.finish(self.capability, success)
                else:
                    budget.finish(self.capability, success, verified_usage=evidence)
                native.finish_session(self, success)
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
                # Complete the existing contiguous cursor after settlement.
                # Legacy sessions first receive their whole turn at this point.
                frames = []
                for target in self.output_order + [key for key in self.streams if key not in self.output_order]:
                    stream = self.streams[target]
                    with stream.lock:
                        if self.progressive and not stream.target_text.strip():
                            continue
                        frames.extend({'stream_id':target, 'target_language':target, **frame}
                                      for frame in stream.frames)
                self.publish(frames)
                native._slots.release()
                native._slots.release()
                db._discard_cached_connection()
                try:
                    finished_at = monotonic()
                    print('KILAS_GEMINI_PAIR '+json.dumps({
                        'outcome':'completed' if success and self.error is None else 'failed',
                        'input_mode':protocol(self.info)['input_mode'],
                        'input_ms':round(self.accepted/32, 1), 'output_ms':round(self.output_bytes/48, 1),
                        'first_output_ms':None if self.first_output_at is None else round((self.first_output_at-self.started)*1000, 1),
                        'first_publication_ms':None if self.first_publication_at is None else round((self.first_publication_at-self.started)*1000, 1),
                        'input_end_ms':None if self.end_at is None else round((self.end_at-self.started)*1000, 1),
                        'post_eos_ms':None if self.end_at is None else round((finished_at-self.end_at)*1000, 1),
                        'streams':{target:{
                            'output_ms':round(stream.output_bytes/48, 1),
                            'first_output_ms':None if stream.first_output_at is None else round((stream.first_output_at-self.started)*1000, 1),
                            'completion_kind':stream.completion_kind,
                            'validation_reason':stream.validation_reason,
                            'provider_status':stream.provider_status}
                            for target, stream in self.streams.items()},
                        'completion_kind':self.completion_kind, 'tail_confirmed':self.tail_confirmed,
                        'code':getattr(self.error, 'code', None),
                        'first_code':getattr(self.first_error, 'code', None),
                        'validation_reason':native.validation_reason(self.first_error),
                        'provider_status':native.provider_status(self.first_error)}), flush=True)
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
        if info['voice_alias'] not in VOICES:
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
