"""Link unified message uploads to the existing private attachment store.

Empty backing messages satisfy the legacy attachment foreign keys. They never
enter model context or visible history; the operation key links the real turn.
"""
import json
import db
from . import usage


def sources(user_id, conversation_id):
    """Bounded document context from this owner's conversation, never binary replay."""
    rows=db.query_all(
        'SELECT a.filename,a.extracted_text FROM kilas_ai_agent_messages m '
        "JOIN kilas_ai_messages b ON b.operation_key=('agent-attachments:' || CAST(m.id AS TEXT)) "
        'JOIN kilas_ai_threads t ON t.id=b.thread_id AND t.user_id=m.user_id '
        'JOIN kilas_ai_attachments a ON a.message_id=b.id AND a.thread_id=t.id AND a.user_id=m.user_id '
        'WHERE m.user_id=? AND m.conversation_id=? AND a.extracted_text IS NOT NULL '
        'ORDER BY m.id DESC,a.id DESC LIMIT 5', (user_id,conversation_id))
    budget=12000
    result=[]
    for row in rows:
        value=row['extracted_text'][:min(4000,budget)]
        if value:result.append({'filename':row['filename'],'text':value})
        budget-=len(value)
        if budget<=0:break
    return list(reversed(result))


def latest_scan(user_id,conversation_id):
    """Only the latest owned scan; bounded rasterization repeats on explicit follow-up."""
    row=db.query_one(
        'SELECT a.filename,a.content FROM kilas_ai_agent_messages m '
        "JOIN kilas_ai_messages b ON b.operation_key=('agent-attachments:' || CAST(m.id AS TEXT)) "
        'JOIN kilas_ai_threads t ON t.id=b.thread_id AND t.user_id=m.user_id '
        'JOIN kilas_ai_attachments a ON a.message_id=b.id AND a.thread_id=t.id AND a.user_id=m.user_id '
        "WHERE m.user_id=? AND m.conversation_id=? AND a.mime_type='application/pdf' "
        "AND a.extracted_text LIKE '%PDF scan:%' ORDER BY m.id DESC,a.id DESC LIMIT 1",(user_id,conversation_id))
    return dict(row) if row else None


def save(conn, user_id, message_id, prepared):
    if not prepared:
        return
    thread_id = usage._query(conn, 'INSERT INTO kilas_ai_threads(user_id,title) VALUES (?,?) RETURNING id',
                             (user_id, 'Lampiran chat'), one=True)[0]
    backing_id = usage._query(conn, "INSERT INTO kilas_ai_messages(thread_id,role,operation_key) VALUES (?,'user',?) RETURNING id",
                              (thread_id, 'agent-attachments:' + str(message_id)), one=True)[0]
    for item in prepared:
        usage._query(conn, 'INSERT INTO kilas_ai_attachments(user_id,thread_id,message_id,filename,mime_type,byte_size,content,extracted_text) VALUES (?,?,?,?,?,?,?,?)',
                     (user_id, thread_id, backing_id, item['filename'], item['mime_type'], item['byte_size'], item['content'], item.get('extracted_text')))


def listing(user_id, conversation_id, message_ids):
    if not message_ids:
        return {}
    marks = ','.join('?' for _ in message_ids)
    rows = db.query_all(
        'SELECT m.id AS origin_message_id,a.id,a.thread_id,a.filename,a.mime_type,a.byte_size '
        'FROM kilas_ai_agent_messages m JOIN kilas_ai_messages b '
        "ON b.operation_key=('agent-attachments:' || CAST(m.id AS TEXT)) "
        'JOIN kilas_ai_threads t ON t.id=b.thread_id AND t.user_id=m.user_id '
        'JOIN kilas_ai_attachments a ON a.message_id=b.id AND a.thread_id=t.id AND a.user_id=m.user_id '
        f'WHERE m.user_id=? AND m.conversation_id=? AND m.id IN ({marks}) ORDER BY a.id',
        (user_id, conversation_id, *message_ids))
    result = {}
    for row in rows:
        result.setdefault(row['origin_message_id'], []).append(dict(row))
    # Older image-edit inputs already have durable files; project them read-only.
    from . import autonomous_runner, autonomous_store
    if not autonomous_runner.enabled():
        return result
    for job in autonomous_store.conversation_jobs(user_id, conversation_id, message_ids):
        origin = job['origin_message_id']
        if origin in result:
            continue
        for row in db.query_all('SELECT a.id,a.job_id,a.name AS filename,a.media_type AS mime_type,a.content,f.byte_size '
                                'FROM kilas_agent_artifacts a JOIN kilas_agent_artifact_files f ON f.artifact_id=a.id '
                                'WHERE a.job_id=? ORDER BY a.id', (job['id'],)):
            if json.loads(row['content']).get('input'):
                result.setdefault(origin, []).append(dict(row))
    return result
