"""Connected clips: deterministic timing, complete exports, authoritative revisions and safety."""
import copy
import json
import os
import re
import unittest
from unittest.mock import patch
from test_kilas_video import VideoTests, provider_response, fixture, director, store, adapters, spec
from test_kilas_video_v2 import plan
from kilas_ai import video_brief as briefs, video_parts as parts


def multipart(subject='mobil',english='car',total=30,strategy='10'):
    value=plan(subject,english);value['duration']=total
    value['scenes'][1]['end']=total
    value['master_prompt']=f'Create a {total}-second video with the same {english}. Use a close-up camera shot then show the whole subject in soft light.'
    bible={k:'' for k in parts.BIBLE_FIELDS}
    bible.update(subject=english,product=english,location='A quiet studio with a white table',
                 lighting='Soft window light from camera left',camera='Static close-ups and a restrained medium shot',
                 aspect_ratio='9:16',color_grade='Warm neutral grade',environment='The same studio and white table')
    value.update(continuity_bible=bible,parts=[])
    state=f'The same {english} is centered on the white table in a medium camera frame.'
    for timing in parts.timeline(total,strategy):
        number=timing['number'];end=f'The same {english} stays on the white table with detail {number} facing the static camera.'
        value['parts'].append({**timing,'title':f'Detail {subject} {number}','purpose':f'Tunjukkan bagian {number}',
            'scene':f'Tampilkan detail {subject} {number}','start_state':state,'end_state':end,
            'image_prompt':f'A still frame of the same {english} centered on the white studio table with detail {number} facing the static camera. Soft window lighting from camera left, warm neutral mood, identical packaging and props. Vertical 9:16 composition; keep the approved identity and exact opening pose.',
            'shot_direction':'Use one static close-up shot with soft window lighting.',
            'on_screen_text':'','voice_over':'','audio':'Keep the same quiet studio ambience throughout the shot.',
            'shot_list':[f'Detail {number} pada {subject}'],'avoid':['Avoid identity changes and invented labels.'],
            'master_prompt':f'Create this {timing["duration"]}-second shot of the same {english}. Show detail {number} in a static close-up camera frame with soft window light. Finish with detail {number} facing the camera.'})
        state=end
    value.pop('scenes');value=parts.expand_draft(value,{'plan_mode':'multi','duration':total})
    return value


