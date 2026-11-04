"""Synthetic, non-financial checkout integration. No external IO, no paid proof."""
import io
import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import test_customer_auth_sessions as auth_fixture
import creative_orders as orders
import security
import payment_service
import projects_repo


class CreativeCheckoutTests(auth_fixture.CustomerAuthTests):
    # Only inherit fixture helpers, not the unrelated authentication suite.
    def setUp(self):
        super().setUp()
        self.client, _ = self.login()
        self.base_url = '/creative-services/checkout/'

    def form(self, key='creative_event_basic', client=None):
        client = client or self.client
        page = client.get(self.base_url + key, follow_redirects=True)
        self.assertEqual(page.status_code, 200)
        return {'order_token': re.search('name="order_token" value="([^"]+)"', page.text)[1],
                'csrf_token': self.csrf(client, self.base_url + key), 'name':'Synthetic QA',
                'whatsapp':'081234567890', 'event_date':'2099-12-01', 'location':'Synthetic venue',
                'brand':'Synthetic brand', 'social_account':'@synthetic', 'notes':'Synthetic non-financial test'}

    def create(self, key='creative_event_basic', addon='none'):
        data=self.form(key);data['addon']=addon
        result=self.client.post(self.base_url+key,data=data)
        self.assertEqual(result.status_code,303,result.text)
        return int(result.location.rsplit('/',1)[1]), data

    def photo(self):
        out=io.BytesIO();Image.new('RGB',(32,24),'white').save(out,format='PNG');return out.getvalue()

    def upload(self, invoice, data=None, filename='synthetic.png', mime='image/png', client=None):
        client=client or self.client
        return client.post(f'/creative-services/payment/{invoice}',data={'csrf_token':self.csrf(client,f'/creative-services/payment/{invoice}'),
            'proof':(io.BytesIO(self.photo() if data is None else data),filename,mime)})

    def test_all_prices_options_and_frozen_snapshot(self):
        facts=json.loads(Path(__file__).with_name('creative_services_offer_facts.json').read_text())
        self.assertEqual([orders.money(v['amount']) for v in orders.CATALOG['packages'].values()],[x['price'] for x in facts['cards']])
        for key, spec in orders.CATALOG['packages'].items():
            for addon in (orders.CATALOG['addons'] if spec['service']=='social' else ['none']):
                invoice,_=self.create(key,addon)
                stored=payment_service.get_invoice(invoice)
                self.assertEqual(stored['amount'],orders.offer(key,addon)['total'])
                snap=projects_repo.get_project(stored['project_id'])['requirements']
                self.assertEqual(snap['bank']['account_number'],'010180016000684')
                self.assertEqual(snap['features'],spec['features'])
                self.assertIn(orders.money(stored['amount']),self.client.get(f'/creative-services/payment/{invoice}').text)
                self.assertNotEqual(stored['status'],'PAID')
        invoice,_=self.create()
        with patch.dict(orders.CATALOG['packages']['creative_event_basic'],amount=99):
            self.assertIn('Rp1.500.000',self.client.get(f'/creative-services/payment/{invoice}').text)

    def test_tamper_validation_csrf_and_ownership(self):
        for field in ('name','whatsapp','event_date','location'):
            data=self.form();data[field]='';self.assertEqual(self.client.post(self.base_url+'creative_event_basic',data=data).status_code,422)
        for field in ('brand','social_account'):
            data=self.form('creative_social_basic');data[field]='';self.assertEqual(self.client.post(self.base_url+'creative_social_basic',data=data).status_code,422)
        for value in ('yesterday','2020-01-01'):
            data=self.form();data['event_date']=value;self.assertEqual(self.client.post(self.base_url+'creative_event_basic',data=data).status_code,422)
        for change in ({'addon':'mega'},{'addon':'unknown'},{'order_token':'forged'},{'whatsapp':'invalid'}):
            data=self.form();data.update(change);self.assertEqual(self.client.post(self.base_url+'creative_event_basic',data=data).status_code,422)
        data=self.form();data.pop('csrf_token');self.assertEqual(self.client.post(self.base_url+'creative_event_basic',data=data).status_code,400)
        data=self.form();data.update(amount='1',price='1',plan='premium',status='PAID')
        result=self.client.post(self.base_url+'creative_event_basic',data=data);invoice=int(result.location.rsplit('/',1)[1])
        self.assertEqual(payment_service.get_invoice(invoice)['amount'],1500000)
        other=self.base.client(self.other)
        self.assertEqual(other.get(result.location).status_code,404)
        self.assertEqual(other.get(result.location+'/proof').status_code,404)
        self.assertIn(self.app.test_client().get(result.location).status_code,(302,303))
        self.assertEqual(self.client.get(self.base_url+'invalid').status_code,404)

    def test_repeated_submit_and_persistence(self):
        invoice,data=self.create();before=self.db.query_one('SELECT COUNT(*) n FROM invoices')['n']
        for _ in range(3):
            result=self.client.post(self.base_url+'creative_event_basic',data=data)
            self.assertEqual(result.location,f'/creative-services/payment/{invoice}')
        self.assertEqual(self.db.query_one('SELECT COUNT(*) n FROM invoices')['n'],before)
        self.db._local.conn.close();self.db._local.conn=None
        self.assertEqual(self.client.get(f'/creative-services/payment/{invoice}').status_code,200)
        self.assertIn('Foto &amp; Video Acara',self.client.get('/creative-services/orders').text)

    def test_proof_private_pending_admin_review_and_gate(self):
        invoice,_=self.create();self.assertEqual(self.upload(invoice).status_code,303)
        p=payment_service.get_payment_for_invoice(invoice)
        self.assertEqual(p['status'],'UNDER_REVIEW')
        self.assertEqual(payment_service.get_invoice(invoice)['status'],'ISSUED')
        self.assertEqual(projects_repo.get_project(payment_service.get_invoice(invoice)['project_id'])['status'],'PAYMENT_PENDING')
        before=self.db.query_one('SELECT COUNT(*) n FROM project_files')['n']
        self.upload(invoice);self.assertEqual(self.db.query_one('SELECT COUNT(*) n FROM project_files')['n'],before)
        proof=self.client.get(f'/creative-services/payment/{invoice}/proof')
        self.assertEqual(proof.mimetype,'image/jpeg');self.assertEqual(proof.headers['Cache-Control'],'private, no-store')
        Image.open(io.BytesIO(proof.data)).verify()
        admin_id=self.repo.create_user('creative-admin@example.test',security.hash_password('synthetic-password'),role='KILAS_ADMIN')
        admin=self.base.client(admin_id)
        queue=admin.get('/admin/payments');self.assertEqual(queue.status_code,200);self.assertIn('Foto &amp; Video Acara',queue.text)
        detail=admin.get(f'/admin/payments/{p["id"]}');self.assertIn('010180016000684',detail.text);self.assertIn('Synthetic venue',detail.text)
        self.assertEqual(admin.get(f'/admin/payments/{p["id"]}/proof').status_code,200)
        self.assertEqual(self.client.post(f'/admin/payments/{p["id"]}/verify',data={'csrf_token':self.csrf(self.client)}).status_code,403)
        self.assertEqual(payment_service.get_payment(p['id'])['status'],'UNDER_REVIEW')
        # Exercise human rejection/reupload only, never mark a synthetic proof as paid.
        result=admin.post(f'/admin/payments/{p["id"]}/reject',data={'csrf_token':self.csrf(admin,f'/admin/payments/{p["id"]}'),'admin_notes':'Synthetic rejection test'})
        self.assertEqual(result.status_code,302)
        self.assertEqual(payment_service.get_payment(p['id'])['status'],'REJECTED')
        self.assertEqual(self.upload(invoice).status_code,303)

    def test_rejected_uploads_leave_no_files_or_success(self):
        invoice,_=self.create();before=self.db.query_one('SELECT COUNT(*) n FROM project_files')['n']
        for data,name,mime in [(b'<svg/>','a.svg','image/svg+xml'),(b'MZbinary','a.png','image/png'),(self.photo(),'../a.png','image/png'),(self.photo(),'a.jpg','image/jpeg'),(self.photo(),'a.png','image/jpeg'),(self.photo()+b'<script>alert(1)</script>','a.png','image/png'),(b'x'*(orders.MAX_PROOF_BYTES+1),'a.png','image/png')]:
            response=self.upload(invoice,data,name,mime);self.assertEqual(response.status_code,422,(name,response.status_code))
        self.assertEqual(self.db.query_one('SELECT COUNT(*) n FROM project_files')['n'],before)
        self.assertEqual(payment_service.get_payment_for_invoice(invoice)['status'],'PAYMENT_PENDING')

    def test_concurrent_retries_create_one_invoice_and_proof(self):
        from concurrent.futures import ThreadPoolExecutor
        from werkzeug.datastructures import FileStorage
        data=self.form()
        def create():
            try:
                with self.app.app_context():return orders.create_order(self.owner,'creative_event_basic',data)
            finally:
                conn=getattr(self.db._local,'conn',None)
                if conn:conn.close();self.db._local.conn=None
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids=list(pool.map(lambda _:create(),range(2)))
        self.assertEqual(ids[0],ids[1])
        before=self.db.query_one('SELECT COUNT(*) n FROM project_files')['n']
        def upload():
            try:
                with self.app.app_context():
                    orders.submit_proof(ids[0],self.owner,FileStorage(stream=io.BytesIO(self.photo()),filename='synthetic.png',content_type='image/png'))
            finally:
                conn=getattr(self.db._local,'conn',None)
                if conn:conn.close();self.db._local.conn=None
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:upload(),range(2)))
        self.assertEqual(self.db.query_one('SELECT COUNT(*) n FROM project_files')['n'],before+1)

    def test_atomic_rollback(self):
        before=self.db.query_one('SELECT COUNT(*) n FROM projects')['n'];data=self.form()
        with patch.object(payment_service,'checkout',side_effect=RuntimeError('synthetic storage failure')):
            with self.assertRaises(RuntimeError):self.client.post(self.base_url+'creative_event_basic',data=data)
        self.assertEqual(self.db.query_one('SELECT COUNT(*) n FROM projects')['n'],before)
        invoice,_=self.create();before=self.db.query_one('SELECT COUNT(*) n FROM project_files')['n']
        with patch.object(payment_service,'upload_payment_proof',side_effect=RuntimeError('synthetic storage failure')):
            with self.assertRaises(RuntimeError):self.upload(invoice)
        self.assertEqual(self.db.query_one('SELECT COUNT(*) n FROM project_files')['n'],before)

    def test_old_invoice_paths_do_not_show_wrong_bank_or_accept_proof(self):
        invoice,_=self.create();pid=payment_service.get_invoice(invoice)['project_id']
        for path in (f'/invoices/{invoice}',f'/projects/{pid}/checkout'):
            self.assertEqual(self.client.get(path).location,f'/creative-services/payment/{invoice}')
            self.assertEqual(self.client.post(path,data={'csrf_token':self.csrf(self.client)}).status_code,409)
        self.assertEqual(payment_service.BANK_DETAILS['bank_name'],'BCA')
        html=self.client.get(f'/creative-services/payment/{invoice}').text
        self.assertNotIn('Pembayaran diperiksa secara manual',html);self.assertIn('010180016000684',html)

    def test_changed_catalog_requires_review_and_addon_survives_login(self):
        data=self.form()
        with patch.dict(orders.CATALOG['packages']['creative_event_basic'],amount=1600000):
            response=self.client.post(self.base_url+'creative_event_basic',data=data)
            self.assertEqual(response.status_code,422);self.assertIn('harga paket berubah',response.text)
        guest=self.app.test_client()
        guest.get('/creative-services/checkout/creative_social_premium/login?addon=mega')
        token=self.csrf(guest)
        guest.post('/login',data={'email':self.email,'password':self.password,'csrf_token':token})
        response=guest.get('/products/start',follow_redirects=True)
        self.assertEqual(response.status_code,200);self.assertIn('value="mega" data-amount="7500000" selected',response.text)
        self.assertIn('Rp17.000.000',response.text)

    def test_approved_login_heading_in_english_and_indonesian(self):
        guest=self.app.test_client()
        for language,expected in [('en','Create, work, and grow with Kilas.'),('id','Berkarya, bekerja, dan berkembang bersama Kilas.')]:
            guest.set_cookie('kilas_language',language)
            html=guest.get('/login').text
            self.assertIn(expected,html)
            self.assertNotIn('One platform for all your business products.',html)
        guest.set_cookie('kilas_language','en')
        self.assertIn('One platform for all your business products.',guest.get('/register').text)

    def test_anonymous_selection_survives_real_login_rotation(self):
        client=self.app.test_client();path=self.base_url+'creative_social_premium'
        self.assertEqual(client.get(path,follow_redirects=True).status_code,200)
        token=self.csrf(client)
        client.post('/login',data={'email':self.email,'password':self.password,'csrf_token':token})
        self.assertEqual(client.get('/products/start').location,path+'?addon=none')
        self.assertEqual(client.get(path,follow_redirects=True).status_code,200)


# Avoid inheriting all test methods of the fixture class.
for _name in list(auth_fixture.CustomerAuthTests.__dict__):
    if _name.startswith('test_') and _name not in CreativeCheckoutTests.__dict__:
        setattr(CreativeCheckoutTests,_name,None)

if __name__ == '__main__':unittest.main()
