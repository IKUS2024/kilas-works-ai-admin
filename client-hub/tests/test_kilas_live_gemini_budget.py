"""Native allowance boundaries with disposable SQLite and synthetic sockets only."""
import hashlib
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db
from kilas_ai import live_gemini_budget as budget, live_gemini as native


class GeminiBudgetTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = str(Path(self.folder.name)/'native-budget.sqlite')
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,role TEXT NOT NULL)')
            conn.execute('CREATE TABLE customer_auth_account_state(user_id INTEGER PRIMARY KEY,disabled INTEGER NOT NULL DEFAULT 0)')
            conn.executescript((Path(__file__).resolve().parents[1]/'migrations/0091_kilas_voice_script_transcription_sqlite.sql').read_text())
            conn.executemany('INSERT INTO users(id,role) VALUES (?,?)',
                             [(1, 'CLIENT_OWNER'), (2, 'CLIENT_MEMBER'), (3, 'KILAS_ADMIN')])
            conn.commit()
        self.env = {'KILAS_LIVE_GEMINI_ENABLED': 'true', 'KILAS_LIVE_GEMINI_BILLING_VERIFIED': 'yes',
                    'KILAS_LIVE_GEMINI_ALLOWED_OWNER_ID': '1', 'KILAS_LIVE_GEMINI_CAMPAIGN': 'synthetic-standing',
                    'KILAS_LIVE_GEMINI_POLICY': 'owner_lifetime',
                    'KILAS_LIVE_GEMINI_IDR_VALUATION_MODE': 'conservative_internal',
                    'KILAS_LIVE_GEMINI_INTERNAL_VALUATION_ACK': 'yes',
                    'KILAS_LIVE_GEMINI_TOTAL_IDR': '500000', 'KILAS_LIVE_GEMINI_INTERNAL_GUARD_IDR': '250000',
                    'KILAS_LIVE_GEMINI_IDR_PER_USD_INTERNAL': '25000',
                    'KILAS_LIVE_GEMINI_BUDGET_MICRO_USD': '10000000',
                    'KILAS_LIVE_GEMINI_LEASE_RESERVE_MICRO_USD': '250000'}
        for changing in (patch.dict(os.environ, self.env, clear=True),
                         patch.object(db, 'BACKEND', 'sqlite'),
                         patch.object(db, 'query_one', side_effect=self.query),
                         patch.object(budget.usage, '_connect', side_effect=self.connect)):
            changing.start()
            self.addCleanup(changing.stop)

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('BEGIN IMMEDIATE')
        return conn

    def query(self, sql, params=()):
        with closing(sqlite3.connect(self.path)) as conn:
            return conn.execute(sql, params).fetchone()

    def execute(self, sql, params=()):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(sql, params)
            conn.commit()

    def key(self, n=1):
        return 'live-'+format(n, '032x')

    def claim(self, n=1):
        return budget.claim(1, 'a'*48, self.key(n))

    def seed(self, amount, status, campaign, n, owner=1, fingerprint=None):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute('INSERT OR IGNORE INTO kilas_vo_stt_campaigns(id,global_micro,account_micro,expires_at,price_version) VALUES (?,10000000,10000000,?,?)',
                         (campaign, 'old-policy', budget.PRICE_VERSION))
            conn.execute('INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at) VALUES (?,?,?,?,?,?,90000,?,?)',
                         (owner, self.key(n)+'-gm', campaign,
                          fingerprint or hashlib.sha256((campaign+':'+self.key(n)).encode()).hexdigest(),
                          status, amount, 'old-lease',
                          (datetime.now(timezone.utc)-timedelta(days=2)).isoformat()))
            conn.commit()

    def assert_denied(self, code, call):
        with self.assertRaises(budget.ledger.BudgetError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    def test_key_presence_never_enables_spend_and_all_internal_amounts_are_explicit(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'synthetic-only'}, clear=True), \
             patch.object(budget.usage, '_connect') as connect:
            self.assertIsNone(budget.policy())
            self.assertFalse(budget.ready(1))
            self.assertEqual(budget.status(1), {'available': False, 'reason': 'gemini_unavailable'})
            self.assert_denied('gemini_unavailable', self.claim)
            connect.assert_not_called()
        for field in self.env:
            if field in ('KILAS_LIVE_GEMINI_CAMPAIGN', 'KILAS_LIVE_GEMINI_POLICY'):
                continue
            with patch.dict(os.environ):
                os.environ.pop(field)
                self.assertIsNone(budget.policy(), field)

    def test_internal_assumption_is_separate_from_verified_actual_conversion(self):
        config = budget.policy()
        self.assertEqual(config['valuation_mode'], 'conservative_internal')
        self.assertEqual(config['guard_idr'], 250000)
        self.assertEqual(config['total_idr'], 500000)
        self.assertEqual(config['idr_per_usd'], 25000)
        self.assertEqual(config['expires_at'], 'owner-lifetime-v1')
        self.assertNotIn('KILAS_LIVE_GEMINI_IDR_CEILING_VERIFIED', os.environ)
        self.assertIn('-internal-25000-250000-500000', config['price_version'])
        for extra in ({'KILAS_LIVE_GEMINI_INTERNAL_VALUATION_ACK': ''},
                      {'KILAS_LIVE_GEMINI_IDR_VALUATION_MODE': 'unknown'},
                      {'KILAS_LIVE_GEMINI_IDR_PER_USD_INTERNAL': '24999'},
                      {'KILAS_LIVE_GEMINI_IDR_PER_USD_INTERNAL': '0'},
                      {'KILAS_LIVE_GEMINI_INTERNAL_GUARD_IDR': '250001'},
                      {'KILAS_LIVE_GEMINI_INTERNAL_GUARD_IDR': '0'},
                      {'KILAS_LIVE_GEMINI_TOTAL_IDR': '249999'},
                      {'KILAS_LIVE_GEMINI_TOTAL_IDR': '500001'},
                      {'KILAS_LIVE_GEMINI_BUDGET_MICRO_USD': '10000001'},
                      {'KILAS_LIVE_GEMINI_LEASE_RESERVE_MICRO_USD': '249999'}):
            with patch.dict(os.environ, extra):
                self.assertIsNone(budget.policy(), extra)
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_IDR_VALUATION_MODE': 'verified_ceiling',
                                    'KILAS_LIVE_GEMINI_IDR_PER_USD_CEILING': '25000'}):
            self.assertIsNone(budget.policy())
            with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_IDR_CEILING_VERIFIED': 'yes'}):
                self.assertEqual(budget.policy()['valuation_mode'], 'verified_ceiling')

    def test_authenticated_audience_is_explicit_and_preserves_campaign_policy(self):
        original = budget.policy()
        self.assertEqual(original['audience'], 'owner')
        self.assertTrue(budget.allowed(1, original))
        self.assertFalse(budget.allowed(2, original))
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_AUDIENCE': 'authenticated'}):
            shared = budget.policy()
            for field in ('id', 'allowed_owner', 'global_micro', 'account_micro', 'expires_at', 'price_version'):
                self.assertEqual(shared[field], original[field], field)
            self.assertEqual(shared['audience'], 'authenticated')
            self.assertTrue(budget.ready(2))
            self.assertTrue(budget.ready(3))
            self.assertEqual(self.query('SELECT role FROM users WHERE id=2'), ('CLIENT_MEMBER',))
            with budget.transaction() as conn:
                self.assertTrue(budget.allowed(2, shared, conn))
                self.assert_denied('not_owned', lambda: budget.ledger._owner(conn, 2))
            with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_POLICY': 'qa',
                                        'KILAS_LIVE_GEMINI_EXPIRES_AT': (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}):
                self.assertEqual(budget.policy()['audience'], 'owner')
                self.assertFalse(budget.ready(2))
                self.assert_denied('gemini_unavailable', lambda: budget.claim(2, 'a'*48, self.key()))
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_AUDIENCE': 'unknown'}):
            self.assertIsNone(budget.policy())

    def test_shared_audience_rejects_untrusted_or_missing_account_ids(self):
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_AUDIENCE': 'authenticated'}):
            for invalid in (None, True, False, '1', 1.0, 0, -1, 10**9+1, 999):
                self.assertFalse(budget.allowed(invalid), repr(invalid))
                self.assertFalse(budget.ready(invalid), repr(invalid))
                self.assertEqual(budget.status(invalid), {'available': False, 'reason': 'gemini_unavailable'})
                self.assert_denied('gemini_unavailable', lambda: budget.claim(invalid, 'a'*48, self.key()))
                forged = budget.ledger.Reservation(invalid, self.key()+'-gm', 'untrusted')
                self.assert_denied('gemini_unavailable', lambda: budget.dispatch(forged))
            self.assertTrue(budget.allowed(3))
            self.execute('DELETE FROM users WHERE id=3')
            self.assertFalse(budget.allowed(3))
            self.assert_denied('gemini_unavailable', lambda: budget.claim(3, 'c'*48, self.key()))
        self.assertEqual(self.query('SELECT COUNT(*) FROM kilas_vo_stt_operations'), (0,))

    def test_accounts_share_one_global_lifetime_cap_including_all_historical_users(self):
        for n in range(100, 104):
            self.seed(100000, 'UNKNOWN', 'gml-historical-'+str(n), n, owner=1 if n%2 else 2)
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_AUDIENCE': 'authenticated',
                                    'KILAS_LIVE_GEMINI_BUDGET_MICRO_USD': '900000'}):
            second = budget.claim(2, 'b'*48, self.key(1))
            self.assert_denied('already_processing', lambda: budget.claim(2, 'b'*48, self.key(2)))
            third = budget.claim(3, 'c'*48, self.key(3))
            self.assert_denied('budget_limit', lambda: self.claim(4))
            budget.dispatch(second)
            budget.dispatch(third)
            budget.finish(second, False)
            budget.finish(third, True)
            for owner in (1, 2, 3):
                snapshot = budget.status(owner)
                self.assertEqual(snapshot['charged_micro_usd'], 900000)
                self.assertEqual(snapshot['remaining_micro_usd'], 0)
                self.assertEqual(snapshot['reason'], 'budget_limit')
            with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_CAMPAIGN': 'rotated-standing'}):
                self.assert_denied('budget_limit', lambda: budget.claim(2, 'b'*48, self.key(5)))
        self.assertEqual(self.query("SELECT COUNT(*),SUM(charge_micro) FROM kilas_vo_stt_operations WHERE campaign LIKE 'gml-%'"),
                         (6, 900000))

    def test_shared_scope_is_rechecked_before_dispatch_and_settlement_survives_revocation(self):
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_AUDIENCE': 'authenticated'}):
            capability = budget.claim(2, 'b'*48, self.key())
            with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_AUDIENCE': 'owner'}):
                self.assert_denied('gemini_unavailable', lambda: budget.dispatch(capability))
                self.assertFalse(budget.finish(capability, False))
            self.assertEqual(self.query('SELECT status,charge_micro FROM kilas_vo_stt_operations'), ('CANCELLED', 0))
            dispatched = budget.claim(2, 'b'*48, self.key(2))
            budget.dispatch(dispatched)
            with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_AUDIENCE': 'owner', 'KILAS_LIVE_GEMINI_ENABLED': 'false'}):
                self.assertFalse(budget.ready(2))
                self.assertFalse(budget.finish(dispatched, False))
                self.assertFalse(budget.finish(dispatched, True))
            self.assertEqual(self.query('SELECT status,charge_micro FROM kilas_vo_stt_operations WHERE operation_key=?',
                                        (self.key(2)+'-gm',)), ('UNKNOWN', 250000))

    def test_disabled_accounts_are_rechecked_without_blocking_existing_settlement(self):
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_AUDIENCE': 'authenticated'}):
            reserved = budget.claim(2, 'b'*48, self.key())
            dispatched = budget.claim(3, 'c'*48, self.key(2))
            budget.dispatch(dispatched)
            self.execute('INSERT INTO customer_auth_account_state(user_id,disabled) VALUES (2,1)')
            self.execute('INSERT INTO customer_auth_account_state(user_id,disabled) VALUES (3,1)')
            for owner in (2, 3):
                self.assertFalse(budget.allowed(owner))
                self.assertFalse(budget.ready(owner))
                self.assertEqual(budget.status(owner), {'available': False, 'reason': 'gemini_unavailable'})
                self.assert_denied('gemini_unavailable', lambda: budget.claim(owner, 'b'*48, self.key(3)))
            self.assert_denied('gemini_unavailable', lambda: budget.dispatch(reserved))
            self.assertFalse(budget.finish(reserved, False))
            self.assertFalse(budget.finish(dispatched, False))
            self.assertEqual(self.query('SELECT status,charge_micro FROM kilas_vo_stt_operations WHERE user_id=2'), ('CANCELLED', 0))
            self.assertEqual(self.query('SELECT status,charge_micro FROM kilas_vo_stt_operations WHERE user_id=3'), ('UNKNOWN', 250000))

    def test_shared_scope_never_allows_foreign_nonce_key_or_boolean_owner(self):
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_AUDIENCE': 'authenticated'}):
            capability = budget.claim(2, 'b'*48, self.key())
            for forged in (budget.ledger.Reservation(1, capability.key, capability.lease),
                           budget.ledger.Reservation(3, capability.key, capability.lease),
                           budget.ledger.Reservation(2, self.key(2)+'-gm', capability.lease),
                           budget.ledger.Reservation(2, capability.key, 'wrong-nonce')):
                self.assert_denied('invalid_reservation', lambda: budget.dispatch(forged))
                self.assert_denied('invalid_reservation', lambda: budget.finish(forged, False))
            forged = budget.ledger.Reservation(True, capability.key, capability.lease)
            self.assert_denied('gemini_unavailable', lambda: budget.dispatch(forged))
            self.assert_denied('invalid_reservation', lambda: budget.finish(forged, False))
            self.assertEqual(self.query('SELECT status,charge_micro FROM kilas_vo_stt_operations'), ('RESERVED', 250000))
            budget.dispatch(capability)
            budget.finish(capability, False)

    def test_status_is_read_only_private_and_counts_all_historical_native_outcomes(self):
        for n, outcome in enumerate(('COMPLETED', 'UNKNOWN', 'CANCELLED', 'DISPATCHED', 'FAILED'), 100):
            self.seed(80000, outcome, 'gml-qa-'+str(n), n, owner=2 if n == 103 else 1)
        self.seed(90000000, 'COMPLETED', 'unrelated-transcription', 200)
        before = (self.query('SELECT COUNT(*) FROM kilas_vo_stt_campaigns'),
                  self.query('SELECT COUNT(*),SUM(charge_micro) FROM kilas_vo_stt_operations'))
        snapshot = budget.status(1)
        self.assertTrue(snapshot['available'])
        self.assertEqual(snapshot['charged_micro_usd'], 400000)
        self.assertEqual(snapshot['remaining_micro_usd'], 9600000)
        self.assertEqual(snapshot['remaining_leases'], 38)
        self.assertEqual(snapshot['lease_ms'], 90000)
        self.assertEqual(before, (self.query('SELECT COUNT(*) FROM kilas_vo_stt_campaigns'),
                                 self.query('SELECT COUNT(*),SUM(charge_micro) FROM kilas_vo_stt_operations')))
        self.assertEqual(budget.status(2), {'available': False, 'reason': 'gemini_unavailable'})

    def test_38_new_leases_exhaust_guard_including_historical_40_cent_dispatches(self):
        for n in range(100, 104):
            self.seed(100000, 'UNKNOWN', 'gml-prior-qa', n)
        # Real standing limits remain in place: these 38 physical dispatches
        # belong to one logical session and must not hit the 20-starts fence.
        for n in range(1, 39):
            capability = self.claim(n)
            budget.dispatch(capability)
            self.assertFalse(budget.finish(capability, False))
        self.assert_denied('budget_limit', lambda: self.claim(39))
        snapshot = budget.status(1)
        self.assertEqual(snapshot['charged_micro_usd'], 9900000)
        self.assertEqual(snapshot['remaining_micro_usd'], 100000)
        self.assertEqual(snapshot['remaining_leases'], 0)
        self.assertEqual(snapshot['reason'], 'budget_limit')
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_CAMPAIGN': 'rotated-standing'}):
            self.assert_denied('budget_limit', lambda: self.claim(40))

    def test_twenty_logical_sessions_limit_new_starts_but_last_session_can_renew(self):
        for n in range(1, 21):
            capability = budget.claim(1, format(n, '048x'), self.key(n))
            budget.dispatch(capability)
            budget.finish(capability, True)
        self.assert_denied('attempt_limit', lambda: budget.claim(1, 'b'*48, self.key(21)))
        # A campaign rename neither resets starts nor splits this session.
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_CAMPAIGN': 'rotated-standing'}):
            renewed = budget.claim(1, format(20, '048x'), self.key(22))
            budget.dispatch(renewed)
            budget.finish(renewed, True)
            self.assert_denied('attempt_limit', lambda: budget.claim(1, 'c'*48, self.key(23)))
        self.assertEqual(self.query('SELECT COUNT(*),COUNT(DISTINCT fingerprint) FROM kilas_vo_stt_operations'), (21, 20))

    def test_original_live_stt_attempts_keep_individual_weight_and_shared_limit(self):
        current = hashlib.sha256(('native-logical-session:'+'a'*48).encode()).hexdigest()
        for n in range(100, 119):
            self.seed(0, 'CANCELLED', 'original-live-stt', n, fingerprint=current)
        self.execute('UPDATE kilas_vo_stt_operations SET created_at=?', (datetime.now(timezone.utc).isoformat(),))
        for n in (1, 2):
            capability = self.claim(n)
            budget.dispatch(capability)
            budget.finish(capability, True)
        self.seed(0, 'CANCELLED', 'original-live-stt', 119, fingerprint=current)
        self.execute('UPDATE kilas_vo_stt_operations SET created_at=? WHERE operation_key=?',
                     (datetime.now(timezone.utc).isoformat(), self.key(119)+'-gm'))
        self.assert_denied('attempt_limit', lambda: self.claim(3))

    def test_daily_logical_limit_and_idle_session_cannot_bypass_recent_sessions(self):
        for n in range(100, 220):
            self.seed(0, 'CANCELLED', 'gml-historical-qa', n)
        self.execute('UPDATE kilas_vo_stt_operations SET created_at=?',
                     ((datetime.now(timezone.utc)-timedelta(hours=2)).isoformat(),))
        # Historical QA fingerprints remain separate attempts: no retroactive
        # coalescing of earlier activity can erase the 120/day protection.
        self.assert_denied('attempt_limit', self.claim)
        self.execute('UPDATE kilas_vo_stt_operations SET created_at=?',
                     ((datetime.now(timezone.utc)-timedelta(days=2)).isoformat(),))
        old = self.claim()
        budget.finish(old, False)
        self.execute('UPDATE kilas_vo_stt_operations SET created_at=? WHERE operation_key=?',
                     ((datetime.now(timezone.utc)-timedelta(hours=2)).isoformat(), self.key()+'-gm'))
        for n in range(2, 22):
            capability = budget.claim(1, format(n, '048x'), self.key(n))
            budget.finish(capability, False)
        self.assert_denied('attempt_limit', lambda: self.claim(22))

    def test_eighty_physical_leases_per_hour_cap_rapid_manual_renewals(self):
        for n in range(1, budget.OWNER_PHYSICAL_LEASES_PER_HOUR+1):
            capability = self.claim(n)
            # Even known-undispatched cancellations retain attempt weight.
            budget.finish(capability, False)
        self.assertEqual(self.query('SELECT COUNT(*),COUNT(DISTINCT fingerprint),SUM(charge_micro) FROM kilas_vo_stt_operations'),
                         (80, 1, 0))
        self.assert_denied('attempt_limit', lambda: self.claim(81))

    def test_qa_mode_keeps_previous_twenty_physical_attempts_per_hour_limit(self):
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_POLICY': 'qa',
                                    'KILAS_LIVE_GEMINI_EXPIRES_AT': (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}):
            for n in range(1, 21):
                capability = self.claim(n)
                budget.finish(capability, False)
            self.assert_denied('attempt_limit', lambda: self.claim(21))
        self.assertEqual(self.query('SELECT COUNT(*),COUNT(DISTINCT fingerprint) FROM kilas_vo_stt_operations'), (20, 20))

    def test_exact_cap_admission_then_denied_renewal_has_no_new_paid_io(self):
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_BUDGET_MICRO_USD': '250000'}):
            capability = self.claim()
            budget.dispatch(capability)
            budget.finish(capability, True)
            info = {'voice_alias': native.VOICE, 'language_a': 'id', 'language_b': 'en'}
            with patch.object(native, 'require_ready'), patch.object(native, '_slots', Mock()), \
                 patch.object(native.sessions, 'claim', return_value=info), \
                 patch.object(native.sessions, 'finish'), patch.object(native.temporary, 'discard'), \
                 patch.object(native.audio_store, 'require_balance'), \
                 patch.object(native.live, 'require_audio_allowance'), \
                 patch.object(native.audio_store, 'create') as create, patch.object(native, 'connect') as connect:
                with self.assertRaises(native.audio_store.AudioError) as caught:
                    native.start(1, 'a'*48, self.key(2))
                self.assertEqual(caught.exception.code, 'budget_limit')
                create.assert_not_called()
                connect.assert_not_called()
            self.assertEqual(self.query('SELECT COUNT(*),SUM(charge_micro) FROM kilas_vo_stt_operations'), (1, 250000))
            with patch.object(budget, 'datetime', wraps=datetime) as future:
                future.now.return_value = datetime(2050, 1, 1, tzinfo=timezone.utc)
                self.assertEqual(budget.policy()['expires_at'], 'owner-lifetime-v1')
                self.assert_denied('budget_limit', lambda: self.claim(3))

    def test_each_handshake_is_dispatched_and_retains_cost_on_failure_or_cancel(self):
        capability = self.claim()
        relay = native.Relay(1, 'a'*48, self.key(), {'language_b': 'en'}, capability, 7)
        def connect_after_dispatch():
            self.assertEqual(self.query('SELECT status,charge_micro FROM kilas_vo_stt_operations'), ('DISPATCHED', 250000))
            raise OSError('synthetic handshake failure')
        with patch.object(relay, 'check'), patch.object(native.Timer, 'start'), \
             patch.object(native, '_slots', Mock()), patch.object(native.audio_store, 'fail'), \
             patch.object(native.sessions, 'finish'), patch.object(native, 'connect', side_effect=connect_after_dispatch) as connect, \
             redirect_stdout(io.StringIO()):
            relay.run()
            connect.assert_called_once()
        self.assertEqual(self.query('SELECT status,charge_micro FROM kilas_vo_stt_operations'), ('UNKNOWN', 250000))
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_ENABLED': 'false'}):
            self.assertFalse(budget.finish(capability, True))
            self.assertFalse(budget.finish(capability, False))
        self.assertEqual(self.query('SELECT status,charge_micro FROM kilas_vo_stt_operations'), ('UNKNOWN', 250000))
        self.assert_denied('duplicate_turn', self.claim)

    def test_only_known_undispatched_reservation_cancellation_releases_charge(self):
        capability = self.claim()
        self.assertFalse(budget.finish(capability, False))
        self.assertEqual(self.query('SELECT status,charge_micro FROM kilas_vo_stt_operations'), ('CANCELLED', 0))
        self.assert_denied('invalid_reservation', lambda: budget.dispatch(capability))
        self.assert_denied('duplicate_turn', self.claim)

    def test_stale_recovery_and_late_settlement_never_refund_unknown_dispatch(self):
        first = self.claim()
        budget.dispatch(first)
        self.execute('UPDATE kilas_vo_stt_operations SET created_at=?',
                     ((datetime.now(timezone.utc)-timedelta(seconds=121)).isoformat(),))
        second = self.claim(2)
        self.assertEqual(self.query('SELECT status,charge_micro FROM kilas_vo_stt_operations WHERE operation_key=?',
                                    (self.key()+'-gm',)), ('UNKNOWN', 250000))
        self.assertFalse(budget.finish(first, True))
        self.assertFalse(budget.finish(first, False))
        budget.finish(second, False)
        self.assertEqual(budget.status(1)['charged_micro_usd'], 250000)
        self.assertEqual(self.query('SELECT COUNT(*) FROM kilas_vo_stt_operations'), (2,))

    def test_policy_edits_do_not_reinterpret_admitted_internal_assumption(self):
        capability = self.claim()
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_TOTAL_IDR': '499999'}):
            self.assertEqual(budget.status(1)['reason'], 'campaign_policy_changed')
            self.assert_denied('campaign_policy_changed', lambda: budget.dispatch(capability))
        with patch.dict(os.environ, {'KILAS_LIVE_GEMINI_LEASE_RESERVE_MICRO_USD': '500000'}):
            self.assert_denied('invalid_reservation', lambda: budget.dispatch(capability))
        self.assertEqual(self.query('SELECT status FROM kilas_vo_stt_operations'), ('RESERVED',))
        budget.finish(capability, False)

    def test_delayed_admission_cannot_connect_near_stale_recovery_fence(self):
        capability = self.claim()
        self.execute('UPDATE kilas_vo_stt_operations SET created_at=?',
                     ((datetime.now(timezone.utc)-timedelta(seconds=budget.DISPATCH_MAX_AGE_SECONDS+1)).isoformat(),))
        relay = native.Relay(1, 'a'*48, self.key(), {'language_b': 'en'}, capability, 7)
        with patch.object(relay, 'check'), patch.object(native.Timer, 'start'), \
             patch.object(native, '_slots', Mock()), patch.object(native.audio_store, 'fail'), \
             patch.object(native.sessions, 'finish'), patch.object(native, 'connect') as connect, \
             redirect_stdout(io.StringIO()):
            relay.run()
            connect.assert_not_called()
        self.assertEqual(self.query('SELECT status,charge_micro FROM kilas_vo_stt_operations'), ('CANCELLED', 0))

    def test_two_distinct_owner_keys_have_one_atomic_admission(self):
        def admit(n):
            try:
                return self.claim(n)
            except budget.ledger.BudgetError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(admit, (1, 2)))
        capabilities = [item for item in results if isinstance(item, budget.ledger.Reservation)]
        self.assertEqual(len(capabilities), 1)
        self.assertIn('already_processing', results)
        self.assertEqual(self.query('SELECT COUNT(*),SUM(charge_micro) FROM kilas_vo_stt_operations'), (1, 250000))
        budget.dispatch(capabilities[0])
        self.assertEqual(budget.status(1)['reason'], 'already_processing')
        budget.finish(capabilities[0], False)


if __name__ == '__main__':
    unittest.main()
