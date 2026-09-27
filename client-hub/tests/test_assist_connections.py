"""Assisted mapping security and signed test evidence. No external network or real sends."""
import os
import unittest
from unittest.mock import patch,Mock
import test_client_hub_v1 as fixture
import assist_connections as flow
import assist_connection_transport as transport
import assist_journey
import tenant_config_service as routing

repo,db=fixture.repo,fixture.db

class ConnectionTests(unittest.TestCase):
    def setUp(self):
        fixture.reset_db()
        from public_chat import schema
        from kilas_core import customer_schema,job_schema,finance_bridge_schema
        schema.apply_schema();customer_schema.apply_schema();job_schema.apply_schema();finance_bridge_schema.apply_schema()
        self.uid=repo.create_user('owner@test.invalid','hash')
        self.aid=repo.create_user('admin@test.invalid','hash',role='KILAS_ADMIN')
        self.otheruid=repo.create_user('other@test.invalid','hash')
        self.bid=repo.create_business(self.uid,'Business One','AI_ADMIN')
        self.other=repo.create_business(self.otheruid,'Other Business','AI_ADMIN')
        self.admin={'id':self.aid,'role':'KILAS_ADMIN'}
        repo.upsert_business_profile(self.bid,dict(business_phone='628111111111'))
        repo.set_trusted_owner_phone(self.bid,'628222222222')
        self.journey=patch.object(assist_journey,'state',return_value=dict(paid=True,ready=True,onboarding_complete=True,connected=False))
        self.journey.start();self.addCleanup(self.journey.stop)
        import payment_service
        self.pay=patch.object(payment_service,'has_verified_ai_admin_payment',return_value=True)
        self.pay.start();self.addCleanup(self.pay.stop)
        flow.enqueue(self.bid,self.uid)

    def mapped(self):
        flow.set_stage(self.bid,self.admin,'Processing')
        flow.set_stage(self.bid,self.admin,'Waiting OTP')
        with patch.object(flow,'bridge',return_value={'display_phone_number':'628111111111'}):
            flow.sync_mapping(self.bid,self.admin,'123','456')
        return flow.start_inbound_test(self.bid,self.admin)

    def inbound(self,code,**kwargs):
        return flow.observe(kwargs.get('waba','123'),kwargs.get('pid','456'),{'messages':[{
            'id':kwargs.get('id','wamid.in'),'from':kwargs.get('phone','628222222222'),
            'type':'text','text':{'body':code}}]})

    def test_mapping_unique_and_cannot_activate_without_both_tests(self):
        self.mapped()
        self.assertEqual(repo.get_whatsapp_config(self.bid)['connection_status'],'PENDING_VALIDATION')
        with self.assertRaisesRegex(ValueError,'both_tests_required'):flow.activate(self.bid,self.admin)
        repo.upsert_whatsapp_config(self.other,'789','123','')
        with self.assertRaisesRegex(ValueError,'mapping_already_assigned'):
            flow.sync_mapping(self.bid,self.admin,'123','789')
        self.assertEqual(repo.get_whatsapp_config(self.bid)['phone_number_id'],'456')
        self.assertIsNone(routing.resolve_tenant_id_by_whatsapp_phone_number_id('456','123'))

    def test_inbound_exact_identity_owner_challenge_and_replay(self):
        code=self.mapped()
        self.assertFalse(self.inbound(code,waba='999'))
        self.inbound(code,phone='628333333333');self.inbound('Wrong code')
        self.assertIsNone(flow.get(self.bid)['inbound_at'])
        self.inbound(code)
        first=flow.get(self.bid)['inbound_event_id']
        self.inbound(code,id='replay.other')
        self.assertEqual(flow.get(self.bid)['inbound_event_id'],first)
        self.assertIsNone(flow.get(self.bid)['outbound_at'])
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kw_web_messages')['n'],0)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kw_core_jobs')['n'],0)

    def test_delivered_receipt_tied_to_same_mapping_and_provider_id(self):
        code=self.mapped();self.inbound(code)
        with patch.dict(os.environ,{'WHATSAPP_ACCESS_TOKEN':'synthetic-shared-token'}),patch.object(transport,'graph',return_value={'messages':[{'id':'wamid.out'}]}) as send:
            self.assertEqual(transport.outbound(self.bid)['delivery'],'sent')
            transport.outbound(self.bid);self.assertEqual(send.call_count,1)
            self.assertEqual(send.call_args.args[1],'456/messages')
            self.assertEqual(send.call_args.kwargs['json']['to'],'628222222222')
        def receipt(pid='wamid.out',waba='123'):
            flow.observe(waba,'456',{'statuses':[{'id':pid,'recipient_id':'628222222222','status':'delivered'}]})
        receipt('another-id');receipt(waba='999')
        self.assertIsNone(flow.get(self.bid)['outbound_at'])
        receipt();self.assertIsNotNone(flow.get(self.bid)['outbound_at'])
        # Activation must preserve knowledge and route only exact authoritative identity.
        repo.replace_business_faqs(self.bid,['Only business one knowledge'])
        before=repo.get_business_faqs(self.bid)
        import provisioning
        with patch.object(provisioning,'provision_tenant'),patch.object(provisioning,'_activate_tenant_core',side_effect=lambda bid,a:db.execute("UPDATE businesses SET status='ACTIVE' WHERE id=?",(bid,))):
            flow.activate(self.bid,self.admin)
        self.assertEqual(flow.get(self.bid)['state'],'Connected')
        self.assertEqual(repo.get_business_faqs(self.bid),before)
        self.assertEqual(routing.resolve_tenant_id_by_whatsapp_phone_number_id('456','123'),self.bid)
        self.assertIsNone(routing.resolve_tenant_id_by_whatsapp_phone_number_id('456','999'))
        self.assertEqual(repo.get_business_faqs(self.other),[])

    def test_mapping_change_invalidates_previous_tests_and_unknown_send_not_retried(self):
        code=self.mapped();self.inbound(code)
        with patch.dict(os.environ,{'WHATSAPP_ACCESS_TOKEN':'synthetic'}),patch.object(transport,'graph',side_effect=ValueError('network')) as send:
            with self.assertRaisesRegex(ValueError,'delivery_unknown'):transport.outbound(self.bid)
            self.assertEqual(transport.outbound(self.bid)['delivery'],'unknown')
            self.assertEqual(send.call_count,1)
        with patch.object(flow,'bridge',return_value={'display_phone_number':'628111111111'}):flow.sync_mapping(self.bid,self.admin,'123','457')
        self.assertIsNone(flow.get(self.bid)['inbound_at'])
        self.assertIsNone(flow.get(self.bid)['outbound_at'])
        with self.assertRaisesRegex(ValueError,'both_tests_required'):flow.activate(self.bid,self.admin)

    def test_owner_cannot_operate_admin_queue_or_read_technical_mapping(self):
        self.mapped()
        with self.assertRaises(PermissionError):flow.set_stage(self.bid,{'id':self.uid,'role':'CLIENT_OWNER'},'Waiting OTP')
        client=fixture.fresh_client()
        with client.session_transaction() as session:session.update(user_id=self.uid,role='CLIENT_OWNER',_csrf_token='test')
        self.assertEqual(client.get('/platform/').status_code,403)
        self.assertEqual(client.get(f'/platform/business/{self.bid}').status_code,403)
        self.assertEqual(client.get(f'/business/{self.other}/assist-whatsapp').status_code,404)
        page=client.get(f'/business/{self.bid}/assist-whatsapp')
        self.assertEqual(page.status_code,200)
        for value in ('WABA','Phone Number ID','credentials_reference','Graph','API token'):
            self.assertNotIn(value,page.text)
        self.assertEqual(client.post(f'/business/{self.bid}/whatsapp/embedded-signup',data={'csrf_token':'test'}).status_code,404)

    def test_knowledge_nested_write_does_not_commit_connection_transaction_early(self):
        with self.assertRaisesRegex(ValueError,'simulated_late_failure'):
            with flow.binding_lock():
                repo.upsert_business_profile(self.bid,dict(business_phone='628999999999'))
                db.execute("UPDATE kw_assist_connections SET state='Processing' WHERE business_id=?",(self.bid,))
                raise ValueError('simulated_late_failure')
        self.assertEqual(repo.get_business_profile(self.bid)['business_phone'],'628111111111')
        self.assertEqual(flow.get(self.bid)['state'],'Pending')

    def test_graph_membership_and_number_verification(self):
        flow.set_stage(self.bid,self.admin,'Processing')
        payload=dict(business_id=self.bid,waba_id='123',phone_number_id='456')
        with patch.dict(os.environ,{'WHATSAPP_ACCESS_TOKEN':'synthetic'}),patch.object(transport,'graph',return_value={'data':[{'id':'456','display_phone_number':'+62 8111111111'}]}) as graph:
            self.assertEqual(transport.verify(payload)['display_phone_number'],'628111111111')
            self.assertEqual(graph.call_args.args[1],'123/phone_numbers')
            graph.return_value={'data':[{'id':'789','display_phone_number':'628111111111'}]}
            with self.assertRaisesRegex(ValueError,'asset_not_in_waba'):transport.verify(payload)

if __name__=='__main__':unittest.main()
