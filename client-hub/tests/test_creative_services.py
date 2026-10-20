"""Same-origin Creative Services with real app guards, disposable accounts and no paid IO."""
import hashlib
import json
from pathlib import Path
import unittest
import test_kilas_home as fixture
import test_kilas_sidebar_products as sidebar

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / 'client-hub' / 'creative-services-site'
SOURCE = ROOT / 'creative-services-site'


class CreativeServicesTests(unittest.TestCase):
    setUp = fixture.HomeTests.setUp
    client = fixture.HomeTests.client

    def test_generated_bundle_has_exact_source_bytes(self):
        paths = sorted(str(p.relative_to(SOURCE)) for p in SOURCE.rglob('*') if p.is_file())
        manifest = json.loads((BUNDLE / '.source-manifest.json').read_text())
        self.assertEqual(paths, sorted(manifest))
        for name in paths:
            with self.subTest(name=name):
                self.assertEqual((SOURCE / name).read_bytes(), (BUNDLE / name).read_bytes())
                self.assertEqual(hashlib.sha256((SOURCE / name).read_bytes()).hexdigest(), manifest[name])

    def test_public_same_origin_index_assets_and_slash_canonicalization(self):
        client = self.client().application.test_client()
        response = client.get('/creative-services', base_url='https://app.kilasworks.id')
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response.location, 'https://app.kilasworks.id/creative-services/')
        response = client.get('/creative-services/', base_url='https://app.kilasworks.id')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, (SOURCE / 'index.html').read_bytes())
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertNotIn('<iframe', response.text)
        self.assertIn('inter-variable.woff2', response.text)
        self.assertIn('assets/portfolio/event-first-drive.jpg', response.text)
        self.assertNotIn('instrument-serif', response.text)
        for name in json.loads((BUNDLE / '.source-manifest.json').read_text()):
            if name == 'index.html':
                continue
            asset = client.get('/creative-services/' + name, base_url='https://app.kilasworks.id')
            self.assertEqual(asset.status_code, 200, name)
            self.assertEqual(asset.data, (SOURCE / name).read_bytes(), name)
        font = client.get('/creative-services/assets/fonts/inter-variable.woff2')
        self.assertEqual(font.mimetype, 'font/woff2')
        self.assertEqual(client.get('/creative-services/assets/editorial.css', headers={'If-None-Match':client.get('/creative-services/assets/editorial.css').headers['ETag']}).status_code, 304)

    def test_directory_traversal_unknown_files_and_writes_are_not_served(self):
        client = self.client()
        for path in ('/creative-services/assets/../../app.py', '/creative-services/assets/%2e%2e/%2e%2e/routes_client.py', '/creative-services/assets/not-a-file.css', '/creative-services/.source-manifest.json'):
            self.assertEqual(client.get(path).status_code, 404, path)
        self.assertEqual(client.post('/creative-services/', data={'csrf_token':'work-csrf'}).status_code,405)

    def test_valid_finance_session_can_read_marketing_without_mutating_ledger(self):
        own, other = sidebar.SidebarProductsTests.finance_fixture(self)
        before = sidebar.SidebarProductsTests.snapshot(self, own, other)
        client = self.client()
        with client.session_transaction() as state:
            state['active_product'] = 'finance'
        self.assertEqual(client.get('/creative-services/').status_code, 200)
        self.assertEqual(client.get('/creative-services/assets/editorial.css').status_code,200)
        self.assertEqual(sidebar.SidebarProductsTests.snapshot(self,own,other),before)
        with client.session_transaction() as state:
            self.assertEqual(state['active_product'],'finance')
            self.assertEqual(state['user_id'],self.owner)

    def test_existing_invalid_session_and_separate_host_guards_are_unchanged(self):
        client = self.client().application.test_client()
        with client.session_transaction() as state:
            state['user_id'] = self.owner
            state['role'] = 'CLIENT_OWNER'
        response = client.get('/creative-services/')
        self.assertEqual(response.status_code,303)
        self.assertIn('/login',response.location)
        anonymous = self.client().application.test_client()
        self.assertEqual(anonymous.get('/creative-services/',base_url='https://trading.kilasworks.id').status_code,404)
        self.assertEqual(anonymous.get('/creative-services/',base_url='https://evil.test').status_code,400)


if __name__ == '__main__':
    unittest.main()
