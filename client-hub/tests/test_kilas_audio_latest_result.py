"""Latest restoration must expose the selected result's actions; no paid IO."""
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


class LatestResultTests(unittest.TestCase):
    setUpClass=classmethod(alternate.AlternateTests.setUpClass.__func__)
    setUp=alternate.AlternateTests.setUp
    credit=alternate.AlternateTests.credit
    create=alternate.AlternateTests.create
    source=alternate.AlternateTests.source

    def latest(self):
        return self.client.get('/kilas-translator?mode=voiceover').text.split('class="audio-tabs"',1)[0]

    def test_latest_and_recent_actions_use_same_successful_job_snapshot(self):
        ident=self.source(script='Naskah asli.',translate_script='yes',translated_script='Última traducción.',language='es',translation_source='id')
        with patch.object(service,'submit',side_effect=AssertionError('GET must not generate')),patch.object(provider,'request',side_effect=AssertionError('GET must not call provider')):
            latest=Actions();latest.feed(self.latest())
            selected=Actions();selected.feed(self.client.get(f'/kilas-translator/jobs/{ident}').text.split('class="audio-tabs"',1)[0])
        self.assertEqual(latest.actions,selected.actions)
        self.assertIn(('data-audio-alternate',f'/kilas-translator/jobs/{ident}/alternate'),latest.actions)
        snapshot=self.client.get(f'/kilas-translator/jobs/{ident}/script').json
        self.assertEqual((snapshot['script'],snapshot['language']),('Última traducción.','es'))

    def test_home_handoff_restores_actions_without_replacing_transferred_draft(self):
        ident=self.source(script='Naskah asli.',translate_script='yes',translated_script='Última traducción.',language='es',translation_source='id')
        count=f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs WHERE user_id=?',(self.user,))['n']
        with patch.object(service,'submit',side_effect=AssertionError('Handoff must not generate')),patch.object(provider,'request',side_effect=AssertionError('Handoff must not call provider')):
            for path in ('/kilas-translator?mode=voiceover','/kilas-ai/home-task'):
                for draft in ('','  Transferred <draft> & 日本語.\nKeep this spacing.  '):
                    response=self.client.post(path,data={'csrf_token':'audio-csrf','task':'voiceover','brief':draft,'return_to':'/products/start'})
                    self.assertEqual(response.status_code,200)
                    parsed=Actions();parsed.feed(response.text)
                    self.assertEqual(parsed.script,draft)
                    self.assertIn(('data-audio-alternate',f'/kilas-translator/jobs/{ident}/alternate'),parsed.actions)
                    self.assertIn('class="audio-latest-result"',response.text)
        self.assertEqual(f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs WHERE user_id=?',(self.user,))['n'],count)

    def test_no_history_or_legacy_snapshot_never_offers_alternate(self):
        self.assertNotIn('data-audio-alternate',self.latest())
        for path in ('/kilas-translator?mode=voiceover','/kilas-ai/home-task'):
            self.assertNotIn('data-audio-alternate',self.client.post(path,data={'csrf_token':'audio-csrf','task':'voiceover','brief':''}).text)
        ident=self.source()
        f.db.execute('UPDATE kilas_audio_jobs SET spoken_script=NULL WHERE id=?',(ident,))
        self.assertNotIn('data-audio-alternate',self.latest())
        self.assertNotIn('data-audio-alternate',self.client.get(f'/kilas-translator/jobs/{ident}').text)

    def test_loading_failed_and_foreign_jobs_cannot_supply_latest_actions(self):
        ident=self.source()
        for status in ('QUEUED','PROCESSING','FAILED'):
            f.db.execute('UPDATE kilas_audio_jobs SET status=? WHERE id=?',(status,ident))
            self.assertNotIn('data-audio-alternate',self.latest())
            self.assertNotIn('data-audio-alternate',self.client.get(f'/kilas-translator/jobs/{ident}').text)
        f.db.execute("UPDATE kilas_audio_jobs SET status='COMPLETED',user_id=? WHERE id=?",(self.other,ident))
        self.assertNotIn('data-audio-alternate',self.latest())
        self.assertEqual(self.client.get(f'/kilas-translator/jobs/{ident}').status_code,404)


if __name__=='__main__':unittest.main()
