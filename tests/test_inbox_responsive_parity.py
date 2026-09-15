"""Focused Inbox navigation, scoped filtering and safe template failure regression tests."""
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timezone, timedelta
import test_inbox_unification as f


class InboxParityTests(unittest.TestCase):
    def setUp(self):
        f.reset_db()
        self.user, self.biz = f._make_active_ai_admin_tenant('Parity', 'parity@example.test')
        self.admin = f._make_admin()
        self.client = f.fresh_client()
        self.phone = '628700111010'
        self.other_phone = '628700111020'
        self.env = patch.dict(os.environ, {'WHATSAPP_REENGAGEMENT_TEMPLATE_NAME':'',
            'KILAS_BOT_PLATFORM_REPLY_URL':'', 'KILAS_BOT_INTERNAL_URL':'',
            'INTERNAL_SERVICE_SECRET':''})
        self.env.start(); self.addCleanup(self.env.stop)

    def login(self, platform):
        with self.client.session_transaction() as session:
            session['user_id'] = self.admin['id'] if platform else self.user

    def seed(self, platform, phone=None, hours=0, content='Preview unik'):
        phone = phone or self.phone
        if platform:
            f.db.execute("INSERT INTO messages(number,mode,role,content,created_at) VALUES (?,'customer','user',?,?)",
                (phone, content, (datetime.now(timezone.utc)-timedelta(hours=hours)).isoformat()))
        else:
            f._seed_message(self.biz, phone, 'user', content, hours_ago=hours)

    def base(self, platform):
        return '/admin/inbox' if platform else f'/business/{self.biz}/inbox'

    def takeover(self, platform):
        if platform:
            f.platform_inbox_service.start_human_takeover(self.phone)
        else:
            f.wa_takeover_service.start_human_takeover(self.biz,self.phone,self.user)

    def test_no_selection_does_not_load_first_thread(self):
        for platform in (True,False):
            self.login(platform); self.seed(platform)
            service = f.platform_inbox_service if platform else f.inbox_service
            with patch.object(service,'get_thread') as thread:
                page=self.client.get(self.base(platform))
            self.assertEqual(page.status_code,200)
            self.assertIn(b'kw-inbox-shell no-selection',page.data)
            self.assertIn(b'Pilih percakapan',page.data)
            thread.assert_not_called()

    def test_selected_thread_and_back_link_both_inboxes(self):
        for platform in (True,False):
            self.login(platform); self.seed(platform)
            page=self.client.get(self.base(platform)+'?customer='+self.phone)
            self.assertEqual(page.status_code,200)
            self.assertIn(b'kw-inbox-shell has-selection',page.data)
            self.assertIn(b'kw-back btn',page.data)
            self.assertIn('← Percakapan'.encode(),page.data)
            self.assertIn(b'id="kw-thread"',page.data)
            self.assertIn(b'Preview unik',page.data)

    def test_scoped_search_name_phone_preview_and_mode(self):
        for platform in (True,False):
            self.seed(platform); self.seed(platform,self.other_phone,content='Lainnya')
            self.takeover(platform)
            key=self.phone if platform else f'T{self.biz}:{self.phone}'
            f.db.execute('INSERT INTO customer_profiles(number,name) VALUES (?,?)',(key,'Nama Unik'))
            service=f.platform_inbox_service if platform else f.inbox_service
            args=() if platform else (self.biz,)
            for search in ('nama unik','111010','preview unik'):
                rows=service.list_conversations(*args,search=search)
                self.assertEqual([r['customer_phone'] for r in rows],[self.phone])
            rows=service.list_conversations(*args,mode_filter='HUMAN_TAKEOVER')
            self.assertEqual([r['customer_phone'] for r in rows],[self.phone])
            rows=service.list_conversations(*args,mode_filter='AI_ACTIVE')
            self.assertEqual([r['customer_phone'] for r in rows],[self.other_phone])
            self.login(platform)
            page=self.client.get(self.base(platform)+'?q=unik&mode=HUMAN_TAKEOVER')
            self.assertIn(b'Preview unik',page.data)
            self.assertNotIn(b'Lainnya',page.data)
        _, other=f._make_active_ai_admin_tenant('Other','other@example.test')
        f._seed_message(other,'628700999999','user','Forbidden preview')
        self.login(False)
        self.assertNotIn(b'Forbidden preview',self.client.get(self.base(False)).data)
        self.assertIn(self.client.get(f'/business/{other}/inbox').status_code,(403,404))

    def test_expired_human_has_template_not_free_text_and_friendly_missing_config(self):
        for platform in (True,False):
            self.login(platform); self.seed(platform,hours=30); self.takeover(platform)
            page=self.client.get(self.base(platform)+'?customer='+self.phone)
            self.assertIn(b'Human Handling',page.data)
            self.assertIn(b'Masa chat 24 jam sudah berakhir',page.data)
            self.assertIn(b'Kirim Template &amp; Lanjutkan',page.data)
            self.assertNotIn(b'<textarea name="message"',page.data)
            self.assertIn(b'disabled',page.data)
            if not platform:
                self.assertIn(b'Template WhatsApp untuk melanjutkan chat belum dikonfigurasi. Hubungi Kilas Works.',page.data)
            service=f.platform_inbox_service if platform else f.inbox_service
            args=(self.phone,) if platform else (self.biz,self.phone)
            with patch.object(service.requests,'post') as post:
                self.assertEqual(service.send_template_reply(*args),(False,'reengagement_template_not_configured'))
            post.assert_not_called()

    def test_platform_readiness_requires_bridge_and_secret(self):
        s=f.platform_inbox_service
        self.assertFalse(s.template_readiness()['ready'])
        os.environ['WHATSAPP_REENGAGEMENT_TEMPLATE_NAME']='approved_test'
        self.assertFalse(s.template_readiness()['ready'])
        os.environ['KILAS_BOT_INTERNAL_URL']='https://bot.example.test'
        self.assertFalse(s.template_readiness()['ready'])
        os.environ['INTERNAL_SERVICE_SECRET']='test-only-secret'
        result=s.template_readiness()
        self.assertTrue(result['ready'])
        self.assertNotIn('test-only-secret',str(result))

    def test_tenant_readiness_reuses_global_fallback_without_bridge(self):
        self.assertFalse(f.inbox_service.template_readiness(self.biz)['ready'])
        os.environ['WHATSAPP_REENGAGEMENT_TEMPLATE_NAME']='approved_test'
        result=f.inbox_service.template_readiness(self.biz)
        self.assertTrue(result['ready'])
        self.assertNotIn('secret-token',str(result))

    def test_bridge_failures_are_single_attempt_and_safe(self):
        s=f.platform_inbox_service
        failures=[Mock(status_code=429),Mock(status_code=403),Mock(status_code=502),
                  Mock(status_code=200,json=Mock(return_value=[])),
                  Mock(status_code=200,json=Mock(side_effect=ValueError())),
                  s.requests.exceptions.Timeout(),s.requests.exceptions.ConnectionError()]
        for failure in failures:
            with self.subTest(kind=type(failure).__name__):
                kwargs={'side_effect':failure} if isinstance(failure,Exception) else {'return_value':failure}
                with patch.object(s.requests,'post',**kwargs) as post:
                    ok,reason=s._post_to_bot_bridge('https://bot.example.test',{},'test-secret')
                self.assertFalse(ok); self.assertEqual(post.call_count,1)
                friendly=f.wa_inbox_shared.template_error_message(reason,platform=True)
                self.assertNotIn(reason,friendly)
                self.assertNotIn('test-secret',friendly)
        with patch.object(s.requests,'post',return_value=Mock(status_code=200,json=Mock(return_value={'status':'ok'}))) as post:
            self.assertEqual(s._post_to_bot_bridge('https://bot.example.test',{},'test-secret'),(True,'sent'))
            self.assertEqual(post.call_count,1)

    def test_unknown_upstream_reason_never_echoed(self):
        for platform in (True,False):
            text=f.wa_inbox_shared.template_error_message('private-response-credential',platform=platform)
            self.assertNotIn('private-response-credential',text)
            if not platform:
                self.assertNotIn('INTERNAL_SERVICE_SECRET',text)

    def test_shared_responsive_layout_and_media_includes(self):
        root=Path(__file__).resolve().parents[1]/'templates'
        css=(root/'_inbox_layout.html').read_text()
        for expected in ('@media(max-width:900px)', '.no-selection .kw-chat{display:none}',
            '.has-selection .kw-inbox-sidebar{display:none}',
            'grid-template-columns:minmax(260px,340px) minmax(0,1fr)',
            '.kw-conversations{overflow:auto', 'scrollTop=thread.scrollHeight',
            '.kw-back{display:inline-flex}'):
            self.assertIn(expected,css)
        for filename in ('inbox.html','platform_inbox.html'):
            template=(root/filename).read_text()
            self.assertIn("{% include '_inbox_layout.html' %}",template)
            self.assertIn("{% include '_inbox_media.html' %}",template)
            self.assertIn('accept="image/jpeg,image/png,application/pdf"',template)
            self.assertIn('name="csrf_token"',template)


if __name__=='__main__':
    unittest.main()
