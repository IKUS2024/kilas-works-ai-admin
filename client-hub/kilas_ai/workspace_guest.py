"""Trusted runner uploaded to a fresh remote E2B microVM; NEVER run on web host."""
import base64
import ctypes
from contextlib import contextmanager
import json
import os
from pathlib import Path
import resource
import selectors
import signal
import stat
import subprocess
import time

ROOT=Path('/tmp/kilas-run')
UID=65534
SCRATCH_BYTES=64*1024**2
SCRATCH_INODES=4096
EVIDENCE={}
BOUNDARY_FD=None
PARENT_NAMESPACES={}
FAILURES={'sandbox_disk_limit_unverified','guest_process_cleanup_unverified','unsafe_output','output_limit',
    'guest_arch_unsupported','guest_swap_unverified','scratch_mount_unavailable','scratch_quota_unverified',
    'child_namespace_unavailable','child_mount_private_failed','child_readonly_unavailable',
    'scratch_write_mount_failed','child_writable_mount_unverified','child_capabilities_unverified',
    'no_new_privs_failed','child_seccomp_unavailable','child_setup_unverified','mount_evidence_limit','guest_launch_error',
    'dedicated_uid_unavailable'}


def capacity(label,path):
    disk=os.statvfs(path)
    EVIDENCE[label]={'total_bytes':disk.f_blocks*disk.f_frsize,
        'available_bytes':disk.f_bavail*disk.f_frsize,'total_inodes':disk.f_files,
        'readonly':bool(disk.f_flag&os.ST_RDONLY)}
    return EVIDENCE[label]


def mount_rows(text):
    rows=[]
    if len(text.encode())>65536:raise RuntimeError('mount_evidence_limit')
    for line in text.splitlines():
        fields=line.split();sep=fields.index('-')
        rows.append((fields[4],set(fields[5].split(',')),fields[sep+1]))
    return rows


def libc_call(result,code):
    if result!=0:raise RuntimeError(code)


class MountAttr(ctypes.Structure):
    _fields_=[('attr_set',ctypes.c_uint64),('attr_clr',ctypes.c_uint64),
              ('propagation',ctypes.c_uint64),('userns_fd',ctypes.c_uint64)]


class SockFilter(ctypes.Structure):
    _fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint32)]


class SockFprog(ctypes.Structure):
    _fields_=[('len',ctypes.c_ushort),('filter',ctypes.POINTER(SockFilter))]


def syscall_filter():
    # x86-64 only; reject alternate audit architectures and x32 syscall numbers.
    # clone3 is ENOSYS so libc can use filtered clone for ordinary threads.
    instructions=[(0x20,0,0,4),(0x15,1,0,0xc000003e),(0x06,0,0,0x80000000),
        (0x20,0,0,0),(0x35,0,1,0x40000000),(0x06,0,0,0x80000000),
        (0x15,0,1,435),(0x06,0,0,0x00050000|38),
        (0x15,0,3,56),(0x20,0,0,16),(0x45,0,1,0x7e020080),
        (0x06,0,0,0x00050000|1),(0x20,0,0,0)]
    # No new namespace, mount, socket/IPC transport or asynchronous I/O bypass.
    for number in (41,53,155,161,165,166,272,308,425,426,427,428,429,430,431,432,442):
        instructions.extend(((0x15,0,1,number),(0x06,0,0,0x00050000|1)))
    instructions.append((0x06,0,0,0x7fff0000))
    return instructions


def prepare_scratch():
    if os.uname().machine!='x86_64':raise RuntimeError('guest_arch_unsupported')
    capacity('root','/')  # Diagnostic only; root capacity is NOT tenant quota.
    rows=mount_rows(Path('/proc/self/mountinfo').read_text())
    root_types=[fs for path,_,fs in rows if path=='/']
    EVIDENCE['root']['filesystem']=root_types[0] if root_types and root_types[0] in ('ext4','xfs','overlay','tmpfs') else 'other'
    if len(Path('/proc/swaps').read_text().splitlines())!=1:raise RuntimeError('guest_swap_unverified')
    for path in Path('/proc').iterdir():
        if path.name.isdecimal():
            try:
                if path.stat().st_uid==UID:raise RuntimeError('dedicated_uid_unavailable')
            except (FileNotFoundError,ProcessLookupError):pass
    ROOT.mkdir(mode=0o700)
    libc=ctypes.CDLL(None,use_errno=True)
    libc_call(libc.mount(b'kilas-scratch',os.fsencode(ROOT),b'tmpfs',14,
        b'size=67108864,nr_inodes=4096,mode=0700'),'scratch_mount_unavailable')
    rows=mount_rows(Path('/proc/self/mountinfo').read_text())
    mounts=[r for r in rows if r[0]==str(ROOT)]
    info=capacity('scratch',ROOT)
    info['filesystem']=mounts[0][2] if mounts and mounts[0][2] in ('ext4','xfs','overlay','tmpfs') else 'other'
    if not (len(mounts)==1 and mounts[0][2]=='tmpfs' and
            {'rw','nosuid','nodev','noexec'}<=mounts[0][1] and
            0<info['total_bytes']<=SCRATCH_BYTES and 0<info['total_inodes']<=SCRATCH_INODES):
        raise RuntimeError('scratch_quota_unverified')
    os.chown(ROOT,UID,UID)


