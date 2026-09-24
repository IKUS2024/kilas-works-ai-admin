"""Phase 5 real WEB routes with synthetic tenants; independent unittest discovery."""
import json
import os
import unittest
from unittest.mock import patch
import test_kilas_jobs_routes as phase4


def output(text, fields=None, intent='REQUEST', **changes):
    fields = fields or {}
    return json.dumps(dict(intent=intent,fields=fields,evidence={key:text for key in fields},corrections=[],ambiguous=[],**changes))


class PlaybookRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        phase4.JobRoutesTests.setUpClass.__func__(cls)
        global jobs, store
        from kilas_core import jobs
        from public_chat import store

    tearDown = phase4.JobRoutesTests.tearDown
    start = phase4.JobRoutesTests.start
    send = phase4.JobRoutesTests.send

    def setUp(self):
        phase4.JobRoutesTests.setUp(self)
        flag = patch.dict(os.environ, {'KILAS_PLAYBOOKS_V2_ENABLED':'true'})
        flag.start(); self.addCleanup(flag.stop)
        self.db.execute("UPDATE business_profiles SET category='Logistics' WHERE business_id=7")

    def deliver(self, text='Mau kirim 20 kg baju dari Guangzhou ke Tangerang', fields=None, event='phase5-event-0001', raw=None):
        fields = fields if fields is not None else {'item':'baju','weight':'20 kg','origin':'Guangzhou','destination':'Tangerang'}
        with patch.object(self.ai,'_call_claude',return_value=(raw if raw is not None else output(text,fields),'end_turn',None)) as model:
            result = self.send(self.identity,text=text,event=event)
        return result, model

    def test_create_retry_followup_one_call(self):
        result, model = self.deliver()
        self.assertEqual(result.status_code,200)
        self.assertEqual(model.call_count,1)
        first = jobs.list_jobs(7)[0][0]
        result, model = self.deliver()
        self.assertEqual(result.status_code,200)
        model.assert_not_called()
        self.assertEqual(jobs.list_jobs(7)[0][0]['version'],first['version'])
        result, model = self.deliver(text='volumenya 0.2 m3',fields={'volume_cbm':'0.2 m³'},event='phase5-event-0002')
        self.assertEqual(result.status_code,200)
        self.assertEqual(model.call_count,1)
        second = jobs.list_jobs(7)[0][0]
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(second['status'],'READY_FOR_QUOTE')
        self.assertEqual(second['customer_id'],self.customer['id'])
        messages = store.thread(7,self.cid)
        self.assertEqual(len(messages),4)
        self.assertIn('volume',messages[1]['content'])
        self.assertNotIn('berat',messages[1]['content'])

    def test_provider_error_malformed_and_action_tags_no_partial_write(self):
        for index, raw in enumerate(('not json','[CREATE_JOB] [PAYMENT]','{"action":"create_invoice"}')):
            result, model = self.deliver(event='phase5-invalid-'+str(index),raw=raw)
            self.assertEqual(result.status_code,502)
        with patch.object(self.ai,'_call_claude',side_effect=RuntimeError('provider down')):
            self.assertEqual(self.send(self.identity,text='kiriman',event='phase5-provider-fail').status_code,502)
        self.assertEqual(jobs.list_jobs(7)[1],0)
        self.assertFalse(any(r['role']=='assistant' for r in store.thread(7,self.cid)))

    def test_human_takeover_during_inference_and_after(self):
        def inference(*args,**kwargs):
            store.set_mode(7,self.cid,'HUMAN_TAKEOVER',1)
            return output('baju',{'item':'baju'}),'end_turn',None
        with patch.object(self.ai,'_call_claude',side_effect=inference):
            self.assertEqual(self.send(self.identity,text='baju',event='phase5-takeover-01').status_code,200)
        result, model = self.deliver(event='phase5-after-human')
        self.assertEqual(result.status_code,200)
        model.assert_not_called()
        self.assertEqual(jobs.list_jobs(7)[1],0)
        self.assertFalse(any(r['role']=='assistant' for r in store.thread(7,self.cid)))

    def test_action_failure_rolls_back_job_and_success_reply(self):
        with patch.object(jobs,'_update_job',side_effect=RuntimeError('DB action unavailable')):
            result, _ = self.deliver()
        self.assertEqual(result.status_code,502)
        self.assertEqual(jobs.list_jobs(7)[1],0)
        self.assertEqual(self.db.query_one('SELECT COUNT(*) AS n FROM kw_core_job_operations')['n'],0)
        self.assertFalse(any(r['role']=='assistant' for r in store.thread(7,self.cid)))

    def test_owner_edit_during_inference_survives(self):
        self.assertEqual(self.deliver()[0].status_code,200)
        row = jobs.list_jobs(7)[0][0]
        def inference(*args,**kwargs):
            jobs.update_job(7,row['id'],expected_version=row['version'],actor_id=1,operation_key='owner-during-0001',title='Rincian dari pemilik')
            return output('0.2 m3',{'volume_cbm':'0.2 m³'}),'end_turn',None
        with patch.object(self.ai,'_call_claude',side_effect=inference):
            self.assertEqual(self.send(self.identity,text='0.2 m3',event='phase5-owner-race').status_code,200)
        current = jobs.get_job(7,row['id'])
        self.assertEqual(current['title'],'Rincian dari pemilik')
        self.assertNotIn('volume_cbm',current['fields'])
        self.assertIn('Tim baru memperbarui',store.thread(7,self.cid)[-1]['content'])

    def test_disabled_flag_keeps_legacy_text_only(self):
        with patch.dict(os.environ,{'KILAS_PLAYBOOKS_V2_ENABLED':'false'}):
            result, _ = self.deliver(raw='Jawaban bisnis lama')
        self.assertEqual(result.status_code,200)
        self.assertEqual(jobs.list_jobs(7)[1],0)
        self.assertEqual(store.thread(7,self.cid)[-1]['content'],'Jawaban bisnis lama')

    def test_owner_context_manual_edit_and_metadata_protection(self):
        self.assertEqual(self.deliver()[0].status_code,200)
        row = jobs.list_jobs(7)[0][0]
        for path in ('/business/7/inbox?channel=web&conversation='+self.cid, '/business/7/jobs/'+row['id']):
            page = self.client.get(path)
            self.assertEqual(page.status_code,200)
            self.assertIn(b'data-playbook-context',page.data)
            for text in ('Guangzhou','Tangerang','20 kg','volume','Masih dibutuhkan'):
                self.assertIn(text.encode(),page.data)
            self.assertNotIn(b'field_uncertain_fields',page.data)
            self.assertNotIn(b'field_playbook',page.data)
        store.set_mode(7,self.cid,'HUMAN_TAKEOVER',1)
        data = dict(csrf_token='csrf-test',title='Pengiriman revisi pemilik',summary='',status=row['status'],
                    version=row['version'],operation_key='manual-phase5-0001',field_item='baju',field_weight='20 kg',
                    field_origin='Shanghai',field_destination='Tangerang',field_volume_cbm='0.3 m3')
        response = self.client.post('/business/7/jobs/'+row['id'],data=data)
        self.assertEqual(response.status_code,303)
        current = jobs.get_job(7,row['id'])
        self.assertEqual(current['fields']['playbook'],'LOGISTICS')
        self.assertEqual(current['fields']['missing_information'],'')
        self.assertEqual(current['fields']['origin'],'Shanghai')
        rejected = self.client.post('/business/7/jobs/'+row['id'],data={**data,'field_playbook':'BOOKING_SERVICE'})
        self.assertEqual(rejected.status_code,400)

    def test_no_finance_legacy_or_whatsapp_writes(self):
        import sqlite3
        from contextlib import ExitStack
        denied=[]
        def authorize(action,table,*args):
            if action in (sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE):
                if not (table.startswith(('kw_web_','kw_core_')) or table in ('audit_log','sqlite_sequence','ai_usage_ledger')):
                    denied.append(table)
                    return sqlite3.SQLITE_DENY
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
                spies.append(stack.enter_context(patch('inbox_service.send_manual_reply')))
                self.assertEqual(self.deliver()[0].status_code,200)
                self.assertEqual(self.deliver(text='0.2 m3',fields={'volume_cbm':'0.2 m³'},event='protected-event-02')[0].status_code,200)
                for spy in spies: spy.assert_not_called()
            self.assertEqual(denied,[])
        finally:
            self.db.get_connection().set_authorizer(None)

    def test_tenant_web_and_owner_cannot_forge_references(self):
        self.assertEqual(self.deliver()[0].status_code,200)
        row=jobs.list_jobs(7)[0][0]
        with patch.object(self.ai,'_call_claude') as model:
            self.assertEqual(self.send(self.identity,text='baju',event='forged-refs-00001',extra={'job_id':row['id']}).status_code,400)
            self.assertEqual(self.send(self.identity,text='baju',event='forged-refs-00002',slug=self.other_slug).status_code,404)
            model.assert_not_called()
        with self.client.session_transaction() as session: session['user_id']=2
        for path in ('/business/7/jobs/'+row['id'],'/business/8/jobs/'+row['id'],
                     '/business/7/customers/'+row['customer_id'],'/business/7/inbox?channel=web&conversation='+self.cid):
            self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.client.post('/business/8/jobs/'+row['id'],data={'csrf_token':'csrf-test'}).status_code,404)
        self.assertEqual(jobs.get_job(7,row['id'])['version'],row['version'])

    def test_business_redirect_and_booking_no_known_reask(self):
        result, _ = self.deliver(text='Tulis puisi tentang planet',raw=output('Tulis puisi tentang planet',intent='UNRELATED'))
        self.assertEqual(result.status_code,200)
        self.assertEqual(jobs.list_jobs(7)[1],0)
        self.assertIn('bisnis ini',store.thread(7,self.cid)[-1]['content'])
        self.db.execute("UPDATE business_profiles SET category='Salon' WHERE business_id=7")
        fields={'service':'potong rambut','preferred_date':'besok','preferred_time':'14.00'}
        self.assertEqual(self.deliver(text='potong rambut besok jam 14',fields=fields,event='booking-event-001')[0].status_code,200)
        row=jobs.list_jobs(7)[0][0]
        self.assertEqual(row['kind'],'BOOKING')
        self.assertEqual(row['fields']['missing_information'],'')
        reply=store.thread(7,self.cid)[-1]['content']
        self.assertNotIn('Boleh informasikan',reply)
        self.assertIn('belum ada pesanan atau booking yang dikonfirmasi',reply)

    def test_revoked_flag_during_provider_no_job(self):
        def inference(*args,**kwargs):
            os.environ['KILAS_PLAYBOOKS_V2_ENABLED']='false'
            return output('baju',{'item':'baju'}),'end_turn',None
        with patch.object(self.ai,'_call_claude',side_effect=inference):
            self.assertEqual(self.send(self.identity,text='baju',event='revoked-event-001').status_code,502)
        self.assertEqual(jobs.list_jobs(7)[1],0)


if __name__ == '__main__': unittest.main()
