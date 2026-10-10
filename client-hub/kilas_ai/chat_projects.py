"""Real project controls in an owner-owned chat. No synthetic artifacts or providers."""
from flask import abort, request
import db
from . import content_projects as projects, usage
from .autonomous_store import transaction


def conversation(owner, ident):
    row = db.query_one('SELECT id,title FROM kilas_ai_conversations WHERE id=? AND user_id=? AND archived_at IS NULL', (ident, owner))
    if not row:
        raise LookupError('conversation_not_owned')
    return dict(row)


def selected(owner, conversation_id):
    conversation(owner, conversation_id)
    # Existing metadata binding; its historical table name does not enable demo routes.
    row = db.query_one('SELECT project_id FROM kilas_chat_demo_projects WHERE user_id=? AND conversation_id=?', (owner, conversation_id))
    return projects.get(owner, row['project_id']) if row else None


def choose(owner, conversation_id, ident, expected, operation, title='', brief=''):
    projects.key(operation)
    if expected is None or expected < 0 or (ident is not None and ident <= 0):
        raise ValueError('project_selection_invalid')
    if ident is None:
        title = ' '.join(title.split())
        if not 1 <= len(title) <= 100 or len(brief) > 2400:
            raise ValueError('title_or_brief_invalid')
    with transaction() as conn:
        if not usage._query(conn, 'SELECT id FROM kilas_ai_conversations WHERE id=? AND user_id=? AND archived_at IS NULL', (conversation_id, owner), one=True):
            raise LookupError('conversation_not_owned')
        if ident is not None:
            if not usage._query(conn, 'SELECT id FROM kilas_content_projects WHERE id=? AND user_id=?', (ident, owner), one=True):
                raise LookupError('project_not_owned')
        else:
            row = usage._query(conn, 'INSERT INTO kilas_content_projects(user_id,title,brief,operation_key) VALUES (?,?,?,?) ON CONFLICT(user_id,operation_key) DO NOTHING RETURNING id', (owner, title, brief, operation), one=True)
            if row:
                ident = row[0]
            else:
                row = usage._query(conn, 'SELECT id,title,brief FROM kilas_content_projects WHERE user_id=? AND operation_key=?', (owner, operation), one=True)
                if row[1:] != (title, brief):
                    raise projects.Conflict('operation_key_reused')
                ident = row[0]
        current = usage._query(conn, 'SELECT project_id FROM kilas_chat_demo_projects WHERE user_id=? AND conversation_id=?', (owner, conversation_id), one=True)
        if (current and current[0] not in (expected, ident)) or (not current and expected != 0):
            raise projects.Conflict('project_selection_changed')
        changed = usage._query(conn, 'INSERT INTO kilas_chat_demo_projects(user_id,conversation_id,project_id) VALUES (?,?,?) ON CONFLICT(user_id,conversation_id) DO UPDATE SET project_id=excluded.project_id WHERE kilas_chat_demo_projects.project_id=? RETURNING project_id', (owner, conversation_id, ident, expected), one=True)
        if not changed:
            current = usage._query(conn, 'SELECT project_id FROM kilas_chat_demo_projects WHERE user_id=? AND conversation_id=?', (owner, conversation_id), one=True)
            if not current or current[0] != ident:
                raise projects.Conflict('project_selection_changed')
        usage._query(conn, "INSERT INTO kilas_content_links(project_id,kind,target_id,target_version,script_version) VALUES (?,'conversation',?,0,0) ON CONFLICT(project_id,kind,target_id,target_version,script_version) DO NOTHING", (ident, conversation_id))
        return ident


def owned_script(owner, conversation_id, ident, version):
    project = selected(owner, conversation_id)
    if not project or project['id'] != ident:
        raise LookupError('project_not_selected_in_conversation')
    chosen = projects.script(owner, ident, version)
    if not chosen:
        raise LookupError('script_version_not_found')
    return chosen


def save_script(owner, conversation_id, ident, expected, text, operation, reviewed):
    if not projects.get(owner, ident):
        raise LookupError('project_not_owned')
    project = selected(owner, conversation_id)
    if not project or project['id'] != ident:
        raise projects.Conflict('project_selection_changed')
    if not reviewed or expected is None or expected < 0:
        raise ValueError('script_review_required')
    # Freeze selection until the immutable revision commits, including concurrent switches.
    with transaction() as conn:
        lock = ' FOR UPDATE' if db.BACKEND == 'postgres' else ''
        binding = usage._query(conn, 'SELECT project_id FROM kilas_chat_demo_projects WHERE user_id=? AND conversation_id=?' + lock, (owner, conversation_id), one=True)
        if not binding or binding[0] != ident:
            raise projects.Conflict('project_selection_changed')
        projects.key(operation)
        text = text.strip()
        if not 1 <= len(text) <= 4000:
            raise ValueError('script_length_invalid')
        existing = usage._query(conn, 'SELECT version,content,source_kind FROM kilas_content_scripts WHERE project_id=? AND operation_key=?', (ident, operation), one=True)
        if existing:
            if existing[1] != text or existing[2] != 'manual':
                raise projects.Conflict('operation_key_reused')
            return existing[0]
        updated = usage._query(conn, 'UPDATE kilas_content_projects SET script_version=script_version+1 WHERE id=? AND user_id=? AND script_version=? RETURNING script_version', (ident, owner, expected), one=True)
        if not updated:
            raise projects.Conflict('script_changed_reload')
        version = updated[0]
        usage._query(conn, "INSERT INTO kilas_content_scripts(project_id,version,content,source_kind,operation_key) VALUES (?,?,?,'manual',?)", (ident, version, text, operation))
        return version


def context(owner, conversation_id, version=None):
    project = selected(owner, conversation_id)
    if version is not None and (version <= 0 or not project):
        raise ValueError('script_version_invalid')
    chosen = None
    if project and (version or project['script_version']):
        chosen = owned_script(owner, conversation_id, project['id'], version or project['script_version'])
    from . import transcription
    audio_draft = None
    if transcription.enabled() and project:
        row = db.query_one('SELECT * FROM kilas_chat_transcriptions WHERE user_id=? AND conversation_id=? AND project_id=? ORDER BY id DESC LIMIT 1', (owner, conversation_id, project['id']))
        audio_draft = {'ready': transcription.ready(), 'job': transcription.public(row) if row else None}
    return {'conversation_id': conversation_id, 'project': project, 'script': chosen, 'transcription': audio_draft,
            'projects': projects.listing(owner),
            'versions': db.query_all('SELECT version FROM kilas_content_scripts WHERE project_id=? ORDER BY version DESC LIMIT 50', (project['id'],)) if project else []}


def view_context(owner, conversation_id):
    if not projects.enabled():
        return None
    try:
        if 'chat_script_version' in request.args and request.args.get('chat_script_version', type=int) is None:
            raise ValueError('script_version_invalid')
        return context(owner, conversation_id, request.args.get('chat_script_version', type=int))
    except LookupError:
        abort(404)
    except ValueError:
        abort(400)
