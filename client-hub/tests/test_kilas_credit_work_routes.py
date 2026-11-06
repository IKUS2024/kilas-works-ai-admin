"""Actual asynchronous Work image wait/consent/resume, offline provider stub."""
import io
import json
import os
import unittest
from unittest.mock import patch
from PIL import Image
from werkzeug.datastructures import FileStorage
import test_kilas_credit_routes as fixture
import db
from kilas_ai import credit_policy as policy,credit_wallet as wallet,autonomous_store as store,autonomous_runner as runner
from kilas_ai.agent_workers import image_worker


class WorkRouteCreditTests(unittest.TestCase):
    setUpClass=classmethod(fixture.CreditRoutesTests.setUpClass.__func__)
    client_for=fixture.CreditRoutesTests.client_for

    def setUp(self):
        self.user=fixture.fixture.repo.create_user(self.id()+'@example.test','hash')
        self.flags=patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'yes','KILAS_AI_AUTOMATION_ENABLED':'true','KILAS_AI_AUTONOMOUS_ENABLED':'true','KILAS_AI_OPENAI_IMAGE_MODEL':'gpt-image-2.5-sunburst','KILAS_CREDIT_TARIFFS_JSON':json.dumps({'version':'customer-credit-v1','rates':{'IMAGE':{'milli':1000,'units':1}},'limits':{'IMAGE':{'models':['gpt-image-2.5-sunburst'],'qualities':['high'],'sizes':['2048x2048'],'prompt_chars':10000}}})})
        self.flags.start();self.addCleanup(self.flags.stop)
        ident=wallet.create_purchase(self.user,'synthetic')
        with patch('file_utils.validate_project_attachment_upload',return_value=('proof.png','image/png')):wallet.submit_proof(self.user,ident,FileStorage(io.BytesIO(b'synthetic'),filename='proof.png',content_type='image/png'))
        wallet.review(ident,self.admin,'VERIFIED',transfer_reference='SYNTHETIC-WORK-'+ident)
        policy.admit(self.user,'image-free-used','IMAGE',1,'a'*64);policy.finish(self.user,'image-free-used',1,success=True)
        self.job=store.create(self.user,'Create a synthetic image',mode='ONE_SHOT')
        db.execute("UPDATE kilas_agent_jobs SET status='RUNNING',plan_json='{}',next_wake_at=? WHERE id=?",(store.stamp(),self.job))
        db.execute("INSERT INTO kilas_agent_steps(job_id,sequence,worker,action,instruction,input_json,idempotency_key) VALUES (?,1,'IMAGE','generate','Create',?,'work-image-'||?)",(self.job,json.dumps({'prompt':'Synthetic 2K image high quality'}),self.job))
        image=io.BytesIO();Image.new('RGB',(2048,2048),'white').save(image,'PNG');self.raw=image.getvalue()

    def tick(self):
        claim=store.claim_due(3)
        own=next(item for item in claim if item[0]==self.job)
        runner.execute(*own)
        for item in claim:
            if item!=own:store.release(*item)

    def test_real_runner_pauses_renders_localized_consent_and_resumes_provider_once(self):
        with patch.object(image_worker.chat_offering,'for_job',return_value=None),patch.object(image_worker.tools,'image',return_value={'raw':self.raw,'mime':'image/png','model':'gpt-image-2.5-sunburst','usage':{}}) as provider:
            self.tick();provider.assert_not_called()
            self.assertEqual(store.get(self.user,self.job)['status'],'NEEDS_APPROVAL')
            token=db.query_one('SELECT token FROM kilas_credit_work_waits WHERE job_id=?',(self.job,))['token']
            client=self.client_for(self.user)
            for lang,label in [('en','Return to Work'),('id','Kembali ke Work'),('es','Volver a Work'),('zh','返回 Work')]:
                client.set_cookie('kilas_language',lang)
                consent=client.get('/kilas-ai/credits/consent/'+token)
                self.assertEqual(consent.status_code,200);self.assertIn(label,consent.text)
                page=client.get('/kilas-ai/agent/jobs/'+str(self.job));self.assertEqual(page.status_code,200);self.assertIn(token,page.text)
            foreign=self.client_for(self.other)
            self.assertEqual(foreign.post('/kilas-ai/credits/consent/'+token,data={'csrf_token':'console-csrf','decision':'approve'}).status_code,404)
            response=client.post('/kilas-ai/credits/consent/'+token,data={'csrf_token':'console-csrf','decision':'approve'})
            self.assertEqual(response.status_code,200);provider.assert_not_called()
            self.tick();provider.assert_called_once()
            self.assertEqual(store.get(self.user,self.job)['status'],'COMPLETED')
            self.assertEqual(wallet.balance(self.user)['balance_milli'],1999000)
            db.execute('UPDATE kilas_agent_jobs SET next_wake_at=? WHERE id=?',(store.stamp(),self.job))
            self.assertNotIn(self.job,[item[0] for item in store.claim_due(3)]);provider.assert_called_once()


if __name__=='__main__':unittest.main()
