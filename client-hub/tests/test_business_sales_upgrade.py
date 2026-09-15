import ast,hashlib,io,json,re,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import test_knowledge_setup_v2 as fixture
import test_ux_catalog_final as previous
import catalog_service as catalog, pricing_config, projects_repo, requests
repo,db=fixture.repo,fixture.db
ROOT=Path(__file__).resolve().parents[2]

class SalesTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture.KnowledgeTests();self.base.setUp()
        self.client=self.base.client
        self.network=patch('requests.sessions.Session.request',side_effect=AssertionError('paid API prohibited'))
        self.network.start();self.addCleanup(self.network.stop)

    def test_official_facts_and_customer_cards(self):
        page=self.client.get('/services').get_data(as_text=True)
        for key,price,reels,photos in [('basic',1990000,4,4),('growth',3490000,8,6),('pro',5490000,12,10)]:
            item=catalog.get_catalog_item('content_'+key)
            self.assertEqual(item['price_amount'],price)
            self.assertIn(catalog.display_price(item),page)
            self.assertIn(f'{reels} Reels / short-form videos + {photos} foto final',page)
            answer=catalog.exact_sales_answer(key+' dapet apa?')
            self.assertIn(catalog.display_price(item),answer)
            self.assertIn(f'{photos} foto final',answer)
        self.assertIn('Rekomendasi',page)

    def test_one_time_update_historical_price_and_restart(self):
        item=catalog.get_catalog_item('content_basic')
        catalog.update_catalog_item(item['id'],price_amount=1500000)
        project=projects_repo.create_fixed_price_project(self.base.bid,catalog.get_catalog_item('content_basic'),self.base.uid)
        db.execute("DELETE FROM platform_settings WHERE key='content_packages_202609_v1'")
        catalog.seed_catalog_if_needed()
        self.assertEqual(catalog.get_catalog_item('content_basic')['price_amount'],1990000)
        self.assertEqual(projects_repo.get_project(project)['final_price'],1500000)
        catalog.update_catalog_item(item['id'],price_amount=2000000)
        catalog.seed_catalog_if_needed();self.assertEqual(catalog.get_catalog_item('content_basic')['price_amount'],2000000)
        self.assertIn('Rp2.000.000',catalog.exact_sales_answer('basic sekarang berapa'))

    def test_bundles_retained_inactive_and_cannot_reactivate(self):
        rows=[r for r in catalog.list_all_catalog() if r['category']=='BUNDLE'];self.assertTrue(rows)
        self.assertTrue(all(not r['is_active'] for r in rows))
        for row in rows:
            self.assertNotIn(row['catalog_key'],[r['catalog_key'] for r in catalog.list_active_catalog()])
            with self.assertRaises(catalog.InvalidCatalogState):catalog.update_catalog_item(row['id'],is_active=True)
        self.assertIn('terpisah',catalog.exact_sales_answer('ada bundle?'))
        self.assertIn('tidak ada paket bundle',catalog.exact_sales_answer('ada bundle?').lower())
        for category in ('ADS','EVENT','WEBSITE','TALENT','PHOTO','VIDEO'):
            self.assertTrue(any(r['category']==category for r in catalog.list_active_catalog()))

    def test_price_objection_no_discount_and_budget_not_repeated(self):
        for query in ('mahal','bisa kurang?','1 juta bisa?','yg murah'):
            result=catalog.exact_sales_answer(query,[{'content':'Content Growth'}])
            self.assertIn('belum didiskon',result)
        answer=catalog.exact_sales_answer('mahal',[{'content':'Budget yang kakak targetkan berapa?'}])
        self.assertNotIn('?',answer)

    def test_talent_management_fee_separate(self):
        reply=catalog.exact_sales_answer('udah termasuk talent?')
        self.assertIn('Belum termasuk fee talent',reply);self.assertNotIn('Rp',reply)
        self.assertIn('terpisah',catalog.service_description(catalog.get_catalog_item('talent_management')))

    def test_facts_bypass_customer_model_and_respect_brain_context(self):
        bot=previous.bot_functions()
        self.assertIn('Rp3.490.000',bot['_exact_customer_route']('growth brp?',[]))
        self.assertIsNone(catalog.exact_sales_answer('basic berapa',[{'content':'Kilas Brain'}]))
        self.assertIsNone(bot['_exact_customer_route']('growth brp?',[],tenant=True))
        self.assertIn(repo.get_official_links()['landing_page'],bot['_exact_customer_route']('ada linknya?',[]))

    def test_context_is_relevant_bounded_and_no_bundle(self):
        context=catalog.sales_context('Content Growth detail')
        self.assertIn('8 Reels',context);self.assertNotIn('Content Pro',context);self.assertNotIn('Kilas Brain Pro',context)
        self.assertLess(len(context),1800)
        self.assertIn('terpisah',catalog.sales_context('talent'))

    def owner_functions(self):
        tree=ast.parse((ROOT/'app.py').read_text())
        names={'_exact_platform_owner_customer','call_claude_owner'}
        ns={'_catalog_service':catalog,'owner_conversations':{},'conversations':{},'load_recent_messages_from_db':lambda *a:[],
            'save_message_to_db':Mock(),'_exact_owner_query':lambda *a:None,'_pending_owner_questions_for_tenant':lambda _: {}}
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'owner','exec'),ns)
        return ns

    def test_owner_facts_and_supported_history_zero_model(self):
        bot=self.owner_functions()
        self.assertIn('Rp1.990.000',bot['call_claude_owner']('owner','Basic sekarang berapa?',None,None))
        bot['conversations']['customer']=[{'role':'user','content':'Bisa bikin website?'}]
        self.assertIn('Bisa bikin website?',bot['call_claude_owner']('owner','customer ini terakhir nanya apa?',None,'customer'))
        self.assertIn('cuplikan',bot['_exact_platform_owner_customer']('ringkas chat customer ini','customer'))
        self.assertIn('Tidak ada permintaan',bot['_exact_platform_owner_customer']('ada chat yang perlu gue takeover?',None))
        self.assertIn('Belum ada laporan',bot['_exact_platform_owner_customer']('siapa yang nanya website hari ini?',None))
        self.assertNotIn('Bisa bikin website',bot['_exact_platform_owner_customer']('customer ini terakhir nanya apa?','T2:customer'))

    def test_platform_provider_error_never_retries(self):
        tree=ast.parse((ROOT/'app.py').read_text())
        for name in ('call_claude','call_claude_owner'):
            fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
            attempt=next(n for n in fn.body if isinstance(n,ast.Try) and 'api.anthropic.com' in ast.unparse(n))
            for image in (None,'image'):
                failure=requests.HTTPError(response=SimpleNamespace(status_code=503))
                post=Mock(side_effect=failure)
                ns=dict(requests=SimpleNamespace(post=post),image_b64=image,tenant_id=None,tenant_context_block='',
                        model_to_use='unchanged-model',ANTHROPIC_API_KEY='test',system_prompt='',history=[], user_message="test", owner_message="test", _ctx=__import__("context_engine"))
                with self.assertRaises(requests.HTTPError):exec(compile(ast.Module(body=[attempt],type_ignores=[]),'attempt','exec'),ns)
                self.assertEqual(post.call_count,1)

    def test_static_pdf_exact_unchanged_and_brief_fields_reused(self):
        path=ROOT/'client-hub/static/kilas-works-official-catalog.pdf'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),'a69937d7723de11211ddbedf290ac9408897b626b7d804ff140c6f4d2176ef43')
        template=(ROOT/'client-hub/templates/custom_project_request.html').read_text()
        for field in ('notes','goal','pages_features','reference','location','photoshoot_type','num_final_photos','num_videos'):
            self.assertIn('name="'+field+'"',template)
        for label in ('Status domain','kontak/WhatsApp','perkiraan jumlah produk','short-form sosial'):
            self.assertIn(label.lower(),template.lower())

if __name__=='__main__':unittest.main()
