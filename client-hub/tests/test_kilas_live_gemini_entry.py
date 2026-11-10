"""Legacy Translator navigation must not strand operator-funded accounts.

Actual authenticated routes and disposable SQLite only; no provider calls.
"""
import os
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_kilas_interpreter as fixture
from kilas_ai import interpreter as calls, interpreter_budget as budget
from kilas_ai import live_gemini as native, live_gemini_pair as pair
from kilas_ai import live_translator_store as sessions


class TranslatorEntryTests(unittest.TestCase):
    setUp = fixture.InterpreterTests.setUp
    config = fixture.InterpreterTests.config
    shared = fixture.InterpreterTests.shared
    lifetime = fixture.InterpreterTests.lifetime
    login_other = fixture.InterpreterTests.login_other
    enabled = fixture.InterpreterTests.enabled
    make = fixture.InterpreterTests.make

    def snapshot(self):
        db = fixture.fixture.audio.f.db
        return {table: [dict(row) for row in db.query_all('SELECT * FROM '+table)]
                for table in ('kilas_vo_stt_campaigns', 'kilas_vo_stt_operations',
                              'kilas_live_translator_sessions', 'kilas_audio_balances')}

    def test_exhausted_trial_bookmark_uses_operator_interpreter_without_mutations(self):
        with self.enabled(), patch.object(calls.wire, 'connect') as connect:
            old = self.make()
            budget.dispatch(old.capability)
            calls.end(self.user, old.ident)
            trial = budget.config()
            fixture.fixture.audio.f.db.execute(
                'UPDATE kilas_vo_stt_operations SET charge_micro=? WHERE operation_key=?',
                (trial['global_micro'], old.capability.key))
            self.addCleanup(fixture.fixture.audio.f.db.execute,
                            'UPDATE kilas_vo_stt_operations SET charge_micro=250000 WHERE operation_key=?',
                            (old.capability.key,))
            self.assertEqual(budget.native.status(self.user, streams=2)['reason'], 'budget_limit')
            before = self.snapshot()
            with patch.dict(os.environ, {'KILAS_TRANSLATOR_FUNDING_MODE': 'operator'}):
                for role in ('CLIENT_OWNER', 'CLIENT_MEMBER'):
                    if role == 'CLIENT_MEMBER':
                        self.login_other(role)
                    for path in ('/kilas-translator/live/gemini', '/kilas-translator/live',
                                 '/kilas-translator?mode=live'):
                        response = self.client.get(path)
                        self.assertEqual(response.status_code, 302)
                        self.assertEqual(response.location, '/kilas-translator/interpreter')
                        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
                        page = self.client.get(path, follow_redirects=True)
                        self.assertEqual(page.status_code, 200)
                        self.assertIn('id="interpreter-active"', page.text)
                        self.assertNotIn('id="interpreter-setup"', page.text)
                        self.assertNotIn('id="native-admission-status"', page.text)
                        self.assertNotIn('id="live-setup-form"', page.text)
                    readiness = self.client.get('/kilas-translator/interpreter/readiness').json
                    self.assertTrue(readiness['available'])
                    self.assertEqual(readiness['funding'], 'operator')
                    self.assertIsNone(readiness['remaining_micro_usd'])
            self.assertEqual(self.snapshot(), before)
            connect.assert_not_called()

    def test_existing_native_sessions_keep_recovery_until_explicit_end(self):
        db = fixture.fixture.audio.f.db
        with self.enabled(), patch.dict(os.environ, {'KILAS_TRANSLATOR_FUNDING_MODE': 'operator'}), \
                patch.object(calls.wire, 'connect') as connect:
            for voice in (native.VOICE, pair.VOICE, pair.LEGACY_VOICE):
                ident = sessions.create(self.user, 'id', 'en', voice)
                self.addCleanup(sessions.end, self.user, ident)
                before = dict(db.query_one('SELECT * FROM kilas_live_translator_sessions WHERE id=?', (ident,)))
                page = self.client.get('/kilas-translator/live/gemini')
                self.assertEqual(page.status_code, 200)
                self.assertIn('id="live-setup-form"', page.text)
                self.assertEqual(dict(db.query_one('SELECT * FROM kilas_live_translator_sessions WHERE id=?', (ident,))), before)
                ended = self.client.post('/kilas-translator/live/sessions/'+ident+'/end',
                                         data={'csrf_token': 'audio-csrf'})
                self.assertEqual(ended.status_code, 200)
                self.assertEqual(self.client.get('/kilas-translator/live/gemini').location,
                                 '/kilas-translator/interpreter')
            connect.assert_not_called()

    def test_classic_return_link_reaches_current_operator_mode_without_dispatch(self):
        with self.enabled(), patch.dict(os.environ, {'KILAS_TRANSLATOR_FUNDING_MODE': 'operator'}), \
                patch.object(calls.wire, 'connect') as connect:
            page = self.client.get('/kilas-translator/live?classic=1')
            self.assertEqual(page.status_code, 200)
            self.assertIn('href="/kilas-translator/live/gemini"', page.text)
            current = self.client.get('/kilas-translator/live/gemini', follow_redirects=True)
            self.assertEqual(current.request.path, '/kilas-translator/interpreter')
            self.assertIn('id="interpreter-active"', current.text)
            self.assertNotIn('id="interpreter-setup"', current.text)
            connect.assert_not_called()

    def test_trial_and_unavailable_operator_do_not_gain_new_access(self):
        with self.enabled(), patch.object(calls.wire, 'connect') as connect:
            for funding in ('trial', 'invalid'):
                with patch.dict(os.environ, {'KILAS_TRANSLATOR_FUNDING_MODE': funding}):
                    response = self.client.get('/kilas-translator/live/gemini')
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('id="live-setup-form"', response.text)
            with patch.dict(os.environ, {'KILAS_TRANSLATOR_FUNDING_MODE': 'operator', 'GEMINI_API_KEY': ''}):
                self.assertEqual(self.client.get('/kilas-translator/live/gemini').status_code, 404)
            anonymous = self.client.application.test_client()
            self.assertEqual(anonymous.get('/kilas-translator/live/gemini').status_code, 302)
            self.assertNotEqual(anonymous.get('/kilas-translator/live/gemini').location,
                                '/kilas-translator/interpreter')
            connect.assert_not_called()

    def test_active_classic_stays_unchanged_and_expired_session_can_redirect(self):
        db = fixture.fixture.audio.f.db
        with self.enabled(), patch.dict(os.environ, {'KILAS_TRANSLATOR_FUNDING_MODE': 'operator'}), \
                patch.object(calls.wire, 'connect') as connect:
            ident = sessions.create(self.user, 'id', 'en', 'kilas-male')
            self.addCleanup(sessions.end, self.user, ident)
            before = dict(db.query_one('SELECT * FROM kilas_live_translator_sessions WHERE id=?', (ident,)))
            response = self.client.get('/kilas-translator/live/gemini')
            self.assertEqual(response.status_code, 200)
            self.assertIn('id="live-setup-form"', response.text)
            self.assertEqual(dict(db.query_one('SELECT * FROM kilas_live_translator_sessions WHERE id=?', (ident,))), before)
            expired = (budget.usage._now()-timedelta(seconds=1)).isoformat()
            db.execute('UPDATE kilas_live_translator_sessions SET expires_at=? WHERE id=?', (expired, ident))
            before = self.snapshot()
            self.assertEqual(self.client.get('/kilas-translator/live/gemini').location,
                             '/kilas-translator/interpreter')
            self.assertEqual(self.snapshot(), before)
            connect.assert_not_called()

    def test_disabled_feature_or_account_does_not_redirect_to_current_mode(self):
        import customer_auth
        with self.enabled(), patch.dict(os.environ, {'KILAS_TRANSLATOR_FUNDING_MODE': 'operator'}), \
                patch.object(calls.wire, 'connect') as connect:
            with patch.dict(os.environ, {'KILAS_AI_ENABLED': 'false'}):
                self.assertEqual(self.client.get('/kilas-translator/live/gemini').status_code, 404)
            self.login_other('CLIENT_MEMBER')
            customer_auth.set_account_disabled(self.other)
            response = self.client.get('/kilas-translator/live/gemini')
            self.assertNotEqual(response.location, '/kilas-translator/interpreter')
            self.assertIn(response.status_code, (302, 303, 404))
            connect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
