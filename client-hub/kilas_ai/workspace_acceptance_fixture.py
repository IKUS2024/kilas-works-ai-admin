"""INERT fixed remote acceptance proposal. Not imported by startup or execution.

Only main() in an explicitly approved remote VM may run the adversarial checks.
Local tests exercise bounded quota algorithms against a synthetic filesystem.
"""
import ctypes
import errno
import fcntl
import json
import os
from pathlib import Path
import resource
import signal
import stat
import time
import urllib.request
import urllib.error

BYTES=67108864
INODES=4096
CHUNK=65536
CHECKS=['identity','environment','descriptors','outside_writes','syscalls',
        'network','descendant','memory_limit','file_limit','cpu_limit','data_enospc','inode_enospc','answer']


def fill_quota(folder,kind):
    """Attempt actual aggregate overflow, not just an attested/per-file limit.

    Files are <=64KiB, so a data failure must be ENOSPC rather than RLIMIT_FSIZE.
    Inodes use empty files after data-test cleanup. Every loop has a fixed bound.
    """
    assert kind in ('data','inode')
    folder.mkdir();created=[];written=0;requested=0;full=False
    before=os.statvfs(folder)
    available=before.f_bavail*before.f_frsize if kind=='data' else before.f_favail
    maximum=BYTES//CHUNK+1 if kind=='data' else INODES+1
    try:
        for index in range(maximum):
            path=folder/str(index);fd=None
            try:
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);created.append(path)
                if kind=='data':
                    requested+=CHUNK;remaining=CHUNK
                    while remaining:
                        count=os.write(fd,b'x'*remaining)
                        assert 0<count<=remaining
                        remaining-=count;written+=count
            except OSError as error:
                if error.errno!=errno.ENOSPC:raise
                full=True;break
            finally:
                if fd is not None:os.close(fd)
        after=os.statvfs(folder)
        assert full, 'no_enforced_quota'
        if kind=='data':
            assert 0<written<=BYTES and requested>available and after.f_bavail==0
            return {'written_bytes':written,'requested_bytes':requested,'available_before':available,'errno':errno.ENOSPC}
        assert 0<len(created)<=INODES and len(created)==available and after.f_favail==0
        return {'created_files':len(created),'available_before':available,'errno':errno.ENOSPC}
    finally:
        for path in created:path.unlink()
        folder.rmdir()


def denied_write(path):
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except OSError as error:
        assert error.errno in (errno.EROFS,errno.EACCES,errno.EPERM)
        return
    os.close(fd)
    try:os.unlink(path)
    finally:raise AssertionError('outside_write_allowed')


def child_probe(action,expected_signal=None):
    pid=os.fork()
    if pid==0:
        try:action()
        except BaseException:os._exit(1)
        os._exit(0)
    until=time.monotonic()+3;reaped=False
    try:
        while time.monotonic()<until:
            finished,status=os.waitpid(pid,os.WNOHANG)
            if finished:
                reaped=True
                assert (os.WIFSIGNALED(status) and os.WTERMSIG(status)==expected_signal) if expected_signal else (os.WIFEXITED(status) and os.WEXITSTATUS(status)==0)
                return
            time.sleep(.01)
        raise AssertionError('child_deadline')
    finally:
        if not reaped:
            try:os.kill(pid,signal.SIGKILL);os.waitpid(pid,0)
            except ProcessLookupError:pass
            except ChildProcessError:pass


def identity():
    assert os.getresuid()==(65534,65534,65534) and os.getresgid()==(65534,65534,65534)
    status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    assert all(int(status[k].strip(),16)==0 for k in ('CapInh','CapPrm','CapEff','CapBnd','CapAmb'))
    assert int(status['NoNewPrivs'])==1 and int(status['Seccomp'])==2
    assert os.statvfs('/').f_flag&os.ST_RDONLY
    try:os.setuid(0)
    except PermissionError:pass
    else:raise AssertionError('uid_escalation')
    try:Path('/root/kilas-input.json').read_bytes()
    except PermissionError:pass
    else:raise AssertionError('private_root_readable')


