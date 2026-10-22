"""Read-only, paginated projection; owner-scoped source records stay authoritative."""
import math
import re
from pathlib import PurePath
from flask import abort, request, url_for
import db
from . import audio_store

KINDS={'all':'Semua aset','image':'Gambar','document':'Dokumen','audio':'Audio','video':'Rencana video','other':'File lainnya'}


def output_filter():
    # Legacy artifact metadata may be plain Markdown. Never cast it blindly.
    if db.BACKEND=='postgres':
        return "(CASE WHEN a.content IS JSON OBJECT THEN CAST(a.content AS JSONB)->>'input' ELSE NULL END) IS DISTINCT FROM 'true'"
    return "COALESCE(CASE WHEN json_valid(a.content) THEN json_extract(a.content,'$.input') ELSE NULL END,0)!=1"


def collection(owner, automation):
    kind=request.args.get('type','all');search=request.args.get('q','')[:200].strip()
    try:page=max(1,int(request.args.get('page','1')))
    except ValueError:abort(400)
    if kind not in KINDS:abort(400)
    # Metadata only; downloads retain their existing owner-scoped handlers.
    parts=["""SELECT a.id,a.thread_id AS parent,a.filename AS name,a.mime_type AS mime,
      CAST(a.created_at AS TEXT) AS created,'attachment' AS origin,'' AS status,t.title AS context,
      CASE WHEN substr(a.mime_type,1,6)='image/' THEN 'image' WHEN a.mime_type IN ('application/zip','application/octet-stream','text/html') THEN 'other' ELSE 'document' END AS kind
      FROM kilas_ai_attachments a JOIN kilas_ai_threads t ON t.id=a.thread_id AND t.user_id=a.user_id WHERE a.user_id=?""",
      """SELECT id,0,title,'audio/mpeg',CAST(created_at AS TEXT),'audio',status,voice_name,'audio'
      FROM kilas_audio_jobs WHERE user_id=? AND NOT """+audio_store.live_output_clause()+" AND NOT "+audio_store.learning_output_clause(),
      """SELECT id,0,title,'',CAST(updated_at AS TEXT),'plan',status,'','video'
      FROM kilas_video_projects WHERE user_id=? AND deleted_at IS NULL"""]
    params=[owner,owner,owner]
    if automation:
        parts.append("""SELECT a.id,a.job_id,a.name,a.media_type,CAST(a.created_at AS TEXT),'artifact','',j.title,
          CASE WHEN substr(a.media_type,1,6)='image/' THEN 'image' WHEN a.media_type IN ('application/zip','application/octet-stream','text/html') THEN 'other' ELSE 'document' END
          FROM kilas_agent_artifacts a JOIN kilas_agent_jobs j ON j.id=a.job_id
          JOIN kilas_agent_artifact_files f ON f.artifact_id=a.id WHERE j.user_id=? AND a.name!='_workspace.json'
          AND """+output_filter())
        params.append(owner)
    query=' FROM ('+' UNION ALL '.join(parts)+') assets WHERE 1=1'
    if kind!='all':query+=' AND kind=?';params.append(kind)
    if search:
        escaped=search.lower().replace('!','!!').replace('%','!%').replace('_','!_')
        query+=" AND (LOWER(name) LIKE ? ESCAPE '!' OR LOWER(context) LIKE ? ESCAPE '!')";params.extend(['%'+escaped+'%']*2)
    total=int(db.query_one('SELECT COUNT(*) AS n'+query,tuple(params))['n'])
    pages=max(1,math.ceil(total/24));page=min(page,pages)
    rows=db.query_all('SELECT *'+query+" ORDER BY REPLACE(created,'T',' ') DESC,id DESC,origin LIMIT 24 OFFSET ?",(*params,(page-1)*24))
    assets=[]
    for row in rows:
        item=dict(row);name=item['name'];stem=PurePath(name).stem
        numeric=bool(re.fullmatch(r'[\d_ -]+',stem))
        item['title']=(item['context'] if numeric and item['context'] else re.sub(r'[_-]+',' ',stem) if numeric else name) or name
        item.update(preview=None,download=None,reuse=None)
        if item['origin']=='attachment':
            item['download']=url_for('kilas_ai.attachment_download',thread_id=item['parent'],attachment_id=item['id'])
            item['open']=item['download']+'?inline=1' if item['mime'].startswith('image/') or item['mime']=='application/pdf' else item['download']
            item['reuse']=url_for('kilas_ai.thread_page',thread_id=item['parent'])
            if item['kind']=='image':item['preview']=item['open']
        elif item['origin']=='audio':
            item['open']=url_for('kilas_audio.home',ident=item['id'])
            if item['status']=='COMPLETED':item['download']=url_for('kilas_audio.result',ident=item['id'],download=1)
        elif item['origin']=='plan':item['open']=url_for('kilas_ai.video_project',project=item['id'])
        else:
            item['open']=url_for('kilas_ai.autonomous_artifact',job_id=item['parent'],artifact_id=item['id'])
            item['download']=url_for('kilas_ai.autonomous_artifact',job_id=item['parent'],artifact_id=item['id'],download=1)
        assets.append(item)
    return dict(assets=assets,total=total,page=page,pages=pages,search=search,kind=kind,kinds=KINDS)
