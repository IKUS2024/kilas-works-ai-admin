"""Video product/security/provider boundaries using disposable owners and transport."""
import copy
import io
import json
import os
from pathlib import Path
from unittest.mock import patch, Mock
import unittest
from PIL import Image
import test_kilas_autonomous_agent as fixture
from kilas_ai import video_director as director, video_store as store, video_adapters as adapters, usage


def spec():
    data={k:'' for k in director.TEXT_FIELDS}
    data.update(title='Skincare Natural Reel',objective='Perkenalkan produk',video_type='UGC',target_platform='Reels',
        aspect_ratio='9:16',subject='Perempuan Indonesia dengan produk referensi',product='Produk referensi',
        setting='Kamar mandi modern',visual_style='Clean, natural',tone='Hangat',story='Demonstrasi pemakaian dengan kemasan tetap sama.',
        hook='Detail kemasan diikuti tangan mengambil produk.',duration=10,cta='Lihat katalog',audio='Suara lingkungan')
    for key in director.LIST_FIELDS:data[key]=['Pertahankan produk referensi']
    data['scenes']=[dict(start=0,end=4,visual='Close-up kemasan',camera='Statis',action='Tangan mengambil produk',lighting='Cahaya jendela',audio='Suara lingkungan',on_screen_text=''),
                    dict(start=4,end=10,visual='Demonstrasi produk',camera='Medium shot',action='Talent menunjukkan penggunaan',lighting='Cahaya tetap',audio='Suara lingkungan',on_screen_text='Lihat katalog')]
    return data


def provider_response(value=None):
    return Mock(json=lambda:{'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value or spec())}}],
        'usage':{'prompt_tokens':250,'completion_tokens':600}})


