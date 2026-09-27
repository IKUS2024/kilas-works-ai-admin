"""Read-only media candidates, cached inference, and explicit session isolation."""
import io,json,os,unittest
from unittest.mock import patch
from PIL import Image
import test_client_hub_v1 as fixture
from public_chat import schema
from kilas_core import customer_schema,job_schema
import assist_demo,assist_media,ai_router,inbox_media_service

repo,db=fixture.repo,fixture.db

class MediaTests(unittest.TestCase):
    def setUp(self):
        fixture.reset_db();schema.apply_schema();customer_schema.apply_schema();job_schema.apply_schema()
        db.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,number TEXT,mode TEXT,role TEXT,content TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        self.uid=repo.create_user('owner@test.invalid','hash');self.otheruid=repo.create_user('other@test.invalid','hash')
        self.bid=repo.create_business(self.uid,'Photo One','AI_ADMIN');self.other=repo.create_business(self.otheruid,'Other','AI_ADMIN')
        db.execute("UPDATE businesses SET status='ACTIVE' WHERE id=?",(self.bid,))
        self.phone='628111111111'
        self.media=inbox_media_service.record(self.bid,self.phone,{'id':'in-media','type':'image','timestamp':'1759000000',
            'image':{'id':'999','mime_type':'image/png','caption':'Bukti transfer','filename':'proof.png'}})
        img=Image.new('RGB',(40,40),'white');buf=io.BytesIO();img.save(buf,format='PNG');self.raw=buf.getvalue()
        self.result={'summary':'Tampak bukti transfer; perlu verifikasi pemilik.','payment_detected':True,
            'amount_minor':9900000,'currency':'IDR','date':'2026-09-27','bank':'Bank Contoh','reference':'REF-TEST'}
        self.client=fixture.fresh_client()
        with self.client.session_transaction() as session:session.update(user_id=self.uid,role='CLIENT_OWNER',_csrf_token='test')

    def test_candidate_is_cached_and_never_posts_payment_or_income(self):
        import inbox_service,finance_service
        with patch.object(inbox_service,'_tenant_channel',return_value=({'access_token':'synthetic','phone_number_id':'123'},None)), \
             patch.object(inbox_media_service,'download',side_effect=lambda *a:(io.BytesIO(self.raw),'image/png')), \
             patch.object(ai_router,'complete',return_value=(json.dumps(self.result),'end_turn',None)) as model, \
             patch.object(finance_service,'record_invoice_payment',side_effect=AssertionError('analysis cannot pay')) as payment:
            first=assist_media.analyze(self.bid,self.media['id'],self.uid)
            self.assertEqual(first,self.result)
            self.assertEqual(assist_media.analyze(self.bid,self.media['id'],self.uid),first)
            model.assert_called_once();payment.assert_not_called()
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n'],0)
        page=self.client.get(f"/business/{self.bid}/media/{self.media['id']}/review")
        self.assertEqual(page.status_code,200)
        self.assertIn('Pembayaran terdeteksi',page.text)
        self.assertIn('belum konfirmasi dana diterima',page.text)

    def test_cross_tenant_media_id_and_candidate_are_not_accessible(self):
        with self.client.session_transaction() as session:session.update(user_id=self.otheruid)
        self.assertEqual(self.client.get(f"/business/{self.bid}/media/{self.media['id']}/review").status_code,404)
        self.assertEqual(self.client.get(f"/business/{self.other}/media/{self.media['id']}/review").status_code,404)
        with self.assertRaisesRegex(ValueError,'media_not_found'):assist_media.owned(self.other,self.media['id'])

    def test_no_model_instructions_or_invalid_amount_become_candidates(self):
        for change in ({'amount_minor':True},{'amount_minor':-1},{'date':'not-a-date'}, {'currency':'invented'}, {'paid':True}):
            with self.assertRaises(ValueError):assist_media._validate(dict(self.result,**change))
        self.assertIsNone(assist_media._validate(dict(self.result,payment_detected=False))['amount_minor'])

    def test_manual_demo_media_is_exactly_attributed_and_foreign_session_denied(self):
        import assist_journey
        with patch.object(assist_journey,'state',return_value={'ready':True,'paid':True,'demo_active':False,'connected':False}):
            sid,marker=assist_demo.begin(self.bid,self.uid)
        db.execute('UPDATE kw_assist_demo_sessions SET sender_phone=? WHERE id=?',(self.phone,sid))
        bound=assist_demo.require_outgoing_scope({'business_id':self.bid,'session_id':sid},self.phone)
        sent=inbox_media_service.record(None,self.phone,{'id':'sent-media','type':'image','timestamp':'1759000000','image':{'id':'888','mime_type':'image/png','caption':'Penawaran'}},role='assistant')
        self.assertTrue(assist_demo.record_sent_media(bound,'sent-media'))
        self.assertTrue(assist_demo.message_allowed(self.bid,self.phone,sent['message_row_id']))
        self.assertFalse(assist_demo.message_allowed(self.other,self.phone,sent['message_row_id']))
        self.assertEqual(len(assist_demo.rows(self.bid,self.phone)),1)
        with self.assertRaises(ValueError):assist_demo.require_outgoing_scope({'business_id':self.other,'session_id':sid},self.phone)

if __name__=='__main__':unittest.main()
