"""Read-only creative-service draft pages; no checkout or external transport."""
import unittest
import test_kilas_home as fixture
from ui_i18n import LANGUAGES


class CreativeServicesTests(unittest.TestCase):
    setUp = fixture.HomeTests.setUp
    client = fixture.HomeTests.client

    def test_category_navigation_and_confirmed_event_scope_in_all_languages(self):
        labels = {
            'id': ('Foto &amp; Video Acara', 'Paket Konten Media Sosial', 'Maksimal 5 jam', 'Maksimal 8 jam'),
            'en': ('Event Photography &amp; Videography', 'Social Media Content Packages', 'Up to 5 hours', 'Up to 8 hours'),
            'es': ('Fotografía y vídeo de eventos', 'Paquetes de contenido para redes sociales', 'Hasta 5 horas', 'Hasta 8 horas'),
            'zh': ('活动摄影与摄像', '社交媒体内容套餐', '最长5小时', '最长8小时'),
        }
        self.assertEqual(set(labels), set(LANGUAGES))
        client = self.client()
        for locale, (event, social, five, eight) in labels.items():
            client.set_cookie('kilas_language', locale)
            page = client.get('/kilas-ai/creative-services')
            self.assertEqual(page.status_code, 200)
            self.assertIn(event, page.text)
            self.assertIn(social, page.text)
            self.assertIn('href="/kilas-ai/creative-services?category=event"', page.text)
            self.assertIn('href="/kilas-ai/creative-services?category=social"', page.text)
            page = client.get('/kilas-ai/creative-services?category=event')
            self.assertEqual(page.status_code, 200)
            content = page.text.split('class="premium-home kilas-creative-services"', 1)[1]
            self.assertLess(content.index('<h3>Basic</h3>'), content.index('<h3>Standard</h3>'))
            self.assertLess(content.index('<h3>Standard</h3>'), content.index('<h3>Premium</h3>'))
            for value in ('Rp1.500.000', 'Rp3.000.000', five, eight):
                self.assertIn(value, content)
            self.assertEqual(content.count('<li>'), 9)
            for old_value in ('Rp1.200.000', 'Rp2.800.000', 'Rp4.400.000', 'Lengkap', 'add-on'):
                self.assertNotIn(old_value, content)
            self.assertNotIn('<form', content)
            page = client.get('/kilas-ai/creative-services?category=social')
            self.assertEqual(page.status_code, 200)
            content = page.text.split('class="premium-home kilas-creative-services"', 1)[1]
            self.assertIn(social, content)
            self.assertNotIn('creative-package-grid', content)
            self.assertNotIn('Rp', content)
        self.assertEqual(client.get('/kilas-ai/creative-services?category=unknown').status_code, 404)

    def test_private_page_uses_existing_authentication_gate(self):
        client = self.client().application.test_client()
        response = client.get('/kilas-ai/creative-services')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.location)


if __name__ == '__main__':
    unittest.main()