def confine_child():
    libc=ctypes.CDLL(None,use_errno=True)
    # Mount + IPC namespaces keep the trusted collector separate. All mounts
    # become read-only in the child, then ONLY the capped scratch becomes RW.
    libc_call(libc.unshare(0x00020000|0x08000000),'child_namespace_unavailable')
    libc_call(libc.mount(None,b'/',None,(1<<18)|16384,None),'child_mount_private_failed')
    attr=MountAttr(7,0,0,0)  # RDONLY | NOSUID | NODEV, including /dev mounts.
    libc_call(libc.syscall(442,-100,b'/',32768,ctypes.byref(attr),ctypes.sizeof(attr)),
              'child_readonly_unavailable')
    attr=MountAttr(0,1,0,0)
    libc_call(libc.syscall(442,-100,os.fsencode(ROOT),0,ctypes.byref(attr),ctypes.sizeof(attr)),
              'scratch_write_mount_failed')
    rows=mount_rows(Path('/proc/self/mountinfo').read_text())
    if not rows or any(not {'ro','nosuid','nodev'}<=opts and path!=str(ROOT) for path,opts,_ in rows):
        raise RuntimeError('child_writable_mount_unverified')
    if not any(path==str(ROOT) and fs=='tmpfs' and {'rw','nosuid','nodev','noexec'}<=opts for path,opts,fs in rows):
        raise RuntimeError('scratch_quota_unverified')
    # Root capabilities must not survive, including through exec or descendants.
    last=int(Path('/proc/sys/kernel/cap_last_cap').read_text())
    if not 0<=last<=63:raise RuntimeError('child_capabilities_unverified')
    libc_call(libc.prctl(8,0,0,0,0),'child_capabilities_unverified')  # KEEPCAPS
    for cap in range(last+1):libc_call(libc.prctl(24,cap,0,0,0),'child_capabilities_unverified')
    os.setgroups([]);os.setresgid(UID,UID,UID);os.setresuid(UID,UID,UID)
    # Explicitly clear inheritable and ambient capability state as well.
    header=(ctypes.c_uint32*2)(0x20080522,0);data=(ctypes.c_uint32*6)()
    libc_call(libc.capset(ctypes.byref(header),ctypes.byref(data)),'child_capabilities_unverified')
    status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    if any(int(status[name].strip(),16) for name in ('CapInh','CapPrm','CapEff','CapBnd','CapAmb')):
        raise RuntimeError('child_capabilities_unverified')
    libc_call(libc.prctl(38,1,0,0,0),'no_new_privs_failed')
    instructions=syscall_filter();program=(SockFilter*len(instructions))(*(SockFilter(*x) for x in instructions))
    descriptor=SockFprog(len(instructions),program)
    libc_call(libc.prctl(22,2,ctypes.byref(descriptor),0,0),'child_seccomp_unavailable')


def process_limits():
    for name,value in (('RLIMIT_CPU',10),('RLIMIT_AS',256*1024*1024),('RLIMIT_FSIZE',65536),
                       ('RLIMIT_NPROC',16),('RLIMIT_NOFILE',32),('RLIMIT_CORE',0)):
        resource.setrlimit(getattr(resource,name),(value,value))


def child_limits():
    try:
        confine_child();process_limits()
        libc=ctypes.CDLL(None,use_errno=True)
        if libc.prctl(21,0,0,0,0)!=2 or libc.prctl(39,0,0,0,0)!=1:raise RuntimeError('child_setup_unverified')
        if any(os.readlink('/proc/self/ns/'+name)==value for name,value in PARENT_NAMESPACES.items()):
            raise RuntimeError('child_namespace_unavailable')
        evidence={'ready':True,'root_readonly':bool(os.statvfs('/').f_flag&os.ST_RDONLY),
            'scratch_writable':not bool(os.statvfs(ROOT).f_flag&os.ST_RDONLY),
            'mount_namespace_private':True,'ipc_namespace_private':True,'capabilities_zero':True,
            'seccomp':2,'no_new_privs':True,'scratch_bytes':SCRATCH_BYTES,'scratch_inodes':SCRATCH_INODES}
        if not evidence['root_readonly'] or not evidence['scratch_writable']:raise RuntimeError('child_setup_unverified')
        os.write(BOUNDARY_FD,json.dumps(evidence).encode());os.close(BOUNDARY_FD)
    except Exception as error:
        code=str(error) if str(error) in FAILURES else 'child_setup_unverified'
        os.write(BOUNDARY_FD,json.dumps({'ready':False,'error':code}).encode());os.close(BOUNDARY_FD)
        raise


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


