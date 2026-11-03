"""Offline routing/answer-key and image-option regressions, not model acceptance."""
import sys
import os
from unittest.mock import patch, MagicMock
import unittest
from fractions import Fraction
from math import comb
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
from kilas_ai import intelligence, model_policy, image_options

CASES = [
    ('Buktikan atau bantah: n²+n+41 prima untuk semua bilangan bulat n >= 0.', 'counterexample: n=40, 1681=41²'),
    ('Selesaikan persamaan sqrt(x+1)=x-1 pada bilangan real. Periksa akar ekstraneous.', 'x=3; x=0 excluded'),
    ('Hitung integral dari 0 sampai 1 untuk x²(1-x)³ dx dengan nilai eksak.', '1/60'),
    ('Peluang tepat dua bola merah saat mengambil tiga tanpa pengembalian dari enam merah dan empat biru?', '1/2'),
    ('Rekurensi a_n=3a_(n-1)-2a_(n-2), a_0=2, a_1=3. Tentukan a_20 dan buktikan rumusnya.', '1048577; a_n=1+2^n'),
]


def selected(prompt):
    messages = model_policy.ChatContext([{'role':'user','content':prompt}])
    messages.selected_model = model_policy.LUNA
    return model_policy.chat_profile(messages)


class ChatMathQualityTests(unittest.TestCase):
    def test_hard_math_uses_selected_luna_with_room_for_reasoning_and_solution(self):
        for prompt, key in CASES:
            with self.subTest(prompt=prompt, answer_key=key):
                profile = selected(prompt)
                self.assertEqual(profile['model'], model_policy.LUNA)
                self.assertEqual(profile['domain'], 'math')
                self.assertEqual(profile['effort'], 'high')
                self.assertGreaterEqual(profile['output_tokens'], 16384)
                self.assertIn('mathematical_reasoning', profile['signals'])

    def test_native_transport_receives_math_guidance_and_selected_model(self):
        from kilas_ai import selected_provider, chat_models, providers, capabilities
        messages=model_policy.ChatContext([{'role':'user','content':CASES[2][0]}])
        messages.selected_model=model_policy.LUNA
        response=MagicMock();response.status_code=200
        response.__enter__.return_value=response
        events=[{'model':model_policy.LUNA,'choices':[{'delta':{'content':'1/60'},'finish_reason':'stop'}]}]
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-not-a-key'}), \
             patch.object(chat_models,'check',return_value={'available':True,'images':True}), \
             patch.object(capabilities,'current',return_value={}), \
             patch.object(providers,'_events',return_value=iter(events)), \
             patch.object(selected_provider.requests,'post',return_value=response) as post:
            list(selected_provider.stream('SMART',messages))
        payload=post.call_args.kwargs['json']
        self.assertEqual(payload['model'],model_policy.LUNA)
        self.assertEqual(payload['reasoning_effort'],'high')
        self.assertEqual(payload['max_completion_tokens'],16384)
        self.assertIn('checkable solution',payload['messages'][0]['content'])
        self.assertIn('counterexample',payload['messages'][0]['content'])
        self.assertEqual(post.call_count,1)

    def test_answer_keys_are_independently_checked_not_provider_outputs(self):
        self.assertEqual(40**2+40+41, 41**2)
        roots = [x for x in (0,3) if x>=1 and x+1 == (x-1)**2]
        self.assertEqual(roots, [3])
        integral = sum(Fraction((-1)**k*comb(3,k),k+3) for k in range(4))
        self.assertEqual(integral, Fraction(1,60))
        self.assertEqual(Fraction(comb(6,2)*comb(4,1),comb(10,3)), Fraction(1,2))
        a,b=2,3
        for n in range(2,21): a,b=b,3*b-2*a
        self.assertEqual(b,1048577)
        self.assertEqual(b,1+2**20)

    def test_brief_math_preserves_reasoning_not_forced_visible_verbosity(self):
        self.assertEqual(selected('What is the integral of x^2 from 0 to 1?')['effort'],'high')
        profile=selected(CASES[2][0]+' Jawab singkat.')
        self.assertEqual((profile['depth'],profile['effort']),('QUICK','high'))
        self.assertGreaterEqual(profile['output_tokens'],8192)
        self.assertIn('brief final answer',intelligence.playbook(profile))

    def test_plain_calculation_definition_and_transformation_are_not_escalated(self):
        for prompt in ('2+2', 'Apa itu integral?', 'Buktikan pembayaran sudah diterima.', 'Berapa limit kartu saya?', 'Translate: prove the theorem.',
                       "Halo\n\nTeks berikut berhasil diekstrak dari lampiran 'x.txt': integral prove proof"):
            with self.subTest(prompt=prompt):
                self.assertNotEqual(selected(prompt)['domain'],'math')
                self.assertNotEqual(selected(prompt)['effort'],'high')

    def test_followup_preserves_math_and_correction(self):
        messages=model_policy.ChatContext([{'role':'user','content':CASES[4][0]},
            {'role':'assistant','content':'Initial answer.'},
            {'role':'user','content':'Koreksi: a_1=4, yang lain tetap. Jelaskan rumus baru.'}])
        messages.selected_model=model_policy.LUNA
        profile=model_policy.chat_profile(messages)
        self.assertEqual((profile['domain'],profile['effort'],profile['model']),('math','high',model_policy.LUNA))
        self.assertEqual(messages[-1]['content'],'Koreksi: a_1=4, yang lain tetap. Jelaskan rumus baru.')

    def test_autonomous_and_legacy_routing_remain_unchanged(self):
        messages=[{'role':'user','content':CASES[2][0]}]
        self.assertEqual(model_policy.chat_profile(messages)['domain'],'general')
        self.assertEqual(model_policy.agent_planner({'instruction':CASES[2][0]})[0],model_policy.LUNA)


class ImageInstructionQualityTests(unittest.TestCase):
    def options(self,prompt):return image_options.resolve('gpt-image-2.5-sunburst',prompt)

    def test_negated_transparency_and_last_correction(self):
        for prompt in ('Buat logo, jangan transparan.', 'Buat gambar tidak transparan.',
                       'Use a non-transparent background.', "Don't make the background transparent.",
                       'Transparent logo. Correction: use opaque background.',
                       'Buat transparan. Koreksi: jangan transparan.'):
            with self.subTest(prompt=prompt):self.assertFalse(self.options(prompt)['transparent'])
        for prompt in ('Buat logo transparan.', 'Use transparent background.',
                       'Jangan transparan. Koreksi: buat transparan.'):
            with self.subTest(prompt=prompt):self.assertTrue(self.options(prompt)['transparent'])

    def test_native_default_quality_and_dimensions_are_preserved(self):
        options=self.options('Buat gambar kotak biru dengan tulisan KILAS.')
        self.assertEqual((options['size'],options['quality']),('2048x2048','high'))
        self.assertEqual(self.options('Buat gambar 1536x1024')['size'],'1536x1024')
        self.assertEqual(self.options('Buat gambar 9:16')['aspect_ratio'],'9:16')

if __name__=='__main__':unittest.main()
