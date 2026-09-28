"""Final CRM contract using real Demo/paid persistence and the shared inference boundary."""
import json
import re
import time
import unittest
from unittest.mock import Mock, patch

import test_assist_runtime as runtime_fixture
import assist_demo
import assist_journey
import assist_reply
import assist_training
import ai_router
from kilas_core import customers, customer_insights, customer_action_jobs, jobs, customer_facts
from kilas_core.adapters import whatsapp
import test_client_hub_v1 as fixture

repo, db = fixture.repo, fixture.db


class CRMTests(runtime_fixture.RuntimeTests):
    # Reuse setup only, not inherited test methods: the existing runtime suite owns those.
    test_information_meeting_payment_cancel_and_same_call_explanation = None
    test_takeover_during_model_discards_reply_and_state_writes = None
    test_customer_human_request_persists_until_owner_returns_control = None

    def setUp(self):
        super().setUp()
        db.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT, mode TEXT, role TEXT, content TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        db.execute('CREATE TABLE customer_profiles(number TEXT PRIMARY KEY,name TEXT)')
        repo.upsert_business_profile(self.bid, {'category':'DJ, Content Creator & Influencer',
            'country':'Indonesia', 'short_description':'TENANT ONLY'})
        self.phone = '14048836437'
        self.client = fixture.fresh_client()
        with self.client.session_transaction() as session:
            session.update(user_id=self.uid,role='CLIENT_OWNER',_csrf_token='crm-test')
        self.send = Mock(return_value=(True,None))
        self.marker = None

    def turn(self, text, insight=None, intent='QUESTION', channel='paid', name='Irvan'):
        self.n += 1
        value = dict(reply='Saya bantu cek.',intent=intent,confidence=.95,evidence=text,
                     knowledge_used=['profile'],insight=insight or {})
        with patch.object(ai_router, 'complete', return_value=(json.dumps(value),'end_turn',None)):
            if channel == 'demo':
                with patch.object(assist_demo.assist_journey,'state',return_value={'ready':True,'connected':False,'demo_active':False,'paid':True}):
                    if self.marker is None:
                        _, self.marker = assist_demo.begin(self.bid,self.uid)
                        assist_demo.process({'id':'bind','from':self.phone,'type':'text','text':{'body':self.marker}},
                                            profile_name=name,send=self.send)
                    assist_demo.process({'id':'demo-'+str(self.n),'from':self.phone,'type':'text','text':{'body':text}},
                                        profile_name=name,send=self.send)
            else:
                whatsapp.handle(self.bid,'456',{'messages':[{'id':'paid-'+str(self.n),'from':self.phone,
                    'timestamp':str(int(time.time())),'type':'text','text':{'body':text}}],
                    'contacts':[{'wa_id':self.phone,'profile':{'name':name}}]},'messages')
        self.customer = customers.list_customers(self.bid)[0][0]
        return customer_insights._stored(self.bid,self.customer['id'])['insight']

    def test_information_stays_lead_and_concrete_request_promotes_one_identity(self):
        self.turn('Berapa harga?')
        original = self.customer['id']
        self.assertEqual(self.customer['stage'],'LEAD')
        self.assertEqual(jobs.list_jobs(self.bid)[1],0)
        self.turn('Saya mau cari talent',dict(action='Cari talent',job_status='PERLU_TINDAKAN'),'REQUEST')
        self.assertEqual(self.customer['id'],original)
        self.assertEqual(customers.list_customers(self.bid,stage='LEAD')[1],0)
        self.assertEqual(customers.list_customers(self.bid,stage='CUSTOMER')[1],1)
        self.assertEqual(customers.list_customers(self.bid)[1],1)
        self.assertEqual(jobs.list_jobs(self.bid)[1],1)
        self.assertEqual(jobs.list_jobs(self.bid)[0][0]['title'],'Carikan talent')
        self.assertEqual(customers.list_customers(self.other)[1],0)

    def test_owner_customers_unifies_inbox_contacts_without_stage_ui(self):
        self.turn('Berapa harga?')
        cid = self.customer['id']
        self.assertEqual(self.customer['stage'], 'LEAD')
        self.assertEqual(jobs.list_jobs(self.bid)[1], 0)

        inbox_conversations = customer_insights.whatsapp_conversation_rows(self.bid, cid)
        self.assertTrue(inbox_conversations)

        legacy_phone = '6282213039137'
        db.execute("INSERT INTO messages(number,mode,role,content) VALUES (?,?,?,?)",
                   (f'T{self.bid}:{legacy_phone}', 'customer', 'user', 'Halo kak'))
        db.execute("INSERT INTO customer_profiles(number,name) VALUES (?,?)",
                   (f'T{self.bid}:{legacy_phone}', 'Kilasworks'))

        page = self.client.get(f'/business/{self.bid}/customers?stage=CUSTOMER')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Irvan', page.text)
        self.assertIn('Kilasworks', page.text)
        self.assertRegex(page.text, r'\+6282213039137\s*·\s*1 percakapan')
        self.assertIn(f'/business/{self.bid}/customers/{cid}', page.text)
        legacy = next(row for row in customers.list_customers(self.bid)[0]
                      if row.get('phone') == legacy_phone)
        self.assertEqual(legacy['stage'], 'LEAD')
        self.assertEqual(customers.list_customers(self.other)[1], 0)
        for retired_ui in ('>Lead<', 'stage=LEAD', 'stage=CUSTOMER', 'lead aktif',
                           'Lead akan berpindah', 'pindah dari Lead'):
            self.assertNotIn(retired_ui, page.text)

        path = f'/business/{self.bid}/customers/{cid}'
        detail = self.client.get(path)
        self.assertEqual(detail.status_code, 200)
        self.assertIn('data-customer-insight', detail.text)
        self.assertIn('Customer Insight', detail.text)
        self.assertNotIn('data-linked-jobs', detail.text)

        self.turn('Saya tertarik', dict(follow_up='Tanyakan kebutuhan yang ingin dibahas'))
        detail = self.client.get(path)
        self.assertIn('Follow-up Customer', detail.text)
        self.assertEqual(jobs.list_jobs(self.bid)[1], 0)

        self.turn('Saya mau cari talent', dict(action='Cari talent',
            job_status='PERLU_TINDAKAN', follow_up='Tanyakan detail talent'), 'REQUEST')
        detail = self.client.get(path)
        self.assertIn('Jobs customer ini', detail.text)
        self.assertIn('Carikan talent', detail.text)
        self.assertIn('Edit Job', detail.text)
        self.assertEqual(jobs.list_jobs(self.bid)[1], 1)

    def test_tenant_profile_and_assistant_messages_cannot_become_customer_facts(self):
        hostile = dict(name='Pemilik',business_name='Foto Satu',business_type='DJ, Content Creator & Influencer',
            location='Indonesia',budget='5 juta',needs=['TENANT ONLY'],interests=['DJ'],
            fact_evidence={'business_name':'Foto Satu','business_type':'DJ, Content Creator & Influencer',
                'location':'Indonesia','budget':'Berapa harga?','needs':{'TENANT ONLY':'Berapa harga?'}})
        with patch.object(assist_reply,'relevant_knowledge',return_value={'profile':'Foto Satu, DJ, Content Creator & Influencer, Indonesia'}):
            insight = self.turn('Berapa harga?',hostile)
        for key in customer_facts.SCALARS:
            self.assertIsNone(insight[key])
        self.assertEqual(insight['needs'],[])
        self.assertNotIn('Indonesia',insight['summary'])
        value=dict(hostile,location='Indonesia',fact_evidence={'location':'Saya dari Indonesia'})
        with patch.object(ai_router,'complete',return_value=(json.dumps(dict(reply='Baik',intent='QUESTION',confidence=.99,
                evidence='',knowledge_used=[],insight=value)),'end_turn',None)):
            _, result, _ = assist_reply.generate(self.bid,'Halo',[{'role':'assistant','content':'Saya dari Indonesia'}])
        self.assertIsNone(result['location'])

    def test_verified_facts_accumulate_and_customer_corrections_replace_conflicts(self):
        text='Saya dari Tangerang, budget 5 juta'
        first=self.turn(text,dict(location='Tangerang',budget='5 juta',fact_evidence={'location':text,'budget':text}))
        self.assertEqual(first['location'],'Tangerang')
        second=self.turn('Terima kasih')
        self.assertEqual(second['location'],'Tangerang');self.assertEqual(second['budget'],'5 juta')
        corrected=self.turn('Koreksi budget 7 juta',dict(budget='7 juta',fact_evidence={'budget':'Koreksi budget 7 juta'}))
        self.assertEqual(corrected['budget'],'7 juta');self.assertEqual(corrected['location'],'Tangerang')

    def test_new_details_enrich_same_job_and_separate_request_creates_second(self):
        self.turn('Saya mau cari talent',dict(action='Cari talent',job_status='PERLU_TINDAKAN'),'REQUEST')
        first=jobs.list_jobs(self.bid)[0][0]
        self.turn('Saya cari talent perempuan',dict(action='Cari talent perempuan',job_status='PERLU_TINDAKAN',request_relation='CONTINUE'),'REQUEST')
        text='Untuk campaign skincare tanggal 20 Oktober, budget 5 juta'
        self.turn(text,dict(needs=['campaign skincare'],schedule='20 Oktober',budget='5 juta',
            fact_evidence={'needs':{'campaign skincare':text},'schedule':text,'budget':text}))
        enriched=jobs.list_jobs(self.bid)[0][0]
        self.assertEqual(enriched['id'],first['id']);self.assertEqual(jobs.list_jobs(self.bid)[1],1)
        self.assertEqual(enriched['title'],'Carikan talent perempuan')
        for detail in ('campaign skincare','20 Oktober','5 juta'):
            self.assertIn(detail,enriched['summary'])
        self.turn('Koreksi budget 7 juta',dict(budget='7 juta',fact_evidence={'budget':'Koreksi budget 7 juta'}))
        corrected=jobs.list_jobs(self.bid)[0][0]
        self.assertIn('7 juta',corrected['summary']);self.assertNotIn('5 juta',corrected['summary'])
        self.assertIn('20 Oktober',corrected['summary'])
        self.turn('Selain itu tolong jadwalkan meeting tim besok',dict(action='Jadwalkan meeting tim besok',
            job_status='PERLU_TINDAKAN',request_relation='NEW'),'REQUEST')
        self.assertEqual(jobs.list_jobs(self.bid)[1],2)
        self.assertEqual(jobs.get_job(self.bid,first['id']),corrected)
        second=next(row for row in jobs.list_jobs(self.bid)[0] if row['id']!=first['id'])
        self.assertNotIn('7 juta',second['summary'])
        self.assertNotIn('20 Oktober',second['summary'])

    def test_customer_confirmation_keeps_semantic_job_and_owner_field_overrides(self):
        first_insight = self.turn('Saya mau urus visa Amerika', dict(
            action='Saya mau urus visa Amerika', interests=['Visa Amerika'],
            fact_evidence={'interests': {'Visa Amerika': 'Saya mau urus visa Amerika'}},
            job_status='PERLU_TINDAKAN'), 'REQUEST')
        rows = jobs.list_jobs(self.bid)[0]
        self.assertEqual(jobs.list_jobs(self.bid)[1], 1)
        original = rows[0]
        self.assertEqual(original['title'], 'Proses pengurusan visa Amerika')
        self.assertNotIn('ingin melanjutkan', original['summary'].casefold())
        self.assertIn('customer meminta pengurusan visa amerika', original['summary'].casefold())
        self.assertNotIn('iya', original['title'].casefold())

        continuation = self.turn('Iya saya ingin lanjut', dict(
            action='Iya saya ingin lanjut', job_status='PERLU_TINDAKAN',
            request_relation='CONTINUE'), 'REQUEST')
        rows = jobs.list_jobs(self.bid)[0]
        self.assertEqual(jobs.list_jobs(self.bid)[1], 1)
        current = rows[0]
        self.assertEqual(current['id'], original['id'])
        self.assertEqual(current['title'], 'Proses pengurusan visa Amerika')
        self.assertEqual(continuation['action'], first_insight['action'],
                         (continuation, first_insight))
        self.assertEqual(current['owner_status'], 'NEW')
        self.assertIn('Tindakan berikutnya', self.client.get(
            f'/business/{self.bid}/customers/{self.customer["id"]}').text)

        edit_path = f'/business/{self.bid}/jobs/{current["id"]}'
        edit_page = self.client.get(edit_path)
        self.assertNotIn('owner_overrides', edit_page.text)
        operation_key = re.search(r'name="operation_key" value="([^"]+)"', edit_page.text).group(1)
        response = self.client.post(edit_path, data={
            'csrf_token': 'crm-test', 'operation_key': operation_key,
            'version': str(current['version']), 'title': 'Urus visa Amerika — Irvan',
            'summary': 'Pemilik menulis ringkasan ini.', 'status': current['owner_status'],
            'field_details': 'Ringkasan manual untuk tim Irvan.',
        })
        self.assertEqual(response.status_code, 303)
        saved = jobs.get_job(self.bid, current['id'])
        self.assertEqual(set(saved['fields']['owner_overrides'].split(',')),
                         {'details', 'summary', 'title'})

        text = 'Saya berangkat tanggal 20 bulan depan.'
        self.turn(text, dict(schedule='tanggal 20 bulan depan',
            fact_evidence={'schedule': text}, request_relation='CONTINUE'))
        refreshed = jobs.get_job(self.bid, current['id'])
        self.assertEqual(refreshed['title'], 'Urus visa Amerika — Irvan')
        self.assertEqual(refreshed['summary'], 'Pemilik menulis ringkasan ini.')
        self.assertEqual(refreshed['fields']['details'], 'Ringkasan manual untuk tim Irvan.')
        self.assertEqual(refreshed['fields']['scheduled_at'], 'tanggal 20 bulan depan')
        self.assertEqual(jobs.list_jobs(self.bid)[1], 1)
        self.assertIn('Edit Job', self.client.get(
            f'/business/{self.bid}/customers/{self.customer["id"]}').text)

    def test_customer_insight_job_rejects_generic_confirmation_as_request(self):
        self.turn('Berapa harga paketnya?')
        customer = self.customer
        value = customer_insights._default()
        value.update(action='Oke lanjut', job_status='PERLU_TINDAKAN',
                     _request_key='confirmed-old-request', _action_evidence='Oke lanjut',
                     _meta={'has_history': True, 'fresh': True})
        self.assertIsNone(customer_action_jobs._payload(value))
        self.assertEqual(jobs.list_jobs(self.bid)[1], 0)
        self.assertEqual(customer['stage'], 'LEAD')

    def test_existing_generic_insight_job_is_repaired_from_verified_request_context(self):
        self.turn('Saya mau urus visa Amerika', dict(action='Saya mau urus visa Amerika',
            interests=['Visa Amerika'], fact_evidence={'interests': {'Visa Amerika': 'Saya mau urus visa Amerika'}},
            job_status='PERLU_TINDAKAN'), 'REQUEST')
        original = jobs.list_jobs(self.bid)[0][0]
        contaminated_fields = dict(original['fields'], action='Iya ingin lanjut')
        with jobs.transaction() as tx:
            jobs._update_job(tx, self.bid, original['id'], expected_version=original['version'],
                actor_id=jobs._CUSTOMER_INSIGHT_ACTOR, operation_key='seed-legacy-generic-job',
                title='Iya ingin lanjut', summary='Iya ingin lanjut', fields=contaminated_fields)

        insight = dict(action='Oke lanjut', job_status='PERLU_TINDAKAN',
            interests=['Visa Amerika'], _request_key=original['fields']['request_key'],
            _meta={'has_history': True, 'fresh': True})
        customer_action_jobs.sync_from_insight(repo.get_business(self.bid), self.customer, insight)
        repaired = jobs.list_jobs(self.bid)[0][0]
        self.assertEqual(jobs.list_jobs(self.bid)[1], 1)
        self.assertEqual(repaired['id'], original['id'])
        self.assertEqual(repaired['title'], 'Tindak lanjuti permintaan Visa Amerika')
        self.assertNotEqual(repaired['summary'], 'Iya ingin lanjut')
        self.assertEqual(repaired['owner_status'], 'NEW')

    def test_customer_insight_does_not_update_manual_jobs_or_status(self):
        self.turn('Berapa harga paketnya?')
        customer = customers.update_customer(self.bid, self.customer['id'],
            display_name=self.customer['display_name'], stage='CUSTOMER', actor_id=self.uid)
        manual = jobs.create_job(self.bid, customer['id'], title='Pekerjaan manual pemilik',
            actor_id=self.uid, operation_key='manual-job-protected', summary='Catatan manual')
        insight = dict(action='Booking konsultasi', job_status='DIKERJAKAN',
            _action_evidence='Booking konsultasi', _payment_evidence='',
            _meta={'has_history': True, 'fresh': True})
        result = customer_action_jobs.sync_from_insight(repo.get_business(self.bid), customer, insight)
        self.assertEqual(result, manual)
        self.assertEqual(jobs.list_jobs(self.bid)[1], 1)
        self.assertEqual(jobs.get_job(self.bid, manual['id'])['title'], 'Pekerjaan manual pemilik')
        self.assertEqual(jobs.get_job(self.bid, manual['id'])['summary'], 'Catatan manual')
        self.assertEqual(jobs.get_job(self.bid, manual['id'])['status'], 'NEW')

    def test_payment_gate_and_finance_completion_are_preserved(self):
        self.turn('Saya mau booking konsultasi',dict(action='Booking konsultasi',job_status='DIKERJAKAN'),'REQUEST')
        row=jobs.list_jobs(self.bid)[0][0];self.assertEqual(row['status'],'NEW')
        self.turn('Kirim invoice saya mau bayar',dict(action='Kirim invoice',job_status='DIKERJAKAN'),'PAYMENT')
        row=jobs.list_jobs(self.bid)[0][0]
        self.assertEqual(row['status'],'IN_PROGRESS');self.assertEqual(row['title'],'Atur booking konsultasi')
        self.turn('Sudah selesai',dict(action=None,job_status='COMPLETED'))
        row=jobs.list_jobs(self.bid)[0][0];self.assertEqual(row['status'],'IN_PROGRESS')
        with self.assertRaisesRegex(jobs.JobError,'finance_confirmation_required'):
            jobs.update_job(self.bid,row['id'],expected_version=row['version'],actor_id=self.uid,
                            operation_key='owner-complete-attempt',status='COMPLETED')
        with jobs.transaction() as tx:
            complete=jobs._update_job(tx,self.bid,row['id'],expected_version=row['version'],
                actor_id=jobs._FINANCE_PAYMENT_ACTOR,operation_key='verified-finance-complete',status='COMPLETED')
        self.turn('Terima kasih ya')
        self.assertEqual(jobs.get_job(self.bid,row['id']),complete)
        self.assertEqual(jobs.list_jobs(self.bid)[1],1)
        self.turn('Saya mau booking konsultasi',dict(action='Booking konsultasi',job_status='PERLU_TINDAKAN'),'REQUEST')
        self.assertEqual(jobs.list_jobs(self.bid)[1],2)
        self.assertEqual(jobs.get_job(self.bid,row['id']),complete)
        self.assertEqual(db.query_all('SELECT * FROM finance_transactions'),[])

    def test_whatsapp_names_sync_and_owner_name_wins(self):
        self.turn('Berapa harga?',name='')
        self.assertEqual(self.customer['display_name'],self.phone)
        self.turn('Berapa harga layanan?',name='Irvan')
        self.assertEqual(self.customer['display_name'],'Irvan')
        customers.update_customer(self.bid,self.customer['id'],display_name='Irvan',phone=self.phone,
                                  notes='Minta informasi',actor_id=self.uid)
        self.turn('Terima kasih',name='Irvan WA')
        self.assertEqual(self.customer['display_name'],'Irvan WA')
        customers.update_customer(self.bid,self.customer['id'],display_name='Pak Irvan',phone=self.phone,actor_id=self.uid)
        self.turn('Terima kasih',name='Nama WA baru')
        self.assertEqual(self.customer['display_name'],'Pak Irvan')
        self.assertEqual(customers.list_customers(self.other)[1],0)

    def test_existing_demo_profile_repairs_only_bound_tenant(self):
        self.turn('Berapa harga?',channel='demo',name='')
        db.execute('INSERT INTO customer_profiles(number,name) VALUES (?,?)',(self.phone,'Irvan'))
        foreign=customers.ensure_whatsapp_lead(self.other,self.phone)
        repaired=customers.sync_verified_profile(self.bid,self.customer)
        self.assertEqual(repaired['display_name'],'Irvan')
        self.assertEqual(customers.sync_verified_profile(self.other,foreign)['display_name'],self.phone)
        page=self.client.get(f'/business/{self.bid}/customers/{self.customer["id"]}')
        self.assertIn('Irvan',page.text);self.assertIn('+1 404-883-6437',page.text)

    def test_demo_uses_same_crm_lifecycle_and_shows_customer_jobs(self):
        self.turn('Berapa harga?',channel='demo');self.assertEqual(self.customer['stage'],'LEAD')
        self.turn('Saya mau cari talent',dict(action='Cari talent',job_status='PERLU_TINDAKAN'),'REQUEST','demo')
        cid=self.customer['id']
        self.turn('Saya cari talent perempuan',dict(action='Cari talent perempuan',job_status='PERLU_TINDAKAN'),'REQUEST','demo')
        self.assertEqual(self.customer['id'],cid);self.assertEqual(jobs.list_jobs(self.bid)[1],1)
        self.assertEqual(customers.list_customers(self.bid,stage='LEAD')[1],0)
        page=self.client.get(f'/business/{self.bid}/customers/{cid}')
        self.assertEqual(page.status_code,200);self.assertIn('Jobs customer ini',page.text)
        self.assertIn('Cari talent perempuan',page.text)
        self.assertNotIn('sudah benar-benar menjadi pelanggan',page.text)

    def test_legacy_contaminated_insight_rebuilds_from_customer_only(self):
        self.turn('Saya mau cari talent',dict(action='Cari talent',job_status='PERLU_TINDAKAN'),'REQUEST')
        old_job=jobs.list_jobs(self.bid)[0][0]
        db.execute('UPDATE kw_core_customer_insights SET insight_json=? WHERE business_id=?',
            (json.dumps({'business_type':'DJ, Content Creator & Influencer','location':'Indonesia','summary':'Indonesia'}),self.bid))
        cached=customer_insights.cached(repo.get_business(self.bid),self.customer)
        self.assertIsNone(cached['location'])
        value=dict(action='Cari talent',job_status='PERLU_TINDAKAN',_action_evidence='Saya mau cari talent')
        with patch.object(customer_insights.ai_onboarding,'_call_claude',return_value=(json.dumps(value),'end_turn',None)) as model:
            response=self.client.get(f'/business/{self.bid}/customers/{self.customer["id"]}/insight')
        self.assertEqual(response.status_code,200)
        self.assertNotIn('DJ, Content Creator',model.call_args.args[1][0]['content'])
        self.assertEqual(jobs.list_jobs(self.bid)[1],1)
        self.assertEqual(jobs.list_jobs(self.bid)[0][0]['id'],old_job['id'])

    def test_lead_and_customer_followup_require_relevant_suggestion_and_never_send(self):
        self.turn('Berapa harga?')
        path=f'/business/{self.bid}/customers/{self.customer["id"]}'
        self.assertNotIn('Follow-up Customer',self.client.get(path).text)
        self.turn('Saya tertarik',dict(follow_up='Tanyakan kebutuhan yang ingin dibahas'))
        page=self.client.get(path)
        self.assertIn('Follow-up Customer',page.text)
        self.assertIn('periksa sebelum dikirim',page.text)
        self.assertNotIn('data-linked-jobs',page.text)
        self.assertEqual(jobs.list_jobs(self.bid)[1],0)
        self.turn('Saya mau booking konsultasi',dict(action='Booking konsultasi',
            job_status='PERLU_TINDAKAN',follow_up='Tanyakan jadwal konsultasi'),'REQUEST')
        page=self.client.get(path)
        self.assertEqual(self.customer['stage'],'CUSTOMER')
        self.assertIn('Follow-up Customer',page.text)
        self.assertIn('periksa sebelum dikirim',page.text)

    def test_quick_setup_preserves_knowledge_and_does_not_extend_demo(self):
        before=assist_training.context(self.bid)
        payload=dict(csrf_token='crm-test',setup_mode='quick',business_name='Foto Satu',category='Fotografi',
            short_description='Foto produk',business_phone='081234567890',online_or_offline='both',
            address='Seluruh Indonesia',operating_hours='09-17 WIB',primary_language='Bahasa Indonesia')
        response=self.client.post(f'/business/{self.bid}/wizard/basics',data=payload)
        self.assertEqual(response.status_code,303);self.assertTrue(response.location.endswith('/train'))
        self.assertTrue(assist_journey.onboarding_complete(self.bid))
        self.assertEqual(assist_training.context(self.bid)['faqs'],before['faqs'])
        self.assertEqual(assist_training.context(self.bid)['services'],before['services'])
        self.assertEqual(repo.get_business_profile(self.bid)['country'],'Indonesia')
        self.assertEqual(repo.get_business_profile(self.bid)['online_or_offline'],'both')
        self.assertIn('value="both" selected',self.client.get(f'/business/{self.bid}/wizard/basics').text)
        self.assertFalse(repo.get_onboarding_status(self.bid)['services_done'])
        trial=assist_journey._event(self.bid,assist_journey.DEMO_STEP)
        self.client.post(f'/business/{self.bid}/wizard/basics',data=payload)
        self.assertEqual(trial,assist_journey._event(self.bid,assist_journey.DEMO_STEP))
        self.assertEqual(self.client.get(response.location).status_code,200)
        self.assertEqual(db.query_all('SELECT * FROM finance_transactions'),[])
        foreign_owner=repo.create_user('foreign@test.invalid','hash')
        db.execute('UPDATE business_memberships SET user_id=? WHERE business_id=?',(foreign_owner,self.other))
        self.assertEqual(self.client.post(f'/business/{self.other}/wizard/basics',data=payload).status_code,404)

    def test_short_setup_has_only_essentials_and_validates_without_writing(self):
        page=self.client.get(f'/business/{self.bid}/wizard/basics')
        self.assertIn('Lanjut ke Latih Kilas Assist',page.text)
        self.assertNotIn('wizard-steps',page.text)
        for retired in ('services_raw','faq_raw','owner_name','trusted_owner_phone','payment_bank_name'):
            self.assertNotIn('name="'+retired+'"',page.text)
        before=repo.get_business_profile(self.bid)
        result=self.client.post(f'/business/{self.bid}/wizard/basics',data={'csrf_token':'crm-test','setup_mode':'quick'})
        self.assertEqual(result.status_code,400);self.assertEqual(repo.get_business_profile(self.bid),before)


if __name__ == '__main__':
    unittest.main()
