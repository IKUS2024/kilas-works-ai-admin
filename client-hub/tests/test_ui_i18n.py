"""Language changes affect explicit UI copy, never customer content or financial values."""
import json
import unittest
import sys
from pathlib import Path
from flask import Flask, render_template_string
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui_i18n


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'isolated-language-test'
        self.app.config['SESSION_COOKIE_SECURE'] = False
        ui_i18n.install(self.app)
        self.app.add_url_rule('/products/start', 'products.product_start', lambda: 'Home')
        self.client = self.app.test_client()

    def test_all_languages_and_cookie_persistence(self):
        for code in ui_i18n.LANGUAGES:
            response = self.client.post('/language', data={'language': code, 'next': '/account?tab=business'})
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.location, '/account?tab=business')
            self.assertIn('HttpOnly', response.headers['Set-Cookie'])
            self.assertIn('SameSite=Lax', response.headers['Set-Cookie'])
            with self.app.test_request_context('/account', headers={'Cookie': 'kilas_language=' + code}):
                self.assertEqual(ui_i18n.language(), code)
                self.assertEqual(ui_i18n.translate('Kirim'), {'id': 'Kirim', 'en': 'Send', 'es': 'Enviar', 'zh': '发送'}[code])

    def test_invalid_language_and_cookie(self):
        self.assertEqual(self.client.post('/language', data={'language': 'invalid'}).status_code, 400)
        with self.app.test_request_context(headers={'Cookie': 'kilas_language=invalid'}):
            self.assertEqual(ui_i18n.language(), 'id')

    def test_retired_page_language_form_does_not_echo_request_identifier(self):
        with self.app.test_request_context('/retired/private'):
            from unittest.mock import patch
            with patch('legacy_order_retirement.retired_endpoint', return_value=True):
                rendered=render_template_string('{{ ui_language_return_path() }}')
                self.assertEqual(rendered,'/products/start')

    def test_redirect_cannot_leave_application(self):
        for destination in ('https://example.test', '//example.test', '/\\example.test', '\\example.test', '/\nexample.test', '//[malformed'):
            with self.subTest(destination=destination):
                response = self.client.post('/language', data={'language': 'es', 'next': destination})
                self.assertEqual(response.location, '/products/start')

    def test_explicit_labels_only_and_safe_interpolation(self):
        with self.app.test_request_context(headers={'Cookie': 'kilas_language=es'}):
            rendered = render_template_string("{{ ui_t('Home') }}|{{ title }}|{{ amount }}|{{ ui_t('Home', unused=title) }}", title='<b>Home</b>', amount='Rp123.456.789.012.300')
            self.assertEqual(rendered, 'Inicio|&lt;b&gt;Home&lt;/b&gt;|Rp123.456.789.012.300|Inicio')

    def test_period_labels_preserve_dates_and_localize_only_ui_months(self):
        with self.app.test_request_context(headers={'Cookie': 'kilas_language=es'}):
            rendered=render_template_string("{{ period|ui_period }}|{{ title }}|{{ ui_t('{count} penerima',count=12) }}",period='Oktober 2026',title='Oktober customer')
            self.assertEqual(rendered,'octubre 2026|Oktober customer|12 destinatarios')

    def test_catalog_placeholders_remain_identical(self):
        import re
        for key, translations in ui_i18n.CATALOG.items():
            placeholders=set(re.findall(r'\{\w+\}',key))
            for translated in translations.values():
                self.assertEqual(placeholders,set(re.findall(r'\{\w+\}',translated)),key)
        self.assertTrue(set(ui_i18n.CLIENT_MESSAGES)<=set(ui_i18n.CATALOG))

    def test_catalog_is_complete_and_has_no_empty_translations(self):
        for key, translations in ui_i18n.CATALOG.items():
            self.assertEqual(set(translations), {'en', 'es', 'zh'}, key)
            self.assertTrue(all(value.strip() for value in translations.values()), key)


if __name__ == '__main__':
    unittest.main()
