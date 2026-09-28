"""Focused direct follow-up delivery regressions; no unrelated suite inheritance."""
import json
import time
import unittest
from unittest.mock import patch

import test_kilas_whatsapp as wa_fixture


class CustomerFollowUpSendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wa_fixture.WhatsAppTests.setUpClass.__func__(cls)
        global customers, followups, store
        from kilas_core import customers, customer_followups as followups
        from public_chat import store

    tearDown = wa_fixture.WhatsAppTests.tearDown
    setUp = wa_fixture.WhatsAppTests.setUp
    start = wa_fixture.WhatsAppTests.start
    send = wa_fixture.WhatsAppTests.send
    event = wa_fixture.WhatsAppTests.event
    receive = wa_fixture.WhatsAppTests.receive
    link = wa_fixture.WhatsAppTests.link

    def prepare(self, stage='CUSTOMER', bid=7):
        self.receive(confirmed=(stage == 'CUSTOMER'), bid=bid)
        link = self.link(bid)
        customer = customers.customer_for_conversation(bid, link['conversation_id'])
        if stage == 'LEAD':
            customer = customers.get_customer(bid, customer['id'])
            self.assertEqual(customer['stage'], 'LEAD')
        insight = {
            'summary': 'Kontak meminta informasi.',
            'interests': ['Kilas Assist'],
            'follow_up': 'Tanyakan apakah masih ingin melanjutkan.',
            '_provenance_version': 2,
        }
        now = int(time.time())
        self.db.execute(
            'INSERT INTO kw_core_customer_insights '
            '(business_id,customer_id,insight_json,core_message_cursor,demo_message_cursor,analyzed_message_count,updated_at) '
            'VALUES (?,?,?,?,?,?,?) ON CONFLICT(business_id,customer_id) DO UPDATE SET '
            'insight_json=excluded.insight_json,analyzed_message_count=excluded.analyzed_message_count,updated_at=excluded.updated_at',
            (bid, customer['id'], json.dumps(insight), 1, 0, 1, now))
        business = self.repo.get_business(bid)
        cached = __import__('kilas_core.customer_insights', fromlist=['cached']).cached(business, customer)
        context = followups.context(business, customer, cached)
        self.http.reset_mock()
        self.response.status_code = 200
        self.response.json.return_value = {'messages': [{'id': 'followup-provider'}]}
        return customer, link, context

    def post(self, customer, context, message='Halo, masih ingin melanjutkan?', bid=7):
        return self.client.post(
            f'/business/{bid}/customers/{customer["id"]}/follow-up',
            data={'csrf_token': 'csrf-test', 'operation_key': context['operation_key'], 'message': message},
            headers={'X-Requested-With': 'XMLHttpRequest'})

    def test_customer_followup_can_send(self):
        customer, link, context = self.prepare('CUSTOMER')
        page = self.client.get(f'/business/7/customers/{customer["id"]}')
        self.assertIn(b'Kirim Follow-up', page.data)
        response = self.post(customer, context)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json['message'], 'Follow-up terkirim')
        self.assertEqual(store.conversation(7, link['conversation_id'])['mode'], 'HUMAN_TAKEOVER')

    def test_lead_followup_can_send(self):
        customer, link, context = self.prepare('LEAD')
        response = self.post(customer, context)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json['conversation_id'], link['conversation_id'])
        self.assertEqual(customers.get_customer(7, customer['id'])['stage'], 'LEAD')

    def test_correct_customer_conversation_receives_followup(self):
        customer, link, context = self.prepare('CUSTOMER')
        other_link = wa_fixture.wa.ensure(7, '77777', '628999999999')
        self.post(customer, context, 'Pesan khusus customer pertama')
        self.assertEqual(self.http.call_args.kwargs['json']['to'], link['customer_phone'])
        self.assertFalse(any(row['content'] == 'Pesan khusus customer pertama'
                             for row in store.thread(7, other_link['conversation_id'])))

    def test_successful_outgoing_message_appears_in_inbox(self):
        customer, link, context = self.prepare('CUSTOMER')
        text = 'Follow-up yang sudah direview owner'
        self.assertEqual(self.post(customer, context, text).status_code, 200)
        payload = self.client.get(
            f'/business/7/web-inbox/{link["conversation_id"]}/messages?after=0').json
        sent = [row for row in payload['messages'] if row['content'] == text]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['role'], 'human')
        self.assertEqual(sent[0]['delivery_status'], 'accepted')

    def test_failed_delivery_is_not_shown_as_sent(self):
        customer, link, context = self.prepare('CUSTOMER')
        self.response.status_code = 400
        self.response.json.return_value = {'error': {'message': 'rejected'}}
        response = self.post(customer, context)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertFalse(response.json['ok'])
        payload = self.client.get(
            f'/business/7/web-inbox/{link["conversation_id"]}/messages?after=0').json
        outgoing = [row for row in payload['messages'] if row['role'] == 'human']
        self.assertEqual(outgoing[-1]['delivery_status'], 'failed')
        self.assertNotEqual(outgoing[-1]['delivery_status'], 'sent')

    def test_duplicate_click_or_retry_does_not_double_send(self):
        customer, _link, context = self.prepare('CUSTOMER')
        first = self.post(customer, context)
        second = self.post(customer, context)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.http.assert_called_once()

    def test_outside_window_uses_template_or_blocks_without_one(self):
        customer, link, context = self.prepare('CUSTOMER')
        with store.transaction() as tx:
            tx.execute('UPDATE kw_core_wa_conversations SET last_inbound_at=0 '
                       'WHERE business_id=? AND conversation_id=?', (7, link['conversation_id']))
        with patch.object(followups.inbox_service, 'template_readiness',
                          return_value={'ready': False, 'message': 'missing'}):
            blocked_context = followups.context(self.repo.get_business(7), customer,
                __import__('kilas_core.customer_insights', fromlist=['cached']).cached(self.repo.get_business(7), customer))
            blocked = self.post(customer, blocked_context)
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json['error'], 'approved_template_required')
        self.http.assert_not_called()

        refreshed = followups.context(self.repo.get_business(7), customer,
            __import__('kilas_core.customer_insights', fromlist=['cached']).cached(self.repo.get_business(7), customer))
        routed = self.post(customer, refreshed)
        self.assertEqual(routed.status_code, 200, routed.data)
        self.assertTrue(routed.json['template'])
        self.assertEqual(self.http.call_args.kwargs['json']['type'], 'template')

    def test_foreign_tenant_customer_cannot_be_targeted(self):
        foreign, _link, context = self.prepare('CUSTOMER', bid=8)
        response = self.client.post(
            f'/business/7/customers/{foreign["id"]}/follow-up',
            data={'csrf_token': 'csrf-test', 'operation_key': context['operation_key'],
                  'message': 'Tidak boleh terkirim'},
            headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(response.status_code, 404)
        self.http.assert_not_called()


if __name__ == '__main__':
    unittest.main()
