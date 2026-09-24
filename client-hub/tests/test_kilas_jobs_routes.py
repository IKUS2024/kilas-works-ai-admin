"""Real owner Jobs routes with synthetic SQLite and independent tenant owners."""
import os
import unittest
from unittest.mock import patch
import test_kilas_customers as phase3


class JobRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        phase3.CustomerTests.setUpClass.__func__(cls)
        global jobs, customers
        from kilas_core import jobs, customers, job_schema
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
        for flag in ('KILAS_JOBS_V2_ENABLED','KILAS_CUSTOMERS_V2_ENABLED','KILAS_CORE_V2_ENABLED'):
            with patch.dict(os.environ,{flag:'false'}):
                self.assertEqual(self.client.get('/business/7/jobs').status_code,404)
                self.assertEqual(self.create().status_code,404)
        self.db.execute("UPDATE subscriptions SET status='SUSPENDED' WHERE business_id=7")
        self.assertEqual(self.create().status_code,404)
        self.db.execute("UPDATE subscriptions SET status='ACTIVE' WHERE business_id=7")
        self.db.execute("UPDATE businesses SET package='FINANCE' WHERE id=7")
        self.assertEqual(self.client.get('/business/7/jobs').status_code,404)
        self.db.execute("UPDATE businesses SET package='AI_ADMIN' WHERE id=7")
        with self.client.session_transaction() as session: session['active_product']='finance'
        response=self.client.get('/business/7/jobs')
        self.assertEqual(response.status_code,303)
        self.assertIn('finance',response.location)
        self.assertEqual(self.create().status_code,303)
        self.assertEqual(jobs.list_jobs(7)[1],0)


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


if __name__=='__main__': unittest.main()
