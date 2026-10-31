"""Owned meaningful history, ordered by submitted message/work activity."""
import db
from flask import abort,current_app,url_for
from itsdangerous import BadData,URLSafeSerializer

PAGE_SIZE=20


def _signer():
    return URLSafeSerializer(current_app.secret_key,salt='kilas-sidebar-meaningful-history-v2')


def recent(owner,*,include_conversations=True,kind=None,after=None,limit=12,offset=0,copilot_only=False,exclude_copilot=False):
    def stamp(field):return field if db.BACKEND=='postgres' else "strftime('%Y-%m-%dT%H:%M:%fZ',"+field+')'
    # Opening, renaming, changing model, and job lease heartbeats do not count.
    visible="t.user_id=? AND NOT EXISTS (SELECT 1 FROM kilas_ai_messages b WHERE b.thread_id=t.id AND b.operation_key LIKE ?)"
    if copilot_only:
        include_conversations=False
        visible+=" AND EXISTS (SELECT 1 FROM kilas_ai_messages c WHERE c.thread_id=t.id AND c.operation_key='copilot:session:v1')"
    elif exclude_copilot:
        visible+=" AND NOT EXISTS (SELECT 1 FROM kilas_ai_messages c WHERE c.thread_id=t.id AND c.operation_key='copilot:session:v1')"
    streams=["SELECT 'thread' AS kind,t.id,t.title,"+stamp('m.created_at')+" AS at FROM kilas_ai_threads t JOIN kilas_ai_messages m ON m.thread_id=t.id WHERE "+visible+" AND TRIM(m.content)<>''",
             "SELECT 'thread',t.id,t.title,"+stamp('a.created_at')+" FROM kilas_ai_threads t JOIN kilas_ai_attachments a ON a.thread_id=t.id AND a.user_id=t.user_id JOIN kilas_ai_messages m ON m.id=a.message_id AND m.thread_id=t.id WHERE "+visible]
    params=[owner,'agent-attachments:%',owner,'agent-attachments:%']
    if include_conversations:
        base=' FROM kilas_ai_conversations c '
        owned=' WHERE c.user_id=? AND c.archived_at IS NULL'
        streams.extend([
            "SELECT 'conversation',c.id,c.title,"+stamp('m.created_at')+base+'JOIN kilas_ai_agent_messages m ON m.conversation_id=c.id AND m.user_id=c.user_id'+owned,
            "SELECT 'conversation',c.id,c.title,"+stamp('COALESCE(j.completed_at,j.stopped_at,j.created_at)')+base+'JOIN kilas_agent_jobs j ON j.origin_conversation_id=c.id AND j.user_id=c.user_id'+owned,
            "SELECT 'conversation',c.id,c.title,"+stamp('e.created_at')+base+'JOIN kilas_agent_jobs j ON j.origin_conversation_id=c.id AND j.user_id=c.user_id JOIN kilas_agent_events e ON e.job_id=j.id'+owned,
            "SELECT 'conversation',c.id,c.title,"+stamp('a.created_at')+base+'JOIN kilas_agent_jobs j ON j.origin_conversation_id=c.id AND j.user_id=c.user_id JOIN kilas_agent_artifacts a ON a.job_id=j.id'+owned])
        params.extend([owner]*4)
    sql='WITH activity AS ('+' UNION ALL '.join(streams)+'), items AS (SELECT kind,id,title,MAX(at) AS updated_at FROM activity GROUP BY kind,id,title) SELECT * FROM items WHERE updated_at IS NOT NULL'
    if kind:
        if kind not in ('thread','conversation'):raise ValueError('invalid_history_kind')
        sql+=' AND kind=?';params.append(kind)
    if after:
        sql+=' AND (updated_at<? OR (updated_at=? AND (kind>? OR (kind=? AND id<?))))'
        params.extend((after['at'],after['at'],after['kind'],after['kind'],after['id']))
    sql+=' ORDER BY updated_at DESC,kind ASC,id DESC LIMIT ? OFFSET ?'
    params.extend((max(1,min(int(limit),200)),max(0,int(offset))))
    return db.query_all(sql,tuple(params))


def page(owner,token=None,*,include_conversations=True,copilot_only=False,exclude_copilot=False):
    after=None
    if token is not None:
        if not isinstance(token,str) or not 1<=len(token)<=2048:abort(400)
        try:after=_signer().loads(token)
        except BadData:abort(400)
        if not isinstance(after,dict) or set(after)!={'owner','kind','at','id'}:abort(400)
        if type(after['owner']) is not int or after['owner']!=owner:abort(400)
        if after['kind'] not in ('conversation','thread') or (after['kind']=='conversation' and not include_conversations):abort(400)
        if type(after['id']) is not int or after['id']<=0 or not isinstance(after['at'],str) or not 1<=len(after['at'])<=128:abort(400)
    rows=recent(owner,include_conversations=include_conversations,after=after,limit=PAGE_SIZE+1,copilot_only=copilot_only,exclude_copilot=exclude_copilot)
    visible=rows[:PAGE_SIZE]
    cursor=_signer().dumps({'owner':owner,'kind':visible[-1]['kind'],'at':str(visible[-1]['updated_at']),'id':visible[-1]['id']}) if len(rows)>PAGE_SIZE else None
    return {'items':[{'kind':r['kind'],'id':r['id'],'title':r['title'],'href':url_for('kilas_ai.agent_home',conversation=r['id']) if r['kind']=='conversation' else url_for('kilas_ai.thread_page',thread_id=r['id'])} for r in visible],'next_cursor':cursor}
