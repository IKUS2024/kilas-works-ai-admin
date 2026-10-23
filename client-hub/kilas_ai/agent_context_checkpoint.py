"""Bounded extractive history checkpoints; no inference or invented summaries."""
import db
import re
from . import conversation_context, usage
from .autonomous_store import transaction

BATCH_SIZE = 128
MAX_BATCHES = 8
SUMMARY_LIMIT = 3000


def quotes(rows):
    """Select actual instruction/correction clauses, including a long turn's middle."""
    result=[]
    for row in rows:
        if row['role']!='user':continue
        text=row['content']
        if re.search(r'(?i)password|api.?key|secret|token\s*[:=]|kata sandi',text):continue
        clauses=re.split(r'(?<=[.!?;])\s+|\n+',text) if len(text)>650 else [text]
        ranked=sorted(range(len(clauses)),key=lambda i:(2 if conversation_context.CORRECTION.search(clauses[i]) else
            1 if conversation_context.CONSTRAINT.search(clauses[i]) else 0,i),reverse=True)[:8]
        for index in sorted(ranked):
            clause=clauses[index]
            if len(clause)>650:
                important=conversation_context.CORRECTION.search(clause) or conversation_context.CONSTRAINT.search(clause)
                if not important:continue
                start=max(0,important.start()-60)
                clause='[Quoted excerpt; surrounding text omitted] '+clause[start:start+590]
            result.append({'role':'user','content':clause})
    return result


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
            summary = conversation_context.summary(previous + quotes([{'role':r[1],'content':r[2]} for r in rows]), SUMMARY_LIMIT)
            through = rows[-1][0]
            if len(rows) < BATCH_SIZE:break
        usage._query(conn, 'INSERT INTO kilas_chat_context_checkpoints(user_id,conversation_id,through_id,summary) VALUES (?,?,?,?) '
            'ON CONFLICT(user_id,conversation_id) DO UPDATE SET through_id=excluded.through_id,summary=excluded.summary',
            (owner, conversation, through, summary))
        gap = usage._query(conn, 'SELECT id FROM kilas_ai_agent_messages WHERE user_id=? AND conversation_id=? AND id>? AND id<? LIMIT 1',
                           (owner, conversation, through, boundary), one=True)
    return summary + ('\nSome older conversation turns are not yet indexed; do not assume their contents.' if gap else '')
