"""Simple explicit per-session checkbox; historical permission rows stay inert."""
import unittest
from unittest.mock import patch
import test_kilas_audio as audio
from auth_test_helpers import authenticate
from kilas_ai import live_translator as live, live_translator_store as sessions
from kilas_ai import live_translator_realtime as realtime, audio_branded_voices as branded


class TranslatorConsentTests(unittest.TestCase):
    def setUp(self):
        audio.AudioTests.setUp(self);audio.AudioTests.credit(self,300)
        for target,name,value in ((live,'require_ready',None),(live,'ready',True),(realtime,'ready',False),(branded,'resolve',{'alias':'kilas-male','id':'synthetic','name':'Kilas Male'}),(branded,'public_choices',[{'alias':'kilas-male','name':'Kilas Male'}])):
            mock=patch.object(target,name,return_value=value);mock.start();self.addCleanup(mock.stop)
        forbidden=patch.object(audio.provider,'request',side_effect=AssertionError('Provider IO forbidden'));forbidden.start();self.addCleanup(forbidden.stop)

    def fields(self,**values):return {'csrf_token':'audio-csrf','language_a':'id','language_b':'en','voice':'kilas-male',**values}
    def start(self,**values):return self.client.post('/kilas-translator/live/sessions',data=self.fields(**values))
    def end(self,ident):return self.client.post('/kilas-translator/live/sessions/'+ident+'/end',data={'csrf_token':'audio-csrf'})
    def rows(self):return [dict(row) for row in audio.f.db.query_all('SELECT * FROM kilas_translator_consents WHERE user_id=?',(self.user,))]

    def test_simple_setup_has_unchecked_required_checkbox_without_inline_policy(self):
        page=self.client.get('/kilas-translator/live');self.assertEqual(page.status_code,200)
        self.assertIn('name="consent" value="yes" required',page.text)
        self.assertNotIn('name="consent" value="yes" required checked',page.text)
        self.assertNotIn('live-permission-settings',page.text);self.assertNotIn('Izinkan dan mulai',page.text)
        label=page.text.split('<label class="live-consent">')[1].split('</label>')[0]
        self.assertNotIn('Kebijakan Privasi',label);self.assertNotIn('<a ',label)
        self.assertIn('Audio dapat dikirim selagi saya berbicara.',label)
        self.assertEqual(self.client.get('/privacy').status_code,200);self.assertEqual(self.rows(),[])

    def test_historical_record_never_substitutes_for_checkbox_and_is_preserved(self):
        audio.f.db.execute('INSERT INTO kilas_translator_consents VALUES (?,?,?,?,?)',(self.user,'live-translator-elevenlabs-openai','2026-10-17-v1','2026-10-17T00:00:00Z',''))
        before=self.rows()
        self.assertEqual(self.start().status_code,400)
        self.assertEqual(self.start(processing_consent='accept',processing_scope='live-translator-elevenlabs-openai',processing_version='2026-10-17-v1').status_code,400)
        first=self.start(consent='yes');self.assertEqual(first.status_code,201,first.text)
        self.assertEqual(self.end(first.json['session_id']).status_code,200)
        self.assertEqual(self.start().status_code,400)
        self.assertEqual(self.rows(),before)

    def test_absent_invalid_consent_and_bad_csrf_reject_before_session_or_provider(self):
        with patch.object(sessions,'create') as create:
            for value in (None,'no','on','true','accept'):
                self.assertEqual(self.start(**({'consent':value} if value is not None else {})).status_code,400)
            self.assertEqual(self.start(consent='yes',csrf_token='bad').status_code,400)
            create.assert_not_called()
        self.assertEqual(self.rows(),[])

    def test_checked_start_retains_pair_busy_owner_and_end_guards(self):
        self.assertEqual(self.start(consent='yes',language_b='id').status_code,400)
        first=self.start(consent='yes');self.assertEqual(first.status_code,201)
        self.assertEqual(self.start(consent='yes').status_code,409)
        authenticate(self.client,audio.f.repo.get_user_by_id(self.other),_csrf_token='audio-csrf')
        self.assertEqual(self.end(first.json['session_id']).status_code,404)
        self.assertEqual(self.start().status_code,400)
        authenticate(self.client,audio.f.repo.get_user_by_id(self.user),_csrf_token='audio-csrf')
        self.assertEqual(self.end(first.json['session_id']).status_code,200)
        self.assertEqual(self.rows(),[])


if __name__=='__main__':unittest.main()
