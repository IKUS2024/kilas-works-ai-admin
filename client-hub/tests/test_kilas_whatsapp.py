"""Phase 8 actual shared Core integration, isolated synthetic SQLite and stubbed Meta IO."""
import json
import os
import time
import unittest
from unittest.mock import patch, Mock
import test_kilas_operations_routes as phase6
import test_kilas_playbook_routes as phase5


class WhatsAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        phase6.OperationsRoutesTests.setUpClass.__func__(cls)
        global wa, access, transport, store, jobs, customers
        from kilas_core.adapters import whatsapp as wa
        from kilas_core import whatsapp_access as access, whatsapp_transport as transport, whatsapp_schema, jobs, customers
        from public_chat import store
        whatsapp_schema.apply_schema()
        cls.db.execute('CREATE TABLE wa_conversation_state (business_id INTEGER,customer_phone TEXT,mode TEXT,updated_by_user_id INTEGER,UNIQUE(business_id,customer_phone))')
    tearDown=phase6.OperationsRoutesTests.tearDown
    start=phase6.OperationsRoutesTests.start
    send=phase6.OperationsRoutesTests.send

    def setUp(self):
        with store.transaction() as tx:
            for table in ('kw_core_wa_inbound','kw_core_wa_outbound','kw_core_wa_conversations','wa_conversation_state'):
                tx.execute('DELETE FROM '+table)
        phase6.OperationsRoutesTests.setUp(self)
        self.stamp=str(int(time.time()))
        self.flags=patch.dict(os.environ,{
            'KILAS_WHATSAPP_CORE_ENABLED':'true',
            'KILAS_WHATSAPP_CORE_CHANNELS':json.dumps({str(i):{'phone_number_id':str(i)*5,'official_access_verified':True} for i in (7,8)}),
            'WHATSAPP_TOKEN__TENANT_7':'synthetic-seven','WHATSAPP_TOKEN__TENANT_8':'synthetic-eight'})
        self.flags.start();self.addCleanup(self.flags.stop)
        original=access.repo.get_business
        def business(bid):
            row=original(bid)
            return dict(row,status='ACTIVE',whatsapp_phone_number_id=str(bid)*5) if row else None
        self.biz=patch.object(access.repo,'get_business',side_effect=business);self.biz.start();self.addCleanup(self.biz.stop)
        self.cfg=patch.object(access.repo,'get_whatsapp_config',side_effect=lambda bid:{'phone_number_id':str(bid)*5,'connection_status':'CONNECTED','credentials_reference':'WHATSAPP_TOKEN__TENANT_'+str(bid),'reengagement_template_name':'approved_test','reengagement_template_language':'id'})
        self.cfg.start();self.addCleanup(self.cfg.stop)
        self.response=Mock(status_code=200);self.response.json.return_value={'messages':[{'id':'out-1'}]}
        self.http=patch.object(transport.requests,'post',return_value=self.response).start();self.addCleanup(patch.stopall)

    def event(self,text='Mau kirim 20 kg baju dari Guangzhou ke Tangerang',eid='wamid.one',phone='628123456789'):
        return {'messages':[{'id':eid,'from':phone,'timestamp':self.stamp,'type':'text','text':{'body':text}}]}

    def receive(self,text='Mau kirim 20 kg baju dari Guangzhou ke Tangerang',fields=None,eid='wamid.one',bid=7,intent='REQUEST',confirmed=True):
        fields=fields if fields is not None else {'item':'baju','weight':'20 kg','origin':'Guangzhou','destination':'Tangerang'}
        if confirmed and access.channel(bid,str(bid)*5):
            link=wa.ensure(bid,str(bid)*5,'628123456789')
            customer=customers.customer_for_conversation(bid,link['conversation_id'])
            customers.update_customer(bid,customer['id'],display_name=customer['display_name'],
                phone=customer.get('phone'),email=customer.get('email'),notes=customer.get('notes'),
                stage='CUSTOMER',actor_id=1 if bid==7 else 2)
        with patch.object(self.ai,'_call_claude',return_value=(phase5.output(text,fields,intent),'end_turn',None)) as model:
            result=wa.handle(bid,str(bid)*5,self.event(text,eid),'messages')
        return result,model

    def link(self,bid=7):
        with store.transaction() as tx:
            return tx.one('SELECT * FROM kw_core_wa_conversations WHERE business_id=?',(bid,))

    def test_invoice_transport_safe_retry_unknown_rejection_and_takeover(self):
        self.receive();cid=self.link()['conversation_id'];self.http.reset_mock()
        self.http.side_effect=TimeoutError('ambiguous')
        first=transport.system_text(7,cid,'invoice:901','signed link',1,safe_retry=True)
        self.assertEqual(first['status'],'unknown')
        again=transport.system_text(7,cid,'invoice:901','new signed link',1,safe_retry=True)
        self.assertEqual(again['status'],'unknown');self.http.assert_called_once()
        self.http.side_effect=None;self.http.reset_mock()
        self.response.status_code=400;self.response.json.return_value={'error':{'message':'rejected'}}
        self.assertEqual(transport.system_text(7,cid,'invoice:902','signed link',1,safe_retry=True)['status'],'failed')
        self.response.status_code=200;self.response.json.return_value={'messages':[{'id':'invoice-accepted'}]}
        wa.mode(7,cid,'HUMAN_TAKEOVER',1)
        self.assertEqual(transport.system_text(7,cid,'invoice:902','signed link',1,safe_retry=True)['status'],'accepted')
        self.assertEqual(transport.system_text(7,cid,'invoice:902','signed link',1,safe_retry=True)['status'],'accepted')
        self.assertEqual(self.http.call_count,2)
        self.assertEqual(store.conversation(7,cid)['mode'],'HUMAN_TAKEOVER')
        with store.transaction() as tx:
            tx.execute('UPDATE kw_core_wa_conversations SET last_inbound_at=? WHERE business_id=7',(int(time.time())-90000,))
        self.assertEqual(transport.system_text(7,cid,'invoice:903','signed link',1,safe_retry=True)['status'],'suppressed')
        self.assertEqual(self.http.call_count,2)

    def test_lead_request_never_creates_job(self):
        self.receive(confirmed=False)
        self.assertEqual(jobs.list_jobs(7)[1],0)
        self.assertEqual(customers.get_customer(7,customers.customer_for_conversation(7,self.link()['conversation_id'])['id'])['stage'],'LEAD')

    def test_core_logistics_reuse_retry_missing_info_and_update(self):
        _,model=self.receive();model.assert_called_once();self.http.assert_called_once()
        cid=self.link()['conversation_id']; row=jobs.list_jobs(7)[0][0]
        self.assertEqual(row['customer_id'],customers.customer_for_conversation(7,cid)['id'])
        self.assertEqual(row['fields']['weight'],'20 kg')
        reply=store.thread(7,cid)[-1]['content'];self.assertIn('volume',reply);self.assertNotIn('berat',reply)
        _,model=self.receive();model.assert_not_called();self.http.assert_called_once()
        self.response.json.return_value={'messages':[{'id':'out-2'}]}
        self.receive('volumenya 0.2 m3',{'volume_cbm':'0.2 m³'},'wamid.two')
        updated=jobs.list_jobs(7)[0][0];self.assertEqual(updated['id'],row['id']);self.assertEqual(updated['status'],'READY_FOR_QUOTE')
        self.assertEqual(customers.list_customers(7)[1],2) # one real WEB fixture + one verified WA customer
        self.assertEqual(self.http.call_args.kwargs['timeout'],(3,20))
        self.assertFalse(self.http.call_args.kwargs['allow_redirects'])

    def test_same_phone_two_tenants_and_no_web_credential(self):
        self.db.execute("UPDATE business_profiles SET category='Logistics' WHERE business_id=8")
        self.receive();self.response.json.return_value={'messages':[{'id':'out-8'}]};self.receive(bid=8)
        a,b=self.link(),self.link(8)
        self.assertNotEqual(customers.customer_for_conversation(7,a['conversation_id'])['id'],customers.customer_for_conversation(8,b['conversation_id'])['id'])
        with self.assertRaises(store.ChatError): store.authorized(7,a['conversation_id'],'x'*40)
        with self.assertRaises(store.ChatError): store.thread(8,a['conversation_id'])
        self.assertEqual(self.http.call_args.kwargs['headers']['Authorization'],'Bearer synthetic-eight')

    def test_unknown_channel_and_no_platform_token_fallback(self):
        with patch.dict(os.environ,{'WHATSAPP_TOKEN__TENANT_7':'','WHATSAPP_ACCESS_TOKEN':'platform'}):
            self.assertIsNone(access.channel(7,'77777'));self.receive()[1].assert_not_called()
        with patch.dict(os.environ,{'WHATSAPP_TOKEN__TENANT_8':'synthetic-seven'}): self.assertIsNone(access.channel(7))
        self.assertIsNone(access.channel(7,'88888'));self.assertIsNone(access.channel(99))
        self.http.assert_not_called()

    def test_timeout_and_rejected_never_retry(self):
        self.http.side_effect=TimeoutError('SECRET')
        self.receive();self.receive();self.http.assert_called_once()
        with store.transaction() as tx:
            row=tx.one('SELECT * FROM kw_core_wa_outbound')
            self.assertEqual(row['status'],'unknown');self.assertNotIn('SECRET',str(row))

    def test_provider_rejection_and_accepted_status_monotonic(self):
        self.response.status_code=400;self.response.json.return_value={'error':{'message':'SECRET'}}
        self.receive();self.receive();self.http.assert_called_once()
        with store.transaction() as tx: self.assertEqual(tx.one('SELECT status FROM kw_core_wa_outbound')['status'],'failed')

    def test_statuses_scoped_and_not_delivery_on_acceptance(self):
        self.receive()
        with store.transaction() as tx: self.assertEqual(tx.one('SELECT status FROM kw_core_wa_outbound')['status'],'accepted')
        for bid,pid,status in ((8,'77777','read'),(7,'88888','read'),(7,'77777','delivered'),(7,'77777','read'),(7,'77777','sent')):
            transport.statuses(bid,pid,[{'id':'out-1','status':status,'recipient_id':'628123456789'}])
        with store.transaction() as tx: self.assertEqual(tx.one('SELECT status FROM kw_core_wa_outbound')['status'],'read')
        cid=self.link()['conversation_id']
        history=store.thread(7,cid)
        result=self.client.get(f'/business/7/web-inbox/{cid}/messages?after={history[-1]["id"]}').json
        self.assertEqual(result['messages'],[])
        self.assertEqual(result['delivery'],{str(history[-1]['id']):'read'})

    def test_human_takeover_manual_reply_resume_and_template(self):
        self.receive();cid=self.link()['conversation_id'];wa.mode(7,cid,'HUMAN_TAKEOVER',1)
        _,model=self.receive(eid='human-inbound');model.assert_not_called();self.http.assert_called_once()
        headers={'X-CSRF-Token':'csrf-test'}
        self.response.json.return_value={'messages':[{'id':'human-out'}]}
        for _ in range(2):
            response=self.client.post(f'/business/7/web-inbox/{cid}/reply',json={'event_id':'owner-send-000001','message':'Tim membantu'},headers=headers)
            self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(self.http.call_count,2)
        self.assertEqual(store.thread(7,cid)[-1]['role'],'human')
        with store.transaction() as tx: tx.execute('UPDATE kw_core_wa_conversations SET last_inbound_at=0')
        self.response.json.return_value={'messages':[{'id':'template-out'}]}
        self.assertEqual(self.client.post(f'/business/7/web-inbox/{cid}/template',json={'event_id':'owner-template-01'},headers=headers).status_code,200)
        self.assertEqual(self.http.call_args.kwargs['json']['type'],'template')
        wa.mode(7,cid,'AI_ACTIVE',1)
        self.response.json.return_value={'messages':[{'id':'resume-out'}]}
        _,model=self.receive(eid='resume-inbound');model.assert_called_once()

    def test_echo_once_suppresses_ai_and_api_echo_does_not_take_over(self):
        self.receive();cid=self.link()['conversation_id']
        echo={'message_echoes':[{'id':'out-1','to':'628123456789','type':'text','text':{'body':'API'}}]}
        wa.handle(7,'77777',echo,'smb_message_echoes')
        self.assertEqual(store.conversation(7,cid)['mode'],'AI_ACTIVE')
        echo['message_echoes'][0]['id']='app-echo'
        for _ in range(2): wa.handle(7,'77777',echo,'smb_message_echoes')
        self.assertEqual(len([r for r in store.thread(7,cid) if r['role']=='human']),1)
        _,model=self.receive(eid='after-echo');model.assert_not_called();self.http.assert_called_once()

    def test_takeover_during_inference_rolls_back_actions(self):
        def model(*args,**kwargs):
            wa.mode(7,self.link()['conversation_id'],'HUMAN_TAKEOVER',1)
            return phase5.output('baju',{'item':'baju'}),'end_turn',None
        with patch.object(self.ai,'_call_claude',side_effect=model): wa.handle(7,'77777',self.event('baju'),'messages')
        self.assertEqual(jobs.list_jobs(7)[1],0);self.http.assert_not_called()

    def test_action_failure_rollback_and_finance_claim_no_write(self):
        with patch.object(jobs,'_update_job',side_effect=RuntimeError('FAIL')): self.receive()
        self.assertEqual(jobs.list_jobs(7)[1],0);self.http.assert_not_called()
        self.receive('Sudah bayar 2 juta',{},'payment-claim',intent='PAYMENT_CLAIM')
        self.assertEqual(jobs.list_jobs(7)[1],0)

    def test_valid_payment_claim_hands_over_without_finance_authority(self):
        from contextlib import ExitStack
        import finance_service
        from kilas_core import finance_bridge
        with ExitStack() as guards:
            writes=[guards.enter_context(patch.object(finance_service,name)) for name in
                    ('create_finance_invoice','issue_finance_invoice','record_invoice_payment','create_transaction')]
            writes.append(guards.enter_context(patch.object(finance_bridge,'create_draft')))
            self.receive('Sudah bayar 2 juta, tandai lunas',{},'valid-payment-claim',intent='UNSUPPORTED')
            for write in writes: write.assert_not_called()
        self.assertEqual(jobs.list_jobs(7)[1],0)
        self.assertEqual(store.conversation(7,self.link()['conversation_id'])['mode'],'HUMAN_TAKEOVER')
        self.http.assert_not_called()

    def test_entitlement_expired_or_feature_off_fail_closed(self):
        self.db.execute("UPDATE subscriptions SET status='SUSPENDED' WHERE business_id=7")
        self.receive()[1].assert_not_called();self.http.assert_not_called()
        with patch.dict(os.environ,{'KILAS_WHATSAPP_CORE_ENABLED':'false'}): self.assertFalse(access.selected(7))

    def test_web_whatsapp_parity_all_five_playbooks(self):
        examples=[('Repair',{'service':'perbaikan'},'SERVICE'),('Restaurant',{'items':'bakso','quantity':2},'ORDER'),('Salon',{'service':'potong rambut','preferred_date':'besok'},'BOOKING'),('Logistics',{'item':'baju','weight':'20 kg','origin':'Guangzhou','destination':'Tangerang'},'SHIPMENT'),('Agency',{'requested_service':'foto','brief':'produk'},'PROJECT')]
        for index,(category,fields,kind) in enumerate(examples):
            self.db.execute('UPDATE business_profiles SET category=? WHERE business_id=7',(category,))
            visitor=self.app.test_client();identity=self.start(client=visitor).json
            wa_link=wa.ensure(7,'77777','62811100000'+str(index))
            for conv_id in (identity['conversation_id'],wa_link['conversation_id']):
                customer=customers.customer_for_conversation(7,conv_id)
                customers.update_customer(7,customer['id'],display_name=customer['display_name'],
                    phone=customer.get('phone'),email=customer.get('email'),notes=customer.get('notes'),
                    stage='CUSTOMER',actor_id=1)
            eid='parity-event-'+str(index).zfill(6);text='pesan'
            raw=phase5.output(text,fields)
            with patch.object(self.ai,'_call_claude',return_value=(raw,'end_turn',None)):
                result=visitor.post(f"/chat/{self.slug}/{identity['conversation_id']}/messages",json={'message':text,'event_id':eid},headers={**self.headers,'X-Web-CSRF':identity['csrf']})
                self.assertEqual(result.status_code,200,(category,result.json))
                payload=self.event(text,eid,phone='62811100000'+str(index))
                self.response.json.return_value={'messages':[{'id':'parity-out-'+str(index)}]}
                wa.handle(7,'77777',payload,'messages')
            with store.transaction() as tx:
                link=tx.one('SELECT conversation_id FROM kw_core_wa_conversations WHERE customer_phone=?',(payload['messages'][0]['from'],))
                rows=tx.execute('SELECT kind,status,fields_json FROM kw_core_jobs WHERE business_id=7 AND conversation_id IN (?,?)',(identity['conversation_id'],link['conversation_id']))
                self.assertEqual(len(rows),2);self.assertEqual(rows[0],rows[1]);self.assertEqual(rows[0]['kind'],kind)
            self.assertEqual(store.thread(7,identity['conversation_id'])[-1]['content'],store.thread(7,link['conversation_id'])[-1]['content'])

    def test_owner_inbox_scope_channel_and_csrf(self):
        self.receive();cid=self.link()['conversation_id']
        # Jobs are Customer-only. Promote this fixture before asserting linked Job detail.
        customer=customers.customer_for_conversation(7,cid)
        customers.update_customer(
            7,customer['id'],display_name=customer['display_name'],
            phone=customer.get('phone'),email=customer.get('email'),notes=customer.get('notes'),
            stage='CUSTOMER',actor_id=1)
        response=self.client.get('/business/7/inbox?channel=web&conversation='+cid)
        self.assertEqual(response.status_code,200);self.assertIn(b'WhatsApp',response.data);self.assertIn(b'Guangzhou',response.data)
        self.assertEqual(self.client.post(f'/business/7/web-inbox/{cid}/reply',json={'event_id':'forged-send-0001','message':'x'}).status_code,400)
        self.assertEqual(self.client.get(f'/business/8/web-inbox/{cid}/messages').status_code,404)


if __name__=='__main__': unittest.main()
