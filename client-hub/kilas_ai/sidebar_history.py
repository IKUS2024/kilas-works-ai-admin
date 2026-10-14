"""Read-only, bounded owned history in the sidebar's existing group order."""
import db
from flask import abort, current_app, url_for
from itsdangerous import BadData, URLSafeSerializer

PAGE_SIZE=20


def _signer():
    return URLSafeSerializer(current_app.secret_key,salt='kilas-sidebar-history-v1')


def _cursor(owner,kind,row=None):
    return _signer().dumps({'owner':owner,'kind':kind,
                           'at':str(row['updated_at']) if row else None,
                           'id':row['id'] if row else None})


def _rows(owner,kind,after,limit=PAGE_SIZE+1):
    if kind=='conversation':
        table='kilas_ai_conversations';condition='archived_at IS NULL'
    else:
        table='kilas_ai_threads'
        condition="NOT EXISTS (SELECT 1 FROM kilas_ai_messages b WHERE b.thread_id=kilas_ai_threads.id AND b.operation_key LIKE 'agent-attachments:%')"
    params=[owner];boundary=''
    if after and after['id'] is not None:
        boundary=' AND (updated_at<? OR (updated_at=? AND id<?))'
        params.extend((after['at'],after['at'],after['id']))
    params.append(limit)
    return db.query_all(f'SELECT id,title,updated_at FROM {table} WHERE user_id=? AND {condition}{boundary} ORDER BY updated_at DESC,id DESC LIMIT ?',tuple(params))


def page(owner,token=None,*,include_conversations=True):
    kind='conversation' if include_conversations else 'thread';after=None
    if token is not None:
        if not isinstance(token,str) or not 1<=len(token)<=2048:abort(400)
        try:after=_signer().loads(token)
        except BadData:abort(400)
        if not isinstance(after,dict) or set(after)!={'owner','kind','at','id'}:abort(400)
        if type(after['owner']) is not int or after['owner']!=owner:abort(400)
        if after['kind'] not in ('conversation','thread') or (after['kind']=='conversation' and not include_conversations):abort(400)
        if after['id'] is None:
            if after['at'] is not None:abort(400)
        elif type(after['id']) is not int or after['id']<=0 or not isinstance(after['at'],str) or not 1<=len(after['at'])<=128:abort(400)
        kind=after['kind']
    rows=_rows(owner,kind,after)
    if kind=='conversation' and not rows:
        kind='thread';rows=_rows(owner,kind,None)
    visible=rows[:PAGE_SIZE]
    next_cursor=(_cursor(owner,kind,visible[-1]) if len(rows)>PAGE_SIZE else
                 _cursor(owner,'thread') if kind=='conversation' and _rows(owner,'thread',None,1) else None)
    return {'items':[{'kind':kind,'id':row['id'],'title':row['title'],
                      'href':url_for('kilas_ai.agent_home',conversation=row['id']) if kind=='conversation' else url_for('kilas_ai.thread_page',thread_id=row['id'])}
                     for row in visible], 'next_cursor':next_cursor}
