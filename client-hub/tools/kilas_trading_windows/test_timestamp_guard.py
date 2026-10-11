"""Synthetic offline boundaries only; no actual XM offset is authorized."""
import unittest
from timestamp_guard import Profile, normalize


class TimestampGuardTests(unittest.TestCase):
    now = 1791283200000
    source = "synthetic-demo"

    def setUp(self):
        self.utc = Profile(self.source, "synthetic-utc", "test fixture", 0, self.now - 1000000, self.now + 1000000)

    def check_status(self, raw, status, profiles=None, **kwargs):
        self.assertEqual(normalize(raw, self.now, self.source, (self.utc,) if profiles is None else profiles, **kwargs)["status"], status)

    def test_missing_profile(self):
        self.check_status(self.now, "unknown_source_time", profiles=())

    def test_actual_observed_three_hour_future_rejected_under_utc(self):
        wider = Profile(self.source, "utc", "test fixture", 0, self.now - 86400000, self.now + 86400000)
        self.check_status(self.now + 10800000, "future_timestamp", profiles=(wider,))

    def test_future_boundaries(self):
        self.check_status(self.now + 2000, "accepted")
        self.check_status(self.now + 2001, "future_timestamp")

    def test_stale_boundaries(self):
        self.check_status(self.now - 60000, "accepted")
        self.check_status(self.now - 60001, "stale_timestamp")

    def test_synthetic_evidence_backed_offset(self):
        profile = Profile(self.source, "synthetic-offset", "test fixture only", 10800, self.now - 1000, self.now + 1000)
        result = normalize(self.now + 10800000, self.now, self.source, (profile,))
        self.assertEqual(result["event_utc_ms"], self.now)

    def test_expired_profile(self):
        profile = Profile(self.source, "expired", "test fixture", 0, self.now - 100, self.now)
        self.check_status(self.now, "unknown_source_time", profiles=(profile,))

    def test_wrong_source(self):
        profile = Profile("other-server", "wrong", "test fixture", 0, self.now - 100, self.now + 100)
        self.check_status(self.now, "unknown_source_time", profiles=(profile,))

    def test_missing_evidence(self):
        profile = Profile(self.source, "unverified", "", 10800, self.now - 100, self.now + 100)
        self.check_status(self.now + 10800000, "unknown_source_time", profiles=(profile,))

    def test_overlapping_profiles_fail_closed(self):
        self.check_status(self.now, "ambiguous_source_time", profiles=(self.utc, self.utc))

    def test_dst_gap_and_fold(self):
        # Explicit synthetic segments: repeated wall time yields two UTC candidates.
        before = Profile(self.source, "before", "fixture", 3600, self.now - 10000000, self.now)
        after = Profile(self.source, "after", "fixture", 0, self.now, self.now + 10000000)
        self.check_status(self.now + 1000, "ambiguous_source_time", profiles=(before, after))
        # Spring-forward wall-clock gap yields no candidate.
        before2 = Profile(self.source, "before", "fixture", 0, self.now - 10000000, self.now)
        after2 = Profile(self.source, "after", "fixture", 3600, self.now, self.now + 10000000)
        self.check_status(self.now + 1000, "unknown_source_time", profiles=(before2, after2))

    def test_invalid_timestamps(self):
        for raw in (0, -1, None, True, float("nan"), float("inf"), "1791283200000"):
            self.check_status(raw, "invalid_timestamp")

    def test_unit_mismatch(self):
        self.check_status(self.now, "inconsistent_units", raw_seconds=self.now)
        self.check_status(self.now, "accepted", raw_seconds=self.now // 1000)


if __name__ == "__main__":
    unittest.main()
