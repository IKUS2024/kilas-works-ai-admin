"""Native high resolution and real illustrated PDF pipeline; no external inference."""
import base64, hashlib, io, json, os, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image, ImageDraw
from pypdf import PdfReader
import test_kilas_selected_artifacts as f
from kilas_ai import pdf, image_models, image_options, selected_image, tools, usage, work_artifacts, autonomous_store, unified_runtime
from kilas_ai.agent_workers import document_worker
import db


def picture(size=(2048,2048)):
    out=io.BytesIO();img=Image.new('RGB',size,'#f6ede1');draw=ImageDraw.Draw(img)
    draw.ellipse((size[0]*.18,size[1]*.18,size[0]*.82,size[1]*.82),fill='#24473c')
    draw.rectangle((size[0]*.28,size[1]*.38,size[0]*.72,size[1]*.62),fill='#dbad70')
    img.save(out,'PNG');return out.getvalue()

SOURCE='# Kopi Contoh — Brosur Sintetis\n\n![Ilustrasi sintetis](image:1)\n\n## Kopi untuk jeda Anda\n\nContoh brosur sintetis dengan kopi pilihan dan kemasan praktis.\n\n- Pilihan rasa yang mudah dinikmati.\n- Kemasan untuk aktivitas sehari-hari.\n\n## Pilihan paket\n\n| Paket | Harga |\n|---|---|\n| Contoh | Rp25.000 |\n\n<!-- pagebreak -->\n\n## Cara memesan\n\nHubungi kanal pemesanan yang Anda tentukan. Ini contoh sintetis, bukan penawaran usaha nyata.'

