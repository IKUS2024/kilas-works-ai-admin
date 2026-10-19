"""Offline document acceptance contracts; all SDK and wheel-download calls are mocked."""
import ast
import copy
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_kilas_workspace_execution as fixture
import test_kilas_workspace_large_outputs as streams
import app
import db
from kilas_ai import autonomous_store as jobs, free_test, usage, work_artifacts
from kilas_ai import workspace_document_bundle as bundle, workspace_document_fixture as fixed
from kilas_ai import workspace_document_guest as guest, workspace_document_runtime as document
from kilas_ai import workspace_execution as base, workspace_execution_rollout as rollout
from kilas_ai import workspace_large_execution as execution, workspace_large_outputs as large
from kilas_ai import workspace_large_proof as old_proof, workspace_output_formats as formats


MEMORY = {'limit': 536870912, 'current': 104857600, 'peak': 209715200}
TEMPLATE = 'synthetic-document-base-v1'


def runtime_evidence():
    return {'abi': 'cp312', 'python': '3.12.9', 'manifest_sha256': bundle.manifest_digest(),
            'versions': {wheel['project'].lower().replace('_', '-'): wheel['version']
                         for wheel in bundle.describe('cp312')['wheels']},
            'root_owned': True, 'network_install': False, 'host_execution': False}


