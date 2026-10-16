"""Owner readiness is observational: no provider dispatch or expiry writes."""
import json
import io
import runpy
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import test_kilas_live_gemini as fixture
from kilas_ai import live_gemini_readiness as readiness


class ReadinessTests(unittest.TestCase):
    setUp = fixture.GeminiTests.setUp

    def checks(self, *, seconds=90, reserved=0, jobs=0, exempt=False, audience='owner'):
        stack = ExitStack()
        self.addCleanup(stack.close)
        patches = {
            'policy': stack.enter_context(patch.object(readiness.budget, 'policy', return_value={
                'allowed_owner':9, 'audience':audience})),
            'allowed': stack.enter_context(patch.object(readiness.budget, 'allowed', return_value=True)),
            'enabled': stack.enter_context(patch.object(readiness.routes, 'enabled', return_value=True)),
            'identity': stack.enter_context(patch.object(readiness.native, 'preview_owner', return_value=True)),
            'native': stack.enter_context(patch.object(readiness.native, 'ready', return_value=True)),
            'status': stack.enter_context(patch.object(readiness.budget, 'status', return_value={
                'available':True, 'remaining_micro_usd':8850000, 'remaining_leases':17,
                'reserve_micro_usd':500000,
                'valuation_mode':'conservative_internal'})),
            'active': stack.enter_context(patch.object(readiness.sessions, 'active', return_value=None)),
            'query': stack.enter_context(patch.object(readiness.usage, '_query', side_effect=[
                (seconds,), (reserved, jobs)])),
            'exempt': stack.enter_context(patch.object(readiness.usage, '_qa_quota_exempt', return_value=exempt)),
            'allowance': stack.enter_context(patch.object(readiness.live, 'require_audio_allowance')),
        }
        connection = Mock()
        patches['connection'] = connection
        stack.enter_context(patch.object(readiness.usage, '_connect', return_value=connection))
        for module, names in (
            (readiness.native, ('connect', 'start')),
            (readiness.budget, ('claim', 'dispatch')),
            (readiness.sessions, ('claim', 'create', 'end')),
            (readiness.audio_store, ('balance', 'require_balance', '_expire')),
            (readiness.budget.ledger, ('_expire',)),
        ):
            for name in names:
                stack.enter_context(patch.object(module, name, side_effect=AssertionError('read-only violation')))
        return patches

    def test_ready_snapshot_contains_only_safe_metadata_and_selects(self):
        checks = self.checks()
        result = readiness.report()
        self.assertEqual(result, {'owner_id':9, 'user_id':9, 'audience':'owner', 'start_eligible':True, 'reason':'ready',
            'input_mode':'gemini-live-two-way-v2', 'output_order':'progressive_stream_runs', 'streams':2,
            'remaining_micro_usd':8850000, 'remaining_leases':17, 'reserve_micro_usd':500000,
            'valuation_mode':'conservative_internal', 'audio_exempt':False})
        for call in checks['query'].call_args_list:
            self.assertTrue(call.args[1].startswith('SELECT '))
        checks['allowance'].assert_called_once_with(9, 90)
        checks['connection'].close.assert_called_once()
        checks['connection'].commit.assert_not_called()

    def test_balance_gate_accepts_only_ninety_seconds_or_existing_exemption(self):
        for seconds, reserved, exempt, expected in ((89,0,False,False), (90,1,False,False),
                                                   (0,0,False,False), (0,0,True,True)):
            with self.subTest(seconds=seconds, reserved=reserved, exempt=exempt):
                checks = self.checks(seconds=seconds, reserved=reserved, exempt=exempt)
                self.assertEqual(readiness.report()['start_eligible'], expected)
                if not expected:
                    checks['allowance'].assert_not_called()

    def test_busy_existing_session_audio_or_ledger_never_resets_anything(self):
        checks = self.checks()
        checks['active'].return_value = {'session_id':'private-existing-id', 'processing':False}
        self.assertEqual(readiness.report()['reason'], 'session_busy')
        checks['active'].return_value = None
        checks['query'].side_effect = [(900,), (90,1)]
        self.assertEqual(readiness.report()['reason'], 'audio_busy')
        checks['status'].return_value = {'available':False, 'reason':'already_processing'}
        self.assertEqual(readiness.report()['reason'], 'already_processing')

    def test_disabled_policy_or_identity_fails_closed(self):
        checks = self.checks()
        for name, expected in (('policy','policy_unavailable'), ('enabled','app_unavailable'),
                               ('identity','owner_unverified'), ('native','gemini_unavailable')):
            previous = checks[name].return_value
            checks[name].return_value = None if name == 'policy' else False
            self.assertEqual(readiness.report()['reason'], expected)
            checks[name].return_value = previous

    def test_live_allowance_and_unknown_errors_are_sanitized(self):
        checks = self.checks()
        checks['allowance'].side_effect = readiness.audio_store.AudioError('private-text', 'live_audio_limit')
        result = readiness.report()
        self.assertEqual(result['reason'], 'live_audio_limit')
        self.assertFalse(result['start_eligible'])
        checks['status'].side_effect = RuntimeError('secret-key-email-session-id')
        result = readiness.report()
        self.assertEqual(result['reason'], 'readiness_error')
        self.assertNotIn('secret', json.dumps(result))

    def test_authenticated_nonowner_uses_same_global_allowance_without_fixture_owner_gate(self):
        checks = self.checks(audience='authenticated')
        result = readiness.report(42)
        self.assertEqual(result['owner_id'], 9)
        self.assertEqual(result['user_id'], 42)
        self.assertEqual(result['audience'], 'authenticated')
        self.assertTrue(result['start_eligible'])
        self.assertEqual(result['remaining_micro_usd'], 8850000)
        self.assertEqual(result['remaining_leases'], 17)
        self.assertEqual(result['reserve_micro_usd'], 500000)
        checks['allowed'].assert_called_once_with(42, checks['policy'].return_value)
        checks['identity'].assert_not_called()
        checks['native'].assert_called_once_with(42)
        checks['status'].assert_called_once_with(42, streams=2)
        checks['allowance'].assert_called_once_with(42, 90)
        checks['exempt'].assert_called_once()
        self.assertEqual(checks['exempt'].call_args.args[1], 42)

    def test_missing_or_disallowed_nonowner_and_invalid_ids_fail_closed(self):
        checks = self.checks(audience='authenticated')
        checks['allowed'].return_value = False
        for user in (42, None, '42', True, 0, -1):
            with self.subTest(user=user):
                result = readiness.report(user)
                self.assertFalse(result['start_eligible'])
                self.assertEqual(result['reason'], 'user_unavailable')
        checks['status'].assert_not_called()
        checks['query'].assert_not_called()

    def test_authenticated_nonowner_retains_audio_quota_requirements(self):
        checks = self.checks(audience='authenticated', seconds=89)
        result = readiness.report(42)
        self.assertFalse(result['start_eligible'])
        self.assertEqual(result['reason'], 'insufficient_balance')
        self.assertEqual(result['remaining_micro_usd'], 8850000)
        checks['allowance'].assert_not_called()
        checks['query'].side_effect = [(0,), (0,0)]
        checks['exempt'].return_value = True
        checks['allowance'].side_effect = readiness.audio_store.AudioError('private', 'live_audio_limit')
        self.assertEqual(readiness.report(42)['reason'], 'live_audio_limit')

    def test_audience_report_selects_existing_nonowner_and_never_exposes_identity_data(self):
        checks = self.checks(audience='authenticated')
        checks['query'].side_effect = [(42,), (90,), (0,0)]
        owner_report = {'owner_id':9, 'user_id':9, 'start_eligible':True, 'reason':'ready'}
        result = readiness.audience_report(owner_report)
        self.assertEqual(result['audience'], 'authenticated')
        self.assertEqual(result['owner'], owner_report)
        self.assertEqual(result['nonowner']['user_id'], 42)
        self.assertTrue(result['nonowner']['start_eligible'])
        self.assertEqual(result['nonowner_reason'], 'ready')
        query = checks['query'].call_args_list[0]
        self.assertTrue(query.args[1].startswith('SELECT id FROM users WHERE id<>?'))
        self.assertEqual(query.args[2], (9,))
        self.assertNotIn('email', json.dumps(result))
        self.assertNotIn('session_id', json.dumps(result))

    def test_audience_report_owner_scope_and_missing_sample_are_explicit(self):
        checks = self.checks()
        result = readiness.audience_report({'user_id':9})
        self.assertEqual(result['nonowner_reason'], 'owner_only')
        checks['query'].assert_not_called()
        checks['policy'].return_value['audience'] = 'authenticated'
        checks['query'].side_effect = [None]
        result = readiness.audience_report({'user_id':9})
        self.assertIsNone(result['nonowner'])
        self.assertEqual(result['nonowner_reason'], 'no_existing_nonowner')

    def test_worker_logs_owner_and_nonowner_report_without_dispatch(self):
        hook = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'gunicorn.conf.py'))['post_worker_init']
        owner = {'owner_id':9, 'user_id':9, 'start_eligible':True, 'reason':'ready'}
        audience = {'audience':'authenticated', 'owner':owner,
                    'nonowner':{'owner_id':9, 'user_id':42, 'start_eligible':True, 'reason':'ready'}}
        output = io.StringIO()
        with patch.object(readiness.budget, 'policy', return_value={'audience':'authenticated'}), \
             patch.object(readiness, 'report', return_value=owner) as report, \
             patch.object(readiness, 'audience_report', return_value=audience) as sample, \
             patch('kilas_ai.live_gemini_smoke.launch'), redirect_stdout(output):
            hook(None)
        report.assert_called_once_with()
        sample.assert_called_once_with(owner)
        lines = output.getvalue().splitlines()
        self.assertEqual(json.loads(next(line.split(' ',1)[1] for line in lines
                                       if line.startswith('KILAS_GEMINI_OWNER_READY '))), owner)
        self.assertEqual(json.loads(next(line.split(' ',1)[1] for line in lines
                                       if line.startswith('KILAS_GEMINI_AUDIENCE_READY '))), audience)

    def test_worker_does_not_run_readiness_when_policy_invalid(self):
        hook = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'gunicorn.conf.py'))['post_worker_init']
        with patch.object(readiness.budget, 'policy', return_value=None), \
             patch.object(readiness, 'report') as report, \
             patch.object(readiness, 'audience_report') as sample, \
             patch('kilas_ai.live_gemini_smoke.launch'), redirect_stdout(io.StringIO()):
            hook(None)
        report.assert_not_called()
        sample.assert_not_called()


if __name__ == '__main__':
    unittest.main()
