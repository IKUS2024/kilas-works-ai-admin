"""Read-only catalog and bounded return navigation using disposable accounts."""
import unittest
from urllib.parse import quote
import test_kilas_home as fixture


class CatalogTests(unittest.TestCase):
    setUp=fixture.HomeTests.setUp
    client=fixture.HomeTests.client

    def test_catalog_has_three_products_and_existing_finance_post(self):
        client=self.client()
        for language in ('en','id','es','zh'):
            client.set_cookie('kilas_language',language)
            response=client.get('/products/catalog')
            self.assertEqual(response.status_code,200)
            html=response.text
            self.assertEqual(html.count('class="catalog-card"'),3)
            self.assertIn('action="/products/start"',html)
            self.assertIn('name="csrf_token"',html)
            self.assertIn('name="product" value="finance"',html)
            self.assertIn('href="https://shotcut.org/download/" target="_blank" rel="noopener noreferrer"',html)
            self.assertIn('Windows · macOS · Linux',html)
            self.assertIn('href="/creative-services/"',html)
            self.assertEqual(client.get('/creative-services/').status_code,200)
            for token in ('premium-sidebar','data-premium-menu','kilas_chat_sidebar.js'):
                self.assertNotIn(token,html)
            self.assertIn('private, no-store',response.headers['Cache-Control'])

    def test_return_paths_are_local_chat_routes_only(self):
        client=self.client()
        for value in ('https://evil.example','//evil.example','/products/catalog','/logout','/kilas-ai/agent?conversation=bad','/\\evil.example','/kilas-ai/threads/12/../../logout'):
            html=client.get('/products/catalog?return_to='+quote(value,safe='')).text
            self.assertIn('class="catalog-back" href="/products/start"',html,value)
        target='/kilas-ai/agent?conversation='+str(self.conversation)
        self.assertIn('class="catalog-back" href="'+target+'"',client.get('/products/catalog?return_to='+quote(target,safe='')).text)

    def test_login_interruption_and_stale_session_are_safe(self):
        client=self.client()
        with client.session_transaction() as state:state.clear()
        response=client.get('/products/catalog?return_to=https://evil.example')
        self.assertIn(response.status_code,(302,303));self.assertIn('/login',response.location)
        with client.session_transaction() as state:state['user_id']=999999999
        response=client.get('/products/catalog')
        self.assertIn(response.status_code,(302,303));self.assertIn('/login',response.location)


if __name__=='__main__':unittest.main()
