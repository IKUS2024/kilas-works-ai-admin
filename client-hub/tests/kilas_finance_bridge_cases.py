"""Shared SQLite/PostgreSQL service cases; only synthetic owner-entered finance data."""
import hashlib
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import db, repo, subscription_service
import finance_service as f, finance_branches as branches
import platform_workspace
from kilas_core import finance_bridge as bridge


class BridgeCases:
    def seed_bridge(self):
        self.actor=repo.create_user(uuid.uuid4().hex+'@example.test','unused')
        self.foreign_actor=repo.create_user(uuid.uuid4().hex+'@example.test','unused')
        self.source=repo.create_business(self.actor,'Same name')
        self.target=repo.create_business(self.actor,'Same name',package='NONE')
        self.foreign=repo.create_business(self.foreign_actor,'Same name',package='NONE')
        subscription_service.create_subscription(self.source,'ai_admin',self.actor)
        f.ensure_finance_defaults(self.target,actor_user_id=self.actor)
        f.ensure_finance_defaults(self.foreign,actor_user_id=self.foreign_actor)
        self.branch=branches.list_branches(self.target,self.actor)[0]['id']
        self.foreign_branch=branches.list_branches(self.foreign,self.foreign_actor)[0]['id']
        self.cid=uuid.uuid4().hex;self.jid=uuid.uuid4().hex
        db.execute('INSERT INTO kw_core_customers(business_id,id,display_name,source_channel,created_at,updated_at,last_activity_at) VALUES (?,?,?,?,?,?,?)',
                   (self.source,self.cid,'Wilson','WEB',1,1,1))
        db.execute('INSERT INTO kw_core_jobs(business_id,id,customer_id,kind,title,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',
                   (self.source,self.jid,self.cid,'PROJECT','Photo work','READY_FOR_QUOTE',1,1))
        self.flags=patch.dict(os.environ,{'KILAS_FINANCE_BRIDGE_ENABLED':'true','KILAS_CORE_V2_ENABLED':'true',
            'KILAS_CORE_V2_TEST_BUSINESS_IDS':str(self.source),'KILAS_CUSTOMERS_V2_ENABLED':'true','KILAS_JOBS_V2_ENABLED':'true',
            'KILAS_FINANCE_ACCESS_MODE':'internal_beta','KILAS_FINANCE_EMERGENCY_DISABLE':'false','KILAS_FINANCE_BETA':'on'})
        self.flags.start();self.addCleanup(self.flags.stop)
        self.invoice=dict(items=[dict(description='Photo',quantity=2,unit_price_minor=50000)],
                          currency='IDR',issue_date='2026-09-01',due_date='2026-09-30')

    def connect(self,**changes):
        args=dict(finance_business_id=self.target,finance_branch_id=self.branch,expected_version=0,
                  enabled_value=True,operation_key='1'*32,confirmed=True);args.update(changes)
        return bridge.configure(self.source,self.actor,**args)

    def customer(self,**changes):
        args=dict(expected_version=1,operation_key='2'*32,confirmed=True,new_customer=dict(name='Wilson'))
        args.update(changes);return bridge.link_customer(self.source,self.actor,self.cid,**args)

    def draft(self,**changes):
        args=dict(expected_version=1,operation_key='3'*32,confirmed=True,invoice=self.invoice)
        args.update(changes);return bridge.create_draft(self.source,self.actor,self.jid,**args)

    def test_explicit_mapping_no_same_name_inference_and_foreign_rejection(self):
        self.assertIsNone(bridge.connection(self.source,self.actor))
        for args in (dict(confirmed=False),dict(finance_business_id=self.foreign,finance_branch_id=self.foreign_branch),
                     dict(finance_branch_id=self.foreign_branch)):
            with self.assertRaises((bridge.BridgeError,f.FinanceError)):self.connect(**args)
        row=self.connect();self.assertEqual(self.connect(),row)
        self.assertEqual(row['finance_business_id'],self.target)
        with self.assertRaises(bridge.BridgeError):self.connect(enabled_value=False)

    def test_customer_explicit_create_not_name_merge_and_replay(self):
        existing=f.create_customer(self.target,'Wilson',actor_user_id=self.actor)
        self.connect();result=self.customer()
        self.assertNotEqual(result['customer']['id'],existing)
        self.assertEqual(self.customer(),result)
        self.assertEqual(len(f.list_customers(self.target,actor_user_id=self.actor)),2)
        with self.assertRaises(bridge.BridgeError):self.customer(operation_key='a'*32)
        self.assertEqual(len(f.list_customers(self.target,actor_user_id=self.actor)),2)

    def test_explicit_existing_customer_and_foreign_customer(self):
        self.connect()
        wrong=f.create_customer(self.foreign,'Other',actor_user_id=self.foreign_actor)
        with self.assertRaises(bridge.BridgeError):self.customer(new_customer=None,existing_customer_id=wrong)
        right=f.create_customer(self.target,'Selected',actor_user_id=self.actor)
        result=self.customer(new_customer=None,existing_customer_id=right)
        self.assertEqual(result['customer']['id'],right)
        self.assertEqual(len(f.list_customers(self.target,actor_user_id=self.actor)),1)

    def test_draft_retry_has_no_cash_and_authoritative_payment_readback(self):
        self.connect();self.customer();result=self.draft()
        self.assertEqual(self.draft(),result)
        self.assertEqual(result['invoice']['status'],'DRAFT')
        self.assertEqual(result['invoice']['branch_id'],self.branch)
        self.assertEqual(result['invoice']['total_minor'],100000)
        self.assertEqual(f.list_transactions(self.target,actor_user_id=self.actor),[])
        iid=result['invoice']['id']
        with branches.scope(self.target,self.branch,self.actor):
            f.issue_finance_invoice(self.target,iid,actor_user_id=self.actor)
            account=f.list_accounts(self.target,actor_user_id=self.actor)[0]['id']
            category=f.list_categories(self.target,'INCOME',actor_user_id=self.actor)[0]['id']
            for n in range(2):
                f.record_invoice_payment(self.target,iid,50000,'2026-09-10',account,category,
                    actor_user_id=self.actor,idempotency_key='bridge-test-payment-'+str(n))
                current=bridge.read_invoice(self.source,self.actor,self.jid)['invoice']
                self.assertEqual(current['status'],'PARTIALLY_PAID' if n==0 else 'PAID')
                self.assertEqual(current['outstanding_minor'],50000 if n==0 else 0)
        self.assertEqual(len(f.list_transactions(self.target,actor_user_id=self.actor)),2)

    def test_parallel_mark_paid_uses_current_outstanding_once(self):
        self.connect();self.customer();self.draft()
        db.execute("UPDATE kw_core_jobs SET status='IN_PROGRESS' WHERE business_id=? AND id=?",(self.source,self.jid))
        bridge.issue_job_invoice(self.source,self.actor,self.jid)
        opts=bridge.payment_options(self.source,self.actor,self.jid)
        barrier=threading.Barrier(4)
        def pay(index):
            try:
                barrier.wait()
                return bridge.record_full_payment(self.source,self.actor,self.jid,paid_on='2026-09-10',
                    account_id=opts['accounts'][0]['id'],category_id=opts['categories'][0]['id'],
                    note='',payment_key=f'concurrent-{index:020d}')
            finally:
                if getattr(db._local,'conn',None):db._local.conn.close();db._local.conn=None
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows=list(pool.map(pay,range(4)))
        self.assertTrue(all(row['invoice']['status']=='PAID' for row in rows))
        transactions=f.list_transactions(self.target,actor_user_id=self.actor)
        self.assertEqual(len(transactions),1)
        self.assertEqual(transactions[0]['amount_minor'],100000)
        self.assertEqual(transactions[0]['source_type'],'FINANCE_INVOICE_PAYMENT')

    def test_deal_job_invoice_payment_posts_authoritative_income(self):
        # New Jobs workflow: only a deal (Dikerjakan) may start invoicing.
        self.connect()
        db.execute("UPDATE kw_core_jobs SET status='IN_PROGRESS' WHERE business_id=? AND id=?",
                   (self.source,self.jid))
        linked=bridge.ensure_job_customer_link(
            self.source,self.actor,self.jid,expected_version=1,operation_key='8'*32)
        finance_customer=linked['customer']['id']
        with branches.scope(self.target,self.branch,self.actor):
            invoice_id=f.create_finance_invoice(
                self.target,finance_customer,self.invoice['issue_date'],self.invoice['due_date'],
                self.invoice['items'],currency=self.invoice['currency'],actor_user_id=self.actor,
                idempotency_key='a'*32)
        attached=bridge.attach_existing_invoice(
            self.source,self.actor,self.jid,invoice_id,expected_version=1)
        self.assertEqual(attached['invoice']['status'],'DRAFT')
        issued=bridge.issue_job_invoice(self.source,self.actor,self.jid)
        self.assertEqual(issued['invoice']['status'],'ISSUED')
        options=bridge.payment_options(self.source,self.actor,self.jid)
        account=next(a for a in options['accounts'] if a['currency']=='IDR')
        category=options['categories'][0]
        paid=bridge.record_full_payment(
            self.source,self.actor,self.jid,paid_on='2026-09-10',
            account_id=account['id'],category_id=category['id'],note='Paid from Job',
            payment_key='job-full-payment-0001')
        self.assertEqual(paid['invoice']['status'],'PAID')
        self.assertEqual(paid['invoice']['outstanding_minor'],0)
        with branches.scope(self.target,self.branch,self.actor):
            rows=f.list_transactions(self.target,actor_user_id=self.actor)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['direction'],'INCOME')
        self.assertEqual(rows[0]['source_type'],'FINANCE_INVOICE_PAYMENT')
        self.assertEqual(rows[0]['amount_minor'],100000)
        # Transport/UI retry with the same payment key must not duplicate income.
        replay=bridge.record_full_payment(
            self.source,self.actor,self.jid,paid_on='2026-09-10',
            account_id=account['id'],category_id=category['id'],note='Paid from Job',
            payment_key='job-full-payment-0001')
        self.assertEqual(replay['invoice']['status'],'PAID')
        with branches.scope(self.target,self.branch,self.actor):
            self.assertEqual(len(f.list_transactions(self.target,actor_user_id=self.actor)),1)

    def test_publish_job_invoice_uses_official_whatsapp_transport(self):
        self.connect()
        db.execute("UPDATE kw_core_jobs SET status='IN_PROGRESS' WHERE business_id=? AND id=?",
                   (self.source,self.jid))
        linked=bridge.ensure_job_customer_link(
            self.source,self.actor,self.jid,expected_version=1,operation_key='c'*32)
        with branches.scope(self.target,self.branch,self.actor):
            invoice_id=f.create_finance_invoice(
                self.target,linked['customer']['id'],self.invoice['issue_date'],self.invoice['due_date'],
                self.invoice['items'],currency='IDR',actor_user_id=self.actor,idempotency_key='d'*32)
        bridge.attach_existing_invoice(self.source,self.actor,self.jid,invoice_id,expected_version=1)
        from flask import Flask
        share_app=Flask(__name__);share_app.secret_key='synthetic-invoice-share-test-key-only-123456789'
        with share_app.app_context(), patch.object(bridge.customer_insights,'whatsapp_conversation_rows',
                          return_value=[{'id':'wa_invoice_test'}]), \
             patch.object(bridge.finance_invoice_view,'base_url',return_value='https://app.kilasworks.id'), \
             patch.object(bridge.whatsapp_transport,'system_text',
                          return_value={'status':'accepted'}) as send:
            result=bridge.publish_and_send_invoice(
                self.source,self.actor,self.jid,'publish-job-invoice-0001')
        self.assertEqual(result['result']['invoice']['status'],'ISSUED')
        send.assert_called_once()
        args=send.call_args.args
        self.assertEqual(args[0],self.source)
        self.assertEqual(args[1],'wa_invoice_test')
        token=args[3].split('/finance/invoice-share/')[1]
        with share_app.app_context():
            self.assertEqual(bridge.finance_invoice_view.resolve_token(token),(self.target,invoice_id))
        self.assertTrue(send.call_args.kwargs['safe_retry'])
        self.assertIn(result['result']['invoice']['invoice_number'],args[3])

    def test_platform_job_invoice_uses_old_inbox_transport_at_most_once(self):
        # Treat this synthetic source as the hidden Kilas Works CRM scope.
        db.execute("DELETE FROM platform_workspace_scope")
        db.execute(
            "INSERT INTO platform_workspace_scope(singleton,business_id) VALUES (1,?)",
            (self.source,))
        db.execute(
            "UPDATE kw_core_customers SET phone=?,source_channel='WHATSAPP' "
            "WHERE business_id=? AND id=?",
            ("628555000111", self.source, self.cid))

        self.connect(); self.customer(); draft=self.draft()
        db.execute(
            "UPDATE kw_core_jobs SET status='IN_PROGRESS' WHERE business_id=? AND id=?",
            (self.source,self.jid))

        with patch.object(bridge.finance_invoice_view,'base_url',
                          return_value='https://app.kilasworks.id'), \
             patch.object(bridge.finance_invoice_view,'create_token',
                          return_value='platform-signed-token'), \
             patch.object(platform_workspace.platform_inbox_service,'send_system_reply',
                          return_value=(True,'sent')) as send, \
             patch.object(bridge.whatsapp_transport,'system_text') as tenant_send:
            first=bridge.publish_and_send_invoice(
                self.source,self.actor,self.jid,'platform-publish-0001')
            second=bridge.publish_and_send_invoice(
                self.source,self.actor,self.jid,'platform-publish-0002')

        self.assertEqual(first['result']['invoice']['status'],'ISSUED')
        self.assertEqual(first['delivery']['status'],'accepted')
        self.assertEqual(second['delivery']['status'],'accepted')
        self.assertTrue(first['already_sent'])
        self.assertTrue(second['already_sent'])
        send.assert_called_once()
        tenant_send.assert_not_called()
        sent_text=send.call_args.args[1]
        self.assertIn(draft['invoice']['invoice_number'],sent_text)
        self.assertIn('/finance/invoice-share/platform-signed-token',sent_text)
        status=bridge.invoice_delivery_status(self.source,draft['invoice']['id'])
        self.assertEqual(status['status'],'accepted')
        self.assertEqual(status['event_id'],f"invoice:{draft['invoice']['id']}:issued")

    def test_mapping_change_disable_preserves_history_and_old_replay(self):
        self.connect();original=self.customer();invoice=self.draft()
        new_branch=branches.create_branch(self.target,'Second',self.actor)
        self.connect(finance_branch_id=new_branch,expected_version=1,operation_key='4'*32)
        self.assertEqual(self.draft(),invoice)
        self.assertEqual(self.customer(),original)
        self.connect(finance_branch_id=new_branch,expected_version=2,enabled_value=False,operation_key='5'*32)
        self.assertEqual(bridge.read_invoice(self.source,self.actor,self.jid),invoice)
        self.assertEqual(len(bridge.customer_links(self.source,self.actor,self.cid)),1)
        with self.assertRaises(bridge.BridgeError):self.draft(operation_key='6'*32,expected_version=3)
        self.connect(finance_branch_id=new_branch,expected_version=3,operation_key='7'*32)
        self.assertEqual(bridge.read_invoice(self.source,self.actor,self.jid),invoice)

    def test_expired_emergency_and_disabled_ai_block_new_writes_keep_finance_reads(self):
        self.connect();self.customer();invoice=self.draft()
        with patch.dict(os.environ,{'KILAS_FINANCE_ACCESS_MODE':'self_service','KILAS_FINANCE_UNLIMITED_TRIAL':'false'}):
            self.assertEqual(bridge.read_invoice(self.source,self.actor,self.jid),invoice)
            with self.assertRaises(f.FinanceError):self.connect(expected_version=1,operation_key='9'*32)
        with patch.dict(os.environ,{'KILAS_FINANCE_EMERGENCY_DISABLE':'true'}):
            with self.assertRaises(f.FinanceError):self.connect(expected_version=1,operation_key='9'*32)
        db.execute("UPDATE subscriptions SET status='SUSPENDED' WHERE business_id=?",(self.source,))
        with self.assertRaises(bridge.BridgeError):self.draft()

    def test_confirmation_and_missing_or_invented_financial_fields_rejected(self):
        self.connect();self.customer()
        for change in (dict(confirmed=False),dict(invoice={'currency':'IDR'}),
                       dict(invoice=dict(self.invoice,paid=True)),
                       dict(invoice=dict(self.invoice,items=[{'description':'x','unit_price_minor':1}]))):
            with self.assertRaises((bridge.BridgeError,f.FinanceError)):self.draft(**change)
        self.assertEqual(f.list_finance_invoices(self.target,actor_user_id=self.actor),[])

    def test_post_finance_write_failure_rolls_back_customer_invoice_link_audit(self):
        self.connect()
        real=bridge._record
        with patch.object(bridge,'_record',side_effect=RuntimeError('link audit failed')),self.assertRaises(RuntimeError):self.customer()
        self.assertEqual(f.list_customers(self.target,actor_user_id=self.actor),[])
        self.customer()
        with patch.object(bridge,'_record',side_effect=RuntimeError('link audit failed')),self.assertRaises(RuntimeError):self.draft()
        self.assertEqual(f.list_finance_invoices(self.target,actor_user_id=self.actor),[])
        self.assertIsNone(bridge.read_invoice(self.source,self.actor,self.jid))
        self.assertEqual(self.draft()['invoice']['status'],'DRAFT')

    def test_parallel_customer_and_invoice_retry_exactly_once(self):
        self.connect()
        def concurrent(fn):
            barrier=threading.Barrier(4)
            def worker(_):
                try:barrier.wait();return fn()
                finally:
                    if getattr(db._local,'conn',None):db._local.conn.close();db._local.conn=None
            with ThreadPoolExecutor(max_workers=4) as pool:return list(pool.map(worker,range(4)))
        rows=concurrent(self.customer)
        self.assertTrue(all(row==rows[0] for row in rows))
        rows=concurrent(self.draft)
        self.assertTrue(all(row==rows[0] for row in rows))
        self.assertEqual(len(f.list_customers(self.target,actor_user_id=self.actor)),1)
        self.assertEqual(len(f.list_finance_invoices(self.target,actor_user_id=self.actor)),1)

    def test_immutable_history_and_foreign_actor_or_job_rejected(self):
        self.connect();self.customer();self.draft()
        for table in ('kw_core_finance_connections','kw_core_finance_customer_links','kw_core_finance_invoice_links','kw_core_finance_operations'):
            with self.assertRaises(Exception):db.execute('DELETE FROM '+table+' WHERE source_business_id=?',(self.source,))
        with self.assertRaises(bridge.BridgeError):bridge.read_invoice(self.source,self.foreign_actor,self.jid)
        with self.assertRaises(bridge.BridgeError):bridge.read_invoice(self.source,self.actor,'unknown')
        self.assertEqual(self.draft()['invoice']['status'],'DRAFT')

    def test_distinct_parallel_requests_cannot_create_two_job_invoices(self):
        self.connect();self.customer()
        barrier=threading.Barrier(2)
        def worker(key):
            try:
                barrier.wait()
                try:self.draft(operation_key=key);return 'created'
                except bridge.BridgeError as error:return error.code
            finally:
                if getattr(db._local,'conn',None):db._local.conn.close();db._local.conn=None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(worker,('a'*32,'b'*32)))
        self.assertEqual(sorted(results),['created','invoice_already_linked'])
        self.assertEqual(len(f.list_finance_invoices(self.target,actor_user_id=self.actor)),1)

    def test_inverse_business_connections_lock_in_consistent_order(self):
        db.execute("UPDATE businesses SET package='AI_ADMIN' WHERE id=?",(self.target,))
        subscription_service.create_subscription(self.target,'ai_admin',self.actor)
        f.ensure_finance_defaults(self.source,actor_user_id=self.actor)
        source_branch=branches.list_branches(self.source,self.actor)[0]['id']
        barrier=threading.Barrier(2)
        def worker(args):
            try:
                barrier.wait()
                source,target,branch=args
                return bridge.configure(source,self.actor,finance_business_id=target,finance_branch_id=branch,
                    expected_version=0,enabled_value=True,operation_key='a'*32,confirmed=True)
            finally:
                if getattr(db._local,'conn',None):db._local.conn.close();db._local.conn=None
        with patch.dict(os.environ,{'KILAS_CORE_V2_TEST_BUSINESS_IDS':f'{self.source},{self.target}'}):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(worker,((self.source,self.target,self.branch),(self.target,self.source,source_branch))))
        self.assertEqual(len(results),2)
        self.assertTrue(all(row['version']==1 for row in results))

    def test_personal_branch_and_unavailable_finance_product_fail_closed(self):
        personal=branches.ensure_personal(self.target,self.actor)
        with self.assertRaises(bridge.BridgeError):self.connect(finance_branch_id=personal)
        self.assertIsNone(bridge.connection(self.source,self.actor))
        with patch.dict(os.environ,{'KILAS_FINANCE_BETA':'off'}):
            with self.assertRaises(bridge.BridgeError):self.connect()
        self.assertIsNone(bridge.connection(self.source,self.actor))
