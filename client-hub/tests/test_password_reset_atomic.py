"""Password reset regression tests. Isolated fixture DB; no real account writes."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import test_customer_auth_sessions as auth_tests
import security


class AtomicResetTests(unittest.TestCase):
    setUp = auth_tests.CustomerAuthTests.setUp
    csrf = auth_tests.CustomerAuthTests.csrf
    def make_link(self):
        raw, digest = security.generate_reset_token()
        self.repo.create_password_reset_token(self.owner, digest,
            (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat())
        return raw, digest

    def test_token_consumed_after_validation_cannot_overwrite_password(self):
        raw, digest = self.make_link()
        client = self.app.test_client()
        csrf = self.csrf(client, '/reset-password/' + raw)
        original = security.hash_password
        def competing_reset(password):
            self.repo.invalidate_all_reset_tokens_for_user(self.owner, datetime.now(timezone.utc).isoformat())
            return original(password)
        with patch.object(security, 'hash_password', side_effect=competing_reset):
            response = client.post('/reset-password/' + raw, data={
                'password': 'late-reset-password', 'confirm_password': 'late-reset-password', 'csrf_token': csrf})
        self.assertEqual(response.location, '/forgot-password')
        self.assertTrue(security.verify_password(self.repo.get_user_by_id(self.owner)['password_hash'], self.password))

    def test_failed_audit_rolls_back_password_token_and_revocation(self):
        _, digest = self.make_link()
        before = self.repo.get_user_by_id(self.owner)['password_hash']
        with patch.object(self.repo, 'write_audit_no_business', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                self.repo.complete_password_reset(digest, security.hash_password('rollback-password'))
        self.assertEqual(self.repo.get_user_by_id(self.owner)['password_hash'], before)
        self.assertIsNotNone(self.repo.get_valid_reset_token(digest, datetime.now(timezone.utc).isoformat()))

    def test_concurrent_reset_links_only_one_wins(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        _, first = self.make_link()
        _, second = self.make_link()
        barrier = threading.Barrier(2)
        state = threading.local()
        original = self.repo.get_valid_reset_token
        def simultaneous_candidate(*args):
            row = original(*args)
            if not getattr(state, 'seen', False):
                state.seen = True
                barrier.wait(timeout=10)
            return row
        def reset(digest):
            try:
                return self.repo.complete_password_reset(digest, 'synthetic-hash-' + digest)
            finally:
                self.db.get_connection().close()
                self.db._local.conn = None
        with patch.object(self.repo, 'get_valid_reset_token', side_effect=simultaneous_candidate):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(reset, (first, second)))
        self.assertEqual(results.count(self.owner), 1)
        self.assertEqual(results.count(None), 1)
        for digest in (first, second):
            self.assertIsNone(original(digest, datetime.now(timezone.utc).isoformat()))

if __name__ == '__main__':
    unittest.main()
