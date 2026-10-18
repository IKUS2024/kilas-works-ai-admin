"""Local synthetic quota algorithm tests. No privileged/main/SDK execution."""
import ast
import errno
import inspect
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from kilas_ai import workspace_acceptance_fixture as fixture


class AcceptanceFixtureTests(unittest.TestCase):
    def quota(self,kind,available,fail_errno=errno.ENOSPC):
        folder=Mock();folder.__truediv__=Mock(side_effect=lambda i:Mock())
        before=SimpleNamespace(f_bavail=available,f_frsize=1,f_favail=available)
        after=SimpleNamespace(f_bavail=0,f_favail=0)
        state={'left':available}
        def open_file(*args):
            if kind=='inode':
                if not state['left']:raise OSError(fail_errno,'synthetic')
                state['left']-=1
            return 7
        def write(fd,data):
            if not state['left']:raise OSError(fail_errno,'synthetic')
            size=min(state['left'],len(data));state['left']-=size;return size
        with patch.object(fixture.os,'statvfs',side_effect=[before,after]),patch.object(fixture.os,'open',side_effect=open_file),patch.object(fixture.os,'write',side_effect=write),patch.object(fixture.os,'close'):
            result=fixture.fill_quota(folder,kind)
        folder.rmdir.assert_called_once();return result

    def test_aggregate_data_hits_enospc_after_partial_chunk_without_fsize_violation(self):
        result=self.quota('data',70000)
        self.assertEqual(result,{'written_bytes':70000,'requested_bytes':131072,'available_before':70000,'errno':errno.ENOSPC})

    def test_empty_file_inode_exhaustion_requires_actual_reported_zero_remaining(self):
        self.assertEqual(self.quota('inode',7),{'created_files':7,'available_before':7,'errno':errno.ENOSPC})

    def test_wrong_error_cannot_be_misrepresented_as_aggregate_quota(self):
        for kind in ('data','inode'):
            with self.assertRaises(OSError) as denied:self.quota(kind,7,errno.EFBIG)
            self.assertEqual(denied.exception.errno,errno.EFBIG)

    def test_inert_source_is_syntax_valid_bounded_and_not_a_new_proof_dispatch(self):
        source=inspect.getsource(fixture);ast.parse(source)
        self.assertIn('BYTES//CHUNK+1',source);self.assertIn('INODES+1',source)
        self.assertEqual(fixture.BYTES,67108864);self.assertEqual(fixture.INODES,4096)
        self.assertLess(len(source.encode()),20000)
        self.assertNotIn('Sandbox.create',source)
        from kilas_ai import workspace_execution_proof as proof,workspace_execution as execution
        self.assertEqual(proof.key(),'diagnostic-proof-v1')
        self.assertNotIn('workspace_acceptance_fixture',inspect.getsource(proof))
        self.assertNotIn('workspace_acceptance_fixture',inspect.getsource(execution))

    def test_outside_write_accepts_only_kernel_denial(self):
        for code in (errno.EACCES,errno.EROFS,errno.EPERM):
            with patch.object(fixture.os,'open',side_effect=OSError(code,'synthetic')):fixture.denied_write('/fixed')
        with patch.object(fixture.os,'open',side_effect=OSError(errno.ENOENT,'synthetic')):
            with self.assertRaises(AssertionError):fixture.denied_write('/fixed')
        with patch.object(fixture.os,'open',return_value=7),patch.object(fixture.os,'close'),patch.object(fixture.os,'unlink'):
            with self.assertRaisesRegex(AssertionError,'outside_write_allowed'):fixture.denied_write('/fixed')

    def test_real_scale_aggregate_algorithms_have_bounded_work(self):
        data=self.quota('data',fixture.BYTES-12288)
        self.assertEqual(data['written_bytes'],fixture.BYTES-12288)
        self.assertLessEqual(data['requested_bytes'],fixture.BYTES+fixture.CHUNK)
        self.assertEqual(self.quota('inode',fixture.INODES-6)['created_files'],fixture.INODES-6)

    def test_reaped_descendant_pid_is_never_signalled_again(self):
        with patch.object(fixture.os,'fork',return_value=123),patch.object(fixture.os,'waitpid',return_value=(123,0)),patch.object(fixture.os,'kill') as kill:
            fixture.child_probe(lambda:None)
        kill.assert_not_called()
