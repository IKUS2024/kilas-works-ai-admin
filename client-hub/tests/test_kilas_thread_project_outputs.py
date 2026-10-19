"""Chat projects require validated deliverables; native authors and VM IO are mocked."""
import base64
import io
import json
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfReader
import test_kilas_thread_projects as fixture
import test_kilas_workspace_large_outputs as streams
from kilas_ai import autonomous_store as jobs, pdf, providers, store
from kilas_ai import workspace_artifact_transport as transport, workspace_execution_worker as worker
from kilas_ai import workspace_large_outputs as large, workspace_model_tools as native


class ThreadProjectOutputs(unittest.TestCase):
    setUp = fixture.ThreadProjects.setUp
    client = fixture.ThreadProjects.client
    sandbox = fixture.ThreadProjects.sandbox
    enabled = fixture.ThreadProjects.enabled

    def post(self, prompt, key):
        return self.client().post(f'/kilas-ai/threads/{self.thread}/send', data={
            'content': prompt, 'operation_key': key, 'selected_model': 'gpt-6-astra', 'csrf_token': 'work-csrf'})

    def provider(self):
        response = fixture.ThreadProjects.provider(self)
        value = response.json()
        value['model'] = 'gpt-6-astra'
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: value)

    def start(self, job):
        return self.client().post(f'/kilas-ai/threads/{self.thread}/jobs/{job["id"]}/start',
                                  json={}, headers={'X-CSRF-Token': 'work-csrf'})

    def status(self, job):
        return self.client().get(f'/kilas-ai/threads/{self.thread}/jobs/{job["id"]}').json

    def test_large_pdf_streamed_once_completes_and_survives_owned_reload_download(self):
        source = '# Synthetic Many Pages\n\n' + '\n\n'.join(
            f'## Section {index}\n\nThis is synthetic content.' for index in range(490))
        raw = pdf.render(source)['content']
        self.assertGreater(len(raw), 65536)
        vm, bodies = streams.sandbox({'large.pdf': raw})
        vm.sandbox_id = 'synthetic-large-thread-vm'
        vm.get_info.return_value = SimpleNamespace(cpu_count=2, memory_mb=4096, allow_internet_access=False,
            network={'allow_public_traffic': False}, lifecycle={'on_timeout': 'kill', 'auto_resume': False})
        vm.commands.run.return_value = SimpleNamespace(stdout='ready')
        read = vm.files.read.side_effect
        report = {'exit_code': 0, 'stdout': '', 'stderr': '', 'timed_out': False,
                  'outputs': streams.manifest({'large.pdf': raw}), 'evidence': fixture.remote.BOUNDARY}
        vm.files.read.side_effect = lambda path, **kwargs: fixture.remote.Stream(json.dumps(report).encode()) \
            if path.endswith('done.json') else read(path, **kwargs)
        create = self.enabled(vm)
        prompt = 'Create a large PDF report project and run Python in the sandbox.'
        key = 'astra_large_pdf_project_000001'
        with patch.object(large, 'capability', return_value={'available': True}), \
             patch.object(large, 'host_memory', return_value={'limit': 536870912, 'current': 104857600, 'peak': 209715200}), \
             patch.object(native.requests, 'post', return_value=self.provider()) as model, \
             patch.object(providers, 'stream', side_effect=AssertionError('Project uses the selected native author')), \
             patch.object(worker, 'result', wraps=worker.result) as result, \
             patch.object(transport, 'collect', wraps=transport.collect) as collect:
            self.assertIn('event: job', self.post(prompt, key).text)
            job = jobs.list_jobs(self.owner)[0]
            self.assertTrue(self.start(job).json['started'])
            self.assertEqual(jobs.get(self.owner, job['id'])['status'], 'COMPLETED')
            output = json.loads(jobs.steps(job['id'])[0]['output_json'])
            self.assertEqual(output['generated_file_count'], 1)
            status = self.status(job)
            self.assertEqual({item['filename'] for item in status['files']},
                             {'source-project.zip', 'execution-result.json', 'large.pdf'})
            item = next(item for item in status['files'] if item['filename'] == 'large.pdf')
            for client in (self.client(), self.client()):
                self.assertIn('data-workspace-job=', client.get(f'/kilas-ai/threads/{self.thread}').text)
                response = client.get(item['url'])
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, raw)
                self.assertIn('attachment;', response.headers['Content-Disposition'])
                self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
                self.assertIn('sandbox', response.headers['Content-Security-Policy'])
            self.assertEqual(self.client(self.other).get(item['url']).status_code, 404)
            other_thread = store.create_thread(self.owner)
            wrong_thread = item['url'].replace(f'/threads/{self.thread}/', f'/threads/{other_thread}/')
            self.assertEqual(self.client().get(wrong_thread).status_code, 404)
            self.assertIn('event: job', self.post(prompt, key).text)
            self.start(job)
            model.assert_called_once()
            self.assertEqual(model.call_args.kwargs['json']['model'], 'gpt-6-astra')
            create.assert_called_once()
            result.assert_called_once()
            collect.assert_called_once()
        vm.kill.assert_called_once()
        self.assertTrue(bodies and all(body.closed for body in bodies))
        pages = PdfReader(io.BytesIO(raw), strict=True).pages
        self.assertEqual(len(pages), 50)
        self.assertIn('Section 489', pages[-1].extract_text())
        print(f'ASTRA_PROJECT_PDF_EVIDENCE bytes={len(raw)} pages={len(pages)} state=COMPLETED owned_reload_download=True')

    def test_runtime_report_only_fails_retains_sources_and_never_retries(self):
        outputs = fixture.frames({})
        report = {'exit_code': 0, 'stdout': 'No files generated.\n', 'stderr': '', 'timed_out': False,
                  'outputs': {name: base64.b64encode(value.encode()).decode() for name, value in outputs.items()}}
        vm = self.sandbox(report)
        create = self.enabled(vm)
        with patch.object(native.requests, 'post', return_value=self.provider()) as model, \
             patch.object(worker, 'result', wraps=worker.result) as result, \
             patch.object(transport, 'collect', wraps=transport.collect) as collect:
            self.assertIn('event: job', self.post(fixture.PROMPT, 'astra_empty_output_000001').text)
            job = jobs.list_jobs(self.owner)[0]
            self.assertTrue(self.start(job).json['started'])
            status = self.status(job)
            self.assertEqual(status['state'], 'FAILED')
            output = json.loads(jobs.steps(job['id'])[0]['output_json'])
            self.assertEqual(output['generated_file_count'], 0)
            self.assertEqual(output['reason'], 'execution_output_missing')
            answer = store.operation(self.owner, self.thread, 'astra_empty_output_000001:assistant')['content']
            self.assertIn('Tidak ada file hasil yang tervalidasi.', answer)
            self.assertNotIn('Python selesai.', answer)
            self.assertEqual({item['filename'] for item in status['files']}, {'source-project.zip', 'execution-result.json'})
            item = next(item for item in status['files'] if item['filename'] == 'source-project.zip')
            with zipfile.ZipFile(io.BytesIO(self.client().get(item['url']).data)) as archive:
                self.assertEqual(archive.read('main.py').decode(), fixture.SOURCE['main.py'])
            self.assertIn('data-workspace-job=', self.client().get(f'/kilas-ai/threads/{self.thread}').text)
            self.post(fixture.PROMPT, 'astra_empty_output_000001')
            self.start(job)
            model.assert_called_once()
            create.assert_called_once()
            result.assert_called_once()
            collect.assert_called_once()
        vm.kill.assert_called_once()

    def test_invalid_export_keeps_source_without_claiming_success(self):
        outputs = fixture.frames({'result.csv': fixture.CSV})
        frame = json.loads(outputs['kilas-export-000.json'])
        frame['sha256'] = '0' * 64
        outputs['kilas-export-000.json'] = json.dumps(frame)
        report = {'exit_code': 0, 'stdout': '', 'stderr': '', 'timed_out': False,
                  'outputs': {name: base64.b64encode(value.encode()).decode() for name, value in outputs.items()}}
        create = self.enabled(self.sandbox(report))
        with patch.object(native.requests, 'post', return_value=self.provider()) as model:
            self.post(fixture.PROMPT, 'astra_invalid_output_000001')
            job = jobs.list_jobs(self.owner)[0]
            self.start(job)
            status = self.status(job)
            self.assertEqual(status['state'], 'FAILED')
            names = {item['filename'] for item in status['files']}
            self.assertIn('source-project.zip', names)
            self.assertNotIn('result.csv', names)
            output = json.loads(jobs.steps(job['id'])[0]['output_json'])
            self.assertEqual(output['generated_file_count'], 0)
            self.assertEqual(output['execution_diagnostic']['phase'], 'validating_outputs')
            self.start(job)
            model.assert_called_once()
            create.assert_called_once()


if __name__ == '__main__':
    unittest.main()
