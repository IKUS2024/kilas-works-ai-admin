"""Unified Home presentation and original task handoffs, with no external transport."""
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import test_kilas_ai_unified as fixture
from kilas_ai import audio_provider, content_projects, content_schema


class HomeTests(unittest.TestCase):
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
            for task in ('chat','voiceover'):self.assertIn('data-home-task="'+task+'"',html)
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
        self.assertIn('How can I Help you?',html)
        for task in ('chat','voiceover'):self.assertIn('data-home-task="'+task+'"',html)
        self.assertNotIn('home-workspace-footer',html)
        self.assertNotIn('premium-home-tools',html)
        self.assertNotIn('href="/kilas-ai/video"',html)
        self.assertNotIn('href="/kilas-translator"',html)
        self.assertNotIn('home-project-options',html)
        self.assertNotIn('premium-home-secondary',html)
        self.assertNotIn('<span>Percakapan</span>',html)
        self.assertEqual(html.count('name="product" value="finance"'),1)
        self.assertIn('data-chat-history-toggle',html)
        self.assertIn('aria-expanded="true" aria-controls="kilas-chat-history"',html)
        self.assertNotIn('home-recent',html)
        self.assertIn('data-chat-sidebar',html)
        self.assertNotIn('home-history-panel',html)
        self.assertNotIn('Belum tersedia untuk akun ini',__import__('re').sub(r'<script\b[^>]*>.*?</script>','',html,flags=__import__('re').S))
        self.assertIn('name="product" value="finance"',html)

    def test_landing_logo_is_available_without_javascript_and_prioritized_in_both_chat_surfaces(self):
        from html.parser import HTMLParser

        class Logos(HTMLParser):
            def __init__(self):
                super().__init__(); self.images=[]

            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag=='img' and attrs.get('class')=='kilas-new-chat-logo':self.images.append(attrs)

        client=self.client()
        for path in ('/products/start','/kilas-ai/agent?conversation='+str(self.conversation)):
            response=client.get(path);self.assertEqual(response.status_code,200)
            logos=Logos();logos.feed(response.text);self.assertEqual(len(logos.images),1)
            image=logos.images[0]
            self.assertEqual((image['width'],image['height'],image['alt']),('1254','1254','Kilas'))
            self.assertEqual((image['loading'],image['fetchpriority'],image['decoding']),('eager','high','async'))
            asset=client.get(image['src'])
            self.assertEqual(asset.status_code,200)
            self.assertEqual(asset.mimetype,'image/webp')
            self.assertLess(len(asset.data),960239*.55)

    def test_available_live_access_is_preserved_without_enabling_it(self):
        from kilas_ai import live_assist, live_qa_budget
        for ready in (False,True):
            with patch.object(live_qa_budget,'enabled',return_value=True), patch.object(live_assist,'ready',return_value=ready), patch.object(live_qa_budget,'ready',return_value=True):
                html=self.client().get('/products/start').get_data(as_text=True)
            visible=__import__('re').sub(r'<script\b[^>]*>.*?</script>','',html,flags=__import__('re').S)
            self.assertEqual('Live translation / Reply assistance' in visible,ready)
            self.assertNotIn('Belum tersedia untuk akun ini',__import__('re').sub(r'<script\b[^>]*>.*?</script>','',html,flags=__import__('re').S))

    def test_shared_sidebar_owned_history_selection_and_native_new_chat(self):
        from kilas_ai import store
        owned=store.create_thread(self.owner);store.rename_thread(self.owner,owned,'My <script> saved title')
        foreign=store.create_thread(self.other);store.rename_thread(self.other,foreign,'Foreign private history')
        for route in ('/products/start','/account?workspace=home','/kilas-translator?mode=voiceover','/kilas-ai/video','/kilas-ai/usage','/kilas-ai/threads/'+str(owned)):
            response=self.client().get(route);self.assertEqual(response.status_code,200)
            html=response.text
            if route.startswith(('/kilas-translator','/account')):
                self.assertNotIn('data-chat-sidebar',html)
                self.assertNotIn('My &lt;script&gt; saved title',html)
            else:
                self.assertEqual(html.count('data-chat-sidebar'),1)
                self.assertIn('My &lt;script&gt; saved title',html)
            self.assertNotIn('Foreign private history',html)
            self.assertNotIn('home-history-panel',html)
        html=self.client().get('/kilas-ai/threads/'+str(owned)).text
        self.assertIn('href="/kilas-ai/threads/'+str(owned)+'" title="My &lt;script&gt; saved title" data-chat-navigation aria-current="page"',html)
        agent=self.client().get('/kilas-ai/agent?conversation='+str(self.conversation)).text
        self.assertIn('action="/kilas-ai/agent/conversations" data-chat-navigation',agent)
        self.assertIn('name="csrf_token" value="work-csrf"',agent)

    def test_sidebar_labels_follow_language_without_translating_history_titles(self):
        from kilas_ai import store
        owned=store.create_thread(self.owner)
        title='Riwayat percakapan <script> My Library'
        store.rename_thread(self.owner,owned,title)
        labels={'id':('Chat baru','Library saya','Chat','See all'),
                'en':('New chat','My Library','Chat','See all'),
                'es':('Nuevo chat','Mi biblioteca','Chat','Ver todo'),
                'zh':('新对话','我的资料库','对话','查看全部')}
        client=self.client()
        for code,(new,library,chat,see_all) in labels.items():
            client.set_cookie('kilas_language',code)
            for route in ('/products/start','/kilas-ai/agent?conversation='+str(self.conversation)):
                with self.subTest(language=code,route=route):
                    html=client.get(route).text
                    self.assertIn('<span>'+new+'</span>',html)
                    self.assertIn('<span>'+library+'</span>',html)
                    self.assertIn('data-chat-history-toggle><span>'+chat+'</span>',html)
                    self.assertIn('>'+see_all+'</button>',html)
                    self.assertIn('data-chat-history-expand aria-expanded="false" aria-controls="kilas-chat-list"',html)
                    self.assertNotIn('href="/kilas-ai/agent?view=history"',html)
                    self.assertIn('title="Riwayat percakapan &lt;script&gt; My Library"',html)
                    self.assertIn('>Riwayat percakapan &lt;script&gt; My Library</a>',html)

    def test_new_chat_and_existing_thread_keep_separate_layout_state_and_full_content(self):
        from kilas_ai import store
        client=self.client()
        empty=client.get('/products/start').text
        self.assertIn('class="ai-main is-empty"',empty)
        self.assertIn('<h1>How can I Help you?</h1>',empty)
        owned=store.create_thread(self.owner)
        content='Full readable synthetic transcript '+('long content ' * 90)
        fixture.base.f.fixture.db.execute("INSERT INTO kilas_ai_messages(thread_id,role,content,created_at) VALUES (?,'user',?,?)",(owned,content,'2026-10-12T17:00:00+00:00'))
        html=client.get('/kilas-ai/threads/'+str(owned)).text
        self.assertNotIn('class="ai-main is-empty"',html)
        self.assertIn(content,html)
        self.assertIn('id="ai-composer"',html)
        self.assertIn('id="ai-messages"',html)
        self.assertIn('class="ai-empty" hidden',html)

    def test_sidebar_projection_excludes_finance_and_disabled_accounts(self):
        client=self.client()
        with client.session_transaction() as values:values['active_product']='finance'
        html=client.get('/account').text
        self.assertNotIn('data-chat-sidebar',html)
        self.assertNotIn('kilas_chat_sidebar.',html)
        self.assertNotIn('data-chat-sidebar',client.get('/account?workspace=home').text)
        with patch.dict(os.environ,{'KILAS_AI_ENABLED':'false'}):
            self.assertNotIn('data-chat-sidebar',client.get('/products/start').text)

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
        response=client.post('/kilas-ai/home-task',data={'csrf_token':'work-csrf','task':'video'})
        self.assertEqual(response.status_code,303)
        self.assertEqual(response.location,'/login')

    def test_old_routes_still_render(self):
        for route in ('/kilas-ai?attachments=1','/kilas-ai/agent?view=history','/kilas-ai/video','/kilas-translator'):
            with self.subTest(route=route):self.assertEqual(self.client().get(route).status_code,200)

    def test_project_data_and_routes_remain_accessible(self):
        with patch.dict(os.environ,{'KILAS_CONTENT_PROJECTS_ENABLED':'true'}):
            # This suite already owns a temporary SQLite fixture on Windows and Linux.
            self.assertEqual(fixture.base.f.fixture.db.BACKEND,'sqlite')
            self.assertTrue(Path(fixture.base.f.fixture.db.SQLITE_PATH).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()))
            content_schema.apply_release()
            ident=content_projects.create(self.owner,'Synthetic retained project','Synthetic brief','home-nav-retained-project')
            client=self.client()
            self.assertEqual(client.get('/products/start').status_code,200)
            self.assertEqual(client.get('/kilas-ai/content-projects').status_code,200)
            self.assertEqual(client.get('/kilas-ai/content-projects/'+str(ident)).status_code,200)
            self.assertEqual(content_projects.get(self.owner,ident)['brief'],'Synthetic brief')

    def test_selected_locale_is_respected(self):
        for language,title in [('en','How can I Help you?'),('es','How can I Help you?'),('zh','How can I Help you?')]:
            client=self.client();client.set_cookie('kilas_language',language)
            response=client.get('/products/start')
            self.assertIn(title,response.get_data(as_text=True))

    def test_account_keeps_finance_forms_without_ai_navigation(self):
        client=self.client();html=client.get('/account').get_data(as_text=True)
        self.assertNotIn('class="account-workspace-access"',html)
        self.assertNotIn('id="premium-sidebar"',html)
        self.assertNotIn('<span>Video</span>',html)
        self.assertNotIn('<span>Translator</span>',html)
        self.assertIn('class="account-back-finance"',html)
        for anchor in ('offer-title','billing-title'):
            settings=client.get('/kilas-ai/usage').get_data(as_text=True)
            self.assertIn('id="'+anchor+'"',settings)
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
        self.assertIn('class="account-back-finance"',html)
        self.assertNotIn('id="premium-sidebar"',html)
        self.assertIn('history.replaceState',html)
        self.assertNotIn('history.pushState',html)
        for action in ('personal_profile','email_change_request','password'):
            self.assertIn('value="'+action+'"',html)
        with client.session_transaction() as values:values['active_product']='kilas_ai'
        with patch.dict(os.environ,{'KILAS_AI_AUTOMATION_ENABLED':'false'}):
            html=client.get('/account').get_data(as_text=True)
            self.assertNotIn('href="/kilas-ai/agent?view=settings"',html)
        with patch.dict(os.environ,{'KILAS_AI_ENABLED':'false'}):
            self.assertNotIn('account-workspace-access',client.get('/account').get_data(as_text=True))

    def test_home_profile_is_informational_and_account_hints_cannot_restore_ai_shell(self):
        import re
        client=self.client()
        with client.session_transaction() as values:values['active_product']='finance'
        home=client.get('/products/start').text
        href=re.search(r'kilas-profile-options.*?<a href="([^"]+)"',home,re.S).group(1)
        self.assertEqual(href,'/kilas-ai/usage')
        self.assertIn('class="kilas-profile-identity"',home)
        self.assertNotIn('href="/account?workspace=home"',home)
        for route in ('/account?workspace=home','/account?workspace=home#security','/account?workspace=home&tab=business'):
            html=client.get(route).text
            self.assertNotIn('class="account-workspace-access"',html)
            self.assertNotIn('id="premium-sidebar"',html)
            self.assertIn('<h1>Accounts</h1>',html)
            self.assertNotIn('<span>Video</span>',html)
        for route in ('/account','/account#business','/account?workspace=finance','/account?workspace=HOME','/account?workspace=invalid'):
            html=client.get(route).text
            self.assertNotIn('account-workspace-access',html)
            self.assertNotIn('<span>Video</span>',html)
            self.assertIn('history.replaceState',html)
        with client.session_transaction() as values:self.assertEqual(values['active_product'],'finance')


if __name__=='__main__':unittest.main()
