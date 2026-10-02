"""Structural and multi-turn regression coverage; no live model acceptance claims."""
import json
import os
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parents[1]))
import test_kilas_ai_cost_quality as base
from kilas_ai import chat_quality as quality, model_policy as policy, providers, usage, store, fair_use, conversation_context, routing


def reply(text='Jawaban yang berguna dengan penjelasan praktis dan langkah berikutnya.', tokens=100, finish='stop'):
    yield {'type':'provider','provider':'openai','model':policy.LUNA}
    yield {'type':'delta','text':text}
    yield {'type':'usage','input_tokens':tokens,'output_tokens':50,'cached_input_tokens':20}
    yield {'type':'finish','reason':finish}


class QualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base.CostQualityTests.setUpClass()

    def setUp(self):
        base.CostQualityTests.setUp(self)

    def spend(self, cost):
        base.CostQualityTests.spend(self,cost)

    def source(self, prompt='halo'):
        key='quality-'+self.id()
        _, ops=usage.reserve(self.uid,self.thread,key,'SMART','CHAT')
        return quality.ChatQualityStream(self.uid,self.thread,key,'SMART',ops,
                                        policy.ChatContext([{'role':'user','content':prompt}]))

    def test_reasoning_examples(self):
        for prompt in ('menurut lu usaha laundry apa cafe modal 200jt','gw bingung mending beli mobil atau sewa dulu','coba analisis bisnis gw','kenapa query SQL gw begini','coba cari kemungkinan salahnya','bikin strategi marketing yang realistis','bandingin pilihan ini','kalau kondisinya begini menurut lu gimana'):
            with self.subTest(prompt=prompt):
                self.assertEqual(policy.chat_profile([{'role':'user','content':prompt}])['effort'],'medium')
        for prompt in ('halo','translate ini','apa itu API','berapa arti kata ini','benerin typo kalimat ini','buat caption pendek'):
            self.assertEqual(policy.chat_profile([{'role':'user','content':prompt}])['effort'],'low')
        self.assertEqual(policy.chat_tier('translate: business strategy and SQL debugging'),'QUICK')
        self.assertEqual(policy.chat_tier('Modal saya 15 juta, saya bekerja sendiri, hanya punya dua jam sehari, dan harus bisa mulai dari rumah.'),'DEEP')
        self.assertEqual(routing.tool_for('jelaskan berita terbaru hari ini'),'WEB')
        self.assertEqual(routing.tool_for('menurut lu harga emas sekarang berapa?'),'WEB')
        self.assertNotIn('none',[effort for effort,_ in policy.TIERS.values()])

    def test_attachment_evidence_does_not_turn_simple_question_into_analysis(self):
        prompt = "Apa isi PDF ini?\n\nTeks berikut berhasil diekstrak dari lampiran 'info.pdf'.\n<isi_lampiran>analysis strategy debug sql</isi_lampiran>"
        self.assertEqual(policy.chat_profile([{'role':'user','content':prompt}])['effort'],'low')
        self.assertEqual(quality.latest_text([{'role':'user','content':prompt}]),'Apa isi PDF ini?')

    def test_guard_broken_patterns_and_explicit_code(self):
        for answer in ('','reasoning_effort=medium','Saya memakai provider OpenAI.','<svg></svg>','Lorem ipsum','Saya sudah mencari di internet.','PDF sudah dibuat.','File created successfully.','\n\n'.join(['Kalimat panjang berulang yang sama persis dan tidak menambah informasi sama sekali.']*2), ' '.join(['https://example.test/'+str(i) for i in range(21)])):
            with self.subTest(answer=answer):self.assertTrue(quality.violations('Jelaskan ini',answer))
        self.assertFalse(quality.violations('buat kode SVG','```svg\n<svg></svg>\n```'))
        self.assertFalse(quality.violations('halo','Halo!'))
        self.assertFalse(quality.violations('translate: PDF sudah dibuat.', 'PDF sudah dibuat.'))
        self.assertFalse(quality.violations('Analisis singkat satu kalimat','Tes permintaan sebelum sewa toko.',tier='DEEP'))
        self.assertTrue(quality.violations('Analisis bisnis laundry dengan modal 200 juta','Laundry lebih bagus.',tier='DEEP'))
        self.assertTrue(quality.violations('Jelaskan','Kalimat terpotong',finish='length'))

    def test_good_stream_is_one_call_and_streams_before_finish(self):
        source=self.source()
        with patch.object(providers,'stream',side_effect=lambda *a,**k:reply()) as call:
            events=iter(source)
            self.assertEqual(next(events)['type'],'provider')
            self.assertEqual(next(events)['type'],'delta')
            list(events)
        self.assertEqual(call.call_count,1)
        self.assertFalse(source.retried)

    def test_guard_allows_exactly_one_metered_luna_medium_retry(self):
        source=self.source('Analisis bisnis saya dengan modal 150 juta untuk laundry')
        with patch.object(providers,'stream',side_effect=[reply('PDF sudah dibuat.'),reply()]) as call:
            events=list(source)
        self.assertEqual(call.call_count,2)
        self.assertEqual(policy.chat_profile(call.call_args.args[1])['effort'],'medium')
        self.assertIn(quality.REPAIR,call.call_args.kwargs['system'])
        self.assertTrue(source.initial_finalized)
        self.assertEqual(sum(e['type']=='reset' for e in events),1)
        rows=base.fixture.db.query_all('SELECT status,model,input_tokens FROM kilas_ai_usage WHERE user_id=? ORDER BY id',(self.uid,))
        self.assertEqual([(r['status'],r['model'],r['input_tokens']) for r in rows],[('FAILED',policy.LUNA,100),('COMPLETE',policy.LUNA,100)])

    def test_second_bad_answer_stops_and_is_charged(self):
        source=self.source()
        with patch.object(providers,'stream',side_effect=lambda *a,**k:reply('PDF sudah dibuat.')) as call:
            with self.assertRaises(providers.ProviderError):list(source)
        self.assertEqual(call.call_count,2)
        self.assertEqual(base.fixture.db.query_one("SELECT COUNT(*) n FROM kilas_ai_usage WHERE user_id=? AND status='FAILED'",(self.uid,))['n'],2)

    def test_provider_failure_does_not_retry(self):
        source=self.source()
        with patch.object(providers,'stream',side_effect=providers.ProviderError()) as call:
            with self.assertRaises(providers.ProviderError):list(source)
        self.assertEqual(call.call_count,1)

    def test_retry_respects_ceiling_after_first_actual_usage(self):
        self.spend(fair_use.sustainability_ceiling(99000)-Decimal('0.0001'))
        source=self.source()
        with patch.object(providers,'stream',side_effect=lambda *a,**k:reply('PDF sudah dibuat.',tokens=100000)) as call:
            with self.assertRaisesRegex(providers.ProviderError,'limited'):list(source)
        self.assertEqual(call.call_count,1)
        self.assertTrue(source.initial_finalized)

    def test_retry_respects_burst(self):
        source=self.source()
        with patch.dict(os.environ,{'KILAS_AI_BURST_PER_MINUTE':'1'}),patch.object(providers,'stream',side_effect=lambda *a,**k:reply('PDF sudah dibuat.')) as call:
            with self.assertRaises(providers.ProviderError):list(source)
        self.assertEqual(call.call_count,1)

    def test_actual_provider_stream_allows_guard_to_repair_empty_completed_answer(self):
        source=self.source()
        empty=[{'type':'usage','input_tokens':10,'output_tokens':30},{'type':'finish','reason':'stop'}]
        good=[{'type':'delta','text':'Halo!'}, {'type':'usage','input_tokens':10,'output_tokens':30},{'type':'finish','reason':'stop'}]
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic'}),patch.object(providers,'_openai',side_effect=[empty,good]) as adapter:
            events=list(source)
        self.assertEqual(adapter.call_count,2)
        self.assertEqual(adapter.call_args.args[0],policy.LUNA)
        self.assertEqual(policy.chat_profile(adapter.call_args.args[2])['effort'],'medium')
        self.assertIn({'type':'delta','text':'Halo!'},events)

    def test_missing_usage_never_unlocks_retry(self):
        source=self.source()
        events=[{'type':'provider','provider':'openai','model':policy.LUNA},{'type':'finish','reason':'stop'}]
        with patch.object(providers,'stream',return_value=events) as call:
            with self.assertRaises(providers.ProviderError):list(source)
        self.assertEqual(call.call_count,1)
        row=base.fixture.db.query_one('SELECT estimated_cost_usd FROM kilas_ai_usage WHERE user_id=?',(self.uid,))
        self.assertIsNone(row['estimated_cost_usd'])

    def test_visual_risk_output_is_not_emitted_before_guard(self):
        source=self.source('Apakah logo saya bagus?')
        with patch.object(providers,'stream',side_effect=[reply('<svg></svg>'),reply()]):
            events=list(source)
        self.assertFalse(any(e.get('text')=='<svg></svg>' for e in events))

    def test_summary_keeps_whole_corrections_and_new_constraints(self):
        rows=[{'role':'user','content':'modal gw 200 juta; jangan cafe'}]+[{'role':'user','content':'obrolan biasa '+str(i)} for i in range(100)]+[{'role':'user','content':'eh koreksi cuma 150 juta'},{'role':'user','content':'ganti jadi boleh cafe, sebenarnya pilih kios'}]
        state=conversation_context.summary(rows,250)
        self.assertLessEqual(len(state),250)
        self.assertIn('koreksi cuma 150 juta',state)
        self.assertIn('ganti jadi boleh cafe',state)
        self.assertLess(state.index('jangan cafe'),state.index('boleh cafe'))

    def test_repeating_an_old_decision_later_is_the_latest_decision(self):
        rows=[{'role':'user','content':'modal 200 juta'}, {'role':'user','content':'koreksi 150 juta'}, {'role':'user','content':'modal 200 juta'}]
        state=conversation_context.summary(rows)
        self.assertLess(state.index('150 juta'),state.index('200 juta'))

    def test_thread_latest_correction_change_of_mind_and_followup_are_ordered(self):
        turns=['modal gw 200 juta; jangan cafe']+['Percakapan '+str(i) for i in range(20)]+['eh koreksi cuma 150 juta','sebenarnya cafe boleh','jadi mending apa?']
        for i,text in enumerate(turns):store.append_user_once(self.uid,self.thread,text,'FAST','turn-'+str(i))
        messages=store.context(self.uid,self.thread)
        joined='\n'.join(m['content'] for m in messages)
        self.assertLess(joined.index('200 juta'),joined.index('150 juta'))
        self.assertLess(joined.index('jangan cafe'),joined.index('cafe boleh'))
        self.assertEqual(messages[-1]['content'],'jadi mending apa?')
        self.assertLessEqual(len(joined),18500)
        self.assertLessEqual(len(messages),13)

    def test_analytical_short_followup_inherits_reasoning(self):
        messages=policy.ChatContext([{'role':'user','content':'Analisis bisnis laundry'}, {'role':'assistant','content':'Bandingkan biaya.'},{'role':'user','content':'kalau 150 juta?'}])
        self.assertEqual(policy.chat_profile(messages)['effort'],'medium')

    def test_corpus_traits_and_multiturn_counts(self):
        cases=json.loads((Path(__file__).parent/'fixtures/kilas_conversation_standard.json').read_text())
        self.assertGreaterEqual(len(cases),200)
        self.assertGreaterEqual(sum(bool(c.get('first_user') and c.get('follow_up')) for c in cases),60)
        for c in cases:
            if not c.get('turns'):continue
            with self.subTest(c=c['id']):
                self.assertEqual(policy.chat_tier(c['follow_up']),c['reasoning_tier'])
                self.assertEqual(routing.tool_for(c['follow_up'],has_previous_content=True,previous_answer=c['prior_assistant']),c['tool_intent'])

    def test_send_and_regenerate_clear_broken_prose_and_persist_repair(self):
        client=base.fixture.app.app.test_client()
        with client.session_transaction() as state:state.update(user_id=self.uid,role='CLIENT_OWNER',_csrf_token='quality-csrf')
        for endpoint in ('send','regenerate'):
            with patch.object(providers,'stream',side_effect=[reply('PDF sudah dibuat.'),reply('Ini jawaban yang berhasil diperbaiki.')]) as call:
                response=client.post(f'/kilas-ai/threads/{self.thread}/{endpoint}',json={'content':'halo','operation_key':'qualityop_'+endpoint+'0123456789'},headers={'X-CSRF-Token':'quality-csrf'})
                output=response.text
            self.assertEqual(response.status_code,200)
            self.assertIn('event: reset',output)
            self.assertIn('event: done',output)
            self.assertEqual(call.call_count,2)
            self.assertEqual(store.messages(self.uid,self.thread)[-1]['content'],'Ini jawaban yang berhasil diperbaiki.')


if __name__=='__main__':unittest.main()
