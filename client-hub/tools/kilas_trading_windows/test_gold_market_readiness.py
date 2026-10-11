"""Synthetic local evidence only: no SDK, network, model or order calls."""
import unittest
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import datetime, timedelta, timezone

from demo_auto_controller import Blocked
from gold_market_readiness import (GoldSessionEvidence, GoldMarketEvidence,
                                   validate_gold_evidence, validate_gold_quote)
from timestamp_guard import Profile


UTC_NOW = datetime(2026, 10, 12, 11, 2, tzinfo=timezone.utc)
NOW = 100.0


def fixture():
    start = UTC_NOW.replace(hour=10, minute=0)
    end = UTC_NOW.replace(hour=12, minute=0)
    session = GoldSessionEvidence('GOLD', 'OPEN', 'fixture:broker-session', 'fixture-session',
                                  start, end, 99.0, 159.0, True)
    profile = Profile('fixture:broker-market', 'fixture-time-profile', 'Synthetic reviewed clock proof',
                      10800, int(start.timestamp()*1000), int(end.timestamp()*1000))
    quote = UTC_NOW-timedelta(milliseconds=500)
    close = UTC_NOW.replace(minute=0)
    market = GoldMarketEvidence('GOLD', session.session_id, profile.source, 99.75,
                               int(quote.timestamp()*1000)+10800000, quote,
                               int((close-timedelta(minutes=5)).timestamp())+10800, close,
                               True, profile, True)
    return session, market


