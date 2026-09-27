"""Signup/training isolation and lifecycle gates; disposable database, no external sends."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

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
        self.assertEqual(journey.state(self.business)['readiness'], 'Belum dilatih')
        self.teach()
        self.assertEqual(journey.state(self.business)['readiness'], 'Sedang dilatih')
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

    def test_last_onboarding_part_starts_demo_and_opens_training_without_extra_step(self):
        for step in journey.ONBOARDING_PARTS[:-1]:
            repo.mark_onboarding_step_done(self.bid, step+'_done')
        result = self.client.post(f'/business/{self.bid}/wizard/upload', data={'csrf_token':'master-test'})
        self.assertEqual(result.status_code, 302)
        self.assertTrue(result.location.endswith(f'/business/{self.bid}/train'))
        self.assertTrue(journey.state(self.business)['demo_active'])
        page = self.client.get(result.location).text
        self.assertIn('Demo 7 hari sudah aktif', page)
        self.assertNotIn('value="start_demo"', page)

    def test_test_confirm_whatsapp_uses_trained_knowledge_in_same_inbox_and_crm(self):
        import assist_demo, assist_reply, routes_client
        from public_chat import schema
        from kilas_core import customer_schema, job_schema, customers, jobs
        from unittest.mock import Mock
        import os
        schema.apply_schema(); customer_schema.apply_schema(); job_schema.apply_schema()
        db.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,number TEXT,mode TEXT,role TEXT,content TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        db.execute('CREATE TABLE customer_profiles(number TEXT PRIMARY KEY,name TEXT)')
        self.complete_onboarding()
        rule = 'Paket Sunrise42 Rp2.345.000, diskon hanya dengan izin pemilik.'
        self.teach(rule)
        repo.replace_business_faqs(self.other, ['Rahasia tenant lain | LUNAR-SECRET'])
        def test_model(prompt, messages, **kwargs):
            self.assertIn(rule, prompt)
            self.assertNotIn('LUNAR-SECRET', prompt)
            return 'Paket Sunrise42 Rp2.345.000. Diskon perlu izin pemilik.', 'end_turn', None
        with patch('knowledge_assist.allow_click', return_value=True), \
             patch.object(training.ai_onboarding, '_call_claude', side_effect=test_model):
            tested = self.client.post(f'/business/{self.bid}/train', data={
                'csrf_token':'master-test','action':'test','message':'Harga Sunrise42?'})
        self.assertEqual(tested.status_code, 303)
        page = self.client.get(tested.location).text
        self.assertIn('Saya sudah memahami cara kamu ingin customer dilayani.', page)
        self.assertIn('Sudah, coba di WhatsApp', page);self.assertIn('Ajari lagi', page)
        self.assertNotIn('Ya, siap melayani', page)
        normalized = {'description':'Jasa foto','services':[],'faqs':[]}
        with patch('knowledge_assist.allow_click', return_value=True), \
             patch.object(training.ai_onboarding,'normalize_business_data',return_value=(normalized,None)):
            launch = self.client.post(f'/business/{self.bid}/train', data={
                'csrf_token':'master-test','action':'ready_whatsapp'})
        parsed = urlparse(launch.location)
        self.assertEqual(parsed.netloc,'wa.me');self.assertEqual(parsed.path,'/'+routes_client._DEMO_KILAS_PHONE)
        message = parse_qs(parsed.query)['text'][0]
        marker = assist_demo.MARKER.search(message).group(0)
        self.assertTrue(journey.state(self.business)['ready'])
        self.assertEqual(assist_demo.latest(self.bid)['business_id'],self.bid)
        self.assertIsNone(assist_demo.latest(self.bid)['sender_phone'])
        phone = '14048836437'
        send = Mock(return_value=(True,None))
        def event(text, ident):return dict(id=ident, **{'from':phone},type='text',text={'body':text})
        def wa_model(prompt, messages, *args, **kwargs):
            payload=json.loads(messages[-1]['content'])
            self.assertIn(rule, json.dumps(payload['knowledge'],ensure_ascii=False))
            self.assertNotIn('LUNAR-SECRET', str(payload))
            text=payload['customer_message']
            request='booking' in text
            return json.dumps(dict(reply='Paket Sunrise42 Rp2.345.000.',intent='REQUEST' if request else 'QUESTION',
                confidence=.95,knowledge_used=list(payload['knowledge']),evidence=text if request else '',
                insight=dict(summary='Minta booking' if request else 'Bertanya harga',
                    action='Atur booking foto' if request else None,job_status='PERLU_TINDAKAN' if request else None))), 'end_turn', None
        with patch.dict(os.environ,{'KILAS_CUSTOMERS_V2_ENABLED':'true','KILAS_JOBS_V2_ENABLED':'true'}), \
             patch.object(assist_reply.ai_router,'complete',side_effect=wa_model) as model:
            self.assertTrue(assist_demo.process(event(message,'binding'),send=send))
            self.assertEqual(send.call_args.args[1],'Demo aktif ✅ Sekarang chat seperti customer bisnis kamu.')
            assist_demo.process(event('Harga Sunrise42?','price'),send=send)
            lead=db.query_one('SELECT id FROM kw_core_customers WHERE business_id=?',(self.bid,))
            self.assertEqual(customers.get_customer(self.bid,lead['id'])['stage'],'LEAD')
            self.assertEqual(jobs.list_jobs(self.bid)[1],0)
            assist_demo.process(event('Saya mau booking foto','booking'),send=send)
            self.assertEqual(customers.get_customer(self.bid,lead['id'])['stage'],'CUSTOMER')
            self.assertEqual(jobs.list_jobs(self.bid)[0][0]['status'],'NEW')
            self.assertEqual(jobs.list_jobs(self.other)[1],0)
            self.assertEqual(model.call_count,2)
        inbox=self.client.get(f'/business/{self.bid}/inbox?source=demo&customer={phone}')
        self.assertEqual(inbox.status_code,200)
        self.assertIn('Paket Sunrise42 Rp2.345.000.',inbox.text)
        self.assertIn('Saya mau booking foto',inbox.text)
        self.assertNotIn(marker,inbox.text)
        self.assertEqual(self.client.get(f'/business/{self.other}/inbox?source=demo&customer={phone}').status_code,404)
        self.assertEqual(assist_demo.rows(self.other,phone),[])
        self.assertEqual(db.query_all('SELECT * FROM finance_transactions'),[])

    def test_stale_or_failed_test_cannot_launch_whatsapp(self):
        import assist_demo
        self.complete_onboarding()
        self.teach()
        with patch('knowledge_assist.allow_click',return_value=True):
            result=self.client.post(f'/business/{self.bid}/train',data={'csrf_token':'master-test','action':'ready_whatsapp'})
        self.assertNotIn('wa.me',result.location)
        self.assertIsNone(assist_demo.latest(self.bid))

        with patch.object(training.ai_onboarding,'_call_claude',return_value=('Baik.','end_turn',None)):
            training.test_reply(self.business,self.uid,'Diskon?')
        self.teach('Tidak boleh diskon')
        with patch('knowledge_assist.allow_click',return_value=True):
            result=self.client.post(f'/business/{self.bid}/train',data={'csrf_token':'master-test','action':'ready_whatsapp'})
        self.assertNotIn('wa.me',result.location)
        self.assertIsNone(assist_demo.latest(self.bid))

    def test_connected_business_hides_demo_without_losing_training(self):
        import routes_client
        self.complete_onboarding();self.teach('Harga tetap Rp2.345.000')
        before=training.fingerprint(self.bid)
        connected=dict(journey.state(self.business),connected=True,demo_visible=False,paid=True,ready=True)
        with patch.object(journey,'state',return_value=connected):
            page=self.client.get(f'/business/{self.bid}/train').text
            self.assertNotIn('Sudah, coba di WhatsApp',page)
            self.assertNotIn('value="ready_whatsapp"',page)
            result=self.client.get(f'/business/{self.bid}/demo-kilas')
            self.assertIn('/inbox',result.location)
            self.assertIsNone(routes_client._demo_kilas_phone_for_business(self.bid))
        self.assertEqual(training.fingerprint(self.bid),before)



if __name__ == '__main__':
    unittest.main()
