"""Strict BTC DEMO v2 wire validation; no transport or execution authority.

This module validates the supplied integration contract only. Freshness against
an authenticated server clock, current owner intent and broker gates belong to
the calling runtime. Parsing execution_authorized=True is not an activation.
"""
import hashlib
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from functools import wraps

from demo_control_v2 import lot as control_lot, strict_json
from demo_integration_instruments import wire_profile


EVIDENCE_PATH = '/products/services/trading/control/btc-evidence'
ANALYSIS_PATH = '/products/services/trading/control/btc-analysis'
MODEL = 'gpt-6.1-sol'
REASONING = 'medium'
EVIDENCE_FIELDS = {
    'schema_version', 'session_id', 'revision', 'command_id', 'instrument', 'lot',
    'sequence', 'challenge', 'account_mode', 'terminal_connected', 'market', 'spec', 'risk',
}
SPEC_FIELDS = {
    'symbol', 'contract_size', 'volume_min', 'volume_max', 'volume_step',
    'tick_cents', 'stops_distance_cents', 'cost_bound_cents', 'verified_at',
}
ANALYSIS_FIELDS = {
    'schema_version', 'operation_key', 'session_id', 'revision', 'command_id',
    'instrument', 'lot', 'evidence',
}
ANALYSIS_RESPONSE_FIELDS = {
    'schema_version', 'outcome', 'instrument', 'model', 'reasoning', 'decision',
    'news_coverage', 'risk_state', 'execution_authorized', 'checked_at',
    'session_id', 'operation_key', 'revision', 'command_id', 'evidence',
    'decision_id', 'authorization_expires_at',
}
BLOCKED_OUTCOMES = frozenset({
    'COSTS_UNKNOWN', 'NOTIONAL_CAP_BLOCKED', 'VOLUME_BLOCKED', 'POLICY_BLOCKED',
    'POSITION_OPEN', 'TICK_LIVENESS_UNCONFIRMED', 'NEWS_RISK_BLOCKED', 'MODEL_WAIT',
    'SLTP_BLOCKED', 'LOSS_CAP_BLOCKED', 'MODEL_PREFLIGHT_UNAVAILABLE',
    'MODEL_RESULT_UNAVAILABLE', 'MODEL_ACCOUNTING_BLOCKED', 'POST_MODEL_GATE_BLOCKED',
})
GOLD_BLOCKED_OUTCOMES = frozenset({
    'NEWS_UNAVAILABLE', 'NEWS_STALE', 'CALENDAR_STALE', 'GOLD_NEWS_UNREVIEWED',
    'CALENDAR_UNVERIFIED', 'CALENDAR_COVERAGE_INSUFFICIENT', 'CALENDAR_EVENT_BLOCKED',
})


class BtcRejected(ValueError):
    """A fixed, sanitized failure; raw bodies never appear in the exception."""


def _need(condition):
    if not condition:
        raise BtcRejected('BTC_V2_REJECTED')


