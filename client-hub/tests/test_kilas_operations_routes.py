"""Real owner/visitor routes, separate owners and synthetic database only."""
import os
import unittest
from unittest.mock import patch
import test_kilas_playbook_routes as phase5


class OperationsRoutesTests(unittest.TestCase):
    def test_invalid_interpretation_handover_is_bounded_atomic_and_tenant_scoped(self):
        phase5.PlaybookRoutesTests.creative_config(self)
        with self.assertLogs('kilas_core.conversation',level='WARNING') as logs:
            result, model = self.deliver(raw='{"action":"write_finance","secret":"DO_NOT_LOG"}')
        self.assertEqual(result.status_code,200)
        self.assertEqual(model.call_count,2)
        self.assertNotIn('DO_NOT_LOG',' '.join(logs.output))
        self.assertEqual(jobs.list_jobs(7)[1],0)
        self.assertEqual(store.conversation(7,self.cid)['mode'],'HUMAN_TAKEOVER')
        self.assertEqual(attention.listing(7)['total'],1)
        self.assertEqual(attention.listing(8)['total'],0)
        result,model=self.deliver(event='after-invalid-human')
        model.assert_not_called()
        self.assertEqual(attention.listing(7)['total'],1)
        self.assertFalse(any(r['role']=='assistant' for r in store.thread(7,self.cid)))

    def test_takeover_during_invalid_inference_prevents_repair_and_attention(self):
        def inference(*args,**kwargs):
            store.set_mode(7,self.cid,'HUMAN_TAKEOVER',1)
            return 'malformed','end_turn',None
        with patch.object(self.ai,'_call_claude',side_effect=inference) as model:
            response = self.send(self.identity,text='DJ',event='invalid-takeover-01')
        self.assertEqual(response.status_code,200)
        self.assertEqual(model.call_count,1)
        self.assertEqual(jobs.list_jobs(7)[1],0)
        self.assertEqual(attention.listing(7)['total'],0)

    def test_repair_does_not_outlive_claim_budget_or_accept_truncation(self):
        def inference(*args,**kwargs):
            return phase5.output('DJ',{'service':'DJ'}),'max_tokens',None
        with patch.object(self.ai,'_call_claude',side_effect=inference) as model:
            with patch('kilas_core.conversation.time') as clock:
                clock.time.return_value=__import__('time').time()+50
                response=self.send(self.identity,text='DJ',event='repair-budget-01')
        # Only inference's clock advances: claim has <46s remaining. No repair call,
        # and a syntactically valid prefix marked truncated is never accepted.
        self.assertEqual(response.status_code,200)
        self.assertEqual(model.call_count,1)
        self.assertEqual(jobs.list_jobs(7)[1],0)
        self.assertEqual(store.conversation(7,self.cid)['mode'],'HUMAN_TAKEOVER')

    @classmethod
    def setUpClass(cls):
        phase5.PlaybookRoutesTests.setUpClass.__func__(cls)
        global jobs, store, attention, auto
        from kilas_core import jobs, attention, automations as auto, operation_schema
        from public_chat import store
        operation_schema.apply_schema()

    tearDown=phase5.PlaybookRoutesTests.tearDown
    start=phase5.PlaybookRoutesTests.start
    send=phase5.PlaybookRoutesTests.send
    deliver=phase5.PlaybookRoutesTests.deliver

    def setUp(self):
        with jobs.transaction() as tx:
            for table in ('kw_core_automation_runs','kw_core_attention','kw_core_automation_config'):
                tx.execute('DELETE FROM '+table)
        phase5.PlaybookRoutesTests.setUp(self)
        flag=patch.dict(os.environ,{'KILAS_OPERATIONS_V2_ENABLED':'true'})
        flag.start();self.addCleanup(flag.stop)

    def test_human_request_duplicate_fences_ai_then_owner_reply_return(self):
        text='Saya mau bicara dengan manusia'
        raw=phase5.output(text,intent='HUMAN')
        result,model=self.deliver(text=text,raw=raw)
        self.assertEqual(result.status_code,200)
        self.assertEqual(model.call_count,1)
        self.assertEqual(store.conversation(7,self.cid)['mode'],'HUMAN_TAKEOVER')
        self.assertEqual(attention.listing(7)['total'],1)
        result,model=self.deliver(text=text,raw=raw)
        model.assert_not_called()
        result,model=self.deliver(event='after-human-00001')
        model.assert_not_called()
        self.assertEqual(jobs.list_jobs(7)[1],0)
        self.assertFalse(any(r['role']=='assistant' for r in store.thread(7,self.cid)))
        headers={'X-CSRF-Token':'csrf-test'}
        self.assertEqual(self.client.post(f'/business/7/web-inbox/{self.cid}/reply',json={'event_id':'owner-human-00001','message':'Tim membantu'},headers=headers).status_code,200)
        self.assertEqual(store.thread(7,self.cid)[-1]['role'],'human')
        self.assertEqual(self.client.post(f'/business/7/web-inbox/{self.cid}/mode',json={'mode':'AI_ACTIVE'},headers=headers).status_code,200)
        self.assertEqual(attention.listing(7)['total'],0)
        self.assertEqual(self.deliver(event='after-return-0001')[0].status_code,200)
        self.assertEqual(jobs.list_jobs(7)[1],1)

    def test_ready_attention_immediate_and_uncertainty(self):
        fields={'item':'baju','weight':'20 kg','origin':'Guangzhou','destination':'Tangerang','volume_cbm':'0.2 m3'}
        self.assertEqual(self.deliver(fields=fields)[0].status_code,200)
        self.assertEqual(attention.listing(7)['total'],1)
        self.assertEqual(attention.listing(7)['rows'][0]['reason'],'READY_FOR_QUOTE')
        self.assertEqual(self.deliver(text='dari Shanghai',fields={'origin':'Shanghai'},event='conflict-origin-01')[0].status_code,200)
        self.assertEqual({r['reason'] for r in attention.listing(7)['rows']},{'READY_FOR_QUOTE','NEEDS_INFORMATION_STUCK'})

    def test_existing_inflight_fence_still_suppresses_actions(self):
        phase5.PlaybookRoutesTests.test_human_takeover_during_inference_and_after(self)
        self.assertEqual(attention.listing(7)['total'],0)

    def test_home_count_links_resolution_and_tenant(self):
        self.assertEqual(self.deliver(text='manusia',raw=phase5.output('manusia',intent='HUMAN'))[0].status_code,200)
        item=attention.listing(7)['rows'][0]
        with patch('routes_products._product_businesses',return_value=[self.repo.get_business(7)]), \
             patch.object(self.repo,'required_fields_missing',return_value=[]), \
             patch('payment_service.has_verified_ai_admin_payment',return_value=True):
            home=self.client.get('/products/assist')
        self.assertEqual(home.status_code,200)
        self.assertIn(b'1 hal perlu perhatian',home.data)
        self.assertIn(b'data-attention-inbox',home.data)
        page=self.client.get('/business/7/attention')
        self.assertIn(self.cid.encode(),page.data)
        self.assertIn(self.customer['id'].encode(),page.data)
        self.assertEqual(self.client.post('/business/7/attention/'+item['id']+'/resolve',data={'csrf_token':'bad'}).status_code,400)
        self.assertEqual(self.client.post('/business/7/attention/'+item['id']+'/resolve',data={'csrf_token':'csrf-test'}).status_code,303)
        self.assertEqual(store.conversation(7,self.cid)['mode'],'HUMAN_TAKEOVER')
        self.assertEqual(attention.listing(7)['total'],0)
        with self.client.session_transaction() as session: session['user_id']=2
        for path in ('/business/7/attention','/business/7/automations'):
            self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.client.post('/business/8/attention/'+item['id']+'/resolve',data={'csrf_token':'csrf-test'}).status_code,404)
        self.assertEqual(self.client.post('/business/7/automations/run',data={'csrf_token':'csrf-test'}).status_code,404)
        self.assertNotIn(self.cid.encode(),self.client.get('/business/8/attention').data)

    def test_config_owner_forms_and_closed_payload(self):
        page=self.client.get('/business/7/automations');self.assertEqual(page.status_code,200)
        data=dict(csrf_token='csrf-test',version=0,followup_enabled='true',review_enabled='true',delay_hours=1,max_attempts=2)
        for change in ({'action':'SEND_WHATSAPP'},{'delay_hours':0},{'max_attempts':10},{'csrf_token':'bad'},{'review_enabled':'yes'}):
            self.assertEqual(self.client.post('/business/7/automations',data={**data,**change}).status_code,400)
        self.assertEqual(auto.get_config(7)['version'],0)
        self.assertEqual(self.client.post('/business/7/automations',data=data).status_code,303)
        self.assertEqual(self.client.post('/business/7/automations',data=data).status_code,303)
        self.assertEqual(self.client.post('/business/7/automations',data={**data,'delay_hours':3}).status_code,409)
        self.assertEqual(self.client.post('/business/7/automations/run',data={'csrf_token':'csrf-test'}).status_code,200)
        self.assertEqual(self.client.post('/business/7/automations/run',data={'csrf_token':'csrf-test','channel':'whatsapp'}).status_code,400)
        self.assertEqual(self.client.post('/business/7/automations',json=data,headers={'X-CSRF-Token':'csrf-test'}).status_code,400)

    def test_flags_package_subscription_and_finance_session(self):
        for flag in ('KILAS_OPERATIONS_V2_ENABLED','KILAS_JOBS_V2_ENABLED','KILAS_CUSTOMERS_V2_ENABLED','KILAS_CORE_V2_ENABLED','KILAS_WEB_CHAT_ENABLED'):
            with patch.dict(os.environ,{flag:'false'}):
                self.assertEqual(self.client.get('/business/7/attention').status_code,404)
                self.assertEqual(self.client.post('/business/7/automations/run',data={'csrf_token':'csrf-test'}).status_code,404)
        self.db.execute("UPDATE subscriptions SET status='SUSPENDED' WHERE business_id=7")
        self.assertEqual(self.client.get('/business/7/automations').status_code,404)
        self.db.execute("UPDATE subscriptions SET status='ACTIVE' WHERE business_id=7")
        self.db.execute("UPDATE businesses SET package='FINANCE' WHERE id=7")
        self.assertEqual(self.client.get('/business/7/attention').status_code,404)
        self.db.execute("UPDATE businesses SET package='AI_ADMIN' WHERE id=7")
        with self.client.session_transaction() as session: session['active_product']='finance'
        for path in ('/business/7/attention','/business/7/automations'):
            response=self.client.get(path)
            self.assertEqual(response.status_code,200)
            self.assertNotIn('finance-app-sidebar',response.text)

    def test_runner_protected_writes_and_no_model_or_external_send(self):
        import sqlite3
        from contextlib import ExitStack
        from kilas_core.operation_contracts import DEFAULT_CONFIG
        self.assertEqual(self.deliver()[0].status_code,200)
        auto.set_config(7,{**DEFAULT_CONFIG,'followup_enabled':True,'delay_hours':1},actor_id=1,expected_version=0)
        with jobs.transaction() as tx: tx.execute('UPDATE kw_web_messages SET created_at=1000')
        denied=[]
        def authorize(action,table,*args):
            if action in (sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE):
                if not (table.startswith(('kw_web_','kw_core_')) or table in ('audit_log','sqlite_sequence')):
                    denied.append(table);return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        original=sqlite3.connect
        def connect(*args,**kwargs):
            connection=original(*args,**kwargs);connection.set_authorizer(authorize);return connection
        self.db.get_connection().set_authorizer(authorize)
        try:
            with ExitStack() as stack:
                stack.enter_context(patch('sqlite3.connect',side_effect=connect))
                spies=[stack.enter_context(patch.object(self.finance,name)) for name in
                       ('create_transaction','create_finance_invoice','record_invoice_payment','create_customer')]
                spies += [stack.enter_context(patch('inbox_service.send_manual_reply')),
                          stack.enter_context(patch.object(self.ai,'_call_claude'))]
                self.assertEqual(auto.run(7,now=4600)['results'],['DELIVERED'])
                self.assertEqual(auto.run(7,now=4600)['results'],[])
                for spy in spies: spy.assert_not_called()
            self.assertEqual(denied,[])
        finally:
            self.db.get_connection().set_authorizer(None)


if __name__=='__main__': unittest.main()
