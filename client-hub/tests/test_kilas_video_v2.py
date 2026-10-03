"""V2 canonical replacement, bounded review/cost and fail-closed quality contracts."""
import copy
import json
import os
import re
from pathlib import Path
from unittest.mock import patch
import unittest
from test_kilas_video import VideoTests, spec, provider_response, fixture, director, store, adapters
from kilas_ai import video_brief as briefs


def plan(subject,english):
    result=spec()
    result.update(title='Arahan '+subject,subject=subject,subject_en=english,product=subject,audience='Penonton video',
                  story='Tampilkan detail '+subject+' lalu akhiri dengan tampilan utuh.',hook='Detail '+subject,
                  master_prompt='Create a 10-second vertical video of the '+english+'. Use the same subject with a static close-up camera shot in soft light. Finish on a clear hero frame with ambient audio.')
    for i,scene in enumerate(result['scenes']):
        scene.update(visual=('Detail ' if i==0 else 'Tampilan utuh ')+subject,action='Perlihatkan '+subject,
                     production_prompt='Use a '+('close-up' if i==0 else 'medium')+' camera shot of the same '+english+' in soft light. Keep the identity and shape stable.')
    for key in director.LIST_FIELDS:result[key]=['Pertahankan '+subject]
    return result


class DirectorV2Tests(unittest.TestCase):
    setUp=VideoTests.setUp

    def submit(self,subject,english,idea,project=None,version=0,key=None):
        payload={'csrf_token':'video-test-csrf','idea':idea,'operation_key':key or 'v2-controlled-key-'+str(version)}
        if project:payload.update(project_id=str(project),version=str(version))
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(director.requests,'post',return_value=provider_response(plan(subject,english))) as calls:
            response=self.client.post('/kilas-ai/video/plan',data=payload)
        return response,calls

    def test_real_store_replacement_chain_and_history(self):
        project=None
        for version,(subject,english,idea) in enumerate([('mobil','car','Bikin video mobil 10 detik'),('baju','shirt','Ganti jadi baju'),('makanan','food','Ganti jadi makanan')]):
            response,calls=self.submit(subject,english,idea,project,version)
            self.assertEqual(response.status_code,200,response.text)
            project=response.json['id'];row=store.get(self.owner,project)
            current=json.loads(row['spec_json']);opts=json.loads(row['options_json'])
            self.assertEqual(row['title'],'Arahan '+subject);self.assertEqual(row['version'],version+1)
            self.assertEqual(opts['_brief']['subject'],subject)
            self.assertNotIn('_brief',response.json['controls'])
            self.assertEqual(calls.call_count,2)
            sent=json.loads(calls.call_args.kwargs['json']['messages'][1]['content'])
            if version:self.assertIsNone(sent['previous_spec'])
            if version==2:
                for retired in ('mobil','baju','car','shirt'):
                    self.assertIsNone(re.search(r'(?i)\b'+retired+r'\b',json.dumps(current)));self.assertIsNone(re.search(r'(?i)\b'+retired+r'\b',response.json['html']))
        snapshots=fixture.db.query_all('SELECT version,spec_json FROM kilas_video_revisions WHERE project_id=? ORDER BY version',(project,))
        self.assertEqual([r['version'] for r in snapshots],[1,2,3])
        self.assertEqual(json.loads(snapshots[0]['spec_json'])['brief']['subject'],'mobil')
        self.assertEqual(json.loads(snapshots[2]['spec_json'])['brief']['subject'],'makanan')

    def test_patch_preserves_unrelated_brief_and_active_spec(self):
        old=briefs.commit(briefs.build('Mobil merah di studio 10 detik',{}),plan('mobil','car'))
        revised=briefs.build('lebih premium',{'_brief':old},plan('mobil','car'),1)
        self.assertEqual(revised['subject'],'mobil');self.assertEqual(revised['duration'],10)
        self.assertEqual(revised['revision_kind'],'STYLE_CHANGE')
        self.assertIsNotNone(briefs.generation_context(revised,plan('mobil','car')))

    def test_preserve_person_replace_product_avoids_old_product_reference(self):
        old={'subject':'parfum','product':'parfum','talent':'talent yang sama','location':'studio'}
        revised=briefs.build('orangnya tetap sama tapi sekarang produknya skincare',{'_brief':old},spec(),1)
        self.assertEqual(revised['revision_kind'],'PRESERVE_AND_REPLACE')
        self.assertEqual(revised['talent'],old['talent']);self.assertNotIn('product',revised)
        self.assertEqual(revised['subject'],'skincare');self.assertIsNone(briefs.generation_context(revised,spec()))

    def test_core_replacement_drops_unrequested_reference(self):
        old=briefs.commit(briefs.build('mobil merah',{}),plan('mobil','car'))
        revised=briefs.build('ganti jadi makanan',{'_brief':old},plan('mobil','car'),1)
        self.assertFalse(revised['use_references']);self.assertNotIn('working_title',revised)
        self.assertNotIn('product',revised)

    def test_attribute_replacement_removes_old_location_and_talent(self):
        old={'subject':'skincare','product':'skincare','location':'Jakarta rooftop','talent':'man','seed_instruction':'man on Jakarta rooftop'}
        location=briefs.build('ganti lokasi jadi bedroom studio',{'_brief':old},spec(),1)
        self.assertEqual(location['location'],'bedroom studio');self.assertNotIn('seed_instruction',location)
        talent=briefs.build('ganti orang jadi woman',{'_brief':location},spec(),2)
        self.assertEqual(talent['talent'],'woman');self.assertIsNone(briefs.generation_context(talent,spec()))

    def test_quality_rejects_stale_english_and_indonesian_subjects(self):
        brief=briefs.build('ganti jadi makanan',{'_brief':{'subject':'mobil','subject_en':'car'}},spec(),1)
        for field,contamination in [('title',' mobil'),('master_prompt',' the car')]:
            value=plan('makanan','food');value[field]+=contamination
            with self.assertRaises(ValueError):director.quality(value,brief)

    def test_quality_language_timing_claims_placeholders_duplicates(self):
        brief=briefs.build('video skincare',{})
        for mutate in [lambda s:s.update(master_prompt='Tampilkan produk ini dengan kamera statis selama sepuluh detik.'),
                       lambda s:s['scenes'][1].update(start=3),lambda s:s.update(story='Terbukti klinis menyembuhkan'),
                       lambda s:s.update(hook='TODO'),lambda s:s['scenes'][1].update(visual=s['scenes'][0]['visual'])]:
            value=spec();mutate(value)
            with self.assertRaises(ValueError):director.quality(value,brief)

    def test_bounded_refinement_and_total_usage(self):
        bad=spec();bad['master_prompt']='Arahan dengan kamera statis.'
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(director.requests,'post',side_effect=[provider_response(bad),provider_response()]) as calls:
            value=director.generate(self.owner,'bounded-repair-123456','video skincare',{})
        self.assertEqual(value,spec());self.assertEqual(calls.call_count,2)
        usage=fixture.db.query_one('SELECT input_tokens,output_tokens,estimated_cost_usd,model FROM kilas_ai_usage WHERE user_id=?',(self.owner,))
        self.assertEqual(usage['input_tokens'],500);self.assertEqual(usage['output_tokens'],1200)
        self.assertEqual(usage['model'],'gpt-6.1-sol');self.assertGreater(float(usage['estimated_cost_usd']),0)

    def test_two_failed_reviews_never_store_contaminated_plan(self):
        first,_=self.submit('mobil','car','video mobil');project=first.json['id']
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(director.requests,'post',return_value=provider_response(plan('mobil','car'))) as calls:
            failed=self.client.post('/kilas-ai/video/plan',data={'csrf_token':'video-test-csrf','idea':'ganti jadi makanan','project_id':project,'version':1,'operation_key':'bad-replacement-key-123456'})
        self.assertEqual(failed.status_code,503);self.assertEqual(calls.call_count,2)
        self.assertEqual(store.get(self.owner,project)['title'],'Arahan mobil')
        self.assertEqual(store.get(self.owner,project)['version'],1)

    def test_english_adapters_are_distinct_without_mutating_plan(self):
        value=spec();before=copy.deepcopy(value)
        prompts=[adapters.package(value,t)['platform'] for t in director.TOOLS]
        self.assertEqual(len(set(prompts)),5);self.assertEqual(value,before)
        for text in prompts:self.assertNotIn('detik',text);self.assertNotIn('Pertahankan',text)

    def test_explicit_no_voice_over_persists_and_new_format_wins(self):
        first=briefs.build('tanpa voice-over, 10 detik',{})
        second=briefs.build('lebih premium',{'_brief':first},spec(),1)
        self.assertEqual(second['voice_over'],'disabled')
        third=briefs.build('pakai voice-over 30 detik',{'_brief':second},spec(),2)
        self.assertEqual(third['duration'],30);self.assertEqual(third['voice_over'],'requested')

    def test_scene_and_format_classification(self):
        old=briefs.commit(briefs.build('video skincare',{}),spec())
        scene=briefs.build('scene 2 ubah kameranya jadi tracking',{'_brief':old},spec(),1)
        self.assertEqual(scene['revision_kind'],'SCENE_CHANGE')
        format_change=briefs.build('sekarang versi Runway 15 detik',{'_brief':old},spec(),1)
        self.assertEqual(format_change['revision_kind'],'FORMAT_CHANGE');self.assertEqual(format_change['duration'],15)

    def test_300_offline_canonical_evaluations(self):
        cases=json.loads((Path(__file__).parent/'fixtures/kilas_video_corpus.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(cases),300)
        for c in cases:
            with self.subTest(c=c['id']):
                old={'subject':c['old_subject'],'subject_en':c['old_subject_en'],'product':c['old_subject'],'location':'studio','duration':10}
                updated=briefs.build(c['revision'],{'_brief':old},spec(),1)
                self.assertEqual(updated['subject'],c['new_subject'])
                self.assertIn(c['old_subject'],updated['retired_subjects'])
                self.assertIsNone(briefs.generation_context(updated,spec()))
                director.quality(plan(c['new_subject'],c['new_subject_en']),updated)


if __name__=='__main__':unittest.main()
