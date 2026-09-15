import ast
import re
import unittest
from pathlib import Path
from unittest.mock import patch
import test_knowledge_setup_v2 as fixture
import test_ux_catalog_final as previous
import catalog_service as catalog
import pricing_config as facts

ROOT = Path(__file__).resolve().parents[2]

class ServiceFactsTests(unittest.TestCase):
    def setUp(self):
        self.base = fixture.KnowledgeTests()
        self.base.setUp()
        self.client = self.base.client
        self.net = patch('requests.sessions.Session.request', side_effect=AssertionError('no external API'))
        self.net.start()
        self.addCleanup(self.net.stop)

    def test_event_facts_prices_and_display(self):
        page = self.client.get('/services').get_data(as_text=True)
        for tier, price, minutes, photos in [('standard',1200000,'1',20),('lengkap',2800000,'2–3',50),('premium',4400000,'4–5',80)]:
            item = catalog.get_catalog_item('event_'+tier)
            self.assertEqual(item['price_amount'], price)
            description = facts.event_description(tier)
            self.assertIn(f'sekitar {minutes} menit', description)
            self.assertIn(f'sekitar {photos} foto final hasil edit', description)
            self.assertIn('RAW foto termasuk', description)
            self.assertIn('RAW video tidak termasuk', description)
            self.assertNotRegex(description, r'jam|fotografer|album|teaser')
            self.assertIn(description, page)
            self.assertIn(description, catalog.exact_sales_answer('event '+tier+' dapet apa?'))

    def test_managed_hosting(self):
        page = self.client.get('/services').get_data(as_text=True)
        for suffix,price in [('com',999000),('id',1099000)]:
            item = catalog.get_catalog_item('website_domain_'+suffix+'_hosting')
            self.assertEqual(item['price_amount'],price)
            self.assertIn('Managed .'+suffix+' + Hosting',page)
            reply = catalog.exact_sales_answer('domain .'+suffix+' hosting termasuk apa?')
            for inclusion in facts.MANAGED_HOSTING_INCLUSIONS:
                self.assertIn(inclusion,reply)

    def test_transport_boundaries(self):
        for distance,fee in [(0,0),(20,0),(20.001,100000),(35,100000),(35.001,150000),(50,150000),(50.001,200000),(70,200000),(70.001,None)]:
            self.assertEqual(facts.transport_fee(distance),fee)
        self.assertIsNone(facts.transport_fee(10,out_of_town=True))
        for invalid in (-1,float('nan'),float('inf'),True,'35'):
            with self.assertRaises(ValueError): facts.transport_fee(invalid)

    def test_transport_does_not_guess_distance_or_extras(self):
        for query in ('transport ke Bandung berapa?', 'parkir berapa?', 'tol Jakarta?', 'jarak dari link Maps?'):
            self.assertEqual(catalog.exact_sales_answer(query),facts.TRANSPORT_POLICY)
        self.assertIn('biaya aktual',facts.TRANSPORT_POLICY)
        self.assertIn('Jarak jalan tidak ditebak',facts.TRANSPORT_POLICY)
        self.assertIn(facts.TRANSPORT_POLICY.replace('>','&gt;'),self.client.get('/services').get_data(as_text=True))

    def test_supplied_distance_conditional_zone_no_geocoding(self):
        for distance, expected in [(20,'gratis'),(35,'Rp100.000'),(50,'Rp150.000'),(70,'Rp200.000'),(71,'Custom Quote')]:
            reply=catalog.exact_sales_answer(f'biaya transport jarak {distance} km')
            self.assertIn(expected,reply)
            self.assertIn('Jika jarak jalan',reply)
            self.assertIn('bukan verifikasi jarak',reply)
            self.assertTrue(catalog.is_exact_transport_reply(reply))
            self.assertFalse(catalog.is_exact_transport_reply(reply+' Tol Rp100.000'))
        self.assertIn('Custom Quote',catalog.exact_sales_answer('transport luar kota jarak 15 km'))

    def test_transport_guard_exact_only_tenant_still_blocked(self):
        tree = ast.parse((ROOT/'app.py').read_text())
        fn = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_enforce_customer_price_guardrail')
        ns = {'_catalog_service':catalog, '_service_facts':facts, '_reply_prices_are_all_canonical_kilas_works':lambda _:False,
              '_customer_reply_contains_price_disclosure':lambda _:True, 'CUSTOMER_PRICE_SAFE_FALLBACK_REPLY':'blocked'}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'guard','exec'),ns)
        guard=ns[fn.name]
        self.assertEqual(guard(facts.TRANSPORT_POLICY,'',True),facts.TRANSPORT_POLICY)
        self.assertEqual(guard(facts.TRANSPORT_POLICY,'tenant',True),'blocked')
        self.assertEqual(guard('Tol Rp100.000','',True),'blocked')
        self.assertEqual(guard(facts.TRANSPORT_POLICY+' Tol Rp100.000','',True),'blocked')

    def test_service_order_active_status_unchanged(self):
        before = [(r['id'],r['is_active']) for r in catalog.list_all_catalog()]
        page=self.client.get('/services').get_data(as_text=True)
        titles=['Kilas Brain','Content / Creative','Website','Business Systems','Fotografi','Videografi','Talent Management','Event','Meta Ads']
        positions=[page.index('<h2>'+title+'</h2>') for title in titles]
        self.assertEqual(positions,sorted(positions))
        self.assertEqual(before,[(r['id'],r['is_active']) for r in catalog.list_all_catalog()])

    def test_ads_prices_disclosures(self):
        for key,price in [('ads_setup_only',399000),('ads_management',799000)]:
            row=catalog.get_catalog_item(key)
            self.assertEqual(row['price_amount'],price)
            self.assertIn(facts.ADS_DESCRIPTION,catalog.service_description(row))
        for part in ('terpisah ke Meta','konten/foto/video iklan terpisah','Tidak ada jaminan ROAS, sales, leads'):
            self.assertIn(part,catalog.exact_sales_answer('meta ads termasuk apa?'))

    def test_platform_exact_tenant_guard(self):
        bot=previous.bot_functions()
        for query in ('event standard dapet apa?', 'hosting .com berapa?', 'transport berapa?', 'meta ads apa?'):
            self.assertTrue(bot['_exact_customer_route'](query,[]))
            self.assertIsNone(bot['_exact_customer_route'](query,[],tenant=True))
        self.assertIn(facts.event_description('premium'),catalog.sales_context('event premium detail'))
        self.assertIn(facts.MANAGED_HOSTING_DESCRIPTION,catalog.sales_context('hosting'))

    def test_legacy_platform_event_prompt_no_old_facts(self):
        source=(ROOT/'app.py').read_text()
        section=source[source.index('    "event": {'):source.index('    "custom_automation_redirect":')]
        self.assertNotRegex(section,r'hingga [58] jam|album cetak|250000|300rb')
        self.assertIn('_service_facts.event_description',section)
        self.assertNotIn('Tangerang & Jakarta: boleh bilang natural "gratis',source)

if __name__=='__main__':unittest.main()
