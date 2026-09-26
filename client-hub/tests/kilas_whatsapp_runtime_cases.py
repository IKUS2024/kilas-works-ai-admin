"""Identical SQLite/PostgreSQL runtime assertions, using disposable fixture data only."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch, Mock
import db
from public_chat import schema, store
from kilas_core import customer_schema, job_schema, operation_schema, whatsapp_schema, jobs, customers
from kilas_core import whatsapp_access as access, whatsapp_transport as transport, conversation
from kilas_core.adapters import whatsapp as wa


class RuntimeCases:
    def setup_runtime(self):
        with store.transaction() as tx:
            tx.execute('CREATE TABLE IF NOT EXISTS businesses(id INTEGER PRIMARY KEY,package TEXT,status TEXT)')
            tx.execute('CREATE TABLE IF NOT EXISTS subscriptions(business_id INTEGER PRIMARY KEY,status TEXT)')
            tx.execute('CREATE TABLE IF NOT EXISTS audit_log(actor_user_id INTEGER,business_id INTEGER,action TEXT,detail TEXT)')
            tx.execute('CREATE TABLE IF NOT EXISTS wa_conversation_state(business_id INTEGER,customer_phone TEXT,mode TEXT,updated_by_user_id INTEGER,UNIQUE(business_id,customer_phone))')
            for bid in (7,8):
                tx.execute("INSERT INTO businesses VALUES (?,'AI_ADMIN','ACTIVE') ON CONFLICT(id) DO NOTHING",(bid,))
                tx.execute("INSERT INTO subscriptions VALUES (?,'ACTIVE') ON CONFLICT(business_id) DO NOTHING",(bid,))
        schema.apply_schema();customer_schema.apply_schema();job_schema.apply_schema();operation_schema.apply_schema();whatsapp_schema.apply_schema()
        with store.transaction() as tx:
            for table in ('kw_core_wa_inbound','kw_core_wa_outbound','kw_core_wa_conversations','kw_core_automation_runs','kw_core_attention','kw_core_automation_config','kw_core_job_operations','kw_core_jobs','kw_web_customer_links','kw_core_customer_identities','kw_core_customers','kw_web_messages','kw_web_events','kw_web_conversations','kw_web_limits','wa_conversation_state','audit_log'):
                tx.execute('DELETE FROM '+table)
        for bid in (7,8): store.ensure_channel(bid)
        flags={k:'true' for k in ('KILAS_CORE_V2_ENABLED','KILAS_WEB_CHAT_ENABLED','KILAS_CUSTOMERS_V2_ENABLED','KILAS_JOBS_V2_ENABLED','KILAS_PLAYBOOKS_V2_ENABLED','KILAS_OPERATIONS_V2_ENABLED','KILAS_WHATSAPP_CORE_ENABLED')}
        flags.update(KILAS_CORE_V2_TEST_BUSINESS_IDS='7,8',KILAS_WHATSAPP_CORE_CHANNELS=json.dumps({str(b):{'phone_number_id':str(b)*5,'official_access_verified':True} for b in (7,8)}),WHATSAPP_TOKEN__TENANT_7='runtime-seven',WHATSAPP_TOKEN__TENANT_8='runtime-eight')
        stubs=[patch.dict(os.environ,flags),patch.object(access.repo,'get_business',side_effect=lambda b:dict(id=b,business_name='Fixture',package='AI_ADMIN',status='ACTIVE',whatsapp_phone_number_id=str(b)*5)),
            patch.object(access.repo,'get_whatsapp_config',side_effect=lambda b:dict(phone_number_id=str(b)*5,connection_status='CONNECTED',credentials_reference='WHATSAPP_TOKEN__TENANT_'+str(b))),
            patch.object(access.repo,'get_ai_settings',return_value={'normalized_config':{}}),
            patch.object(access.repo,'get_business_profile',return_value={'category':'Logistics'})]
        for stub in stubs: stub.start();self.addCleanup(stub.stop)
        self.response=Mock(status_code=200);self.response.json.return_value={'messages':[{'id':'provider-out'}]}
        stub=patch.object(transport.requests,'post',return_value=self.response);self.http=stub.start();self.addCleanup(stub.stop)

    def _message(self):
        return {'messages':[{'id':'wamid.runtime','from':'628111222333','timestamp':str(int(time.time())),'type':'text','text':{'body':'pesan'}}]}

    def _raw(self):
        return json.dumps(dict(intent='REQUEST',fields={'item':'baju'},evidence={'item':'pesan'},corrections=[],ambiguous=[]))

    def test_four_concurrent_identity_retries_one_customer(self):
        barrier=Barrier(4)
        def work(_):
            barrier.wait()
            return wa.ensure(7,'77777','628111222333',event_id='same',payload_hash='same')
        with ThreadPoolExecutor(max_workers=4) as pool: links=list(pool.map(work,range(4)))
        self.assertEqual(len({r['conversation_id'] for r in links}),1)
        self.assertEqual(customers.list_customers(7)[1],1)
        other=wa.ensure(8,'88888','628111222333')
        self.assertNotEqual(other['conversation_id'],links[0]['conversation_id'])

    def test_identity_link_rollback_and_conflicting_provider_replay(self):
        with patch.object(customers,'ensure_channel_customer',side_effect=RuntimeError('rollback')):
            with self.assertRaises(RuntimeError): wa.ensure(7,'77777','628111222333',event_id='same',payload_hash='first')
        with store.transaction() as tx:
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM kw_web_conversations')['n'],0)
        wa.ensure(7,'77777','628111222333',event_id='same',payload_hash='first')
        with self.assertRaises(store.ChatError): wa.ensure(7,'77777','628444555666',event_id='same',payload_hash='changed')
        self.assertEqual(customers.list_customers(7)[1],1)

    def confirm_action_customer(self):
        link=wa.ensure(7,'77777','628111222333')
        customer=customers.customer_for_conversation(7,link['conversation_id'])
        with store.transaction() as tx:
            tx.execute("UPDATE kw_core_customer_stages SET stage='CUSTOMER' WHERE business_id=7 AND customer_id=?",(customer['id'],))

    def test_core_action_outbound_concurrency_and_repeat_schema(self):
        self.confirm_action_customer()
        with patch.object(conversation.ai_onboarding,'_call_claude',return_value=(self._raw(),'end_turn',None)):
            wa.handle(7,'77777',self._message(),'messages')
        row=jobs.list_jobs(7)[0][0];cid=row['conversation_id']
        barrier=Barrier(4)
        def work(_):
            barrier.wait();return transport.deliver(7,cid,'wamid.runtime',role='assistant')
        with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(work,range(4)))
        self.http.assert_called_once();self.assertTrue(all(r['status']=='accepted' for r in results))
        whatsapp_schema.apply_schema();self.assertEqual(jobs.get_job(7,row['id']),row)

    def test_action_rollback_no_false_reply_or_outbound(self):
        self.confirm_action_customer()
        with patch.object(conversation.ai_onboarding,'_call_claude',return_value=(self._raw(),'end_turn',None)),patch.object(jobs,'_update_job',side_effect=RuntimeError('rollback')):
            wa.handle(7,'77777',self._message(),'messages')
        self.assertEqual(jobs.list_jobs(7)[1],0);self.http.assert_not_called()
        with store.transaction() as tx: self.assertEqual(tx.one("SELECT COUNT(*) AS n FROM kw_web_messages WHERE role='assistant'")['n'],0)

    def test_abandoned_send_attempt_never_resends(self):
        self.confirm_action_customer()
        with patch.object(conversation.ai_onboarding,'_call_claude',return_value=(self._raw(),'end_turn',None)):
            wa.handle(7,'77777',self._message(),'messages')
        cid=jobs.list_jobs(7)[0][0]['conversation_id']
        with store.transaction() as tx: tx.execute("UPDATE kw_core_wa_outbound SET status='attempting',provider_id=NULL")
        self.assertEqual(transport.deliver(7,cid,'wamid.runtime',role='assistant')['status'],'attempting')
        self.http.assert_called_once()
