"""Incremental owner-scoped legacy Chat memory; source messages stay untouched."""
import db
from . import usage, conversation_context
from .agent_context_checkpoint import quotes, BATCH_SIZE, MAX_BATCHES, SUMMARY_LIMIT
from .autonomous_store import transaction


def before(owner, thread, boundary):
    if not boundary:
        return ''
    with transaction() as conn:
        if not usage._query(conn, 'SELECT id FROM kilas_ai_threads WHERE user_id=? AND id=?' +
                            (' FOR UPDATE' if db.BACKEND == 'postgres' else ''), (owner, thread), one=True):
            return ''
        state = usage._query(conn, 'SELECT through_id,summary FROM kilas_thread_context_checkpoints '
                            'WHERE user_id=? AND thread_id=?', (owner, thread), one=True)
        through, summary = state if state else (0, '')
        for _ in range(MAX_BATCHES):
            rows = usage._rows(conn, "SELECT id,role,CASE WHEN role='user' THEN content ELSE '' END "
                               'FROM kilas_ai_messages WHERE thread_id=? AND id>? AND id<? ORDER BY id LIMIT ?',
                               (thread, through, boundary, BATCH_SIZE))
            if not rows:
                break
            previous = [{'role':'user', 'content':line} for line in summary.splitlines()]
            summary = conversation_context.summary(previous + quotes([{'role':r[1], 'content':r[2]} for r in rows]), SUMMARY_LIMIT)
            through = rows[-1][0]
            if len(rows) < BATCH_SIZE:
                break
        usage._query(conn, 'INSERT INTO kilas_thread_context_checkpoints(user_id,thread_id,through_id,summary) '
                     'VALUES (?,?,?,?) ON CONFLICT(user_id,thread_id) DO UPDATE '
                     'SET through_id=excluded.through_id,summary=excluded.summary', (owner, thread, through, summary))
        gap = usage._query(conn, 'SELECT id FROM kilas_ai_messages WHERE thread_id=? AND id>? AND id<? LIMIT 1',
                           (thread, through, boundary), one=True)
    return summary + ('\nSome older conversation turns are not yet indexed; do not assume their contents.' if gap else '')
