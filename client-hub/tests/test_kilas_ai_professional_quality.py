"""Curated answer-contract regression tests; never live model or truth benchmarks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]))
import kilas_ai_conversation_eval as evaluator
from kilas_ai import response_style, conversation_standard, model_policy


class ProfessionalQualityTests(unittest.TestCase):
    def test_pairs_have_supplied_facts_requested_parts_and_distinct_examples(self):
        cases=evaluator.professional_pairs()
        self.assertEqual(len(cases),10)
        self.assertEqual({case['id'] for case in cases},{f'P{i:03d}' for i in range(1,11)})
        self.assertGreaterEqual(sum(len(case['turns'])>1 for case in cases),5)
        for case in cases:
            with self.subTest(case=case['id']):
                self.assertTrue(case['ground_truth'] and case['requested_parts'] and case['required_parts'])
                self.assertEqual(case['turns'][-1]['role'],'user')
                self.assertNotEqual(case['good_answer'],case['bad_answer'])
                self.assertEqual(evaluator.evaluate_professional(case,case['good_answer']),[])
                self.assertTrue(evaluator.evaluate_professional(case,case['bad_answer']))

    def test_partial_reply_flags_missing_requested_parts(self):
        case=next(case for case in evaluator.professional_pairs() if case['id']=='P002')
        flags=evaluator.evaluate_professional(case,'Profit Rp3.000.000; margin 25%.')
        self.assertIn('missing_part:cost_action',flags)
        self.assertIn('missing_part:price_action',flags)

    def test_correct_simple_answer_is_not_penalized_for_being_short(self):
        case=evaluator.professional_pairs()[0]
        self.assertEqual(evaluator.evaluate_professional(case,'391.'),[])
        self.assertIn('explicit_length_ignored',evaluator.evaluate_professional(case,'391. Saya akan menjelaskan konsep perkalian secara panjang lebar.'))

    def test_source_abstention_and_correction_examples_remain_honest(self):
        cases={case['id']:case for case in evaluator.professional_pairs()}
        self.assertIn('unreturned_url',evaluator.evaluate_professional(cases['P005'],cases['P005']['good_answer']+' https://invented.example/citation'))
        self.assertEqual(evaluator.evaluate_professional(cases['P006'],cases['P006']['good_answer']),[])
        self.assertIn('known_bad_pattern:modal Rp15 juta',evaluator.evaluate_professional(cases['P003'],cases['P003']['bad_answer']))
        self.assertIn('missing_part:outline_boundary',evaluator.evaluate_professional(cases['P010'],'Laporannya belum tersedia.'))

    def test_fixture_checker_is_not_a_semantic_judge(self):
        case={'required_parts':{'result':['391']}}
        # Includes the required keyword while contradicting it: human rubric must reject.
        self.assertEqual(evaluator.evaluate_professional(case,'391 is not correct; the answer is 999.'),[])

    def test_runtime_guidance_is_bounded_and_does_not_load_examples(self):
        self.assertLess(len(response_style.CHAT_SYSTEM),4000)
        self.assertLess(len(response_style.ANSWER_COMPLETENESS),550)
        self.assertIn('every requested part',response_style.CHAT_SYSTEM)
        self.assertIn('Honor explicit length and language preferences',response_style.CHAT_SYSTEM)
        self.assertIn('latest correction',response_style.CHAT_SYSTEM)
        self.assertIn('no Web result was provided',response_style.CHAT_SYSTEM)
        self.assertIn('untrusted data',response_style.CHAT_SYSTEM)
        for case in evaluator.professional_pairs():
            self.assertNotIn(case['good_answer'],response_style.CHAT_SYSTEM)
        self.assertTrue({'all_requested_parts','source_honesty','actionable_completeness'}<=set(conversation_standard.EVALUATION_DIMENSIONS))
        self.assertEqual(model_policy.chat_profile([{'role':'user','content':'halo'}])['model'],model_policy.LUNA)

    def test_offline_cli_reads_synthetic_responses_without_provider_calls(self):
        responses={case['id']:case['good_answer'] for case in evaluator.professional_pairs()}
        with tempfile.TemporaryDirectory(prefix='kilas-professional-') as folder:
            path=Path(folder)/'responses.json';path.write_text(json.dumps(responses,ensure_ascii=False),encoding='utf-8')
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('kilas_ai_conversation_eval.py')),'--professional',str(path)],capture_output=True,text=True,check=False,timeout=10,env=os.environ)
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(result.stdout)
        self.assertEqual(report['checked'],10)
        self.assertEqual(report['failures'],{})
        self.assertIn('human review',report['label'])


if __name__=='__main__':unittest.main()
