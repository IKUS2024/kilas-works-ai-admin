"""Focused catalog/navigation acceptance; real SQLite routes, no paid APIs."""
import ast
import io
import json
from html.parser import HTMLParser
import re
import unittest
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import test_knowledge_setup_v2 as fixture
import catalog_service as catalog
import catalog_cache
import live_catalog_pdf as pdf
import pricing_config
from pypdf import PdfReader

repo, db, hub, security = fixture.repo, fixture.db, fixture.hub, fixture.security
ROOT = Path(__file__).resolve().parents[2]


def bot_functions():
    tree = ast.parse((ROOT / 'app.py').read_text())
    names = {'_official_link_answer', '_exact_customer_route', '_build_official_links_note_safe', 'build_focused_customer_prompt',
             '_get_live_catalog_pdf_path_safe', '_get_static_catalog_pdf_path_safe', 'get_catalog_media_id', 'send_catalog_pdf'}
    module = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
    ns = {'_catalog_service':catalog, '__file__':str(ROOT/'app.py'), 'os':os, 're': re, 'json': json, '_CLIENT_HUB_AVAILABLE': True, '_ch_repo': repo}
    import sys
    sys.path.insert(0,str(ROOT))
    import official_link_routing
    ns['_links']=official_link_routing
    exec(compile(module, 'platform-functions', 'exec'), ns)
    return ns


