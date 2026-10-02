"""Unified routing and shared quality contract; synthetic owners and transports."""
import io
import os
import unittest
from unittest.mock import patch
import test_kilas_work_v2 as base
from kilas_ai import unified_runtime, agent_chat, providers, model_policy, agent_store, work_artifacts, store


def answer(text='Halo! Ada yang bisa saya bantu?'):
    yield {'type':'provider','provider':'openai','model':model_policy.LUNA}
    yield {'type':'delta','text':text}
    yield {'type':'usage','input_tokens':100,'output_tokens':60}
    yield {'type':'finish','reason':'stop'}


class UnifiedTests(unittest.TestCase):
    setUp=base.WorkV2Tests.setUp
    client=base.WorkV2Tests.client
    submit=base.WorkV2Tests.submit
    tick=base.WorkV2Tests.tick
    complete=base.WorkV2Tests.complete
    jobs=base.f.fixture.store

    def test_routing_matrix(self):
        for prompt,expected in (
            ('halo','CHAT'),('menurut lu modal 150 juta mending laundry atau cafe?','CHAT'),
            ('versi iOS terbaru sekarang berapa?','WEB'),('buat logo Kilas Works','IMAGE_GENERATE'),
            ('buat kode SVG logo Kilas Works','CHAT'),('kamu bisa bikin PDF ga?','CHAT'),
            ('buat company profile Kilas Works jadi PDF','DOCUMENT'),('buat PPTX company profile','DOCUMENT'),
            ('buat XLSX budget','DOCUMENT'),('ingatkan aku besok jam 8 bayar tagihan','SCHEDULE'),
            ('setiap Senin jam 8 cek laporan','SCHEDULE')):
            with self.subTest(prompt=prompt):self.assertEqual(unified_runtime.intent(prompt),expected)

    def test_ordinary_and_capability_never_create_jobs(self):
        with patch.object(providers,'stream',side_effect=lambda *a,**k:answer()) as called:
            self.submit('halo');self.submit('kamu bisa bikin PDF ga?')
        self.assertEqual(called.call_count,2)
        self.assertEqual(self.jobs.list_jobs(self.owner),[])

    def test_analysis_uses_luna_medium_without_job(self):
        with patch.object(providers,'stream',side_effect=lambda *a,**k:answer('Laundry lebih cocok bila ingin tim kecil. Uji permintaan dan hitung biaya sewa, mesin, air, listrik serta cadangan kas sebelum memilih.')) as called:
            self.submit('menurut lu modal 150 juta mending laundry atau cafe?')
        self.assertEqual(model_policy.chat_profile(called.call_args.args[1])['effort'],'medium')
        self.assertEqual(called.call_count,1)
        self.assertEqual(self.jobs.list_jobs(self.owner),[])

    def test_current_information_searches_real_tool_without_chat_or_job(self):
        result={'text':'Versi terverifikasi dari sumber resmi.','citations':[{'url':'https://www.python.org/downloads/','title':'Python'}],'model':model_policy.LUNA,'usage':{'input_tokens':10,'output_tokens':10}}
        with patch.object(unified_runtime.tools,'web_search_steps',return_value=iter([{'result':result}])) as search,patch.object(providers,'stream',side_effect=AssertionError('ordinary current-info answer')):
            self.submit('versi Python terbaru sekarang apa?')
        self.assertEqual(search.call_count,1)
        self.assertEqual(self.jobs.list_jobs(self.owner),[])
        self.assertIn('https://www.python.org/downloads/',agent_store.messages(self.owner,conversation_id=self.conversation)[-1]['content'])

    def test_search_failure_does_not_claim_unverified_answer(self):
        with patch.object(unified_runtime.tools,'web_search_steps',side_effect=RuntimeError('synthetic failure')):
            self.submit('kurs dolar sekarang berapa?')
        self.assertIn('belum dapat diperiksa',agent_store.messages(self.owner,conversation_id=self.conversation)[-1]['content'])

    def test_explicit_svg_code_stays_chat(self):
        with patch.object(providers,'stream',side_effect=lambda *a,**k:answer('```svg\n<svg></svg>\n```')):
            self.submit('buat kode SVG logo Kilas Works')
        self.assertEqual(self.jobs.list_jobs(self.owner),[])

    def test_bounded_transform_does_not_enter_worker(self):
        with patch.object(providers,'stream',side_effect=lambda *a,**k:answer('Kalimat yang diperbaiki.')):
            self.submit('perbaiki typo kalimat ini: haloo')
        self.assertEqual(self.jobs.list_jobs(self.owner),[])

    def test_quality_one_bounded_retry(self):
        with patch.object(providers,'stream',side_effect=[answer('PDF sudah dibuat.'),answer()]) as called:
            self.submit('halo')
        self.assertEqual(called.call_count,2)
        self.assertEqual(model_policy.chat_profile(called.call_args.args[1])['effort'],'medium')
        self.assertEqual(agent_store.messages(self.owner,conversation_id=self.conversation)[-1]['content'],'Halo! Ada yang bisa saya bantu?')

    def test_second_bad_answer_stops(self):
        with patch.object(providers,'stream',side_effect=lambda *a,**k:answer('PDF sudah dibuat.')) as called:
            self.submit('halo')
        self.assertEqual(called.call_count,2)
        self.assertIn('belum bisa menjawab',agent_store.messages(self.owner,conversation_id=self.conversation)[-1]['content'])

    def test_provider_failure_no_fallback(self):
        with patch.object(providers,'stream',side_effect=providers.ProviderError('synthetic')) as called:
            self.submit('halo')
        self.assertEqual(called.call_count,1)
        self.assertIn('belum bisa menjawab',agent_store.messages(self.owner,conversation_id=self.conversation)[-1]['content'])

    def test_latest_correction_remains_last_in_bounded_context(self):
        agent_store.append(self.owner,'user','Modal 200 juta untuk cafe',self.conversation)
        agent_store.append(self.owner,'assistant','Pertimbangkan biaya tim.',self.conversation)
        with patch.object(providers,'stream',side_effect=lambda *a,**k:answer('Gunakan modal 150 juta untuk laundry. Uji permintaan, hitung biaya mesin, dan sisakan cadangan kas agar tim tetap kecil.')) as called:
            self.submit('koreksi: modal 150 juta, pilih laundry, bukan cafe')
        self.assertIn('koreksi: modal 150 juta',called.call_args.args[1][-1]['content'])

    def test_real_pdf_through_unified_submission(self):
        self.submit('buat company profile Kilas Works jadi PDF')
        job=self.jobs.list_jobs(self.owner)[0]['id']
        with patch.object(base.f.content_worker,'text',return_value=(base.f.SOURCE.replace('Rp5.000.000','belum ditentukan'),model_policy.LUNA,{})):
            self.tick(job);self.tick(job)
        file=work_artifacts.listing(self.owner,job_id=job)[0]
        response=self.client().get(f"/kilas-ai/agent/jobs/{job}/artifacts/{file['id']}")
        self.assertTrue(response.data.startswith(b'%PDF'))
        self.assertEqual(self.jobs.get(self.owner,job)['origin_conversation_id'],self.conversation)

    def test_real_office_files(self):
        for ext,source in [('pptx','# Kilas Works\nLayanan UMKM\n## Tujuan\n- Membantu usaha\n'),('xlsx','Item,Jumlah\nBudget,150000000\n')]:
            with self.subTest(ext=ext):
                self.submit('buat '+ext+' company profile' if ext=='pptx' else 'buat XLSX budget')
                job=self.jobs.list_jobs(self.owner)[0]['id']
                with patch.object(base.f.content_worker,'text',return_value=(source,model_policy.LUNA,{})):
                    self.tick(job);self.tick(job)
                file=work_artifacts.listing(self.owner,job_id=job)[0]
                self.assertTrue(file['name'].endswith('.'+ext))
                self.assertTrue(self.client().get(f"/kilas-ai/agent/jobs/{job}/artifacts/{file['id']}").data.startswith(b'PK'))

    def test_substantial_research_enters_durable_engine(self):
        self.submit('riset 20 kompetitor dan buat laporan')
        self.assertEqual(len(self.jobs.list_jobs(self.owner)),1)
        self.assertEqual(self.jobs.list_jobs(self.owner)[0]['origin_conversation_id'],self.conversation)

    def test_uploaded_and_recent_image_edits_route(self):
        image={'mime_type':'image/png'}
        self.assertEqual(unified_runtime.intent('edit gambar ini jadi lebih terang',[image]),'IMAGE_EDIT')
        self.assertEqual(unified_runtime.intent('buat lebih premium',previous={'media_type':'image/png'}),'IMAGE_EDIT')

    def test_document_revision_retains_context(self):
        self.assertEqual(unified_runtime.intent('buat lebih premium',previous={'media_type':'application/pdf'}),'DOCUMENT')

    def test_image_generation_persists_real_inline_artifact(self):
        from PIL import Image
        raw=io.BytesIO();Image.new('RGB',(24,24),'orange').save(raw,'PNG')
        self.submit('buat logo Kilas Works')
        job=self.jobs.list_jobs(self.owner)[0]['id']
        with patch.dict(os.environ,{'KILAS_AI_OPENAI_IMAGE_MODEL':'configured-image'}),patch.object(unified_runtime.tools,'image',return_value={'raw':raw.getvalue(),'mime':'image/png','model':'configured-image','usage':{}}) as called:
            self.tick(job);self.tick(job)
        self.assertEqual(called.call_count,1)
        file=work_artifacts.listing(self.owner,job_id=job)[0]
        self.assertEqual(file['media_type'],'image/png')
        self.assertEqual(self.client().get(f"/kilas-ai/agent/jobs/{job}/artifacts/{file['id']}").data,raw.getvalue())

    def test_unified_navigation_and_legacy_history(self):
        thread=store.create_thread(self.owner)
        html=self.client().get('/kilas-ai/agent?view=history').text
        self.assertIn('Percakapan sebelumnya',html)
        self.assertIn('/kilas-ai/threads/'+str(thread),html)
        self.assertEqual(self.client().get('/kilas-ai/threads/'+str(thread)).status_code,200)
        html=self.client().get('/kilas-ai/agent').text
        for hidden in ('ai-mode-tabs','id="ai-search"','+ Work baru','Pengaturan Work'):self.assertNotIn(hidden,html)
        self.assertIn('+ Chat baru',html)

    test_waiting_same_job=base.WorkV2Tests.test_started_clarification_waits_without_artifact_and_reply_resumes_same_job
    test_anchored_result=base.WorkV2Tests.test_completed_result_stays_in_original_chat_turn_after_open_and_new_message
    test_reminder_same_conversation_once=base.WorkV2Tests.test_delayed_reminder_same_conversation_once_unread_with_delivery_times


if __name__=='__main__':unittest.main()
