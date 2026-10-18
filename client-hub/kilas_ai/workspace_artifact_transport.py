"""Binary export framing outside the immutable proven VM/collector boundary."""
import base64,hashlib,io,json,re,zipfile
from pathlib import Path
from . import workspace_output_formats as formats

RESERVED={'_kilas_artifacts.py','_kilas_entrypoint.py'}
MAX_DECODED=180000


def prepare(files,entrypoint):
    from .workspace_execution import checked
    checked(files,entrypoint)  # Preserve original entrypoint/source admission before wrapping.
    if any(name.casefold() in RESERVED for name in files):raise ValueError('reserved_export_name')
    exporter=Path(__file__).with_name('workspace_artifact_exporter.py').read_text()
    action="sys.argv=['unittest','discover','-s','tests'];runpy.run_module('unittest',run_name='__main__')" if entrypoint=='unittest' else 'sys.argv=['+repr(entrypoint)+'];runpy.run_path('+repr(entrypoint)+",run_name='__main__')"
    wrapper="import os,runpy,sys\nfrom _kilas_artifacts import export_outputs\n_original_cwd=os.getcwd()\ntry:\n    "+action+"\nfinally:\n    os.chdir(_original_cwd)\n    export_outputs()\n"
    return {**files,'_kilas_artifacts.py':exporter,'_kilas_entrypoint.py':wrapper},'_kilas_entrypoint.py'


def collect(outputs):
    if not any(name.startswith('kilas-export-') or name=='kilas-runtime.json' for name in outputs):return None
    groups={};seen=set();runtime=None;encoded=0;decoded=0;frame_names=[]
    for name,text in outputs.items():
        encoded+=len(text.encode())
        if encoded>262144:raise ValueError('artifact_transport_limit')
        if name=='kilas-runtime.json':
            value=formats.strict_json(text)
            if not isinstance(value,dict) or set(value)!={'protocol','python','packages'} or value['protocol']!='kilas.runtime.v1' or not isinstance(value['python'],str) or not re.fullmatch(r'\d+\.\d+\.\d+',value['python']):raise ValueError('invalid_runtime_report')
            if not isinstance(value['packages'],dict) or set(value['packages'])!={'reportlab','docx','openpyxl','xlsxwriter','pptx','PIL'} or any(type(v) is not bool for v in value['packages'].values()):raise ValueError('invalid_runtime_report')
            runtime={**value,'evidence':'unprivileged guest report; availability is not generation acceptance'};continue
        if not re.fullmatch(r'kilas-export-\d{3}\.json',name):raise ValueError('mixed_export_protocol')
        frame_names.append(name)
        value=formats.strict_json(text)
        if not isinstance(value,dict) or set(value)!={'protocol','name','part','parts','sha256','base64'} or value['protocol']!='kilas.artifact.v1':raise ValueError('invalid_artifact_frame')
        formats.filename(value['name'])
        if value['name'].casefold() in {'source-project.zip','execution-result.json','execution-output.zip','kilas-runtime.json'} or value['name'].startswith('kilas-export-'):raise ValueError('reserved_artifact_name')
        if type(value['part']) is not int or type(value['parts']) is not int or not 0<=value['part']<value['parts']<=4 or not isinstance(value['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',value['sha256']) or not isinstance(value['base64'],str) or len(value['base64'])>60000:raise ValueError('invalid_artifact_frame')
        data=base64.b64decode(value['base64'],validate=True)
        if base64.b64encode(data).decode()!=value['base64']:raise ValueError('noncanonical_artifact_base64')
        if not 0<len(data)<=45000 or (value['part']<value['parts']-1 and len(data)!=45000):raise ValueError('invalid_artifact_chunk')
        key=value['name'].casefold()
        if key in seen:raise ValueError('artifact_name_collision')
        group=groups.setdefault(key,{'name':value['name'],'parts':value['parts'],'sha256':value['sha256'],'data':{}})
        if any(group[k]!=value[k] for k in ('name','parts','sha256')) or value['part'] in group['data']:raise ValueError('artifact_chunk_collision')
        group['data'][value['part']]=data;decoded+=len(data)
        if sum(len(g['data']) for g in groups.values())>4 or decoded>MAX_DECODED:raise ValueError('artifact_transport_limit')
    if runtime is None:raise ValueError('missing_runtime_report')
    if sorted(frame_names)!=[f'kilas-export-{i:03}.json' for i in range(len(frame_names))]:raise ValueError('invalid_artifact_sequence')
    files=[]
    for group in groups.values():
        if set(group['data'])!=set(range(group['parts'])):raise ValueError('truncated_artifact')
        raw=b''.join(group['data'][i] for i in range(group['parts']))
        if len(raw)>65536 or hashlib.sha256(raw).hexdigest()!=group['sha256']:raise ValueError('artifact_hash_mismatch')
        mime=formats.MIMES[formats.filename(group['name'])];formats.validate(group['name'],mime,raw)
        files.append({'filename':group['name'],'mime_type':mime,'content':raw,'validation':{'execution':'completed','format_checked':True,'transport':'kilas.artifact.v1'}});seen.add(group['name'].casefold())
    return files,runtime


def bundle(files):
    if any(file['mime_type']=='application/zip' for file in files):return None
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for file in files:archive.writestr(file['filename'],file['content'])
    raw=output.getvalue();formats.validate('execution-output.zip','application/zip',raw)
    return {'filename':'execution-output.zip','mime_type':'application/zip','content':raw,'validation':{'execution':'completed','format_checked':True}}
