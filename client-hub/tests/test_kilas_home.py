"""Unified Home presentation and original task handoffs, with no external transport."""
import os
import unittest
from unittest.mock import patch
from pathlib import Path
import test_kilas_ai_unified as fixture
from kilas_ai import audio_provider, content_projects


class HomeTests(unittest.TestCase):
    setUp=fixture.UnifiedTests.setUp
    client=fixture.UnifiedTests.client

    def setUp(self):
        fixture.UnifiedTests.setUp(self)
        self.network=patch('requests.sessions.Session.request',side_effect=AssertionError('External transport forbidden'))
        self.network.start();self.addCleanup(self.network.stop)
        self.voices=patch.object(audio_provider,'voices',return_value=[])
        self.voices.start();self.addCleanup(self.voices.stop)

    def handoff(self,task,brief='Synthetic <script>alert(1)</script> brief'):
        return self.client().post('/kilas-ai/home-task',data={'csrf_token':'work-csrf','task':task,'brief':brief})

    def test_home_single_entry_optional_projects_and_live_unavailable(self):
        with patch.dict(os.environ,{'KILAS_LIVE_ASSIST_QA_ENABLED':'false','KILAS_LIVE_ASSIST_ENABLED':'false'}):
            response=self.client().get('/products/start')
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        self.assertIn('Mau ngapain hari ini?',html)
        for task in ('chat','video','translate','voiceover'):self.assertIn('data-home-task="'+task+'"',html)
        self.assertIn('Belum tersedia untuk akun ini',html)
        self.assertNotIn('premium-home-tools',html)
        self.assertNotIn('href="/kilas-ai/video"',html)
        self.assertNotIn('href="/kilas-translator"',html)
        self.assertIn('home-project-options',html)
        self.assertIn('name="product" value="finance"',html)

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

    def test_selected_locale_is_respected(self):
        for language,title in [('en','What would you like to do today?'),('es','¿Qué quieres hacer hoy?'),('zh','今天想做什么？')]:
            client=self.client();client.set_cookie('kilas_language',language)
            response=client.get('/products/start')
            self.assertIn(title,response.get_data(as_text=True))


if __name__=='__main__':unittest.main()
