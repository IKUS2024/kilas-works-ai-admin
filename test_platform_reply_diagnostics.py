"""Focused manual bridge status provenance and persistent platform mode checks."""
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch, Mock
import test_platform_takeover as fixture

bot = fixture.appmod
service = fixture.platform_inbox_service

class ManualBridgeTests(unittest.TestCase):
    def setUp(self):
        fixture.reset_state()
        self.phone = '628700111010'

    def bridge(self, result):
        with patch.object(bot, 'INTERNAL_SERVICE_SECRET', 'test-only'), patch.object(bot, '_CLIENT_HUB_AVAILABLE', True), patch.object(service, 'customer_exists', return_value=True), patch.object(service, 'get_state', return_value='HUMAN_TAKEOVER'), patch.object(service, 'freeform_window_status', return_value={'allowed': True}), patch.object(bot, 'send_whatsapp_message', return_value=result), patch.object(bot, 'save_message_to_db'), patch.object(bot, 'load_recent_messages_from_db', return_value=[]):
            return fixture.client.post('/internal/platform-cs-reply', json={'customer_phone':self.phone,'message':'test'}, headers={'X-Internal-Service-Secret':'test-only'})

    def test_manual_reply_success(self):
        service.start_human_takeover(self.phone)
        response = self.bridge((True, None))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'status':'ok'})

    def test_meta_429_is_bridge_502_with_safe_code(self):
        response = self.bridge((False, 'meta_http_429_code_130429'))
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json['reason'], 'meta_http_429_code_130429')

    def test_unsafe_error_is_redacted(self):
        self.assertEqual(self.bridge((False, 'private provider payload')).json['reason'], 'whatsapp_send_failed')

    def test_upstream_429_is_not_reported_as_meta(self):
        response = Mock(status_code=429)
        response.json.return_value={'reason':'private provider payload'}
        output=io.StringIO()
        with patch.object(service, 'customer_exists', return_value=True), patch.object(service, 'get_state', return_value='HUMAN_TAKEOVER'), patch.object(service, 'freeform_window_status', return_value={'allowed':True}), patch.object(service, '_bot_platform_reply_url', return_value='https://example.invalid/internal/platform-cs-reply'), patch.dict(service.os.environ, {'INTERNAL_SERVICE_SECRET':'test-only'}), patch.object(service.requests, 'post', return_value=response), redirect_stdout(output):
            ok, reason=service.send_manual_reply(self.phone, 'private message')
        self.assertFalse(ok)
        self.assertEqual(reason, 'bot_internal_bridge_http_429:unclassified_bridge_response')
        self.assertNotIn('private',output.getvalue())

    def test_existing_human_mode_has_no_expiry_and_is_scoped(self):
        service.start_human_takeover(self.phone)
        fixture.chdb.execute("UPDATE platform_wa_conversation_state SET updated_at = '2000-01-01 00:00:00' WHERE customer_phone = ?", (self.phone,))
        self.assertEqual(service.get_state(self.phone), 'HUMAN_TAKEOVER')
        self.assertEqual(bot._get_conversation_mode_safe(None,self.phone), 'HUMAN_TAKEOVER')
        self.assertEqual(service.get_state('628700111011'), 'AI_ACTIVE')
        with patch.object(bot._tcs, 'get_conversation_mode', return_value='AI_ACTIVE') as tenant:
            self.assertEqual(bot._get_conversation_mode_safe(101,self.phone),'AI_ACTIVE')
            tenant.assert_called_once_with(101,self.phone)
        service.return_to_ai(self.phone)
        self.assertEqual(service.get_state(self.phone),'AI_ACTIVE')

if __name__ == '__main__':
    unittest.main()
