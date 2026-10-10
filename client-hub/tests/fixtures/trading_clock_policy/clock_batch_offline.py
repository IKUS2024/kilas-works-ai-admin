"""Experimental OFFLINE evidence validator only. No sockets, MT5, or execution.
Not wired into the producer. It never grants source freshness or trading authority.
Each side contains exactly two attempts, including any timeout. Format is v2.
"""
import hashlib
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).with_name('validate_trace.py')
PIN = '6359d012d244c1098b9a58608228d1ee8c817eb49facc91b5115d8ac64992698'
if hashlib.sha256(BASE.read_bytes()).hexdigest() != PIN:
    raise ValueError('Original offline validator bytes do not match reviewed version.')
spec = importlib.util.spec_from_file_location('_kilas_pinned_clock', BASE)
policy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = policy
spec.loader.exec_module(policy)
Error = policy.TradingError
NS = 1_000_000_000
ATTEMPT_FIELDS = {'status', 'start_ns', 'end_ns', 'start_utc', 'end_utc', 'packet'}
BATCH_FIELDS = {'schema', 'session_id', 'clock_domain', 'before', 'after',
                'acquired_start_utc', 'acquired_end_utc', 'acquired_start_mono_ns',
                'acquired_end_mono_ns', 'decision_utc', 'decision_mono_ns'}


def require(condition, message):
    if not condition:
        raise Error(message)


def qualify_batch(batch):
    require(type(batch) is dict and set(batch) == BATCH_FIELDS, 'Exact v2 batch required.')
    require(batch['schema'] == 'kilas-clock-batch-offline-v2', 'Unsupported schema.')
    require(type(batch['session_id']) is str and 16 <= len(batch['session_id']) <= 64
            and batch['session_id'].isascii() and batch['session_id'].isalnum(), 'Bounded session identity required.')
    require(batch['clock_domain'] == 'ONE_PROCESS_PERF_COUNTER_NS', 'One measured clock domain required.')
    parsed = []
    attempts = []
    sides = []
    marks = []
    tokens = set()
    transmit = set()
    endpoint = None
    for name in ('before', 'after'):
        side = batch[name]
        require(type(side) is list and len(side) == 2, 'Exactly two planned attempts per side required.')
        good = []
        for a in side:
            require(type(a) is dict and set(a) == ATTEMPT_FIELDS, 'Complete attempt required.')
            start, end = policy.mono(a['start_ns']), policy.mono(a['end_ns'])
            ws, we = policy.utc(a['start_utc']), policy.utc(a['end_utc'])
            require(0 < end - start <= 600_000_000, 'Attempt duration exceeds policy or is not measured.')
            require(abs(policy.seconds(we-ws) - Decimal(end-start)/NS) <= Decimal('.050'), 'Attempt clock discrepancy.')
            if attempts:
                require(attempts[-1]['end_ns'] <= start, 'Sequential attempts required.')
            attempts.append(a)
            marks.extend(((start, ws), (end, we)))
            require(a['status'] in ('OK', 'NTP_TIMEOUT'), 'Non-timeout failure rejects whole batch.')
            if a['status'] == 'NTP_TIMEOUT':
                require(a['packet'] is None, 'Timeout cannot supply offset evidence.')
                continue
            p = a['packet']
            v = policy.packet(p)
            require(v['start'] == start and v['end'] == end and v['wall_start'] == ws and v['wall_end'] == we,
                    'Packet and attempt marks differ.')
            peer = (p['reference_host'], tuple(p['resolved_ips']), p['request_peer'], p['request_port'])
            if endpoint is None:
                endpoint = peer
            require(peer == endpoint, 'All packets must use the same resolved endpoint.')
            require(p['request_ntp_hex'] not in tokens and p['transmit_ntp_hex'] not in transmit,
                    'Duplicate request or acknowledgement.')
            tokens.add(p['request_ntp_hex']); transmit.add(p['transmit_ntp_hex'])
            good.append(p); parsed.append(v)
        require(len(good) >= 1, 'Both attempts failed on one side.')
        sides.append(good)
    start = policy.mono(batch['acquired_start_mono_ns'])
    end = policy.mono(batch['acquired_end_mono_ns'])
    decision = policy.mono(batch['decision_mono_ns'])
    first, last = attempts[0]['start_ns'], attempts[-1]['end_ns']
    require(0 < end-start <= 2*NS, 'Positive bounded acquisition required.')
    require(attempts[1]['end_ns'] <= start < end <= attempts[2]['start_ns'], 'All attempts must bracket acquisition.')
    require(last-first <= 4*NS, 'Collection including failed attempts exceeds four seconds.')
    require(last <= decision, 'Decision precedes collection completion.')
    # A timeout is not a reference reply and cannot extend the consumption lease.
    last_reply = max(p['end'] for p in parsed)
    require(decision <= last_reply + NS, 'Decision lease expired after last actual reply.')
    marks.extend(((start, policy.utc(batch['acquired_start_utc'])),
                  (end, policy.utc(batch['acquired_end_utc'])),
                  (decision, policy.utc(batch['decision_utc']))))
    marks.sort(key=lambda pair: pair[0])
    m0, w0 = marks[0]
    for m, w in marks:
        require(abs(policy.seconds(w-w0) - Decimal(m-m0)/NS) <= Decimal('.050'), 'Cumulative wall/monotonic discrepancy.')
    for (m1,w1),(m2,w2) in zip(marks, marks[1:]):
        require(abs(policy.seconds(w2-w1) - Decimal(m2-m1)/NS) <= Decimal('.050'), 'Adjacent clock discrepancy.')
    low = min(v['offset']-v['error'] for v in parsed)
    high = max(v['offset']+v['error'] for v in parsed)
    require(max(v['offset']-v['error'] for v in parsed) <= min(v['offset']+v['error'] for v in parsed), 'Not all intervals intersect.')
    require(max(v['offset'] for v in parsed)-min(v['offset'] for v in parsed) <= Decimal('.250'), 'Offsets disagree.')
    expiry = last_reply+NS
    error = (high-low)/2 + policy.DRIFT_SECONDS_PER_SECOND * Decimal(expiry-first)/NS
    require(error <= policy.MAX_UNCERTAINTY_SECONDS, 'Union uncertainty exceeds 750 ms.')
    evidence = json.dumps(batch, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()
    return {'status': 'OFFLINE_CLOCK_BATCH_VALIDATED', 'schema': batch['schema'],
            'attempt_count': 4, 'reply_count': len(parsed),
            'offset_seconds': str((low+high)/2), 'uncertainty_seconds': str(error),
            'expires_mono_ns': expiry, 'evidence_sha256': hashlib.sha256(evidence).hexdigest(),
            'assurance': 'UNAUTHENTICATED_OPERATIONAL_PAPER_ONLY',
            'source_freshness_evaluated': False, 'producer_acceptance': 'NOT_IMPLEMENTED',
            'runtime_eligible': False, 'broker_execution_allowed': False}
