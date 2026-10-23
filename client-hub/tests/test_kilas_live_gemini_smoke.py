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

    def test_new_ten_second_harness_is_off_and_uses_complete_offline_sources(self):
        from kilas_ai import live_gemini_smoke_10s as bounded
        with patch.dict(os.environ, {smoke.ARM: 'off'}), patch.object(smoke, 'run') as run:
            bounded.run()
            run.assert_not_called()
        with patch.object(smoke, 'INPUT_MS', 10000), \
             patch.object(smoke, 'FIXTURE_DIRECTORY', 'gemini_live_synthetic_10s'), \
             patch.object(smoke, 'FIXTURES', bounded.FIXTURES):
            for language in ('id', 'en'):
                pcm = smoke.fixture(language)
                self.assertEqual(len(pcm), 320000)
                self.assertTrue(any(pcm[:280000]))
                self.assertFalse(any(pcm[-16000:]))
        self.assertEqual(smoke.INPUT_MS, 15000)
        self.assertNotEqual(smoke.RUN, bounded.RUN)

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

    def test_fixture_checks_require_actual_streaming_terminal_tail_and_end(self):
        valid={'code':None,'setup_complete':True,'input_ms':15000,'output_ms':1000,
               'streamed_before_input_finished':True,'source_tail_word_confirmed':True,
               'target_tail_word_confirmed':True,'terminal_turn_complete':True,'tail_confirmed':True,
               'all_generated_pcm_read':True,'settled_after_end':True,'post_end_frames':0,
               'post_end_output_access':'blocked','backend_end_ms':50}
        self.assertTrue(smoke.passed(valid))
        for field in ('streamed_before_input_finished','source_tail_word_confirmed','target_tail_word_confirmed',
                      'terminal_turn_complete','all_generated_pcm_read','settled_after_end'):
            self.assertFalse(smoke.passed(dict(valid,**{field:False})))
        self.assertFalse(smoke.passed(dict(valid,code='gemini_tail_timeout')))
        self.assertFalse(smoke.passed(dict(valid,tail_confirmed=False,completion_kind='bounded_drain')))
        self.assertFalse(smoke.passed(dict(valid,backend_end_ms=2500)))
        self.assertTrue(smoke.tail_word('A bottle of WATER.','en'))
        self.assertTrue(smoke.tail_word('Sebotol air!','id'))
        self.assertFalse(smoke.tail_word('A bottle of','en'))

    def test_policy_check_restores_child_flag_and_never_reads_or_reports_secret_names(self):
        from kilas_ai import live_gemini_budget as budget
        with patch.dict(os.environ,{'KILAS_LIVE_GEMINI_ENABLED':'false'}),\
             patch.object(budget,'ready',return_value=False):
            value=smoke.production_policy_check(9)
            self.assertFalse(value['valid_for_owner_if_enabled'])
            self.assertEqual(os.environ['KILAS_LIVE_GEMINI_ENABLED'],'false')
            self.assertNotIn('GEMINI_API_KEY',str(value))

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

    def test_remaining_arm_is_one_named_direction_and_binary_setup_is_observed(self):
        with self.config(**{smoke.ARM:smoke.RUN+'-remaining-en-id'}):
            self.assertTrue(smoke.config()['remaining'])
        raw=b'{"setupComplete":{"sessionId":"synthetic"}}'
        class Socket:
            def recv(self):return raw
        observation={'usage_snapshots':[]}
        self.assertEqual(smoke.ProbeSocket(Socket(),observation).recv(),raw)
        self.assertEqual(observation['first_frame_type'],'bytes')
        self.assertTrue(observation['setup_complete'])

    def test_probe_keeps_terminal_event_kinds_separate_from_transcripts_and_usage(self):
        raw=json.dumps({'serverContent':{'generationComplete':True,'turnComplete':True,
                                        'interactionStatus':'IN_PROGRESS','outputTranscription':{'text':'synthetic'}}})
        class Socket:
            def recv(self):return raw
        observation={'usage_snapshots':[]}
        self.assertEqual(smoke.ProbeSocket(Socket(),observation).recv(),raw)
        self.assertEqual(observation['server_terminal_events'],{'generationComplete':1,'turnComplete':1})
        self.assertEqual(observation['last_interaction_status'],'IN_PROGRESS')
        self.assertNotIn('synthetic',str(observation))

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

    def test_new_round_runs_each_direction_once_without_retrying_a_failed_outcome(self):
        with self.config(),patch.dict(os.environ,{'KILAS_LIVE_GEMINI_ENABLED':'false'}),\
             patch.object(smoke,'once',return_value=True),\
             patch.object(smoke,'session',side_effect=[{'code':'gemini_tail_timeout'},{'code':'gemini_deadline'}]) as execute,\
             redirect_stdout(io.StringIO()) as output:
            smoke.run()
            self.assertEqual([(call.args[1],call.args[2]) for call in execute.call_args_list],[('id','en'),('en','id')])
            self.assertEqual(execute.call_count,2)
            self.assertIn('"all_backend_checks_passed":false',output.getvalue())
            self.assertEqual(os.environ['KILAS_LIVE_GEMINI_ENABLED'],'false')


if __name__=='__main__':unittest.main()
