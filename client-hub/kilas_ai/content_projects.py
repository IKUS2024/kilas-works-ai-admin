"""Default-off content project metadata. No media, billing or provider mutations."""
import json
import os
import re
from flask import abort, request
import db
from . import usage
from .autonomous_store import transaction


def enabled():
    return os.environ.get('KILAS_CONTENT_PROJECTS_ENABLED', '').lower() in ('1', 'true', 'yes', 'on')


class Conflict(ValueError):
    pass


def key(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', value or ''):
        raise ValueError('operation_key_invalid')
    return value


def get(owner, ident):
    row = db.query_one('SELECT * FROM kilas_content_projects WHERE id=? AND user_id=?', (ident, owner))
    return dict(row) if row else None


def listing(owner):
    return db.query_all('SELECT * FROM kilas_content_projects WHERE user_id=? ORDER BY id DESC LIMIT 50', (owner,))


def create(owner, title, brief, operation):
    title = ' '.join(title.split())
    if not 1 <= len(title) <= 100 or len(brief) > 2400:
        raise ValueError('title_or_brief_invalid')
    key(operation)
    with transaction() as conn:
        row = usage._query(conn, 'INSERT INTO kilas_content_projects(user_id,title,brief,operation_key) VALUES (?,?,?,?) ON CONFLICT(user_id,operation_key) DO NOTHING RETURNING id', (owner, title, brief, operation), one=True)
        if row:
            return row[0]
        existing = usage._query(conn, 'SELECT id,title,brief FROM kilas_content_projects WHERE user_id=? AND operation_key=?', (owner, operation), one=True)
        if existing[1:] != (title, brief):
            raise Conflict('operation_key_reused')
        return existing[0]


# Only fixed queries can resolve user-selected targets; never interpolate a table name.
TARGETS = {
    'video': 'SELECT id,title,version,spec_json FROM kilas_video_projects WHERE id=? AND user_id=? AND deleted_at IS NULL',
    'audio': 'SELECT id,title,mode,target_language,status,CASE WHEN substr(result_content,5,4)=? THEN 1 ELSE 0 END AS result_is_video FROM kilas_audio_jobs WHERE id=? AND user_id=?',
    'conversation': 'SELECT id,title FROM kilas_ai_conversations WHERE id=? AND user_id=? AND archived_at IS NULL',
    'thread': 'SELECT id,title FROM kilas_ai_threads WHERE id=? AND user_id=?',
}


def target(owner, kind, ident):
    if kind not in TARGETS:
        raise ValueError('target_invalid')
    params = (b'ftyp', ident, owner) if kind == 'audio' else (ident, owner)
    row = db.query_one(TARGETS[kind], params)
    if not row:
        raise LookupError('target_not_owned_or_removed')
    return dict(row)


def script(owner, project, version):
    return db.query_one('SELECT s.* FROM kilas_content_scripts s JOIN kilas_content_projects p ON p.id=s.project_id WHERE p.id=? AND p.user_id=? AND s.version=?', (project, owner, version))


def save_script(owner, project, expected, text, operation, source='manual', source_id=None):
    key(operation)
    existing = db.query_one('SELECT s.* FROM kilas_content_scripts s JOIN kilas_content_projects p ON p.id=s.project_id WHERE p.id=? AND p.user_id=? AND s.operation_key=?', (project, owner, operation))
    if existing:
        if existing['source_kind'] != source or (source == 'video' and existing['source_id'] != source_id) or (source == 'manual' and existing['content'] != text.strip()):
            raise Conflict('operation_key_reused')
        return existing['version']
    source_version = None
    if source == 'video':
        item = target(owner, source, source_id)
        source_version = item['version']
        text = json.loads(item['spec_json'] or '{}').get('voice_over', '')
    elif source != 'manual':
        raise ValueError('script_source_invalid')
    text = text.strip()
    if not 1 <= len(text) <= 4000:
        raise ValueError('script_length_invalid')
    with transaction() as conn:
        existing = usage._query(conn, 'SELECT s.version,s.content,s.source_kind,s.source_id FROM kilas_content_scripts s JOIN kilas_content_projects p ON p.id=s.project_id WHERE p.id=? AND p.user_id=? AND s.operation_key=?', (project, owner, operation), one=True)
        if existing:
            if existing[2] != source or (source == 'video' and existing[3] != source_id) or (source == 'manual' and existing[1] != text):
                raise Conflict('operation_key_reused')
            return existing[0]
        updated = usage._query(conn, 'UPDATE kilas_content_projects SET script_version=script_version+1 WHERE id=? AND user_id=? AND script_version=? RETURNING script_version', (project, owner, expected), one=True)
        if not updated:
            raise Conflict('script_changed_reload')
        version = updated[0]
        usage._query(conn, 'INSERT INTO kilas_content_scripts(project_id,version,content,source_kind,source_id,source_version,operation_key) VALUES (?,?,?,?,?,?,?)', (project, version, text, source, source_id if source == 'video' else None, source_version, operation))
        return version


def link(owner, project, kind, ident, version):
    if not get(owner, project):
        raise LookupError('project_not_owned')
    item = target(owner, kind, ident)
    if kind == 'audio' and item['status'] != 'COMPLETED':
        raise ValueError('link_completed_audio_only')
    if kind == 'video' and not item['version']:
        raise ValueError('link_ready_plan_only')
    if version and not script(owner, project, version):
        raise ValueError('script_version_invalid')
    source_version = item['version'] if kind == 'video' else 0
    with transaction() as conn:
        # Exact retry is a no-op. Linking to another script version is explicit.
        usage._query(conn, 'INSERT INTO kilas_content_links(project_id,kind,target_id,target_version,script_version) VALUES (?,?,?,?,?) ON CONFLICT(project_id,kind,target_id,target_version,script_version) DO NOTHING', (project, kind, ident, source_version, version))


def links(owner, project):
    if not get(owner, project):
        raise LookupError('project_not_owned')
    rows = db.query_all('SELECT * FROM kilas_content_links WHERE project_id=? ORDER BY id DESC LIMIT 100', (project,))
    result = []
    for row in rows:
        item = dict(row)
        try:
            item['target'] = target(owner, row['kind'], row['target_id'])
        except LookupError:
            item['target'] = None
        result.append(item)
    return result


def choices(owner):
    queries = {
        'video': 'SELECT id,title FROM kilas_video_projects WHERE user_id=? AND deleted_at IS NULL AND version>0 ORDER BY id DESC LIMIT 50',
        'audio': "SELECT id,title FROM kilas_audio_jobs WHERE user_id=? AND status='COMPLETED' ORDER BY id DESC LIMIT 50",
        'conversation': 'SELECT id,title FROM kilas_ai_conversations WHERE user_id=? AND archived_at IS NULL ORDER BY id DESC LIMIT 50',
        'thread': 'SELECT id,title FROM kilas_ai_threads WHERE user_id=? ORDER BY id DESC LIMIT 50',
    }
    return {kind: db.query_all(query, (owner,)) for kind, query in queries.items()}


def draft(owner):
    """Read an immutable, owner-owned draft. Never submit or create a provider job."""
    if not enabled() or 'content_project' not in request.args:
        return None
    ident = request.args.get('content_project', type=int)
    project = get(owner, ident)
    if not project:
        abort(404)
    version = request.args.get('script_version', type=int)
    if version is None or version < 0:
        abort(400)
    chosen = script(owner, ident, version) if version else None
    if version and not chosen:
        abort(404)
    mode = request.args.get('content_mode', 'voiceover')
    if mode not in ('voiceover', 'translate'):
        abort(400)
    return {'project': project, 'version': version, 'script': chosen['content'] if chosen else '', 'mode': mode}