class GoldReadinessTests(unittest.TestCase):
    def check(self, session, market, code='MARKET_EVIDENCE_UNVERIFIED', **kwargs):
        with self.assertRaisesRegex(Blocked, '^'+code+'$'):
            validate_gold_evidence(session, market, now=NOW, utc_now=UTC_NOW, **kwargs)

    def test_verified_open_evidence_and_frozen_records(self):
        session, market = fixture()
        self.assertIsNone(validate_gold_evidence(session, market, now=NOW, utc_now=UTC_NOW))
        for obj in (session, market):
            with self.assertRaises(FrozenInstanceError):
                obj.symbol = 'BTCUSD'

    def test_verified_closed_does_not_inspect_market_or_quote_policy(self):
        session, _ = fixture()
        self.check(replace(session, state='CLOSED'), object(), 'MARKET_CLOSED', max_quote_age=None)

    def test_session_missing_stale_unknown_or_unbound(self):
        session, market = fixture()
        invalid = [None, asdict(session)]
        for changes in ({'symbol': 'BTCUSD'}, {'state': 'UNKNOWN'}, {'verified': False},
                        {'verified': 1}, {'source': ''}, {'session_id': ''},
                        {'observed_at': 101.0}, {'valid_until_at': NOW},
                        {'observed_at': 0.0, 'valid_until_at': 301.0},
                        {'start_utc': UTC_NOW+timedelta(seconds=1)}, {'end_utc': UTC_NOW},
                        {'start_utc': session.start_utc.replace(tzinfo=None)}):
            invalid.append(replace(session, **changes))
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                self.check(candidate, market, 'MARKET_SESSION_UNVERIFIED')

    def test_stale_closed_proof_is_unverified(self):
        session, _ = fixture()
        self.check(replace(session, state='CLOSED', valid_until_at=NOW), None,
                   'MARKET_SESSION_UNVERIFIED')

    def test_market_typed_binding_and_clock_proof_required(self):
        session, market = fixture()
        invalid = [None, asdict(market)]
        for changes in ({'symbol': 'BTCUSD'}, {'session_id': 'previous-session'},
                        {'source': 'other-source'}, {'source_clock_utc_verified': False},
                        {'source_clock_utc_verified': 1}, {'closed_m5_verified': False},
                        {'normalization_profile': asdict(market.normalization_profile)},
                        {'quote_utc': market.quote_utc.replace(tzinfo=None)}):
            invalid.append(replace(market, **changes))
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                self.check(session, candidate)

    def test_capture_and_actual_quote_age_are_independent(self):
        session, market = fixture()
        for changes in ({'captured_at': NOW-1.5}, {'captured_at': NOW+.01},
                        {'quote_utc': UTC_NOW-timedelta(seconds=1.5)},
                        {'quote_utc': UTC_NOW+timedelta(milliseconds=1)},
                        {'captured_at': float('nan')}):
            with self.subTest(changes=changes):
                self.check(session, replace(market, **changes))

    def test_old_raw_quote_cannot_be_relabelled_with_receipt_time(self):
        session, market = fixture()
        self.check(session, replace(market, quote_raw_msc=market.quote_raw_msc-86400000,
                                    quote_utc=UTC_NOW, captured_at=NOW))

    def test_raw_bar_open_cannot_be_relabelled_as_normalized_close(self):
        session, market = fixture()
        # A fresh claimed close cannot replace yesterday's actual source bar.
        self.check(session, replace(market, latest_m5_raw_open_epoch=
                                    market.latest_m5_raw_open_epoch-86400))
        # Feeding a raw close where the collector promises raw open adds 5 min.
        self.check(session, replace(market, latest_m5_raw_open_epoch=
                                    market.latest_m5_raw_open_epoch+300))

    def test_latest_closed_bar_must_be_closed_fresh_aligned_and_inside_session(self):
        session, market = fixture()
        for close in (UTC_NOW-timedelta(minutes=5), UTC_NOW+timedelta(minutes=3),
                      UTC_NOW-timedelta(seconds=1)):
            self.check(session, replace(market, latest_m5_close_utc=close))
        # The first bar cannot straddle a verified session opening.
        self.check(replace(session, start_utc=UTC_NOW.replace(hour=10, minute=58)), market)

    def test_profile_source_validity_and_fields_fail_closed(self):
        session, market = fixture()
        profile = market.normalization_profile
        for changes in ({'source': 'BTCUSD'}, {'evidence': ''}, {'offset_seconds': True},
                        {'valid_until_utc_ms': int((UTC_NOW-timedelta(seconds=1)).timestamp()*1000)},
                        {'valid_from_utc_ms': int((market.latest_m5_close_utc-timedelta(minutes=2)).timestamp()*1000)},
                        {'valid_from_utc_ms': int(UTC_NOW.timestamp()*1000)}):
            with self.subTest(changes=changes):
                self.check(session, replace(market, normalization_profile=replace(profile, **changes)))

    def test_policy_cannot_relax_quote_freshness(self):
        session, market = fixture()
        for age in (0, -1, True, float('nan'), 1.5001):
            self.check(session, market, max_quote_age=age)

    def test_invalid_reference_clocks_fail_with_fixed_code(self):
        session, market = fixture()
        for now, utc_now in ((float('nan'), UTC_NOW), (True, UTC_NOW),
                             (NOW, UTC_NOW.replace(tzinfo=None)), (NOW, '2026-10-12')):
            with self.assertRaisesRegex(Blocked, '^MARKET_SESSION_UNVERIFIED$'):
                validate_gold_evidence(session, market, now=now, utc_now=utc_now)

    def test_actual_quote_can_advance_but_cannot_regress_or_be_future(self):
        _, market = fixture()
        for change in (0, 1, 500):
            self.assertIsNone(validate_gold_quote(market, market.quote_raw_msc+change, utc_now=UTC_NOW))
        for raw in (market.quote_raw_msc-1, market.quote_raw_msc+501, True, None):
            with self.assertRaisesRegex(Blocked, '^MARKET_EVIDENCE_UNVERIFIED$'):
                validate_gold_quote(market, raw, utc_now=UTC_NOW)

    def test_actual_quote_age_and_profile_are_rechecked_after_math(self):
        _, market = fixture()
        with self.assertRaisesRegex(Blocked, '^MARKET_EVIDENCE_UNVERIFIED$'):
            validate_gold_quote(market, market.quote_raw_msc,
                                utc_now=UTC_NOW+timedelta(seconds=1))
        profile = replace(market.normalization_profile, source='other-source')
        with self.assertRaisesRegex(Blocked, '^MARKET_EVIDENCE_UNVERIFIED$'):
            validate_gold_quote(replace(market, normalization_profile=profile), market.quote_raw_msc,
                                utc_now=UTC_NOW)


if __name__ == '__main__':
    unittest.main()
