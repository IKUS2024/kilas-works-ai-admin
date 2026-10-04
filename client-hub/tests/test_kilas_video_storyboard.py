"""Two real inference stages, image exports and locked storyboard regeneration."""
import copy
import json
import os
import unittest
from unittest.mock import patch
from test_kilas_video import VideoTests, spec, provider_response, director, store, adapters, fixture
from test_kilas_video_parts import multipart
from kilas_ai import video_storyboard as storyboard


def motion(value):
    if value.get('parts'):
        return {'parts':[{k:p[k] for k in ('shot_direction','master_prompt')} for p in value['parts']]}
    return {'master_prompt':value['master_prompt'],
            'scenes':[{'production_prompt':s['production_prompt']} for s in value['scenes']]}


class StoryboardTests(unittest.TestCase):
    setUp=VideoTests.setUp

    def test_two_phases_still_frame_then_video_with_metering(self):
        target=spec();first=storyboard.frames(target)
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(director.requests,'post',side_effect=[provider_response(first),provider_response(motion(target))]) as calls:
            result=director.generate(self.owner,'storyboard-two-phase-123','Bikin video skincare dengan storyboard dulu',{})
        self.assertEqual(result,target)
        self.assertEqual(calls.call_count,2)
        initial,final=[c.kwargs['json'] for c in calls.call_args_list]
        self.assertIn('PHASE 1',initial['messages'][0]['content'])
        self.assertIn('PHASE 2',final['messages'][0]['content'])
        frames=json.loads(final['messages'][2]['content'])['storyboard_frames']
        self.assertTrue(all(s['image_prompt'] and not s['production_prompt'] for s in frames['scenes']))
        self.assertEqual(frames['scenes'][0]['image_prompt'],first['scenes'][0]['image_prompt'])
        used=fixture.db.query_one('SELECT input_tokens FROM kilas_ai_usage WHERE user_id=?',(self.owner,))
        self.assertEqual(used['input_tokens'],500)

    def test_video_phase_cannot_replace_frozen_image_or_scene(self):
        first=storyboard.frames(spec())
        for key,value in [('visual','An unrelated location'),('image_prompt','An unrelated product'),('start',1)]:
            changes=motion(spec());changes['scenes'][0][key]=value
            with self.assertRaisesRegex(ValueError,'video_changed_storyboard'):storyboard.complete(first,changes)
        changes=motion(spec());changes['title']='New unrelated title'
        with self.assertRaisesRegex(ValueError,'video_changed_storyboard'):storyboard.complete(first,changes)

    def test_multi_image_and_video_handoffs_share_one_plan(self):
        target=multipart();first=storyboard.frames(target)
        result=storyboard.complete(first,motion(target))
        storyboard.require_images(result,director.english_check)
        for s,p in zip(result['scenes'],result['parts']):
            self.assertEqual(s['image_prompt'],p['image_prompt'])
            self.assertEqual(s['production_prompt'],p['master_prompt'])
        for a,b in zip(result['parts'],result['parts'][1:]):self.assertEqual(a['end_state'],b['start_state'])
        exported=adapters.package(result,'Google Flow')
        for number,s in enumerate(result['scenes'],1):
            self.assertIn(s['image_prompt'],exported['all_images'])
            self.assertIn(exported[f'video_{number}'],exported['all_videos'])
            self.assertIn(s['image_prompt'],exported['everything'])
        self.assertNotEqual(exported['all_images'],exported['all_videos'])

    def test_missing_duplicate_or_non_english_images_fail(self):
        for change in [lambda s:s['scenes'][0].pop('image_prompt'),
                       lambda s:s['scenes'][0].update(image_prompt='Tampilkan produk dengan kamera statis.'),
                       lambda s:s['scenes'][1].update(image_prompt=s['scenes'][0]['image_prompt'])]:
            value=spec();change(value)
            with self.assertRaises(ValueError):storyboard.require_images(value,director.english_check)

    def test_video_only_route_reuses_storyboard_one_call_and_persists(self):
        created,_=self.make();project=created.json['id'];previous=json.loads(store.get(self.owner,project)['spec_json'])
        desired=motion(previous);desired['scenes'][0]['production_prompt']+=' End with the same packaging facing the camera.'
        data={'csrf_token':'video-test-csrf','operation_key':'storyboard-video-only-123','project_id':project,
              'version':1,'idea':'Do not use this to replace the subject','generation':'video','plan_mode':'multi','total_duration':'30'}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(director.requests,'post',return_value=provider_response(desired)) as calls:
            result=self.client.post('/kilas-ai/video/plan',data=data)
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(calls.call_count,1)
        current=json.loads(store.get(self.owner,project)['spec_json'])
        self.assertEqual(storyboard.frames(current),storyboard.frames(previous))
        self.assertEqual(current['scenes'][0]['production_prompt'],desired['scenes'][0]['production_prompt'])
        self.assertEqual(result.json['version'],2)
        with self.client.session_transaction() as session:session['user_id']=self.other
        self.assertEqual(self.client.post('/kilas-ai/video/plan',data=data).status_code,404)

    def test_legacy_plan_remains_readable_but_video_only_needs_storyboard(self):
        created,_=self.make();project=created.json['id'];old=spec()
        for s in old['scenes']:
            for k in storyboard.SCENE_FIELDS:s.pop(k)
        fixture.db.execute('UPDATE kilas_video_projects SET spec_json=? WHERE id=?',(json.dumps(old),project))
        page=self.client.get(created.json['url']);self.assertEqual(page.status_code,200)
        self.assertIn('Rencana lama tetap tersedia',page.text)
        with patch.object(director.requests,'post') as calls:
            result=self.client.post('/kilas-ai/video/plan',data={'csrf_token':'video-test-csrf','project_id':project,'version':1,
                'operation_key':'storyboard-legacy-test-123','idea':'Buat prompt video','generation':'video'})
        self.assertEqual(result.status_code,400);calls.assert_not_called()

    def make(self):
        return VideoTests.make(self)


if __name__=='__main__':unittest.main()
