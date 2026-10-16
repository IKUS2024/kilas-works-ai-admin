"""Real Flask navigation and owned Finance handoff; no paid IO or browser."""
import json
import os
from pathlib import Path
import unittest
import test_kilas_home as fixture
import db
import repo
import finance_service as finance


class SidebarProductsTests(unittest.TestCase):
    setUp=fixture.HomeTests.setUp
    client=fixture.HomeTests.client

    def test_products_below_library_and_finance_absent_from_peer_tools_in_all_locales(self):
        pages={};client=self.client()
        for locale,label in (('en','Products'),('id','Produk'),('es','Productos'),('zh','产品')):
            client.set_cookie('kilas_language',locale)
            for name,path in (('home','/products/start'),('agent','/kilas-ai/agent?conversation='+str(self.conversation)),('library','/kilas-ai/library')):
                response=client.get(path);self.assertEqual(response.status_code,200,path)
                html=response.text;self.assertIn('<html lang="'+locale+'">',html)
                self.assertLess(html.index('chat-library-entry'),html.index('class="chat-products"'))
                self.assertLess(html.index('class="chat-products"'),html.index('data-chat-history-toggle'))
                self.assertIn('<summary><span>'+label+'</span>',html)
                self.assertEqual(html.count('name="product" value="finance"'),1)
                self.assertNotIn('class="kilas-finance-entry"',html)
                pages[name+'_'+locale]=html
            audio=client.get('/kilas-translator?mode=voiceover')
            self.assertEqual(audio.status_code,200);self.assertNotIn('class="kilas-finance-entry"',audio.text)
            self.assertIn('data-kilas-feature="chat"',audio.text)
        target=os.environ.get('KILAS_SIDEBAR_PRODUCTS_FIXTURE_PATH')
        if target:Path(target).write_text(json.dumps(pages),encoding='utf-8')

    def finance_fixture(self):
        own=repo.create_business(self.owner,'Owned synthetic Finance',package='NONE')
        other=repo.create_business(self.other,'Foreign synthetic Finance',package='NONE')
        finance.ensure_finance_defaults(own);finance.ensure_finance_defaults(other)
        return own,other

    def snapshot(self,own,other):
        return {table:[dict(row) for row in db.query_all('SELECT * FROM '+table+' WHERE '+column+' IN (?,?) ORDER BY id',(own,other))]
                for table,column in (('businesses','id'),('finance_accounts','business_id'),('finance_transactions','business_id'))}

    def test_finance_post_keeps_csrf_ownership_and_existing_rows(self):
        own,other=self.finance_fixture();client=self.client();before=self.snapshot(own,other)
        self.assertEqual(client.post('/products/start',data={'product':'finance'}).status_code,400)
        response=client.post('/products/start',data={'product':'finance','business_id':other,'csrf_token':'work-csrf'})
        self.assertEqual(response.status_code,303)
        self.assertIn('/business/'+str(own)+'/',response.location)
        self.assertNotIn('/business/'+str(other)+'/',response.location)
        with client.session_transaction() as state:
            self.assertEqual(state['workspace_finance_business'],own)
            self.assertEqual(state['active_product'],'finance')
            self.assertEqual(state['user_id'],self.owner)
        self.assertIn(client.get('/business/'+str(other)+'/finance').status_code,(403,404))
        self.assertEqual(before,self.snapshot(own,other))

    def test_sidebar_get_does_not_create_or_change_finance_data_and_anonymous_stays_gated(self):
        own,other=self.finance_fixture();client=self.client();before=self.snapshot(own,other)
        for path in ('/products/start','/kilas-ai/library','/kilas-ai/agent?conversation='+str(self.conversation)):
            self.assertEqual(client.get(path).status_code,200)
        self.assertEqual(before,self.snapshot(own,other))
        with client.session_transaction() as state:state.clear()
        response=client.get('/products/start');self.assertIn(response.status_code,(302,303))
        self.assertNotIn('Owned synthetic Finance',response.text)


if __name__=='__main__':unittest.main()
