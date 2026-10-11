"""Offline wire-contract tests; no transport, model, credentials or broker."""
import hashlib
import json
import unittest
from datetime import datetime

from btc_integration_protocol import (
    BtcRejected, BLOCKED_OUTCOMES, canonical_json, contract_hash, decision_id,
    parse_analysis_response, parse_evidence_response,
    validate_analysis_request, validate_evidence_request,
)


STAMP = '2026-10-10T12:00:01+00:00'


def bootstrap_request():
    return {
        'schema_version': 2, 'session_id': 'a' * 32, 'revision': 1,
        'command_id': 'b' * 32, 'instrument': 'BTC', 'lot': '0.01',
        'sequence': 0, 'challenge': None, 'account_mode': 'DEMO',
        'terminal_connected': True, 'market': None, 'spec': None, 'risk': None,
    }


def capture_request():
    body = bootstrap_request()
    body['sequence'] = 1
    body['challenge'] = 'c' * 64
    epoch = 1791633601
    last = epoch // 60 * 60 - 60
    body['market'] = {
        'symbol': 'BTCUSD', 'timeframe': 'M1',
        'tick': {'time': epoch, 'time_msc': epoch * 1000 + 400, 'bid': '60000', 'ask': '60010'},
        'capture': {'start_utc': '2026-10-10T12:00:00.900000+00:00', 'end_utc': STAMP,
                    'start_mono_ns': 100, 'end_mono_ns': 100000100},
        'candles': [{'time': last - (11 - i) * 60, 'open': '60000', 'high': '60020',
                     'low': '59980', 'close': '60000'} for i in range(12)],
        'clock': None, 'clock_profile': None,
    }
    body['spec'] = {
        'symbol': 'BTCUSD', 'contract_size': '1', 'volume_min': '0.01', 'volume_max': '1',
        'volume_step': '0.01', 'tick_cents': 100, 'stops_distance_cents': 100,
        'cost_bound_cents': 50, 'verified_at': '2026-10-10T12:00:00+00:00',
    }
    body['risk'] = {
        'captured_at': STAMP, 'position_open': False, 'protection_active': False,
        'daily_loss_remaining_cents': 50000, 'strategy_verified': True,
        'cooldown_clear': True, 'loss_streak_clear': True,
        'broker_contract_sha256': contract_hash(body['spec']), 'policy_version': 'd' * 64,
    }
    return body


def evidence_response(request):
    response = {
        'schema_version': 2,
        'outcome': 'CAPTURE_CHALLENGE_ISSUED' if request['challenge'] is None else 'EVIDENCE_ACCEPTED',
        'sequence': request['sequence'], 'challenge': 'e' * 64,
        'challenge_expires_at': '2026-10-10T12:00:06+00:00',
        'received_at': STAMP, 'execution_authorized': False,
    }
    if request['challenge'] is not None:
        response.update(session_id=request['session_id'],
                        evidence={'market_id': '1' * 32, 'spec_id': '2' * 32, 'news_id': None},
                        coverage='BTC_EDITORIAL_ONLY', risk_review='UNREVIEWED',
                        tick_liveness='UNCONFIRMED')
    return response


def analysis_request():
    return {
        'schema_version': 2, 'operation_key': 'worker-operation-123', 'session_id': 'a' * 32,
        'revision': 1, 'command_id': 'b' * 32, 'instrument': 'BTC', 'lot': '0.01',
        'evidence': {'market_id': '1' * 32, 'news_id': '3' * 32, 'spec_id': '2' * 32},
    }


def analysis_response(request, *, authorized=False):
    return {
        'schema_version': 2, 'outcome': 'PROPOSAL_READY', 'instrument': 'BTC',
        'model': 'gpt-6.1-sol', 'reasoning': 'medium',
        'decision': {'decision': 'BUY', 'reason': 'Synthetic example only',
                     'invalidation': 'Synthetic example only', 'stop_cents': 5981000,
                     'target_cents': 6041000, 'news_risk': 'LOW'},
        'news_coverage': 'BTC_EDITORIAL_ONLY', 'risk_state': 'PASSED',
        'execution_authorized': authorized, 'checked_at': STAMP,
        'session_id': request['session_id'], 'operation_key': request['operation_key'],
        'revision': request['revision'], 'command_id': request['command_id'],
        'evidence': dict(request['evidence']), 'decision_id': decision_id(request),
        'authorization_expires_at': '2026-10-10T12:00:05+00:00' if authorized else None,
    }