class HighResolutionTests(unittest.TestCase):
    def test_model_specific_options_and_budget_follow_native_request(self):
        self.assertEqual(image_options.resolve('gpt-image-2','')['size'],'2048x2048')
        self.assertEqual(image_options.resolve('gpt-image-1-mini','')['quality'],'high')
        self.assertEqual(image_options.resolve('gemini-3-pro-image','')['quality'],'2K')
        self.assertEqual(image_options.resolve('gemini-3.1-flash-lite-image','')['quality'],'1K')
        for model in image_options.MODERN:
            for ratio in image_options.RATIOS:
                options=image_options.resolve(model,'Buat gambar 4K '+ratio)
                w,h=map(int,options['size'].split('x'))
                self.assertLessEqual(w*h,8294400);self.assertLessEqual(max(w,h),3840)
            self.assertEqual(image_options.resolve(model,'3840x2160 16:9 quality high')['size'],'3840x2160')
        self.assertGreater(image_models.forecast('gpt-image-2.5-flare',prompt='4K quality max'),image_models.forecast('gpt-image-2.5-flare',prompt='1K quality low'))
        with self.assertRaises(tools.ToolUnavailable):image_options.resolve('gemini-3.1-flash-lite-image','4K')
        with self.assertRaises(tools.ToolUnavailable):image_options.resolve('gpt-image-1-mini','quality max')
        with self.assertRaises(tools.ToolUnavailable):image_options.resolve('gpt-image-2','8K')
        self.assertEqual(image_options.resolve('gemini-3-pro-image','2K 16:9')['size'],'2752x1536')
        self.assertEqual(image_options.resolve('gemini-3-pro-image','4K 3:2')['size'],'5056x3392')
    def test_4k_provider_original_is_never_reencoded_and_edit_input_preserved(self):
        for model,size,prompt in [('gpt-image-2.5-flare',(3840,2160),'Buat visual 3840x2160 16:9 quality max'),('gemini-3-pro-image',(4096,4096),'Buat gambar 4K')]:
            raw=picture(size);encoded=base64.b64encode(raw).decode()
            data={'model':model,'data':[{'b64_json':encoded}]} if model.startswith('gpt') else {'modelVersion':model,'candidates':[{'finishReason':'STOP','content':{'parts':[{'inlineData':{'mimeType':'image/png','data':encoded}}]}}]}
            reference={'filename':'reference.png','mime_type':'image/png','content':picture()}
            with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic','GEMINI_API_KEY':'synthetic'}),patch.object(image_models,'check',return_value={'available':True}),patch.object(selected_image.requests,'post',return_value=SimpleNamespace(raise_for_status=lambda:None,json=lambda:data)) as post:
                result=tools.image(prompt,source=reference,selected_model=model)
            self.assertEqual(result['raw'],raw);self.assertEqual(result['image_options']['dimensions'],list(size));self.assertTrue(result['image_options']['original_bytes_preserved'])
            if model.startswith('gpt'):
                self.assertEqual(post.call_args.kwargs['data']['quality'],'max');self.assertEqual(post.call_args.kwargs['files']['image'][1],reference['content'])
            else:
                payload=post.call_args.kwargs['json'];self.assertEqual(payload['generationConfig']['imageConfig']['imageSize'],'4K')
                self.assertEqual(base64.b64decode(payload['contents'][0]['parts'][1]['inlineData']['data']),reference['content'])
    def test_native_png_above_old_8mib_ceiling_preserves_bytes_and_other_limits(self):
        stream=io.BytesIO();Image.frombytes('RGB',(2048,2048),os.urandom(2048*2048*3)).save(stream,'PNG')
        raw=stream.getvalue();self.assertGreater(len(raw),8*1024*1024)
        file={'filename':'native.png','mime_type':'image/png','content':raw}
        self.assertEqual(work_artifacts.validate(file),raw)
        with self.assertRaises(ValueError):work_artifacts.validate({'filename':'large.txt','mime_type':'text/plain','content':b'x'*(8*1024*1024+1)})

    def test_low_resolution_response_cannot_be_labeled_2k(self):
        raw=picture((1024,1024));data={'model':'gpt-image-2','data':[{'b64_json':base64.b64encode(raw).decode()}]}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic'}),patch.object(image_models,'check',return_value={'available':True}),patch.object(selected_image.requests,'post',return_value=SimpleNamespace(raise_for_status=lambda:None,json=lambda:data)):
            with self.assertRaises(tools.ToolUnavailable):selected_image.generate('gpt-image-2','Buat gambar HD')
    def test_brochure_pdf_embeds_native_image_selectable_text_and_page_break(self):
        image={'filename':'synthetic.png','mime_type':'image/png','content':picture()}
        file=pdf.render(SOURCE,images=[image],brochure=True,professional=True)
        reader=PdfReader(io.BytesIO(file['content']));self.assertEqual(len(reader.pages),2)
        text='\n'.join(page.extract_text() for page in reader.pages)
        self.assertIn('Rp25.000',text);self.assertIn('Cara memesan',reader.pages[1].extract_text());self.assertNotIn('image:1',text)
        images=list(reader.pages[0].images);self.assertEqual(len(images),1);self.assertEqual(images[0].image.size,(2048,2048))
        self.assertEqual(file['validation']['embedded_images'],1);work_artifacts.validate(file)
        # Save reviewable synthetic evidence only; never provider/user data.
        target=os.environ.get('KILAS_HD_EVIDENCE_DIR')
        if target:
            Path(target).mkdir(parents=True,exist_ok=True);Path(target,'brochure-synthetic.pdf').write_bytes(file['content']);Path(target,'synthetic-reference.png').write_bytes(image['content'])
    def test_pdf_rejects_remote_files_and_missing_images_without_fetch(self):
        for address in ('https://example.test/private.png','file:///etc/passwd','image:2'):
            with self.assertRaises(ValueError):pdf.render('# Test\n\n![x]('+address+')')
    def test_pdf_routing_wins_over_visual_edit(self):
        for text in ('Buat brosur PDF dari gambar tadi','Buat brosur kopi dengan foto produk','Ubah gambar ini jadi PDF'):
            self.assertEqual(unified_runtime.intent(text,[{'mime_type':'image/png'}]),'DOCUMENT')

