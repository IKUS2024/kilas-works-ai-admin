"""Video-only owner isolation, optimistic revision leases and private references."""
import json
from datetime import datetime, timezone, timedelta
import db
from . import usage
from .autonomous_store import transaction


def stamp():return datetime.now(timezone.utc).isoformat()


def get(owner, project):
    row=db.query_one('SELECT * FROM kilas_video_projects WHERE id=? AND user_id=? AND deleted_at IS NULL',(project,owner))
    return dict(row) if row else None


def history(owner,page=1):
    return db.query_all('SELECT id,title,version,status FROM kilas_video_projects WHERE user_id=? AND deleted_at IS NULL ORDER BY updated_at DESC,id DESC LIMIT 21 OFFSET ?',(owner,(page-1)*20))


def create(owner,idea,options,key,images=()):
    with transaction() as conn:
        row=usage._query(conn,'INSERT INTO kilas_video_projects(user_id,title,idea,options_json,operation_key,created_at,updated_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(user_id,operation_key) DO NOTHING RETURNING id',(owner,' '.join(idea.split())[:60],idea,json.dumps(options),key,stamp(),stamp()),one=True)
        if not row:
            return usage._query(conn,'SELECT id FROM kilas_video_projects WHERE user_id=? AND operation_key=? AND deleted_at IS NULL',(owner,key),one=True)[0]
        for image in images:
            usage._query(conn,'INSERT INTO kilas_video_references(project_id,filename,mime_type,byte_size,content) VALUES (?,?,?,?,?)',(row[0],image['filename'],image['mime_type'],image['byte_size'],image['content']))
        return row[0]


def references(owner,project):
    return [dict(r) for r in db.query_all('SELECT r.* FROM kilas_video_references r JOIN kilas_video_projects p ON p.id=r.project_id WHERE p.user_id=? AND p.id=? AND p.deleted_at IS NULL ORDER BY r.id',(owner,project))]


def claim(owner,project,version):
    with transaction() as conn:
        row=usage._query(conn,"UPDATE kilas_video_projects SET status='GENERATING',updated_at=? WHERE id=? AND user_id=? AND version=? AND deleted_at IS NULL AND (status!='GENERATING' OR updated_at<?) RETURNING id",(stamp(),project,owner,version,(datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat()),one=True)
        return bool(row)


def save(owner,project,version,spec,options,instruction):
    encoded=json.dumps(spec,ensure_ascii=False)
    with transaction() as conn:
        row=usage._query(conn,"UPDATE kilas_video_projects SET spec_json=?,options_json=?,idea=?,version=version+1,status='READY',title=?,updated_at=? WHERE id=? AND user_id=? AND version=? AND status='GENERATING' AND deleted_at IS NULL RETURNING id",(encoded,json.dumps(options),instruction,spec['title'][:60],stamp(),project,owner,version),one=True)
        if not row:raise ValueError('revision_conflict')
        snapshot=json.dumps({'plan':spec,'brief':options['_brief']},ensure_ascii=False) if '_brief' in options else encoded
        usage._query(conn,'INSERT INTO kilas_video_revisions(project_id,version,instruction,spec_json,created_at) VALUES (?,?,?,?,?)',(project,version+1,instruction,snapshot,stamp()))


def fail(owner,project,version,instruction=None,controls=None,generation='all'):
    if instruction is not None:
        with transaction() as conn:
            row=usage._query(conn,'SELECT options_json FROM kilas_video_projects WHERE id=? AND user_id=? AND version=?',(project,owner,version),one=True)
            if row:
                options=json.loads(row[0]);options['_retry']={'idea':instruction,'generation':generation,'controls':{k:v for k,v in (controls or {}).items() if not k.startswith('_')}}
                usage._query(conn,"UPDATE kilas_video_projects SET options_json=? WHERE id=? AND user_id=? AND version=? AND status='GENERATING'",(json.dumps(options),project,owner,version))
    db.execute("UPDATE kilas_video_projects SET status='ERROR',updated_at=? WHERE id=? AND user_id=? AND version=? AND status='GENERATING'",(stamp(),project,owner,version))


def rename(owner,project,title):
    if not get(owner,project):return False
    db.execute('UPDATE kilas_video_projects SET title=?,updated_at=? WHERE id=? AND user_id=? AND deleted_at IS NULL',(title,stamp(),project,owner));return True


def delete(owner,project):
    if not get(owner,project):return False
    db.execute('UPDATE kilas_video_projects SET deleted_at=? WHERE id=? AND user_id=? AND deleted_at IS NULL',(stamp(),project,owner));return True


def duplicate(owner,project,key):
    source=get(owner,project)
    if not source:return None
    result=create(owner,source['idea'],json.loads(source['options_json']),key,references(owner,project))
    row=get(owner,result)
    if row['version']==0 and source['version'] and claim(owner,result,0):
        save(owner,result,0,json.loads(source['spec_json']),json.loads(source['options_json']),'Duplikat rencana')
        rename(owner,result,(source['title'][:50]+' — salinan')[:60])
    return result
