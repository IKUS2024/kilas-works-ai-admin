"""Bounded source/archive tools. Read and package bytes; never execute their contents."""
import ast
import io
import json
import re
import stat
import zipfile
from pathlib import PurePosixPath

SOURCE_TYPES={'txt':'text/plain','md':'text/markdown','csv':'text/csv','json':'application/json',
              'html':'text/html','css':'text/css','js':'text/javascript','ts':'text/plain',
              'tsx':'text/plain','jsx':'text/javascript','py':'text/x-python','yaml':'text/yaml',
              'yml':'text/yaml','toml':'text/plain','sql':'text/plain','svg':'image/svg+xml'}
MAX_FILES=80
MAX_TOTAL=2*1024*1024
MAX_ENTRY=256*1024


def safe_path(name):
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_. /-]{1,180}',name):raise ValueError('unsafe_project_path')
    path=PurePosixPath(name)
    if path.is_absolute() or any(part in ('','..','.') for part in name.split('/')):raise ValueError('unsafe_project_path')
    if any(part.startswith('.') and part not in ('.gitignore',) for part in path.parts):raise ValueError('protected_project_path')
    if any(part.lower() in ('node_modules','__pycache__','venv') for part in path.parts):raise ValueError('project_dependency_tree')
    if path.suffix.lower().lstrip('.') not in SOURCE_TYPES and path.name not in ('Dockerfile','Makefile','.gitignore','LICENSE'):
        raise ValueError('unsupported_project_file')
    return name


def read_archive(raw):
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_TOTAL:raise ValueError('archive_size')
    result={};total=0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos=archive.infolist()
        if not 1<=len(infos)<=MAX_FILES*2:raise ValueError('archive_count')
        seen=set()
        for info in infos:
            name=info.filename.rstrip('/')
            if not name:raise ValueError('unsafe_project_path')
            # Validate directory paths too, including archives containing only traversal entries.
            if info.is_dir():
                if name.startswith('/') or any(p.startswith('.') or p in ('','..') for p in name.split('/')):raise ValueError('unsafe_archive_directory')
                continue
            safe_path(name)
            if name.casefold() in seen:raise ValueError('duplicate_archive_path')
            seen.add(name.casefold())
            mode=info.external_attr>>16
            if stat.S_ISLNK(mode) or (mode and stat.S_IFMT(mode) not in (0,stat.S_IFREG)) or info.flag_bits&1:raise ValueError('unsafe_archive_member')
            total+=info.file_size
            if info.file_size>MAX_ENTRY or total>MAX_TOTAL or info.file_size>max(1,info.compress_size)*100 or len(result)>=MAX_FILES:
                raise ValueError('archive_resource_limit')
            data=archive.read(info)
            if len(data)!=info.file_size or b'\0' in data:raise ValueError('invalid_source_text')
            result[name]=data.decode('utf-8-sig')
    if not result:raise ValueError('empty_project')
    return result


def describe(files,budget=18000):
    """Always expose scope/provenance. Quoted source is data, never tool authority."""
    chunks=['Project archive: '+str(len(files))+' source files. Read-only; code and dependencies were not executed.']
    used=len(chunks[0]);truncated=[]
    for name,value in files.items():
        allowance=min(5000,max(0,budget-used-len(name)-30))
        if allowance<=0:truncated.append(name);continue
        part='\nFile: '+name+'\n'+value[:allowance]
        if len(value)>allowance:part+='\n[Source truncated; remainder not read]';truncated.append(name)
        chunks.append(part);used+=len(part)
    if truncated:chunks.append('\nCoverage limited: '+', '.join(truncated)[:1000]+'. Do not claim these files were fully read or tested.')
    return '\n'.join(chunks)


def validate_source(name,value):
    safe_path(name)
    if not isinstance(value,str) or not value.strip() or len(value.encode())>MAX_ENTRY or '\0' in value:raise ValueError('invalid_source_text')
    suffix=PurePosixPath(name).suffix
    if suffix=='.json':json.loads(value)
    if suffix=='.py':ast.parse(value,filename=name)  # Syntax only; never compile/eval/exec/import user code.
    return value


def package(files):
    if not isinstance(files,dict) or not 1<=len(files)<=MAX_FILES:raise ValueError('invalid_project')
    if sum(len(str(value).encode()) for value in files.values())>MAX_TOTAL:raise ValueError('project_size')
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as archive:
        for name,value in files.items():
            validate_source(name,value)
            info=zipfile.ZipInfo(name);info.external_attr=(stat.S_IFREG|0o600)<<16
            archive.writestr(info,value.encode('utf-8'),compress_type=zipfile.ZIP_DEFLATED)
    raw=output.getvalue()
    read_archive(raw)  # Round-trip validates real ZIP structure, CRCs and paths.
    return raw
