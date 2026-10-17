"""Smoke fences only; unit tests never open a provider socket."""
from datetime import datetime, timezone, timedelta
import os
from pathlib import Path
import sys
import unittest
import contextlib
import io
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kilas_ai import ai_call_smoke as smoke


class SmokeTests(unittest.TestCase):
    def armed(self, **extra):
        values = {smoke.ARM: smoke.RUN, 'RENDER_SERVICE_ID': smoke.SERVICE,
                  'KILAS_AI_CALL_SMOKE_EXPIRES_AT': (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()}
        values.update(extra)
        return patch.dict(os.environ, values)

    def test_default_off_expired_wrong_service_and_overlong_arm_never_launch(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(smoke.subprocess, 'Popen') as child:
            self.assertFalse(smoke.launch())
            with self.armed(RENDER_SERVICE_ID='unrelated'):
                self.assertFalse(smoke.launch())
            for minutes in (-1, 31):
                with self.armed(KILAS_AI_CALL_SMOKE_EXPIRES_AT=(datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()):
                    self.assertFalse(smoke.launch())
            child.assert_not_called()

    def test_explicit_arm_only_launches_child_never_reads_or_copies_credentials(self):
        with self.armed(), patch.object(smoke.subprocess, 'Popen') as child:
            self.assertTrue(smoke.launch())
            child.assert_called_once_with([smoke.sys.executable, '-m', 'kilas_ai.ai_call_smoke'], close_fds=True)

    def test_synthetic_fixture_hashes_format_duration_and_context_answers(self):
        values = smoke.fixtures()
        self.assertEqual(len(values), 4)
        self.assertLess(sum(len(raw) for _, raw in values), 25 * 32000)
        self.assertEqual([item['answer'][0] for item, _ in values], ['lima', 'tiga', 'twelve', 'eight'])

    def test_durable_attempt_marker_prevents_provider_or_paid_admission_after_restart(self):
        from kilas_ai import ai_call as calls, ai_call_budget as budget
        import db
        with self.armed(), patch.object(db, 'BACKEND', 'postgres'), \
             patch.object(budget, 'config', return_value={'allowed_owner': 1}), \
             patch.object(budget, 'owned', return_value={'status': 'UNKNOWN'}), \
             patch.object(calls, 'start') as start, patch.object(calls.wire, 'connect') as connect, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            smoke.run()
            start.assert_not_called()
            connect.assert_not_called()
            self.assertIn('already_attempted_no_retry', output.getvalue())

    def test_unarmed_run_never_imports_database_or_calls_provider(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(smoke, 'fixtures') as fixtures:
            smoke.run()
            fixtures.assert_not_called()


if __name__ == '__main__':
    unittest.main()
