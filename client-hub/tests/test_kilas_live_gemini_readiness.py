"""Owner readiness is observational: no provider dispatch or expiry writes."""
import json
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import test_kilas_live_gemini as fixture
from kilas_ai import live_gemini_readiness as readiness


class ReadinessTests(unittest.TestCase):
    setUp = fixture.GeminiTests.setUp

    def checks(self, *, seconds=90, reserved=0, jobs=0, exempt=False):
        stack = ExitStack()
        self.addCleanup(stack.close)
        patches = {
            'policy': stack.enter_context(patch.object(readiness.budget, 'policy', return_value={'allowed_owner':9})),
            'enabled': stack.enter_context(patch.object(readiness.routes, 'enabled', return_value=True)),
            'identity': stack.enter_context(patch.object(readiness.native, 'preview_owner', return_value=True)),
            'native': stack.enter_context(patch.object(readiness.native, 'ready', return_value=True)),
            'status': stack.enter_context(patch.object(readiness.budget, 'status', return_value={
                'available':True, 'remaining_micro_usd':9600000, 'remaining_leases':38,
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
        self.assertEqual(result, {'owner_id':9, 'start_eligible':True, 'reason':'ready',
            'remaining_micro_usd':9600000, 'remaining_leases':38,
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


if __name__ == '__main__':
    unittest.main()
