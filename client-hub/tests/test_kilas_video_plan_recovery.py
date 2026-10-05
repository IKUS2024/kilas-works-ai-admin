"""Optional output normalization and retry preserve the last valid private plan."""
import copy
import io
import json
import os
import re
import unittest
from unittest.mock import patch
from PIL import Image
from test_kilas_video import VideoTests, spec, provider_response, director, store, fixture
from test_kilas_video_parts import multipart
from kilas_ai import video_brief


class PlanRecoveryTests(unittest.TestCase):
    setUp=VideoTests.setUp
    make=VideoTests.make

    def test_optional_single_sections_normalized_without_new_facts(self):
        original=spec();value=copy.deepcopy(original)
        for key in ('hook','voice_over','audience','subject_en','master_prompt',*director.LIST_FIELDS):value.pop(key)
        for scene in value['scenes']:
            for key in ('camera','lighting','audio','on_screen_text','environment','continuity','title','purpose'):scene.pop(key)
        brief=video_brief.build('video skincare 10 detik',{})
        normalized=director.normalize(value,brief)
        director.quality(normalized,brief,require_storyboard=True)
        self.assertEqual(normalized['hook'],'');self.assertEqual(normalized['shot_list'],[])
        self.assertEqual(normalized['scenes'][0]['image_prompt'],original['scenes'][0]['image_prompt'])
        self.assertNotIn('master_prompt',value)

    def test_optional_multi_sections_and_maximum_clip_validation(self):
        value=multipart(total=20,strategy='auto')
        for part in value['parts']:
            for key in ('voice_over','on_screen_text','audio','shot_list','avoid'):part.pop(key)
        brief=video_brief.build('Video mobil 20 detik',{'plan_mode':'multi','total_duration':'20','clip_strategy':'auto'})
        director.quality(director.normalize(value,brief),brief,require_storyboard=True)
        with self.assertRaises(ValueError):director.options({'plan_mode':'multi','total_duration':'180','clip_strategy':'5'})

    def test_required_wrong_types_and_extra_fields_still_fail(self):
        brief=video_brief.build('video skincare 10 detik',{})
        for change in (lambda v:v.pop('story'),lambda v:v.update(master_prompt=None),lambda v:v.update(shot_list='not a list'),
                       lambda v:v['scenes'][0].pop('image_prompt'),lambda v:v.update(internal_metadata='bad')):
            value=spec();change(value)
            with self.assertRaises(ValueError):director.quality(director.normalize(value,brief),brief,require_storyboard=True)

    def test_timeout_keeps_existing_plan_and_saves_retry_draft_on_reopen(self):
        result,_=self.make();project=result.json['id'];before=store.get(self.owner,project)['spec_json']
        data={'csrf_token':'video-test-csrf','operation_key':'retry-draft-timeout-123','project_id':project,
              'version':1,'idea':'lebih premium tanpa voice-over','duration':'10','tool':'Runway'}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(director.requests,'post',side_effect=director.requests.Timeout('private transport detail')):
            failed=self.client.post('/kilas-ai/video/plan',data=data)
        self.assertEqual(failed.status_code,503);self.assertEqual(failed.json['code'],'video_timeout')
        self.assertNotIn('private transport detail',failed.text)
        row=store.get(self.owner,project)
        self.assertEqual(row['spec_json'],before);self.assertEqual(row['version'],1)
        reopened=self.client.get(result.json['url']).text
        self.assertIn(data['idea'],reopened);self.assertIn('Coba Lagi',reopened)
        self.assertRegex(reopened,r'id="video-error" role="alert"\s*>')
        data['operation_key']='retry-draft-success-123'
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(director.requests,'post',return_value=provider_response()):
            done=self.client.post('/kilas-ai/video/plan',data=data)
        self.assertEqual(done.status_code,200,done.text)
        self.assertEqual(done.json['version'],2)
        self.assertNotIn('_retry',json.loads(store.get(self.owner,project)['options_json']))

    def test_first_failure_retains_uploaded_reference_and_controls(self):
        image=io.BytesIO();Image.new('RGB',(48,48),'white').save(image,format='PNG');image.seek(0)
        data={'csrf_token':'video-test-csrf','operation_key':'retry-reference-fail-123','idea':'Video produk sintetis',
              'duration':'20','tool':'Google Flow','references':(image,'synthetic.png')}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(director.requests,'post',side_effect=director.requests.Timeout()):
            failed=self.client.post('/kilas-ai/video/plan',data=data,content_type='multipart/form-data')
        self.assertEqual(failed.status_code,503)
        self.assertEqual(len(store.references(self.owner,failed.json['id'])),1)
        html=self.client.get(failed.json['url']).text
        self.assertIn('Video produk sintetis',html);self.assertIn('Google Flow',html)

    def test_processing_conflict_does_not_report_generation_failure(self):
        result,_=self.make();project=result.json['id'];store.claim(self.owner,project,1)
        with patch.object(director.requests,'post') as call:
            failed=self.client.post('/kilas-ai/video/plan',data={'csrf_token':'video-test-csrf','operation_key':'retry-conflict-123456',
                'idea':'lebih premium','project_id':project,'version':1})
        self.assertEqual(failed.status_code,409);self.assertTrue(failed.json['processing']);call.assert_not_called()

    def test_only_image_and_video_copy_controls_and_clean_motion_exports(self):
        result,_=self.make();html=result.json['html']
        keys=re.findall(r'data-video-copy="([^"]+)"',html)
        self.assertEqual(keys,['image_1','video_1','image_2','video_2'])
        self.assertIn('Salin Prompt Gambar',html);self.assertIn('Salin Prompt Video',html)
        package=director.normalize(spec(),video_brief.build('video skincare',{}))
        from kilas_ai import video_adapters
        exported=video_adapters.package(package)
        self.assertNotIn(exported['image_1'],exported['video_1'])
        connected=multipart()
        exported=video_adapters.package(connected)
        self.assertIn(connected['parts'][0]['master_prompt'],exported['video_1'])
        self.assertIn(connected['parts'][0]['avoid'][0],exported['video_1'])
        self.assertNotIn(exported['image_1'],exported['video_1'])


if __name__=='__main__':unittest.main()