class ConnectedVideoTests(unittest.TestCase):
    setUp=VideoTests.setUp

    def send(self,value,idea='Video mobil 30 detik',project=None,version=0,**controls):
        data={'csrf_token':'video-test-csrf','operation_key':'multipart-controlled-'+str(version),
              'idea':idea,'plan_mode':'multi','total_duration':'30','clip_strategy':'10',**controls}
        if project:data.update(project_id=str(project),version=str(version))
        expanded=parts.expand_draft(value,{'plan_mode':'multi','duration':int(data['total_duration'])})
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(director.requests,'post',side_effect=[provider_response(value),provider_response(expanded)]) as calls:
            response=self.client.post('/kilas-ai/video/plan',data=data)
        return response,calls

    def test_auto_and_fixed_timing(self):
        for total,strategy,lengths in [(30,'10',[10]*3),(45,'15',[15]*3),(25,'auto',[9,8,8]),(25,'10',[10,10,5]),(120,'15',[15]*8)]:
            timeline=parts.timeline(total,strategy)
            self.assertEqual([p['duration'] for p in timeline],lengths)
            self.assertEqual(timeline[-1]['end'],total)
            for a,b in zip(timeline,timeline[1:]):self.assertEqual(a['end'],b['start'])
        for total,strategy in [(0,'auto'),(181,'auto'),(30,'7'),(10,'15'),(True,'auto'),(180,'5')]:
            with self.assertRaises(ValueError):parts.timeline(total,strategy)

    def test_connected_plan_bounds_reasoning_and_uses_one_complete_call(self):
        response,calls=self.send(multipart())
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(calls.call_count,1)
        self.assertTrue(all(c.kwargs['json']['reasoning_effort']=='low' for c in calls.call_args_list))
        self.assertLessEqual(calls.call_args_list[0].kwargs['timeout'][1],65)

    def test_single_legacy_contract_is_unchanged(self):
        value=spec();director.quality(value,briefs.build('video skincare 10 detik',{'plan_mode':'single'}))
        self.assertNotIn('parts',value);self.assertEqual(adapters.package(value)['master'],value['master_prompt'])

    def test_compact_provider_draft_expands_without_new_facts(self):
        value=multipart();brief=briefs.build('Video mobil 30 detik',{'plan_mode':'multi','total_duration':'30','clip_strategy':'10'})
        full=copy.deepcopy(value)
        self.assertEqual(parts.expand_draft(full,brief),full)
        for field in ('scenes','master_prompt','shot_list','b_roll','continuity','must_preserve','avoid','camera','movement','lighting','audio','voice_over','on_screen_text','duration','aspect_ratio'):
            value.pop(field)
        for part in value['parts']:part.pop('master_prompt')
        compact=copy.deepcopy(value)
        expanded=parts.expand_draft(value,brief);director.quality(expanded,brief)
        self.assertEqual(value,compact)
        self.assertEqual(expanded['duration'],30)
        for p,s in zip(expanded['parts'],expanded['scenes']):
            self.assertIn(p['start_state'],s['production_prompt'])
            self.assertIn(p['end_state'],s['production_prompt'])
            self.assertIn(p['shot_direction'],s['production_prompt'])
            exported=parts.prompt(expanded,p)
            self.assertEqual(exported.count(p['shot_direction']),1)
            self.assertEqual(exported.count(p['start_state']),1)
            self.assertEqual(exported.count(p['end_state']),1)
        result,calls=self.send(value)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(calls.call_count,1)
        broken=copy.deepcopy(value);broken['parts'][1]['start_state']='The car is suddenly outside in a different street camera frame.'
        with self.assertRaisesRegex(ValueError,'disconnected_part_handoff'):
            director.quality(parts.expand_draft(broken,brief),brief)

    def test_exact_handoff_timing_and_complete_standalone_copies(self):
        value=multipart();brief=briefs.build('Video mobil 30 detik',{'plan_mode':'multi','total_duration':'30','clip_strategy':'10'})
        director.quality(value,brief);before=copy.deepcopy(value)
        for tool in director.TOOLS:
            package=adapters.package(value,tool)
            for part in value['parts']:
                text=package['part_'+str(part['number'])]
                self.assertIn(package['bible'],text)
                self.assertIn(part['start_state'],text);self.assertIn(part['end_state'],text)
                self.assertIn(part['master_prompt'],text)
                self.assertIn(text,package['all_parts']);self.assertIn(text,package['everything'])
                self.assertIn('Part '+str(part['number']),package['part_'+str(part['number'])+'_platform'])
                self.assertEqual(package['part_'+str(part['number'])+'_platform'].count(text),1)
            self.assertNotIn('Part 2',package['part_1'])
        self.assertEqual(value,before)

    def test_reject_disconnected_or_unsafe_parts(self):
        brief=briefs.build('Video mobil 30 detik',{'plan_mode':'multi','total_duration':'30','clip_strategy':'10'})
        changes=[lambda s:s['parts'][1].update(start_state='An unrelated opening state'),
                 lambda s:s['parts'][1].update(start=11),lambda s:s['parts'].pop(),
                 lambda s:s['continuity_bible'].update(aspect_ratio='16:9'),
                 lambda s:s['parts'][0].update(master_prompt='Tampilkan mobil dengan kamera statis.'),
                 lambda s:s['parts'][0].update(purpose='Terbukti klinis menyembuhkan'),
                 lambda s:s['parts'][1].update(master_prompt=s['parts'][0]['master_prompt']),
                 lambda s:s['parts'][0].update(start_state='Same as before.'),
                 lambda s:s['parts'][0].update(avoid=['Jangan ubah produk ini.']),
                 lambda s:s['parts'][0].update(internal_metadata='forbidden')]
        for mutate in changes:
            value=multipart();mutate(value)
            with self.assertRaises(ValueError):director.quality(value,brief)

    def test_no_voice_over_applies_to_every_part(self):
        brief=briefs.build('Video mobil tanpa voice-over 30 detik',{'plan_mode':'multi','total_duration':'30','clip_strategy':'10'})
        value=multipart();value['parts'][1]['voice_over']='Kalimat tambahan'
        with self.assertRaises(ValueError):director.quality(value,brief)

    def test_store_replacement_chain_and_latest_snapshot(self):
        project=None
        for version,(subject,english,instruction) in enumerate([('mobil','car','Video mobil 30 detik'),('baju','shirt','Ganti jadi baju'),('makanan','food','Ganti jadi makanan'),('makanan','food','lebih premium, tanpa voice-over')]):
            response,calls=self.send(multipart(subject,english),instruction,project,version)
            self.assertEqual(response.status_code,200,response.text);project=response.json['id']
            self.assertEqual(response.json['version'],version+1)
            public=response.json['html'].lower()
            if version>=2:
                for old in ('mobil','car','baju','shirt'):self.assertIsNone(re.search(r'\b'+old+r'\b',public))
            row=store.get(self.owner,project);options=json.loads(row['options_json'])
            self.assertEqual(options['_brief']['plan_mode'],'multi')
            self.assertEqual(options['_brief']['clip_timeline'],parts.timeline(30,'10'))
            sent=json.loads(calls.call_args.kwargs['json']['messages'][1]['content'])
            if version in (1,2):self.assertIsNone(sent['previous_spec'])
            if version==3:self.assertIsNotNone(sent['previous_spec'])
            self.assertEqual(calls.call_count,1)
            self.assertEqual(len(json.loads(row['spec_json'])['parts']),3)
        reopen=self.client.get(response.json['url']);self.assertEqual(reopen.status_code,200)
        self.assertIn('Arahan makanan',reopen.text)
        snapshots=fixture.db.query_all('SELECT spec_json FROM kilas_video_revisions WHERE project_id=? ORDER BY version',(project,))
        self.assertEqual(len(snapshots),4)
        self.assertEqual(json.loads(snapshots[-1]['spec_json'])['brief']['revision_number'],4)
        with self.client.session_transaction() as state:state['user_id']=self.other
        self.assertEqual(self.client.get(response.json['url']).status_code,404)

    def test_stale_continuity_and_part_prompt_rejected(self):
        brief=briefs.build('ganti jadi makanan',{'plan_mode':'multi','total_duration':'30','clip_strategy':'10','_brief':{'subject':'mobil','subject_en':'car'}},multipart(),1)
        for change in (lambda s:s['continuity_bible'].update(product='car'),lambda s:s['parts'][0].update(master_prompt=s['parts'][0]['master_prompt']+' Keep the car visible.')):
            value=multipart('makanan','food');change(value)
            with self.assertRaises(ValueError):director.quality(value,brief)

    def test_latest_duration_wins_and_remainder_is_explicit(self):
        brief=briefs.build('sekarang 25 detik',{'plan_mode':'multi','total_duration':'30','clip_strategy':'10','_brief':{'subject':'mobil'}},multipart(),1)
        self.assertEqual(brief['duration'],25);self.assertEqual(brief['total_duration'],'25')
        self.assertEqual([p['duration'] for p in brief['clip_timeline']],[10,10,5])
        director.quality(multipart(total=25),brief)

    def test_invalid_controls_do_not_call_provider_or_create_project(self):
        response,calls=self.send(multipart(),total_duration='181')
        self.assertEqual(response.status_code,400);calls.assert_not_called()
        self.assertFalse(store.history(self.owner))
        response,calls=self.send(multipart(),total_duration='10',clip_strategy='15')
        self.assertEqual(response.status_code,400);calls.assert_not_called()

    def test_invalid_handoff_preserves_last_good_version(self):
        good,_=self.send(multipart());project=good.json['id']
        bad=multipart();bad['parts'][1]['start_state']='Unrelated state'
        failed,_=self.send(bad,'lebih premium',project,1)
        self.assertEqual(failed.status_code,503)
        self.assertEqual(store.get(self.owner,project)['version'],1)

    def test_switching_mode_replaces_derived_structure(self):
        first,_=self.send(multipart());project=first.json['id']
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(director.requests,'post',return_value=provider_response(plan('mobil','car'))):
            single=self.client.post('/kilas-ai/video/plan',data={'csrf_token':'video-test-csrf','operation_key':'mode-single-controlled','project_id':project,'version':1,'idea':'sekarang single video 10 detik','plan_mode':'single','duration':'10'})
        self.assertEqual(single.status_code,200,single.text)
        row=store.get(self.owner,project);self.assertNotIn('parts',json.loads(row['spec_json']))
        self.assertNotIn('clip_timeline',json.loads(row['options_json'])['_brief'])
        multi,_=self.send(multipart(),project=project,version=2)
        self.assertEqual(multi.status_code,200,multi.text)
        self.assertEqual(len(json.loads(store.get(self.owner,project)['spec_json'])['parts']),3)

    def test_over_limit_revision_does_not_claim_or_meter(self):
        good,_=self.send(multipart());project=good.json['id']
        count=fixture.db.query_one('SELECT COUNT(*) AS count FROM kilas_ai_usage WHERE user_id=?',(self.owner,))['count']
        failed,calls=self.send(multipart(),'sekarang 180 detik',project,1)
        self.assertEqual(failed.status_code,400);calls.assert_not_called()
        current=store.get(self.owner,project)
        self.assertEqual(current['version'],1);self.assertEqual(current['status'],'READY')
        self.assertEqual(fixture.db.query_one('SELECT COUNT(*) AS count FROM kilas_ai_usage WHERE user_id=?',(self.owner,))['count'],count)

    def test_style_patch_preserves_identity_and_handoffs_while_updating_style(self):
        previous=multipart('makanan','food')
        brief=briefs.build('lebih premium, tanpa voice-over',{'_brief':briefs.commit(briefs.build('video makanan 30 detik',{'plan_mode':'multi','total_duration':'30','clip_strategy':'10'}),previous)},previous,1)
        changed=copy.deepcopy(previous);changed['continuity_bible']['lighting']='Use softer window lighting from the same camera left direction.'
        director.quality(changed,brief,previous)
        for mutate in (lambda s:s['parts'][-1].update(end_state='The same food is moved to a different table in a wide camera frame.'),lambda s:s['continuity_bible'].update(product='A different food product')):
            value=copy.deepcopy(previous);mutate(value)
            with self.assertRaises(ValueError):director.quality(value,brief,previous)


if __name__=='__main__':unittest.main()
