"""Production knowledge completeness and bounded inference; synthetic data, no network."""
import json
import os
import unittest
from unittest.mock import patch

import test_client_hub_v1 as fixture
import assist_reply
import assist_training
import ai_router

repo, db = fixture.repo, fixture.db


class KnowledgeContractTests(unittest.TestCase):
    def setUp(self):
        fixture.reset_db()
        self.uid = repo.create_user('knowledge-contract@example.test', 'unused')
        self.bid = repo.create_business(self.uid, 'Foto Karawaci', 'AI_ADMIN')
        self.other = repo.create_business(self.uid, 'Other private business', 'AI_ADMIN')
        repo.upsert_business_profile(self.bid, dict(
            address='Jalan Foto 17', business_phone='628111111111',
            trusted_owner_phone='628999999999', closed_days='Minggu',
            operating_hours='09.00-17.00', online_or_offline='offline',
            payment_bank_name='Bank Contoh', payment_account_name='Foto Karawaci',
            payment_account_number='1234567', payment_instructions='DP 50 persen setelah invoice'))
        repo.upsert_business_profile(self.other, dict(address='PRIVATE OTHER ADDRESS'))

    def test_reply_has_owner_entered_contact_hours_and_payment_facts_without_private_owner_number(self):
        knowledge = assist_reply.relevant_knowledge(self.bid, 'Alamat dan rekeningnya di mana?')
        payload = json.dumps(knowledge)
        for fact in ('Foto Karawaci', 'Jalan Foto 17', 'Minggu', '628111111111',
                     'Bank Contoh', '1234567', 'DP 50 persen'):
            self.assertIn(fact, payload)
        self.assertNotIn('628999999999', payload)
        self.assertNotIn('PRIVATE OTHER ADDRESS', payload)

    def test_preview_is_not_teaching_and_updates_preserve_initial_readiness(self):
        version = assist_training.fingerprint(self.bid)
        repo.save_onboarding_session(self.bid, 'assist_test', {'knowledge_version': version}, self.uid)
        self.assertFalse(assist_training.can_ready(self.bid))
        repo.save_onboarding_session(self.bid, 'assist_teach', {'message':'Aturan', 'reply':'Dipahami'}, self.uid)
        assist_training.ready(repo.get_business(self.bid), self.uid)
        repo.upsert_business_profile(self.bid, {'address': 'Alamat baru'})
        self.assertTrue(assist_training.can_ready(self.bid))
        import assist_journey
        self.assertTrue(assist_journey.state(repo.get_business(self.bid))['ready'])
        self.assertIn('Alamat baru', str(assist_reply.relevant_knowledge(self.bid, 'Alamat?')))

    def test_canonical_owner_training_is_kept_with_many_existing_faqs(self):
        rows = [dict(question=f'FAQ {n}', answer='Informasi', raw_input='Informasi') for n in range(65)]
        rows.append(dict(question=assist_training.GUIDE_QUESTION,
                         answer='Diskon hanya atas izin pemilik', raw_input='Panduan'))
        with patch.object(repo, 'get_business_faqs', return_value=rows):
            knowledge = assist_reply.relevant_knowledge(self.bid, 'Halo kak')
        self.assertIn('Diskon hanya atas izin pemilik', str(knowledge))

    @staticmethod
    def result(confidence):
        return json.dumps(dict(reply='Silakan konfirmasi dengan tim.', intent='QUESTION',
            confidence=confidence, knowledge_used=['profile'], evidence='', insight={})), 'end_turn', None

    def test_provider_failure_then_low_confidence_strong_reply_never_calls_a_third_model(self):
        with patch.dict(os.environ, {'KILAS_AI_FAST_PROVIDER': 'openai',
                                    'KILAS_AI_STRONG_PROVIDER': 'anthropic'}), \
                patch.object(ai_router, '_openai', return_value=(None, None, 'unavailable')) as fast, \
                patch.object(assist_reply.ai_onboarding, '_call_claude_direct',
                             return_value=self.result(.2)) as strong:
            reply, _, _ = assist_reply.generate(self.bid, 'Berapa harga?', [])
        self.assertEqual(reply, 'Silakan konfirmasi dengan tim.')
        fast.assert_called_once()
        strong.assert_called_once()

    def test_invalid_structured_fast_result_gets_one_validated_strong_attempt(self):
        with patch.dict(os.environ, {'KILAS_AI_FAST_PROVIDER': 'openai',
                                    'KILAS_AI_STRONG_PROVIDER': 'anthropic'}), \
                patch.object(ai_router, '_openai', return_value=('not JSON', 'end_turn', None)) as fast, \
                patch.object(assist_reply.ai_onboarding, '_call_claude_direct',
                             return_value=self.result(.9)) as strong:
            reply, insight, _ = assist_reply.generate(self.bid, 'Berapa harga?', [])
        self.assertTrue(reply)
        self.assertIsNone(insight['action'])
        fast.assert_called_once()
        strong.assert_called_once()


if __name__ == '__main__':
    unittest.main()
