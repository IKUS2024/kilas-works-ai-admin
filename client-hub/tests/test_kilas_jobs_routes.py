"""Real owner Jobs routes with synthetic SQLite and independent tenant owners."""
import os
import unittest
from unittest.mock import patch
import test_kilas_customers as phase3


class JobRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        phase3.CustomerTests.setUpClass.__func__(cls)
        global jobs, customers, customer_action_jobs
        from kilas_core import jobs, customers, job_schema, customer_action_jobs
        job_schema.apply_schema()
        cls.db.execute('CREATE TABLE business_profiles(business_id INTEGER PRIMARY KEY,category TEXT)')
        cls.db.execute("INSERT INTO business_profiles VALUES (7,'Restaurant'),(8,'Salon')")

    tearDown = phase3.CustomerTests.tearDown
    start = phase3.CustomerTests.start
    send = phase3.CustomerTests.send

    def setUp(self):
        with jobs.transaction() as tx:
            tx.execute('DELETE FROM kw_core_job_operations')
            tx.execute('DELETE FROM kw_core_jobs')
        phase3.CustomerTests.setUp(self)
        flag=patch.dict(os.environ,{'KILAS_JOBS_V2_ENABLED':'true'})
        flag.start();self.addCleanup(flag.stop)
        self.identity=self.start().json
        self.cid=self.identity['conversation_id']
        self.customer=customers.customer_for_conversation(7,self.cid)
        customers.update_customer(
            7,self.customer['id'],display_name=self.customer['display_name'],stage='CUSTOMER')
        self.customer=customers.get_customer(7,self.customer['id'])
        self.form=dict(csrf_token='csrf-test',customer_id=self.customer['id'],conversation_id=self.cid,
                       title='Pesanan makan siang',summary='Untuk kantor',operation_key='route-create-0001')

    def create(self, **changes):
        return self.client.post('/business/7/jobs',data={**self.form,**changes})

    def test_owner_create_detail_update_audit(self):
        page=self.client.get('/business/7/jobs/new?customer_id='+self.customer['id']+'&conversation_id='+self.cid)
        self.assertEqual(page.status_code,200)
        self.assertIn(b'Buat Pesanan',page.data)
        response=self.create();self.assertEqual(response.status_code,303)
        job=jobs.list_jobs(7)[0][0]
        self.assertEqual(job['kind'],'ORDER')
        self.assertIn(b'Pesanan makan siang',self.client.get(response.location).data)
        edited=self.client.post(f"/business/7/jobs/{job['id']}",data=dict(csrf_token='csrf-test',title='Makan siang revisi',
                 summary='Besok',status='NEEDS_INFORMATION',version=1,operation_key='route-update-0001'))
        self.assertEqual(edited.status_code,303)
        self.assertEqual(jobs.get_job(7,job['id'])['status'],'NEEDS_INFORMATION')
        self.assertEqual(self.db.query_one("SELECT COUNT(*) AS n FROM audit_log WHERE action LIKE 'JOB_%'")['n'],2)

    def test_form_csrf_unknown_payload_and_status_rejected(self):
        for changes in ({'csrf_token':'bad'},{'business_id':8},{'kind':'FINANCE'},
                        {'status':'COMPLETED'},{'field_token':'secret'},{'field_quantity':'oops'}):
            self.assertEqual(self.create(**changes).status_code,400)
        self.assertEqual(jobs.list_jobs(7)[1],0)
        self.assertEqual(self.create(summary='x'*25000).status_code,413)
        self.assertEqual(self.client.post('/business/7/jobs',json=self.form,headers={'X-CSRF-Token':'csrf-test'}).status_code,400)

    def test_foreign_customer_conversation_job_and_owner(self):
        other=self.start(slug=self.other_slug,client=self.app.test_client()).json
        foreign=customers.customer_for_conversation(8,other['conversation_id'])
        for changes in ({'customer_id':foreign['id']},{'conversation_id':other['conversation_id']}):
            self.assertEqual(self.create(**changes).status_code,404)
        self.assertEqual(self.create().status_code,303)
        job=jobs.list_jobs(7)[0][0]
        self.assertEqual(self.client.get('/business/8/jobs/'+job['id']).status_code,404)
        with self.client.session_transaction() as session: session['user_id']=2
        for path in ('/business/7/jobs','/business/7/jobs/'+job['id'],'/business/8/jobs/'+job['id']):
            self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.client.post('/business/7/jobs/'+job['id'],data={'csrf_token':'csrf-test'}).status_code,404)
        self.assertEqual(self.client.get('/business/8/jobs').status_code,200)
        self.assertEqual(jobs.get_job(7,job['id'])['version'],1)

    def test_gates_and_finance_session(self):
        # Manual owner Jobs workspace is gated by the Jobs + Customers product flags.
        for flag in ('KILAS_JOBS_V2_ENABLED','KILAS_CUSTOMERS_V2_ENABLED'):
            with patch.dict(os.environ,{flag:'false'}):
                self.assertEqual(self.client.get('/business/7/jobs').status_code,404)
                self.assertEqual(self.create().status_code,404)
        # Core rollout is intentionally a stricter automation/channel gate. Owners may
        # still explore and use their own manual Jobs workspace before Core rollout.
        with patch.dict(os.environ,{'KILAS_CORE_V2_ENABLED':'false'}):
            self.assertEqual(self.client.get('/business/7/jobs').status_code,200)
        self.db.execute("UPDATE subscriptions SET status='SUSPENDED' WHERE business_id=7")
        # Subscription gates automated/channel-linked availability, not the owner's
        # pre-onboarding manual Jobs workspace.
        self.assertEqual(self.client.get('/business/7/jobs').status_code,200)
        self.db.execute("UPDATE subscriptions SET status='ACTIVE' WHERE business_id=7")
        self.db.execute("UPDATE businesses SET package='FINANCE' WHERE id=7")
        self.assertEqual(self.client.get('/business/7/jobs').status_code,404)
        self.db.execute("UPDATE businesses SET package='AI_ADMIN' WHERE id=7")
        with self.client.session_transaction() as session: session['active_product']='finance'
        response=self.client.get('/business/7/jobs')
        self.assertEqual(response.status_code,200)
        self.assertNotIn('finance-app-sidebar',response.text)
        self.assertEqual(self.create().status_code,303)
        self.assertEqual(jobs.list_jobs(7)[1],1)


    def test_customer_and_inbox_manual_job_linkage(self):
        with patch.object(self.ai,'_call_claude',return_value=('Jawaban bisnis','end_turn',None)):
            self.assertEqual(self.send(self.identity).status_code,200)
        detail='/business/7/customers/'+self.customer['id']
        inbox='/business/7/inbox?channel=web&conversation='+self.cid
        for path in (detail,inbox):
            page=self.client.get(path)
            self.assertEqual(page.status_code,200)
            self.assertIn(b'data-create-job',page.data)
        # Server resolves the customer from the selected conversation.
        new=self.client.get('/business/7/jobs/new?conversation_id='+self.cid)
        self.assertEqual(new.status_code,200)
        self.assertIn(self.customer['id'].encode(),new.data)
        self.assertEqual(self.create().status_code,303)
        job=jobs.list_jobs(7)[0][0]
        for path in (detail,inbox):
            page=self.client.get(path)
            self.assertIn(('/business/7/jobs/'+job['id']).encode(),page.data)
            self.assertIn(b'Pesanan makan siang',page.data)
        page=self.client.get('/business/7/jobs/'+job['id'])
        self.assertIn(detail.encode(),page.data)
        self.assertIn(b'data-job-conversation',page.data)
        with patch.dict(os.environ,{'KILAS_JOBS_V2_ENABLED':'false'}):
            self.assertNotIn(b'data-linked-jobs',self.client.get(detail).data)
            self.assertNotIn(b'data-linked-jobs',self.client.get(inbox).data)


    def test_stale_version_retry_conflict_and_rendered_text_escaping(self):
        self.assertEqual(self.create(title='<script>alert(1)</script>').status_code,303)
        self.assertEqual(self.create(title='<script>alert(1)</script>').status_code,303)
        job=jobs.list_jobs(7)[0][0];path='/business/7/jobs/'+job['id']
        self.assertIn(b'&lt;script&gt;',self.client.get(path).data)
        self.assertNotIn(b'<script>alert(1)</script>',self.client.get(path).data)
        data=dict(csrf_token='csrf-test',title='Updated',summary='',status='NEEDS_INFORMATION',version=1,operation_key='retry-update-0001')
        for _ in range(2): self.assertEqual(self.client.post(path,data=data).status_code,303)
        self.assertEqual(self.client.post(path,data={**data,'operation_key':'stale-update-0001'}).status_code,409)
        self.assertEqual(self.client.post(path,data={**data,'version':2,'status':'COMPLETED','operation_key':'bad-status-00001'}).status_code,409)
        self.assertEqual(jobs.get_job(7,job['id'])['version'],2)
        self.assertEqual(self.client.get('/business/7/jobs?status=BAD').status_code,400)
        self.assertEqual(self.client.get('/business/7/jobs?customer_id=foreign').status_code,404)
        self.assertEqual(self.client.get('/business/7/jobs?q=Updated&status=NEEDS_INFORMATION').status_code,200)
        self.assertEqual(self.app.test_client().get('/business/7/jobs').status_code,302)

    def test_jobs_have_no_finance_legacy_order_whatsapp_or_model_writes(self):
        import sqlite3
        from contextlib import ExitStack
        denied=[]
        def authorize(action,table,*args):
            if action in (sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE):
                if table not in ('kw_core_jobs','kw_core_job_operations','audit_log','sqlite_sequence'):
                    denied.append(table);return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        original=sqlite3.connect
        def guarded(*args,**kwargs):
            conn=original(*args,**kwargs);conn.set_authorizer(authorize);return conn
        self.db.get_connection().set_authorizer(authorize)
        try:
            with ExitStack() as stack:
                stack.enter_context(patch('sqlite3.connect',side_effect=guarded))
                spies=[stack.enter_context(patch.object(self.finance,name)) for name in
                       ('create_transaction','create_finance_invoice','record_invoice_payment','create_customer')]
                spies.append(stack.enter_context(patch('inbox_service.send_manual_reply')))
                spies.append(stack.enter_context(patch.object(self.ai,'_call_claude')))
                self.assertEqual(self.create().status_code,303)
                row=jobs.list_jobs(7)[0][0]
                response=self.client.post('/business/7/jobs/'+row['id'],data=dict(csrf_token='csrf-test',
                         title='Approved manual details',summary='',status='READY_FOR_QUOTE',version=1,operation_key='safe-update-0001'))
                self.assertEqual(response.status_code,303)
                for spy in spies: spy.assert_not_called()
            self.assertEqual(denied,[])
        finally: self.db.get_connection().set_authorizer(None)

    def test_customer_insight_creates_one_short_action_for_customer_only(self):
        business = {'id': 7}
        insight = {
            'summary': 'Customer tertarik dan ingin booking konsultasi untuk kebutuhan parfum.',
            'name': None, 'business_name': None, 'business_type': 'parfum',
            'location': None, 'budget': None,
            'interests': ['Kilas Assist'], 'needs': ['booking konsultasi'],
            'buying_stage': 'BERMINAT',
            'buying_signal_reason': 'Customer menyebut ingin booking.',
            'communication_notes': None,
            'missing_info': ['tanggal booking'],
            'follow_up': 'Tanyakan tanggal yang diinginkan untuk booking konsultasi.',
            '_meta': {'has_history': True, 'fresh': True, 'message_count': 3},
        }
        first = customer_action_jobs.sync_from_insight(business, self.customer, insight)
        self.assertIsNotNone(first)
        self.assertEqual(first['customer_id'], self.customer['id'])
        self.assertEqual(first['status'], 'NEW')
        self.assertEqual(first['fields']['source'], 'Customer Insight')
        self.assertEqual(first['fields']['action'], 'Mau booking konsultasi')
        self.assertEqual(first['summary'], 'Mau booking konsultasi')

        # Same customer/intent stays one Job.
        again = customer_action_jobs.sync_from_insight(business, self.customer, insight)
        self.assertEqual(again['id'], first['id'])
        self.assertEqual(jobs.list_jobs(7)[1], 1)

        updated_insight = {
            **insight,
            'buying_stage': 'SIAP_MEMBELI',
            'follow_up': 'Konfirmasi tanggal booking dan langkah berikutnya.',
            '_meta': {'has_history': True, 'fresh': True, 'message_count': 4},
        }
        updated = customer_action_jobs.sync_from_insight(business, self.customer, updated_insight)
        self.assertEqual(updated['id'], first['id'])
        self.assertEqual(updated['fields']['priority'], 'Tinggi')
        self.assertEqual(updated['fields']['action'], 'Mau booking konsultasi')

        page = self.client.get('/business/7/jobs')
        self.assertEqual(page.status_code, 200)
        self.assertIn(self.customer['display_name'].encode(), page.data)
        self.assertIn(b'Mau booking konsultasi', page.data)
        self.assertNotIn(b'Mencari informasi', page.data)

    def test_lead_never_appears_in_jobs_until_promoted_to_customer(self):
        business = {'id': 7}
        customers.update_customer(
            7,self.customer['id'],display_name=self.customer['display_name'],stage='LEAD')
        lead = customers.get_customer(7,self.customer['id'])
        insight = {
            'summary': 'Lead ingin tahu paket yang tersedia untuk bisnis parfum.',
            'interests': ['Kilas Assist'], 'needs': ['informasi paket yang tersedia'],
            'buying_stage': 'MENCARI_INFORMASI',
            'missing_info': [], 'follow_up': 'Jelaskan paket yang relevan.',
            '_meta': {'has_history': True, 'fresh': True, 'message_count': 3},
        }
        self.assertIsNone(customer_action_jobs.sync_from_insight(business, lead, insight))
        page = self.client.get('/business/7/jobs')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Belum ada tindakan', page.data)
        self.assertNotIn(b'informasi paket', page.data)
        self.assertEqual(
            self.client.get('/business/7/jobs/new?customer_id='+lead['id']).status_code,404)

        # Even a legacy/raw Job linked to a Lead is hidden from the Customer-only Jobs page.
        raw = jobs.create_job(
            7,lead['id'],title='Legacy lead action',summary='hidden',
            actor_id=1,operation_key='legacy-lead-job-0001')
        self.assertIsNotNone(raw)
        hidden = self.client.get('/business/7/jobs')
        self.assertNotIn(b'Legacy lead action', hidden.data)

        customers.update_customer(
            7,lead['id'],display_name=lead['display_name'],stage='CUSTOMER')
        customer = customers.get_customer(7,lead['id'])
        result = customer_action_jobs.sync_from_insight(business, customer, insight)
        # Existing manual Job wins rather than creating a duplicate.
        self.assertEqual(result['id'], raw['id'])
        visible = self.client.get('/business/7/jobs')
        self.assertIn(b'Legacy lead action', visible.data)


    def test_customer_insight_skips_noise_and_never_duplicates_manual_job(self):
        business = {'id': 7}
        noise = {
            'summary': 'Customer hanya menyapa.',
            'interests': [], 'needs': [], 'buying_stage': 'BELUM_JELAS',
            'missing_info': [], 'follow_up': None,
            '_meta': {'has_history': True, 'fresh': True, 'message_count': 1},
        }
        self.assertIsNone(customer_action_jobs.sync_from_insight(business, self.customer, noise))
        self.assertEqual(jobs.list_jobs(7)[1], 0)

        manual = jobs.create_job(
            7, self.customer['id'], title='Hubungi customer manual',
            summary='Owner sudah membuat tindakan sendiri.',
            actor_id=1, operation_key='manual-action-job-0001', fields={'details':'Manual'},
        )
        actionable = {
            'summary': 'Customer meminta price list.',
            'interests': ['paket'], 'needs': ['informasi harga'],
            'buying_stage': 'MENCARI_INFORMASI',
            'buying_signal_reason': 'Meminta harga.',
            'missing_info': [], 'follow_up': 'Kirim dan jelaskan pilihan paket.',
            '_meta': {'has_history': True, 'fresh': True, 'message_count': 2},
        }
        result = customer_action_jobs.sync_from_insight(business, self.customer, actionable)
        self.assertEqual(result['id'], manual['id'])
        self.assertEqual(jobs.list_jobs(7)[1], 1)
        self.assertNotEqual(jobs.list_jobs(7)[0][0]['fields'].get('source'), 'Customer Insight')

    def test_chat_and_simulator_never_create_jobs_automatically(self):
        with patch.object(self.ai,'_call_claude',return_value=('Kami bantu pesanan Anda','end_turn',None)):
            self.assertEqual(self.send(self.identity,text='Buat pesanan 20 kopi').status_code,200)
        self.assertEqual(jobs.list_jobs(7)[1],0)
        with patch.object(self.ai,'simulate_customer_reply',return_value=('Siap',None)):
            response=self.client.post('/business/7/simulate/message',json={'message':'Buat job sekarang'},
                                      headers={'X-CSRF-Token':'csrf-test'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(jobs.list_jobs(7)[1],0)


if __name__=='__main__': unittest.main()
