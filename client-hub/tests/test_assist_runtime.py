"""Production WhatsApp uses the owner's knowledge, one inference, and fenced CRM/Jobs writes."""
import json
import os
import time
import unittest
from unittest.mock import patch
import test_client_hub_v1 as fixture
from public_chat import schema,store
from kilas_core import customer_schema,job_schema,whatsapp_schema,customers,jobs,whatsapp_access
from kilas_core.adapters import whatsapp as wa
import assist_reply
import ai_router

repo,db=fixture.repo,fixture.db

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        fixture.reset_db();schema.apply_schema();customer_schema.apply_schema();job_schema.apply_schema();whatsapp_schema.apply_schema()
        self.uid=repo.create_user('owner@test.invalid','hash')
        self.bid=repo.create_business(self.uid,'Foto Satu','AI_ADMIN')
        self.other=repo.create_business(self.uid,'Foto Dua','AI_ADMIN')
        repo.replace_business_faqs(self.bid,['Harga foto produk Rp500.000; diskon perlu izin pemilik'])
        repo.replace_business_faqs(self.other,['SECRET OF OTHER TENANT'])
        store.ensure_channel(self.bid);store.ensure_channel(self.other)
        self.flags=patch.dict(os.environ,{'KILAS_ASSIST_RUNTIME_ENABLED':'true','KILAS_PLAYBOOKS_V2_ENABLED':'true',
            'KILAS_JOBS_V2_ENABLED':'true','KILAS_CUSTOMERS_V2_ENABLED':'true','KILAS_OPERATIONS_V2_ENABLED':'false'})
        self.flags.start();self.addCleanup(self.flags.stop)
        self.channel=patch.object(whatsapp_access,'channel',side_effect=lambda bid,pid=None: {'phone_number_id':'456','access_token':'synthetic'} if bid==self.bid else None)
        self.channel.start();self.addCleanup(self.channel.stop)
        from kilas_core import whatsapp_transport
        self.send=patch.object(whatsapp_transport,'deliver',return_value={}).start();self.addCleanup(patch.stopall)
        self.n=0

    def receive(self,text,*,action=None,status=None,intent='QUESTION',side_effect=None):
        self.n+=1;eid='wamid.'+str(self.n)
        value={'messages':[{'id':eid,'from':'628111111111','timestamp':str(int(time.time())),'type':'text','text':{'body':text}}],
               'contacts':[{'wa_id':'628111111111','profile':{'name':'Nama Pelanggan'}}]}
        result=dict(reply='Baik, saya bantu sesuai ketentuan bisnis.',intent=intent,confidence=.95,
            evidence=text,knowledge_used=['profile'],insight=dict(summary=text,action=action,job_status=status))
        def infer(*args,**kwargs):
            self.assertNotIn('SECRET OF OTHER TENANT',str(args))
            if side_effect:side_effect()
            return json.dumps(result),'end_turn',None
        with patch.object(ai_router,'complete',side_effect=infer) as model:
            response=wa.handle(self.bid,'456',value,'messages')
        return response,model,eid

    def test_information_meeting_payment_cancel_and_same_call_explanation(self):
        _,model,_=self.receive('Berapa harga foto produk?')
        self.assertEqual(model.call_count,1)
        lead=db.query_one('SELECT * FROM kw_core_customers WHERE business_id=?',(self.bid,))
        self.assertEqual(lead['display_name'],'Nama Pelanggan');self.assertEqual(lead['phone'],'628111111111')
        self.assertEqual(customers.get_customer(self.bid,lead['id'])['stage'],'LEAD')
        self.assertEqual(jobs.list_jobs(self.bid)[1],0)
        self.receive('Saya mau meeting besok',action='Jadwalkan meeting besok',status='DIKERJAKAN',intent='REQUEST')
        self.assertEqual(customers.get_customer(self.bid,lead['id'])['stage'],'CUSTOMER')
        self.assertEqual(jobs.list_jobs(self.bid)[0][0]['status'],'NEW')
        self.receive('Belum mau bayar',action='Menunggu keputusan customer',status='DIKERJAKAN',intent='REQUEST')
        self.assertEqual(jobs.list_jobs(self.bid)[0][0]['status'],'NEW')
        _,model,eid=self.receive('Kirim invoice, saya mau bayar',action='Kirim invoice',status='DIKERJAKAN',intent='PAYMENT')
        self.assertEqual(jobs.list_jobs(self.bid)[0][0]['status'],'IN_PROGRESS')
        self.assertEqual(model.call_count,1)
        trace=db.query_one("SELECT detail FROM audit_log WHERE business_id=? AND action='AI_REPLY_EXPLANATION' ORDER BY id DESC LIMIT 1",(self.bid,))
        self.assertIn('Keyakinan' if False else 'confidence',trace['detail'])
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n'],0)
        self.assertEqual(jobs.list_jobs(self.other)[1],0)
        self.receive('Saya batal lanjut',action='Customer membatalkan',status='BATAL',intent='CANCEL')
        self.assertEqual(jobs.list_jobs(self.bid)[0][0]['status'],'CANCELLED')

    def test_takeover_during_model_discards_reply_and_state_writes(self):
        def take():
            row=db.query_one('SELECT conversation_id FROM kw_core_wa_conversations WHERE business_id=?',(self.bid,))
            wa.mode(self.bid,row['conversation_id'],'HUMAN_TAKEOVER',self.uid)
        self.receive('Saya mau booking',action='Booking foto',status='PERLU_TINDAKAN',intent='REQUEST',side_effect=take)
        self.assertEqual(jobs.list_jobs(self.bid)[1],0)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kw_web_messages WHERE role='assistant'")['n'],0)
        self.assertEqual(db.query_one('SELECT mode FROM kw_web_conversations')['mode'],'HUMAN_TAKEOVER')

    def test_customer_human_request_persists_until_owner_returns_control(self):
        self.receive('Saya ingin bicara dengan pemilik',intent='HUMAN')
        self.assertEqual(db.query_one('SELECT mode FROM kw_web_conversations')['mode'],'HUMAN_TAKEOVER')
        _,model,_=self.receive('Ada orang?')
        model.assert_not_called()
        self.assertEqual(jobs.list_jobs(self.bid)[1],0)
        self.assertEqual(db.query_one('SELECT mode FROM kw_web_conversations')['mode'],'HUMAN_TAKEOVER')

if __name__=='__main__':unittest.main()
