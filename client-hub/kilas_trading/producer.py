"""Offline acceptance skeleton for the existing market-only observation contract.

Not installed as analysis.market_source. A valid observation is still not a
trusted, current market snapshot; this module cannot enable any runtime gate.
The collector mapping uses the reviewed ReadOnlyMT5.market_snapshot shape only.
No account/report payload is stored.
"""
import json
from datetime import datetime
from . import analysis, observation


# Evidence categories, not client-settable verification flags. Their concrete
# broker provenance/verification contract awaits inspection of the collector.
MISSING_EVIDENCE = (
    'DEMO_SOURCE_BINDING',
    'GOLD_XAUUSD_MAPPING',
    'PRICE_AND_CONTRACT_UNITS',
    'BROKER_LOT_RULES',
    'UTC_CAPTURE_CLOCK',
    'BROKER_TIME_PROFILE',
    'CLOSED_CANDLE_SEMANTICS',
    'CURRENT_SOURCE_FRESHNESS',
)


def project_collector_market(market):
    """Project an in-process ReadOnlyMT5.market_snapshot result to v1 bytes.

    Not a report upload/parser or freshness acceptance. Ignore specs, calls,
    session/server identifiers and diagnostic details; never serialize them.
    Retain raw tick/bar epochs and raw capture UTC without clock correction.
    A declared canonical_symbol is deliberately not propagated as proof.
    """
    def require(ok):
        if not ok:
            raise observation.TradingError('Collector market shape unavailable/unqualified.')

    require(type(market) is dict)
    require(market.get('status') == 'READ_ONLY_MARKET_UNQUALIFIED')
    require(market.get('input_kind') == 'DEMO_OBSERVATION' and market.get('account_mode') == 'DEMO')
    require(all(market.get(k) is False for k in
                ('runtime_eligible', 'broker_execution_allowed', 'ai_analysis', 'paper_execution')))
    require(market.get('symbol') == 'GOLD' and market.get('timeframe') == 'M1')
    require(market.get('source_time_status') == 'UNQUALIFIED'
            and market.get('candle_semantics') == 'OPEN_TIME_CANDIDATE_NOT_VERIFIED'
            and 'clock_evidence' in market and market['clock_evidence'] is None)
    tick = market.get('tick'); sample = market.get('sample'); bars = market.get('candles')
    require(type(tick) is dict and set(tick) == {'time', 'time_msc', 'bid', 'ask'})
    sample_fields = {'kind', 'time', 'time_msc', 'acquired_start_utc', 'acquired_end_utc',
                     'acquired_start_mono_ns', 'acquired_end_mono_ns'}
    require(type(sample) is dict and set(sample) == sample_fields and sample['kind'] == 'DEMO_OBSERVATION')
    require(type(bars) is list and 12 <= len(bars) <= 13)
    require(all(type(tick[k]) is int and type(sample[k]) is int and 0 < tick[k] < 10**15 and tick[k] == sample[k]
                for k in ('time', 'time_msc')))
    require(all(type(tick[k]) is str and len(tick[k]) <= 24 for k in ('bid', 'ask')))
    start = sample['acquired_start_mono_ns']; end = sample['acquired_end_mono_ns']
    require(type(start) is int and type(end) is int and 0 <= start < end < 2**63
            and end-start <= 2000000000)
    captures = []
    for key in ('acquired_start_utc', 'acquired_end_utc'):
        value = sample[key]
        require(type(value) is str and len(value) <= 40)
        try:
            date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            raise observation.TradingError('Collector capture timestamp invalid.') from None
        require(date.tzinfo is not None and date.utcoffset().total_seconds() == 0)
        captures.append(date)
    elapsed = captures[1]-captures[0]
    elapsed_us = elapsed.days*86400000000 + elapsed.seconds*1000000 + elapsed.microseconds
    require(elapsed_us > 0 and abs(elapsed_us*1000 - (end-start)) <= 50000000)
    # This check mirrors raw M1 candidate selection, not UTC closure/freshness.
    for bar in bars:
        require(type(bar) is dict and set(bar) == {'time', 'open', 'high', 'low', 'close'})
        require(type(bar['time']) is int and bar['time'] % 60 == 0 and bar['time']+60 <= tick['time'])
        require(all(type(bar[k]) is str and len(bar[k]) <= 24 for k in ('open', 'high', 'low', 'close')))
    require(0 <= tick['time'] - (bars[-1]['time']+60) < 60)
    raw = {'schema_version': 1, 'kind': 'DEMO', 'source_symbol': 'GOLD',
           'bid': tick['bid'], 'ask': tick['ask'], 'time': tick['time'], 'time_msc': tick['time_msc'],
           'observed_at_utc': sample['acquired_end_utc'], 'timeframe': 'M1',
           'candles': [{k: bar[k] for k in ('time', 'open', 'high', 'low', 'close')} for bar in bars]}
    # Reuse the original size/privacy/decimal/interval contract. This cannot
    # ingest a full diagnostic report or weaken the existing upload endpoint.
    try:
        data = json.dumps(raw, allow_nan=False, separators=(',', ':')).encode('utf-8')
    except (ValueError, TypeError, OverflowError):
        raise observation.TradingError('Collector market numeric shape invalid.') from None
    observation.parse_file(data)
    return data


