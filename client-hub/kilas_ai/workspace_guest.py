"""Trusted runner uploaded to a fresh remote E2B microVM; NEVER run on web host."""
import base64
import ctypes
import json
import os
from pathlib import Path
import resource
import signal
import stat
import subprocess
import time

ROOT=Path('/tmp/kilas-run')
UID=65534


def child_limits():
    os.setgroups([]);os.setgid(UID);os.setuid(UID)
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(38,1,0,0,0)!=0:raise OSError('no_new_privs_failed')
    for name,value in (('RLIMIT_CPU',10),('RLIMIT_AS',256*1024*1024),('RLIMIT_FSIZE',65536),
                       ('RLIMIT_NPROC',16),('RLIMIT_NOFILE',32),('RLIMIT_CORE',0)):
        resource.setrlimit(getattr(resource,name),(value,value))


def kill_children():
    # Stop first, including detached descendants, so no process can race output
    # collection by forking again. Require a stable stopped set before killing.
    previous=None
    for attempt in range(32):
        found=set()
        for path in Path('/proc').iterdir():
            if path.name.isdecimal():
                try:
                    if path.stat().st_uid==UID:
                        pid=int(path.name);os.kill(pid,signal.SIGSTOP);found.add(pid)
                except (ProcessLookupError,FileNotFoundError,PermissionError):pass
        if found==previous:
            for pid in found:
                try:os.kill(pid,signal.SIGKILL)
                except ProcessLookupError:pass
            return
        previous=found
    raise RuntimeError('guest_process_cleanup_unverified')


def main():
    if os.environ.get('KILAS_REMOTE_GUEST')!='e2b-ephemeral-v1':raise RuntimeError('remote_guest_only')
    assert os.getuid()==0
    disk=os.statvfs('/')
    if disk.f_blocks*disk.f_frsize>10*1024**3:raise RuntimeError('sandbox_disk_limit_unverified')
    payload=json.loads(Path('/root/kilas-input.json').read_text())
    ROOT.mkdir(mode=0o700);os.chown(ROOT,UID,UID)
    disk=os.statvfs(ROOT)
    if disk.f_blocks*disk.f_frsize>10*1024**3:raise RuntimeError('sandbox_disk_limit_unverified')
    for name,text in payload['files'].items():
        target=ROOT/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
    (ROOT/'output').mkdir(exist_ok=True);(ROOT/'tmp').mkdir(exist_ok=True)
    for directory,dirs,files in os.walk(ROOT):
        os.chown(directory,UID,UID)
        for name in files:os.chown(Path(directory)/name,UID,UID)
    entry=payload['entrypoint']
    args=['/usr/bin/python3','-B','-E','-s']+(['-m','unittest','discover','-s','tests'] if entry=='unittest' else [entry])
    env={'PATH':'/usr/bin:/bin','HOME':str(ROOT),'TMPDIR':str(ROOT/'tmp'),'LANG':'C.UTF-8'}
    timed_out=False
    with open('/root/kilas-stdout','w+b') as stdout,open('/root/kilas-stderr','w+b') as stderr:
        process=subprocess.Popen(args,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                                 start_new_session=True,preexec_fn=child_limits)
        deadline=time.monotonic()+20
        try:
            while process.poll() is None:
                size=0;count=0
                for directory,dirs,files in os.walk(ROOT,followlinks=False):
                    count+=len(dirs)
                    if count>4096 or time.monotonic()>deadline:break
                    for name in files:
                        try:size+=(Path(directory)/name).lstat().st_size;count+=1
                        except FileNotFoundError:pass
                        if size>64*1024**2 or count>4096:break
                    if size>64*1024**2 or count>4096:break
                if time.monotonic()>deadline or size>64*1024**2 or count>4096:
                    timed_out=True;break
                time.sleep(.05)
        finally:
            kill_children();process.wait(timeout=2)
        stdout.seek(0);stderr.seek(0)
        report={'exit_code':process.returncode,'stdout':stdout.read(65536).decode(errors='replace').encode()[:65536].decode(errors='ignore'),
                'stderr':stderr.read(65536).decode(errors='replace').encode()[:65536].decode(errors='ignore'),'timed_out':timed_out,'outputs':{}}
    total=0;output=ROOT/'output'
    if output.is_symlink():raise ValueError('unsafe_output')
    for path in output.iterdir():
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=UID or info.st_nlink!=1 or info.st_size>65536 or len(report['outputs'])>=8:raise ValueError('unsafe_output')
        total+=info.st_size
        if total>262144:raise ValueError('output_limit')
        with path.open('rb') as file:data=file.read(65537)
        if len(data)>65536:raise ValueError('output_limit')
        report['outputs'][path.name]=base64.b64encode(data).decode()
    Path('/root/kilas-done.json').write_text(json.dumps(report,ensure_ascii=False))


def run():
    # An early trusted-runner error must produce a bounded terminal report too.
    # Otherwise the host sees only a later timeout and loses the actual phase.
    if os.environ.get('KILAS_REMOTE_GUEST')!='e2b-ephemeral-v1' or os.getuid()!=0:
        raise RuntimeError('remote_guest_only')
    try:
        main()
    except Exception as error:
        allowed={'sandbox_disk_limit_unverified','guest_process_cleanup_unverified',
                 'unsafe_output','output_limit'}
        code=str(error) if str(error) in allowed else 'guest_runner_error'
        # Do not echo exception messages, paths, source, environment or secrets.
        Path('/root/kilas-done.json').write_text(json.dumps({'exit_code':1,
            'stdout':'','stderr':'KILAS_GUEST_FAILURE:'+code,'timed_out':False,'outputs':{}}))


if __name__=='__main__':run()
