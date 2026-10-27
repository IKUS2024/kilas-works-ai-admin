"""Synthetic request fidelity and response-depth regressions. No provider transport."""
import base64
import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
from kilas_ai import intelligence, model_policy, chat_models, selected_image, image_models, tools, routing, chat_quality
from kilas_ai.agent_workers import image_worker


class AnswerModelAuditTests(unittest.TestCase):
    def setUp(self):
        block=patch('requests.sessions.Session.request',side_effect=AssertionError('External transport forbidden'))
        block.start();self.addCleanup(block.stop)

    def test_negated_brevity_never_reduces_substantive_request(self):
        for instruction in ('jangan singkat','jangan terlalu singkat','jangan ringkas',"don't be brief",'do not make it too brief','not concise'):
            request='Analisis strategi penjualan dengan risiko dan langkah praktis; '+instruction
            for model in chat_models.CATALOG:
                with self.subTest(instruction=instruction,model=model):
                    messages=chat_models.bind(model_policy.ChatContext([{'role':'user','content':request}]),model)
                    profile=model_policy.chat_profile(messages)
                    self.assertEqual(profile['model'],model)
                    self.assertEqual(profile['depth'],'DEEP')
                    self.assertEqual(profile['output_tokens'],16384)
                    self.assertFalse(intelligence.wants_short(request))

    def test_explicit_short_and_quoted_words_are_distinct(self):
        for request in ('Jawab singkat: apa itu index?', 'Brief: compare A and B', 'Satu kalimat saja'):
            self.assertTrue(intelligence.wants_short(request))
        self.assertFalse(intelligence.wants_short('Analisis kenapa pesan "jawab singkat" kurang membantu'))
        self.assertFalse(intelligence.wants_short('Debug kode `brief = True` dengan langkah lengkap'))
        messages=[{'role':'user','content':'Analisis strategi modal 20 juta, jangan singkat'},{'role':'assistant','content':'Contoh'},{'role':'user','content':'Lanjut yang kedua'}]
        self.assertEqual(intelligence.classify(messages)['depth'],'DEEP')

    def test_image_concept_is_not_cut_at_800(self):
        concept='Konsep poster: '+('detail warna dan posisi. '*60)+' Tulisan akhir harus UTUH.'
        self.assertIn(concept,routing.image_prompt('buat gambarnya dari konsep tadi',concept))

    def _generate(self,model,prompt,size=None,transparent=False):
        if size is None:
            from kilas_ai.image_options import resolve
            size=tuple(map(int,resolve(model,prompt)['size'].split('x')))
        image=io.BytesIO();Image.new('RGBA' if transparent else 'RGB',size,(10,20,30,0) if transparent else 'blue').save(image,format='PNG')
        encoded=base64.b64encode(image.getvalue()).decode()
        data={'model':model,'data':[{'b64_json':encoded}]}
        if image_models.spec(model)['provider']=='google':
            data={'modelVersion':model,'candidates':[{'finishReason':'STOP','content':{'parts':[{'inlineData':{'mimeType':'image/png','data':encoded}}]}}]}
        with patch.object(image_models,'check',return_value={'available':True}),patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic','GEMINI_API_KEY':'synthetic'}),patch.object(selected_image.requests,'post',return_value=SimpleNamespace(raise_for_status=lambda:None,json=lambda:data)) as post:
            result=selected_image.generate(model,prompt)
        self.assertEqual(post.call_count,1)
        self.assertEqual(result['raw'],image.getvalue())
        return post.call_args.kwargs['json'],result

    def test_all_image_models_preserve_long_prompt_and_default_cost_settings(self):
        prompt='Buat poster. '+('Pola biru dan putih. '*240)+'TULISAN AKHIR WAJIB UTUH'
        for model in image_models.CATALOG:
            with self.subTest(model=model):
                payload,result=self._generate(model,prompt)
                self.assertEqual(result['model'],model)
                if image_models.spec(model)['provider']=='openai':
                    self.assertEqual(payload['prompt'],prompt);self.assertEqual(payload['quality'],'high')
                    self.assertEqual(payload['model'],model)
                else:
                    self.assertEqual(payload['contents'][0]['parts'][0]['text'],prompt)
                    self.assertEqual(payload['generationConfig']['imageConfig']['imageSize'],image_models.spec(model)['quality'])

    def test_flare_and_sunburst_transparency_is_supported(self):
        for model in ('gpt-image-2.5-flare','gpt-image-2.5-sunburst','gpt-image-1-mini'):
            with self.subTest(model=model):
                payload,result=self._generate(model,'Buat logo transparan',transparent=True)
                self.assertEqual(payload['background'],'transparent');self.assertTrue(result['image_options']['transparent'])

    def test_modern_openai_aspect_ratio_preserves_actual_requested_dimensions(self):
        for model in ('gpt-image-2','gpt-image-2.5-flare','gpt-image-2.5-sunburst'):
            for ratio,size in (('16:9',(1536,864)),('9:16',(864,1536)),('4:5',(1024,1280))):
                with self.subTest(model=model,ratio=ratio):
                    payload,result=self._generate(model,'Buat poster rasio '+ratio+' '+str(size[0])+'x'+str(size[1]),size)
                    self.assertEqual(payload['size'],f'{size[0]}x{size[1]}')
                    self.assertEqual(result['image_options']['dimensions'],list(size))

    def test_invalid_or_cost_increasing_options_fail_without_provider_call(self):
        with patch.object(image_models,'check',return_value={'available':True}),patch.object(selected_image.requests,'post') as post:
            for model,prompt in (('gpt-image-1-mini','Buat 16:9'),('gpt-image-2','Buat transparan'),('gemini-3.1-flash-lite-image','Buat 4K'),('gpt-image-2','quality max'),('gpt-image-2.5-flare','16:9 1024x1024'),('gpt-image-2.5-flare','000x000'),('gpt-image-2.5-flare','x'*32001)):
                with self.subTest(model=model,prompt=prompt[:40]),self.assertRaises(tools.ToolUnavailable):selected_image.generate(model,prompt)
            post.assert_not_called()

    def test_full_prompt_reservation_keeps_existing_rates_and_capacity_floor(self):
        from kilas_ai import capacity
        for model in image_models.CATALOG:
            base=image_models.forecast(model)
            self.assertEqual(capacity.forecast('IMAGE_GENERATION','FAST',{'image_model':model,'image_input_token_bound':5000}),base)
            bound=512+len(('細節'*10000).encode('utf-8'))
            self.assertGreater(capacity.forecast('IMAGE_GENERATION','FAST',{'image_model':model,'image_input_token_bound':bound}),base)

    def test_invalid_image_response_is_an_accounted_tool_failure(self):
        data={'model':'gpt-image-2.5-flare','data':[{'b64_json':base64.b64encode(b'not an image').decode()}]}
        with patch.object(image_models,'check',return_value={'available':True}),patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic'}),patch.object(selected_image.requests,'post',return_value=SimpleNamespace(raise_for_status=lambda:None,json=lambda:data)) as post:
            with self.assertRaises(tools.ToolUnavailable) as error:selected_image.generate('gpt-image-2.5-flare','Buat poster')
        self.assertEqual(post.call_count,1)
        self.assertTrue(error.exception.usage['billing_unknown'])
        self.assertEqual(error.exception.model,'gpt-image-2.5-flare')

    def test_explicit_size_metadata_and_logo_style_are_faithful(self):
        _,result=self._generate('gpt-image-2.5-flare','Buat poster 1536x1024',(1536,1024))
        self.assertEqual(result['image_options']['aspect_ratio'],'3:2')
        prompt='Buat logo rumit dengan banyak ornamen, bukan minimalis'
        enhanced=routing.enhance_image_prompt(prompt)
        self.assertTrue(enhanced.startswith(prompt))
        self.assertNotIn('bersih, sederhana',enhanced)

    def test_direct_image_worker_uses_full_original_but_generic_plan_keeps_step_prompt(self):
        full='Buat poster '+('detail '*700)+'akhir utuh'
        for checkpoint,expected in (({'image_prompt_full':full},full),({'request_full':'Buat dokumen dengan gambar'},'Buat gambar kucing')):
            job={'checkpoint_json':json.dumps({'image_model':'gpt-image-2.5-flare',**checkpoint}),'user_id':1,'origin_conversation_id':2}
            with patch.object(image_models,'check',return_value={'available':True}),patch.object(image_worker.usage,'reserve',return_value=('PAID',['IMAGE_GENERATION'])),patch.object(image_worker.usage,'finish'),patch.dict('sys.modules',{'kilas_ai.work_runtime':SimpleNamespace(progress=lambda *args:None)}),patch.object(image_worker.work_artifacts,'validate'),patch.object(tools,'image',return_value={'raw':b'synthetic','mime':'image/png','model':'gpt-image-2.5-flare','usage':{}}) as generate:
                image_worker.run(job,{'idempotency_key':'synthetic','attempts':1,'action':'generate'},{'prompt':'Buat gambar kucing'})
            self.assertEqual(generate.call_args.args[0],expected)

if __name__=='__main__':unittest.main()