class DocumentRuntimeTests(unittest.TestCase):
    client = fixture.ExecutionTests.client

    @classmethod
    def setUpClass(cls):
        # Only the fixed document generator runs locally, never its adversarial main().
        cls.files = fixed.documents()

    def setUp(self):
        fixture.ExecutionTests.setUp(self)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(document, 'OWNER_ID', self.owner))
        self.stack.enter_context(patch.object(old_proof, 'OWNER_ID', self.owner))
        self.stack.enter_context(patch.object(large, 'host_memory', return_value=dict(MEMORY)))
        self.sdk = self.stack.enter_context(patch('e2b.Sandbox.create', side_effect=AssertionError('Real SDK forbidden')))
        self.folder = self.stack.enter_context(tempfile.TemporaryDirectory(prefix='kilas-document-runtime-test-'))
        wheel = Path(self.folder) / bundle.describe('cp312')['wheels'][0]['filename']
        wheel.write_bytes(b'Inert upload stub: VM extraction is mocked.')
        self.prepare = self.stack.enter_context(patch.object(bundle, 'prepare',
            return_value={abi: (wheel,) for abi in bundle.SUPPORTED_ABIS}))

    def armed(self):
        stack = ExitStack()
        stack.enter_context(patch.object(document, 'RELEASE_ENABLED', True))
        stack.enter_context(patch.object(document, 'EXPIRES_AT', jobs.now() + timedelta(hours=1)))
        stack.enter_context(patch.dict(os.environ, {'RENDER_SERVICE_ID': document.SERVICE_ID,
                                                  'E2B_API_KEY': 'synthetic-only'}))
        return stack

    def enabled(self, vm):
        return fixture.ExecutionTests.enabled(self, vm)

    def remote(self):
        from kilas_ai import workspace_acceptance_fixture as boundary
        vm, bodies = streams.sandbox(self.files)
        vm.sandbox_id = 'synthetic-document-proof-vm'
        vm.get_info.return_value = SimpleNamespace(cpu_count=2, memory_mb=4096, template_id=TEMPLATE,
            network={'allow_public_traffic': False}, allow_internet_access=False,
            lifecycle={'on_timeout': 'kill', 'auto_resume': False})
        probe = {'abi': 'cp312', 'python': '3.12.9', 'machine': 'x86_64',
                 'libc': ['glibc', '2.36'], 'free_threaded': False}
        vm.commands.run.side_effect = lambda command, **kwargs: SimpleNamespace(
            exit_code=0, stderr='', stdout=json.dumps(probe) if command == document.PROBE_COMMAND else 'ready')
        value = {'pages': fixed.PAGES, 'slides': fixed.SLIDES,
                 'sizes': {name: len(raw) for name, raw in self.files.items()},
                 'boundary': {'answer': 42, 'checks': boundary.CHECKS, 'evidence': {
                     'data': {'written_bytes': 66000000, 'available_before': 66000000,
                              'requested_bytes': 66060288, 'errno': 28},
                     'inodes': {'created_files': 4000, 'available_before': 4000, 'errno': 28}}}}
        report = {'exit_code': 0, 'stdout': 'KILAS_ACCEPTANCE_OK\nKILAS_DOCUMENT_OK ' + json.dumps(value) + '\n',
                  'stderr': '', 'timed_out': False, 'outputs': streams.manifest(self.files),
                  'evidence': copy.deepcopy(fixture.BOUNDARY), 'runtime_evidence': runtime_evidence(),
                  'collector_evidence': {'checks': ['file_limit', 'job_limit', 'file_count'],
                                         'private_staging': True, 'post_stop': True}}
        read = vm.files.read.side_effect
        vm.files.read.side_effect = lambda path, **kwargs: fixture.Stream(json.dumps(report).encode()) \
            if path.endswith('done.json') else read(path, **kwargs)
        return vm, report, bodies

    def outcome(self):
        _, report, _ = self.remote()
        return {'exit_code': 0, 'timed_out': False, 'customer_metered': False, 'sandbox_created': True,
                'cleanup_confirmed': True, 'elapsed_ms': 1000, 'stderr': '', 'stdout': report['stdout'],
                'boundary_evidence': report['evidence'], 'collector_evidence': report['collector_evidence'],
                'runtime_evidence': report['runtime_evidence'], 'template_id': TEMPLATE,
                'large_files': [{'filename': name, 'mime_type': formats.MIMES[name.rsplit('.', 1)[1]], 'content': raw}
                                for name, raw in self.files.items()],
                'host_memory_before': dict(MEMORY), 'host_memory_after': dict(MEMORY)}

    def test_release_is_off_and_service_expiry_testing_guards_precede_dispatch(self):
        with patch.object(document, 'RELEASE_ENABLED', False), \
             patch.dict(os.environ, {'RENDER_SERVICE_ID': document.SERVICE_ID, 'E2B_API_KEY': 'synthetic-only'}), \
             patch.object(document.threading, 'Thread') as thread:
            document.maybe_start(SimpleNamespace(testing=False))
            document.run(app.app)
            thread.assert_not_called()
            self.assertFalse(document.approval_valid())
        with self.armed(), patch.object(document.threading, 'Thread') as thread:
            document.maybe_start(SimpleNamespace(testing=True))
            thread.assert_not_called()
            with patch.dict(os.environ, {'RENDER_SERVICE_ID': 'another-service'}):
                self.assertFalse(document.approval_valid())
                document.run(app.app)
            with patch.object(document, 'EXPIRES_AT', jobs.now() - timedelta(seconds=1)):
                self.assertFalse(document.approval_valid())
                document.run(app.app)
        self.prepare.assert_not_called()
        self.sdk.assert_not_called()
        self.assertIsNone(db.query_one('SELECT id FROM kilas_agent_steps WHERE idempotency_key=?', (document.KEY,)))

    def test_unauthorized_and_mixed_proofs_stop_before_reservation_or_sdk(self):
        job, step = document.claim()
        source = document.fixture()
        with patch.object(execution, 'reserve', wraps=execution.reserve) as reserve:
            with self.assertRaisesRegex(ValueError, 'document_proof_not_authorized'):
                execution.execute(job, step, source, _document_proof=True)
            with self.armed():
                for wrong_job, wrong_step, wrong_source in (
                    ({**job, 'user_id': self.other}, step, source),
                    (job, {**step, 'idempotency_key': 'different-proof'}, source),
                    (job, step, {'main.py': 'print(42)\n'})):
                    with self.assertRaisesRegex(ValueError, 'document_proof_not_authorized'):
                        execution.execute(wrong_job, wrong_step, wrong_source, _document_proof=True)
                with self.assertRaisesRegex(ValueError, 'invalid_proof_profile'):
                    execution.execute(job, step, source, _proof=True, _document_proof=True)
            reserve.assert_not_called()
        self.prepare.assert_not_called()
        self.sdk.assert_not_called()

    def test_budget_counts_failed_reservations_and_accepts_only_exact_remaining_ceiling(self):
        prior = jobs.create(self.owner, 'Synthetic prior release reservation')
        db.execute("INSERT INTO kilas_workspace_executions(user_id,job_id,operation_key,state,reserved_micro_usd,created_at,expires_at,cleanup_confirmed) VALUES (?,?,?,'FAILED',?,?,?,1)",
            (self.owner, prior, 'execution:document-runtime-20261019-prior',
             document.TASK_BUDGET_MICRO_USD - document.VM_RESERVE_MICRO_USD + 1, jobs.stamp(), jobs.stamp()))
        before = db.query_one('SELECT COUNT(*) AS n FROM kilas_agent_jobs')['n']
        with self.assertRaisesRegex(ValueError, 'document_release_budget_exhausted'):
            document.claim()
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_agent_jobs')['n'], before)
        db.execute('UPDATE kilas_workspace_executions SET reserved_micro_usd=reserved_micro_usd-1')
        self.assertIsNotNone(document.claim())
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_agent_jobs')['n'], before + 1)
        self.sdk.assert_not_called()

    def test_concurrent_claims_have_one_winner_and_failed_restart_cannot_claim_again(self):
        barrier = threading.Barrier(2)
        original = db.query_one
        visited = threading.local()
        sql = 'SELECT id FROM kilas_agent_steps WHERE idempotency_key=?'
        def synchronized(query, params=()):
            result = original(query, params)
            if query == sql and params == (document.KEY,) and not getattr(visited, 'waited', False):
                visited.waited = True
                self.assertIsNone(result)
                barrier.wait(timeout=5)
            return result
        before = original('SELECT COUNT(*) AS n FROM kilas_agent_jobs')['n']
        with patch.object(db, 'query_one', side_effect=synchronized), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(document.claim) for _ in range(2)]
            results = [future.result(timeout=10) for future in futures]
        winners = [result for result in results if result is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(original('SELECT COUNT(*) AS n FROM kilas_agent_jobs')['n'], before + 1)
        job, step = winners[0]
        db.execute("UPDATE kilas_agent_jobs SET status='FAILED' WHERE id=?", (job['id'],))
        db.execute("UPDATE kilas_agent_steps SET status='FAILED' WHERE id=?", (step['id'],))
        self.assertIsNone(document.claim())
        with self.armed():
            document.run(app.app)
        self.prepare.assert_not_called()
        self.sdk.assert_not_called()

    def test_failed_step_insert_rolls_back_job_and_does_not_consume_operation(self):
        original = usage._query
        before = db.query_one('SELECT COUNT(*) AS n FROM kilas_agent_jobs')['n']
        def fail_step(conn, sql, *args, **kwargs):
            if sql.startswith('INSERT INTO kilas_agent_steps'):
                raise ValueError('synthetic step insert failure')
            return original(conn, sql, *args, **kwargs)
        with patch.object(usage, '_query', side_effect=fail_step), \
             self.assertRaisesRegex(ValueError, 'synthetic step insert failure'):
            document.claim()
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_agent_jobs')['n'], before)
        self.assertIsNotNone(document.claim())
        self.sdk.assert_not_called()

    def test_real_documents_mock_sdk_receipt_download_tenant_gate_and_no_replay(self):
        vm, _, bodies = self.remote()
        create = self.enabled(vm)
        with self.armed():
            document.run(app.app)
            self.assertTrue(document.accepted())
            document.run(app.app)
            self.assertTrue(large.capability(self.owner)['available'])
            self.assertFalse(large.capability(self.other)['available'])
            with patch.dict(os.environ, {'KILAS_EXECUTION_AUDIENCE': 'entitled'}), patch.object(free_test, 'active', return_value=False):
                self.assertFalse(large.capability(self.other)['available'])
                now = jobs.now()
                db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PLUS','ACTIVE',?,?)",
                           (self.other, jobs.stamp(now-timedelta(days=1)), jobs.stamp(now+timedelta(days=29))))
                self.assertTrue(large.capability(self.other)['available'])
            with patch.object(document, 'fingerprint', return_value='changed'):
                self.assertFalse(document.accepted())
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs['template'], 'base')
        vm.kill.assert_called_once()
        self.assertTrue(bodies and all(body.closed for body in bodies))
        row = db.query_one('SELECT * FROM kilas_workspace_executions')
        public = json.loads(row['outcome_json'])
        self.assertEqual(row['state'], 'SUCCEEDED')
        self.assertEqual(public['template_id'], TEMPLATE)
        self.assertTrue(public['download_checked'])
        self.assertFalse(public['customer_metered'])
        self.assertNotIn('large_storage_reserved', public)
        self.assertLessEqual(row['reserved_micro_usd'], document.VM_RESERVE_MICRO_USD)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_ai_usage WHERE operation_type='CODE_EXECUTION'")['n'], 0)
        self.assertEqual(jobs.get(self.owner, row['job_id'])['status'], 'COMPLETED')
        files = work_artifacts.listing(self.owner, job_id=row['job_id'])
        self.assertEqual(len(files), 5)
        for item in files:
            link = f'/kilas-ai/agent/jobs/{row["job_id"]}/artifacts/{item["id"]}?download=1'
            response = self.client().get(link)
            self.assertEqual(response.status_code, 200)
            self.assertIn('attachment;', response.headers['Content-Disposition'])
            self.assertEqual(self.client(self.other).get(link).status_code, 404)
            if item['name'] in self.files:
                self.assertEqual(response.data, self.files[item['name']])
        paths = [call.args[0] for call in vm.files.write.call_args_list]
        self.assertTrue(any(path.endswith('.whl') for path in paths))
        self.assertIn('/root/kilas-input.json', paths)
        self.assertIn('/root/kilas-runner.py', paths)
        self.assertIn(document.PROBE_COMMAND, [call.args[0] for call in vm.commands.run.call_args_list])
        print('DOCUMENT_RUNTIME_EVIDENCE '+json.dumps({'pdf_pages': fixed.PAGES, 'pptx_slides': fixed.SLIDES,
              'sizes': {name: len(raw) for name, raw in self.files.items()}, 'once': True, 'owned_download': True}))

    def test_tampered_runtime_fails_before_binary_download_and_cannot_replay(self):
        vm, report, bodies = self.remote()
        report['runtime_evidence']['versions']['reportlab'] = '0.0.0'
        create = self.enabled(vm)
        with self.armed():
            document.run(app.app)
            document.run(app.app)
            self.assertFalse(document.accepted())
            self.assertFalse(large.capability(self.owner)['available'])
        create.assert_called_once()
        vm.kill.assert_called_once()
        self.assertEqual(bodies, [])
        row = db.query_one('SELECT * FROM kilas_workspace_executions')
        self.assertEqual(json.loads(row['outcome_json'])['reason'], 'document_runtime_unverified')
        self.assertEqual(jobs.get(self.owner, row['job_id'])['status'], 'FAILED')
        self.assertEqual(work_artifacts.listing(self.owner, job_id=row['job_id']), [])

    def test_failed_cleanup_keeps_full_reservation_and_cannot_accept_or_replay(self):
        vm, _, _ = self.remote()
        vm.kill.side_effect = RuntimeError('synthetic cleanup failure')
        create = self.enabled(vm)
        with self.armed():
            document.run(app.app)
            document.run(app.app)
            self.assertFalse(document.accepted())
        create.assert_called_once()
        row = db.query_one('SELECT * FROM kilas_workspace_executions')
        self.assertEqual(row['state'], 'CLEANUP_REQUIRED')
        self.assertEqual(row['cleanup_confirmed'], 0)
        self.assertEqual(row['reserved_micro_usd'], document.VM_RESERVE_MICRO_USD)
        self.assertEqual(work_artifacts.listing(self.owner, job_id=row['job_id']), [])
        self.assertEqual(jobs.get(self.owner, row['job_id'])['status'], 'FAILED')

    def test_proof_predicate_requires_runtime_real_files_boundary_and_cleanup(self):
        outcome = self.outcome()
        self.assertTrue(document.passed(outcome))
        for key, value in [('cleanup_confirmed', False), ('customer_metered', True), ('timed_out', True),
                           ('exit_code', True), ('elapsed_ms', 60000), ('runtime_evidence', {}),
                           ('collector_evidence', {}), ('large_files', []), ('boundary_evidence', {}),
                           ('host_memory_after', {**MEMORY, 'peak': 500000000})]:
            with self.subTest(key=key):
                self.assertFalse(document.passed({**outcome, key: value}))
        for key, value in [('root_owned', False), ('network_install', True), ('host_execution', True),
                           ('manifest_sha256', '0'*64), ('versions', {})]:
            with self.subTest(runtime_key=key):
                self.assertFalse(document.passed({**outcome, 'runtime_evidence': {**runtime_evidence(), key: value}}))

    def test_probe_rejects_unsupported_runtime_and_changed_receipt_python(self):
        vm, _, _ = self.remote()
        self.assertEqual(document.probe(vm)['abi'], 'cp312')
        expected = {'runtime_evidence': {**runtime_evidence(), 'python': '3.12.8'}}
        with self.assertRaisesRegex(ValueError, 'document_runtime_unavailable'):
            document.probe(vm, expected)
        value = {'abi': 'cp312', 'python': '3.12.9', 'machine': 'x86_64',
                 'libc': ['glibc', '2.36'], 'free_threaded': False}
        for field, invalid in [('free_threaded', True), ('machine', 'aarch64'), ('abi', 'cp39'),
                               ('libc', ['glibc', '2.27'])]:
            vm.commands.run.side_effect = None
            vm.commands.run.return_value = SimpleNamespace(exit_code=0, stderr='', stdout=json.dumps({**value, field: invalid}))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'document_runtime_unavailable'):
                document.probe(vm)

    def test_runner_bootstrap_precedes_payload_and_preserves_old_six_pins(self):
        root = Path(guest.__file__).parent
        self.assertEqual(len(rollout.REVIEWED_FILES), 6)
        for name, digest in rollout.REVIEWED_FILES.items():
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(), digest, name)
        for proof in (False, True):
            source = guest.runner_source(bundle.describe('cp312'), bundle.manifest_digest(), proof=proof)
            compile(source, 'synthetic-document-runner', 'exec')
            main = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == 'main')
            lines = [ast.unparse(node) for node in main.body]
            install = lines.index('runtime_evidence = install_runtime()')
            payload = next(index for index, line in enumerate(lines) if line.startswith('payload = '))
            self.assertLess(install, payload)
            self.assertLess(install, lines.index('prepare_scratch()'))
            self.assertIn("args=['/usr/bin/python3','-I','-B',", source)
            self.assertIn("('RLIMIT_CPU',10)", source)
            self.assertIn("('RLIMIT_AS',256*1024*1024)", source)
            self.assertIn("('RLIMIT_FSIZE',8388608)", source)
            self.assertEqual(source.count('runtime_evidence=install_runtime()'), 1)
        original = Path.read_bytes
        fingerprint = document.fingerprint()
        for name in ('workspace_document_runtime.py', 'workspace_document_guest.py', 'workspace_document_fixture.py',
                     'workspace_document_bundle.py', 'workspace_document_bundle.lock.json', 'workspace_large_execution.py'):
            def changed(path, target=name):
                return original(path) + (b'\nsynthetic-change' if path.name == target else b'')
            with self.subTest(fingerprint_file=name), patch.object(Path, 'read_bytes', changed):
                self.assertNotEqual(document.fingerprint(), fingerprint)


if __name__ == '__main__':
    unittest.main()
