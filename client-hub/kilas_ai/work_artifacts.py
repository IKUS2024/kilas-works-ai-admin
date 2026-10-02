"""Durable Work files. No public path, base64 metadata or Chat-history dependency."""
import hashlib
import io
import json
import re
import db
from pypdf import PdfReader
from . import usage

MIMES={'pdf':'application/pdf','csv':'text/csv','json':'application/json','md':'text/markdown','txt':'text/plain','png':'image/png','jpg':'image/jpeg','webp':'image/webp'}


def validate(file):
    raw=file.get('content')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',file.get('filename','')):raise ValueError('invalid_work_filename')
    if not isinstance(raw,bytes) or not 0 < len(raw) <= 8*1024*1024 or file['mime_type'] not in MIMES.values():raise ValueError('invalid_work_file')
    if file['mime_type']=='application/pdf':
        reader=PdfReader(io.BytesIO(raw),strict=True)
        if not raw.startswith(b'%PDF') or reader.is_encrypted or not reader.pages or not any(p.extract_text().strip() for p in reader.pages):raise ValueError('invalid_work_pdf')
    elif file['mime_type'].startswith('image/'):
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as picture:
            if {'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp'}.get(picture.format)!=file['mime_type'] or picture.width*picture.height>20_000_000:raise ValueError('invalid_work_image')
            picture.verify()
    return raw


def persist(conn,job,step,file):
    raw=validate(file)
    metadata=json.dumps({'source':file.get('extracted_text','')[:24000],'title':file.get('title',''),'format':file['filename'].rsplit('.',1)[-1]},ensure_ascii=False)
    digest=hashlib.sha256(raw).hexdigest()
    row=usage._query(conn,'INSERT INTO kilas_agent_artifacts(job_id,step_id,name,media_type,content,digest) VALUES (?,?,?,?,?,?) ON CONFLICT(step_id,name,digest) DO NOTHING RETURNING id',(job['id'],step['id'],file['filename'][:100],file['mime_type'],metadata,digest),one=True)
    if row:usage._query(conn,'INSERT INTO kilas_agent_artifact_files(artifact_id,content,byte_size) VALUES (?,?,?)',(row[0],raw,len(raw)))


def listing(user_id,job_id=None,conversation_id=None):
    where='j.user_id=?';params=[user_id]
    if job_id is not None:where+=' AND j.id=?';params.append(job_id)
    if conversation_id is not None:where+=' AND j.origin_conversation_id=?';params.append(conversation_id)
    return [dict(r) for r in db.query_all('SELECT a.id,a.job_id,a.name,a.media_type,a.content,f.byte_size FROM kilas_agent_artifacts a JOIN kilas_agent_jobs j ON j.id=a.job_id JOIN kilas_agent_artifact_files f ON f.artifact_id=a.id WHERE '+where+' ORDER BY a.id DESC LIMIT 20',tuple(params))]


def latest_document(user_id,conversation_id):
    for row in listing(user_id,conversation_id=conversation_id):
        if row['media_type']=='application/pdf':return row
    return None


def source(user_id,artifact_id,conversation_id):
    row=db.query_one('SELECT a.content FROM kilas_agent_artifacts a JOIN kilas_agent_jobs j ON j.id=a.job_id JOIN kilas_agent_artifact_files f ON f.artifact_id=a.id WHERE a.id=? AND j.user_id=? AND j.origin_conversation_id=?',(artifact_id,user_id,conversation_id))
    if not row:raise ValueError('source_not_owned')
    return json.loads(row['content'])['source']
