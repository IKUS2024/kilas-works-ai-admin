"""Real code/test outcomes inside a networkless OS sandbox, CI-only disposable fixtures."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kilas_ai.agent_workers import code_worker


class CodeSandboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != 'posix' or not shutil.which('bwrap'):
            if os.environ.get('REQUIRE_SANDBOX_QA') == '1':
                raise AssertionError('Real sandbox required by CI')
            raise unittest.SkipTest('No Linux bubblewrap locally; required in CI')

    def exercise(self, assertion):
        with tempfile.TemporaryDirectory() as source:
            Path(source, 'tests').mkdir()
            Path(source, 'tests/test_actual.py').write_text('import unittest\nclass Actual(unittest.TestCase):\n    def test_actual(self):\n        ' + assertion + '\n')
            job = {'id': 987654321}
            code_worker.cleanup(job)
            with patch.dict(os.environ, {'KILAS_AI_CODE_REPOSITORIES': json.dumps({'fixture': source}), 'PRODUCTION_SECRET': 'must-never-enter-sandbox'}), patch.object(code_worker, 'load_snapshot', return_value=None):
                try:
                    return code_worker.run(job, {'action': 'test'}, {'repo': 'fixture'})
                finally:
                    code_worker.cleanup(job)

    def test_actual_success(self):
        result = self.exercise('self.assertEqual(2 + 2, 4)')
        self.assertEqual(result.status, 'SUCCEEDED', result.output)
        self.assertEqual(result.output['exit_code'], 0)
        self.assertIn('Ran 1 test', result.output['test_output'])

    def test_actual_failure(self):
        result = self.exercise('self.assertEqual(2 + 2, 5)')
        self.assertEqual(result.status, 'FAILED')
        self.assertNotEqual(result.output['exit_code'], 0)
        self.assertIn('FAIL', result.output['test_output'], result.output)

    def test_no_production_environment(self):
        result = self.exercise("self.assertNotIn('PRODUCTION_SECRET', __import__('os').environ)")
        self.assertEqual(result.status, 'SUCCEEDED', result.output)

    def test_no_host_application_mount(self):
        result = self.exercise("self.assertFalse(__import__('os').path.exists('/home/runner/work'))")
        self.assertEqual(result.status, 'SUCCEEDED', result.output)


if __name__ == '__main__':
    unittest.main()