@contextmanager
def readonly_stdin():
    # Popen.DEVNULL uses O_RDWR, which violates the reviewed inherited-FD
    # boundary even though /dev/null itself cannot store files. Supply an
    # explicitly read-only, close-on-exec descriptor; dup2 makes only fd0 live.
    descriptor=os.open(os.devnull,os.O_RDONLY|os.O_CLOEXEC)
    try:yield descriptor
    finally:os.close(descriptor)


def main():
    global BOUNDARY_FD,PARENT_NAMESPACES
    if os.environ.get('KILAS_REMOTE_GUEST')!='e2b-ephemeral-v1':raise RuntimeError('remote_guest_only')
    assert os.getuid()==0
    payload=json.loads(Path('/root/kilas-input.json').read_text())
    prepare_scratch()
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
    PARENT_NAMESPACES={name:os.readlink('/proc/self/ns/'+name) for name in ('mnt','ipc')}
    setup_read,BOUNDARY_FD=os.pipe2(os.O_CLOEXEC)
    process=None;launch_error=False
    try:
        with readonly_stdin() as input_fd:
            process=subprocess.Popen(args,cwd=ROOT,env=env,stdin=input_fd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                     start_new_session=True,preexec_fn=child_limits,close_fds=True,pass_fds=(BOUNDARY_FD,))
    except Exception:launch_error=True
    finally:
        os.close(BOUNDARY_FD)
        setup=os.read(setup_read,4097);os.close(setup_read)
        try:
            if len(setup)>4096:raise ValueError()
            EVIDENCE['child']=json.loads(setup)
        except (ValueError,TypeError):EVIDENCE['child']={'ready':False,'error':'child_setup_unverified'}
    if not EVIDENCE['child'].get('ready'):raise RuntimeError(EVIDENCE['child'].get('error','child_setup_unverified'))
    if launch_error:raise RuntimeError('guest_launch_error')
    with selectors.DefaultSelector() as selector:
        logs={'stdout':bytearray(),'stderr':bytearray()}
        for name in logs:
            pipe=getattr(process,name);os.set_blocking(pipe.fileno(),False);selector.register(pipe,selectors.EVENT_READ,name)
        deadline=time.monotonic()+20
        try:
            while process.poll() is None or selector.get_map():
                for key,_ in selector.select(.05):
                    chunk=os.read(key.fileobj.fileno(),8192)
                    if not chunk:selector.unregister(key.fileobj);continue
                    log=logs[key.data]
                    if len(chunk)>65536-len(log):timed_out=True;break
                    log.extend(chunk)
                if timed_out:break
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
        process.stdout.close();process.stderr.close()
        report={'exit_code':process.returncode,'stdout':bytes(logs['stdout']).decode(errors='replace').encode()[:65536].decode(errors='ignore'),
                'stderr':bytes(logs['stderr']).decode(errors='replace').encode()[:65536].decode(errors='ignore'),'timed_out':timed_out,'outputs':{},'evidence':EVIDENCE}
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
    write_report(report)


def write_report(report):
    raw=json.dumps(report,ensure_ascii=False)
    if len(raw.encode())>512*1024:
        raw=json.dumps({'exit_code':1,'stdout':'','stderr':'KILAS_GUEST_FAILURE:output_limit',
                        'timed_out':False,'outputs':{},'evidence':EVIDENCE})
    Path('/root/kilas-done.json').write_text(raw)


def run():
    # An early trusted-runner error must produce a bounded terminal report too.
    # Otherwise the host sees only a later timeout and loses the actual phase.
    if os.environ.get('KILAS_REMOTE_GUEST')!='e2b-ephemeral-v1' or os.getuid()!=0:
        raise RuntimeError('remote_guest_only')
    EVIDENCE.clear()
    try:
        main()
    except Exception as error:
        code=str(error) if str(error) in FAILURES else 'guest_runner_error'
        # Do not echo exception messages, paths, source, environment or secrets.
        write_report({'exit_code':1,'stdout':'','stderr':'KILAS_GUEST_FAILURE:'+code,'timed_out':False,'outputs':{},'evidence':EVIDENCE})


if __name__=='__main__':run()
