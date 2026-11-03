"""Real ownership/bytes tests, synthetic images; no provider inference."""
import io
import unittest
from PIL import Image, ImageDraw
import test_kilas_managed_offering as fixture
from kilas_ai import store, autonomous_store
import db
import app


def seed(case):
    buffer=io.BytesIO();im=Image.new('RGB',(1200,800),'#e9eef5');draw=ImageDraw.Draw(im)
    draw.rectangle((100,160,1100,650),fill='#173a60');draw.text((160,240),'SYNTHETIC IMAGE - VIEWER QA',fill='white',font_size=42)
    draw.text((160,330),'Same-site preview / original download',fill='white',font_size=32);im.save(buffer,'PNG');raw=buffer.getvalue()
    file={'filename':'synthetic-viewer.png','mime_type':'image/png','content':raw,'byte_size':len(raw),'extracted_text':''}
    aid=store.save_generated_document(case.owner,case.thread,'Synthetic image fixture','SMART','fixture','fixture','viewer-image',{},file)
    job=autonomous_store.create(case.owner,'Synthetic image fixture',conversation_id=case.conversation)
    step=db.insert_returning_id("INSERT INTO kilas_agent_steps(job_id,sequence,worker,action,instruction,idempotency_key) VALUES (?,1,'image','image','synthetic',?)",(job,'viewer-step-'+str(job)))
    artifact=db.insert_returning_id('INSERT INTO kilas_agent_artifacts(job_id,step_id,name,media_type,content,digest) VALUES (?,?,?, ?,?,?)',(job,step,file['filename'],'image/png','{}','synthetic-viewer'))
    db.execute('INSERT INTO kilas_agent_artifact_files(artifact_id,content,byte_size) VALUES (?,?,?)',(artifact,raw,len(raw)))
    return {'raw':raw,'thread':f'/kilas-ai/threads/{case.thread}','preview':f'/kilas-ai/threads/{case.thread}/attachments/{aid}?inline=1','artifact':f'/kilas-ai/agent/jobs/{job}/artifacts/{artifact}','job':job,'artifact_id':artifact}

class ImageViewerTests(unittest.TestCase):
    client=fixture.ManagedOfferingTests.client
    def setUp(self):
        fixture.ManagedOfferingTests.setUp(self);self.data=seed(self)
    def test_owned_original_bytes_and_download_headers(self):
        for path in (self.data['preview'],self.data['artifact']):
            with self.subTest(path=path):
                response=self.client().get(path);self.assertEqual(response.status_code,200);self.assertEqual(response.data,self.data['raw'])
                self.assertEqual(response.mimetype,'image/png');self.assertIn('no-store',response.headers['Cache-Control']);self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
                download=path.split('?')[0]+('?download=1' if '/artifacts/' in path else '')
                response=self.client().get(download);self.assertEqual(response.data,self.data['raw']);self.assertIn('attachment;',response.headers['Content-Disposition'])
    def test_other_account_anonymous_and_wrong_parent_cannot_read(self):
        for path in (self.data['preview'],self.data['artifact']):
            self.assertEqual(self.client(self.other).get(path).status_code,404)
            self.assertIn(app.app.test_client().get(path).status_code,(302,401))
        other_thread=store.create_thread(self.owner)
        self.assertEqual(self.client().get(self.data['preview'].replace(f'/threads/{self.thread}/',f'/threads/{other_thread}/')).status_code,404)
        other_job=autonomous_store.create(self.owner,'Other synthetic job',conversation_id=self.conversation)
        self.assertEqual(self.client().get(self.data['artifact'].replace(f'/jobs/{self.data["job"]}/',f'/jobs/{other_job}/')).status_code,404)
    def test_persisted_image_uses_viewer_assets_and_opt_in(self):
        html=self.client().get(self.data['thread']).text
        self.assertIn('data-kilas-image',html);self.assertIn('kilas_image_viewer.js?v=image-viewer-20261103',html)
        from flask import render_template
        with app.app.test_request_context('/'):
            html=render_template('kilas_ai/_work_artifact.html',artifact={'id':self.data['artifact_id'],'job_id':self.data['job'],'name':'synthetic.png','media_type':'image/png'},job={'id':self.data['job']})
            self.assertEqual(html.count('data-kilas-image'),2)
            html=render_template('kilas_ai/_work_artifact.html',artifact={'id':1,'job_id':self.data['job'],'name':'file.pdf','media_type':'application/pdf'},job={'id':self.data['job']})
            self.assertNotIn('data-kilas-image',html)

if __name__=='__main__':unittest.main()
