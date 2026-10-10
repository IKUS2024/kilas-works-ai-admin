"""Real STT endpoints, independently gated; existing auth/CSRF are unchanged."""
import io
import tempfile
from pathlib import Path
from flask import abort, request, session
from werkzeug.datastructures import FileStorage
from .routes import ai_bp, automation_enabled
from . import transcription as store, content_projects, audio_media
from .transcription_provider import TranscriptionError


@ai_bp.before_request
def gate_transcription():
    if (request.endpoint or '').startswith('kilas_ai.transcription_'):
        if not store.enabled() or not content_projects.enabled() or not automation_enabled():
            abort(404)
        request.max_content_length = store.MAX_BYTES + 64 * 1024


@ai_bp.route('/agent/conversations/<int:cid>/projects/<int:pid>/transcription/<key>', methods=['GET', 'POST'], endpoint='transcription_job')
def job(cid, pid, key):
    owner = session['user_id']
    try:
        if request.method == 'GET':
            row = store.owned(owner, cid, pid, key)
        elif request.form.get('action') == 'cancel':
            row = store.cancel(owner, cid, pid, key)
        else:
            store.project(owner, cid, pid)
            if request.form.get('consent') != 'yes':
                raise ValueError('audio_processing_consent_required')
            item = request.files.get('audio')
            # WAV/WebM/Ogg/MP4/M4A are decoded by existing browser voice_sample.
            # MP3 support is local normalization only, still under this 10MiB limit.
            if item and item.mimetype in ('audio/mpeg', 'audio/mp3'):
                raw = item.stream.read(store.MAX_BYTES + 1)
                if not raw or len(raw) > store.MAX_BYTES or not (raw[:3] == b'ID3' or (raw[0] == 255 and len(raw) > 1 and raw[1] & 224 == 224)):
                    raise ValueError('audio_type_invalid')
                with tempfile.TemporaryDirectory(prefix='kilas-transcription-') as directory:
                    source = Path(directory) / 'recording.mp3'
                    source.write_bytes(raw)
                    _, pcm = audio_media._decode_source(source, directory, sample_rate=16000, max_seconds=store.MAX_SECONDS)
                item = FileStorage(stream=io.BytesIO(pcm), filename='recording.wav', content_type='audio/wav')
            row = store.submit(owner, cid, pid, key, item, True)
        if not row:
            abort(404)
        return store.public(row), 200, {'Cache-Control': 'private, no-store'}
    except LookupError:
        abort(404)
    except content_projects.Conflict:
        return {'error': 'Proyek atau permintaan berubah. Muat ulang chat.', 'code': 'transcription_conflict'}, 409, {'Cache-Control': 'private, no-store'}
    except TranscriptionError as error:
        code = str(error)
        return {'error': 'Transkripsi belum tersedia: batas biaya STT belum disetujui.' if code == 'transcription_budget_unavailable' else 'Batas percobaan transkripsi tercapai. Coba lagi besok.', 'code': code}, 503 if code == 'transcription_budget_unavailable' else 429, {'Cache-Control': 'private, no-store'}
    except (ValueError, audio_media.MediaError):
        return {'error': 'Setujui pemrosesan audio dan pilih rekaman yang valid, maksimal 10 MiB dan 3 menit.', 'code': 'transcription_invalid'}, 400, {'Cache-Control': 'private, no-store'}
