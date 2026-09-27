"""Real transport demo boundaries, using a disposable DB and mocked transport/inference."""
import json
import os
import unittest
from unittest.mock import Mock, patch
import test_client_hub_v1 as fixture
import assist_demo as demo
import assist_reply
import platform_inbox_service
from public_chat import schema
from kilas_core import customer_schema, job_schema, customers, jobs

repo, db = fixture.repo, fixture.db


class DemoTests(unittest.TestCase):
    def setUp(self):
        fixture.reset_db()
        schema.apply_schema(); customer_schema.apply_schema(); job_schema.apply_schema()
        db.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT, mode TEXT, role TEXT, content TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        db.execute('CREATE TABLE customer_profiles(number TEXT PRIMARY KEY, name TEXT)')
        self.flags = patch.dict(os.environ, {'KILAS_CUSTOMERS_V2_ENABLED':'true','KILAS_JOBS_V2_ENABLED':'true'})
        self.flags.start(); self.addCleanup(self.flags.stop)
        self.ready = patch.object(demo.assist_journey,'state',return_value={
            'ready':True,'connected':False,'demo_active':False,'paid':True})
        self.ready.start(); self.addCleanup(self.ready.stop)
        self.u1=repo.create_user('one@test.invalid','hash'); self.u2=repo.create_user('two@test.invalid','hash')
        self.b1=repo.create_business(self.u1,'Bisnis Satu','AI_ADMIN')
        self.b2=repo.create_business(self.u2,'Bisnis Dua','AI_ADMIN')
        self.sid,self.marker=demo.begin(self.b1,self.u1)
        self.phone='628123450001'
        self.send=Mock(return_value=(True,None))
        self.infer=patch.object(assist_reply,'generate',return_value=(
            'Foto produk tersedia.',dict(summary='Bertanya harga',action=None,job_status=None),
            {'intent':'Pertanyaan bisnis','confidence':90}))
        self.model=self.infer.start(); self.addCleanup(self.infer.stop)

    def event(self,text,ident):
        return {'id':ident,'from':self.phone,'type':'text','text':{'body':text}}

    def receive(self,text,ident):
        return demo.process(self.event(text,ident),profile_name='Nama WhatsApp',send=self.send)

    def test_binding_replies_and_duplicate_are_scoped(self):
        self.assertTrue(self.receive(self.marker,'bind-1'))
        self.assertTrue(self.receive('Berapa harga foto?','ask-1'))
        self.assertTrue(self.receive('Berapa harga foto?','ask-1'))
        self.assertEqual(self.model.call_count,1)
        self.assertEqual(self.send.call_count,2)
        self.assertEqual(self.model.call_args.args[0],self.b1)
        self.assertEqual(len(demo.rows(self.b1,self.phone)),4)
        self.assertEqual(demo.rows(self.b2,self.phone),[])
        lead=db.query_one('SELECT * FROM kw_core_customers WHERE business_id=?',(self.b1,))
        self.assertEqual(lead['display_name'],'Nama WhatsApp')
        self.assertEqual(customers.get_customer(self.b1,lead['id'])['stage'],'LEAD')
        self.assertEqual(jobs.list_jobs(self.b1)[1],0)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n'],0)

    def test_rebinding_same_phone_never_leaks_later_messages(self):
        self.receive(self.marker,'bind-1')
        before=demo.rows(self.b1,self.phone)
        _,second=demo.begin(self.b2,self.u2)
        self.receive(second,'bind-2');self.receive('Rahasia bisnis dua','ask-2')
        self.assertEqual(demo.rows(self.b1,self.phone),before)
        self.assertNotIn('Rahasia bisnis dua',str(demo.rows(self.b1,self.phone)))
        self.assertEqual(self.model.call_args.args[0],self.b2)
        self.assertFalse(demo.binding(self.b1)['active'])
        self.assertFalse(demo.message_allowed(self.b1,self.phone,demo.rows(self.b2,self.phone)[0]['id']))
        # A delayed retry of the original binding does not reactivate the old business.
        self.receive(self.marker,'bind-1')
        self.assertEqual(demo.resolve(self.phone,'hello')['business_id'],self.b2)

    def test_another_sender_cannot_steal_bound_token(self):
        self.receive(self.marker,'bind-1')
        with self.assertRaisesRegex(ValueError,'demo_already_bound'):
            demo.resolve('628999000011',self.marker)
        with self.assertRaisesRegex(ValueError,'not_found'):
            demo.begin(self.b2,self.u1)

    def test_human_takeover_stays_active_and_original_media_is_bound(self):
        self.receive(self.marker,'bind-1')
        platform_inbox_service.start_human_takeover(self.phone,self.u1)
        mid=db.insert_returning_id("INSERT INTO messages(number,mode,role,content) VALUES (?,'customer','user','Bukti transfer')",(self.phone,))
        event={'id':'image-1','from':self.phone,'type':'image','image':{'id':'media-1','caption':'Bukti transfer'}}
        demo.process(event,media_message_id=mid,send=self.send)
        self.assertTrue(demo.message_allowed(self.b1,self.phone,mid))
        self.assertEqual(self.send.call_count,1)
        self.model.assert_not_called()
        self.assertEqual(platform_inbox_service.get_state(self.phone),'HUMAN_TAKEOVER')

    def test_meeting_creates_customer_and_new_job_payment_intent_moves_in_progress(self):
        self.receive(self.marker,'bind-1')
        insight=dict(summary='Minta meeting besok',action='Jadwalkan meeting besok',job_status='PERLU_TINDAKAN')
        self.model.return_value=('Baik.',insight,{'confidence':90})
        self.receive('Minta meeting besok','meeting')
        lead=db.query_one('SELECT id FROM kw_core_customers WHERE business_id=?',(self.b1,))
        self.assertEqual(customers.get_customer(self.b1,lead['id'])['stage'],'CUSTOMER')
        self.assertEqual(jobs.list_jobs(self.b1)[0][0]['status'],'NEW')
        self.model.return_value=('Invoice akan disiapkan pemilik.',dict(summary='Minta invoice',action='Kirim invoice',job_status='DIKERJAKAN'),{'confidence':90})
        self.receive('Kirim invoice','payment')
        self.assertEqual(jobs.list_jobs(self.b1)[0][0]['status'],'IN_PROGRESS')
        self.assertEqual(jobs.list_jobs(self.b2)[1],0)

    def test_uncertain_send_not_replayed(self):
        self.send.side_effect=TimeoutError('transport unavailable')
        with self.assertRaises(TimeoutError): self.receive(self.marker,'bind-1')
        self.assertEqual(db.query_one('SELECT status FROM kw_assist_demo_events')['status'],'delivery_unknown')
        self.assertTrue(self.receive(self.marker,'bind-1'))
        self.assertEqual(self.send.call_count,1)

    def test_customer_requested_human_handoff_waits_for_owner_to_resume(self):
        self.receive(self.marker,'bind-1')
        self.model.return_value = ('Saya hubungkan dengan pemilik.',
            dict(summary='Meminta bantuan pemilik', action=None, job_status=None,
                 _handoff_requested=True), {'confidence':95})
        self.receive('Saya ingin bicara dengan pemilik','human-request')
        self.assertEqual(platform_inbox_service.get_state(self.phone),'HUMAN_TAKEOVER')
        self.assertEqual(self.send.call_count,2)
        self.model.reset_mock()
        self.receive('Ada orang?','human-wait')
        self.model.assert_not_called()
        self.assertEqual(self.send.call_count,2)
        self.assertEqual(db.query_one("SELECT status FROM kw_assist_demo_events WHERE provider_id='human-wait'")['status'],'human')
        self.assertEqual(jobs.list_jobs(self.b1)[1],0)
        self.assertEqual(demo.rows(self.b2,self.phone),[])
        platform_inbox_service.return_to_ai(self.phone,self.u1)
        self.model.return_value=('Saya bantu.',dict(action=None,job_status=None),{'confidence':90})
        self.receive('Terima kasih','owner-resumed')
        self.model.assert_called_once()
        self.assertEqual(self.send.call_count,3)

    def test_expired_binding_fails_closed(self):
        db.execute('UPDATE kw_assist_demo_sessions SET expires_at=1 WHERE id=?',(self.sid,))
        with self.assertRaisesRegex(ValueError,'invalid_demo_binding'):
            self.receive(self.marker,'expired')
        self.send.assert_not_called();self.model.assert_not_called()

    def test_fresh_invitation_does_not_inherit_legacy_takeover_but_replay_preserves_handoff(self):
        platform_inbox_service.start_human_takeover(self.phone,self.u1)
        self.receive(self.marker,'new-binding')
        self.assertEqual(platform_inbox_service.get_state(self.phone),'AI_ACTIVE')
        self.assertEqual(self.send.call_args.args[1],'Demo aktif ✅ Sekarang chat seperti customer bisnis kamu.')
        platform_inbox_service.start_human_takeover(self.phone,self.u1)
        self.receive(self.marker,'repeated-invitation')
        self.assertEqual(platform_inbox_service.get_state(self.phone),'HUMAN_TAKEOVER')
        self.assertEqual(self.send.call_count,1)


if __name__=='__main__': unittest.main()
