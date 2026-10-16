"""Default-off and durable one-run tests, never real provider connections."""
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from kilas_ai import live_gemini_smoke as smoke


class SmokeTests(unittest.TestCase):
    def config(self,**extra):
        values={smoke.ARM:smoke.RUN,'RENDER_SERVICE_ID':smoke.SERVICE,
                'KILAS_LIVE_GEMINI_QA_OWNER_ID':'9','KILAS_LIVE_GEMINI_QA_OWNER_EMAIL':'synthetic@example.test',
                'KILAS_LIVE_GEMINI_QA_EXPIRES_AT':(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat()}
        values.update(extra)
        return patch.dict(os.environ,values)

    def test_no_child_without_complete_fixed_short_test_policy(self):
        for change in ({smoke.ARM:''},{'RENDER_SERVICE_ID':'different'},
                       {'KILAS_LIVE_GEMINI_QA_EXPIRES_AT':(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()},
                       {'KILAS_LIVE_GEMINI_QA_EXPIRES_AT':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()},
                       {'KILAS_LIVE_GEMINI_QA_OWNER_ID':'0'}):
            with self.config(**change),patch.object(smoke.subprocess,'Popen') as child:
                self.assertFalse(smoke.launch());child.assert_not_called()

    def test_child_inherits_runtime_without_secret_env_or_command_arguments(self):
        with self.config(),patch.object(smoke.subprocess,'Popen') as child:
            self.assertTrue(smoke.launch())
            child.assert_called_once_with([smoke.sys.executable,'-m','kilas_ai.live_gemini_smoke'],close_fds=True)

    def test_launch_failure_does_not_break_web_worker_startup(self):
        with self.config(),patch.object(smoke.subprocess,'Popen',side_effect=OSError('synthetic')),\
             redirect_stdout(io.StringIO()):
            self.assertFalse(smoke.launch())

    def test_immutable_nonprivate_fixtures_match_exact_15_second_pcm_contract(self):
        for language in ('id','en'):
            pcm=smoke.fixture(language)
            self.assertEqual(len(pcm),480000)
            self.assertTrue(any(pcm))

    def test_probe_retains_only_numeric_usage_and_preserves_wire_response(self):
        raw=json.dumps({'usageMetadata':{'promptTokenCount':375,'responseTokenCount':750,
                                        'totalTokenCount':1125,'secret':'synthetic-not-output'},
                        'setupComplete':{}})
        class Socket:
            def recv(self):return raw
        observation={'usage_snapshots':[]}
        probe=smoke.ProbeSocket(Socket(),observation)
        self.assertEqual(probe.recv(),raw)
        self.assertEqual(observation['observed_token_estimate_micro'],17063)
        self.assertNotIn('secret',str(observation))
        self.assertTrue(observation['setup_complete'])

    def test_probe_stops_conservatively_before_internal_lease_limit(self):
        class Socket:
            def recv(self):return json.dumps({'usageMetadata':{'promptTokenCount':10,'responseTokenCount':5000}})
        with self.assertRaisesRegex(ValueError,'usage_limit'):
            smoke.ProbeSocket(Socket(),{'usage_snapshots':[]}).recv()

    def test_run_never_prints_supplier_exception_text_and_never_enables_web_parent(self):
        from kilas_ai import live_gemini_budget as budget
        with self.config(),patch.dict(os.environ,{'KILAS_LIVE_GEMINI_ENABLED':'false'}),\
             patch.object(smoke,'once',side_effect=RuntimeError('synthetic-secret-must-not-print')),\
             patch.object(budget,'LEASE_MS',90000),redirect_stdout(io.StringIO()) as output:
            smoke.run()
            self.assertNotIn('synthetic-secret',output.getvalue())
            self.assertIn('stopped_no_retry',output.getvalue())
            self.assertEqual(os.environ['KILAS_LIVE_GEMINI_ENABLED'],'false')


if __name__=='__main__':unittest.main()
