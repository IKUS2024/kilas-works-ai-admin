"""Restored ElevenLabs entry, account isolation and exact voice admission; offline."""
import os
import unittest
from unittest.mock import patch

import test_kilas_free_test as fixture
from auth_test_helpers import authenticate
from kilas_ai import audio_branded_voices as voices, live_gemini as native
from kilas_ai import live_translator_realtime as realtime, live_translator_store as sessions
from kilas_ai import live_translator_readiness as readiness

db = fixture.db
CHOICES = [{'alias':'kilas-male', 'id':'syntheticMale123', 'name':'Kilas Male', 'style':'Natural'},
           {'alias':'kilas-female', 'id':'syntheticFemale456', 'name':'Kilas Female', 'style':'Natural'}]


class RestoreTests(unittest.TestCase):
    def setUp(self):
        fixture.FreeTestTests.setUp(self)
        from kilas_ai import translator_languages
        catalog=patch.object(translator_languages,'classic_names',return_value=translator_languages.names(translator_languages.CLASSIC))
        catalog.start();self.addCleanup(catalog.stop)
    cleanup_journals = fixture.FreeTestTests.cleanup_journals
    trial = fixture.FreeTestTests.trial
    verified = fixture.FreeTestTests.verified

    def login(self, user):
        authenticate(self.client, __import__('repo').get_user_by_id(user), _csrf_token='audio-csrf')

    def fields(self, voice='kilas-male'):
        return {'csrf_token':'audio-csrf', 'language_a':'id', 'language_b':'en',
                'voice':voice, 'consent':'yes'}

    def test_default_and_selected_elevenlabs_never_route_to_native_or_mutate_existing_session(self):
        with self.trial(), patch.object(voices,'choices',return_value=CHOICES), \
             patch.object(native,'ready',return_value=True) as gemini_ready, \
             patch.object(native,'connect') as gemini, patch.object(realtime,'connect') as supplier:
            self.verified()
            ident=sessions.create(self.user,'id','en',native.VOICE)
            self.addCleanup(sessions.end,self.user,ident)
            before=dict(db.query_one('SELECT * FROM kilas_live_translator_sessions WHERE id=?',(ident,)))
            with patch.dict(os.environ):
                os.environ.pop('KILAS_TRANSLATOR_PROVIDER',None)
                for selected in (None,'elevenlabs'):
                    if selected:os.environ['KILAS_TRANSLATOR_PROVIDER']=selected
                    for path in ('/kilas-translator/live','/kilas-translator?mode=live'):
                        response=self.client.get(path)
                        self.assertEqual(response.status_code,200)
                        self.assertIn('Kilas Male',response.text);self.assertIn('Kilas Female',response.text)
                        self.assertIn('kilas_live_translator.mjs',response.text)
                        self.assertNotIn('/static/kilas_live_gemini.mjs',response.text)
                        self.assertEqual(response.headers['Cache-Control'],'private, no-store')
            self.assertEqual(dict(db.query_one('SELECT * FROM kilas_live_translator_sessions WHERE id=?',(ident,))),before)
            gemini_ready.assert_not_called();gemini.assert_not_called();supplier.assert_not_called()

    def test_authenticated_owner_and_member_admit_both_voices_realtime_with_tenant_end_fences(self):
        with self.trial(), patch.dict(os.environ,{'KILAS_TRANSLATOR_PROVIDER':'elevenlabs','KILAS_LIVE_GEMINI_ENABLED':'false'}), \
             patch.object(voices,'choices',return_value=CHOICES), patch.object(realtime,'connect') as supplier, \
             patch.object(native,'connect') as gemini:
            self.verified()
            db.execute("UPDATE users SET role='CLIENT_MEMBER' WHERE id=?",(self.user,))
            for user in (self.other,self.user):
                self.login(user)
                for choice in CHOICES:
                    response=self.client.post('/kilas-translator/live/sessions',data=self.fields(choice['alias']))
                    self.assertEqual(response.status_code,201,response.json)
                    self.assertEqual(response.json['input_mode'],'realtime-v1')
                    ident=response.json['session_id'];self.addCleanup(sessions.end,user,ident)
                    self.assertEqual(db.query_one('SELECT voice_alias FROM kilas_live_translator_sessions WHERE id=? AND user_id=?',(ident,user))['voice_alias'],choice['alias'])
                    foreign=self.other if user==self.user else self.user
                    self.login(foreign)
                    self.assertEqual(self.client.get('/kilas-translator/live/sessions/'+ident).status_code,404)
                    self.assertEqual(self.client.post('/kilas-translator/live/sessions/'+ident+'/end',data={'csrf_token':'audio-csrf'}).status_code,404)
                    self.assertEqual(sessions.status(user,ident)['status'],'ACTIVE')
                    self.login(user)
                    self.assertEqual(self.client.post('/kilas-translator/live/sessions/'+ident+'/end',data={'csrf_token':'audio-csrf'}).status_code,200)
            supplier.assert_not_called();gemini.assert_not_called()

    def test_voice_pair_consent_csrf_and_revoked_funding_fail_before_supplier(self):
        with self.trial(), patch.object(voices,'choices',return_value=CHOICES),patch.object(realtime,'connect') as supplier:
            self.verified()
            for extra in ({'voice':'stock-voice'},{'language_b':'id'},{'consent':'no'},{'csrf_token':'wrong'}):
                response=self.client.post('/kilas-translator/live/sessions',data={**self.fields(),**extra})
                self.assertIn(response.status_code,(400,403,409))
                self.assertIsNone(sessions.active(self.user))
            db.execute("UPDATE kilas_realtime_checks SET status='UNKNOWN'")
            self.assertFalse(realtime.ready(self.user))
            self.assertEqual(self.client.post('/kilas-translator/live/sessions',data=self.fields()).status_code,503)
            supplier.assert_not_called()

    def test_runtime_report_reads_existing_accounts_and_public_voices_without_admission(self):
        with self.trial(),patch.object(voices,'choices',return_value=CHOICES),patch.object(sessions,'create') as create, \
             patch.object(realtime,'connect') as supplier:
            self.verified()
            value=readiness.report()
            self.assertEqual(value['selected_provider'],'elevenlabs')
            self.assertTrue(value['owner']['configured_ready'])
            self.assertTrue(value['nonowner']['configured_ready'])
            self.assertEqual(value['owner']['input_mode'],'realtime-v1')
            self.assertEqual([row['alias'] for row in value['voices']],['kilas-male','kilas-female'])
            self.assertNotIn('syntheticMale123',str(value))
            create.assert_not_called();supplier.assert_not_called()


if __name__=='__main__':
    unittest.main()
