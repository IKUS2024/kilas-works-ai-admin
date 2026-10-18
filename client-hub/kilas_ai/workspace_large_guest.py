"""Versioned large-output runner. Source is delivered to a VM, never run here."""
import hashlib
import inspect
import os
from pathlib import Path
import stat

SMALL_GUEST_SHA256='41420460392f80c3b3314b7f254005f5947ae81b550dae7b084dc38c6807dd61'


def stage_outputs(output=None,staging=None):
    # Called by trusted runner only AFTER kill_children()/wait. The untrusted
    # child cannot access /root or change these root-owned staged files.
    output=ROOT/'output' if output is None else output
    if output.is_symlink():raise ValueError('unsafe_output')
    staging=Path('/root/kilas-large-output') if staging is None else staging
    staging.mkdir(mode=0o700)
    os.chmod(staging,0o700)
    manifest=[];total=0
    for path in sorted(output.iterdir()):
        if len(manifest)>=4:raise ValueError('output_limit')
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=UID or info.st_nlink!=1 or not 0<info.st_size<=8388608:raise ValueError('unsafe_output')
            total+=info.st_size
            if total>16777216:raise ValueError('output_limit')
            label=f'{len(manifest):03}'
            target=os.open(staging/label,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC,0o600)
            digest=hashlib.sha256();size=0
            try:
                while True:
                    chunk=os.read(fd,min(65536,info.st_size-size+1))
                    if not chunk:break
                    size+=len(chunk)
                    if size>info.st_size:raise ValueError('unsafe_output')
                    digest.update(chunk)
                    view=memoryview(chunk)
                    while view:
                        written=os.write(target,view)
                        if written<=0:raise ValueError('unsafe_output')
                        view=view[written:]
            finally:os.close(target)
            after=os.fstat(fd)
            if size!=info.st_size or (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)!=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns):raise ValueError('unsafe_output')
            manifest.append({'name':path.name,'slot':label,'size':size,'sha256':digest.hexdigest()})
        finally:os.close(fd)
    return {'protocol':'kilas.large.v1','files':manifest}


def runner_source():
    from . import workspace_guest
    source=Path(workspace_guest.__file__).read_text()
    if hashlib.sha256(source.encode()).hexdigest()!=SMALL_GUEST_SHA256:raise ValueError('large_runner_baseline_changed')
    start=source.index('    total=0;output=ROOT/\'output\'')
    end=source.index('    write_report(report)',start)
    source=source[:start]+"    report['outputs']=stage_outputs()\n"+source[end:]
    source=source.replace("('RLIMIT_FSIZE',65536)","('RLIMIT_FSIZE',8388608)")
    return source.replace('import base64\n','import base64\nimport hashlib\n'+inspect.getsource(stage_outputs)+'\n',1)


def collector_acceptance():
    # Fixed trusted self-test after UID processes are dead. Deliberately invalid
    # source sizes never become publishable outputs. All staging is removed.
    import shutil
    base=Path('/root/kilas-collector-check');base.mkdir(mode=0o700)
    checks=[]
    try:
        for kind,sizes in (('file_limit',[8388609]),('job_limit',[8388608,8388608,1]),('file_count',[1]*5)):
            source=base/kind;source.mkdir(mode=0o700)
            for index,size in enumerate(sizes):
                target=source/str(index)
                with target.open('wb') as output:output.truncate(size)
                os.chown(target,UID,UID)
            try:stage_outputs(source,base/(kind+'-stage'))
            except ValueError as error:
                if str(error)!=('unsafe_output' if kind=='file_limit' else 'output_limit'):raise
            else:raise ValueError('unsafe_output')
            checks.append(kind)
            shutil.rmtree(source);shutil.rmtree(base/(kind+'-stage'))
        return {'checks':checks,'private_staging':True,'post_stop':True}
    finally:shutil.rmtree(base)


def proof_runner_source():
    source=runner_source()
    source=source.replace("    report['outputs']=stage_outputs()", "    report['collector_evidence']=collector_acceptance()\n    report['outputs']=stage_outputs()",1)
    return source.replace('import hashlib\n','import hashlib\n'+inspect.getsource(collector_acceptance)+'\n',1)
