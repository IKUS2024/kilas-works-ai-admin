"""Shared deterministic SQLite/PostgreSQL assertions; no unittest class discovery."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from kilas_core import jobs, job_schema


class Cases:
    def seed(self):
        with jobs.transaction() as tx:
            tx.execute('DELETE FROM kw_core_job_operations')
            tx.execute('DELETE FROM kw_core_jobs')
            tx.execute('DELETE FROM audit_log')
            for bid, cid in ((7,'alice'),(7,'bob'),(8,'other')):
                tx.execute("INSERT INTO kw_core_customers(business_id,id,display_name,source_channel,created_at,updated_at,last_activity_at) "
                           "VALUES (?,?,?,'WEB',1,1,1) ON CONFLICT(business_id,id) DO NOTHING",(bid,cid,cid))
            for bid, cid, cust in ((7,'conv','alice'),(7,'second','bob'),(8,'foreign','other')):
                tx.execute("INSERT INTO kw_web_channels(business_id,slug) VALUES (?,?) ON CONFLICT(business_id) DO NOTHING",(bid,str(bid)))
                tx.execute('INSERT INTO kw_web_conversations(business_id,id,visitor_hash,expires_at,created_at,updated_at) VALUES (?,?,?,100,1,1) '
                           'ON CONFLICT(business_id,id) DO NOTHING',(bid,cid,cid))
                tx.execute('INSERT INTO kw_web_customer_links VALUES (?,?,?,1) ON CONFLICT(business_id,conversation_id) DO NOTHING',(bid,cid,cust))

    def create(self, **changes):
        data=dict(business_id=7,customer_id='alice',conversation_id='conv',title='Pesanan kopi',actor_id=1,
                  operation_key='create-operation-01')
        data.update(changes)
        return jobs.create_job(**data)

    def update(self, row, **changes):
        data=dict(business_id=row['business_id'],job_id=row['id'],expected_version=row['version'],
                  actor_id=1,operation_key='update-operation-'+str(row['version']))
        data.update(changes)
        return jobs.update_job(**data)

    def test_create_replay_conflict_and_audit(self):
        first=self.create(); again=self.create()
        self.assertEqual(first,again)
        with self.assertRaises(jobs.JobError) as error: self.create(title='Changed')
        self.assertEqual(error.exception.status,409)
        with jobs.transaction() as tx:
            audits=tx.execute('SELECT * FROM audit_log')
            self.assertEqual(len(audits),1)
            self.assertEqual(audits[0]['actor_user_id'],1)
            self.assertEqual(json.loads(audits[0]['detail'])['job_id'],first['id'])

    def test_references_fail_closed(self):
        for changes in ({'customer_id':'other'},{'conversation_id':'foreign'},
                        {'conversation_id':'second'},{'customer_id':'missing'}):
            with self.assertRaises(jobs.JobError) as error: self.create(**changes)
            self.assertEqual(error.exception.status,404)
        self.assertEqual(jobs.list_jobs(7)[1],0)

    def test_database_rejects_mismatched_links(self):
        first=self.create()
        with self.assertRaises(Exception):
            with jobs.transaction() as tx:
                tx.execute("UPDATE kw_core_jobs SET customer_id='bob' WHERE business_id=7 AND id=?",(first['id'],))
        self.assertEqual(jobs.get_job(7,first['id'])['customer_id'],'alice')

    def test_tenants_independent_same_operation_key(self):
        first=self.create()
        other=self.create(business_id=8,customer_id='other',conversation_id='foreign',actor_id=2)
        self.assertNotEqual(first['id'],other['id'])
        with self.assertRaises(jobs.JobError): jobs.get_job(8,first['id'])
        with self.assertRaises(jobs.JobError): self.update(first,business_id=8)
        self.assertEqual(jobs.list_jobs(7)[1],1)
        self.assertEqual(jobs.list_jobs(8)[0][0]['id'],other['id'])

    def test_lifecycle_forward_only_and_terminal(self):
        row=self.create()
        for status in ('NEEDS_INFORMATION','READY_FOR_QUOTE','QUOTED','APPROVED','IN_PROGRESS','COMPLETED'):
            row=jobs.transition_job(7,row['id'],status,expected_version=row['version'],actor_id=1,
                                    operation_key='transition-'+status)
            self.assertEqual(row['status'],status)
        for status in ('NEW','CANCELLED','PAID','unexpected'):
            with self.assertRaises(jobs.JobError): self.update(row,status=status)
        self.assertEqual(jobs.get_job(7,row['id'])['version'],7)

    def test_invalid_transition_rollback_and_cancel(self):
        row=self.create()
        with self.assertRaises(jobs.JobError): self.update(row,status='COMPLETED',title='Rejected edit')
        self.assertEqual(jobs.get_job(7,row['id'])['title'],row['title'])
        cancelled=self.update(row,status='CANCELLED')
        with self.assertRaises(jobs.JobError): self.update(cancelled,status='NEW')

    def test_update_replay_stale_and_payload_conflict(self):
        row=self.create()
        changed=self.update(row,title='Updated',fields={'quantity':2,'unit':'cup'})
        self.assertEqual(self.update(row,title='Updated',fields={'quantity':2,'unit':'cup'}),changed)
        with self.assertRaises(jobs.JobError): self.update(row,title='Different')
        with self.assertRaises(jobs.JobError): self.update(row,operation_key='other-update-0001',title='Stale')
        newer=self.update(changed,summary='Newer')
        self.assertEqual(self.update(row,title='Updated',fields={'quantity':2,'unit':'cup'})['version'],newer['version'])
        with jobs.transaction() as tx:
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM audit_log')['n'],3)

    def test_search_filter_pagination_customer_scope(self):
        for i in range(12): self.create(title='Coffee '+str(i),operation_key='many-create-'+str(i).zfill(5))
        other=self.create(customer_id='bob',conversation_id=None,title='Service',operation_key='bob-create-00001')
        self.update(other,status='CANCELLED')
        self.create(business_id=8,customer_id='other',conversation_id='foreign',actor_id=2,title='Coffee foreign')
        rows,total,page,pages=jobs.list_jobs(7,search='Coffee')
        self.assertEqual((len(rows),total,page,pages),(10,12,1,2))
        self.assertEqual(len(jobs.list_jobs(7,search='Coffee',page=2)[0]),2)
        self.assertEqual(jobs.list_jobs(7,status='CANCELLED')[1],1)
        self.assertEqual(jobs.jobs_for_customer(7,'bob')[0]['id'],other['id'])
        with self.assertRaises(jobs.JobError): jobs.jobs_for_customer(7,'other')

    def test_fields_limits_types_and_explicit_keys(self):
        for fields in ([],{'token':'secret'},{'unknown':'x'},{'details':{}},{'quantity':True},
                       {'quantity':float('nan')},{'quantity':-1},{'details':'x'*1001},
                       {key:'🔥'*1000 for key in jobs.FIELD_LABELS}):
            with self.assertRaises(jobs.JobError): self.create(fields=fields)
        row=self.create(fields={'details':'Besok','quantity':2,'missing_information':'Alamat'})
        self.assertEqual(row['fields']['quantity'],2)
        with self.assertRaises(jobs.JobError): self.update(row,title='')

    def test_actor_and_operation_required(self):
        for changes in ({'actor_id':None},{'actor_id':True},{'business_id':False},
                        {'operation_key':'short'},{'operation_key':'x'*129},{'kind':'FINANCE'}):
            with self.assertRaises(jobs.JobError): self.create(**changes)

    def test_atomic_audit_failure_rolls_back(self):
        from unittest.mock import patch
        with patch.object(jobs,'_record',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError): self.create()
        self.assertEqual(jobs.list_jobs(7)[1],0)
        self.assertEqual(self.create()['version'],1)

    def test_label_mapping_and_fallback(self):
        for category,kind in [('Restaurant','ORDER'),('Retail','ORDER'),('Salon','BOOKING'),
                              ('Logistics / freight','SHIPMENT'),('Agency Videography','PROJECT'),
                              ('Workshop repair','SERVICE'),('', 'GENERIC'),('unknown','GENERIC')]:
            result=jobs.presentation(category)
            self.assertEqual(result['kind'],kind)
            self.assertTrue(result['singular']);self.assertTrue(result['plural'])

    def test_concurrent_idempotent_create(self):
        barrier=threading.Barrier(4)
        def run(_): barrier.wait();return self.create()
        with ThreadPoolExecutor(max_workers=4) as pool: rows=list(pool.map(run,range(4)))
        self.assertEqual(len({r['id'] for r in rows}),1)
        self.assertEqual(jobs.list_jobs(7)[1],1)
        with jobs.transaction() as tx: self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM audit_log')['n'],1)

    def test_concurrent_update_one_winner_and_same_key_retry(self):
        row=self.create();barrier=threading.Barrier(2)
        def run(i):
            barrier.wait()
            try: return self.update(row,title='Winner '+str(i),operation_key='concurrent-update-'+str(i))
            except jobs.JobError as error: return error.status
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(run,range(2)))
        self.assertEqual(sum(r==409 for r in results),1)
        current=jobs.get_job(7,row['id']);barrier=threading.Barrier(2)
        def retry(_): barrier.wait();return self.update(current,title='Same retry',operation_key='identical-update-01')
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(retry,range(2)))
        self.assertEqual(results[0],results[1]);self.assertEqual(results[0]['version'],3)

    def test_installer_idempotent_preserves_data(self):
        row=self.create();job_schema.apply_schema();job_schema.apply_schema()
        self.assertEqual(jobs.get_job(7,row['id']),row)
