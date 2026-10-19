"""Execution of owned project sources, with no model call or local-code fallback."""
import json
import re
import db
from . import workspace_execution as execution,workspace_files,workspace_projects


def requested(text):
    if re.search(r"(?i)\b(?:tanpa tools?|chat saja|no tools?|without tools?|do not (?:run|execute)|don't (?:run|execute)|jangan (?:jalankan|eksekusi))\b",text):return False
    return bool(re.search(r'(?i)(?:^(?:(?:please|tolong|coba)\s+)?|\b(?:and|then|dan|lalu|kemudian)\s+)(?:run|execute|test|jalankan|jalanin|eksekusi|uji|tes|ejecuta|prueba)\b|^(?:请)?(?:运行|执行|测试)',text)
                and re.search(r'(?i)\b(?:python|kode|code|project|proyek|zip|unittest|artifact|artefak)\b|代码|项目',text))


def plan(job):
    if not requested(job['instruction']) or workspace_projects.requested(job['instruction']):return None
    return {'objective':job['instruction'][:90],'mode':job['mode'],'stop_condition':'Actual remote exit status and retained output, or explicit unavailable status',
            'next_action':'Run isolated Python','steps':[{'worker':'EXECUTION','action':'python','instruction':'Menjalankan Python…',
                'input_json':json.dumps({'request':job['instruction']}),'completion_criteria':'Recorded remote process outcome; no invented test pass','requires_approval':False}]}


def source(job,data):
    checkpoint=json.loads(job['checkpoint_json'])
    files=workspace_projects.sources(job,checkpoint)
    if files:return files
    # Explicit artifact IDs are scoped to the same owner AND conversation.
    match=re.search(r'(?i)\b(?:artifact|artefak)\s*#?\s*(\d+)\b',data['request'])
    scope='a.id=? AND' if match else "a.media_type='application/zip' AND"
    params=(int(match[1]),job['user_id'],job['origin_conversation_id']) if match else (job['user_id'],job['origin_conversation_id'])
    row=db.query_one('SELECT a.media_type,a.name,f.content FROM kilas_agent_artifacts a JOIN kilas_agent_artifact_files f ON f.artifact_id=a.id JOIN kilas_agent_jobs j ON j.id=a.job_id WHERE '+scope+' j.user_id=? AND j.origin_conversation_id=? ORDER BY a.id DESC LIMIT 1',params)
    if not row:raise ValueError('execution_source_not_owned')
    if row['media_type']=='application/zip':return workspace_files.read_archive(bytes(row['content']))
    if row['name'].endswith('.py'):return {row['name']:bytes(row['content']).decode('utf-8')}
    raise ValueError('execution_python_source_required')


def entrypoint(files,request):
    if re.search(r'(?i)\b(?:unittest|tests|pengujian|uji|test|tes|prueba)\b|测试',request) and any(n.startswith('tests/') and n.endswith('.py') for n in files):return 'unittest'
    explicit=re.search(r'(?<![A-Za-z0-9_./-])([A-Za-z0-9_./-]+\.py)\b',request)
    if explicit:return workspace_files.safe_path(explicit[1])
    if 'main.py' in files:return 'main.py'
    choices=[name for name in files if name.endswith('.py') and not name.startswith('tests/') and not name.endswith('__init__.py')]
    if len(choices)==1:return choices[0]
    raise ValueError('execution_entrypoint_required')


def result(outcome):
    from .agent_workers import Result
    from . import workspace_artifact_transport as transport
    exported=transport.collect(outcome['outputs'])
    public={k:v for k,v in outcome.items() if k not in ('outputs','stdout','stderr','large_files')}
    if 'large_files' in outcome:public.update(transport='kilas.large.v1',large_run_id=outcome['run_id'])
    if exported:public['runtime_library_report']=exported[1]
    # Outputs remain real files. Logs never assert that user-supplied tests are trustworthy.
    log=json.dumps({**public,'stdout':outcome['stdout'],'stderr':outcome['stderr']},ensure_ascii=False,indent=2)
    artifacts=[{'binary_file':{'filename':'execution-result.json','mime_type':'application/json','content':log.encode(),
                            'validation':public,'title':'Python execution'}}]
    if 'large_files' in outcome:
        for file in outcome['large_files']:
            file['validation']={**public,**file['validation'],'large_run_id':outcome['run_id']}
            artifacts.append({'binary_file':file})
    elif exported:
        files,_=exported
        for file in files:file['validation']={**public,**file['validation']}
        artifacts.extend({'binary_file':file} for file in files)
        bundle=transport.bundle(files) if files else None
        if bundle:artifacts.append({'binary_file':bundle})
    elif outcome['outputs']:
        archive=workspace_files.package(outcome['outputs'])
        artifacts.append({'binary_file':{'filename':'execution-output.zip','mime_type':'application/zip','content':archive,
                                        'validation':public,'title':'Python output'}})
    success=outcome['exit_code']==0 and not outcome['timed_out']
    return Result('SUCCEEDED' if success else 'FAILED','Python selesai.' if success else 'Python gagal. Lihat hasil eksekusi.',public,artifacts,verified=True)


def run(job,step,data):
    from .agent_workers import Result
    from . import workspace_large_outputs as large, workspace_document_runtime as document
    if large.requested(data['request']):
        if not large.capability(job['user_id'])['available']:
            return Result('WAITING_CAPABILITY','Ekspor dokumen besar belum lolos verifikasi sandbox. File kecil tetap tersedia.',{'reason':'large_output_acceptance_pending','execution':'not_run'})
    if not execution.capability(job['user_id'])['available']:
        return Result('WAITING_CAPABILITY','Sandbox pengujian terisolasi belum tersedia.',{'reason':'isolated_execution_not_configured','execution':'not_run'})
    try:
        files=source(job,data)
        if large.requested(data['request']) or document.accepted():
            from .workspace_large_execution import execute
            return result(execute(job,step,files,entrypoint(files,data['request'])))
        from . import workspace_artifact_transport as transport
        prepared,entry=transport.prepare(files,entrypoint(files,data['request']))
        return result(execution.execute(job,step,prepared,entry))
    except ValueError as error:
        from . import usage
        if isinstance(error,usage.UsageLimit):return Result('FAILED',str(error),{'execution':'not_run','reason':'execution_quota_exhausted'})
        reason=str(error)
        messages={'execution_source_not_owned':'Tambahkan file Python atau ZIP proyek di percakapan ini.',
                  'execution_python_source_required':'Tambahkan file Python atau ZIP proyek di percakapan ini.',
                  'execution_entrypoint_required':'Sebutkan file Python yang ingin dijalankan, misalnya main.py.',
                  'execution_capacity_limit':'Batas eksekusi kode tercapai. Tidak ada sandbox baru dibuat.',
                  'execution_already_dispatched':'Eksekusi ini sudah dikirim. Permintaan tidak diulang.',
                  'execution_cancelled':'Pekerjaan dibatalkan.',
                  'execution_timeout':'Eksekusi terhenti. Hasil belum terverifikasi; permintaan tidak diulang.'}
        message=messages.get(reason,'Eksekusi gagal. Hasil belum terverifikasi; permintaan tidak diulang.')
        return Result('FAILED',message,{'execution':'not_verified','reason':reason if reason in messages else 'execution_failed'},verified=False)