def _status(outcome, reason, *, valid=False, candle_count=0):
    # Fresh scalar projection: never return reader bytes, quotes, identifiers,
    # arbitrary producer fields or an analysis-compatible connected snapshot.
    return {
        'outcome': outcome,
        'reason': reason,
        'market_only_candidate_valid': valid,
        'candle_count': candle_count,
        'producer_acceptance': 'NOT_IMPLEMENTED',
        'missing_evidence': list(MISSING_EVIDENCE),
        'connected': False,
        'runtime_eligible': False,
        'broker_execution_allowed': False,
        'ai_analysis': False,
        'paper_execution': False,
        'policy_replay_only': True,
    }


class OfflineMarketProducer:
    """Reader is a server-owned callable: reader(user) -> market-only bytes.

    This dependency seam performs no transport, retention or user binding of
    its own. The eventual reader must enforce tenant ownership independently.
    There is deliberately no registration, environment switch or approval flag.
    """

    def __init__(self, reader=None):
        self._reader = reader

    @classmethod
    def from_collector(cls, reader):
        """Server-owned reader(user) returns the reviewed market dict only.

        No SDK invocation is supplied here. Tenant binding and actual producer
        evidence remain the caller's responsibility and are never inferred.
        """
        return cls(lambda user: project_collector_market(reader(user)))

    def acceptance(self, user):
        if self._reader is None:
            return _status('UNAVAILABLE', 'NO_PRODUCER_READER')
        try:
            raw = self._reader(user)
        except observation.TradingError:
            return _status('REJECTED', 'INVALID_MARKET_ONLY_CANDIDATE')
        except Exception:
            # A connector exception could include credentials or paths. Do not
            # surface it, retain it or log its content.
            return _status('UNAVAILABLE', 'PRODUCER_READ_FAILED')
        try:
            candidate = observation.parse_file(raw)
        except observation.TradingError:
            return _status('REJECTED', 'INVALID_MARKET_ONLY_CANDIDATE')
        # parse_file intentionally leaves mapping/event time/freshness unknown.
        # No subtraction of a guessed broker offset and no inferred bar close.
        return _status(
            'BLOCKED', 'SOURCE_EVIDENCE_NOT_VERIFIED', valid=True,
            candle_count=len(candidate.get('candles', [])),
        )

    def snapshot(self, user):
        status = self.acceptance(user)
        # This is the exact interface the existing analyst consumes. It must
        # fail even for a fresh-looking candidate or a WITHIN_CAP scenario.
        raise analysis.Unavailable('Producer market-only belum diterima: ' + status['reason'])
