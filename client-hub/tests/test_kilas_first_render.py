"""Initial style/markup contracts on disposable fixtures; no external transport."""
import unittest
from html.parser import HTMLParser
from unittest.mock import patch
import test_kilas_home as fixture
from kilas_ai import live_translator as live, audio_branded_voices as branded, translator_languages as languages, live_gemini as native, live_gemini_pair as pair


class Assets(HTMLParser):
    def __init__(self, text):
        super().__init__(); self.head = False; self.styles = []; self.buttons = []; self.preloads = []; self.feed(text)
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'head': self.head = True
        if tag == 'link' and attrs.get('rel') == 'stylesheet': self.styles.append((self.head, attrs['href']))
        if tag == 'link' and attrs.get('rel') == 'preload': self.preloads.append(attrs)
        if tag == 'button' and 'data-translator-trigger' in attrs: self.buttons.append(attrs)
    def handle_endtag(self, tag):
        if tag == 'head': self.head = False


class FirstRenderTests(unittest.TestCase):
    def setUp(self):
        fixture.HomeTests.setUp(self)
        for module, name, value in ((languages,'classic_names',languages.names(languages.CLASSIC)),
                                    (native,'ready',True),(pair,'ready',True)):
            mocked=patch.object(module,name,return_value=value);mocked.start();self.addCleanup(mocked.stop)
    client = fixture.HomeTests.client

    def test_all_initial_workspace_styles_are_in_head_once(self):
        with patch.object(live, 'ready', return_value=True), patch.object(branded, 'public_choices', return_value=[{'alias':'kilas-male','name':'Kilas Male'}]):
            for path in ('/products/start', '/kilas-translator/live', '/kilas-translator?mode=voiceover', '/kilas-translator/live/gemini'):
                with self.subTest(path=path):
                    response = self.client().get(path); self.assertEqual(response.status_code, 200)
                    assets = Assets(response.text)
                    self.assertTrue(assets.styles)
                    self.assertTrue(all(head for head, _ in assets.styles), assets.styles)
                    urls = [url for _, url in assets.styles]
                    self.assertEqual(len(urls), len(set(urls)))
                    self.assertEqual(len([p for p in assets.preloads if p.get('as') == 'font']), 1)
                    self.assertIn('manrope-variable.ttf', assets.preloads[0]['href'])

    def test_language_picker_has_final_controls_and_native_form_values_before_javascript(self):
        with patch.object(live, 'ready', return_value=True), patch.object(branded, 'public_choices', return_value=[{'alias':'kilas-male','name':'Kilas Male'}]):
            client = self.client(); client.set_cookie('kilas_language', 'en')
            response = client.get('/kilas-translator/live')
        assets = Assets(response.text)
        self.assertEqual(len(assets.buttons), 2)
        self.assertEqual([b['aria-label'] for b in assets.buttons], ['First language', 'Second language'])
        self.assertTrue(all(b['aria-haspopup'] == 'listbox' and b['type'] == 'button' for b in assets.buttons))
        self.assertIn('name="language_a" required', response.text)
        self.assertIn('name="language_b" required', response.text)
        self.assertIn('<noscript><style>', response.text)
        self.assertIn('value="id" selected', response.text)
        self.assertIn('value="en" selected', response.text)
        self.assertNotIn('visibility:hidden', response.text)

    def test_unrelated_finance_context_does_not_opt_into_shell_font_preload(self):
        client = self.client()
        with client.session_transaction() as values: values['active_product'] = 'finance'
        html = client.get('/account?workspace=finance').text
        self.assertNotIn('as="font"', html)
        self.assertNotIn('data-translator-picker', html)


if __name__ == '__main__': unittest.main()