class BtcProtocolTests(unittest.TestCase):
    def rejected(self, function, *args):
        with self.assertRaisesRegex(BtcRejected, '^BTC_V2_REJECTED$'):
            function(*args)

    def test_bootstrap_uses_current_control_context_and_can_recover_sequence(self):
        request = bootstrap_request()
        request.update(revision=18, command_id='f' * 32, lot='0.02')
        response = evidence_response(request)
        response['sequence'] = 91
        self.assertEqual(validate_evidence_request(request), request)
        self.assertEqual(parse_evidence_response(json.dumps(response), request)['sequence'], 91)

    def test_initial_null_command_bootstrap_is_valid(self):
        request = bootstrap_request()
        request.update(revision=0, command_id=None)
        self.assertEqual(validate_evidence_request(request), request)

    def test_exact_twelve_relative_closed_bars_accept_without_absolute_clock_proof(self):
        request = capture_request()
        # Relative broker epochs need not agree with the PC's absolute UTC.
        request['market']['capture']['start_utc'] = '2026-10-10T09:00:00.900000+00:00'
        request['market']['capture']['end_utc'] = '2026-10-10T09:00:01+00:00'
        request['risk']['captured_at'] = request['market']['capture']['end_utc']
        self.assertEqual(validate_evidence_request(request), request)
        self.assertNotEqual(request['market']['tick']['time'], int(datetime.fromisoformat(request['risk']['captured_at']).timestamp()))

    def test_cent_prices_normalize_without_requiring_canonical_price_text(self):
        request = capture_request()
        request['market']['tick']['bid'] = '60000.0000'
        request['market']['tick']['ask'] = '60010.0100'
        self.assertEqual(validate_evidence_request(request), request)

    def test_unknown_cost_bound_stays_null_and_is_not_a_wire_error(self):
        request = capture_request()
        request['spec']['cost_bound_cents'] = None
        request['risk']['broker_contract_sha256'] = contract_hash(request['spec'])
        self.assertIsNone(validate_evidence_request(request)['spec']['cost_bound_cents'])

    def test_contract_hash_excludes_timestamp_and_is_exact_sorted_compact_json(self):
        spec = capture_request()['spec']
        facts = {k: v for k, v in spec.items() if k != 'verified_at'}
        expected = hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(contract_hash(spec), expected)
        spec['verified_at'] = '2026-10-11T12:00:00+00:00'
        self.assertEqual(contract_hash(spec), expected)
        spec['cost_bound_cents'] += 1
        self.assertNotEqual(contract_hash(spec), expected)

    def test_forged_contract_hash_is_rejected(self):
        request = capture_request()
        request['risk']['broker_contract_sha256'] = '0' * 64
        self.rejected(validate_evidence_request, request)

    def test_unknown_missing_duplicate_and_prototype_keys_reject(self):
        for mutation in ('extra', 'missing', 'prototype'):
            with self.subTest(mutation=mutation):
                request = capture_request()
                if mutation == 'extra': request['market']['account_id'] = 1
                elif mutation == 'missing': del request['market']['tick']['ask']
                else: request['market']['tick']['__proto__'] = {}
                self.rejected(validate_evidence_request, request)
        raw = json.dumps(bootstrap_request()).replace('"schema_version": 2', '"schema_version": 2, "schema_version": 2')
        self.rejected(validate_evidence_request, raw)

    def test_invalid_json_nonfinite_utf8_and_oversize_are_sanitized(self):
        for raw in (b'\xff', '{}junk', '{"schema_version":NaN}', '{"schema_version":1e999}', ' ' * 8193, []):
            with self.subTest(raw_type=type(raw).__name__):
                self.rejected(validate_evidence_request, raw)
        request = bootstrap_request()
        request['revision'] = float('nan')
        self.rejected(validate_evidence_request, request)

    def test_strict_types_ids_revision_sequence_and_canonical_lot(self):
        invalid = [('schema_version', True), ('session_id', 'A' * 32), ('revision', True),
                   ('revision', 2**63 - 1), ('sequence', 2**63), ('sequence', -1),
                   ('instrument', 'GOLD'), ('account_mode', 'REAL'), ('terminal_connected', 1),
                   ('lot', '0.010'), ('lot', '1e-2'), ('lot', '.01'), ('lot', '0.009'),
                   ('lot', '0.010000001'), ('lot', '100000001')]
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                request = bootstrap_request(); request[key] = value
                self.rejected(validate_evidence_request, request)

    def test_bootstrap_cannot_carry_capture_and_normal_capture_requires_nonce(self):
        request = capture_request(); request['challenge'] = None
        self.rejected(validate_evidence_request, request)
        request = capture_request(); request['sequence'] = 0
        self.rejected(validate_evidence_request, request)
        request = bootstrap_request(); request['challenge'] = 'c' * 64
        self.rejected(validate_evidence_request, request)

    def test_tick_cent_and_millisecond_consistency(self):
        for key, value in (('bid', '60000.001'), ('ask', '59999'), ('bid', '0'),
                           ('bid', 60000), ('bid', '6e4'), ('time_msc', 1791633599000), ('time', True)):
            with self.subTest(key=key, value=value):
                request = capture_request(); request['market']['tick'][key] = value
                self.rejected(validate_evidence_request, request)

    def test_capture_delta_is_positive_bounded_and_matches_monotonic(self):
        for patch in ({'end_mono_ns': 100}, {'end_mono_ns': 2_000_000_101},
                      {'end_mono_ns': 150_000_101}, {'start_mono_ns': True},
                      {'end_utc': '2026-10-10T12:00:00.900000+00:00'},
                      {'end_utc': '2026-10-10T12:00:03+00:00'}):
            with self.subTest(patch=patch):
                request = capture_request(); request['market']['capture'].update(patch)
                request['risk']['captured_at'] = request['market']['capture']['end_utc']
                self.rejected(validate_evidence_request, request)

    def test_capture_matching_tolerance_boundary_accepts(self):
        request = capture_request(); request['market']['capture']['end_mono_ns'] = 150_000_100
        self.assertEqual(validate_evidence_request(request), request)

    def test_bars_reject_missing_gapped_unclosed_unaligned_or_bad_ohlc(self):
        changes = ('missing', 'gap', 'future', 'stale', 'unaligned', 'ohlc')
        for change in changes:
            with self.subTest(change=change):
                request = capture_request(); bars = request['market']['candles']
                if change == 'missing': bars.pop()
                elif change == 'gap': bars[3]['time'] += 60
                elif change == 'future':
                    for bar in bars: bar['time'] += 60
                elif change == 'stale':
                    for bar in bars: bar['time'] -= 60
                elif change == 'unaligned':
                    for bar in bars: bar['time'] += 1
                else: bars[-1]['close'] = '60021'
                self.rejected(validate_evidence_request, request)

    def test_spec_risk_types_and_protection_are_strict(self):
        for section, key, value in (
            ('spec', 'symbol', 'GOLD'), ('spec', 'contract_size', '1.0'),
            ('spec', 'volume_min', '-0.01'), ('spec', 'volume_step', '0'),
            ('spec', 'tick_cents', True), ('spec', 'cost_bound_cents', -1),
            ('spec', 'stops_distance_cents', 0.5),
            ('risk', 'captured_at', '2026-10-10T12:00:01Z'),
            ('risk', 'strategy_verified', 1), ('risk', 'daily_loss_remaining_cents', 50001),
            ('risk', 'position_open', True), ('risk', 'policy_version', 'g' * 64),
        ):
            with self.subTest(section=section, key=key):
                request = capture_request(); request[section][key] = value
                self.rejected(validate_evidence_request, request)

    def test_claim_only_optional_clock_profile_does_not_require_verification(self):
        request = capture_request()
        request['market']['clock'] = {'status': 'PRODUCER_CLAIM_ONLY', 'offset_seconds': '0', 'uncertainty_ms': '1'}
        request['market']['clock_profile'] = {'profile_id': 'candidate-id', 'candidate_offset_seconds': 10800, 'evidence_ref': 'review-ref'}
        self.assertEqual(validate_evidence_request(request), request)
        request['market']['clock']['status'] = 'VERIFIED'
        self.rejected(validate_evidence_request, request)

    def test_evidence_can_be_unreviewed_without_news_until_later_capture(self):
        request = capture_request(); response = evidence_response(request)
        self.assertEqual(parse_evidence_response(response, request), response)
        request['sequence'] = 2; response = evidence_response(request)
        response['tick_liveness'] = 'VERIFIED'; response['evidence']['news_id'] = '3' * 32
        self.assertEqual(parse_evidence_response(response, request), response)

    def test_evidence_response_context_schema_and_grants_reject(self):
        for key, value in (('session_id', 'f' * 32), ('sequence', 2), ('execution_authorized', True),
                           ('coverage', 'GLOBAL'), ('risk_review', 'ACCEPTED'), ('tick_liveness', 'TRUE'),
                           ('schema_version', True), ('challenge', 'f' * 32)):
            with self.subTest(key=key):
                request = capture_request(); response = evidence_response(request); response[key] = value
                self.rejected(parse_evidence_response, response, request)

    def test_challenge_times_are_utc_positive_and_bounded(self):
        for expiry in (STAMP, '2026-10-10T12:00:06.000001+00:00', '2026-10-10T12:00:05', '2026-10-10T12:00:05+01:00'):
            request = bootstrap_request(); response = evidence_response(request); response['challenge_expires_at'] = expiry
            self.rejected(parse_evidence_response, response, request)

    def test_analysis_request_requires_all_three_ids_and_operation_shape(self):
        request = analysis_request(); self.assertEqual(validate_analysis_request(request), request)
        for key, value in (('operation_key', 'short'), ('operation_key', 'x' * 81), ('operation_key', 'spaces are forbidden'),
                           ('command_id', None), ('schema_version', 1)):
            with self.subTest(key=key):
                request = analysis_request(); request[key] = value
                self.rejected(validate_analysis_request, request)
        request = analysis_request(); request['evidence']['news_id'] = None
        self.rejected(validate_analysis_request, request)

    def test_decision_id_uses_complete_canonical_request_not_order(self):
        request = analysis_request()
        expected = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:32]
        self.assertEqual(decision_id(request), expected)
        self.assertEqual(decision_id(dict(reversed(list(request.items())))), expected)
        for key, value in (('lot', '0.02'), ('revision', 2), ('operation_key', 'another-operation-123')):
            changed = dict(request); changed[key] = value
            self.assertNotEqual(decision_id(changed), expected)

    def test_ready_without_authority_and_bounded_true_both_parse(self):
        for authorized in (False, True):
            request = analysis_request(); response = analysis_response(request, authorized=authorized)
            self.assertEqual(parse_analysis_response(json.dumps(response).encode(), request), response)

    def test_analysis_echo_context_and_decision_hash_must_match(self):
        for key, value in (('session_id', 'f' * 32), ('command_id', 'f' * 32), ('revision', 2),
                           ('revision', True), ('operation_key', 'another-operation-123'), ('decision_id', 'f' * 32),
                           ('evidence', {'market_id': '4' * 32, 'news_id': '3' * 32, 'spec_id': '2' * 32})):
            with self.subTest(key=key):
                request = analysis_request(); response = analysis_response(request); response[key] = value
                self.rejected(parse_analysis_response, response, request)

    def test_all_documented_blocked_outcomes_are_non_authorizing(self):
        for outcome in BLOCKED_OUTCOMES:
            with self.subTest(outcome=outcome):
                request = analysis_request(); response = analysis_response(request)
                response.update(outcome=outcome, risk_state='BLOCKED', decision=None)
                self.assertEqual(parse_analysis_response(response, request), response)
                response.update(execution_authorized=True, authorization_expires_at='2026-10-10T12:00:05Z')
                self.rejected(parse_analysis_response, response, request)

    def test_model_wait_has_null_sltp_and_no_grant(self):
        request = analysis_request(); response = analysis_response(request)
        response.update(outcome='MODEL_WAIT', risk_state='BLOCKED')
        response['decision'].update(decision='WAIT', stop_cents=None, target_cents=None, news_risk='UNKNOWN')
        self.assertEqual(parse_analysis_response(response, request), response)
        response['decision']['stop_cents'] = 100
        self.rejected(parse_analysis_response, response, request)

    def test_ready_requires_sltp_int_cents_low_news_and_current_model(self):
        for key, value in (('stop_cents', True), ('stop_cents', 0), ('target_cents', '6041000'),
                           ('target_cents', 6041000.0), ('reason', ''), ('reason', 'a' * 401),
                           ('invalidation', 'a' * 241), ('news_risk', 'HIGH'), ('decision', 'WAIT')):
            with self.subTest(key=key):
                request = analysis_request(); response = analysis_response(request); response['decision'][key] = value
                self.rejected(parse_analysis_response, response, request)
        for key, value in (('model', 'gpt-6-astra'), ('reasoning', 'high'), ('instrument', 'GOLD'), ('news_coverage', 'GLOBAL')):
            request = analysis_request(); response = analysis_response(request); response[key] = value
            self.rejected(parse_analysis_response, response, request)

    def test_authorization_flag_is_strict_and_expiry_consistent(self):
        for authorized, expiry in ((1, None), (False, '2026-10-10T12:00:05Z'), (True, None),
                                  (True, STAMP), (True, '2026-10-10T12:00:00Z')):
            request = analysis_request(); response = analysis_response(request)
            response.update(execution_authorized=authorized, authorization_expires_at=expiry)
            self.rejected(parse_analysis_response, response, request)

    def test_unknown_and_non200_fixed_error_shapes_never_form_authority(self):
        request = analysis_request(); response = analysis_response(request); response['outcome'] = 'UNKNOWN_FUTURE_OUTCOME'
        self.rejected(parse_analysis_response, response, request)
        self.rejected(parse_analysis_response, {'outcome': 'FIXED_ERROR_CODE'}, request)

    def test_returned_dict_is_detached_from_caller_input(self):
        request = analysis_request(); response = analysis_response(request)
        parsed = parse_analysis_response(response, request)
        response['decision']['stop_cents'] = 1
        self.assertEqual(parsed['decision']['stop_cents'], 5981000)


if __name__ == '__main__':
    unittest.main()