def _fixed(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except BtcRejected:
            raise
        except (ValueError, TypeError, KeyError, ArithmeticError, RecursionError):
            raise BtcRejected('BTC_V2_REJECTED') from None
    return wrapped


def _wire(raw):
    if type(raw) is dict:
        # Match the actual compact transport byte limit even for offline seams.
        raw = json.dumps(raw, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return strict_json(raw)


def _shape(value, fields):
    _need(type(value) is dict and set(value) == fields)


def _integer(value, *, minimum=0, maximum=None):
    _need(type(value) is int and value >= minimum)
    _need(maximum is None or value <= maximum)
    return value


def _hex(value, length, *, nullable=False):
    if nullable and value is None:
        return
    _need(type(value) is str and re.fullmatch('[0-9a-f]{' + str(length) + '}', value))


def _boolean(value):
    _need(type(value) is bool)


def _utc(value):
    _need(type(value) is str and len(value) <= 40)
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    _need(result.tzinfo is not None and result.utcoffset() == timedelta(0))
    return result


def _decimal(value, *, canonical=False, positive=True):
    _need(type(value) is str)
    pattern = r'(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?' if canonical else r'[0-9]+(?:\.[0-9]+)?'
    _need(re.fullmatch(pattern, value))
    result = Decimal(value)
    _need(result.is_finite() and (result > 0 if positive else result >= 0))
    return result


def _price(value):
    result = _decimal(value)
    with localcontext() as context:
        context.prec = max(28, len(value) + 3)
        cents = result * 100
        _need(cents == cents.to_integral_value())
    return result


def _lot(value):
    # The BTC contract inherits the existing control v2 lot representation.
    control_lot(value)


def _context(value, *, command_nullable=False, instrument='BTC'):
    _integer(value['schema_version'])
    _need(value['schema_version'] == 2 and value['instrument'] == wire_profile(instrument).instrument)
    _hex(value['session_id'], 32)
    _integer(value['revision'], maximum=2**63 - 2)
    _hex(value['command_id'], 32, nullable=command_nullable)
    _lot(value['lot'])


def _spec(spec, instrument='BTC'):
    _shape(spec, SPEC_FIELDS)
    _need(spec['symbol'] == wire_profile(instrument).symbol)
    for key in ('contract_size', 'volume_min', 'volume_max', 'volume_step'):
        _decimal(spec[key], canonical=True)
    _integer(spec['tick_cents'], minimum=1)
    _integer(spec['stops_distance_cents'])
    if spec['cost_bound_cents'] is not None:
        _integer(spec['cost_bound_cents'])
    _utc(spec['verified_at'])


@_fixed
def contract_hash(spec, *, instrument='BTC'):
    """Hash the exact wire spec facts, excluding the producer time claim."""
    _spec(spec,instrument)
    facts = {key: value for key, value in spec.items() if key != 'verified_at'}
    return hashlib.sha256(canonical_json(facts)).hexdigest()


@_fixed
def canonical_json(body):
    """Sorted compact UTF-8 JSON used by contract and decision fingerprints."""
    return json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _market(market, instrument='BTC'):
    _shape(market, {'symbol', 'timeframe', 'tick', 'capture', 'candles', 'clock', 'clock_profile'})
    _need(market['symbol'] == wire_profile(instrument).symbol and market['timeframe'] == 'M1')
    tick = market['tick']
    _shape(tick, {'time', 'time_msc', 'bid', 'ask'})
    _integer(tick['time'], minimum=1)
    _integer(tick['time_msc'], minimum=1)
    _need(tick['time_msc'] // 1000 == tick['time'])
    _need(_price(tick['bid']) <= _price(tick['ask']))
    capture = market['capture']
    _shape(capture, {'start_utc', 'end_utc', 'start_mono_ns', 'end_mono_ns'})
    start, end = _utc(capture['start_utc']), _utc(capture['end_utc'])
    _integer(capture['start_mono_ns'])
    _integer(capture['end_mono_ns'])
    elapsed_ns = capture['end_mono_ns'] - capture['start_mono_ns']
    _need(0 < elapsed_ns <= 2_000_000_000)
    delta = end - start
    elapsed_us = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    _need(0 < elapsed_us <= 2_000_000)
    _need(abs(elapsed_us * 1000 - elapsed_ns) <= 50_000_000)
    bars = market['candles']
    _need(type(bars) is list and len(bars) == 12)
    previous = None
    for bar in bars:
        _shape(bar, {'time', 'open', 'high', 'low', 'close'})
        _integer(bar['time'], minimum=1)
        _need(bar['time'] % 60 == 0 and (previous is None or bar['time'] - previous == 60))
        opening, high, low, close = (_price(bar[key]) for key in ('open', 'high', 'low', 'close'))
        _need(low <= min(opening, close) <= max(opening, close) <= high)
        previous = bar['time']
    _need(0 <= tick['time'] - (previous + 60) < 60)
    clock = market['clock']
    if clock is not None:
        _shape(clock, {'status', 'offset_seconds', 'uncertainty_ms'})
        _need(clock['status'] == 'PRODUCER_CLAIM_ONLY')
        _need(type(clock['offset_seconds']) is str and re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?', clock['offset_seconds']))
        _need(Decimal(clock['offset_seconds']).is_finite())
        _decimal(clock['uncertainty_ms'], positive=False)
    profile = market['clock_profile']
    if profile is not None:
        # The supplied contract does not enumerate the legacy bridge's extra
        # string/range bounds. No claim here is promoted to clock verification.
        _shape(profile, {'profile_id', 'candidate_offset_seconds', 'evidence_ref'})
        for key in ('profile_id', 'evidence_ref'):
            _need(type(profile[key]) is str and len(profile[key]) > 0)
        _need(type(profile['candidate_offset_seconds']) is int)


@_fixed
def validate_evidence_request(body, *, instrument='BTC'):
    body = _wire(body)
    _shape(body, EVIDENCE_FIELDS)
    _context(body, command_nullable=True,instrument=instrument)
    _integer(body['sequence'], maximum=2**63 - 1)
    _need(body['account_mode'] == 'DEMO')
    _boolean(body['terminal_connected'])
    if body['challenge'] is None:
        _need(all(body[key] is None for key in ('market', 'spec', 'risk')))
        return body
    _hex(body['challenge'], 64)
    _need(body['sequence'] >= 1)
    _market(body['market'],instrument)
    _spec(body['spec'],instrument)
    risk = body['risk']
    _shape(risk, {
        'captured_at', 'position_open', 'protection_active', 'daily_loss_remaining_cents',
        'strategy_verified', 'cooldown_clear', 'loss_streak_clear',
        'broker_contract_sha256', 'policy_version',
    })
    _need(risk['captured_at'] == body['market']['capture']['end_utc'])
    for key in ('position_open', 'protection_active', 'strategy_verified', 'cooldown_clear', 'loss_streak_clear'):
        _boolean(risk[key])
    _need(not risk['position_open'] or risk['protection_active'])
    _integer(risk['daily_loss_remaining_cents'], maximum=50000)
    _hex(risk['broker_contract_sha256'], 64)
    _hex(risk['policy_version'], 64)
    _need(risk['broker_contract_sha256'] == contract_hash(body['spec'],instrument=instrument))
    return body


def _evidence_ids(evidence, *, news_nullable=False):
    _shape(evidence, {'market_id', 'spec_id', 'news_id'})
    for key in ('market_id', 'spec_id', 'news_id'):
        _hex(evidence[key], 32, nullable=news_nullable and key == 'news_id')


@_fixed
def parse_evidence_response(raw, request, *, instrument='BTC'):
    request = validate_evidence_request(request,instrument=instrument)
    response = _wire(raw)
    bootstrap = request['challenge'] is None
    fields = {'schema_version', 'outcome', 'sequence', 'challenge', 'challenge_expires_at', 'received_at', 'execution_authorized'}
    if not bootstrap:
        fields |= {'session_id', 'evidence', 'coverage', 'risk_review', 'tick_liveness'}
    _shape(response, fields)
    _integer(response['schema_version'])
    _need(response['schema_version'] == 2)
    _need(response['execution_authorized'] is False)
    _integer(response['sequence'], maximum=2**63 - 1)
    _hex(response['challenge'], 64)
    received, expires = _utc(response['received_at']), _utc(response['challenge_expires_at'])
    _need(timedelta(0) < expires - received <= timedelta(seconds=5))
    if bootstrap:
        _need(response['outcome'] == 'CAPTURE_CHALLENGE_ISSUED')
    else:
        _need(response['outcome'] == 'EVIDENCE_ACCEPTED')
        _need(response['session_id'] == request['session_id'] and response['sequence'] == request['sequence'])
        _evidence_ids(response['evidence'], news_nullable=True)
        _need(response['coverage'] == wire_profile(instrument).coverage)
        _need(response['risk_review'] in ('UNREVIEWED', 'SERVER_REVIEWED'))
        _need(response['tick_liveness'] in ('UNCONFIRMED', 'VERIFIED'))
    return response


@_fixed
def validate_analysis_request(body, *, instrument='BTC'):
    body = _wire(body)
    _shape(body, ANALYSIS_FIELDS)
    _context(body,instrument=instrument)
    _need(type(body['operation_key']) is str and re.fullmatch(r'[A-Za-z0-9_-]{16,80}', body['operation_key']))
    _evidence_ids(body['evidence'])
    return body


@_fixed
def decision_id(request, *, instrument='BTC'):
    return hashlib.sha256(canonical_json(validate_analysis_request(request,instrument=instrument))).hexdigest()[:32]


def _decision(decision):
    _shape(decision, {'decision', 'reason', 'invalidation', 'stop_cents', 'target_cents', 'news_risk'})
    _need(decision['decision'] in ('BUY', 'SELL', 'WAIT'))
    _need(type(decision['reason']) is str and 1 <= len(decision['reason']) <= 400)
    _need(type(decision['invalidation']) is str and len(decision['invalidation']) <= 240)
    _need(decision['news_risk'] in ('LOW', 'HIGH', 'UNKNOWN'))
    if decision['decision'] == 'WAIT':
        _need(decision['stop_cents'] is None and decision['target_cents'] is None)
    else:
        _integer(decision['stop_cents'], minimum=1)
        _integer(decision['target_cents'], minimum=1)


@_fixed
def parse_analysis_response(raw, request, *, instrument='BTC'):
    request = validate_analysis_request(request,instrument=instrument)
    response = _wire(raw)
    _shape(response, ANALYSIS_RESPONSE_FIELDS)
    _integer(response['schema_version'])
    _need(response['schema_version'] == 2 and response['instrument'] == wire_profile(instrument).instrument)
    _need(response['model'] == MODEL and response['reasoning'] == REASONING)
    _need(response['news_coverage'] == wire_profile(instrument).coverage)
    for key in ('session_id', 'operation_key', 'revision', 'command_id', 'evidence'):
        _need(response[key] == request[key])
    _integer(response['revision'], maximum=2**63 - 2)
    _need(response['decision_id'] == decision_id(request,instrument=instrument))
    checked = _utc(response['checked_at'])
    _boolean(response['execution_authorized'])
    if response['decision'] is not None:
        _decision(response['decision'])
    if response['outcome'] == 'PROPOSAL_READY':
        _need(response['risk_state'] == 'PASSED' and response['decision'] is not None)
        _need(response['decision']['decision'] in ('BUY', 'SELL') and response['decision']['news_risk'] == 'LOW')
    else:
        outcomes = BLOCKED_OUTCOMES | GOLD_BLOCKED_OUTCOMES if instrument=='GOLD' else BLOCKED_OUTCOMES
        _need(response['outcome'] in outcomes and response['risk_state'] == 'BLOCKED')
        _need(response['execution_authorized'] is False)
    if response['execution_authorized']:
        _need(response['outcome'] == 'PROPOSAL_READY')
        _need(_utc(response['authorization_expires_at']) > checked)
    else:
        _need(response['authorization_expires_at'] is None)
    return response
