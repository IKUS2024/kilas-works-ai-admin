"""Asset discovery, tenant authorization and editable, nonpaid task handoffs."""
import unittest
from unittest.mock import patch
from html.parser import HTMLParser
import test_kilas_home as home
from kilas_ai import store,audio_store,audio_service,audio_provider
db=home.fixture.base.f.fixture.db


class Textarea(HTMLParser):
    def __init__(self):super().__init__();self.active=False;self.value=''
    def handle_starttag(self,tag,attrs):
        if tag=='textarea':self.active=dict(attrs).get('id')=='audio-script'
    def handle_endtag(self,tag):
        if tag=='textarea':self.active=False
    def handle_data(self,text):
        if self.active:self.value+=text


class ExperienceTests(unittest.TestCase):
    setUp=home.HomeTests.setUp
    client=home.HomeTests.client

    def test_legacy_plain_artifact_metadata_preserves_downloads_and_input_privacy(self):
        from kilas_ai import autonomous_store
        for owner in (self.owner,self.other):
            job=autonomous_store.create(owner,'Legacy files')
            db.execute("INSERT INTO kilas_agent_steps(job_id,sequence,worker,action,instruction,idempotency_key) VALUES (?,1,'FILE','create','Legacy',?)",(job,'legacy-'+str(job)))
            step=db.query_one('SELECT id FROM kilas_agent_steps WHERE job_id=?',(job,))['id']
            for number,content in enumerate(('# Legacy markdown','{broken JSON','{"input":true}','{"input":false}')):
                name=f'legacy-{owner}-{number}.txt'
                db.execute("INSERT INTO kilas_agent_artifacts(job_id,step_id,name,media_type,content,digest) VALUES (?,?,?,'text/plain',?,?)",(job,step,name,content,name))
                ident=db.query_one('SELECT id FROM kilas_agent_artifacts WHERE name=?',(name,))['id']
                db.execute('INSERT INTO kilas_agent_artifact_files(artifact_id,content,byte_size) VALUES (?,?,3)',(ident,b'old'))
        html=self.client().get('/kilas-ai/library').text
        for number in (0,1,3):self.assertIn(f'legacy-{self.owner}-{number}.txt',html)
        self.assertNotIn(f'legacy-{self.owner}-2.txt',html)
        self.assertNotIn(f'legacy-{self.other}-',html)
        with home.fixture.base.f.fixture.app.app.test_request_context('/kilas-ai/library'):
            from kilas_ai.library import collection
            data=collection(self.owner,True)
        self.assertEqual(data['total'],3)
        for item in data['assets']:
            self.assertEqual(self.client().get(item['open']).data,b'old')
            self.assertEqual(self.client(self.other).get(item['download']).status_code,404)

    def attachment(self,owner,name='1729999999.jpg',date='2026-10-22T00:00:00+00:00'):
        thread=store.create_thread(owner);store.rename_thread(owner,thread,'Product catalogue')
        db.execute('INSERT INTO kilas_ai_attachments(user_id,thread_id,filename,mime_type,byte_size,content,created_at) VALUES (?,?,?,?,?,?,?)',(owner,thread,name,'image/jpeg',3,b'bad',date))
        ident=db.query_one('SELECT MAX(id) AS n FROM kilas_ai_attachments WHERE user_id=?',(owner,))['n']
        return f'/kilas-ai/threads/{thread}/attachments/{ident}'

    def audio(self,owner,title='Newest voice',origin='voiceover',status='COMPLETED'):
        db.execute("INSERT INTO kilas_audio_jobs(user_id,operation_key,fingerprint,mode,title,source_language,target_language,voice_name,estimated_seconds,reserved_seconds,status,actual_ms,created_at,updated_at,content_origin) VALUES (?,?,?,'voiceover',?,'id','id','QA Voice',2,0,?,2000,'2026-10-22T01:00:00+00:00','2026-10-22T01:00:00+00:00',?)",(owner,title+str(owner),'synthetic',title,status,origin))
        return db.query_one('SELECT MAX(id) AS n FROM kilas_audio_jobs WHERE user_id=?',(owner,))['n']

    def test_library_mixed_latest_search_literal_and_account_scoping(self):
        own=self.attachment(self.owner);foreign=self.attachment(self.other,'Foreign secret.jpg')
        ident=self.audio(self.owner);self.audio(self.other,'Foreign private voice');self.audio(self.owner,'Hidden live','live_session')
        html=self.client().get('/kilas-ai/library').text
        self.assertIn('Product catalogue',html);self.assertIn('1729999999.jpg',html)
        self.assertIn('Newest voice',html);self.assertLess(html.index('<h2><a href="/kilas-translator'),html.index('<h2><a href="'+own))
        self.assertNotIn('Foreign secret',html);self.assertNotIn('Foreign private voice',html);self.assertNotIn('Hidden live',html)
        self.assertIn('private, no-store',self.client().get('/kilas-ai/library').headers['Cache-Control'])
        filtered=self.client().get('/kilas-ai/library?type=audio').text
        self.assertNotIn('1729999999.jpg',filtered);self.assertIn('Newest voice',filtered)
        self.assertNotIn('Newest voice',self.client().get('/kilas-ai/library?q=%25').text)
        self.assertIn('1729999999.jpg',self.client().get('/kilas-ai/library?q=catalogue').text)
        for path in (foreign,foreign+'?inline=1',f'/kilas-translator/jobs/{ident}/result'):
            # Own audio result may be empty in this metadata fixture; foreign is always denied.
            if path.startswith(foreign):self.assertEqual(self.client().get(path).status_code,404)
        other_audio=self.audio(self.other,'Hidden audio')
        for suffix in ('','/result','/script'):
            self.assertEqual(self.client().get(f'/kilas-translator/jobs/{other_audio}'+suffix).status_code,404)

    def test_library_pagination_finds_older_files_without_removing_or_duplicating(self):
        for number in range(29):self.attachment(self.owner,f'Photo {number:02}.jpg')
        before=db.query_one('SELECT COUNT(*) AS n FROM kilas_ai_attachments WHERE user_id=?',(self.owner,))['n']
        first=self.client().get('/kilas-ai/library').text;second=self.client().get('/kilas-ai/library?page=2').text
        self.assertEqual(first.count('class="library-asset"'),24);self.assertEqual(second.count('class="library-asset"'),5)
        self.assertIn('Photo 00.jpg',second);self.assertIn('Photo 00.jpg',self.client().get('/kilas-ai/library?q=Photo+00').text)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_ai_attachments WHERE user_id=?',(self.owner,))['n'],before)
        self.assertEqual(self.client().get('/kilas-ai/library?type=forbidden').status_code,400)
        self.assertEqual(self.client().get('/kilas-ai/library?page=bad').status_code,400)

    def test_exact_script_handoff_no_generation_no_open_redirect_and_csrf(self):
        script='  Naskah <b>asli</b> & 日本語\n\n  Akhir.  '
        with patch.object(audio_service,'submit',side_effect=AssertionError('No generation')),patch.object(audio_provider,'request',side_effect=AssertionError('No provider')):
            response=self.client().post('/kilas-ai/home-task',data={'csrf_token':'work-csrf','task':'voiceover','brief':script,'return_to':'/products/start'})
        self.assertEqual(response.status_code,200)
        parser=Textarea();parser.feed(response.text);self.assertEqual(parser.value.removeprefix('\n'),script)
        self.assertIn('class="audio-draft-return"',response.text)
        malicious=self.client().post('/kilas-ai/home-task',data={'csrf_token':'work-csrf','task':'voiceover','brief':script,'return_to':'//evil.test'})
        self.assertNotIn('class="audio-draft-return"',malicious.text)
        self.assertEqual(self.client().post('/kilas-ai/home-task',data={'task':'voiceover','brief':script}).status_code,400)
        self.assertEqual(self.client().post('/kilas-ai/home-task',data={'csrf_token':'work-csrf','task':'voiceover','brief':'x'*4001}).status_code,400)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs WHERE user_id=?',(self.owner,))['n'],0)

    def test_latest_voice_result_excludes_other_owners_live_and_failed_jobs(self):
        ident=self.audio(self.owner,'Saved readable script');self.audio(self.other,'Foreign latest');self.audio(self.owner,'Failed latest',status='FAILED');self.audio(self.owner,'Live latest','live_session')
        html=self.client().get('/kilas-translator?mode=voiceover').text
        self.assertIn('audio-latest-result',html);self.assertIn('Saved readable script',html)
        latest=html.split('class="audio-latest-result"',1)[1].split('class="audio-tabs"',1)[0]
        self.assertNotIn('Foreign latest',latest);self.assertNotIn('Failed latest',latest);self.assertNotIn('Live latest',latest)
        self.assertIn(f'/kilas-translator/jobs/{ident}/result',latest)

    def test_starters_follow_ui_language_without_changing_models(self):
        for language,label in [('id','Naskah promosi'),('en','Promotional script'),('es','Guion promocional'),('zh','推广文案')]:
            client=self.client();client.set_cookie('kilas_language',language);html=client.get('/products/start').text
            self.assertNotIn('data-home-starter=',html);self.assertNotIn('class="home-starters"',html);self.assertIn('data-chat-model',html);self.assertIn('kilas-new-chat-logo',html)


if __name__=='__main__':unittest.main()
