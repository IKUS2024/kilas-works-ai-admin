"""Owner-scoped Agent conversation and read-only activity over existing runs."""
import db
from datetime import datetime, timezone
from flask import has_request_context, session
from . import usage


def conversation(user_id, conversation_id):
    return db.query_one('SELECT * FROM kilas_ai_conversations WHERE id=? AND user_id=? AND archived_at IS NULL',
                        (conversation_id, user_id))


def new_conversation(user_id):
    from .autonomous_store import transaction
    with transaction() as conn:
        now = datetime.now(timezone.utc).isoformat()
        return usage._query(conn, 'INSERT INTO kilas_ai_conversations(user_id,created_at,updated_at) VALUES (?,?,?) RETURNING id', (user_id, now, now), one=True)[0]


def recent_conversations(user_id):
    return db.query_all('SELECT id,title FROM kilas_ai_conversations WHERE user_id=? AND archived_at IS NULL ORDER BY updated_at DESC,id DESC LIMIT 20', (user_id,))


def conversation_page(user_id, page):
    page = max(1, min(int(page), 10000))
    rows = db.query_all('SELECT id,title FROM kilas_ai_conversations WHERE user_id=? AND archived_at IS NULL ORDER BY updated_at DESC,id DESC LIMIT 21 OFFSET ?', (user_id, (page-1)*20))
    return rows[:20], len(rows)>20


def current_conversation(user_id):
    # A rolling deploy can leave messages written by the old Hub after 0079 applied.
    # Repair only that owner's NULL associations; never move an already-linked message.
    if db.query_one('SELECT id FROM kilas_ai_agent_messages WHERE user_id=? AND conversation_id IS NULL LIMIT 1', (user_id,)):
        from .autonomous_store import transaction
        with transaction() as conn:
            if db.BACKEND == 'postgres':
                usage._query(conn, 'SELECT id FROM users WHERE id=? FOR UPDATE', (user_id,), one=True)
            old = usage._query(conn, 'SELECT id FROM kilas_ai_conversations WHERE user_id=? ORDER BY id LIMIT 1', (user_id,), one=True)
            old_id = old[0] if old else usage._query(conn, "INSERT INTO kilas_ai_conversations(user_id,title) VALUES (?,'Percakapan sebelumnya') RETURNING id", (user_id,), one=True)[0]
            usage._query(conn, 'UPDATE kilas_ai_agent_messages SET conversation_id=? WHERE user_id=? AND conversation_id IS NULL', (old_id, user_id))
    selected = session.get('agent_conversation_id') if has_request_context() else None
    if selected and conversation(user_id, selected):
        return selected
    recent = recent_conversations(user_id)
    selected = recent[0]['id'] if recent else new_conversation(user_id)
    if has_request_context():
        session['agent_conversation_id'] = selected
    return selected


def claim_request(user_id, conversation_id, key):
    """One durable submission key cannot create two tasks, including across tabs."""
    from .autonomous_store import transaction
    with transaction() as conn:
        row = usage._query(conn, 'INSERT INTO kilas_agent_chat_requests(user_id,conversation_id,operation_key) VALUES (?,?,?) ON CONFLICT(user_id,operation_key) DO NOTHING RETURNING operation_key', (user_id, conversation_id, key), one=True)
        return bool(row)


def messages(user_id, limit=60, conversation_id=None, before=None):
    limit = max(1, min(int(limit), 100))
    conversation_id = conversation_id or current_conversation(user_id)
    if not conversation(user_id, conversation_id):
        return []
    rows = db.query_all(
        "SELECT id,role,content,created_at FROM kilas_ai_agent_messages "
        "WHERE user_id=? AND conversation_id=? AND (? IS NULL OR id<?) ORDER BY id DESC LIMIT ?",
        (user_id, conversation_id, before, before, limit))
    return list(reversed(rows))


def append(user_id, role, content, conversation_id=None):
    if role not in ("user", "assistant"):
        raise ValueError("invalid_agent_role")
    content = str(content or "").strip()
    if not content or len(content) > (12000 if role=='assistant' else 2400):
        raise ValueError("invalid_agent_message")
    conversation_id = conversation_id or current_conversation(user_id)
    if not conversation(user_id, conversation_id):
        raise ValueError('conversation_not_owned')
    from .autonomous_store import transaction
    with transaction() as conn:
        usage._query(conn, "INSERT INTO kilas_ai_agent_messages(user_id,role,content,conversation_id) VALUES (?,?,?,?)",
                     (user_id, role, content, conversation_id))
        title = ' '.join(content.split())[:60].rstrip()
        usage._query(conn, "UPDATE kilas_ai_conversations SET updated_at=?,title=CASE WHEN title='Chat baru' AND ?='user' THEN ? ELSE title END WHERE id=? AND user_id=?",
                     (datetime.now(timezone.utc).isoformat(), role, title, conversation_id, user_id))


def activity(user_id, limit=12):
    limit = max(1, min(int(limit), 30))
    return db.query_all(
        "SELECT r.id,r.automation_id,r.status,r.completed_at,r.scheduled_for,r.result_text,"
        "r.error_code,r.unread,a.title,a.automation_type "
        "FROM kilas_automation_runs r JOIN kilas_automations a "
        "ON a.id=r.automation_id AND a.user_id=r.user_id "
        "WHERE r.user_id=? AND a.deleted_at IS NULL AND r.status NOT IN ('QUEUED','RUNNING') "
        "ORDER BY r.id DESC LIMIT ?", (user_id, limit))
