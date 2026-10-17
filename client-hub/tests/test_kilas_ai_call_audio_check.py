"""Authenticated local diagnostics cannot admit a Call or consume provider usage."""
import unittest
from unittest.mock import patch
import test_kilas_ai_call as fixture
from kilas_ai import ai_call as calls, ai_call_budget as budget


class AudioCheckRouteTests(unittest.TestCase):
    setUp=fixture.CallTests.setUp
    config=fixture.CallTests.config
    shared=fixture.CallTests.shared
    lifetime=fixture.CallTests.lifetime
    enabled=fixture.CallTests.enabled
    login_other=fixture.CallTests.login_other

    def test_local_check_is_no_store_and_cannot_dispatch_or_reserve(self):
        with self.enabled(),patch.object(calls,'start') as start,patch.object(calls.wire,'connect') as connect,patch.object(budget,'claim') as claim:
            before=budget.ledger.db.query_one('SELECT COUNT(*) AS n FROM kilas_vo_stt_operations')['n']
            with self.config(KILAS_AI_CALL_ENABLED='false'):
                response=self.client.get('/kilas-ai/call/audio-check')
            self.assertEqual(response.status_code,200)
            self.assertIn("connect-src 'none'",response.headers['Content-Security-Policy'])
            self.assertIn('no-store',response.headers['Cache-Control'])
            self.assertEqual(response.headers['Permissions-Policy'],'microphone=(self), camera=(), geolocation=()')
            self.assertIn(b'kilas_ai_call_audio_check.mjs',response.data)
            self.assertEqual(budget.ledger.db.query_one('SELECT COUNT(*) AS n FROM kilas_vo_stt_operations')['n'],before)
            start.assert_not_called();connect.assert_not_called();claim.assert_not_called()

    def test_local_check_requires_existing_ai_auth_and_rejects_post(self):
        with self.enabled():
            self.assertEqual(self.client.post('/kilas-ai/call/audio-check',headers={'X-CSRF-Token':'audio-csrf'}).status_code,404)
            with self.client.session_transaction() as session:session.clear()
            self.assertIn(self.client.get('/kilas-ai/call/audio-check').status_code,(302,303))


if __name__=='__main__':unittest.main()
