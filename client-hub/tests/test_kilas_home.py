"""Unified Home presentation and original task handoffs, with no external transport."""
import os
import unittest
from unittest.mock import patch
from pathlib import Path
import test_kilas_ai_unified as fixture
from kilas_ai import audio_provider, content_projects, content_schema


class HomeTests(unittest.TestCase):
    setUp=fixture.UnifiedTests.setUp
    client=fixture.UnifiedTests.client

    def setUp(self):
        fixture.UnifiedTests.setUp(self)
        self.offering=patch.dict(os.environ,{'KILAS_AUDIO_UPLOAD_TRANSLATION_VISIBLE':'true'});self.offering.start();self.addCleanup(self.offering.stop)
        self.network=patch('requests.sessions.Session.request',side_effect=AssertionError('External transport forbidden'))
        self.network.start();self.addCleanup(self.network.stop)
        self.voices=patch.object(audio_provider,'voices',return_value=[])
        self.voices.start();self.addCleanup(self.voices.stop)

    def handoff(self,task,brief='Synthetic <script>alert(1)</script> brief'):
        return self.client().post('/kilas-ai/home-task',data={'csrf_token':'work-csrf','task':task,'brief':brief})

    def test_hidden_upload_entry_keeps_other_tools_and_native_handoff(self):
        with patch.dict(os.environ,{'KILAS_AUDIO_UPLOAD_TRANSLATION_VISIBLE':'false'}):
            html=self.client().get('/products/start').text
            self.assertNotIn('data-home-task="translate"',html)
            for task in ('chat','video','voiceover'):self.assertIn('data-home-task="'+task+'"',html)
            response=self.handoff('translate','A carried brief')
            self.assertEqual(response.status_code,200)
            self.assertIn('A carried brief',response.text)
            self.assertIn('data-active-mode="voiceover"',response.text)
            self.assertNotIn('id="audio-file"',response.text)
            self.assertNotIn('data-kilas-feature="translate"',self.client().get('/kilas-ai/video').text)

    def test_home_single_entry_no_duplicate_tools(self):
        with patch.dict(os.environ,{'KILAS_LIVE_ASSIST_QA_ENABLED':'false','KILAS_LIVE_ASSIST_ENABLED':'false'}):
            response=self.client().get('/products/start')
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        self.assertIn('Mau ngapain hari ini?',html)
        for task in ('chat','video','translate','voiceover'):self.assertIn('data-home-task="'+task+'"',html)
        self.assertNotIn('home-workspace-footer',html)
        self.assertNotIn('premium-home-tools',html)
        self.assertNotIn('href="/kilas-ai/video"',html)
        self.assertNotIn('href="/kilas-translator"',html)
        self.assertNotIn('home-project-options',html)
        self.assertNotIn('premium-home-secondary',html)
        self.assertNotIn('<span>Percakapan</span>',html)
        self.assertEqual(html.count('name="product" value="finance"'),1)
        self.assertIn('Riwayat percakapan',html)
        self.assertNotIn('home-recent',html)
        self.assertIn('home-history-panel',html)
        self.assertNotIn('Belum tersedia untuk akun ini',html)
        self.assertIn('name="product" value="finance"',html)

    def test_available_live_access_is_preserved_without_enabling_it(self):
        from kilas_ai import live_assist, live_qa_budget
        for ready in (False,True):
            with patch.object(live_qa_budget,'enabled',return_value=True), patch.object(live_assist,'ready',return_value=ready), patch.object(live_qa_budget,'ready',return_value=True):
                html=self.client().get('/products/start').get_data(as_text=True)
            self.assertEqual('Terjemahan langsung / Bantu jawab' in html,ready)
            self.assertNotIn('Belum tersedia untuk akun ini',html)

    def test_task_handoffs_escape_drafts_preserve_original_forms(self):
        for task in ('chat','video','translate','voiceover'):
            with self.subTest(task=task):
                response=self.handoff(task);self.assertEqual(response.status_code,200)
                html=response.get_data(as_text=True)
                self.assertNotIn('<script>alert(1)</script>',html)
                self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',html)
                if task=='video':
                    self.assertIn('action="/kilas-ai/video/plan"',html)
                    self.assertIn('name="references"',html)
                if task in ('translate','voiceover'):
                    self.assertIn('action="/kilas-translator/jobs"',html)
                    self.assertIn('data-active-mode="'+task+'"',html)
                if task!='chat':self.assertIn('Kembali ke Kilas AI Home',html)

    def test_native_feature_handoff_validated_without_generating(self):
        app=fixture.base.f.fixture.app.app
        from kilas_ai import audio_service,video_director
        with patch.object(audio_service,'submit') as audio,patch.object(video_director,'generate') as video:
            for path,task in (('/kilas-translator?mode=voiceover','voiceover'),('/kilas-translator?mode=translate','translate'),('/kilas-ai/video','video')):
                response=self.client().post(path,data={'csrf_token':'work-csrf','task':task,'brief':'Native carried draft'})
                self.assertEqual(response.status_code,200);self.assertIn('Native carried draft',response.get_data(as_text=True))
                self.assertEqual(self.client().post(path,data={'task':task}).status_code,400)
                self.assertEqual(self.client().post(path,data={'csrf_token':'work-csrf','task':'chat'}).status_code,400)
                self.assertEqual(app.test_client().post(path,data={'csrf_token':'work-csrf','task':task}).status_code,400)
            audio.assert_not_called();video.assert_not_called()

    def test_invalid_csrf_task_and_size_rejected(self):
        self.assertEqual(self.client().post('/kilas-ai/home-task',data={'task':'video','brief':'draft'}).status_code,400)
        self.assertEqual(self.handoff('unknown').status_code,400)
        self.assertEqual(self.handoff('video','x'*2401).status_code,400)
        self.assertEqual(self.handoff('voiceover','x'*4001).status_code,400)

    def test_anonymous_and_non_owner_gates(self):
        app=fixture.base.f.fixture.app.app
        self.assertEqual(app.test_client().post('/kilas-ai/home-task',data={'task':'video'}).status_code,400)
        client=self.client()
        fixture.base.f.fixture.db.execute('UPDATE users SET role=? WHERE id=?',('KILAS_ADMIN',self.owner))
        self.assertEqual(client.post('/kilas-ai/home-task',data={'csrf_token':'work-csrf','task':'video'}).status_code,404)

    def test_old_routes_still_render(self):
        for route in ('/kilas-ai?attachments=1','/kilas-ai/agent?view=history','/kilas-ai/video','/kilas-translator'):
            with self.subTest(route=route):self.assertEqual(self.client().get(route).status_code,200)

    def test_project_data_and_routes_remain_accessible(self):
        with patch.dict(os.environ,{'KILAS_CONTENT_PROJECTS_ENABLED':'true'}):
            content_schema.apply_disposable_sqlite(Path(fixture.base.f.fixture.db.SQLITE_PATH).parent)
            ident=content_projects.create(self.owner,'Synthetic retained project','Synthetic brief','home-nav-retained-project')
            client=self.client()
            self.assertEqual(client.get('/products/start').status_code,200)
            self.assertEqual(client.get('/kilas-ai/content-projects').status_code,200)
            self.assertEqual(client.get('/kilas-ai/content-projects/'+str(ident)).status_code,200)
            self.assertEqual(content_projects.get(self.owner,ident)['brief'],'Synthetic brief')

    def test_selected_locale_is_respected(self):
        for language,title in [('en','What would you like to do today?'),('es','¿Qué quieres hacer hoy?'),('zh','今天想做什么？')]:
            client=self.client();client.set_cookie('kilas_language',language)
            response=client.get('/products/start')
            self.assertIn(title,response.get_data(as_text=True))

    def test_account_uses_home_navigation_and_existing_destinations(self):
        client=self.client();html=client.get('/account').get_data(as_text=True)
        self.assertIn('account-workspace-access',html)
        self.assertNotIn('<span>Video</span>',html)
        self.assertNotIn('<span>Translator</span>',html)
        self.assertIn('href="/account?workspace=home" aria-current="page"',html)
        self.assertIn('href="/kilas-ai/usage"',html)
        for anchor in ('offer-title','audio-settings-title','billing-title'):
            self.assertIn('href="/kilas-ai/usage#'+anchor+'"',html)
            settings=client.get('/kilas-ai/usage').get_data(as_text=True)
            self.assertIn('id="'+anchor+'"',settings)
        self.assertIn('href="/kilas-ai/agent?view=settings"',html)
        self.assertEqual(client.get('/kilas-ai/agent?view=settings').status_code,200)
        for action in ('personal_profile','email_change_request','password'):
            # Existing account forms remain available; no replacement account backend.
            self.assertIn('value="'+action+'"',html)

    def test_account_finance_content_preserved_with_canonical_home_navigation(self):
        client=self.client()
        with client.session_transaction() as values:values['active_product']='finance'
        html=client.get('/account').get_data(as_text=True)
        self.assertNotIn('account-workspace-access',html)
        for label in ('Video','Translator','Kilas AI'):
            self.assertNotIn('<span>'+label+'</span>',html)
        self.assertIn('href="/account" aria-current="page"',html)
        self.assertIn('history.replaceState',html)
        self.assertNotIn('history.pushState',html)
        self.assertIn('href="/kilas-ai/usage"',html)
        for action in ('personal_profile','email_change_request','password'):
            self.assertIn('value="'+action+'"',html)
        with client.session_transaction() as values:values['active_product']='kilas_ai'
        with patch.dict(os.environ,{'KILAS_AI_AUTOMATION_ENABLED':'false'}):
            html=client.get('/account').get_data(as_text=True)
            self.assertNotIn('href="/kilas-ai/agent?view=settings"',html)
        with patch.dict(os.environ,{'KILAS_AI_ENABLED':'false'}):
            self.assertNotIn('account-workspace-access',client.get('/account').get_data(as_text=True))

    def test_home_account_entry_overrides_only_presentation_in_finance_session(self):
        import re
        client=self.client()
        with client.session_transaction() as values:values['active_product']='finance'
        home=client.get('/products/start').text
        href=re.search(r'premium-sidebar-account.*?<a href="([^"]+)"',home).group(1)
        self.assertEqual(href,'/account?workspace=home')
        for route in (href,href+'#security','/account?workspace=home&tab=business'):
            html=client.get(route).text
            self.assertIn('account-workspace-access',html)
            self.assertIn('<h1>Akun saya</h1>',html)
            self.assertNotIn('<span>Video</span>',html)
        for route in ('/account','/account#business','/account?workspace=finance','/account?workspace=HOME','/account?workspace=invalid'):
            html=client.get(route).text
            self.assertNotIn('account-workspace-access',html)
            self.assertNotIn('<span>Video</span>',html)
            self.assertIn('history.replaceState',html)
        with client.session_transaction() as values:self.assertEqual(values['active_product'],'finance')


if __name__=='__main__':unittest.main()
