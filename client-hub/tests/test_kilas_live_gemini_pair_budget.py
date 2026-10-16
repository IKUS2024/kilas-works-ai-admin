"""Atomic two-socket funding/capacity; disposable SQLite, no provider calls."""
import hashlib
import os
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import test_kilas_live_gemini_budget as fixture
from kilas_ai import live_gemini_budget as budget


class GeminiPairBudgetTests(unittest.TestCase):
    setUp = fixture.GeminiBudgetTests.setUp
    connect = fixture.GeminiBudgetTests.connect
    query = fixture.GeminiBudgetTests.query
    execute = fixture.GeminiBudgetTests.execute
    key = fixture.GeminiBudgetTests.key
    seed = fixture.GeminiBudgetTests.seed
    assert_denied = fixture.GeminiBudgetTests.assert_denied

    def pair(self, n=1, owner=1):
        return budget.claim(owner, 'a'*48, self.key(n), streams=2)

    def states(self):
        return self.query('SELECT COUNT(*),MIN(status),MAX(status),SUM(charge_micro) FROM kilas_vo_stt_operations')

    def test_pair_reserves_full_amount_and_both_capacity_units_without_policy_change(self):
        for n in range(100, 104):
            self.seed(100000, 'UNKNOWN', 'gml-historical-qa', n, owner=1 if n%2 else 2)
        original = budget.policy()
        snapshot = budget.status(1, streams=2)
        self.assertEqual(snapshot['reserve_micro_usd'], 500000)
        self.assertEqual(snapshot['remaining_leases'], 19)
        self.assertEqual(snapshot['streams'], 2)
        capability = self.pair()
        self.assertEqual(capability.key, self.key()+'-gm2:parent')
        self.assertEqual(self.query("SELECT COUNT(*),SUM(charge_micro),COUNT(DISTINCT fingerprint) FROM kilas_vo_stt_operations WHERE status='RESERVED'"),
                         (2, 500000, 1))
        self.assertEqual(self.query('SELECT charge_micro FROM kilas_vo_stt_operations WHERE operation_key=?',
                                    (self.key()+'-gm2:slot',)), (0,))
        self.assertEqual(budget.policy(), original)
        self.assertEqual(self.query('SELECT global_micro,account_micro,expires_at,price_version FROM kilas_vo_stt_campaigns WHERE id=?',
                                    (original['id'],)), tuple(original[k] for k in ('global_micro', 'account_micro', 'expires_at', 'price_version')))

    def test_pair_insert_failure_rolls_back_funding_and_both_capacity_units(self):
        self.execute("CREATE TRIGGER reject_pair_slot BEFORE INSERT ON kilas_vo_stt_operations WHEN NEW.operation_key LIKE '%-gm2:slot' BEGIN SELECT RAISE(ABORT,'synthetic slot insert failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.pair()
        self.assertEqual(self.query('SELECT COUNT(*) FROM kilas_vo_stt_operations'), (0,))
        self.assertEqual(self.query('SELECT COUNT(*) FROM kilas_vo_stt_campaigns'), (0,))

    def test_dispatch_failure_rolls_back_both_before_any_socket_can_start(self):
        capability = self.pair()
        self.execute("CREATE TRIGGER reject_pair_dispatch BEFORE UPDATE OF status ON kilas_vo_stt_operations WHEN OLD.operation_key LIKE '%-gm2:slot' AND NEW.status='DISPATCHED' BEGIN SELECT RAISE(ABORT,'synthetic dispatch failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            budget.dispatch(capability)
        self.assertEqual(self.states(), (2, 'RESERVED', 'RESERVED', 500000))

    def test_settlement_failure_keeps_both_capacity_units_and_full_charge(self):
        capability = self.pair()
        budget.dispatch(capability)
        self.execute("CREATE TRIGGER reject_pair_settlement BEFORE UPDATE OF status ON kilas_vo_stt_operations WHEN OLD.operation_key LIKE '%-gm2:slot' AND NEW.status='UNKNOWN' BEGIN SELECT RAISE(ABORT,'synthetic settlement failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            budget.finish(capability, False)
        self.assertEqual(self.states(), (2, 'DISPATCHED', 'DISPATCHED', 500000))
        self.execute('DROP TRIGGER reject_pair_settlement')
        budget.finish(capability, False)
        self.assertEqual(self.states(), (2, 'UNKNOWN', 'UNKNOWN', 500000))

    def test_full_pair_reserve_is_required_before_any_admission(self):
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_BUDGET_MICRO_USD': '499999'}):
            self.assertEqual(budget.status(1, streams=2)['reason'], 'budget_limit')
            self.assert_denied('budget_limit', self.pair)
        self.assertEqual(self.query('SELECT COUNT(*) FROM kilas_vo_stt_operations'), (0,))
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_BUDGET_MICRO_USD': '500000'}):
            capability = self.pair()
            budget.dispatch(capability)
            budget.finish(capability, False)
            self.assertEqual(self.states(), (2, 'UNKNOWN', 'UNKNOWN', 500000))
            self.assert_denied('budget_limit', lambda: self.pair(2))

    def test_existing_stt_admission_sees_both_pair_capacity_units(self):
        self.seed(0, 'DISPATCHED', 'other-stt', 100, owner=2)
        self.execute('UPDATE kilas_vo_stt_operations SET created_at=?', (datetime.now(timezone.utc).isoformat(),))
        capability = self.pair()
        self.assertEqual(self.query("SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE status IN ('RESERVED','DISPATCHED')"), (3,))
        config = {'id': 'synthetic-stt', 'mode': 'qa', 'global_micro': 1000000, 'account_micro': 1000000}
        with budget.transaction() as conn:
            self.assert_denied('service_busy', lambda: budget.ledger._admit(conn, 3, config, key='dictate-synthetic'))
        budget.finish(capability, False)
        self.assertEqual(self.query("SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE status IN ('RESERVED','DISPATCHED')"), (1,))

    def test_pair_requires_two_free_capacity_units_while_single_call_remains_compatible(self):
        for n, owner in ((100, 2), (101, 3)):
            self.seed(0, 'DISPATCHED', 'other-stt', n, owner=owner)
        self.execute('UPDATE kilas_vo_stt_operations SET created_at=?', (datetime.now(timezone.utc).isoformat(),))
        self.assert_denied('service_busy', self.pair)
        self.assertEqual(self.query('SELECT COUNT(*) FROM kilas_vo_stt_operations'), (2,))
        single = budget.claim(1, 'a'*48, self.key())
        self.assertEqual(single.key, self.key()+'-gm')
        self.assertEqual(self.query('SELECT charge_micro FROM kilas_vo_stt_operations WHERE operation_key=?', (single.key,)), (250000,))
        budget.dispatch(single)
        budget.finish(single, True)

    def test_slot_cannot_be_dispatched_settled_or_cancelled_independently(self):
        capability = self.pair()
        slot = budget.ledger.Reservation(1, self.key()+'-gm2:slot', capability.lease)
        self.assert_denied('invalid_reservation', lambda: budget.dispatch(slot))
        self.assert_denied('invalid_reservation', lambda: budget.finish(slot, False))
        for key in (capability.key, slot.key):
            self.assert_denied('invalid_operation', lambda: budget.ledger.cancel(1, key))
        self.assertEqual(self.states(), (2, 'RESERVED', 'RESERVED', 500000))

    def test_pair_dispatch_and_failed_handshake_keep_full_parent_charge_after_scope_off(self):
        capability = self.pair()
        budget.dispatch(capability)
        self.assertEqual(self.states(), (2, 'DISPATCHED', 'DISPATCHED', 500000))
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_ENABLED': 'false'}):
            self.assertFalse(budget.finish(capability, False))
            self.assertFalse(budget.finish(capability, True))
        self.assertEqual(self.states(), (2, 'UNKNOWN', 'UNKNOWN', 500000))

    def test_known_undispatched_pair_cancel_releases_both_once(self):
        capability = self.pair()
        self.assertFalse(budget.finish(capability, False))
        self.assertFalse(budget.finish(capability, False))
        self.assertEqual(self.states(), (2, 'CANCELLED', 'CANCELLED', 0))
        self.assert_denied('invalid_reservation', lambda: budget.dispatch(capability))
        self.assert_denied('duplicate_turn', lambda: budget.claim(1, 'a'*48, self.key()))

    def test_single_operation_key_cannot_be_replayed_as_pair_after_settlement(self):
        single = budget.claim(1, 'a'*48, self.key())
        budget.dispatch(single)
        budget.finish(single, False)
        self.assert_denied('duplicate_turn', self.pair)
        self.assertEqual(self.states(), (1, 'UNKNOWN', 'UNKNOWN', 250000))

    def test_missing_mismatched_or_partial_slot_fails_closed_without_parent_refund(self):
        capability = self.pair()
        self.execute("UPDATE kilas_vo_stt_operations SET status='DISPATCHED' WHERE operation_key=?", (self.key()+'-gm2:slot',))
        self.assert_denied('invalid_reservation', lambda: budget.dispatch(capability))
        self.assert_denied('invalid_reservation', lambda: budget.finish(capability, False))
        self.assertEqual(self.query('SELECT charge_micro FROM kilas_vo_stt_operations WHERE operation_key=?', (capability.key,)), (500000,))
        self.execute("UPDATE kilas_vo_stt_operations SET status='RESERVED',lease_digest='tampered' WHERE operation_key=?", (self.key()+'-gm2:slot',))
        self.assert_denied('invalid_reservation', lambda: budget.dispatch(capability))
        self.execute('DELETE FROM kilas_vo_stt_operations WHERE operation_key=?', (self.key()+'-gm2:slot',))
        self.assert_denied('invalid_reservation', lambda: budget.dispatch(capability))
        self.assert_denied('invalid_reservation', lambda: budget.finish(capability, False))
        self.assertEqual(self.states(), (1, 'RESERVED', 'RESERVED', 500000))

    def test_stale_pair_recovery_marks_both_unknown_and_never_resets_history(self):
        for dispatched in (False, True):
            with self.subTest(dispatched=dispatched):
                capability = self.pair(1 if not dispatched else 2)
                if dispatched:
                    budget.dispatch(capability)
                self.execute('UPDATE kilas_vo_stt_operations SET created_at=?',
                             ((datetime.now(timezone.utc)-timedelta(seconds=121)).isoformat(),))
                with budget.transaction() as conn:
                    budget.ledger._expire(conn, owner=1)
                self.assertFalse(budget.finish(capability, True))
                self.assertFalse(budget.finish(capability, False))
        self.assertEqual(self.states(), (4, 'UNKNOWN', 'UNKNOWN', 1000000))
        self.assertEqual(budget.status(1, streams=2)['charged_micro_usd'], 1000000)

    def test_pair_and_single_accounts_race_for_one_global_remaining_allowance(self):
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_AUDIENCE': 'authenticated',
                                    'KILAS_LIVE_GEMINI_BUDGET_MICRO_USD': '500000'}):
            def contend(item):
                owner, streams = item
                try:
                    return budget.claim(owner, 'a'*48, self.key(owner), streams=streams)
                except budget.ledger.BudgetError as error:
                    return error.code
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(contend, ((1, 2), (2, 1))))
            admitted = [item for item in results if isinstance(item, budget.ledger.Reservation)]
            self.assertEqual(len(admitted), 1)
            self.assertIn('budget_limit', results)
            self.assertLessEqual(self.query('SELECT SUM(charge_micro) FROM kilas_vo_stt_operations')[0], 500000)

    def test_pair_consumes_two_physical_attempts_at_hourly_boundary(self):
        fingerprint = hashlib.sha256(('native-logical-session:'+'a'*48).encode()).hexdigest()
        for n in range(100, 179):
            self.seed(0, 'CANCELLED', 'gml-old-standing', n, fingerprint=fingerprint)
        self.execute('UPDATE kilas_vo_stt_operations SET created_at=?', (datetime.now(timezone.utc).isoformat(),))
        self.assert_denied('attempt_limit', self.pair)
        single = budget.claim(1, 'a'*48, self.key())
        budget.finish(single, False)
        self.assertEqual(self.query('SELECT COUNT(*) FROM kilas_vo_stt_operations'), (80,))

    def test_stream_count_is_a_bounded_server_option(self):
        for invalid in (True, False, '2', 2.0, 0, -1, 3, 1000000):
            self.assert_denied('invalid_operation', lambda: budget.claim(1, 'a'*48, self.key(), streams=invalid))
            self.assert_denied('invalid_operation', lambda: budget.status(1, streams=invalid))
        self.assertEqual(self.query('SELECT COUNT(*) FROM kilas_vo_stt_operations'), (0,))


if __name__ == '__main__':
    unittest.main()
