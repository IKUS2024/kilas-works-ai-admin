"""Isolated, provider-free end-to-end paid access and expiry invariants."""
import io
import os
import sys
import tempfile
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
import unittest
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
_pg_schema = getattr(sys.modules.get('db'), '_platform_payments_qa_schema', None)
if not _pg_schema:
    os.environ.pop('DATABASE_URL',None)
    os.environ['CLIENT_HUB_DB_PATH']=tempfile.mktemp(suffix='-access-pass.sqlite')
os.environ.update(SECRET_KEY='synthetic-pass-only', KILAS_AI_ENABLED='true', KILAS_APP_FREE_TEST_ENABLED='false', KILAS_AI_CHAT_FREE_TEST_ENABLED='false', KILAS_AI_IMAGE_FREE_TEST_ENABLED='false')
import app, db, repo
from auth_test_helpers import authenticate
from kilas_ai import access_pass, audio_store, billing, capacity, usage, video_entitlement
from PIL import Image
from werkzeug.datastructures import FileStorage

class AccessPassTests(unittest.TestCase):
    def setUp(self):
        self.user=repo.create_user(uuid4().hex+'@example.test','hash')
        self.other=repo.create_user(uuid4().hex+'@example.test','hash')
        self.admin=repo.create_user(uuid4().hex+'@example.test','hash',role='KILAS_ADMIN')
        self.now=usage._now()
        self.client=app.app.test_client();app.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        authenticate(self.client,repo.get_user_by_id(self.user),_csrf_token='pass-csrf')
        out=io.BytesIO();Image.new('RGB',(2,2)).save(out,format='PNG');self.proof=out.getvalue()
    def invoice(self):return billing.create_invoice(self.user,'PLUS')
    def upload(self,invoice):
        billing.submit_proof(self.user,invoice,FileStorage(io.BytesIO(self.proof),filename='proof.png',content_type='image/png'))
        return billing.proof_status(self.user,invoice)['id']
    def approve(self):
        invoice=self.invoice();payment=self.upload(invoice)
        with patch.object(usage,'_now',return_value=self.now):billing.review(payment,self.admin,'VERIFIED')
        return payment
    def test_exact_price_pending_and_proof_do_not_grant_access(self):
        invoice=self.invoice();self.assertEqual(self.invoice(),invoice)
        self.assertEqual(billing.invoice(self.user,invoice)['amount_idr'],99000)
        self.assertFalse(access_pass.active(self.user));self.upload(invoice)
        self.assertFalse(access_pass.active(self.user))
    def test_approval_30_days_replay_renewal_expiry(self):
        payment=self.approve();state=usage.effective_plan(self.user)
        self.assertEqual(state['period_end'],self.now+timedelta(days=30))
        billing.review(payment,self.admin,'VERIFIED');self.assertEqual(usage.effective_plan(self.user),state)
        self.approve();self.assertEqual(usage.effective_plan(self.user)['period_end'],self.now+timedelta(days=60))
        with patch.object(usage,'_now',return_value=self.now+timedelta(days=60)):
            self.assertFalse(access_pass.active(self.user));self.assertEqual(usage.effective_plan(self.user)['plan'],'FREE')
    def test_rejected_resubmit_and_nonadmin_denied(self):
        invoice=self.invoice();payment=self.upload(invoice)
        with self.assertRaises(billing.BillingError):billing.review(payment,self.user,'VERIFIED')
        billing.review(payment,self.admin,'REJECTED','Bukti kurang jelas')
        self.assertFalse(access_pass.active(self.user));self.assertEqual(self.upload(invoice),payment)
        billing.review(payment,self.admin,'VERIFIED');self.assertTrue(access_pass.active(self.user))
    def test_missing_proof_direct_review_denied(self):
        invoice=self.invoice();payment=self.upload(invoice)
        db.execute('UPDATE kilas_ai_payments SET proof_content=? WHERE id=?',(b'',payment))
        with self.assertRaises(billing.BillingError):billing.review(payment,self.admin,'VERIFIED')
        self.assertFalse(access_pass.active(self.user))
    def test_paid_audio_zero_balance_settles_after_expiry_without_debit(self):
        self.approve();self.assertTrue(audio_store.balance(self.user)['exempt'])
        job,new=audio_store.create(self.user,uuid4().hex,'voiceover','Test','id','en','test','Test','Hello',0,None,2,10)
        self.assertTrue(new);self.assertTrue(audio_store.start(self.user,job))
        conn=usage._connect()
        try:
            self.assertTrue(access_pass.audio_granted(conn,self.user,job));self.assertFalse(access_pass.audio_granted(conn,self.other,job))
        finally:conn.close()
        with patch.object(usage,'_now',return_value=self.now+timedelta(days=31)):
            audio_store.finish(self.user,job,b'audio',2000,'test-provider')
            self.assertFalse(audio_store.balance(self.user)['exempt'])
            with self.assertRaises(audio_store.AudioError):audio_store.require_balance(self.user)
        self.assertEqual(audio_store.get(self.user,job)['seconds_charged'],0)
    def test_free_audio_does_not_get_grant(self):
        with self.assertRaises(audio_store.AudioError):audio_store.require_balance(self.user)
        self.assertFalse(access_pass.active(self.user))
        self.assertEqual(usage.PLANS['FREE'],{'price':0,'CHAT':100,'CHAT_DAILY':10,'WEB_SEARCH':3,'IMAGES':2,'PDF':10})
    def test_paid_image_and_web_no_commercial_capacity_cap(self):
        self.approve()
        with patch.object(capacity,'spent',return_value=capacity.allowance()*10):
            plan,ops=usage.reserve(self.user,None,uuid4().hex,'SMART','IMAGE_GENERATE')
            self.assertEqual(plan,'PLUS');self.assertEqual(ops,('IMAGE_GENERATION',))
            self.assertTrue(capacity.summary(self.user)['available']);self.assertTrue(video_entitlement.state(self.user)['allowed'])
        self.assertIsNone(db.query_one('SELECT id FROM kilas_ai_topup_debits WHERE user_id=?',(self.user,)))
    def test_paid_usage_does_not_consume_free_after_expiry(self):
        self.approve()
        for tool in ('CHAT','IMAGE_GENERATE','WEB','PDF'):
            key=uuid4().hex
            usage.reserve(self.user,None,key,'FAST',tool)
            db.execute("UPDATE kilas_ai_usage SET status='COMPLETE',estimated_cost_usd='20' WHERE user_id=? AND operation_key=?",(self.user,key))
        db.execute("UPDATE kilas_ai_subscriptions SET period_end=? WHERE user_id=?",((self.now-timedelta(seconds=1)).isoformat(),self.user))
        state=usage.snapshot(self.user)
        self.assertEqual(state['plan'],'FREE')
        self.assertEqual([v['used'] for v in state['usage'].values()],[0,0,0,0])
        usage.reserve(self.user,None,uuid4().hex,'FAST','PDF')
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_ai_usage WHERE user_id=? AND estimated_cost_usd='20'",(self.user,))['n'],4)

    def test_paid_rate_limit_kept(self):
        self.approve()
        with patch.dict(os.environ,{'KILAS_AI_BURST_PER_MINUTE':'1'}):
            usage.reserve(self.user,None,uuid4().hex,'FAST','CHAT')
            with self.assertRaises(usage.UsageLimit):usage.reserve(self.user,None,uuid4().hex,'FAST','CHAT')
    def test_routes_csrf_idor_invalid_upload_and_queue(self):
        self.assertEqual(self.client.post('/kilas-ai/checkout').status_code,400)
        response=self.client.post('/kilas-ai/checkout',data={'csrf_token':'pass-csrf','plan':'MAX','amount_idr':'1'})
        self.assertEqual(response.status_code,303);invoice=int(response.location.split('/')[-1])
        self.assertEqual(billing.invoice(self.user,invoice)['amount_idr'],99000)
        response=self.client.post(response.location+'/proof',data={'csrf_token':'pass-csrf','proof':(io.BytesIO(b'bad'),'bad.png')},content_type='multipart/form-data')
        self.assertEqual(response.status_code,400);self.assertIn(b'role="alert"',response.data)
        foreign=billing.create_invoice(self.other,'PLUS');self.assertEqual(self.client.get('/kilas-ai/invoices/'+str(foreign)).status_code,404)
        payment=self.upload(invoice)
        self.assertEqual(self.client.get(f'/platform/payments/subscription/{payment}/proof').status_code,403)
        response=self.client.get('/kilas-ai/usage');self.assertEqual(response.status_code,200)
        self.assertNotIn(b'2000 kredit',response.data);self.assertNotIn(b'Kuota rancangan belum aktif',response.data.split(b'<main',1)[1])
        self.assertIn(b'Menunggu persetujuan admin',response.data)

if __name__=='__main__':unittest.main()
