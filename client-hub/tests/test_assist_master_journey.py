"""Signup/training isolation and lifecycle gates; disposable database, no external sends."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import test_client_hub_v1 as fixture
import assist_journey as journey
import assist_training as training

repo, db = fixture.repo, fixture.db


class MasterJourneyTests(unittest.TestCase):
    def setUp(self):
        fixture.reset_db()
        self.uid = repo.create_user('owner@example.test', fixture.security.hash_password('password123'))
        self.other_uid = repo.create_user('other@example.test', fixture.security.hash_password('password123'))
        self.bid = repo.create_business(self.uid, 'Toko Test', 'AI_ADMIN')
        self.other = repo.create_business(self.other_uid, 'Other business', 'AI_ADMIN')
        repo.upsert_business_profile(self.bid, dict(short_description='Jasa foto', category='Fotografi',
            owner_name='Pemilik', operating_hours='09-17', online_or_offline='online',
            business_phone='628123000000', primary_language='id', customer_salutation='Kak'))
        repo.replace_business_services(self.bid, ['Foto produk Rp2.000.000'])
        self.business = repo.get_business(self.bid)
        self.client = fixture.fresh_client()
        with self.client.session_transaction() as session:
            session.update(user_id=self.uid, role='CLIENT_OWNER', _csrf_token='master-test')

    def complete_onboarding(self):
        for step in journey.ONBOARDING_PARTS:
            repo.mark_onboarding_step_done(self.bid, step+'_done')
        journey.start_demo(self.bid, self.uid)

    def teach(self, text='Jangan beri diskon'):
        with patch.object(training.ai_onboarding, '_call_claude', return_value=(json.dumps({
                'reply': 'Baik, diskon membutuhkan izin Anda.', 'knowledge': text}), 'end_turn', None)):
            training.teach(self.business, self.uid, text)

    def test_signup_and_training_require_account_and_six_steps(self):
        anonymous = fixture.fresh_client()
        self.assertEqual(anonymous.get(f'/business/{self.bid}/train').status_code, 302)
        self.assertEqual(anonymous.get(f'/business/{self.bid}/demo-kilas').status_code, 302)
        with self.assertRaisesRegex(ValueError, 'onboarding_incomplete'):
            journey.start_demo(self.bid, self.uid)
        self.assertIn('/wizard/', self.client.get(f'/business/{self.bid}/train').location)
        self.complete_onboarding()
        page = self.client.get(f'/business/{self.bid}/train')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Ajari Kilas', page.text)
        self.assertNotIn('Ya, siap melayani', page.text)

    def test_trial_is_seven_days_and_cannot_restart_on_retry(self):
        self.complete_onboarding()
        before = journey._event(self.bid, journey.DEMO_STEP)
        self.assertEqual(datetime.fromisoformat(before['expires_at'])-
                         datetime.fromisoformat(before['started_at']), timedelta(days=7))
        journey.start_demo(self.bid, self.uid)
        self.assertEqual(before, journey._event(self.bid, journey.DEMO_STEP))
        self.assertIsNone(repo.get_tenant_config_row(self.bid))
        self.assertEqual(db.query_all('SELECT * FROM subscriptions'), [])
        self.assertEqual(db.query_all('SELECT * FROM finance_transactions'), [])

    def test_teaching_updates_existing_knowledge_without_tenant_leak_or_production_reset(self):
        self.complete_onboarding()
        db.execute("UPDATE businesses SET status='ACTIVE' WHERE id=?", (self.bid,))
        self.teach()
        guide = next(r for r in repo.get_business_faqs(self.bid) if r.get('question') == training.GUIDE_QUESTION)
        self.assertEqual(guide['answer'], 'Jangan beri diskon')
        self.teach('Diskon 5 persen hanya setelah saya setuju')
        revised = [r for r in repo.get_business_faqs(self.bid) if r.get('question') == training.GUIDE_QUESTION]
        self.assertEqual(len(revised), 1)
        self.assertEqual(revised[0]['id'], guide['id'])
        self.assertEqual(revised[0]['answer'], 'Diskon 5 persen hanya setelah saya setuju')
        self.assertEqual(repo.get_business_faqs(self.other), [])
        self.assertEqual(repo.get_business(self.bid)['status'], 'ACTIVE')
        self.assertEqual(self.client.get(f'/business/{self.other}/train').status_code, 404)
        self.assertEqual(self.client.get(f'/workspace/usage/{self.other}').status_code, 404)

    def test_only_successful_current_knowledge_test_can_be_confirmed(self):
        self.complete_onboarding()
        self.teach()
        with patch.object(training.ai_onboarding, '_call_claude', return_value=(None, None, 'provider_failure')):
            with self.assertRaisesRegex(ValueError, 'test_unavailable'):
                training.test_reply(self.business, self.uid, 'Bisa diskon?')
        self.assertFalse(training.can_ready(self.bid))
        with patch.object(training.ai_onboarding, '_call_claude', return_value=('Saya tanya pemilik dulu ya.', 'end_turn', None)):
            training.test_reply(self.business, self.uid, 'Bisa diskon?')
        self.assertTrue(training.can_ready(self.bid))
        repo.save_ai_normalized_config(self.bid, 'Jasa foto', {'description':'Jasa foto'}, [])
        training._confirm_ready(self.bid, self.uid)
        self.assertTrue(journey.state(self.business)['ready'])
        self.teach('Tidak ada diskon')
        self.assertFalse(training.can_ready(self.bid))
        self.assertFalse(journey.state(self.business)['ready'])
        self.assertEqual(db.query_all('SELECT * FROM finance_transactions'), [])

    def test_ready_normalization_preserves_exact_tested_owner_knowledge(self):
        self.complete_onboarding();self.teach()
        with patch.object(training.ai_onboarding,'_call_claude',return_value=('Saya tanya pemilik dahulu.','end_turn',None)):
            training.test_reply(self.business,self.uid,'Bisa diskon?')
        before=training.fingerprint(self.bid)
        normalized={'description':'Bisnis uji','services':[], 'faqs':[
            {'question':'Panduan yang ditulis ulang model','answer':'Ringkasan berbeda'}]}
        with patch.object(training.ai_onboarding,'normalize_business_data',return_value=(normalized,None)):
            training.ready(self.business,self.uid)
        self.assertEqual(training.fingerprint(self.bid),before)
        self.assertTrue(journey.state(self.business)['ready'])
        self.assertEqual(db.query_all('SELECT * FROM subscriptions'),[])

    def test_training_and_usage_gets_are_read_only_no_model(self):
        self.complete_onboarding()
        before = db.query_one('SELECT COUNT(*) AS n FROM onboarding_sessions')['n']
        with patch.object(training.ai_onboarding, '_call_claude', side_effect=AssertionError('GET cannot call AI')):
            for path in (f'/business/{self.bid}/train', f'/workspace/usage/{self.bid}', '/workspace/ai'):
                self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM onboarding_sessions')['n'], before)


if __name__ == '__main__':
    unittest.main()
