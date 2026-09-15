"""Offline direct routing, action separation and scoped unavailable behavior."""
import unittest
from unittest.mock import patch
import _test_bootstrap
import app as bot
import official_link_routing as links

class LinkTests(unittest.TestCase):
    def setUp(self):
        bot.conversations.clear();bot.owner_conversations.clear();bot.tenant_owner_conversations.clear()
        self.data=bot._ch_repo.get_official_links()
        self.provider=patch.object(bot.requests,'post',side_effect=AssertionError('paid call'))
        self.http=self.provider.start();self.addCleanup(self.provider.stop)
        self.storage=patch.object(bot,'save_message_to_db');self.storage.start();self.addCleanup(self.storage.stop)

    def test_owner_all_requested_aliases_no_model(self):
        groups={'landing_page':['website kita','website kilas works','landing page kita','website landing page kilasworks dong kirim kesini','kirim website kita','kirim link website','web kita mana','link kilasworks','website resmi kita'],
                'demo':['demo kita dong','link demo','demo kilas brain','kirim demo','link buat coba kilas brain'],
                'instagram':['ig kita','instagram kita','kirim ig','link instagram'],
                'app':['client hub','client hub kita','link client hub','app kita','login app']}
        for key,phrases in groups.items():
            for phrase in phrases:
                with self.subTest(phrase=phrase):
                    reply=bot.call_claude_owner('owner',phrase,None,None)
                    self.assertIn(self.data[key],reply)
                    self.assertEqual(reply.count('https://'),1)
        self.http.assert_not_called()

    def test_owner_webhook_before_send_target_resolution(self):
        with patch.object(bot,'send_whatsapp_message',return_value=(True,None)) as sent,patch.object(bot,'call_claude_owner',side_effect=AssertionError('owner model path')):
            client=bot.app.test_client()
            for i,text in enumerate(('website landing page kilasworks dong kirim kesini','demo kita dong','ig kita','client hub kita')):
                response=client.post('/webhook',json={'entry':[{'changes':[{'value':{'messages':[{'id':f'light-{i}','from':bot.OWNER_WHATSAPP_NUMBER,'type':'text','text':{'body':text}}]}}]}]})
                self.assertEqual(response.status_code,200)
            self.assertEqual(sent.call_count,4)
        self.http.assert_not_called()

    def test_customer_direct_aliases_no_model(self):
        for phrase in ('website Kilas Works apa','website kalian','link website','ada webnya','webnya mana','landing page Kilas Works','mau lihat website kalian','link Kilas Works'):
            with self.subTest(phrase=phrase):
                reply=bot.call_claude('customer',phrase,defer_delivery=True)
                self.assertIn(self.data['landing_page'],reply)
                self.assertEqual(reply.count('https://'),1)
        self.http.assert_not_called()

    def test_demo_only_relevant(self):
        self.assertIn(self.data['demo'],bot._exact_customer_route('demo kilas brain',[]))
        self.assertIn(self.data['demo'],bot._exact_customer_route('mau lihat botnya',[]))
        self.assertIn(self.data['demo'],bot._exact_customer_route('bisa dicoba?',[{'content':'Kilas Brain'}]))
        self.assertIsNone(links.classify_official_link_intent('bisa dicoba?',[{'content':'Content Growth'}]))
        reply=bot._exact_customer_route('growth brp?',[])
        self.assertNotIn(self.data['demo'],reply)

    def test_exploratory_single_link(self):
        for phrase in ('Kilas Works ada layanan apa aja?','mau lihat-lihat dulu','ada info lengkap?'):
            reply=bot._exact_customer_route(phrase,[])
            self.assertIn(self.data['landing_page'],reply)
            self.assertEqual(reply.count('https://'),1)

    def test_purchase_and_complex_work_not_consumed(self):
        for text in ('aku mau beli Kilas Brain','mau order website','bikin website untuk usaha saya','analisis website kita bagus ga','kirim link website ke Wilson','kirim ke customer ini link demo'):
            self.assertIsNone(links.classify_official_link_intent(text,role='owner'))

    def test_ready_purchase_keeps_setup_path(self):
        bot._catalog_service.seed_catalog_if_needed()
        reply=bot.call_claude('628999900001','mau Kilas Brain',defer_delivery=True)
        self.assertIn('Setup Awal',reply)
        self.assertNotIn(self.data['demo'],reply)
        self.http.assert_not_called()

    def test_owner_followup_remembers_direct_demo(self):
        bot.call_claude_owner('owner','demo kita',None,None)
        reply=bot.call_claude_owner('owner','linknya mana?',None,None)
        self.assertIn(self.data['demo'],reply)
        self.http.assert_not_called()

    def test_history_bounded_and_recent_resource(self):
        self.assertEqual(links.classify_official_link_intent('linknya mana',[{'content':'Instagram'}]),'instagram')
        self.assertEqual(links.classify_official_link_intent('linknya mana',[{'content':'Instagram'}]+[{'content':'ok'}]*6),'landing_page')
        self.assertEqual(links.classify_official_link_intent('linknya mana',[{'content':[]}]),'landing_page')

    def test_tenant_customer_and_owner_never_platform_fallback(self):
        with patch.object(bot._ch_repo,'get_official_links',side_effect=AssertionError('platform leak')):
            for tenant in (21,22):
                reply=bot.call_claude('same-phone','website kalian',tenant_id=tenant,tenant_context_block='Scoped business',defer_delivery=True)
                self.assertIn('belum tersedia',reply)
                reply=bot.call_tenant_owner_ai(tenant,'same-owner','website kita','Tenant')
                self.assertIn('belum tersedia',reply)
                self.assertNotIn('kilasworks',reply)
        self.http.assert_not_called()

    def test_pure_resolver_uses_only_supplied_tenant_resource(self):
        self.assertIn('https://tenant-a.example',links.link_reply('landing_page',{'landing_page':'https://tenant-a.example'},tenant=True))
        self.assertNotIn('tenant-a',links.link_reply('landing_page',{},tenant=True))
        for value in ('javascript:alert(1)','https://secret:token@example.test','https://example.test\nsecret'):
            self.assertIn('belum tersedia',links.link_reply('landing_page',{'landing_page':value},tenant=True))

    def test_live_settings_and_safe_missing(self):
        with patch.object(bot._ch_repo,'get_official_links',return_value={'landing_page':'https://updated.example'}):
            self.assertIn('https://updated.example',bot._official_link_answer('website kita',owner=True))
        with patch.object(bot._ch_repo,'get_official_links',side_effect=RuntimeError('secret')):
            reply=bot._official_link_answer('website kita',owner=True)
            self.assertNotIn('secret',reply);self.assertIn('belum bisa diambil',reply)

    def test_catalog_owner_transport_not_consumed(self):
        self.assertIsNone(bot._official_link_answer('kirim katalog ke gw',owner=True))
        self.assertIsNone(bot._official_link_answer('kirim katalog ke Wilson',owner=True))
        for text in ('kirim katalog','kirim katalognya','minta katalog','kirim pricelist','kirim semua harga','daftar layanan','lihat paket di mana'):
            self.assertIn(self.data['catalog'],bot._exact_customer_route(text,[]))

    def test_owner_fallback_compact_and_query_gated(self):
        with patch.object(bot,'_build_official_links_note_safe',return_value='LINK_CANONICAL') as note:
            unrelated=str(bot.build_owner_system_prompt(None,None,query='ringkas chat'))
            note.assert_not_called();self.assertNotIn('LINK_CANONICAL',unrelated)
            relevant=str(bot.build_owner_system_prompt(None,None,query='jelaskan cara pakai website kita'))
            note.assert_called_once();self.assertIn('LINK_CANONICAL',relevant)
            self.assertIn('Jangan buat domain alternatif',relevant)

if __name__=='__main__':unittest.main()