class CatalogUXTests(unittest.TestCase):
    def setUp(self):
        self.base = fixture.KnowledgeTests(); self.base.setUp()
        self.client, self.bid = self.base.client, self.base.bid
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('Unexpected API call'))
        self.network.start(); self.addCleanup(self.network.stop)

    def admin(self):
        uid = repo.create_user('catalog-admin@test.com', security.hash_password('password123'), role='KILAS_ADMIN')
        client = hub.app.test_client(); client.post('/login', data={'email':'catalog-admin@test.com','password':'password123'})
        return client

    def test_incomplete_setup_and_completed_editor(self):
        for status in ('DRAFT','ONBOARDING','READY_FOR_AI_SETUP'):
            db.execute('UPDATE businesses SET status=? WHERE id=?',(status,self.bid))
            page = self.client.get('/dashboard').get_data(as_text=True)
            self.assertIn('Lanjutkan Setup Awal',page)
            self.assertEqual(self.client.get(f'/business/{self.bid}/wizard/basics').status_code,200)
        for status in ('READY_FOR_REVIEW','NEEDS_REVISION','APPROVED','ACTIVE','SUSPENDED'):
            db.execute('UPDATE businesses SET status=? WHERE id=?',(status,self.bid))
            page = self.client.get('/dashboard').get_data(as_text=True)
            self.assertIn('Ajari Kilas Brain',page); self.assertNotIn('Edit Data Bisnis',page)
            response=self.client.get(f'/business/{self.bid}/wizard/basics')
            self.assertEqual(response.status_code,302); self.assertTrue(response.location.endswith('/memory'))

    def test_review_operational_payment_activation_links_preserved(self):
        db.execute("UPDATE businesses SET status='APPROVED' WHERE id=?",(self.bid,))
        page=self.client.get('/dashboard').get_data(as_text=True)
        for label in ('Tinjau Bisnis','Pengaturan Operasional','Invoice/Pembayaran','Hubungkan WhatsApp ke Kilas Brain'):
            self.assertIn(label,page)
        self.assertEqual(self.client.get(f'/business/{self.bid}/review').status_code,200)

    def test_wizard_redirect_preserves_ownership(self):
        other=repo.create_user('other@test.com',security.hash_password('password123'))
        bid=repo.create_business(other,'Other','AI_ADMIN_BASIC')
        db.execute("UPDATE businesses SET status='ACTIVE' WHERE id=?",(bid,))
        self.assertIn(self.client.get(f'/business/{bid}/wizard/basics').status_code,(403,404))

    def test_customer_active_only_cards_safe_description(self):
        item=catalog.get_catalog_item('website_landing_page')
        catalog.update_catalog_item(item['id'],description='<script>alert(1)</script>')
        page=self.client.get('/services').get_data(as_text=True)
        parser=HTMLParser(); tags=[]; parser.handle_starttag=lambda tag,attrs:tags.append(tag); parser.feed(page)
        self.assertNotIn('table',tags); self.assertIn('service-grid',page); self.assertIn('minmax(min(100%',page)
        self.assertIn('&lt;script&gt;',page); self.assertNotIn('<script>alert',page)
        catalog.update_catalog_item(item['id'],is_active=False)
        self.assertNotIn('<h3>Landing Page</h3>',self.client.get('/services').get_data(as_text=True))
        self.assertIsNotNone(catalog.get_catalog_item('website_landing_page'))

    def test_admin_archive_restore_survives_restart(self):
        client=self.admin(); key=pricing_config.RETIRED_BUNDLE_KEYS[0]
        db.execute("INSERT INTO service_catalog(catalog_key,category,name,pricing_mode,is_active) VALUES(?,?,?,?,?)", (key,'BUNDLE','Archived Historical Bundle','CUSTOM_QUOTE',False))
        item=catalog.get_catalog_item(key)
        self.assertIsNotNone(item)
        self.assertNotIn(item['name'],client.get('/admin/catalog').get_data(as_text=True))
        self.assertIn(item['name'],client.get('/admin/catalog?view=archive').get_data(as_text=True))
        self.assertEqual(client.post(f"/admin/catalog/{item['id']}/toggle-active").status_code,302)
        catalog.seed_catalog_if_needed()
        self.assertFalse(catalog.get_catalog_item(key)['is_active'])
        self.assertNotIn(item['name'],client.get('/admin/catalog').get_data(as_text=True))

    def test_description_admin_edit_survives_boot(self):
        item=catalog.get_catalog_item('website_landing_page'); catalog.update_catalog_item(item['id'],description='Scope resmi dari admin')
        catalog.seed_catalog_if_needed()
        self.assertEqual(catalog.service_description(catalog.get_catalog_item('website_landing_page')),'Scope resmi dari admin')

    def test_defaults_no_fabricated_counts_and_matrix(self):
        for key in ('content_basic','content_growth','content_pro'):
            text=catalog.service_description(catalog.get_catalog_item(key))
            facts=pricing_config.CONTENT_PACKAGES[key.removeprefix('content_')]
            self.assertIn(f"{facts['reels']} Reels",text); self.assertIn(f"{facts['photos']} foto final",text)
            self.assertNotRegex(text,r'\d+ (?:revisi|jam)')
        basic=catalog.service_description(catalog.get_catalog_item('ai_admin_basic'))
        pro=catalog.service_description(catalog.get_catalog_item('ai_admin_pro'))
        for phrase in ('alur booking','percakapan pembayaran','perintah owner','voice note'):
            self.assertNotIn(phrase,basic); self.assertIn(phrase,pro)
        self.assertIn('Kilas Inbox',basic)

    def test_live_pricing_mode_wins(self):
        row=dict(catalog.get_catalog_item('content_basic'))
        row.update(pricing_mode='CUSTOM_QUOTE',price_amount=12345)
        self.assertNotIn('12345',catalog.display_price(row))
        row.update(pricing_mode='STARTING_FROM',price_amount=876543)
        self.assertEqual(catalog.display_price(row),'Mulai dari Rp876.543 per bulan')

    def test_four_link_defaults_and_admin_catalog_setting(self):
        links=repo.get_official_links()
        self.assertEqual([links[k] for k in ('landing_page','app','instagram','catalog')],
                         ['https://kilasworks.id','https://app.kilasworks.id','https://instagram.com/kilasworks','https://app.kilasworks.id/catalog.pdf'])
        client=self.admin(); self.assertIn('name="catalog"',client.get('/admin/settings/official-links').get_data(as_text=True))
        before=catalog_cache.get_version()
        self.assertEqual(client.post('/admin/settings/official-links',data={'catalog':'https://app.kilasworks.id/catalog.pdf?live=1'}).status_code,302)
        self.assertEqual(repo.get_official_links()['catalog'],'https://app.kilasworks.id/catalog.pdf?live=1')
        self.assertNotEqual(before,catalog_cache.get_version())

    def test_platform_links_deterministic_and_tenant_never_receives(self):
        bot=bot_functions()
        for question,key in [('website Kilas Works apa?','landing_page'),('IG-nya apa?','instagram'),('Instagram?','instagram'),
                             ('ada katalog?','catalog'),('kirim katalog','catalog'),('pricelist','catalog'),('daftar layanan','catalog'),
                             ('layanan Kilas Works apa aja?','catalog'),('lihat paket di mana?','catalog')]:
            self.assertIn(repo.get_official_links()[key],bot['_exact_customer_route'](question,[]))
            self.assertIn('belum tersedia',bot['_exact_customer_route'](question,[],tenant=True))
        repo.set_platform_setting('official_link_instagram','https://instagram.com/updated')
        self.assertIn('/updated',bot['_exact_customer_route']('Instagram?',[]))

    def test_tenant_prompt_does_not_read_platform_catalog_or_links(self):
        bot=bot_functions(); forbidden=lambda *a,**k: self.fail('Platform context accessed for tenant')
        bot.update(_ctx=SimpleNamespace(customer_core=lambda *a:'TENANT CORE',relevant_records=lambda *a:[],cache_blocks=lambda *a:a),
                   AI_ADMIN_CORE_BEHAVIOR='',build_language_context=lambda *a:'id',customer_names={},agreed_facts={},
                   _build_official_links_note_safe=forbidden,_build_active_service_categories_safe=forbidden,
                   _build_live_price_sync_note_safe=forbidden)
        result=bot['build_focused_customer_prompt']('tenant-key','website Instagram katalog pricelist','TOKO SENDIRI')
        self.assertIn('TOKO SENDIRI',str(result)); self.assertNotIn('kilasworks',str(result).lower())

    def test_pdf_live_values_active_archive_and_safe_text(self):
        item=catalog.get_catalog_item('website_landing_page')
        catalog.update_catalog_item(item['id'],name='LIVE UNIQUE',price_amount=876543,description='Admin <b>literal</b> & scope')
        def text(): return '\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.generate_catalog_pdf_bytes())).pages)
        generated=text(); self.assertIn('LIVE UNIQUE',generated); self.assertIn('876.543',generated)
        self.assertIn('<b>literal</b>',generated); self.assertIn('https://kilasworks.id',generated)
        self.assertIn('https://app.kilasworks.id/catalog.pdf',generated)
        catalog.update_catalog_item(item['id'],is_active=False); self.assertNotIn('LIVE UNIQUE',text())
        catalog.update_catalog_item(item['id'],is_active=True); self.assertIn('LIVE UNIQUE',text())

    def test_pdf_price_not_overridden_by_category(self):
        item=catalog.list_active_catalog()[0]
        sample=dict(item, category='PHOTO',name='Fixed live photo',price_amount=654321,pricing_mode='FIXED_PRICE',description='Scope admin')
        with patch.object(catalog,'list_active_catalog',return_value=[sample]):
            text='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.generate_catalog_pdf_bytes())).pages)
        self.assertIn('654.321',text)

    def test_public_names_internal_keys_unchanged(self):
        item=catalog.get_catalog_item('ai_admin_basic'); self.assertEqual(item['category'],'AI_ADMIN')
        for path in ('/services','/dashboard',f'/business/{self.bid}/simulate'):
            self.assertNotIn('AI Admin',self.client.get(path).get_data(as_text=True))
        self.assertIn('value="AI_ADMIN"',self.client.get('/dashboard').get_data(as_text=True))
        self.assertNotIn('value="AI_ADMIN_BASIC"',self.client.get('/dashboard').get_data(as_text=True))

    def test_public_pdf_is_exact_static_asset_despite_catalog_changes(self):
        asset=ROOT/'client-hub/static/kilas-works-official-catalog.pdf'
        expected=asset.read_bytes()
        self.assertEqual(hashlib.sha256(expected).hexdigest(), 'a69937d7723de11211ddbedf290ac9408897b626b7d804ff140c6f4d2176ef43')
        item=catalog.get_catalog_item('content_basic')
        # Public endpoint needs neither login nor catalog reads/generation.
        client=hub.app.test_client()
        with patch.object(pdf,'get_cached_catalog_pdf_path',side_effect=AssertionError('generator called')), patch.object(catalog,'list_active_catalog',side_effect=AssertionError('catalog read')):
            for active,price in ((True,123456),(False,987654),(True,234567)):
                catalog.update_catalog_item(item['id'],is_active=active,price_amount=price)
                response=client.get('/catalog.pdf')
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.mimetype,'application/pdf')
                self.assertEqual(response.data,expected); response.close()

    def test_platform_document_upload_uses_static_catalog_only(self):
        bot=bot_functions(); uploads=[]
        asset=ROOT/'client-hub/static/kilas-works-official-catalog.pdf'
        bot.update(_get_live_catalog_pdf_path_safe=lambda:self.fail('live generator called'),
                   _CATALOG_MEDIA_ID_CACHE={'media_id':None,'path':None,'mtime':None},
                   upload_media=lambda path,mime: uploads.append((Path(path).read_bytes(),mime)) or 'media-id')
        self.assertEqual(Path(bot['_get_static_catalog_pdf_path_safe']()),asset)
        self.assertEqual(bot['get_catalog_media_id'](),'media-id')
        self.assertEqual(bot['get_catalog_media_id'](),'media-id')
        self.assertEqual(uploads,[(asset.read_bytes(),'application/pdf')])
        bot['_get_static_catalog_pdf_path_safe']=lambda:None
        self.assertIsNone(bot['get_catalog_media_id']())

    def test_catalog_document_send_uses_uploaded_static_bytes(self):
        bot=bot_functions(); uploads=[]; sends=[]
        bot.update(_CATALOG_MEDIA_ID_CACHE={'media_id':None,'path':None,'mtime':None},
                   upload_media=lambda path,mime: uploads.append(Path(path).read_bytes()) or 'static-id',
                   _active_whatsapp_phone_number_id=lambda:'test-id', _active_whatsapp_access_token=lambda:'test-token',
                   CATALOG_PDF_FILENAME='Katalog Kilas Works.pdf',
                   requests=SimpleNamespace(post=lambda *a,**k:sends.append(k['json']) or SimpleNamespace(status_code=200)),
                   _whatsapp_result=lambda response:(True,None))
        self.assertEqual(bot['send_catalog_pdf']('test-recipient'),(True,None))
        self.assertEqual(uploads,[(ROOT/'client-hub/static/kilas-works-official-catalog.pdf').read_bytes()])
        self.assertEqual(len(sends),1); self.assertEqual(sends[0]['document']['id'],'static-id')

    def test_short_link_followups_without_clarification(self):
        bot=bot_functions(); links=repo.get_official_links()
        for question,key in (('ada linknya?','landing_page'),('linknya mana?','landing_page'),('ada webnya?','landing_page'),
                             ('websitenya?','landing_page'),('ada katalog?','catalog'),('kirim katalog','catalog'),
                             ('ada IG?','instagram'),('instagramnya?','instagram')):
            reply=bot['_exact_customer_route'](question,[])
            self.assertIn(links[key],reply)
            self.assertNotIn('?',reply); self.assertNotIn('Drive',reply)

    def test_context_orders_relevant_official_link_first(self):
        bot=bot_functions(); links=repo.get_official_links()
        for context,key in (('Company Profile / Landing Page / Website','landing_page'),('Katalog layanan','catalog'),('Instagram','instagram'),('Client Hub login','app')):
            reply=bot['_exact_customer_route']('ada linknya?',[{'role':'assistant','content':context}])
            self.assertIn(links[key],reply)

    def test_portfolio_request_never_invents_a_project_or_folder_link(self):
        bot=bot_functions(); links=repo.get_official_links()
        for question in ('ada link portfolio?', 'link portofolionya?', 'ada URL project?'):
            reply=bot['_exact_customer_route'](question,[])
            self.assertIn('Belum ada link khusus',reply)
            self.assertIn(links['landing_page'],reply); self.assertNotIn(links['instagram'],reply)
            self.assertNotIn('Drive',reply); self.assertNotIn('folder',reply)
        reply=bot['_exact_customer_route']('ada linknya?',[{'role':'user','content':'portfolio'}])
        self.assertIn('Belum ada link khusus',reply)

    def test_new_link_routes_tenant_guard_precedes_settings_and_history(self):
        bot=bot_functions()
        bot['_ch_repo']=SimpleNamespace(get_official_links=lambda:self.fail('tenant accessed platform settings'))
        for question in ('ada linknya?', 'linknya mana?', 'ada webnya?', 'websitenya?', 'ada katalog?', 'kirim katalog', 'ada IG?', 'instagramnya?', 'link portfolio?'):
            self.assertIn('belum tersedia',bot['_exact_customer_route'](question,[{'content':'website Kilas Works'}],tenant=True))

    def test_missing_links_fail_safely_and_history_is_bounded(self):
        bot=bot_functions(); bot['_CLIENT_HUB_AVAILABLE']=False
        self.assertIn('belum bisa diambil',bot['_exact_customer_route']('ada linknya?',[]))
        bot['_CLIENT_HUB_AVAILABLE']=True
        history=[{'content':'Instagram'}]+[{'content':[]}] * 6
        reply=bot['_exact_customer_route']('ada linknya?',history)
        self.assertIn('Website resmi Kilas Works:',reply)

    def test_catalog_add_invalidates_pdf(self):
        before=catalog_cache.get_version(); catalog.create_catalog_item('CONTENT','New live','CUSTOM_QUOTE')
        self.assertNotEqual(before,catalog_cache.get_version())


if __name__=='__main__': unittest.main()
