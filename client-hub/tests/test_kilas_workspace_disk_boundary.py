"""Pure/synthetic contracts. No privileged syscall, generated code or VM runs."""
import copy
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from test_kilas_workspace_execution import BOUNDARY
from kilas_ai import workspace_guest as guest,workspace_execution as execution


def mountinfo(writable=None,filesystem='tmpfs'):
    paths=['/','/proc','/proc/sys','/sys','/dev','/dev/shm','/run','/proc/fd-alias']
    lines=[f'{i+1} 0 0:1 / {path} {"rw" if path==writable else "ro"},nosuid,nodev - ext4 none ro' for i,path in enumerate(paths)]
    lines.append(f'20 0 0:2 / {guest.ROOT} rw,nosuid,nodev,noexec - {filesystem} kilas-scratch rw,size=65536k,nr_inodes=4096')
    return '\n'.join(lines)


def bpf_result(number,flags=0,architecture=0xc000003e):
    program=guest.syscall_filter();pc=0;acc=0
    while pc<len(program):
        code,jt,jf,value=program[pc]
        if code==0x20:acc={0:number,4:architecture,16:flags}[value]
        elif code==0x15:pc+=jt if acc==value else jf
        elif code==0x35:pc+=jt if acc>=value else jf
        elif code==0x45:pc+=jt if acc&value else jf
        elif code==0x06:return value
        else:raise AssertionError('unexpected BPF instruction')
        pc+=1
    raise AssertionError('missing terminal BPF action')


