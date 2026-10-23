"""Voice Over starts fresh; explicit results retain their actions. No paid IO."""
import unittest
from html.parser import HTMLParser
from unittest.mock import patch
import test_kilas_voice_alternate as alternate
from test_kilas_audio import f, provider, service


class Actions(HTMLParser):
    def __init__(self):
        super().__init__();self.actions=[];self.in_script=False;self.script=''

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='textarea':self.in_script=attrs.get('id')=='audio-script'
        for name in ('data-audio-edit','data-audio-alternate'):
            if name in attrs:self.actions.append((name,attrs[name]))

    def handle_endtag(self, tag):
        if tag=='textarea':self.in_script=False

    def handle_data(self, text):
        if self.in_script:self.script+=text


class FreshEntryTests(unittest.TestCase):
    setUpClass=classmethod(alternate.AlternateTests.setUpClass.__func__)
    setUp=alternate.AlternateTests.setUp
    credit=alternate.AlternateTests.credit
    create=alternate.AlternateTests.create
    source=alternate.AlternateTests.source

    def assert_fresh(self, html):
        self.assertNotIn('class="audio-latest-result"',html)
        self.assertNotIn('data-audio-alternate',html)
        primary=html.split('class="audio-tabs"',1)[0]
        self.assertNotIn('class="audio-result-section"',primary)
        self.assertIn('data-job-status=""',primary)

    def test_default_direct_entry_is_fresh_without_mutating_history(self):
        ident=self.source(script='Old completed result')
        before=f.db.query_all('SELECT * FROM kilas_audio_jobs WHERE user_id=? ORDER BY id',(self.user,))
        with patch.object(service,'submit',side_effect=AssertionError('Navigation must not generate')),patch.object(provider,'request',side_effect=AssertionError('Navigation must not call provider')):
            for path in ('/kilas-translator?mode=voiceover','/kilas-translator'):
                with patch.dict('os.environ',{'KILAS_AUDIO_UPLOAD_TRANSLATION_VISIBLE':'false'}):
                    response=self.client.get(path)
                self.assertEqual(response.status_code,200);self.assert_fresh(response.text)
                self.assertIn(f'data-audio-history="{ident}"',response.text)
        self.assertEqual(f.db.query_all('SELECT * FROM kilas_audio_jobs WHERE user_id=? ORDER BY id',(self.user,)),before)

    def test_home_handoff_starts_fresh_and_preserves_transferred_draft(self):
        ident=self.source(script='Old completed result')
        before=f.db.query_all('SELECT * FROM kilas_audio_jobs WHERE user_id=? ORDER BY id',(self.user,))
        with patch.object(service,'submit',side_effect=AssertionError('Handoff must not generate')),patch.object(provider,'request',side_effect=AssertionError('Handoff must not call provider')):
            for path in ('/kilas-translator?mode=voiceover','/kilas-ai/home-task'):
                for draft in ('','  Transferred <draft> & 日本語.\nKeep this spacing.  '):
                    response=self.client.post(path,data={'csrf_token':'audio-csrf','task':'voiceover','brief':draft,'return_to':'/products/start'})
                    self.assertEqual(response.status_code,200);self.assert_fresh(response.text)
                    parsed=Actions();parsed.feed(response.text);self.assertEqual(parsed.script,draft)
                    self.assertIn(f'data-audio-history="{ident}"',response.text)
        self.assertEqual(f.db.query_all('SELECT * FROM kilas_audio_jobs WHERE user_id=? ORDER BY id',(self.user,)),before)

    def test_new_result_and_explicit_recent_keep_actual_job_actions_and_final_language(self):
        ident=self.source(script='Naskah asli.',translate_script='yes',translated_script='Última traducción.',language='es',translation_source='id')
        with patch.object(service,'submit',side_effect=AssertionError('GET must not generate')),patch.object(provider,'request',side_effect=AssertionError('GET must not call provider')):
            history=self.client.get('/kilas-translator/history?kind=voiceover').json['html']
            self.assertIn(f'/kilas-translator/jobs/{ident}',history)
            selected=self.client.get(f'/kilas-translator/jobs/{ident}').text
            actions=Actions();actions.feed(selected.split('class="audio-tabs"',1)[0])
            self.assertIn(('data-audio-alternate',f'/kilas-translator/jobs/{ident}/alternate'),actions.actions)
            self.assertIn(('data-audio-edit',f'/kilas-translator/jobs/{ident}/script'),actions.actions)
            self.assertIn(f'/kilas-translator/jobs/{ident}/result',selected)
            self.assertEqual(self.client.get(f'/kilas-translator/jobs/{ident}/result').data,self.audio)
            snapshot=self.client.get(f'/kilas-translator/jobs/{ident}/script').json
            self.assertEqual((snapshot['script'],snapshot['language']),('Última traducción.','es'))

    def test_active_explicit_job_survives_navigation_refresh_and_completion_poll(self):
        ident=self.source()
        for status in ('QUEUED','PROCESSING'):
            f.db.execute('UPDATE kilas_audio_jobs SET status=? WHERE id=?',(status,ident))
            self.assert_fresh(self.client.get('/kilas-translator?mode=voiceover').text)
            for _ in range(2):
                html=self.client.get(f'/kilas-translator/jobs/{ident}').text
                self.assertIn(f'data-job-status="{status}"',html)
                self.assertIn(f'data-status-url="/kilas-translator/jobs/{ident}/status"',html)
                self.assertNotIn('data-audio-alternate',html)
            self.assertEqual(f.db.query_one('SELECT status FROM kilas_audio_jobs WHERE id=?',(ident,))['status'],status)
        f.db.execute("UPDATE kilas_audio_jobs SET status='COMPLETED' WHERE id=?",(ident,))
        result=self.client.get(f'/kilas-translator/jobs/{ident}/status').json
        self.assertEqual(result['status'],'COMPLETED')
        self.assertIn(f'data-audio-alternate="/kilas-translator/jobs/{ident}/alternate"',result['html'])

    def test_empty_legacy_failed_and_foreign_jobs_never_offer_invalid_alternate(self):
        self.assert_fresh(self.client.get('/kilas-translator?mode=voiceover').text)
        ident=self.source()
        f.db.execute('UPDATE kilas_audio_jobs SET spoken_script=NULL WHERE id=?',(ident,))
        self.assertNotIn('data-audio-alternate',self.client.get(f'/kilas-translator/jobs/{ident}').text)
        f.db.execute("UPDATE kilas_audio_jobs SET status='FAILED' WHERE id=?",(ident,))
        self.assertNotIn('data-audio-alternate',self.client.get(f'/kilas-translator/jobs/{ident}').text)
        f.db.execute('UPDATE kilas_audio_jobs SET user_id=? WHERE id=?',(self.other,ident))
        self.assert_fresh(self.client.get('/kilas-translator?mode=voiceover').text)
        self.assertEqual(self.client.get(f'/kilas-translator/jobs/{ident}').status_code,404)


if __name__=='__main__':unittest.main()
