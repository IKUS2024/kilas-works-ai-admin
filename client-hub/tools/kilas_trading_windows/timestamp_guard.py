"""Offline validation prototype, not a deployed bridge. No active XM profile.

An offset is allowed only under an evidence-backed, source-bound profile with
an explicit UTC validity interval. Never infer it from current quote age.
Historical DST segments require separate profiles; overlaps fail closed.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    source: str
    profile_id: str
    evidence: str
    offset_seconds: int
    valid_from_utc_ms: int
    valid_until_utc_ms: int


def normalize(raw_ms, received_ms, source, profiles=(), *, max_age_ms=60000,
              future_tolerance_ms=2000, raw_seconds=None):
    """Return UTC milliseconds only after source and freshness validation.

    60s age/2s future thresholds are example test policy, not cloud contract.
    Receive time must independently be trustworthy; it cannot replace event time.
    """
    if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (raw_ms, received_ms)):
        return {"status": "invalid_timestamp"}
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in (max_age_ms, future_tolerance_ms)):
        return {"status": "invalid_policy"}
    if raw_seconds is not None and (type(raw_seconds) is not int or raw_seconds != raw_ms // 1000):
        return {"status": "inconsistent_units"}
    candidates = []
    for profile in profiles:
        if profile.source != source or not profile.evidence.strip() or not profile.profile_id.strip():
            continue
        if type(profile.offset_seconds) is not int or abs(profile.offset_seconds) > 14 * 3600:
            continue
        candidate = raw_ms - profile.offset_seconds * 1000
        if profile.valid_from_utc_ms <= candidate < profile.valid_until_utc_ms:
            candidates.append((profile, candidate))
    if not candidates:
        return {"status": "unknown_source_time"}
    if len(candidates) != 1:
        return {"status": "ambiguous_source_time"}
    profile, candidate = candidates[0]
    age = received_ms - candidate
    if age < -future_tolerance_ms:
        return {"status": "future_timestamp"}
    if age > max_age_ms:
        return {"status": "stale_timestamp"}
    return {"status": "accepted", "event_utc_ms": candidate, "age_ms": age,
            "time_profile_id": profile.profile_id}
