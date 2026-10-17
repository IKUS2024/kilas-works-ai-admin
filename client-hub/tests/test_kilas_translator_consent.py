"""Real authenticated routes/transactions; no microphone or paid provider IO."""
import unittest
from unittest.mock import patch
import test_kilas_audio as audio
from auth_test_helpers import authenticate
from kilas_ai import translator_consent as consent, live_translator as live
from kilas_ai import live_translator_store as sessions, live_translator_realtime as realtime
from kilas_ai import audio_branded_voices as branded


class TranslatorConsentTests(unittest.TestCase):
    def setUp(self):
        audio.AudioTests.setUp(self)
        audio.AudioTests.credit(self,300)
        for target,name,value in ((live,'require_ready',None),(live,'ready',True),(realtime,'ready',False),(branded,'resolve',{'alias':'kilas-male','id':'synthetic','name':'Kilas Male'}),(branded,'public_choices',[{'alias':'kilas-male','name':'Kilas Male'}])):
            mock=patch.object(target,name,return_value=value);mock.start();self.addCleanup(mock.stop)
        forbidden=patch.object(audio.provider,'request',side_effect=AssertionError('Provider IO forbidden'));forbidden.start();self.addCleanup(forbidden.stop)

    def fields(self,accept=False,**values):
        data={'csrf_token':'audio-csrf','language_a':'id','language_b':'en','voice':'kilas-male','processing_scope':consent.SCOPE,'processing_version':consent.VERSION}
        if accept:data['processing_consent']='accept'
        return {**data,**values}

    def start(self,data=None):return self.client.post('/kilas-translator/live/sessions',data=data if data is not None else self.fields())
    def end(self,ident):return self.client.post('/kilas-translator/live/sessions/'+ident+'/end',data={'csrf_token':'audio-csrf'})
    def rows(self):return [dict(row) for row in audio.f.db.query_all('SELECT * FROM kilas_translator_consents WHERE user_id=?',(self.user,))]

    def test_first_use_has_no_backfill_or_checkbox_and_declares_recipients(self):
        audio.f.db.execute('INSERT INTO kilas_audio_personal_voices(user_id,voice_id,consent_at) VALUES (?,?,?)',(self.user,'syntheticExistingVoice','2026-10-01T00:00:00Z'))
        page=self.client.get('/kilas-translator/live')
        self.assertEqual(page.status_code,200)
        self.assertIn('Izinkan dan mulai',page.text);self.assertIn('ElevenLabs',page.text);self.assertIn('OpenAI',page.text)
        self.assertNotIn('type="checkbox"',page.text)
        self.assertIn('/privacy#audio-processing',page.text)
        self.assertFalse(self.client.get('/kilas-translator/live/permission').json['granted'])
        self.assertEqual(self.rows(),[])
        self.assertEqual(self.start().status_code,409)
        self.assertEqual(self.start(self.fields(consent='yes')).status_code,409)
        self.assertEqual(self.rows(),[])

    def test_explicit_first_use_then_repeat_across_fresh_login_preserves_timestamp(self):
        accepted=self.start(self.fields(True));self.assertEqual(accepted.status_code,201,accepted.text)
        self.assertTrue(accepted.json['permission']['granted']);self.assertEqual(self.end(accepted.json['session_id']).status_code,200)
        before=self.rows();self.assertTrue(before[0]['accepted_at']);self.assertEqual(before[0]['revoked_at'],'')
        self.client=audio.f.app.app.test_client();self.client.set_cookie('kilas_language','en')
        authenticate(self.client,audio.f.repo.get_user_by_id(self.user),_csrf_token='audio-csrf')
        page=self.client.get('/kilas-translator/live').text
        self.assertIn('id="live-permission-notice" hidden',page)
        repeated=self.start();self.assertEqual(repeated.status_code,201,repeated.text)
        self.assertEqual(self.rows(),before);self.end(repeated.json['session_id'])

    def test_missing_wrong_and_obsolete_scope_version_cannot_grant_or_reuse(self):
        for fields in (self.fields(True,processing_version='old'),self.fields(True,processing_scope='voice-cloning'),self.fields(True,processing_consent='yes')):
            self.assertEqual(self.start(fields).status_code,409);self.assertEqual(self.rows(),[])
        missing=self.fields(True);missing.pop('processing_version')
        self.assertEqual(self.start(missing).status_code,409)
        first=self.start(self.fields(True));self.end(first.json['session_id'])
        with patch.object(consent,'VERSION','next-version'):
            self.assertFalse(consent._granted(self.user));self.assertEqual(self.start().status_code,409)
            self.assertEqual(self.start(self.fields(True,processing_version='2026-10-17-v1')).status_code,409)
            fresh=self.start(self.fields(True));self.assertEqual(fresh.status_code,201);self.end(fresh.json['session_id'])
            self.assertEqual(len(self.rows()),2)
        with patch.object(consent,'SCOPE','changed-processing-recipients'):
            self.assertFalse(consent._granted(self.user));self.assertEqual(self.start().status_code,409)

    def test_user_isolation_and_csrf_no_consent_record_from_get_or_forged_post(self):
        self.assertEqual(self.start(self.fields(True,csrf_token='bad')).status_code,400);self.assertEqual(self.rows(),[])
        first=self.start(self.fields(True));self.end(first.json['session_id'])
        authenticate(self.client,audio.f.repo.get_user_by_id(self.other),_csrf_token='audio-csrf')
        self.assertFalse(self.client.get('/kilas-translator/live/permission').json['granted'])
        self.assertEqual(self.start().status_code,409)
        self.assertEqual(self.client.post('/kilas-translator/live/permission/revoke',data={'csrf_token':'audio-csrf','user_id':self.user}).status_code,200)
        self.assertTrue(consent._granted(self.user));self.assertFalse(consent._granted(self.other))
        self.assertEqual(audio.f.app.app.test_client().get('/kilas-translator/live/permission').status_code,302)

    def test_revocation_ends_only_owned_scope_cancels_turn_and_requires_new_action(self):
        first=self.start(self.fields(True));ident=first.json['session_id']
        key='live-'+'1'*32
        audio.f.db.execute("INSERT INTO kilas_live_translator_turns(operation_key,session_id,status,created_at) VALUES (?,?,'PROCESSING',?)",(key,ident,'2026-10-17T00:00:00Z'))
        other=sessions.create(self.other,'id','en','kilas-male')
        native='b'*48
        audio.f.db.execute("INSERT INTO kilas_live_translator_sessions VALUES (?,?,?,?,?,'ACTIVE',?,?)",(native,self.user,'id','en','gemini-native-test','2026-10-17T00:00:00Z',''))
        self.assertEqual(self.client.post('/kilas-translator/live/permission/revoke',data={'csrf_token':'bad'}).status_code,400)
        self.assertTrue(consent._granted(self.user))
        with patch.object(realtime,'cancel') as cancel:
            response=self.client.post('/kilas-translator/live/permission/revoke',data={'csrf_token':'audio-csrf'})
            self.assertEqual(response.status_code,200,response.text);cancel.assert_called_once_with(self.user,ident)
        self.assertFalse(response.json['granted']);self.assertTrue(self.rows()[0]['revoked_at'])
        self.assertEqual(sessions.status(self.user,ident)['status'],'ENDED')
        self.assertEqual(sessions.status(self.other,other)['status'],'ACTIVE')
        self.assertEqual(sessions.status(self.user,native)['status'],'ACTIVE')
        self.assertEqual(sessions.result(self.user,ident,key)['status'],'CANCELLED')
        self.assertEqual(self.start().status_code,409)
        self.assertEqual(self.end(native).status_code,200)
        fresh=self.start(self.fields(True));self.assertEqual(fresh.status_code,201);self.end(fresh.json['session_id'])
        self.assertEqual(self.rows()[0]['revoked_at'],'')

    def test_absent_or_revoked_permission_rejects_audio_before_any_dispatch(self):
        ident=sessions.create(self.user,'id','en','kilas-male');prefix='/kilas-translator/live/sessions/'+ident+'/turns/live-'+'a'*32
        with patch.object(realtime,'start') as start,patch.object(realtime,'owned') as owned,patch.object(live,'enqueue') as enqueue:
            for suffix in ('','/input/start','/input/chunks/0','/input/commit'):
                response=self.client.post(prefix+suffix,data={'csrf_token':'audio-csrf'})
                self.assertEqual(response.status_code,409);self.assertEqual(response.json['code'],'processing_consent_required')
            start.assert_not_called();owned.assert_not_called();enqueue.assert_not_called()
        self.assertEqual(self.client.get('/kilas-translator/live/sessions/'+ident).status_code,409)
        self.assertEqual(self.end(ident).status_code,200)

    def test_failed_session_creation_rolls_back_new_consent(self):
        self.assertEqual(self.start(self.fields(True,language_b='id')).status_code,400);self.assertEqual(self.rows(),[])
        old=sessions.create(self.user,'id','en','kilas-male')
        self.assertEqual(self.start(self.fields(True)).status_code,409);self.assertEqual(self.rows(),[])
        self.end(old)


if __name__=='__main__':unittest.main()
