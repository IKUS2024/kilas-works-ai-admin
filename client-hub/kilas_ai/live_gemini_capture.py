"""Private, short-lived exports for the two server-selected synthetic fixtures.

No import IO, provider connections, browser options, upload paths or real-session
capture hooks. Only the internal smoke runner mints a capability. Output remains
in RAM until its complete, ordered input matches a canonical fixture. The raw
provider segments are retained for analysis, never as proof of audible playback.
"""
import base64
import binascii
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
from threading import Event, Lock, Thread
from time import monotonic, time
import wave
import zipfile

import db
from . import audio_store

FIXTURES = {
    'id': '3751b3b407c81b5f6398f1dcccc4ad21fbaffda3912e51f6aabe12f760714fc9',
    'en': '955455943bd45b9ca13b375030f75b49e9515d477ab26a65ed3e6731df3e0e8a',
}
TTL_SECONDS = 600
MAX_ENTRIES = 4
MAX_OUTPUT_BYTES = 90 * 48000
MAX_JSON_BYTES = 512 * 1024
MAX_BUNDLE_BYTES = 6 * 1024 * 1024
MAX_EVENTS = 2048
MAX_SECONDS = 120
MAX_TEXT = 4000
KINDS = ('zip', 'json', 'wav', 'source.wav')
_ROOT = Path('/tmp') / ('kilas-gemini-synthetic-v1-' + str(os.getuid()))
_MINT = object()
_maintenance_lock = Lock()
_maintenance_started = False
_write_lock = Lock()
_ID = re.compile(r'^[a-f0-9]{48}$')
_FILES = {'source.wav', 'output.wav', 'timeline.json'}
_DIAGNOSTIC_NUMBERS = (
    'generation_complete_count', 'turn_complete_count', 'generation_complete_after_end',
    'turn_complete_after_end', 'input_accepted_bytes', 'input_sent_bytes',
    'input_sent_packets', 'output_accepted_bytes', 'output_received_packets',
    'output_rejected_bytes', 'last_output_after_start_ms',
)
_CODES = frozenset((
    'gemini_transport', 'gemini_deadline', 'gemini_tail_timeout', 'gemini_tail_unconfirmed',
    'gemini_setup_invalid', 'gemini_response_invalid', 'gemini_output_limit',
    'gemini_input_idle', 'gemini_input_invalid', 'gemini_backlog', 'gemini_unavailable',
    'gemini_session_changed', 'gemini_settlement_failed', 'turn_cancelled',
))


def _unavailable():
    return audio_store.AudioError('Hasil uji sintetis tidak tersedia.', 'gemini_fixture_unavailable', 404)


def _binding(owner):
    """Fresh configured ID/email + database role check, independent of paid ON."""
    try:
        configured = os.environ.get('KILAS_LIVE_GEMINI_QA_OWNER_ID', '')
        expected = os.environ.get('KILAS_LIVE_GEMINI_QA_OWNER_EMAIL', '').strip().lower()
        if (type(owner) is not int or not 0 < owner <= 10**9 or configured != str(owner)
                or not expected or len(expected) > 254 or '@' not in expected):
            return None
        row = db.query_one('SELECT email,role FROM users WHERE id=?', (owner,))
        if (not row or row['role'] != 'CLIENT_OWNER' or not isinstance(row['email'], str)
                or row['email'].strip().lower() != expected):
            return None
        return hashlib.sha256((str(owner) + '\0' + expected).encode('utf-8')).hexdigest()
    except Exception:
        # Fail closed without copying database/configuration errors into logs.
        return None


def require_owner(owner):
    if _binding(owner) is None:
        raise _unavailable()


def fixture_pcm(language):
    """No caller paths: verify fixed WAV bytes before decoding the fixed format."""
    if language not in FIXTURES:
        raise _unavailable()
    path = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'gemini_live_synthetic' / (language + '.wav')
    try:
        # Bound reads even if a deployment accidentally replaces a fixture.
        with path.open('rb') as handle:
            raw = handle.read(480045)
        if hashlib.sha256(raw).hexdigest() != FIXTURES[language]:
            raise _unavailable()
        with wave.open(io.BytesIO(raw), 'rb') as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()) != (1, 2, 16000, 240000):
                raise _unavailable()
            return wav.readframes(240000)
    except (OSError, ValueError, wave.Error):
        raise _unavailable() from None


