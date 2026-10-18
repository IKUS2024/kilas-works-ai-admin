"""Durable Work files. No public path, base64 metadata or Chat-history dependency."""
import hashlib
import io
import json
import re
import db
from pypdf import PdfReader
from . import usage

from .workspace_output_formats import MIMES,validate as validate_output
RETENTION_POLICY='Retained in account history with no automatic expiry. Archiving a chat hides it and does not delete its files. Data deletion requires the existing account data-deletion process.'


def validate(file):
    return validate_output(file.get('filename',''),file.get('mime_type'),file.get('content'))


def persist(conn,job,step,file):
    raw=validate(file)
    metadata=json.dumps({'source':(file.get('extracted_text') or '')[:24000],'title':file.get('title',''),'format':file['filename'].rsplit('.',1)[-1],'input':bool(file.get('input')), 'model_provenance':file.get('model_provenance'),'retention_policy':RETENTION_POLICY,'validation':file.get('validation',{}),'image_options':file.get('image_options')},ensure_ascii=False)
    digest=hashlib.sha256(raw).hexdigest()
    row=usage._query(conn,'INSERT INTO kilas_agent_artifacts(job_id,step_id,name,media_type,content,digest) VALUES (?,?,?,?,?,?) ON CONFLICT(step_id,name,digest) DO NOTHING RETURNING id',(job['id'],step['id'],file['filename'][:100],file['mime_type'],metadata,digest),one=True)
    if row:usage._query(conn,'INSERT INTO kilas_agent_artifact_files(artifact_id,content,byte_size) VALUES (?,?,?)',(row[0],raw,len(raw)))
    return row[0] if row else None


def listing(user_id,job_id=None,conversation_id=None):
    where='j.user_id=?';params=[user_id]
    if job_id is not None:where+=' AND j.id=?';params.append(job_id)
    if conversation_id is not None:where+=' AND j.origin_conversation_id=?';params.append(conversation_id)
    return [{**dict(r),'model_provenance':json.loads(r['content']).get('model_provenance'),'validation':json.loads(r['content']).get('validation',{})} for r in db.query_all('SELECT a.id,a.job_id,a.name,a.media_type,a.content,f.byte_size FROM kilas_agent_artifacts a JOIN kilas_agent_jobs j ON j.id=a.job_id JOIN kilas_agent_artifact_files f ON f.artifact_id=a.id WHERE '+where+' ORDER BY a.id DESC LIMIT 20',tuple(params)) if not json.loads(r['content']).get('input')]


def latest_document(user_id,conversation_id):
    for row in listing(user_id,conversation_id=conversation_id):
        if row['media_type'] in (MIMES['pdf'],MIMES['docx'],MIMES['xlsx'],MIMES['pptx']):return row
    return None


def source(user_id,artifact_id,conversation_id):
    row=db.query_one('SELECT a.content FROM kilas_agent_artifacts a JOIN kilas_agent_jobs j ON j.id=a.job_id JOIN kilas_agent_artifact_files f ON f.artifact_id=a.id WHERE a.id=? AND j.user_id=? AND j.origin_conversation_id=?',(artifact_id,user_id,conversation_id))
    if not row:raise ValueError('source_not_owned')
    return json.loads(row['content'])['source']


def image_source(user_id,artifact_id,conversation_id):
    row=db.query_one('SELECT a.name,a.media_type,f.content FROM kilas_agent_artifacts a JOIN kilas_agent_jobs j ON j.id=a.job_id JOIN kilas_agent_artifact_files f ON f.artifact_id=a.id WHERE a.id=? AND j.user_id=? AND j.origin_conversation_id=?',(artifact_id,user_id,conversation_id))
    if not row or not row['media_type'].startswith('image/'):raise ValueError('source_not_owned')
    return {'filename':row['name'],'mime_type':row['media_type'],'content':bytes(row['content'])}
