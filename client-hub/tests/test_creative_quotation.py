"""Current quote-only catalog and historical payment preservation; isolated SQLite."""
import io
import json
import unittest
from copy import deepcopy
from unittest.mock import patch
from PIL import Image
import test_customer_auth_sessions as auth_fixture
import creative_orders as orders
import payment_service
import projects_repo


class CreativeQuotationTests(auth_fixture.CustomerAuthTests):
    def setUp(self):
        super().setUp()
        self.client, _ = self.login()
        self.client.set_cookie('kilas_language', 'id')
        self.path = '/creative-services/checkout/creative_event_basic'

    def counts(self):
        return {table:self.db.query_one(f'SELECT COUNT(*) n FROM {table}')['n']
                for table in ('projects','invoices','payments','project_files')}

    def test_current_prices_and_all_packages_require_quote(self):
        expected = {'creative_event_basic':2000000,'creative_event_standard':4500000,
                    'creative_event_premium':7500000,'creative_social_basic':3500000,
                    'creative_social_standard':6000000,'creative_social_premium':9000000}
        for key, amount in expected.items():
            self.assertEqual(orders.offer(key)['amount'], amount)
        self.assertEqual(orders.offer('creative_editing_1m')['amount'],250000)
        self.assertEqual(orders.offer('creative_editing_1m')['name'],'Basic Social Media Editing')
        self.assertEqual([k for k in orders.CATALOG['packages'] if k.startswith('creative_editing_')],['creative_editing_1m','creative_editing_advanced','creative_editing_premium','creative_editing_professional'])
        self.assertEqual(len(orders.CATALOG['packages']),14)
        self.assertEqual(self.client.get('/creative-services/checkout/creative_editing_5_10m').status_code,404)
        for key in orders.CATALOG['packages']:
            self.assertTrue(orders.offer(key)['quotation_required'])
            self.assertIsNone(orders.offer(key)['total'])
        self.assertNotIn('mega',orders.CATALOG['addons'])
        self.assertNotIn('color',orders.CATALOG['addons'])
        self.assertEqual(orders.CATALOG['addons']['bilingual']['price_type'],'starting_from')
        self.assertEqual(orders.CATALOG['addons']['urgent']['percentage'],30)
        with self.assertRaises(ValueError): orders.offer('creative_social_basic','motion')

    def test_editing_ranges_scope_and_starting_price_are_explicit(self):
        for key, low, high in [('creative_editing_advanced',350000,500000),
                               ('creative_editing_premium',600000,900000)]:
            spec=orders.offer(key)
            self.assertEqual((spec['amount'],spec['amount_max'],spec['price_type']),(low,high,'range'))
            page=self.client.get('/creative-services/checkout/'+key)
            self.assertIn(orders.money(low)+'–'+orders.money(high),page.text)
            self.assertIn('Durasi maksimal 1 menit',page.text)
        professional=orders.offer('creative_editing_professional')
        self.assertEqual((professional['amount'],professional['unit'],professional['price_type']),
                         (1500000,'proyek','starting_from'))
        page=self.client.get('/creative-services/checkout/creative_editing_professional')
        self.assertIn('Mulai dari Rp1.500.000',page.text)
        self.assertIn('Beberapa output / cutdown hanya jika disepakati',page.text)
        self.assertIn('Scope dan durasi sesuai brief',page.text)
        self.assertNotIn('Durasi maksimal 1 menit',page.text)
        for key in ('creative_editing_1m','creative_editing_advanced','creative_editing_premium','creative_editing_professional'):
            page=self.client.get('/creative-services/checkout/'+key)
            for term in orders.offer(key)['scope_notes']:
                self.assertIn(term,page.text)
            self.assertNotIn('data-checkout-form',page.text)

    def test_anonymous_legacy_links_show_current_quote_without_order_form(self):
        client=self.app.test_client();client.set_cookie('kilas_language','id')
        before=self.counts()
        for key in orders.CATALOG['packages']:
            response=client.get('/creative-services/checkout/'+key)
            self.assertEqual(response.status_code,200,response.text)
            self.assertIn('quotation tertulis',response.text)
            self.assertIn('https://wa.me/6282213039137?',response.text)
            self.assertNotIn('data-checkout-form',response.text)
            self.assertNotIn('name="order_token"',response.text)
            if orders.offer(key)['amount'] is not None:
                self.assertIn(orders.money(orders.offer(key)['amount']),response.text)
        response=client.get('/creative-services/checkout/creative_social_premium?addon=mega')
        self.assertEqual(response.status_code,200)
        self.assertIn('Rp9.000.000',response.text)
        self.assertNotIn('Influencer',response.text)
        self.assertIn('dibayar di muka',response.text)
        self.assertEqual(client.get(self.path+'/login').status_code,303)
        self.assertEqual(before,self.counts())

    def test_direct_post_and_service_calls_cannot_create_new_invoices(self):
        before=self.counts()
        for key in orders.CATALOG['packages']:
            with self.app.app_context():
                token=orders.checkout_token(self.owner,key)
                with self.assertRaisesRegex(ValueError,'quotation tertulis'):
                    orders.create_order(self.owner,key,{'order_token':token})
            response=self.client.post('/creative-services/checkout/'+key,data={
                'order_token':token,'csrf_token':self.csrf(self.client),
                'name':'Synthetic','whatsapp':'081234567890','event_date':'2099-12-01',
                'location':'Synthetic venue','brand':'Synthetic','social_account':'@synthetic'})
            self.assertEqual(response.status_code,422)
            self.assertIn('quotation tertulis',response.text)
            self.assertNotIn('data-checkout-form',response.text)
        self.assertEqual(before,self.counts())

    def test_historical_snapshot_invoice_proof_and_nonce_replay_are_preserved(self):
        legacy=deepcopy(orders.CATALOG)
        item=legacy['packages']['creative_event_basic']
        item.update(amount=1500000,quotation_required=False,name='Historical event package',tier='Basic')
        with patch.object(orders,'CATALOG',legacy),self.app.app_context():
            token=orders.checkout_token(self.owner,'creative_event_basic')
            data={'order_token':token,'name':'Synthetic','whatsapp':'081234567890',
                  'event_date':'2099-12-01','location':'Synthetic venue'}
            invoice_id=orders.create_order(self.owner,'creative_event_basic',data)
        invoice=payment_service.get_invoice(invoice_id)
        project=projects_repo.get_project(invoice['project_id'])
        before=deepcopy(project['requirements']); counts=self.counts()
        with self.app.app_context():
            self.assertEqual(orders.create_order(self.owner,'creative_event_basic',data),invoice_id)
        replay=self.client.get(self.path+'?draft='+token)
        self.assertEqual(replay.status_code,303)
        self.assertTrue(replay.location.endswith('/payment/'+str(invoice_id)))
        page=self.client.get('/creative-services/payment/'+str(invoice_id))
        self.assertEqual(page.status_code,200)
        self.assertIn('Rp1.500.000',page.text)
        self.assertIn('data-proof-form',page.text)
        self.assertIn('Historical event package',self.client.get('/creative-services/orders').text)
        other=self.base.client(self.other)
        self.assertEqual(other.get('/creative-services/payment/'+str(invoice_id)).status_code,404)
        self.assertEqual(counts,self.counts())
        out=io.BytesIO();Image.new('RGB',(16,16),'white').save(out,format='PNG')
        response=self.client.post('/creative-services/payment/'+str(invoice_id),data={
            'csrf_token':self.csrf(self.client),'proof':(io.BytesIO(out.getvalue()),'proof.png','image/png')})
        self.assertEqual(response.status_code,303)
        self.assertEqual(self.client.get(f'/creative-services/payment/{invoice_id}/proof').status_code,200)
        self.assertEqual(projects_repo.get_project(invoice['project_id'])['requirements'],before)
        self.assertEqual(payment_service.get_invoice(invoice_id)['amount'],1500000)

    def test_quote_terms_are_localized(self):
        from creative_i18n import CATALOG
        for lang in ('id','en','es','zh'):
            self.client.set_cookie('kilas_language',lang)
            response=self.client.get(self.path)
            self.assertEqual(response.status_code,200)
            self.assertIn(CATALOG['Harga referensi / draft'][lang],response.text)
            self.assertIn(CATALOG['DP 50% setelah quotation disepakati; pelunasan 50% sebelum hasil diserahkan.'][lang],response.text)

for _name in list(auth_fixture.CustomerAuthTests.__dict__):
    if _name.startswith('test_') and _name not in CreativeQuotationTests.__dict__:
        setattr(CreativeQuotationTests,_name,None)

if __name__=='__main__':unittest.main()
