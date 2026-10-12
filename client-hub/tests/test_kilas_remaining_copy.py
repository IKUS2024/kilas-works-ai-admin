"""Presentation-only remaining copy, owned synthetic pages and Finance DOM proof."""
import re
import subprocess
import unittest
from jinja2 import ChoiceLoader, DictLoader
import test_kilas_tabs_copy as tabs_fixture

BASE = '1565016fb928a3299a694302c07a861c6087eee2'
INTRO = 'Kelola profil Pribadi, Bisnis, keamanan, dan data invoice Kilas Works.'


class RemainingCopyTests(unittest.TestCase):
    def setUp(self):
        self.base = tabs_fixture.TabsCopyTests('test_feature_routes_keep_inputs_user_content_and_essential_notices')
        self.base.id = lambda: self.id()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.client = self.base.client
        self.paths = {'settings': '/kilas-ai/usage', 'account': '/account?workspace=home',
                      'services': '/products/services', 'catalog': '/services'}

    def old_template(self, name):
        return subprocess.check_output(['git', 'show', BASE+':client-hub/templates/'+name], text=True, encoding='utf-8')

    def baseline(self, name, path):
        env = tabs_fixture.fixture.app.app.jinja_env
        previous = env.loader
        env.loader = ChoiceLoader([DictLoader({name: self.old_template(name)}), previous])
        env.cache.clear()
        try:
            return self.client.get(path)
        finally:
            env.loader = previous
            env.cache.clear()

    @staticmethod
    def controls(html):
        return re.findall(r'<(?:form|input|button|select|option|textarea|a)\b[^>]*>', html)

    def test_owned_pages_keep_controls_prices_terms_and_service_content(self):
        templates = {'settings': 'kilas_ai/usage.html', 'account': 'account.html',
                     'services': 'kilas_services.html', 'catalog': 'service_catalog.html'}
        removed = {'settings': ['Akun, pembelian, dan penggunaan Kilas AI, Video, serta Translator.'],
                   'account': [], 'services': ['Ceritakan kebutuhan Anda. Tim kami akan membantu'],
                   'catalog': ['Pilih kategori dulu, baru lihat layanan di dalamnya.',
                               'Pilih talent dari profil bergambar, lihat niche dan ketersediaannya']}
        for key, path in self.paths.items():
            with self.subTest(surface=key):
                before = self.baseline(templates[key], path)
                after = self.client.get(path)
                self.assertEqual((before.status_code, after.status_code), (200, 200))
                if key in ('account','settings'):
                    # Navigation changed intentionally; profile/security and purchase forms did not.
                    pattern=r'<form\b.*?</form>'
                    self.assertEqual(re.findall(pattern,before.text,re.S),re.findall(pattern,after.text,re.S))
                else:
                    self.assertEqual(self.controls(before.text), self.controls(after.text))
                for text in removed[key]: self.assertNotIn(text, after.text)
                if key == 'settings':
                    for text in ('Rp99.000', 'Aktif hingga', 'Perpanjangan dilakukan melalui tagihan baru.',
                                 'Fair Use', 'Batas keamanan', '90 hari', 'Saldo Audio', 'Belum ada tagihan.'):
                        self.assertIn(text, after.text)
                if key == 'services':
                    summaries = re.findall(r'<p class="service-summary">(.*?)</p>', before.text, re.S)
                    self.assertEqual(len(summaries), 3)
                    self.assertEqual(summaries, re.findall(r'<p class="service-summary">(.*?)</p>', after.text, re.S))
                    self.assertEqual(after.text.count('<summary>Info layanan</summary>'), len(summaries))
                    for text in ('Persetujuan Anda diperlukan.', 'bukan kedutaan', 'Keputusan visa sepenuhnya',
                                 'dibayar terpisah.', 'Konsultasi via WhatsApp'):
                        self.assertIn(text, after.text)
                if key == 'catalog':
                    for css in ('catalog-price', 'catalog-desc'):
                        pattern = r'<div class="'+css+r'">(.*?)</div>'
                        self.assertEqual(re.findall(pattern, before.text, re.S), re.findall(pattern, after.text, re.S))
                    self.assertIn('Ketentuan Transport', after.text)

    def test_finance_account_dom_identical_home_hint_preserves_session_authority(self):
        with self.client.session_transaction() as state: state['active_product'] = 'finance'
        for path in ('/account', '/account?workspace=finance', '/account?workspace=invalid'):
            before = self.baseline('account.html', path)
            after = self.client.get(path)
            self.assertEqual((before.status_code, after.status_code), (200, 200))
            self.assertEqual(re.sub(r'\s+', ' ', before.text), re.sub(r'\s+', ' ', after.text))
            self.assertIn(INTRO, after.text)
        home = self.client.get('/account?workspace=home')
        self.assertEqual(home.status_code, 200)
        self.assertIn(INTRO, home.text)
        self.assertNotIn('id="premium-sidebar"', home.text)
        self.assertIn('class="account-back-finance"', home.text)
        with self.client.session_transaction() as state: self.assertEqual(state['active_product'], 'finance')

    def test_inactive_settings_loses_marketing_keeps_purchase_and_fair_use(self):
        other = tabs_fixture.fixture.app.app.test_client()
        with other.session_transaction() as state:
            state.update(user_id=self.base.base.other, role='CLIENT_OWNER', csrf_token='remaining-copy-csrf')
        response = other.get('/kilas-ai/usage')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('AI untuk membantu pekerjaan sehari-hari.', response.text)
        for text in ('Belum aktif', 'Rp99.000', 'Mulai berlangganan', 'Fair Use', 'csrf_token'):
            self.assertIn(text, response.text)


if __name__ == '__main__': unittest.main()