class VideoTests(unittest.TestCase):
    def setUp(self):
        fixture.app.app.config.update(TESTING=True,CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        self.owner=fixture.repo.create_user(self.id()+'@example.test','hash')
        self.other=fixture.repo.create_user(self.id()+'-other@example.test','hash')
        self.client=fixture.app.app.test_client()
        with self.client.session_transaction() as state:state.update(user_id=self.owner,role='CLIENT_OWNER',_csrf_token='video-test-csrf')

    def make(self,**extra):
        data={'idea':'gw bikin skincare buat reels, cewek Indonesia, clean, produknya jangan berubah','csrf_token':'video-test-csrf','operation_key':'video-key-1234567890',**extra}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-video-only'}),patch.object(director.requests,'post',return_value=provider_response()) as call:
            response=self.client.post('/kilas-ai/video/plan',data=data,content_type='multipart/form-data')
        return response,call

    def test_auth_and_existing_navigation_home(self):
        self.assertEqual(fixture.app.app.test_client().get('/kilas-ai/video').status_code,302)
        html=self.client.get('/kilas-ai/video').text
        self.assertIn('Kilas Video',html);self.assertNotIn('Connections',html)
        self.assertIn('Buka Kilas Video',self.client.get('/products/start').text)
        self.assertIn('video-studio',html)

    def test_create_and_reopen_owner_history(self):
        response,call=self.make();self.assertEqual(response.status_code,200,response.text)
        project=store.get(self.owner,response.json['id']);self.assertEqual(project['version'],1)
        self.assertIn('Skincare Natural Reel',self.client.get(response.json['url']).text)
        self.assertEqual(call.call_args.args[0],'https://api.openai.com/v1/chat/completions')
        self.assertFalse(call.call_args.kwargs['json']['store'])
        row=fixture.db.query_one('SELECT status,input_tokens FROM kilas_ai_usage WHERE user_id=?',(self.owner,))
        self.assertEqual(row['status'],'COMPLETE');self.assertEqual(row['input_tokens'],250)

    def test_owner_isolation_every_action(self):
        response,_=self.make();project=response.json['id']
        with self.client.session_transaction() as state:state['user_id']=self.other
        self.assertEqual(self.client.get(response.json['url']).status_code,404)
        self.assertNotIn('Skincare Natural Reel',self.client.get('/kilas-ai/video').text)
        for action in ('rename','duplicate','delete'):
            self.assertEqual(self.client.post(f'/kilas-ai/video/projects/{project}/{action}',data={'csrf_token':'video-test-csrf','title':'Foreign','confirm':'delete'}).status_code,404)
        self.assertEqual(self.client.post('/kilas-ai/video/plan',data={'csrf_token':'video-test-csrf','operation_key':'video-other-key-123456','idea':'lebih premium','project_id':project,'version':1}).status_code,404)
        self.assertIsNone(store.get(self.owner,project)['deleted_at'])

    def test_reference_safe_normalized_vision_and_private_download(self):
        raw=io.BytesIO();Image.new('RGB',(40,40),'orange').save(raw,'PNG')
        response,call=self.make(references=(io.BytesIO(raw.getvalue()),'product.png'))
        self.assertEqual(response.status_code,200,response.text)
        content=call.call_args.kwargs['json']['messages'][-1]['content']
        self.assertEqual(content[1]['type'],'image_url')
        refs=store.references(self.owner,response.json['id']);self.assertEqual(len(refs),1)
        route=f"/kilas-ai/video/projects/{response.json['id']}/references/{refs[0]['id']}"
        self.assertEqual(self.client.get(route).headers['Cache-Control'],'private, no-store')
        with self.client.session_transaction() as state:state['user_id']=self.other
        self.assertEqual(self.client.get(route).status_code,404)

    def test_non_image_reference_rejected_before_model(self):
        response,call=self.make(references=(io.BytesIO(b'%PDF-not-image'),'fake.pdf'))
        self.assertEqual(response.status_code,400);call.assert_not_called()

    def test_duplicate_submit_does_not_call_model_twice(self):
        response,_=self.make();again,call=self.make()
        self.assertEqual(response.json['id'],again.json['id']);call.assert_not_called()

    def test_revision_preserves_context_and_tool_adapter(self):
        response,_=self.make();project=response.json['id']
        revised,call=self.make(project_id=str(project),version='1',operation_key='video-revision-key-123456',idea='lebih premium, sekarang versi Seedance')
        self.assertEqual(revised.status_code,200,revised.text)
        sent=json.loads(call.call_args.kwargs['json']['messages'][-1]['content'])
        self.assertEqual(sent['previous_spec'],spec());self.assertEqual(sent['controls']['tool'],'Seedance')
        self.assertIn('Seedance',revised.json['html']);self.assertEqual(store.get(self.owner,project)['version'],2)
        self.assertEqual(len(fixture.db.query_all('SELECT * FROM kilas_video_revisions WHERE project_id=?',(project,))),2)

    def test_stale_revision_does_not_overwrite(self):
        response,_=self.make()
        changed,call=self.make(project_id=str(response.json['id']),version='0',idea='scene kedua ganti',operation_key='video-stale-key-123456789')
        self.assertEqual(changed.status_code,409);call.assert_not_called()

    def test_reference_and_plan_duplication_is_private(self):
        response,_=self.make();project=response.json['id']
        duplicate=self.client.post(f'/kilas-ai/video/projects/{project}/duplicate',data={'csrf_token':'video-test-csrf'})
        self.assertEqual(duplicate.status_code,303)
        self.assertEqual(len(store.history(self.owner)),2)
        self.assertEqual(store.history(self.other),[])

    def test_delete_requires_confirmation_and_preserves_original_other_data(self):
        response,_=self.make();project=response.json['id']
        url=f'/kilas-ai/video/projects/{project}/delete'
        self.assertEqual(self.client.post(url,data={'csrf_token':'video-test-csrf'}).status_code,400)
        self.assertEqual(self.client.post(url,data={'csrf_token':'video-test-csrf','confirm':'delete'}).status_code,303)
        self.assertIsNone(store.get(self.owner,project));self.assertEqual(self.client.get(response.json['url']).status_code,404)
        self.assertIsNotNone(fixture.db.query_one('SELECT id FROM kilas_video_projects WHERE id=?',(project,)))

    def test_rename_escaped_output_and_copy_payload(self):
        response,_=self.make();project=response.json['id']
        self.client.post(f'/kilas-ai/video/projects/{project}/rename',data={'csrf_token':'video-test-csrf','title':'<script>alert(1)</script>'})
        html=self.client.get(response.json['url']).text
        self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>alert(1)</script>',html)
        self.assertIn('video-copy-data',html)

    def test_invalid_provider_result_keeps_previous_plan(self):
        response,_=self.make();project=response.json['id']
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(director.requests,'post',return_value=provider_response({'wrong':'data'})):
            failed=self.client.post('/kilas-ai/video/plan',data={'csrf_token':'video-test-csrf','idea':'lebih premium','project_id':project,'version':1,'operation_key':'video-failure-key-123456'})
        self.assertEqual(failed.status_code,503)
        self.assertEqual(json.loads(store.get(self.owner,project)['spec_json']),spec())
        self.assertNotIn('invalid_video_spec',failed.text)

    def test_locked_project_and_version_guard(self):
        project=store.create(self.owner,'new idea',{},'video-lease-key-123456')
        self.assertTrue(store.claim(self.owner,project,0));self.assertFalse(store.claim(self.owner,project,0))

    def test_csrf_and_admin_gate(self):
        self.assertEqual(self.client.post('/kilas-ai/video/plan',data={'idea':'bikin iklan','operation_key':'video-csrf-key-123456'}).status_code,400)
        with self.client.session_transaction() as state:state['role']='KILAS_ADMIN'
        fixture.db.execute("UPDATE users SET role='KILAS_ADMIN' WHERE id=?",(self.owner,))
        self.assertEqual(self.client.get('/kilas-ai/video').status_code,404)

    def test_failed_generation_can_retry_same_saved_project(self):
        data={'idea':'Rencana produk natural','operation_key':'video-failed-key-123456789','csrf_token':'video-test-csrf'}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(director.requests,'post',return_value=provider_response({'invalid':'spec'})):
            failed=self.client.post('/kilas-ai/video/plan',data=data)
        self.assertEqual(failed.status_code,503)
        project=failed.json['id'];self.assertEqual(failed.json['version'],0)
        response,_=self.make(project_id=project,version='0',operation_key='video-retry-key-123456789')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json['id'],project)
        self.assertEqual(len(store.history(self.owner)),1)

    def test_script_copy_payload_and_rendering_when_relevant(self):
        raw=spec();raw['voice_over']='Lihat detail kemasan dan cara pemakaiannya.'
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(director.requests,'post',return_value=provider_response(raw)):
            result=self.client.post('/kilas-ai/video/plan',data={'idea':'Bikin demonstrasi produk dengan narasi singkat','operation_key':'video-vo-key-123456789','csrf_token':'video-test-csrf'})
        self.assertEqual(result.status_code,200)
        self.assertIn('Salin script',result.json['html'])
        self.assertEqual(adapters.package(raw)['script'],raw['voice_over'])
        self.assertIn('video-manage',result.json['manage_html'])

    def test_adapters_keep_same_spec_and_do_not_call_external_services(self):
        before=spec();original=copy.deepcopy(before)
        with patch.object(director.requests,'post',side_effect=AssertionError('No inference in adapters')):
            for tool in director.TOOLS:
                result=adapters.package(before,tool);self.assertIn('Produk referensi',result['master'])
                self.assertIn('0–4 detik',result['storyboard']);self.assertTrue(result['platform']);self.assertEqual(before,original)

    def test_custom_duration_and_bad_timing_fail_closed(self):
        director.validate(spec(),{'duration':'10'})
        with self.assertRaises(ValueError):director.validate(spec(),{'duration':'20'})
        bad=spec();bad['scenes'][1]['start']=3
        with self.assertRaises(ValueError):director.validate(bad)
        self.assertEqual(director.resolve('buat 30 detik untuk Runway',{})['duration'],'Custom storyboard')

    def test_no_narration_guard(self):
        raw=spec();raw['voice_over']='Narasi';raw['audio']='Voice-over dan musik'
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(director.requests,'post',return_value=provider_response(raw)):
            result=director.generate(self.owner,'no-vo-key-123456789','tanpa voice over',{},None)
        self.assertEqual(result['voice_over'],'');self.assertEqual(result['audio'],'')

    def test_quota_gate_blocks_provider(self):
        with patch.object(usage,'reserve',side_effect=usage.UsageLimit('Batas pemakaian')),patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(director.requests,'post') as call:
            with self.assertRaises(usage.UsageLimit):director.generate(self.owner,'quota-key-123456789','idea',{})
        call.assert_not_called()

    def test_editorial_pages_and_official_only_tools(self):
        for area in ('learn','workflow','tools'):self.assertEqual(self.client.get('/kilas-ai/video?area='+area).status_code,200)
        self.assertNotIn('Rp',self.client.get('/kilas-ai/video?area=tools').text)

    def test_200_corpus_context_and_revision_controls(self):
        cases=json.loads((Path(__file__).parent/'fixtures/kilas_video_corpus.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(cases),200);self.assertEqual(len({c['id'] for c in cases}),len(cases))
        self.assertNotIn('V001',director.STANDARD)
        for case in cases:
            with self.subTest(case=case['id']):
                self.assertTrue(case['idea']);self.assertTrue(case['revision']);self.assertTrue(case['preserve'])
                self.assertEqual(director.resolve(case['revision'],{'tool':'Universal'})['tool'],case['target_tool'])


if __name__=='__main__':unittest.main()
