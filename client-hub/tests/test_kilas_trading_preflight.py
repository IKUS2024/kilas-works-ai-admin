"""Standalone preflight tests: synthetic reports and pinned offline policy only."""
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('trading_diagnostic_preflight', ROOT / 'scripts/trading_diagnostic_preflight.py')
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)
FIXTURES = Path(__file__).parent / 'fixtures'
POLICY = FIXTURES / 'trading_clock_policy'
NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.report = json.loads((FIXTURES / 'trading_preflight_synthetic.json').read_text())
        self.guard = patch('socket.socket', side_effect=AssertionError('No sockets'))
        self.guard.start(); self.addCleanup(self.guard.stop)
        self.dns = patch('socket.getaddrinfo', side_effect=AssertionError('No DNS'))
        self.dns.start(); self.addCleanup(self.dns.stop)
        self.http = patch('requests.sessions.Session.request', side_effect=AssertionError('No HTTP'))
        self.http.start(); self.addCleanup(self.http.stop)

    def check(self, report=None, digest=None, policy=POLICY):
        data = json.dumps(report or self.report).encode()
        return preflight.preflight(data, policy, digest, NOW)

    def assert_blocked(self, out):
        for key in ('connected', 'runtime_eligible', 'broker_execution_allowed', 'ai_analysis', 'paper_execution'):
            self.assertIs(out['runtime'][key], False)
        self.assertIs(out['runtime']['policy_replay_only'], True)
        self.assertEqual(out['runtime']['source_freshness'], 'NOT_GRANTED')

    def test_complete_report_reuses_policy_and_stays_historical_blocked(self):
        data = json.dumps(self.report).encode()
        out = preflight.preflight(data, POLICY, hashlib.sha256(data).hexdigest(), NOW)
        self.assertEqual(out['outcome'], 'OFFLINE_CHECKS_PASSED_RUNTIME_BLOCKED')
        self.assertEqual(out['diagnostic_outcome'], 'READ_ONLY_DEMO_DIAGNOSTIC_CAPTURED')
        self.assertEqual(out['sdk_shutdown'], 'COMPLETED')
        self.assertEqual(out['integrity']['status'], 'SUPPLIED_DIGEST_MATCH')
        self.assertEqual(out['demo_identity_binding']['status'], 'RECORDED_DEMO_SESSION_CONSISTENT_ONLY')
        self.assertIs(out['demo_identity_binding']['static_ui_evidence_grants_sdk_binding'], False)
        self.assertEqual(out['clock_replay']['replies'], 8)
        self.assertEqual(out['contract_specs']['economic_units'], 'NOT_INDEPENDENTLY_VERIFIED')
        self.assertEqual(out['minimum_lot_notional']['status'], 'BLOCKED_MINIMUM_LOT_CAP')
        self.assertEqual(out['runtime']['capture_recency'], 'STALE_HISTORICAL')
        self.assert_blocked(out)

    def test_missing_digest_is_honestly_separate_from_schema(self):
        out = self.check()
        self.assertEqual(out['schema']['status'], 'COMPATIBLE_DIAGNOSTIC')
        self.assertEqual(out['integrity']['status'], 'NOT_PROVIDED')
        self.assert_blocked(out)

    def test_digest_invalid_or_mismatch_does_not_run_report_parser(self):
        for digest, status in [('not-a-hash', 'INVALID_DIGEST'), ('0'*64, 'DIGEST_MISMATCH')]:
            with patch.object(preflight, 'browser_projection', side_effect=AssertionError('No parse')):
                out = self.check(digest=digest)
            self.assertEqual(out['integrity']['status'], status)
            self.assertIsNone(out['sdk_shutdown'])
            self.assertEqual(out['clock_replay']['status'], 'NOT_EVALUATED')
            self.assert_blocked(out)

    def test_size_malformed_duplicate_and_execution_claims_rejected(self):
        cases = [b'{}' + b' '*preflight.MAX_BYTES, b'\xff', b'{', b'{"status":0,"status":1}']
        r = copy.deepcopy(self.report); r['runtime_eligible'] = True; cases.append(json.dumps(r).encode())
        for data in cases:
            out = preflight.preflight(data, POLICY, now=NOW)
            self.assertEqual(out['outcome'], 'INVALID_REPORT'); self.assert_blocked(out)

    def test_pin_mismatch_never_executes_replacement_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            for name in preflight.PINS:
                (p/name).write_bytes((POLICY/name).read_bytes())
            (p/'clock_batch_offline.py').write_text('raise RuntimeError("SYNTHETIC_PRIVATE_MARKER")')
            out = self.check(policy=p)
        self.assertEqual(out['outcome'], 'PREFLIGHT_UNAVAILABLE')
        self.assertEqual(out['policy_integrity']['status'], 'POLICY_UNAVAILABLE_OR_PIN_MISMATCH')
        self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', json.dumps(out))

    def test_session_call_and_sample_binding_rejected(self):
        mutations = [lambda r: r['markets'][1].update(session_id='anotherSession0001'),
                     lambda r: r['markets'][0]['calls']['tick'].update(symbol='OTHER'),
                     lambda r: r['markets'][0]['calls']['tick'].update(ended_mono_ns=True),
                     lambda r: r['markets'][0]['sample'].update(acquired_end_mono_ns=r['markets'][0]['sample']['acquired_end_mono_ns']+1),
                     lambda r: r['risk_evidence'][0]['session'].update(session_id='anotherSession0001')]
        for mutation in mutations:
            r = copy.deepcopy(self.report); mutation(r); out = self.check(r)
            self.assertEqual(out['demo_identity_binding']['status'], 'REJECTED_BINDING')
            self.assertEqual(out['outcome'], 'INVALID_REPORT'); self.assert_blocked(out)

    def test_packet_failure_and_claimed_qualification_tampering_rejected(self):
        mutations = [lambda r: r['collection']['cycles'][0]['batch']['before'][0]['packet'].update(stratum=0),
                     lambda r: r['collection']['cycles'][0]['qualification'].update(evidence_sha256='0'*64),
                     lambda r: r['collection']['cycles'][0]['qualification'].update(uncertainty_seconds='0.001'),
                     lambda r: r['clock_results'][1].update(clock_uncertainty_ms=0),
                     lambda r: r['clock_results'][1]['tick'].update(normalized_time_utc='2026-10-09T00:00:00Z')]
        for mutation in mutations:
            r = copy.deepcopy(self.report); mutation(r); out = self.check(r)
            self.assertEqual(out['clock_replay']['status'], 'REJECTED_CLOCK_REPLAY')
            self.assert_blocked(out)

    def test_recorded_expired_lease_rejected_without_reanchoring(self):
        r = copy.deepcopy(self.report)
        b = r['collection']['cycles'][1]['batch']
        b['decision_mono_ns'] += 2000000000
        b['decision_utc'] = '2026-10-09T12:00:06.100000+00:00'
        out = self.check(r)
        self.assertEqual(out['clock_replay']['status'], 'REJECTED_CLOCK_REPLAY')
        self.assert_blocked(out)

    def test_changed_market_specs_or_bad_step_rejected_separately(self):
        mutations = [lambda r: r['markets'][1]['specs'].update(trade_contract_size='10'),
                     lambda r: r['markets'][0]['specs'].update(volume_step='0.03')]
        for mutation in mutations:
            r = copy.deepcopy(self.report); mutation(r); out = self.check(r)
            self.assertEqual(out['contract_specs']['status'], 'REJECTED_MARKET_SPECS')
            self.assertEqual(out['minimum_lot_notional']['status'], 'NOT_EVALUATED')
            self.assert_blocked(out)

    def test_risk_quote_or_formula_rejection_preserves_market_spec_result(self):
        mutations = [lambda r: r['risk_evidence'][0]['quote'].update(raw_time_msc=1),
                     lambda r: r['risk_evidence'][0]['scenarios'][0].update(notional_usd='2501'),
                     lambda r: r['risk_evidence'][0]['scenarios'][0].update(volume_lots='0.02')]
        for mutation in mutations:
            r = copy.deepcopy(self.report); mutation(r); out = self.check(r)
            self.assertEqual(out['contract_specs']['status'], 'NUMERIC_SPECS_CONSISTENT_ONLY')
            self.assertEqual(out['minimum_lot_notional']['status'], 'REJECTED_RISK_BINDING_OR_FORMULA')
            self.assert_blocked(out)

    def test_unknown_or_private_fields_never_escape_and_input_is_unchanged(self):
        r = copy.deepcopy(self.report)
        r['account'] = {'balance':'SYNTHETIC_PRIVATE_MARKER'}
        r['risk_evidence'][0]['account'] = {'login':'SYNTHETIC_PRIVATE_MARKER'}
        r['markets'][0]['specs']['password'] = 'SYNTHETIC_PRIVATE_MARKER'
        r['history'] = ['SYNTHETIC_PRIVATE_MARKER']; r['arbitrary'] = '<img onerror=SYNTHETIC_PRIVATE_MARKER>'
        before = copy.deepcopy(r); out = self.check(r)
        self.assertEqual(out['outcome'], 'OFFLINE_CHECKS_PASSED_RUNTIME_BLOCKED')
        self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', json.dumps(out))
        self.assertEqual(r, before)
        self.assert_blocked(out)

    def test_recent_capture_and_within_cap_arithmetic_never_enable_runtime(self):
        r = copy.deepcopy(self.report); r['finished_utc'] = NOW.isoformat()
        r['ui_evidence'] = {'demo_title': True, 'green_connection_bars': True, 'sdk_binding_verified': True}
        for m in r['markets']:
            m['tick']['bid'] = '1000.10'; m['tick']['ask'] = '1000.30'
        risk = r['risk_evidence'][0]; risk['quote'].update(bid='1000.10', ask='1000.30')
        for scenario in risk['scenarios']:
            scenario.update(notional_usd='1000.30' if scenario['direction']=='BUY' else '1000.10', cap_status='WITHIN_CAP')
        out = self.check(r)
        self.assertEqual(out['outcome'], 'OFFLINE_CHECKS_PASSED_RUNTIME_BLOCKED')
        self.assertEqual(out['minimum_lot_notional']['status'], 'WITHIN_CAP_ARITHMETIC_ONLY')
        self.assertEqual(out['runtime']['capture_recency'], 'RECENT_CAPTURE_UNVERIFIED')
        self.assert_blocked(out)

    def test_cli_exit_code_and_fixed_local_input_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory)/'report.json'; report.write_text(json.dumps(self.report))
            digest = Path(directory)/'report.sha256'; digest.write_text(hashlib.sha256(report.read_bytes()).hexdigest())
            command = [sys.executable, str(ROOT/'scripts/trading_diagnostic_preflight.py'), str(report), '--policy-dir', str(POLICY), '--sha256-file', str(digest)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)['outcome'], 'OFFLINE_CHECKS_PASSED_RUNTIME_BLOCKED')
            digest.write_text('0'*64)
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            report.unlink()
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 3)
            self.assertEqual(json.loads(result.stdout)['schema']['status'], 'LOCAL_INPUT_UNREADABLE')


if __name__ == '__main__': unittest.main()