def main():
    # This fixture must never act as a host-side execution alternative.
    assert os.getuid()==65534 and Path.cwd()==Path('/tmp/kilas-run')
    stage='identity';passed=[];evidence={}
    try:
        identity();passed.append(stage)
        stage='environment'
        assert set(os.environ)<= {'PATH','HOME','TMPDIR','LANG','LC_CTYPE'}
        assert os.environ['HOME']==str(Path.cwd()) and os.environ['TMPDIR']==str(Path.cwd()/'tmp')
        passed.append(stage)
        stage='descriptors'
        assert fcntl.fcntl(0,fcntl.F_GETFL)&os.O_ACCMODE==os.O_RDONLY
        assert all(stat.S_ISFIFO(os.fstat(fd).st_mode) for fd in (1,2))
        for value in os.listdir('/proc/self/fd'):
            fd=int(value)
            if fd<3:continue
            try:flags=fcntl.fcntl(fd,fcntl.F_GETFL)
            except OSError as error:
                assert error.errno==errno.EBADF;continue
            assert flags&os.O_ACCMODE==os.O_RDONLY
        passed.append(stage)
        stage='outside_writes'
        for folder in ('/tmp','/var/tmp','/run','/dev/shm'):
            denied_write(folder+'/kilas-fixed-acceptance')
        alias=Path('outside-alias');alias.symlink_to('/tmp')
        try:denied_write(alias/'kilas-fixed-acceptance')
        finally:alias.unlink()
        fd=os.open('/tmp',os.O_RDONLY|os.O_DIRECTORY)
        try:denied_write(f'/proc/self/fd/{fd}/kilas-fixed-acceptance')
        finally:os.close(fd)
        passed.append(stage)
        stage='syscalls';libc=ctypes.CDLL(None,use_errno=True)
        for number in (41,53,155,161,165,166,272,308,425,426,427,428,429,430,431,432,442):
            ctypes.set_errno(0)
            assert libc.syscall(number,0,0,0,0,0,0)==-1 and ctypes.get_errno()==errno.EPERM
        assert libc.syscall(435,0,0)==-1 and ctypes.get_errno()==errno.ENOSYS
        child_probe(lambda:libc.syscall(0x40000000,0,0,0),signal.SIGSYS)
        passed.append(stage)
        stage='network'
        try:
            response=urllib.request.urlopen('https://example.com',timeout=1)
            response.read(1)
        except urllib.error.HTTPError:raise AssertionError('unexpected_http_response')
        except (OSError,TimeoutError):pass
        else:raise AssertionError('unexpected_network_response')
        passed.append(stage)
        stage='descendant'
        def descendant():
            identity();denied_write('/tmp/kilas-descendant-acceptance')
            assert resource.getrlimit(resource.RLIMIT_NPROC)==(16,16)
            assert resource.getrlimit(resource.RLIMIT_AS)==(268435456,268435456)
        child_probe(descendant);passed.append(stage)
        stage='memory_limit'
        def memory():
            try:bytearray(300*1024**2)
            except MemoryError:return
            raise AssertionError('memory_limit_not_enforced')
        child_probe(memory);passed.append(stage)
        stage='file_limit'
        def file_limit():
            signal.signal(signal.SIGXFSZ,signal.SIG_IGN)
            with open('file-limit','wb',buffering=0) as target:
                target.write(b'x'*65536)
                try:target.write(b'x')
                except OSError as error:
                    assert error.errno==errno.EFBIG;return
                raise AssertionError('file_limit_not_enforced')
        try:child_probe(file_limit)
        finally:Path('file-limit').unlink(missing_ok=True)
        passed.append(stage)
        stage='cpu_limit'
        assert resource.getrlimit(resource.RLIMIT_CPU)==(10,10)
        def cpu():
            resource.setrlimit(resource.RLIMIT_CPU,(1,1))
            while True:pass
        child_probe(cpu,signal.SIGKILL);passed.append(stage)
        disk=os.statvfs('.')
        assert disk.f_blocks*disk.f_frsize==BYTES and disk.f_files==INODES
        assert not disk.f_flag&os.ST_RDONLY
        stage='data_enospc';evidence['data']=fill_quota(Path('data-quota'),'data');passed.append(stage)
        stage='inode_enospc';evidence['inodes']=fill_quota(Path('inode-quota'),'inode');passed.append(stage)
        stage='answer';Path('output/answer.txt').write_text('42\n');passed.append(stage)
        Path('output/proof.json').write_text(json.dumps({'answer':42,'checks':passed,'evidence':evidence}))
        print('KILAS_ACCEPTANCE_OK')
    except BaseException:
        # Only fixed phase and bounded numeric evidence; never arbitrary errors.
        Path('output/proof.json').write_text(json.dumps({'failed_stage':stage,'checks':passed,'evidence':evidence}))
        os.write(2,('KILAS_ACCEPTANCE_FAILURE:'+stage).encode())
        raise SystemExit(1)


if __name__=='__main__':main()