class OwnedDocumentTests(f.SelectedArtifactTests):
    # Explicit subclass tests only; inherited tests are intentionally retained.
    def test_generated_picture_to_brochure_http_download_integrity_and_tenant_gate(self):
        image_job=self.job('gpt-6.1-sol');raw=picture()
        with autonomous_store.transaction() as conn:
            sid=usage._query(conn,"INSERT INTO kilas_agent_steps(job_id,sequence,worker,action,instruction,input_json,idempotency_key,status) VALUES (?,1,'IMAGE','create','Synthetic','{}','hd-image-source','SUCCEEDED') RETURNING id",(image_job['id'],),one=True)[0]
            image_id=work_artifacts.persist(conn,image_job,{'id':sid},{'filename':'native.png','mime_type':'image/png','content':raw,'image_options':{'dimensions':[2048,2048],'quality':'high'}})
        response=self.submit('gpt-6.1-sol','Buat brosur PDF dari gambar tadi, data sintetis, paket Rp25.000',selected_image_model='gpt-image-2')
        self.assertEqual(response.status_code,303)
        job=dict(autonomous_store.list_jobs(self.owner)[0]);self.assertEqual(json.loads(job['checkpoint_json'])['document_image_ids'],[image_id])
        def stream(mode,messages,**kwargs):
            self.assertIn('image:1',kwargs['system']);self.assertTrue(any(isinstance(m.get('content'),list) and any(b.get('type')=='image_url' for b in m['content']) for m in messages))
            for event in f.response_stream(mode,messages,**kwargs):
                if event['type']=='delta':event['text']=SOURCE
                yield event
        with patch.object(f.f.providers,'stream',side_effect=stream):result=document_worker.run(job,self.step('hd-brochure'),{'format':'pdf','request':job['instruction']})
        self.assertEqual(result.status,'SUCCEEDED');file=result.artifacts[0]['binary_file']
        with autonomous_store.transaction() as conn:
            sid=usage._query(conn,"INSERT INTO kilas_agent_steps(job_id,sequence,worker,action,instruction,input_json,idempotency_key,status) VALUES (?,1,'DOCUMENT','create','Synthetic','{}','hd-brochure-save','SUCCEEDED') RETURNING id",(job['id'],),one=True)[0]
            ident=work_artifacts.persist(conn,job,{'id':sid},file)
        url=f'/kilas-ai/agent/jobs/{job["id"]}/artifacts/{ident}?download=1'
        download=self.client().get(url);self.assertEqual(download.status_code,200)
        self.assertEqual(hashlib.sha256(download.data).hexdigest(),hashlib.sha256(file['content']).hexdigest())
        self.assertIn('attachment;',download.headers['Content-Disposition']);self.assertEqual(download.content_type,'application/pdf')
        self.assertEqual(self.client(self.other).get(url).status_code,404)
        image_url=f'/kilas-ai/agent/jobs/{image_job["id"]}/artifacts/{image_id}?download=1'
        self.assertEqual(self.client().get(image_url).data,raw);self.assertEqual(self.client(self.other).get(image_url).status_code,404)
        for number in range(2):
            self.assertEqual(work_artifacts.document_image_context(self.owner,ident,self.conversation)['document_image_ids'],[image_id])
            revision_id=autonomous_store.create(self.owner,'Revisi brosur PDF data sintetis, paket Rp25.000',conversation_id=self.conversation,checkpoint={'author_model':'gpt-6.1-sol','document_source_id':ident})
            revision=dict(autonomous_store.get(self.owner,revision_id))
            with patch.object(f.f.providers,'stream',side_effect=stream):updated=document_worker.run(revision,self.step('hd-revision-'+str(number)),{'format':'pdf','request':revision['instruction']})
            updated_file=updated.artifacts[0]['binary_file']
            self.assertEqual(updated_file['validation']['embedded_images'],1)
            self.assertEqual(PdfReader(io.BytesIO(updated_file['content'])).pages[0].images[0].image.size,(2048,2048))
            with autonomous_store.transaction() as conn:
                sid=usage._query(conn,"INSERT INTO kilas_agent_steps(job_id,sequence,worker,action,instruction,input_json,idempotency_key,status) VALUES (?,1,'DOCUMENT','create','Synthetic','{}',?,'SUCCEEDED') RETURNING id",(revision_id,'hd-revision-save-'+str(number)),one=True)[0]
                ident=work_artifacts.persist(conn,revision,{'id':sid},updated_file)


if __name__=='__main__':unittest.main()
