"""Language changes affect explicit UI copy, never customer content or financial values."""
import unittest
import sys
from pathlib import Path
from flask import Blueprint, Flask, render_template_string
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui_i18n


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'isolated-language-test'
        self.app.config['SESSION_COOKIE_SECURE'] = False
        ui_i18n.install(self.app)
        self.app.add_url_rule('/products/start', 'products.product_start', lambda: 'Home')
        audio = Blueprint('kilas_audio', __name__)
        @audio.get('/ui-probe', endpoint='status')
        def probe():
            return {'error': 'Pilih suara', 'status_label': 'Menunggu',
                    'script': 'Pilih suara', 'translated_text': 'Pilih suara',
                    'language_a': 'id', 'language_b': 'en', 'voice': 'kilas-male',
                    'seconds_charged': 7, 'content': {'error': 'Pilih suara'}}, 409, {'Cache-Control': 'private, no-store'}
        @audio.get('/content-probe')
        def content_probe():
            return {'error': 'Pilih suara', 'status_label': 'Menunggu'}
        @audio.get('/download-probe')
        def download_probe():
            return {'error': 'Pilih suara', 'status': 'FAILED', 'code': 'user-content'}, 200, {'Content-Disposition': 'attachment; filename=original.json'}
        self.app.register_blueprint(audio)
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
            self.assertEqual(ui_i18n.language(), 'en')

    def test_default_is_english_without_using_browser_language(self):
        for headers in ({}, {'Accept-Language': 'id-ID,id;q=0.9'}):
            with self.app.test_request_context(headers=headers):
                self.assertEqual(ui_i18n.language(), 'en')
                self.assertEqual(ui_i18n.translate('Kirim'), 'Send')
                self.assertEqual(ui_i18n.translate('Pilih suara'), 'Choose a voice')

    def test_new_english_ui_catalog_preserves_placeholders(self):
        import re
        for key, translated in ui_i18n.EN_MESSAGES.items():
            self.assertTrue(translated.strip(), key)
            self.assertEqual(set(re.findall(r'\{\w+\}', key)),
                             set(re.findall(r'\{\w+\}', translated)), key)

    def test_numeric_ui_errors_keep_exact_values_and_leave_other_text_unchanged(self):
        with self.app.test_request_context():
            self.assertEqual(ui_i18n.translate_ui_message('File maksimal 10 MB.'),
                             'Files must be no larger than 10 MB.')
            self.assertEqual(ui_i18n.translate_ui_message('Saldo tidak cukup. Dibutuhkan 12s; saldo tersedia 3s.'),
                             'Insufficient balance. 12s required; 3s available.')
            self.assertEqual(ui_i18n.translate_ui_message('Customer wrote: Pilih suara'),
                             'Customer wrote: Pilih suara')

    def test_response_localizes_only_designated_ui_fields_preserving_security_and_content(self):
        response = self.client.get('/ui-probe')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        self.assertIn('Cookie', response.vary)
        self.assertEqual(response.json['error'], 'Choose a voice')
        self.assertEqual(response.json['status_label'], 'Waiting')
        for key in ('script', 'translated_text'):
            self.assertEqual(response.json[key], 'Pilih suara')
        self.assertEqual(response.json['content'], {'error': 'Pilih suara'})
        self.assertEqual((response.json['language_a'], response.json['language_b'],
                          response.json['voice'], response.json['seconds_charged']),
                         ('id', 'en', 'kilas-male', 7))
        self.client.set_cookie('kilas_language', 'id')
        self.assertEqual(self.client.get('/ui-probe').json['error'], 'Pilih suara')

    def test_successful_content_and_download_json_are_never_translated(self):
        for path in ('/content-probe', '/download-probe'):
            self.assertEqual(self.client.get(path).json['error'], 'Pilih suara')
        self.assertEqual(self.client.get('/content-probe').json['status_label'], 'Menunggu')

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
        self.assertTrue(set(ui_i18n.CLIENT_MESSAGES)<=(set(ui_i18n.CATALOG)|set(ui_i18n.EN_MESSAGES)))

    def test_catalog_is_complete_and_has_no_empty_translations(self):
        for key, translations in ui_i18n.CATALOG.items():
            self.assertTrue({'en', 'es', 'zh'} <= set(translations) <= set(ui_i18n.LANGUAGES), key)
            self.assertTrue(all(value.strip() for value in translations.values()), key)

    def test_english_source_ui_keys_have_explicit_indonesian_client_mappings(self):
        with self.app.test_request_context(headers={'Cookie':'kilas_language=id'}):
            context = {}
            self.app.update_template_context(context)
            for key, expected in [('See all','Lihat semua'),('Profile','Profil'),
                                  ('Wallet','Dompet'),('Generate Voice Over','Buat Voice Over')]:
                self.assertEqual(ui_i18n.translate(key), expected)
                self.assertEqual(context['ui_messages'][key], expected)


if __name__ == '__main__':
    unittest.main()