class BoundaryTests(unittest.TestCase):
    def setUp(self):guest.EVIDENCE.clear()

    def scratch(self,*,size=67108864,inodes=4096,filesystem='tmpfs',swap=False,mount_result=0):
        stack=ExitStack();self.addCleanup(stack.close)
        folder=stack.enter_context(tempfile.TemporaryDirectory())
        stack.enter_context(patch.object(guest,'ROOT',Path(folder)/'scratch'))
        stack.enter_context(patch.object(guest.os,'uname',return_value=SimpleNamespace(machine='x86_64')))
        stack.enter_context(patch.object(guest.os,'chown'))
        stack.enter_context(patch.object(guest.Path,'iterdir',return_value=iter([])))
        disk=lambda path:SimpleNamespace(f_blocks=100*1024**3 if str(path)=='/' else size,f_frsize=1,f_bavail=0,f_files=100000 if str(path)=='/' else inodes,f_flag=0)
        stack.enter_context(patch.object(guest.os,'statvfs',side_effect=disk))
        def read(path,*args,**kwargs):
            if str(path)=='/proc/swaps':return 'Filename Type Size Used Priority\n'+('/swap file 10 0 0\n' if swap else '')
            if str(path)=='/proc/self/mountinfo':return mountinfo(filesystem=filesystem)
            raise AssertionError('unexpected path')
        stack.enter_context(patch.object(guest.Path,'read_text',read))
        libc=Mock();libc.mount.return_value=mount_result
        stack.enter_context(patch.object(guest.ctypes,'CDLL',return_value=libc))
        return libc

    def test_large_root_total_is_diagnostic_while_independent_scratch_is_bounded(self):
        libc=self.scratch();guest.prepare_scratch()
        self.assertEqual(guest.EVIDENCE['root']['total_bytes'],100*1024**3)
        self.assertEqual(guest.EVIDENCE['scratch']['total_bytes'],67108864)
        self.assertEqual(guest.EVIDENCE['scratch']['total_inodes'],4096)
        self.assertEqual(libc.mount.call_args.args[2],b'tmpfs')
        self.assertEqual(libc.mount.call_args.args[3],14)
        self.assertIn(b'nr_inodes=4096',libc.mount.call_args.args[4])

    def test_scratch_rejects_oversize_inodes_wrong_fs_and_swap(self):
        for options,reason in [({'size':67108865},'scratch_quota_unverified'),({'inodes':4097},'scratch_quota_unverified'),({'filesystem':'ext4'},'scratch_quota_unverified'),({'swap':True},'guest_swap_unverified'),({'mount_result':-1},'scratch_mount_unavailable')]:
            with self.subTest(options=options):
                self.scratch(**options)
                with self.assertRaisesRegex(RuntimeError,reason):guest.prepare_scratch()

    def test_mount_table_is_bounded_and_never_persisted_verbatim(self):
        with self.assertRaisesRegex(RuntimeError,'mount_evidence_limit'):guest.mount_rows('x'*65537)
        value=copy.deepcopy(BOUNDARY);value['root']['host_path']='/private/provider/path'
        with self.assertRaisesRegex(ValueError,'invalid_boundary_evidence'):execution.validated_evidence(value,False)

    def child(self,*,writable=None,syscall_result=0,capability=0):
        stack=ExitStack();self.addCleanup(stack.close)
        libc=Mock();libc.unshare.return_value=0;libc.mount.return_value=0;libc.syscall.return_value=syscall_result;libc.prctl.return_value=0;libc.capset.return_value=0
        stack.enter_context(patch.object(guest.ctypes,'CDLL',return_value=libc))
        def read(path,*args,**kwargs):
            if str(path)=='/proc/self/mountinfo':return mountinfo(writable=writable)
            if str(path)=='/proc/sys/kernel/cap_last_cap':return '40'
            if str(path)=='/proc/self/status':return '\n'.join(f'{key}: {capability:x}' for key in ('CapInh','CapPrm','CapEff','CapBnd','CapAmb'))
            raise AssertionError('unexpected path')
        stack.enter_context(patch.object(guest.Path,'read_text',read))
        groups=stack.enter_context(patch.object(guest.os,'setgroups'))
        gid=stack.enter_context(patch.object(guest.os,'setresgid'))
        uid=stack.enter_context(patch.object(guest.os,'setresuid'))
        return libc,groups,gid,uid

    def test_child_readonly_tree_clears_only_scratch_and_drops_all_ids_caps(self):
        libc,groups,gid,uid=self.child();guest.confine_child()
        libc.unshare.assert_called_once_with(0x08020000)
        calls=libc.syscall.call_args_list
        self.assertEqual(calls[0].args[:4],(442,-100,b'/',32768))
        self.assertEqual(calls[0].args[4]._obj.attr_set,7)
        self.assertEqual(calls[1].args[2],bytes(str(guest.ROOT),'utf8'))
        self.assertEqual(calls[1].args[4]._obj.attr_clr,1)
        groups.assert_called_once_with([]);gid.assert_called_once_with(65534,65534,65534);uid.assert_called_once_with(65534,65534,65534)
        self.assertEqual(sum(c.args[0]==24 for c in libc.prctl.call_args_list),41)
        self.assertEqual(libc.prctl.call_args_list[-1].args[0:2],(22,2))

    def test_every_other_writable_mount_including_aliases_fails_before_user_ids(self):
        for path in ('/','/proc','/proc/sys','/sys','/dev','/dev/shm','/run','/proc/fd-alias'):
            with self.subTest(path=path):
                _,_,_,uid=self.child(writable=path)
                with self.assertRaisesRegex(RuntimeError,'child_writable_mount_unverified'):guest.confine_child()
                uid.assert_not_called()

    def test_unsupported_kernel_or_surviving_capability_fails_closed(self):
        self.child(syscall_result=-1)
        with self.assertRaisesRegex(RuntimeError,'child_readonly_unavailable'):guest.confine_child()
        self.child(capability=1)
        with self.assertRaisesRegex(RuntimeError,'child_capabilities_unverified'):guest.confine_child()

    def test_filter_rejects_mount_namespace_network_async_bypasses_and_x32(self):
        for number in (41,53,155,161,165,166,272,308,425,426,427,428,429,430,431,432,442):
            with self.subTest(number=number):self.assertEqual(bpf_result(number),0x00050001)
        self.assertEqual(bpf_result(435),0x00050026)
        self.assertEqual(bpf_result(0x40000000),0x80000000)
        self.assertEqual(bpf_result(1,architecture=0x40000003),0x80000000)
        for flag in (0x80,0x20000,0x02000000,0x04000000,0x08000000,0x10000000,0x20000000,0x40000000):
            self.assertEqual(bpf_result(56,flags=flag),0x00050001)
        for number in (0,1,3,9,12,57,58,59,60):self.assertEqual(bpf_result(number),0x7fff0000)
        self.assertEqual(bpf_result(56,flags=0x00010f00),0x7fff0000)

    def test_success_requires_every_attestation_not_just_filesystem_size(self):
        self.assertEqual(execution.validated_evidence(copy.deepcopy(BOUNDARY),True),BOUNDARY)
        for section,key,value in [('child','root_readonly',False),('child','capabilities_zero',False),('child','ipc_namespace_private',False),('child','seccomp',0),('scratch','total_bytes',67108865),('scratch','total_inodes',4097),('scratch','filesystem','ext4')]:
            evidence=copy.deepcopy(BOUNDARY);evidence[section][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):execution.validated_evidence(evidence,True)
        with self.assertRaises(ValueError):execution.validated_evidence({},True)

    def test_diagnostics_reject_arbitrary_paths_messages_and_wrong_types(self):
        for evidence in ({'mountinfo':'secret'}, {'child':{'ready':False,'error':'secret'}}, {'child':[]}, {'scratch':{'total_bytes':True}}):
            with self.assertRaises(ValueError):execution.validated_evidence(evidence,False)
        self.assertEqual(execution.validated_evidence({'child':{'ready':False,'error':'child_readonly_unavailable'}},False)['child']['ready'],False)

    def test_unsupported_setup_cannot_reach_user_process(self):
        with patch.dict(guest.os.environ,{'KILAS_REMOTE_GUEST':'e2b-ephemeral-v1'}),patch.object(guest.os,'getuid',return_value=0),patch.object(guest.Path,'read_text',return_value='{"files":{},"entrypoint":"main.py"}'),patch.object(guest,'prepare_scratch',side_effect=RuntimeError('scratch_mount_unavailable')),patch.object(guest.subprocess,'Popen') as process,patch.object(guest,'write_report') as report:
            guest.run()
        process.assert_not_called();self.assertEqual(report.call_args.args[0]['stderr'],'KILAS_GUEST_FAILURE:scratch_mount_unavailable')

    def test_escaped_log_report_is_bounded_before_trusted_disk_write(self):
        report={'exit_code':0,'stdout':'\x01'*65536,'stderr':'\x01'*65536,'timed_out':False,'outputs':{},'evidence':{}}
        with patch.object(guest.Path,'write_text') as write:guest.write_report(report)
        raw=write.call_args.args[0];self.assertLess(len(raw.encode()),512*1024)
        self.assertEqual(json.loads(raw)['stderr'],'KILAS_GUEST_FAILURE:output_limit')

    def test_launch_uses_only_pipe_stdio_and_bounded_setup_handshake(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(guest,'ROOT',Path(folder)),patch.dict(guest.os.environ,{'KILAS_REMOTE_GUEST':'e2b-ephemeral-v1'}),patch.object(guest.os,'getuid',return_value=0),patch.object(guest.Path,'read_text',return_value='{"files":{},"entrypoint":"main.py"}'),patch.object(guest,'prepare_scratch'),patch.object(guest.os,'chown'),patch.object(guest.os,'readlink',return_value='parent-namespace'),patch.object(guest.os,'pipe2',return_value=(10,11)),patch.object(guest.os,'close'),patch.object(guest.os,'read',return_value=b'{"ready":false,"error":"child_readonly_unavailable"}') as read,patch.object(guest.subprocess,'Popen',side_effect=RuntimeError('synthetic setup failure')) as process:
            with self.assertRaisesRegex(RuntimeError,'child_readonly_unavailable'):guest.main()
        options=process.call_args.kwargs
        self.assertEqual(options['stdout'],guest.subprocess.PIPE);self.assertEqual(options['stderr'],guest.subprocess.PIPE)
        self.assertEqual(options['stdin'],guest.subprocess.DEVNULL);self.assertTrue(options['close_fds'])
        self.assertEqual(options['pass_fds'],(11,));read.assert_called_once_with(10,4097)


if __name__=='__main__':unittest.main()
