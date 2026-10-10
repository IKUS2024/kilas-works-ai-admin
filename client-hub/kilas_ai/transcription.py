"""Owner-scoped real transcription jobs; raw audio is never persisted."""
import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
import db
from . import chat_projects, content_projects, audio_media, usage
from . import transcription_provider as provider
from .autonomous_store import transaction

MAX_BYTES = 10 * 1024 * 1024
MAX_SECONDS = 180
DAILY_ATTEMPTS = 2


def enabled():
    return os.environ.get('KILAS_CHAT_TRANSCRIPTION_ENABLED', '').lower() in ('1', 'true', 'yes', 'on')


def ready():
    return enabled() and provider.budget_ready() and provider.configured()


def project(owner, cid, pid, selected=True):
    chat_projects.conversation(owner, cid)
    if not content_projects.get(owner, pid):
        raise LookupError('project_not_owned')
    if selected:
        current = chat_projects.selected(owner, cid)
        if not current or current['id'] != pid:
            raise content_projects.Conflict('project_selection_changed')


def owned(owner, cid, pid, key):
    project(owner, cid, pid, selected=False)
    content_projects.key(key)
    row = db.query_one('SELECT * FROM kilas_chat_transcriptions WHERE user_id=? AND conversation_id=? AND project_id=? AND operation_key=?', (owner, cid, pid, key))
    if row and row['status'] == 'PROCESSING' and datetime.fromisoformat(row['created_at']) < datetime.now(timezone.utc) - timedelta(seconds=90):
        with transaction() as conn:
            usage._query(conn, "UPDATE kilas_chat_transcriptions SET status='FAILED' WHERE id=? AND user_id=? AND status='PROCESSING'", (row['id'], owner))
        row = db.query_one('SELECT * FROM kilas_chat_transcriptions WHERE id=? AND user_id=?', (row['id'], owner))
    return dict(row) if row else None


def public(row):
    return {'status': row['status'], 'text': row['text'], 'operation_key': row['operation_key'],
            'project_id': row['project_id'], 'conversation_id': row['conversation_id']}


def cancel(owner, cid, pid, key):
    project(owner, cid, pid, selected=False)
    content_projects.key(key)
    with transaction() as conn:
        lock = ' FOR UPDATE' if db.BACKEND == 'postgres' else ''
        usage._query(conn, 'SELECT id FROM users WHERE id=?' + lock, (owner,), one=True)
        existing = usage._query(conn, 'SELECT id FROM kilas_chat_transcriptions WHERE user_id=? AND operation_key=?', (owner, key), one=True)
        if not existing:
            if not ready():
                raise provider.TranscriptionError('transcription_budget_unavailable')
            cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            count = usage._query(conn, 'SELECT COUNT(*) FROM kilas_chat_transcriptions WHERE user_id=? AND created_at>=?', (owner, cutoff), one=True)[0]
            if count >= DAILY_ATTEMPTS:
                raise provider.TranscriptionError('transcription_attempt_limit')
        # A tombstone fences a POST that has not yet reached claim(). No audio/paid work.
        usage._query(conn, "INSERT INTO kilas_chat_transcriptions(user_id,conversation_id,project_id,operation_key,fingerprint,status,duration_ms,created_at) VALUES (?,?,?,?,?,'CANCELLED',1,?) ON CONFLICT(user_id,operation_key) DO NOTHING", (owner, cid, pid, key, 'cancelled-before-start', datetime.now(timezone.utc).isoformat()))
        usage._query(conn, "UPDATE kilas_chat_transcriptions SET status='CANCELLED',text='',usage_json='{}' WHERE user_id=? AND conversation_id=? AND project_id=? AND operation_key=? AND status IN ('PROCESSING','COMPLETED')", (owner, cid, pid, key))
    row = owned(owner, cid, pid, key)
    if not row:
        raise content_projects.Conflict('operation_key_reused')
    return row


def claim(owner, cid, pid, key, digest, ms):
    now = datetime.now(timezone.utc)
    with transaction() as conn:
        # Lock owner, not global billing state; count and insertion are atomic across tabs.
        lock = ' FOR UPDATE' if db.BACKEND == 'postgres' else ''
        usage._query(conn, 'SELECT id FROM users WHERE id=?' + lock, (owner,), one=True)
        binding = usage._query(conn, 'SELECT project_id FROM kilas_chat_demo_projects WHERE user_id=? AND conversation_id=?' + lock, (owner, cid), one=True)
        if not binding or binding[0] != pid:
            raise content_projects.Conflict('project_selection_changed')
        old = usage._query(conn, 'SELECT id,conversation_id,project_id,fingerprint,status FROM kilas_chat_transcriptions WHERE user_id=? AND operation_key=?', (owner, key), one=True)
        if old:
            if old[1:3] != (cid, pid) or (old[4] != 'CANCELLED' and old[3] != digest):
                raise content_projects.Conflict('operation_key_reused')
            return old[0], False
        count = usage._query(conn, 'SELECT COUNT(*) FROM kilas_chat_transcriptions WHERE user_id=? AND created_at>=?', (owner, (now - timedelta(days=1)).isoformat()), one=True)[0]
        if count >= DAILY_ATTEMPTS:
            raise provider.TranscriptionError('transcription_attempt_limit')
        row = usage._query(conn, "INSERT INTO kilas_chat_transcriptions(user_id,conversation_id,project_id,operation_key,fingerprint,status,duration_ms,created_at,consent_at) VALUES (?,?,?,?,?,'PROCESSING',?,?,?) RETURNING id", (owner, cid, pid, key, digest, ms, now.isoformat(), now.isoformat()), one=True)
        return row[0], True


def submit(owner, cid, pid, key, item, consent):
    project(owner, cid, pid)
    content_projects.key(key)
    if not consent:
        raise ValueError('audio_processing_consent_required')
    if not ready():
        raise provider.TranscriptionError('transcription_budget_unavailable')
    # Reuse browser media MIME/magic/10MiB/180s validation, FFmpeg sandbox and cleanup.
    pcm = audio_media.voice_sample(item)
    import io
    import wave
    with wave.open(io.BytesIO(pcm)) as audio:
        ms = int(audio.getnframes() * 1000 / audio.getframerate())
    if not 0 < ms <= MAX_SECONDS * 1000:
        raise ValueError('audio_duration_invalid')
    # voice_sample currently accepts browser WebM/Ogg/MP4/WAV; MP3 uploads use local
    # normalization in routes. Never pass filenames, URLs or raw uploads to provider.
    digest = hashlib.sha256(pcm).hexdigest()
    ident, fresh = claim(owner, cid, pid, key, digest, ms)
    if fresh:
        # Crash/timeout must not resubmit a paid request. Status polling can recover the
        # indeterminate PROCESSING state; a new attempt always requires explicit action.
        try:
            text, evidence = provider.transcribe(pcm)
            with transaction() as conn:
                usage._query(conn, "UPDATE kilas_chat_transcriptions SET status='COMPLETED',text=?,usage_json=? WHERE id=? AND user_id=? AND status='PROCESSING'", (text, json.dumps(evidence, allow_nan=False), ident, owner))
        except provider.TranscriptionError:
            with transaction() as conn:
                usage._query(conn, "UPDATE kilas_chat_transcriptions SET status='FAILED' WHERE id=? AND user_id=? AND status='PROCESSING'", (ident, owner))
    return owned(owner, cid, pid, key)
