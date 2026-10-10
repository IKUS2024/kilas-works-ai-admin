"""Explicit synthetic artifacts inside an existing owner-owned conversation. No providers."""
import hashlib
import json
import os
from flask import abort, request
import db
from . import content_projects as projects, usage
from .autonomous_store import transaction

FIXTURES = {
    'intro': 'Halo, ini contoh rekaman sintetis untuk menguji transkrip dalam percakapan.',
    'question': 'Bisa jelaskan pilihan yang perlu kita bandingkan?',
}


def enabled():
    return os.environ.get('KILAS_CHAT_CONTENT_DEMO_ENABLED', '').strip().lower() in ('1', 'true', 'yes', 'on')


def conversation(owner, ident):
    row = db.query_one('SELECT id,title FROM kilas_ai_conversations WHERE id=? AND user_id=? AND archived_at IS NULL', (ident, owner))
    if not row:
        raise LookupError('conversation_not_owned')
    return dict(row)


def recording(owner, conversation_id, ident):
    conversation(owner, conversation_id)
    row = db.query_one('SELECT * FROM kilas_chat_demo_recordings WHERE id=? AND user_id=? AND conversation_id=?', (ident, owner, conversation_id))
    if not row:
        raise LookupError('recording_not_in_conversation')
    return dict(row)


def transcript(owner, conversation_id, ident, version):
    recording(owner, conversation_id, ident)
    row = db.query_one('SELECT * FROM kilas_chat_demo_transcripts WHERE recording_id=? AND version=?', (ident, version))
    if not row:
        raise LookupError('transcript_version_not_found')
    return dict(row)


def create_recording(owner, conversation_id, label, fixture, operation, consent):
    conversation(owner, conversation_id)
    projects.key(operation)
    label = ' '.join(label.split())
    if not consent or fixture not in FIXTURES or not 1 <= len(label) <= 120:
        raise ValueError('invalid_mock_recording')
    with transaction() as conn:
        existing = usage._query(conn, 'SELECT id,conversation_id,label,fixture FROM kilas_chat_demo_recordings WHERE user_id=? AND operation_key=?', (owner, operation), one=True)
        if existing:
            if existing[1:] != (conversation_id, label, fixture):
                raise projects.Conflict('operation_key_reused')
            return existing[0]
        inserted = usage._query(conn, 'INSERT INTO kilas_chat_demo_recordings(user_id,conversation_id,label,fixture,operation_key) VALUES (?,?,?,?,?) ON CONFLICT(user_id,operation_key) DO NOTHING RETURNING id', (owner, conversation_id, label, fixture, operation), one=True)
        if not inserted:
            existing = usage._query(conn, 'SELECT id,conversation_id,label,fixture FROM kilas_chat_demo_recordings WHERE user_id=? AND operation_key=?', (owner, operation), one=True)
            if existing[1:] != (conversation_id, label, fixture):
                raise projects.Conflict('operation_key_reused')
            return existing[0]
        ident = inserted[0]
        usage._query(conn, 'INSERT INTO kilas_chat_demo_transcripts(recording_id,version,content,operation_key) VALUES (?,1,?,?)', (ident, FIXTURES[fixture], operation))
        return ident


def edit_transcript(owner, conversation_id, ident, expected, text, operation):
    recording(owner, conversation_id, ident)
    projects.key(operation)
    text = text.strip()
    if not 1 <= len(text) <= 4000:
        raise ValueError('transcript_length_invalid')
    with transaction() as conn:
        existing = usage._query(conn, 'SELECT version,content FROM kilas_chat_demo_transcripts WHERE recording_id=? AND operation_key=?', (ident, operation), one=True)
        if existing:
            if existing[1] != text:
                raise projects.Conflict('operation_key_reused')
            return existing[0]
        row = usage._query(conn, 'UPDATE kilas_chat_demo_recordings SET transcript_version=transcript_version+1 WHERE id=? AND user_id=? AND conversation_id=? AND transcript_version=? RETURNING transcript_version', (ident, owner, conversation_id, expected), one=True)
        if not row:
            raise projects.Conflict('transcript_changed_reload')
        usage._query(conn, 'INSERT INTO kilas_chat_demo_transcripts(recording_id,version,content,operation_key) VALUES (?,?,?,?)', (ident, row[0], text, operation))
        return row[0]


def linked_project(owner, conversation_id):
    row = db.query_one('SELECT project_id FROM kilas_chat_demo_projects WHERE user_id=? AND conversation_id=?', (owner, conversation_id))
    return projects.get(owner, row['project_id']) if row else None


def attach_project(owner, conversation_id, ident):
    conversation(owner, conversation_id)
    if not projects.get(owner, ident):
        raise LookupError('project_not_owned')
    # Retries do not duplicate the underlying conversation link.
    projects.link(owner, ident, 'conversation', conversation_id, 0)
    db.execute('INSERT INTO kilas_chat_demo_projects(user_id,conversation_id,project_id) VALUES (?,?,?) ON CONFLICT(user_id,conversation_id) DO UPDATE SET project_id=excluded.project_id', (owner, conversation_id, ident))