def _root(create=False):
    """Open a fixed private directory; never follow a substituted symlink."""
    if create:
        try:
            os.mkdir(_ROOT, 0o700)
        except FileExistsError:
            pass
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(_ROOT, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise OSError('private_storage_unavailable')
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _names(descriptor):
    return [name for name in os.listdir(descriptor)
            if re.fullmatch(r'[a-f0-9]{48}\.(?:zip|pending)', name)]


def _cleanup(descriptor):
    cutoff = time() - TTL_SECONDS
    for name in _names(descriptor):
        try:
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            # Symlinks and unsafe files are never read. Delete their directory
            # entry only; the outside target is never traversed or changed.
            if not stat.S_ISREG(info.st_mode) or info.st_mtime <= cutoff:
                os.unlink(name, dir_fd=descriptor)
        except FileNotFoundError:
            pass


def cleanup():
    """Best-effort TTL sweep; an absent directory is not created by maintenance."""
    try:
        descriptor = _root()
    except OSError:
        return
    try:
        _cleanup(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _sweep():
    while True:
        cleanup()
        Event().wait(30)


def start_cleanup():
    """Explicit worker-start hook, including when Gemini and QA arming are OFF."""
    global _maintenance_started
    with _maintenance_lock:
        if not _maintenance_started:
            Thread(target=_sweep, name='kilas-synthetic-expiry', daemon=True).start()
            _maintenance_started = True


def _wav(pcm, rate):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return stream.getvalue()


def _publish(owner_binding, source, output, timeline):
    created = time()
    timeline.update(created_at=datetime.fromtimestamp(created, timezone.utc).isoformat(),
                    expires_at=datetime.fromtimestamp(created + TTL_SECONDS, timezone.utc).isoformat(),
                    created_epoch=created, expires_epoch=created + TTL_SECONDS,
                    owner_binding=owner_binding)
    encoded = json.dumps(timeline, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(encoded) > MAX_JSON_BYTES:
        raise _unavailable()
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('source.wav', _wav(source, 16000))
        archive.writestr('output.wav', _wav(output, 24000))
        archive.writestr('timeline.json', encoded)
    value = bundle.getvalue()
    if len(value) > MAX_BUNDLE_BYTES:
        raise _unavailable()
    descriptor = _root(create=True)
    pending = None
    try:
        with _write_lock:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            _cleanup(descriptor)
            if len(_names(descriptor)) >= MAX_ENTRIES:
                raise _unavailable()
            ident = secrets.token_hex(24)
            pending = ident + '.pending'
            file_descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                      0o600, dir_fd=descriptor)
            with os.fdopen(file_descriptor, 'wb') as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            # An exclusive hard link makes the complete bundle visible at once
            # without overwriting a pre-existing file, even across processes.
            os.link(pending, ident + '.zip', src_dir_fd=descriptor, dst_dir_fd=descriptor, follow_symlinks=False)
            os.unlink(pending, dir_fd=descriptor)
            pending = None
            return ident
    finally:
        if pending is not None:
            try:
                os.unlink(pending, dir_fd=descriptor)
            except FileNotFoundError:
                pass
        os.close(descriptor)


def _read(descriptor, ident, binding):
    file_descriptor = os.open(ident + '.zip', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=descriptor)
    with os.fdopen(file_descriptor, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
                or not 0 < info.st_size <= MAX_BUNDLE_BYTES):
            raise _unavailable()
        raw = handle.read(MAX_BUNDLE_BYTES + 1)
    with zipfile.ZipFile(io.BytesIO(raw), 'r') as archive:
        files = archive.infolist()
        if (len(files) != 3 or {item.filename for item in files} != _FILES
                or any(item.compress_type != zipfile.ZIP_STORED for item in files)):
            raise _unavailable()
        limits = {'source.wav': 480044, 'output.wav': MAX_OUTPUT_BYTES + 44, 'timeline.json': MAX_JSON_BYTES}
        if any(not 0 < item.file_size <= limits[item.filename] for item in files):
            raise _unavailable()
        timeline_raw = archive.read('timeline.json')
        timeline = json.loads(timeline_raw)
        if not isinstance(timeline, dict) or timeline.get('owner_binding') != binding:
            raise _unavailable()
        created, expires = timeline.get('created_epoch'), timeline.get('expires_epoch')
        if (type(created) not in (int, float) or type(expires) not in (int, float)
                or not math.isfinite(created) or not math.isfinite(expires)
                or not created <= time() < expires or expires != created + TTL_SECONDS
                or timeline.get('scope') != 'canonical_synthetic_fixture_only'):
            raise _unavailable()
        return raw, timeline_raw, timeline, archive.read('output.wav'), archive.read('source.wav')


def _summary(ident, timeline):
    return {'id': ident, 'source_language': timeline['source_language'],
            'target_language': timeline['target_language'], 'created_at': timeline['created_at'],
            'expires_at': timeline['expires_at'], 'input_ms': timeline['input_ms'],
            'output_ms': timeline['output_ms'], 'download_kinds': list(KINDS)}


def list_for_owner(owner):
    binding = _binding(owner)
    if binding is None:
        raise _unavailable()
    start_cleanup()
    try:
        descriptor = _root()
    except FileNotFoundError:
        return []
    except OSError:
        raise _unavailable() from None
    results = []
    try:
        _cleanup(descriptor)
        for name in _names(descriptor):
            if not name.endswith('.zip'):
                continue
            try:
                _, _, timeline, _, _ = _read(descriptor, name[:-4], binding)
                results.append(_summary(name[:-4], timeline))
            except (OSError, ValueError, KeyError, zipfile.BadZipFile, audio_store.AudioError):
                continue
        return sorted(results, key=lambda item: item['created_at'], reverse=True)
    finally:
        os.close(descriptor)


def export(owner, ident, kind='zip'):
    binding = _binding(owner)
    if (binding is None or not isinstance(ident, str) or not _ID.fullmatch(ident)
            or kind not in KINDS):
        raise _unavailable()
    start_cleanup()
    descriptor = None
    try:
        descriptor = _root()
        _cleanup(descriptor)
        bundle, timeline_raw, _, output, source = _read(descriptor, ident, binding)
        data, mimetype, filename = {
            'zip': (bundle, 'application/zip', 'gemini-synthetic-fixture.zip'),
            'json': (timeline_raw, 'application/json', 'gemini-synthetic-timeline.json'),
            'wav': (output, 'audio/wav', 'gemini-synthetic-output.wav'),
            'source.wav': (source, 'audio/wav', 'gemini-synthetic-source.wav'),
        }[kind]
        return {'data': data, 'mimetype': mimetype, 'filename': filename}
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        raise _unavailable() from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def begin_fixture(owner, source, target):
    """Mint only in trusted server code; HTTP input never supplies a capability."""
    binding = _binding(owner)
    if binding is None or (source, target) not in (('id', 'en'), ('en', 'id')):
        raise _unavailable()
    pcm = fixture_pcm(source)
    start_cleanup()
    return _FixtureCapture(_MINT, owner, binding, source, target, pcm)


class _FixtureCapture:
    def __init__(self, mint, owner, binding, source, target, pcm):
        if mint is not _MINT:
            raise _unavailable()
        self.owner, self.binding, self.source, self.target = owner, binding, source, target
        self.source_pcm = pcm
        self.started = monotonic()
        self.lock = Lock()
        self.valid = True
        self.closed = self.finalized = False
        self.expected = self.accepted = self.generation = 0
        self.output_pcm = bytearray()
        self.source_text = self.target_text = ''
        self.events = []

    def _invalidate(self):
        self.valid = False
        self.output_pcm.clear()
        self.source_text = self.target_text = ''
        self.events.clear()
        return False

    def _event(self, event, **fields):
        if not self.valid or self.finalized:
            return False
        elapsed = monotonic() - self.started
        if elapsed < 0 or elapsed > MAX_SECONDS or len(self.events) >= MAX_EVENTS:
            return self._invalidate()
        self.events.append({'event': event, 'at_ms': round(elapsed * 1000, 3), **fields})
        return True

    def accept(self, index, pcm):
        """Call only after relay.accept succeeded; exact fixed chunk order required."""
        with self.lock:
            expected = self.source_pcm[self.accepted:self.accepted + 16000]
            if (not self.valid or self.finalized or self.closed or type(index) is not int
                    or index != self.expected or not isinstance(pcm, bytes)
                    or not expected or pcm != expected):
                return self._invalidate()
            if not self._event('input_chunk', index=index, bytes=len(pcm), input_offset=self.accepted):
                return False
            self.expected += 1
            self.accepted += len(pcm)
            return True

    def finish_input(self, count):
        """The full sequence, not a caller fixture flag, permits persistence."""
        with self.lock:
            if (not self.valid or self.finalized or self.closed or type(count) is not int
                    or count != self.expected or self.accepted != len(self.source_pcm)):
                return self._invalidate()
            self.closed = True
            return self._event('input_finished', chunks=count, bytes=self.accepted)

    def observe(self, value):
        """Passive provider response observation; only an explicit small allowlist."""
        with self.lock:
            if not self.valid or self.finalized:
                return False
            try:
                if not isinstance(value, dict):
                    return self._invalidate()
                if 'setupComplete' in value:
                    self._event('setup_complete')
                error = value.get('error')
                if isinstance(error, dict) and type(error.get('code')) is int:
                    self._event('provider_error', code=max(0, min(error['code'], 10**7)))
                usage = value.get('usageMetadata')
                if isinstance(usage, dict):
                    numeric = {key: usage[key] for key in ('promptTokenCount', 'responseTokenCount', 'totalTokenCount')
                               if type(usage.get(key)) is int and 0 <= usage[key] <= 10**7}
                    if numeric:
                        self._event('usage', **numeric)
                content = value.get('serverContent', {})
                if not isinstance(content, dict):
                    return self._invalidate()
                if content.get('interrupted') is True:
                    self.generation += 1
                    self._event('interrupted', generation=self.generation, output_offset=len(self.output_pcm))
                for field, attribute in (('inputTranscription', 'source_text'), ('outputTranscription', 'target_text')):
                    transcript = content.get(field)
                    if transcript is not None:
                        if not isinstance(transcript, dict) or not isinstance(transcript.get('text', ''), str):
                            return self._invalidate()
                        text = getattr(self, attribute) + transcript.get('text', '')
                        if len(text) > MAX_TEXT:
                            return self._invalidate()
                        setattr(self, attribute, text)
                        self._event('source_transcript' if attribute == 'source_text' else 'target_transcript',
                                    characters=len(transcript.get('text', '')), total_characters=len(text))
                turn = content.get('modelTurn', {})
                if not isinstance(turn, dict) or not isinstance(turn.get('parts', []), list):
                    return self._invalidate()
                for part in turn.get('parts', []):
                    if not isinstance(part, dict):
                        return self._invalidate()
                    audio = part.get('inlineData')
                    if audio is None:
                        continue
                    if (not isinstance(audio, dict) or audio.get('mimeType') != 'audio/pcm;rate=24000'
                            or not isinstance(audio.get('data'), str)
                            or len(audio['data']) > 2 * MAX_OUTPUT_BYTES):
                        return self._invalidate()
                    pcm = base64.b64decode(audio['data'], validate=True)
                    if not pcm or len(pcm) % 2 or len(self.output_pcm) + len(pcm) > MAX_OUTPUT_BYTES:
                        return self._invalidate()
                    offset = len(self.output_pcm)
                    if not self._event('output_segment', generation=self.generation, bytes=len(pcm),
                                       output_offset=offset, samples=len(pcm) // 2):
                        return False
                    self.output_pcm.extend(pcm)
                for field, name in (('generationComplete', 'generation_complete'), ('turnComplete', 'turn_complete'),
                                    ('waitingForInput', 'waiting_for_input')):
                    if content.get(field) is True:
                        self._event(name, generation=self.generation, output_offset=len(self.output_pcm))
                status = content.get('interactionStatus')
                if status in ('IDLE', 'IN_PROGRESS', 'REQUIRES_ACTION', 'INTERACTION_STATUS_UNSPECIFIED'):
                    self._event('interaction_status', status=status)
                return self.valid
            except (ValueError, TypeError, binascii.Error):
                return self._invalidate()

    def finalize(self, code=None, diagnostics=None):
        """Publish once after settlement/End; invalid or incomplete input is erased."""
        with self.lock:
            if (not self.valid or self.finalized or not self.closed or not self.output_pcm
                    or self.accepted != len(self.source_pcm) or _binding(self.owner) != self.binding):
                self.finalized = True
                self._invalidate()
                return None
            numeric = {}
            if isinstance(diagnostics, dict):
                for key in _DIAGNOSTIC_NUMBERS:
                    value = diagnostics.get(key)
                    if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 10**9:
                        numeric[key] = value
                for key in ('end_sent', 'tail_confirmed'):
                    if type(diagnostics.get(key)) is bool:
                        numeric[key] = diagnostics[key]
                if diagnostics.get('completion_kind') in ('turn_complete', 'bounded_drain'):
                    numeric['completion_kind'] = diagnostics['completion_kind']
                for key in ('first_error_code', 'tail_code'):
                    if isinstance(diagnostics.get(key), str) and diagnostics[key] in _CODES:
                        numeric[key] = diagnostics[key]
            if not self._event('finalized', code=code if isinstance(code, str) and code in _CODES else None):
                self.finalized = True
                return None
            timeline = {'version': 1, 'scope': 'canonical_synthetic_fixture_only',
                        'source_language': self.source, 'target_language': self.target,
                        'fixture_wav_sha256': FIXTURES[self.source],
                        'source_pcm_sha256': hashlib.sha256(self.source_pcm).hexdigest(),
                        'input_ms': len(self.source_pcm) / 32, 'output_ms': len(self.output_pcm) / 48,
                        'input_format': {'encoding': 'pcm_s16le', 'rate': 16000, 'channels': 1},
                        'output_format': {'encoding': 'pcm_s16le', 'rate': 24000, 'channels': 1},
                        'output_semantics': 'raw_provider_segments_in_receive_order_including_interrupted_generations',
                        'audible_playback_verified': False, 'semantic_translation_tail_verified': False,
                        'source_text': self.source_text, 'translated_text': self.target_text,
                        'protocol': numeric, 'events': self.events}
            self.finalized = True
            try:
                return _publish(self.binding, self.source_pcm, bytes(self.output_pcm), timeline)
            except (OSError, ValueError, audio_store.AudioError):
                return None
            finally:
                self._invalidate()
