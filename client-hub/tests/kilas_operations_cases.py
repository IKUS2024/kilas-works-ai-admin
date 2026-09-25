"""Phase 6 assertions shared by disposable SQLite/PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from kilas_core import automations as auto, attention, jobs
from kilas_core.operation_contracts import DEFAULT_CONFIG, MESSAGES, OperationError
from public_chat import store


class Cases:
    def operational_seed(self):
        with jobs.transaction() as tx:
            for table in ('kw_core_automation_runs','kw_core_attention','kw_core_automation_config','kw_web_events','kw_web_messages','kw_web_limits'):
                tx.execute('DELETE FROM '+table)
            tx.execute("UPDATE kw_web_conversations SET mode='AI_ACTIVE',version=1,expires_at=9999999999")
            store._message(tx,7,'conv','initial-user','user','Saya perlu layanan')
            store._message(tx,7,'conv','initial-answer','assistant','Boleh lengkapi rincian?')
            tx.execute('UPDATE kw_web_messages SET created_at=1000')

    def configure(self,**changes):
        current=auto.get_config(7)
        return auto.set_config(7,{**DEFAULT_CONFIG,**changes},actor_id=1,expected_version=current['version'])

    def pending(self):
        with jobs.transaction() as tx:
            return tx.execute("SELECT * FROM kw_core_automation_runs WHERE business_id=7 ORDER BY source_key")

    def completed(self,conversation_id='conv'):
        row=jobs.create_job(7,'alice',conversation_id=conversation_id,title='Service selesai',kind='SERVICE',
                            actor_id=1,operation_key='review-test-create')
        for status in ('READY_FOR_QUOTE','QUOTED','APPROVED','IN_PROGRESS','COMPLETED'):
            row=jobs.transition_job(7,row['id'],status,expected_version=row['version'],actor_id=1,operation_key='review-test-'+status)
        return row

    def test_due_cooldown_max_and_customer_reset(self):
        self.configure(followup_enabled=True,delay_hours=1,max_attempts=2)
        auto.run(7,now=4599);self.assertEqual(self.pending(),[])
        auto.run(7,now=4600);self.assertEqual([r['status'] for r in self.pending()],['DELIVERED'])
        auto.run(7,now=4600);self.assertEqual(len(self.pending()),1)
        # Synthetic time must also advance the actual durable message timestamp.
        with jobs.transaction() as tx: tx.execute('UPDATE kw_web_messages SET created_at=4600 WHERE role=\'assistant\'')
        auto.run(7,now=8199);self.assertEqual(len(self.pending()),1)
        auto.run(7,now=8200);self.assertEqual(len(self.pending()),2)
        auto.run(7,now=999999);self.assertEqual(len(self.pending()),2)
        with jobs.transaction() as tx:
            store._message(tx,7,'conv','new-user','user','Rincian tambahan')
            store._message(tx,7,'conv','new-answer','assistant','Ada rincian lain?')
            tx.execute('UPDATE kw_web_messages SET created_at=10000 WHERE event_id IN (?,?)',('new-user','new-answer'))
        auto.run(7,now=13600);self.assertEqual(len(self.pending()),3)

    def test_customer_reply_and_mode_version_cancel_pending(self):
        self.configure(followup_enabled=True,delay_hours=1)
        auto.scan(7,now=4600);key=self.pending()[0]['source_key']
        with jobs.transaction() as tx: store._message(tx,7,'conv','customer-replied','user','Saya membalas')
        self.assertEqual(auto.deliver(7,key,now=4600),'SKIPPED')
        self.assertEqual(len(store.thread(7,'conv')),3)
        self.operational_seed();self.configure(followup_enabled=True,delay_hours=1)
        auto.scan(7,now=4600);key=self.pending()[0]['source_key']
        store.set_mode(7,'conv','HUMAN_TAKEOVER',1);store.set_mode(7,'conv','AI_ACTIVE',1)
        self.assertEqual(auto.deliver(7,key,now=4600),'SKIPPED')
        self.assertEqual(len(store.thread(7,'conv')),2)

    def test_concurrent_runners_deliver_once(self):
        self.configure(followup_enabled=True,delay_hours=1)
        barrier=Barrier(4)
        def execute(_): barrier.wait();return auto.run(7,now=4600)
        with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(execute,range(4)))
        self.assertEqual(len(self.pending()),1)
        self.assertEqual(self.pending()[0]['status'],'DELIVERED')
        self.assertEqual([r['content'] for r in store.thread(7,'conv')].count(MESSAGES[auto.FOLLOWUP]),1)

    def test_review_once_and_ready_attention_resolves(self):
        self.configure(review_enabled=True)
        row=self.completed()
        auto.run(7,now=4600);auto.run(7,now=4600)
        self.assertEqual(len(self.pending()),1)
        self.assertEqual(self.pending()[0]['status'],'DELIVERED')
        self.assertEqual([r['content'] for r in store.thread(7,'conv')].count(MESSAGES[auto.REVIEW]),1)
        self.assertEqual(attention.listing(7)['total'],0)

    def test_review_human_or_missing_conversation_attention(self):
        self.configure(review_enabled=True)
        row=self.completed()
        store.set_mode(7,'conv','HUMAN_TAKEOVER',1)
        auto.run(7,now=4600);auto.run(7,now=4600)
        self.assertEqual(self.pending()[0]['status'],'SKIPPED')
        self.assertEqual(attention.listing(7)['total'],1)
        self.assertEqual(attention.listing(7)['rows'][0]['reason'],'REVIEW_REQUEST_DUE')
        self.assertEqual(len(store.thread(7,'conv')),2)

    def test_message_failure_never_delivered(self):
        self.configure(followup_enabled=True,delay_hours=1)
        with patch.object(store,'_message',side_effect=RuntimeError('write failed')):
            result=auto.run(7,now=4600)
        self.assertEqual(result['results'],['FAILED'])
        self.assertIsNone(self.pending()[0]['delivered_at'])
        self.assertEqual(attention.listing(7)['rows'][0]['reason'],'AUTOMATION_FAILED')
        auto.run(7,now=4600)
        self.assertEqual(len(store.thread(7,'conv')),2)

    def test_ready_attention_repeated_scans_no_quote_action(self):
        row=jobs.create_job(7,'alice',conversation_id='conv',title='Ready',actor_id=1,operation_key='ready-create-0001')
        row=jobs.transition_job(7,row['id'],'READY_FOR_QUOTE',expected_version=1,actor_id=1,operation_key='ready-update-0001')
        for _ in range(3): auto.run(7,now=4600)
        items=attention.listing(7)
        self.assertEqual(items['total'],1)
        self.assertEqual(items['rows'][0]['job_id'],row['id'])
        attention.resolve(7,items['rows'][0]['id'],1);auto.run(7,now=4600)
        self.assertEqual(attention.listing(7)['total'],0)
        self.assertEqual(jobs.get_job(7,row['id'])['status'],'READY_FOR_QUOTE')

    def test_config_and_foreign_run_fail_closed(self):
        self.configure(followup_enabled=True,delay_hours=1)
        auto.scan(7,now=4600);key=self.pending()[0]['source_key']
        with self.assertRaises(OperationError): auto.deliver(8,key,now=4600)
        self.configure(followup_enabled=False)
        self.assertEqual(auto.deliver(7,key,now=4600),'SKIPPED')
        self.assertEqual(len(store.thread(7,'conv')),2)

    def test_terminal_failure_rolls_back_already_inserted_message(self):
        self.configure(followup_enabled=True,delay_hours=1)
        terminal=auto._terminal
        def fail_after_message(tx,row,status,now,error=None):
            if status=='DELIVERED': raise RuntimeError('terminal audit unavailable')
            return terminal(tx,row,status,now,error)
        with patch.object(auto,'_terminal',side_effect=fail_after_message):
            self.assertEqual(auto.run(7,now=4600)['results'],['FAILED'])
        self.assertEqual(len(store.thread(7,'conv')),2)
        self.assertIsNone(self.pending()[0]['delivered_at'])
        self.assertEqual(attention.listing(7)['total'],1)

    def test_review_without_web_conversation_falls_back(self):
        self.configure(review_enabled=True)
        self.completed(conversation_id=None)
        self.assertEqual(auto.run(7,now=4600)['results'],['SKIPPED'])
        self.assertEqual(self.pending()[0]['error_code'],'UNAVAILABLE')
        self.assertEqual(attention.listing(7)['rows'][0]['reason'],'REVIEW_REQUEST_DUE')
        self.assertEqual(len(store.thread(7,'conv')),2)

    def test_disabled_channel_and_expired_session_cannot_deliver(self):
        self.configure(followup_enabled=True,delay_hours=1)
        auto.scan(7,now=4600);key=self.pending()[0]['source_key']
        with jobs.transaction() as tx: tx.execute('UPDATE kw_web_channels SET enabled=0 WHERE business_id=7')
        self.assertEqual(auto.deliver(7,key,now=4600),'SKIPPED')
        self.assertEqual(len(store.thread(7,'conv')),2)
        with jobs.transaction() as tx:
            tx.execute('UPDATE kw_web_channels SET enabled=1 WHERE business_id=7')
            tx.execute('UPDATE kw_web_conversations SET expires_at=4600 WHERE business_id=7')
        auto.run(7,now=4600)
        self.assertEqual(len(self.pending()),1)

    def test_human_mode_and_system_audit_identity(self):
        self.configure(followup_enabled=True,delay_hours=1)
        store.set_mode(7,'conv','HUMAN_TAKEOVER',1)
        auto.run(7,now=4600)
        self.assertEqual(self.pending(),[])
        store.set_mode(7,'conv','AI_ACTIVE',1)
        auto.run(7,now=4600)
        with jobs.transaction() as tx:
            rows=tx.execute("SELECT actor_user_id,detail FROM audit_log WHERE action='WEB_AUTOMATION_DELIVERED'")
        self.assertTrue(rows)
        self.assertTrue(all(row['actor_user_id'] is None and 'WEB_AUTOMATION' in row['detail'] for row in rows))