def action(owner, conversation_id, ident):
    conversation(owner, conversation_id)
    row = db.query_one('SELECT * FROM kilas_chat_demo_actions WHERE id=? AND user_id=? AND conversation_id=?', (ident, owner, conversation_id))
    if not row:
        raise LookupError('action_not_owned')
    return dict(row)


def run_mock(owner, conversation_id, ident, version, kind, language, operation, source_action=None, voice='', expected_project_version=None):
    chosen = transcript(owner, conversation_id, ident, version)
    projects.key(operation)
    if kind not in ('translate', 'voice', 'project_script') or language not in ('id', 'en'):
        raise ValueError('mock_action_invalid')
    project = linked_project(owner, conversation_id) if kind == 'project_script' else None
    body = [conversation_id, ident, version, kind, language, source_action, voice, project['id'] if project else None, expected_project_version]
    fingerprint = hashlib.sha256(json.dumps(body, separators=(',', ':')).encode()).hexdigest()
    existing = db.query_one('SELECT id,payload_hash FROM kilas_chat_demo_actions WHERE user_id=? AND operation_key=?', (owner, operation))
    if existing:
        if existing['payload_hash'] != fingerprint:
            raise projects.Conflict('operation_key_reused')
        return existing['id']
    source = None
    if kind == 'voice':
        if voice != 'stock_demo':
            raise ValueError('personal_voice_not_enabled')
        source = action(owner, conversation_id, source_action)
        if source['kind'] != 'translate' or source['status'] != 'COMPLETED' or source['recording_id'] != ident or source['transcript_version'] != version or source['language'] != language:
            raise ValueError('translation_reference_mismatch')
    if kind == 'project_script' and not project:
        raise ValueError('choose_project_first')
    script_version = None
    if kind == 'project_script':
        # If a response is interrupted, retrying the same operation key reuses this snapshot.
        script_version = projects.save_script(owner, project['id'], expected_project_version, chosen['content'], operation)
        output = 'Snapshot transkrip tersimpan sebagai naskah proyek; tidak ada generasi.'
    elif kind == 'voice':
        output = 'Simulasi VoiceOver dari terjemahan #' + str(source['id']) + '. Tidak ada audio atau kloning suara.'
    else:
        output = '[MOCK ' + language + ' — belum diterjemahkan provider]\n' + chosen['content']
    with transaction() as conn:
        existing = usage._query(conn, 'SELECT id,payload_hash FROM kilas_chat_demo_actions WHERE user_id=? AND operation_key=?', (owner, operation), one=True)
        if existing:
            if existing[1] != fingerprint:
                raise projects.Conflict('operation_key_reused')
            return existing[0]
        inserted = usage._query(conn, 'INSERT INTO kilas_chat_demo_actions(user_id,conversation_id,recording_id,transcript_version,kind,language,source_action_id,output_text,project_id,project_script_version,operation_key,payload_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,operation_key) DO NOTHING RETURNING id', (owner, conversation_id, ident, version, kind, language, source_action, output, project['id'] if project else None, script_version, operation, fingerprint), one=True)
        if inserted:
            return inserted[0]
        existing = usage._query(conn, 'SELECT id,payload_hash FROM kilas_chat_demo_actions WHERE user_id=? AND operation_key=?', (owner, operation), one=True)
        if existing[1] != fingerprint:
            raise projects.Conflict('operation_key_reused')
        return existing[0]


def cancel(owner, conversation_id, ident):
    action(owner, conversation_id, ident)
    db.execute("UPDATE kilas_chat_demo_actions SET status='CANCELLED' WHERE id=? AND user_id=? AND conversation_id=?", (ident, owner, conversation_id))


def context(owner, conversation_id, selected=None, version=None):
    if not enabled():
        return None
    conversation(owner, conversation_id)
    rows = db.query_all('SELECT * FROM kilas_chat_demo_recordings WHERE user_id=? AND conversation_id=? ORDER BY id DESC LIMIT 50', (owner, conversation_id))
    if selected is None and rows:
        selected = rows[0]['id']
    item = recording(owner, conversation_id, selected) if selected else None
    chosen = transcript(owner, conversation_id, selected, version if version is not None else item['transcript_version']) if item else None
    revisions = db.query_all('SELECT version FROM kilas_chat_demo_transcripts WHERE recording_id=? ORDER BY version DESC LIMIT 50', (selected,)) if item else []
    history = db.query_all('SELECT * FROM kilas_chat_demo_actions WHERE user_id=? AND conversation_id=? ORDER BY id DESC LIMIT 50', (owner, conversation_id))
    return {'conversation_id': conversation_id, 'recordings': rows, 'recording': item, 'transcript': chosen,
            'revisions': revisions, 'history': history, 'project': linked_project(owner, conversation_id),
            'projects': projects.listing(owner)}


def view_context(owner, conversation_id):
    if not enabled():
        return None
    for name in ('demo_recording', 'demo_version'):
        if name in request.args and (request.args.get(name, type=int) is None or request.args.get(name, type=int) <= 0):
            abort(400)
    try:
        data = context(owner, conversation_id, request.args.get('demo_recording', type=int), request.args.get('demo_version', type=int))
        data['listening_enabled'] = os.environ.get('KILAS_LISTENING_DEMO_ENABLED', '').strip().lower() in ('1', 'true', 'yes', 'on')
        return data
    except LookupError:
        abort(404)
