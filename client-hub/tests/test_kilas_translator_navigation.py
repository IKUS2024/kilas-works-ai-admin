"""Translator navigation is independent of provider readiness; no paid calls."""
import unittest
from html.parser import HTMLParser
from unittest.mock import patch

import test_kilas_home as fixture
from kilas_ai import audio_routes, live_gemini, live_translator, store


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.append(dict(attrs))


class TranslatorNavigationTests(unittest.TestCase):
    setUp = fixture.HomeTests.setUp
    client = fixture.HomeTests.client

    def test_chat_links_to_guarded_page_when_all_transports_unavailable(self):
        thread = store.create_thread(self.owner)
        with patch.object(live_translator, 'ready', return_value=False), \
             patch.object(live_gemini, 'ready', return_value=False), \
             patch.object(audio_routes, '_native_default_ready', return_value=False):
            for locale in ('id', 'en', 'es', 'zh'):
                client = self.client()
                client.set_cookie('kilas_language', locale)
                for path in ('/products/start', '/kilas-ai', f'/kilas-ai/threads/{thread}'):
                    page = client.get(path, follow_redirects=True)
                    self.assertEqual(page.status_code, 200)
                    links = [a for a in Links(page.text).links if a.get('href') == '/kilas-translator/live']
                    self.assertEqual(len(links), 1, (locale, path))
                    self.assertNotIn('aria-disabled', links[0])
                    self.assertNotIn('kilas-translator-pending', page.text)
                page = client.get('/kilas-translator/live')
                self.assertEqual(page.status_code, 200)
                self.assertIn('data-ready="false"', page.text)
                blocked = client.post('/kilas-translator/live/sessions', data={
                    'csrf_token': 'work-csrf', 'consent': 'yes',
                    'language_a': 'id', 'language_b': 'en', 'voice': 'kilas-male'})
                self.assertEqual(blocked.status_code, 503)
                self.assertEqual(blocked.json['code'], 'translator_unavailable')

    def test_navigation_retains_auth_and_native_routing(self):
        app = fixture.fixture.base.f.fixture.app.app
        anonymous = app.test_client().get('/kilas-translator/live')
        self.assertIn(anonymous.status_code, (302, 303))
        self.assertIn('/login', anonymous.location)
        with patch.object(live_translator, 'ready', return_value=False), \
             patch.object(audio_routes, '_native_default_ready', return_value=True), \
             patch.object(live_gemini, 'ready', return_value=True):
            response = self.client().get('/kilas-translator/live')
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.location, '/kilas-translator/interpreter')


if __name__ == '__main__':
    unittest.main()
