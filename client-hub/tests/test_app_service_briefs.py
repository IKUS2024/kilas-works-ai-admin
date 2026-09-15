"""Authenticated purchases share WhatsApp briefs, with review and serialized checkout."""
import io
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from threading import Barrier
from unittest.mock import patch
import test_knowledge_setup_v2 as fixture
import wa_checkout as shared
import catalog_service as catalog
import projects_repo as projects
import payment_service as payment
import quotation_service as quotes

repo, db, hub = fixture.repo, fixture.db, fixture.hub

class AppBriefTests(unittest.TestCase):
    def setUp(self):
        self.base = fixture.KnowledgeTests(); self.base.setUp()
        self.client = self.base.client
        self.uid = self.base.uid
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('no API calls'))
        self.network.start(); self.addCleanup(self.network.stop)

    def select(self, key, client=None, business=None):
        item = catalog.get_catalog_item(key)
        suffix = 'request-quote' if item['pricing_mode']=='CUSTOM_QUOTE' else 'checkout-fixed'
        response = (client or self.client).post(f'/services/{key}/{suffix}', data={'business_id':business or ''})
        self.assertEqual(response.status_code,302)
        return response.location

    def project(self, url):
        return projects.get_project(int(url.split('/')[2]))

    def values(self,key):
        return {field: (shared.FIELDS[field][1][0] if shared.FIELDS[field][1] else 'Test '+field) for field in shared.fields(catalog.get_catalog_item(key))[0]}

    def brief(self,url,key):
        response=self.client.post(url,data={'action':'brief',**self.values(key)})
        self.assertEqual(response.status_code,302)
        return self.project(url)

    def confirm(self,url,client=None):
        project=self.project(url)
        return (client or self.client).post(url,data={'action':'confirm','review_version':project['requirements']['_review_version']})

    def test_every_active_fixed_catalog_row_requires_brief_review_payment(self):
        items=[x for x in catalog.list_active_catalog() if x['category'] not in ('AI_ADMIN','BUNDLE') and x['pricing_mode']!='CUSTOM_QUOTE']
        keys={x['catalog_key'] for x in items}
        self.assertTrue({'content_basic','content_growth','content_pro','website_landing_page','website_company_profile','website_extra_page','website_maintenance','website_domain_com_hosting','website_domain_id_hosting','event_standard','event_lengkap','event_premium','ads_setup_only','ads_management'} <= keys)
        for item in items:
            with self.subTest(key=item['catalog_key']):
                url=self.select(item['catalog_key']); p=self.project(url)
                self.assertEqual(p['status'],'REQUESTED')
                self.assertEqual(self.select(item['catalog_key']),url)
                self.assertEqual(self.client.get(url).status_code,200)
                self.client.post(f"/projects/{p['id']}/checkout")
                self.assertIsNone(payment.get_latest_invoice_for_project(p['id']))
                self.assertEqual(self.client.post(url,data={'action':'confirm'}).status_code,400)
                self.assertEqual(self.client.post(url,data={'action':'brief','name':'Only name'}).status_code,400)
                self.assertIsNone(payment.get_latest_invoice_for_project(p['id']))
                p=self.brief(url,item['catalog_key'])
                self.assertEqual(p['status'],'REQUESTED')
                self.assertEqual({k:v for k,v in p['requirements'].items() if k in shared.FIELDS},self.values(item['catalog_key']))
                page=self.client.get(url).get_data(as_text=True)
                self.assertIn('Ringkasan brief',page);self.assertIn('Lanjut ke Pembayaran',page)
                self.assertIsNone(payment.get_latest_invoice_for_project(p['id']))
                self.assertEqual(self.confirm(url).status_code,302)
                invoice=payment.get_latest_invoice_for_project(p['id'])
                self.assertEqual(invoice['amount'],item['price_amount'])
                self.confirm(url);self.client.post(f"/projects/{p['id']}/checkout")
                self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM invoices WHERE project_id=?',(p['id'],))['n'],1)
                self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM payments WHERE invoice_id=?',(invoice['id'],))['n'],1)

    def test_every_custom_catalog_row_stays_quotation_until_approved(self):
        items=[x for x in catalog.list_active_catalog() if x['pricing_mode']=='CUSTOM_QUOTE' and x['category'] not in ('AI_ADMIN','BUNDLE')]
        self.assertTrue({'custom_photo','custom_video','custom_website_app','talent_management'} <= {i['catalog_key'] for i in items})
        for item in items:
            with self.subTest(key=item['catalog_key']):
                url=self.select(item['catalog_key']);self.brief(url,item['catalog_key'])
                p=self.project(url);self.assertEqual(p['status'],'REQUESTED')
                self.assertIn('Kirim Brief &amp; Minta Penawaran',self.client.get(url).get_data(as_text=True))
                self.confirm(url);p=self.project(url)
                self.assertEqual(p['status'],'WAITING_FOR_QUOTE');self.assertIsNone(p['final_price'])
                self.assertEqual(self.select(item['catalog_key']),url)
                self.client.post(f"/projects/{p['id']}/checkout")
                self.assertIsNone(payment.get_latest_invoice_for_project(p['id']))
                qid=shared.admin_quote(p['id'],None,scope='Agreed scope',deliverables='Agreed output',quantity=1,final_price=1234567,notes='',created_by_user_id=self.uid)
                page=self.client.get(url).get_data(as_text=True);self.assertIn('Agreed scope',page)
                self.assertEqual(self.client.post(url,data={'action':'approve','quotation_id':qid}).status_code,302)
                self.assertEqual(payment.get_latest_invoice_for_project(p['id'])['amount'],1234567)

    def test_shared_specialized_addons(self):
        self.assertEqual(shared.fields(catalog.get_catalog_item('website_extra_page'))[0],('website_project','page','page_content'))
        self.assertEqual(shared.fields(catalog.get_catalog_item('website_maintenance'))[0],('website_project','changes'))
        self.assertEqual(shared.fields(catalog.get_catalog_item('website_domain_com_hosting'))[0],('domain','extension','alternatives'))
        self.assertEqual(shared.fields(catalog.get_catalog_item('ads_setup_only')),shared.fields(catalog.get_catalog_item('ads_management')))

    def test_invalid_choice_and_server_limits(self):
        url=self.select('content_basic');data=self.values('content_basic')
        data['platform']='not a platform'
        self.assertEqual(self.client.post(url,data={'action':'brief',**data}).status_code,400)
        data['platform']='Instagram';data['notes']='x'*1501
        self.assertEqual(self.client.post(url,data={'action':'brief',**data}).status_code,400)
        self.assertIsNone(payment.get_latest_invoice_for_project(self.project(url)['id']))

    def test_review_edit_and_old_review_rejected(self):
        url=self.select('content_basic');p=self.brief(url,'content_basic');old=p['requirements']['_review_version']
        self.assertIn('Review Order',self.client.get(url+'?edit=1').get_data(as_text=True))
        data=self.values('content_basic');data['name']='New brand'
        self.client.post(url,data={'action':'brief',**data})
        self.assertEqual(self.client.post(url,data={'action':'confirm','review_version':old}).status_code,400)
        self.assertEqual(self.confirm(url).status_code,302)

    def test_cannot_bypass_review_by_changing_status_or_posting_prices(self):
        url=self.select('content_basic');p=self.project(url)
        db.execute("UPDATE projects SET status='APPROVED' WHERE id=?",(p['id'],))
        with self.assertRaisesRegex(ValueError,'brief_review_required'):payment.checkout(p['id'],None,self.uid)
        self.assertIsNone(payment.get_latest_invoice_for_project(p['id']))

    def test_historical_locked_order_unchanged(self):
        item=catalog.get_catalog_item('content_basic')
        pid=projects.create_fixed_price_project(None,item,self.uid)
        db.execute('UPDATE projects SET final_price=123 WHERE id=?',(pid,))
        before=projects.get_project(pid)
        self.assertEqual(self.select('content_basic'),f'/projects/{pid}')
        self.assertEqual(projects.get_project(pid),before)
        iid=payment.checkout(pid,None,self.uid)
        self.assertEqual(payment.get_invoice(iid)['amount'],123)

    def test_user_and_business_authorization(self):
        url=self.select('content_basic');other=hub.app.test_client()
        uid=repo.create_user('other@test.com',fixture.security.hash_password('password123'))
        with other.session_transaction() as s:s['user_id']=uid
        self.assertEqual(other.get(url).status_code,404)
        self.assertEqual(other.post(url,data={'action':'brief',**self.values('content_basic')}).status_code,404)
        self.assertEqual(other.post('/services/content_basic/checkout-fixed',data={'business_id':self.base.bid}).status_code,404)
        guest=hub.app.test_client();self.assertEqual(guest.get(url).status_code,302)

    def test_csrf_required(self):
        url=self.select('content_basic')
        with patch.dict(hub.app.config,{'CLIENT_HUB_FORCE_CSRF_IN_TESTS':True}):
            self.assertEqual(self.client.post(url,data={'action':'brief',**self.values('content_basic')}).status_code,400)
            self.assertEqual(self.client.post('/services/content_basic/checkout-fixed').status_code,400)

    def test_catalog_and_brain(self):
        page=self.client.get('/services').get_data(as_text=True)
        for item in catalog.list_active_catalog():
            if item['category']=='AI_ADMIN':continue
            suffix='request-quote' if item['pricing_mode']=='CUSTOM_QUOTE' else 'checkout-fixed'
            self.assertIn(f"/services/{item['catalog_key']}/{suffix}",page)
        before=db.query_one('SELECT COUNT(*) AS n FROM projects')['n']
        response=self.client.post('/services/ai_admin_basic/checkout-fixed')
        self.assertEqual(response.status_code,302);self.assertNotIn('/brief',response.location)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM projects')['n'],before)

    def test_admin_readable_and_reference_upload(self):
        url=self.select('content_basic')
        from PIL import Image
        content=io.BytesIO();Image.new('RGB',(2,2)).save(content,format='PNG');content.seek(0)
        data={'action':'brief',**self.values('content_basic'),'reference_file':(content,'logo.png')}
        self.assertEqual(self.client.post(url,data=data,content_type='multipart/form-data').status_code,302)
        p=self.project(url)
        db.execute("UPDATE users SET role='KILAS_ADMIN' WHERE id=?",(self.uid,))
        page=self.client.get(f"/admin/projects/{p['id']}")
        self.assertEqual(page.status_code,200);text=page.get_data(as_text=True)
        self.assertIn('Nama brand / project',text);self.assertNotIn('_review_version',text)
        f=db.query_one('SELECT id FROM project_files WHERE project_id=?',(p['id'],))
        self.assertEqual(self.client.get(f"/admin/projects/{p['id']}/reference/{f['id']}").status_code,200)

    def test_policy_copy_and_no_surcharge(self):
        for key,expected in [('ads_management','termasuk setup awal'),('talent_management','terpisah dari fee talent'),('event_standard','Transport mengikuti lokasi'),('website_domain_id_hosting','Ketersediaan domain')]:
            url=self.select(key);self.assertIn(expected,self.client.get(url).get_data(as_text=True))
        self.assertEqual(catalog.get_catalog_item('ads_management')['price_amount'],799000)

    def test_legacy_forms_no_longer_create_unreviewed_requests(self):
        before=db.query_one('SELECT COUNT(*) AS n FROM projects')['n']
        for kind in ('PHOTO','VIDEO','WEBSITE','APPLICATION','CONTENT'):
            self.assertEqual(self.client.post('/projects/custom/'+kind,data={'notes':'old'}).status_code,302)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM projects')['n'],before)

    def test_concurrent_selection_and_confirm_reuse(self):
        def client():
            c=hub.app.test_client()
            with c.session_transaction() as s:s['user_id']=self.uid
            return c
        barrier=Barrier(2)
        def select(_):
            barrier.wait(timeout=5)
            try:return self.select('content_basic',client=client())
            finally:db.reset_connection_for_new_db_path()
        with ThreadPoolExecutor(max_workers=2) as pool:urls=list(pool.map(select,range(2)))
        self.assertEqual(urls[0],urls[1]);url=urls[0];self.brief(url,'content_basic')
        version=self.project(url)['requirements']['_review_version']
        def confirm(_):
            barrier.wait(timeout=5)
            try:return client().post(url,data={'action':'confirm','review_version':version}).status_code
            finally:db.reset_connection_for_new_db_path()
        with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(confirm,range(2)))
        self.assertEqual(codes,[302,302]);pid=self.project(url)['id']
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM projects WHERE catalog_key=?',('content_basic',))['n'],1)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM invoices WHERE project_id=?',(pid,))['n'],1)

    def test_business_purchase_reuses_project_and_invoice_is_scoped(self):
        url=self.select('content_basic',business=self.base.bid)
        self.assertEqual(self.select('content_basic',business=self.base.bid),url)
        self.brief(url,'content_basic');self.confirm(url)
        p=self.project(url);self.assertEqual(p['business_id'],self.base.bid)
        invoice=payment.get_latest_invoice_for_project(p['id'])
        self.assertEqual(self.client.get(f"/business/{self.base.bid}/projects/{p['id']}").status_code,200)
        uid=repo.create_user('invoice-other@test.com',fixture.security.hash_password('password123'))
        other=hub.app.test_client()
        with other.session_transaction() as session:session['user_id']=uid
        self.assertEqual(other.get(f"/invoices/{invoice['id']}").status_code,404)
        self.assertEqual(other.post(f"/invoices/{invoice['id']}").status_code,404)
        self.assertEqual(self.client.get(f"/invoices/{invoice['id']}").status_code,200)

    def test_admin_cannot_quote_draft_and_repeat_quote_is_idempotent(self):
        url=self.select('custom_photo');pid=self.project(url)['id']
        db.execute("UPDATE users SET role='KILAS_ADMIN' WHERE id=?",(self.uid,))
        quote_url=f'/admin/projects/{pid}/quote'
        self.assertEqual(self.client.post(quote_url,data={'final_price':'10000'}).status_code,302)
        self.assertIsNone(quotes.get_latest_quotation_for_project(pid))
        self.brief(url,'custom_photo');self.confirm(url)
        self.client.post(quote_url,data={'final_price':'10000'})
        self.client.post(quote_url,data={'final_price':'99999'})
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM quotations WHERE project_id=?',(pid,))['n'],1)
        self.assertEqual(quotes.get_latest_quotation_for_project(pid)['final_price'],10000)
        self.assertEqual(self.client.post(url,data={'action':'approve','quotation_id':'99999'}).status_code,400)
        self.assertIsNone(payment.get_latest_invoice_for_project(pid))

    def test_failed_invoice_rolls_back_confirmation_and_retry_keeps_one_project(self):
        url=self.select('content_basic');self.brief(url,'content_basic');pid=self.project(url)['id']
        with patch.object(payment,'checkout',side_effect=ValueError('unavailable')):
            self.assertEqual(self.confirm(url).status_code,400)
        self.assertEqual(self.project(url)['status'],'REQUESTED')
        self.assertFalse(self.project(url)['requirements'].get('_brief_confirmed'))
        self.assertIsNone(payment.get_latest_invoice_for_project(pid))
        self.assertEqual(self.confirm(url).status_code,302)
        self.assertEqual(self.select('content_basic'),url)
        self.assertIsNotNone(payment.get_latest_invoice_for_project(pid))

    def test_mobile_and_shared_fields_only(self):
        url=self.select('content_growth');page=self.client.get(url).get_data(as_text=True)
        tags=[]
        parser=HTMLParser();parser.handle_starttag=lambda tag,attrs:tags.append(tag);parser.feed(page)
        self.assertNotIn('table',tags);self.assertIn('Detail tambahan (opsional)',page)
        for k in shared.fields(catalog.get_catalog_item('content_growth'))[0]:self.assertIn('name="'+k+'"',page)
        self.assertNotIn('name="price"',page)

if __name__=='__main__':unittest.main()
