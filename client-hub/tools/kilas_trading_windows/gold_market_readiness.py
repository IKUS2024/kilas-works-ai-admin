"""Local, read-only GOLD evidence gate; never execution authority.

Only a trusted local collector may construct these records from verified broker
session/clock evidence. They are not a server schema or an input-dict decoder.
OPEN bounds describe one trading session; CLOSED bounds describe a verified
closure. Refresh either proof within five minutes. No active time profile or
session schedule is supplied here, and receipt time never replaces source time.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite

from demo_auto_controller import Blocked
from timestamp_guard import Profile, normalize


@dataclass(frozen=True)
class GoldSessionEvidence:
    symbol: str
    state: str  # OPEN / CLOSED / UNKNOWN
    source: str
    session_id: str
    start_utc: datetime
    end_utc: datetime
    observed_at: float
    valid_until_at: float
    verified: bool


@dataclass(frozen=True)
class GoldMarketEvidence:
    symbol: str
    session_id: str
    source: str
    captured_at: float
    quote_raw_msc: int
    quote_utc: datetime
    latest_m5_raw_open_epoch: int
    latest_m5_close_utc: datetime
    source_clock_utc_verified: bool
    normalization_profile: Profile
    closed_m5_verified: bool


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_SESSION = 'MARKET_SESSION_UNVERIFIED'
_MARKET = 'MARKET_EVIDENCE_UNVERIFIED'


def _need(value, code):
    if not value:
        raise Blocked(code)


def _mono(value):
    try:
        return type(value) in (int, float) and isfinite(value) and value >= 0
    except OverflowError:
        return False


def _utc(value):
    return (type(value) is datetime and value.tzinfo is not None
            and value.utcoffset() == timedelta(0) and value > _EPOCH)


def _text(value, maximum=160):
    return type(value) is str and 0 < len(value.strip()) <= maximum


def _profile(market):
    profile = market.normalization_profile
    _need(type(profile) is Profile and profile.source == market.source
          and _text(profile.profile_id) and _text(profile.evidence, 2048)
          and type(profile.offset_seconds) is int and abs(profile.offset_seconds) <= 14*3600
          and type(profile.valid_from_utc_ms) is int and profile.valid_from_utc_ms > 0
          and type(profile.valid_until_utc_ms) is int
          and profile.valid_until_utc_ms > profile.valid_from_utc_ms, _MARKET)
    return profile


def _normalized(raw, market, utc_now, maximum_ms):
    _need(type(raw) is int and raw > 0, _MARKET)
    profile = _profile(market)
    elapsed = utc_now-_EPOCH
    received_ms = (elapsed.days*86400+elapsed.seconds)*1000+elapsed.microseconds//1000
    result = normalize(raw, received_ms, market.source, (profile,),
                       max_age_ms=maximum_ms, future_tolerance_ms=0)
    _need(result.get('status') == 'accepted', _MARKET)
    return _EPOCH+timedelta(milliseconds=result['event_utc_ms'])


def validate_gold_quote(market, raw_quote_msc, *, utc_now, max_quote_age=1.5):
    """Bind the actual quote used by risk math to an already checked proof.

    Advancing source timestamps are allowed; regressions and stale/future raw
    timestamps are rejected. Call validate_gold_evidence first and again after
    calculations to check the complete proof and its monotonic lease.
    """
    _need(type(market) is GoldMarketEvidence and market.symbol == 'GOLD'
          and _text(market.source) and market.source_clock_utc_verified is True
          and _utc(utc_now) and _mono(max_quote_age) and 0 < max_quote_age <= 1.5
          and type(market.quote_raw_msc) is int and market.quote_raw_msc > 0
          and type(raw_quote_msc) is int and raw_quote_msc >= market.quote_raw_msc, _MARKET)
    actual_utc = _normalized(raw_quote_msc, market, utc_now, int(max_quote_age*1000))
    _need(0 <= (utc_now-actual_utc).total_seconds() < max_quote_age, _MARKET)


def validate_gold_evidence(session, market, *, now, utc_now, max_quote_age=1.5):
    """Return None for qualified local evidence, otherwise a fixed Blocked code.

    Success permits only subsequent read-only proposal assessment. It does not
    establish reviewed strategy, fee policy, risk limits or order permission.
    Session and market proofs must share a collector-controlled session binding.
    """
    _need(type(session) is GoldSessionEvidence and _mono(now) and _utc(utc_now), _SESSION)
    _need(session.symbol == 'GOLD' and session.state in ('OPEN', 'CLOSED')
          and session.verified is True and _text(session.source) and _text(session.session_id)
          and _utc(session.start_utc) and _utc(session.end_utc)
          and session.start_utc <= utc_now < session.end_utc
          and _mono(session.observed_at) and _mono(session.valid_until_at)
          and 0 < session.valid_until_at-session.observed_at <= 300
          and session.observed_at <= now < session.valid_until_at, _SESSION)
    if session.state == 'CLOSED':
        raise Blocked('MARKET_CLOSED')

    _need(_mono(max_quote_age) and 0 < max_quote_age <= 1.5, _MARKET)
    _need(type(market) is GoldMarketEvidence, _MARKET)
    _need(market.symbol == 'GOLD' and market.session_id == session.session_id
          and _text(market.source) and market.source_clock_utc_verified is True
          and market.closed_m5_verified is True and _mono(market.captured_at)
          and session.observed_at <= market.captured_at <= now
          and now-market.captured_at < max_quote_age
          and _utc(market.quote_utc) and _utc(market.latest_m5_close_utc), _MARKET)
    quote_age = (utc_now-market.quote_utc).total_seconds()
    bar_age = (utc_now-market.latest_m5_close_utc).total_seconds()
    _need(0 <= quote_age < max_quote_age and 0 <= bar_age < 300
          and session.start_utc <= market.quote_utc < session.end_utc
          and session.start_utc <= market.latest_m5_close_utc-timedelta(seconds=300)
          and market.latest_m5_close_utc <= market.quote_utc
          and market.latest_m5_close_utc.minute % 5 == 0
          and market.latest_m5_close_utc.second == 0
          and market.latest_m5_close_utc.microsecond == 0, _MARKET)

    _need(type(market.latest_m5_raw_open_epoch) is int
          and market.latest_m5_raw_open_epoch > 0, _MARKET)
    for raw, claimed, age_ms in (
            (market.quote_raw_msc, market.quote_utc, int(max_quote_age*1000)),
            (market.latest_m5_raw_open_epoch*1000,
             market.latest_m5_close_utc-timedelta(seconds=300), 600000),
            ((market.latest_m5_raw_open_epoch+300)*1000, market.latest_m5_close_utc, 300000)):
        _need(claimed == _normalized(raw, market, utc_now, age_ms), _MARKET)
