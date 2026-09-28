"""Focused direct follow-up delivery regressions; no unrelated suite inheritance."""
import hashlib
import json
import time
import unittest
import uuid
from unittest.mock import Mock, patch

import test_kilas_whatsapp as wa_fixture


class CustomerFollowUpSendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wa_fixture.WhatsAppTests.setUpClass.__func__(cls)
        global customers, followups, insights, store
        from kilas_core import customers, customer_followups as followups, customer_insights as insights
        from public_chat import store

    tearDown = wa_fixture.WhatsAppTests.tearDown
    start = wa_fixture.WhatsAppTests.start
    send = wa_fixture.WhatsAppTests.send
    event = wa_fixture.WhatsAppTests.event
    receive = wa_fixture.WhatsAppTests.receive
    link = wa_fixture.WhatsAppTests.link

    def setUp(self):
        wa_fixture.WhatsAppTests.setUp(self)
        self.db.execute(
            'CREATE TABLE IF NOT EXISTS platform_wa_conversation_state('
            'id INTEGER PRIMARY KEY AUTOINCREMENT,customer_phone TEXT NOT NULL UNIQUE,'
            'mode TEXT NOT NULL,updated_by_user_id INTEGER,updated_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        for table in ('platform_workspace_outbound', 'kw_assist_demo_events',
                      'kw_assist_demo_sessions', 'platform_wa_conversation_state'):
            try:
                self.db.execute('DELETE FROM ' + table)
            except Exception:
                pass

    def _insight(self, customer, bid=7, *, payment=False):
        insight = {
            'summary': 'Customer ingin melanjutkan pembayaran.' if payment else 'Kontak meminta informasi.',
            'interests': ['Kilas Assist'],
            'follow_up': 'Tanyakan detail lanjutan berdasarkan percakapan.',
            '_action_evidence': 'Saya mau bayar 1 juta' if payment else '',
            '_payment_evidence': 'Saya mau bayar 1 juta' if payment else '',
            'action': 'Bayar 1 juta' if payment else None,
            '_provenance_version': 2,
        }
        now = int(time.time())
        self.db.execute(
            'INSERT INTO kw_core_customer_insights '
            '(business_id,customer_id,insight_json,core_message_cursor,demo_message_cursor,analyzed_message_count,updated_at) '
            'VALUES (?,?,?,?,?,?,?) ON CONFLICT(business_id,customer_id) DO UPDATE SET '
            'insight_json=excluded.insight_json,core_message_cursor=excluded.core_message_cursor,'
            'demo_message_cursor=excluded.demo_message_cursor,analyzed_message_count=excluded.analyzed_message_count,'
            'updated_at=excluded.updated_at',
            (bid, customer['id'], json.dumps(insight), 1, 1, 1, now))
        return insights.cached(self.repo.get_business(bid), customer)

    def prepare_core(self, stage='CUSTOMER', bid=7, *, payment=False):
        self.receive(confirmed=(stage == 'CUSTOMER'), bid=bid)
        link = self.link(bid)
        customer = customers.customer_for_conversation(bid, link['conversation_id'])
        customer = customers.get_customer(bid, customer['id'])
        if payment:
            customers.update_customer(bid, customer['id'], display_name='Irvan',
                                      phone=customer.get('phone'), email=customer.get('email'),
                                      notes=customer.get('notes'), stage=customer['stage'],
                                      actor_id=1 if bid == 7 else 2)
            customer = customers.get_customer(bid, customer['id'])
        cached = self._insight(customer, bid, payment=payment)
        with patch.object(followups.whatsapp_access, 'selected', return_value=False):
            context = followups.context(self.repo.get_business(bid), customer, cached)
        self.http.reset_mock()
        self.response.status_code = 200
        self.response.json.return_value = {'messages': [{'id': 'followup-provider'}]}
        return customer, link, context

    def prepare_demo(self, bid=7, phone='628777000001'):
        customer = customers.ensure_whatsapp_lead(bid, phone, display_name='Irvan')
        customers.update_customer(bid, customer['id'], display_name='Irvan', phone=phone,
                                  email=None, notes=None, stage='CUSTOMER', actor_id=1)
        customer = customers.get_customer(bid, customer['id'])
        message_id = self.db.execute(
            "INSERT INTO messages(number,mode,role,content,created_at) "
            "VALUES (?,'customer','user','Saya mau bayar 1 juta',CURRENT_TIMESTAMP)",
            (phone,)).lastrowid
        session_id = uuid.uuid4().hex
        now = int(time.time())
        self.db.execute(
            'INSERT INTO kw_assist_demo_sessions'
            '(id,business_id,actor_id,token_hash,created_at,expires_at,sender_phone,active) '
            'VALUES (?,?,?,?,?,?,?,TRUE)',
            (session_id, bid, 1, hashlib.sha256(session_id.encode()).hexdigest(), now, now + 86400, phone))
        self.db.execute(
            'INSERT INTO kw_assist_demo_events'
            '(provider_id,session_id,business_id,payload_hash,inbound_message_id,status,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?)',
            ('demo-in-' + session_id, session_id, bid, 'hash', message_id, 'received', now, now))
        cached = self._insight(customer, bid, payment=True)
        context = followups.context(self.repo.get_business(bid), customer, cached)
        return customer, context, session_id

    def prepare_legacy(self, bid=7, phone='628777000002'):
        customer = customers.ensure_whatsapp_lead(bid, phone, display_name='Legacy Customer')
        customers.update_customer(bid, customer['id'], display_name='Legacy Customer', phone=phone,
                                  email=None, notes=None, stage='CUSTOMER', actor_id=1)
        customer = customers.get_customer(bid, customer['id'])
        self.db.execute(
            "INSERT INTO messages(number,mode,role,content,created_at) "
            "VALUES (?,'customer','user','Saya ingin lanjut',CURRENT_TIMESTAMP)",
            (f'T{bid}:{phone}',))
        cached = self._insight(customer, bid)
        with patch.object(followups.whatsapp_access, 'selected', return_value=False):
            context = followups.context(self.repo.get_business(bid), customer, cached)
        return customer, context, phone

    def post(self, customer, context, message='Halo, masih ingin melanjutkan?', bid=7):
        return self.client.post(
            f'/business/{bid}/customers/{customer["id"]}/follow-up',
            data={'csrf_token': 'csrf-test', 'operation_key': context['operation_key'], 'message': message},
            headers={'X-Requested-With': 'XMLHttpRequest'})

    def test_core_whatsapp_customer_direct_send_and_contextual_draft(self):
        customer, link, context = self.prepare_core(payment=True)
        page = self.client.get(f'/business/7/customers/{customer["id"]}')
        self.assertIn(b'Follow-up Customer', page.data)
        self.assertIn(b'Kirim WhatsApp', page.data)
        self.assertIn('Halo Irvan, terkait pembayaran Rp1 juta'.encode(), page.data)
        response = self.post(customer, context)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json['message'], 'Pesan follow-up berhasil dikirim')
        self.assertEqual(response.json['source'], 'core')
        self.assertEqual(store.conversation(7, link['conversation_id'])['mode'], 'HUMAN_TAKEOVER')

    def test_demo_whatsapp_customer_direct_send(self):
        customer, context, session_id = self.prepare_demo()
        self.assertEqual(context['source'], 'demo')
        def deliver(phone, text, demo_scope=None):
            bound = followups.assist_demo.require_outgoing_scope(demo_scope, phone)
            followups.assist_demo.record_sent(bound, text)
            return True, 'sent'
        with patch.object(followups.platform_inbox_service, 'send_manual_reply',
                          side_effect=deliver) as send:
            response = self.post(customer, context, 'Pesan demo yang direview')
        self.assertEqual(response.status_code, 200, response.data)
        send.assert_called_once_with('628777000001', 'Pesan demo yang direview',
                                     demo_scope={'business_id': 7, 'session_id': session_id})
        thread = followups.assist_demo.rows(7, '628777000001')
        self.assertEqual(thread[-1]['content'], 'Pesan demo yang direview')
        self.assertEqual(thread[-1]['role'], 'assistant')

    def test_legacy_whatsapp_customer_direct_send(self):
        response = Mock(status_code=200)
        customer, context, phone = self.prepare_legacy()
        self.assertEqual(context['source'], 'legacy')
        def takeover(bid, target_phone, actor):
            self.db.execute(
                "INSERT INTO wa_conversation_state(business_id,customer_phone,mode,updated_by_user_id) "
                "VALUES (?,?, 'HUMAN_TAKEOVER',?) ON CONFLICT(business_id,customer_phone) "
                "DO UPDATE SET mode='HUMAN_TAKEOVER',updated_by_user_id=excluded.updated_by_user_id",
                (bid, target_phone, actor))
        with patch.object(followups.whatsapp_access, 'selected', return_value=False), \
             patch.object(followups.wa_takeover_service, 'start_human_takeover', side_effect=takeover), \
             patch.object(followups.inbox_service.requests, 'post', return_value=response) as send:
            result = self.post(customer, context, 'Pesan legacy yang direview')
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(send.call_args.kwargs['json']['to'], phone)
        thread = followups.inbox_service.get_thread(7, phone)
        self.assertEqual(thread[-1]['content'], 'Pesan legacy yang direview')
        self.assertEqual(thread[-1]['role'], 'assistant')

    def test_correct_business_customer_and_channel_receive_message(self):
        customer, link, context = self.prepare_core()
        other_link = wa_fixture.wa.ensure(7, '77777', '628999999999')
        self.post(customer, context, 'Pesan khusus customer pertama')
        self.assertEqual(self.http.call_args.kwargs['json']['to'], link['customer_phone'])
        self.assertFalse(any(row['content'] == 'Pesan khusus customer pertama'
                             for row in store.thread(7, other_link['conversation_id'])))

    def test_successful_outgoing_message_appears_in_existing_inbox(self):
        customer, link, context = self.prepare_core()
        text = 'Follow-up yang sudah direview owner'
        self.assertEqual(self.post(customer, context, text).status_code, 200)
        payload = self.client.get(
            f'/business/7/web-inbox/{link["conversation_id"]}/messages?after=0').json
        sent = [row for row in payload['messages'] if row['content'] == text]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['role'], 'human')
        self.assertEqual(sent[0]['delivery_status'], 'accepted')

    def test_failed_delivery_is_not_marked_sent(self):
        customer, link, context = self.prepare_core()
        self.response.status_code = 400
        self.response.json.return_value = {'error': {'message': 'rejected'}}
        response = self.post(customer, context)
        self.assertEqual(response.status_code, 409, response.data)
        payload = self.client.get(
            f'/business/7/web-inbox/{link["conversation_id"]}/messages?after=0').json
        outgoing = [row for row in payload['messages'] if row['role'] == 'human']
        self.assertEqual(outgoing[-1]['delivery_status'], 'failed')
        self.assertNotEqual(outgoing[-1]['delivery_status'], 'sent')

    def test_duplicate_demo_retry_does_not_double_send(self):
        customer, context, _session_id = self.prepare_demo()
        with patch.object(followups.platform_inbox_service, 'send_manual_reply',
                          return_value=(True, 'sent')) as send:
            first = self.post(customer, context)
            second = self.post(customer, context)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        send.assert_called_once()

    def test_outside_window_uses_template_or_blocks_without_one(self):
        customer, link, context = self.prepare_core()
        with store.transaction() as tx:
            tx.execute('UPDATE kw_core_wa_conversations SET last_inbound_at=0 '
                       'WHERE business_id=? AND conversation_id=?', (7, link['conversation_id']))
        with patch.object(followups.inbox_service, 'template_readiness',
                          return_value={'ready': False, 'message': 'missing'}):
            blocked_context = followups.context(self.repo.get_business(7), customer,
                                                insights.cached(self.repo.get_business(7), customer))
            blocked = self.post(customer, blocked_context)
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json['error'], 'approved_template_required')
        self.http.assert_not_called()

        refreshed = followups.context(self.repo.get_business(7), customer,
                                      insights.cached(self.repo.get_business(7), customer))
        routed = self.post(customer, refreshed)
        self.assertEqual(routed.status_code, 200, routed.data)
        self.assertTrue(routed.json['template'])
        self.assertEqual(self.http.call_args.kwargs['json']['type'], 'template')

    def test_foreign_tenant_customer_cannot_be_targeted(self):
        foreign, _link, context = self.prepare_core(bid=8)
        response = self.client.post(
            f'/business/7/customers/{foreign["id"]}/follow-up',
            data={'csrf_token': 'csrf-test', 'operation_key': context['operation_key'],
                  'message': 'Tidak boleh terkirim'},
            headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(response.status_code, 404)
        self.http.assert_not_called()


if __name__ == '__main__':
    unittest.main()
