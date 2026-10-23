"""Bounded extractive history checkpoints; no inference or invented summaries."""
import db
from . import conversation_context, usage
from .autonomous_store import transaction

BATCH_SIZE = 128
MAX_BATCHES = 8
SUMMARY_LIMIT = 3000


def before(owner, conversation, boundary):
    """Advance at most 1024 old rows, retaining only 3000 quoted characters.

    Existing long chats catch up in bounded batches. New chats advance as turns
    leave the recent window. A remaining historical gap is disclosed to the model.
    """
    if not boundary:return ''
    with transaction() as conn:
        owned = usage._query(conn, 'SELECT id FROM kilas_ai_conversations WHERE user_id=? AND id=? AND archived_at IS NULL' +
            (' FOR UPDATE' if db.BACKEND == 'postgres' else ''), (owner, conversation), one=True)
        if not owned:return ''
        state = usage._query(conn, 'SELECT through_id,summary FROM kilas_chat_context_checkpoints WHERE user_id=? AND conversation_id=?',
                             (owner, conversation), one=True)
        through, summary = state if state else (0, '')
        for _ in range(MAX_BATCHES):
            rows = usage._rows(conn, "SELECT id,role,CASE WHEN role='user' THEN content ELSE '' END FROM kilas_ai_agent_messages "
                'WHERE user_id=? AND conversation_id=? AND id>? AND id<? ORDER BY id LIMIT ?',
                (owner, conversation, through, boundary, BATCH_SIZE))
            if not rows:break
            previous = [{'role':'user','content':line} for line in summary.splitlines()]
            summary = conversation_context.summary(previous + [{'role':r[1],'content':r[2]} for r in rows], SUMMARY_LIMIT)
            through = rows[-1][0]
            if len(rows) < BATCH_SIZE:break
        usage._query(conn, 'INSERT INTO kilas_chat_context_checkpoints(user_id,conversation_id,through_id,summary) VALUES (?,?,?,?) '
            'ON CONFLICT(user_id,conversation_id) DO UPDATE SET through_id=excluded.through_id,summary=excluded.summary',
            (owner, conversation, through, summary))
        gap = usage._query(conn, 'SELECT id FROM kilas_ai_agent_messages WHERE user_id=? AND conversation_id=? AND id>? AND id<? LIMIT 1',
                           (owner, conversation, through, boundary), one=True)
    return summary + ('\nSome older conversation turns are not yet indexed; do not assume their contents.' if gap else '')
