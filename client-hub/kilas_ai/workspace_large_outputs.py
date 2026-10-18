"""Bounded streaming profile; deliberately unavailable until distinct VM proof."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import db
from . import workspace_execution as base, workspace_output_formats as formats, autonomous_store as store, usage

MAX_FILE=8*1024*1024
MAX_JOB=16*1024*1024
MAX_FILES=4
STORAGE_CEILING=64*1024*1024
STORAGE_RESERVATION=MAX_JOB+1024*1024  # Source ZIP, execution log and metadata margin.
PROFILE='kilas.large.v1'


def fingerprint():
    root=Path(__file__).parent
    names=('workspace_large_outputs.py','workspace_large_guest.py','workspace_large_execution.py',
           'workspace_execution.py','workspace_guest.py','workspace_execution_proof.py','workspace_acceptance_fixture.py',
           'workspace_execution_access.py','workspace_execution_credits.py','workspace_execution_rollout.py',
           'workspace_output_formats.py','work_artifacts.py','workspace_execution_worker.py','workspace_projects.py','autonomous_runner.py')
    return hashlib.sha256(b''.join((root/name).read_bytes() for name in names)).hexdigest()


def capability(user_id=None):
    # No environment value or old proof can accept this changed RLIMIT/collector.
    # A separately reviewed actual acceptance operation must precede activation.
    return {'available':False,'reason':'large_output_acceptance_pending','profile':PROFILE,
            'max_file_bytes':MAX_FILE,'max_job_bytes':MAX_JOB,'max_files':MAX_FILES,'fingerprint':fingerprint()}


def requested(text):
    return bool(re.search(r'(?i)\b(?:large|big|besar|grande|besar-besar)\b|大型|大文件',text)
                and re.search(r'(?i)\b(?:pdf|docx|xlsx|pptx|zip|documents?|dokumen|files?|berkas|project|proyek)\b|文件|文档',text))


def storage_check(conn,additional,exclude_run=None,require_idle=False):
    if db.BACKEND=='postgres':usage._query(conn,'SELECT pg_advisory_xact_lock(74110602)',())
    used=usage._query(conn,'SELECT COALESCE(SUM(byte_size),0) FROM kilas_agent_artifact_files',(),one=True)[0]
    # Include durable in-flight bytes, including UNKNOWN/cleanup/publication gaps.
    pending=0
    rows=usage._rows(conn,"SELECT id,outcome_json FROM kilas_workspace_executions WHERE outcome_json LIKE ?",('%large_storage_reserved%',))
    for ident,raw in rows:
        if ident==exclude_run:continue
        value=json.loads(raw or '{}').get('large_storage_reserved',0)
        if type(value) is not int or not 0<=value<=STORAGE_RESERVATION:raise ValueError('large_storage_unverified')
        pending+=value
    if require_idle and pending:raise ValueError('large_artifact_storage_busy')
    if used+pending+additional>STORAGE_CEILING:raise ValueError('large_artifact_storage_full')


def reserve_storage(run_id):
    with store.transaction() as conn:
        storage_check(conn,STORAGE_RESERVATION,exclude_run=run_id,require_idle=True)
        usage._query(conn,'UPDATE kilas_workspace_executions SET outcome_json=? WHERE id=?',(json.dumps({'large_storage_reserved':STORAGE_RESERVATION}),run_id))


def publishing(conn,job,run_id,additional):
    row=usage._query(conn,"SELECT outcome_json FROM kilas_workspace_executions WHERE id=? AND user_id=? AND job_id=? AND state IN ('SUCCEEDED','FAILED') AND cleanup_confirmed=1",(run_id,job['user_id'],job['id']),one=True)
    if not row or json.loads(row[0]).get('large_storage_reserved')!=STORAGE_RESERVATION:raise ValueError('large_output_not_owned')
    storage_check(conn,additional,exclude_run=run_id)


def published(conn,job,run_id):
    # Same transaction as all artifact inserts: rollback retains full reservation.
    row=usage._query(conn,'SELECT outcome_json FROM kilas_workspace_executions WHERE id=? AND user_id=? AND job_id=?',(run_id,job['user_id'],job['id']),one=True)
    if not row:raise ValueError('large_output_not_owned')
    value=json.loads(row[0]);value.pop('large_storage_reserved',None)
    usage._query(conn,'UPDATE kilas_workspace_executions SET outcome_json=? WHERE id=?',(json.dumps(value),run_id))


def manifest(value):
    if not isinstance(value,dict) or set(value)!={'protocol','files'} or value['protocol']!=PROFILE or not isinstance(value['files'],list) or len(value['files'])>MAX_FILES:raise ValueError('invalid_large_manifest')
    seen=set();total=0
    for index,item in enumerate(value['files']):
        if not isinstance(item,dict) or set(item)!={'name','slot','size','sha256'}:raise ValueError('invalid_large_manifest')
        formats.filename(item['name'])
        if item['name'].casefold() in seen or item['name'].casefold() in {'execution-result.json','source-project.zip'}:raise ValueError('large_name_collision')
        if item['slot']!=f'{index:03}' or type(item['size']) is not int or not 0<item['size']<=MAX_FILE or not isinstance(item['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',item['sha256']):raise ValueError('invalid_large_manifest')
        total+=item['size'];seen.add(item['name'].casefold())
    if total>MAX_JOB:raise ValueError('large_output_limit')
    return value['files']


def download(sandbox,value,deadline,active=lambda:True):
    items=manifest(value);files=[]
    # Private anonymous temporary files; no untrusted path and no persistent host
    # staging. All streams/files close on timeout, cancellation or validation error.
    if shutil.disk_usage(tempfile.gettempdir()).free<MAX_JOB*2:raise ValueError('large_transfer_space_unavailable')
    with tempfile.TemporaryDirectory(prefix='kilas-large-') as folder:
        os.chmod(folder,0o700)
        for item in items:
            if not active():raise ValueError('execution_cancelled')
            remaining=deadline-time.monotonic()
            if remaining<=0:raise ValueError('execution_timeout')
            digest=hashlib.sha256();count=0
            with tempfile.TemporaryFile(dir=folder) as target:
                with sandbox.files.read('/root/kilas-large-output/'+item['slot'],format='stream',user='root',gzip=False,request_timeout=min(5,remaining)) as stream:
                    # Verified E2B FileStreamReader contract. iter_raw explicitly
                    # limits yielded chunks and avoids decompression amplification.
                    response=getattr(stream,'_response',None)
                    if response is None or response.headers.get('content-encoding','identity').lower() not in ('','identity'):raise ValueError('large_stream_contract_unavailable')
                    length=response.headers.get('content-length')
                    if length is not None and (not length.isdecimal() or int(length)!=item['size']):raise ValueError('large_stream_length_mismatch')
                    for chunk in response.iter_raw(chunk_size=65536):
                        if not active():raise ValueError('execution_cancelled')
                        if time.monotonic()>deadline:raise ValueError('execution_timeout')
                        if len(chunk)>min(65536,item['size']-count):raise ValueError('large_output_limit')
                        count+=len(chunk);digest.update(chunk);target.write(chunk)
                if count!=item['size'] or digest.hexdigest()!=item['sha256']:raise ValueError('large_output_integrity')
                target.seek(0);raw=target.read(MAX_FILE+1)
            mime=formats.MIMES[formats.filename(item['name'])]
            formats.validate(item['name'],mime,raw,large=True)
            files.append({'filename':item['name'],'mime_type':mime,'content':raw,'validation':{'format_checked':True,'transport':PROFILE}})
    return files
