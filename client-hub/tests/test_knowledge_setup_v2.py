"""Knowledge setup phase 1: explicit data, deterministic completeness, scoped atomic writes."""
import json
import unittest
from unittest.mock import patch
from html.parser import HTMLParser
from werkzeug.datastructures import MultiDict
import test_targeted_production_upgrade as fixture
import knowledge_setup as knowledge
import ai_onboarding

repo, db, security, hub = fixture.repo, fixture.db, fixture.security, fixture.hub

class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        fixture.auth_fixture.reset_db()
        fixture.catalog_service.seed_catalog_if_needed()
        self.uid=repo.create_user('knowledge@test.com',security.hash_password('password123'))
        self.bid=repo.create_business(self.uid,'Knowledge Test','AI_ADMIN_BASIC')
        repo.upsert_business_profile(self.bid,dict(short_description='Bisnis lama',tone='ramah',primary_language='id',customer_salutation='Kak'))
        db.execute("UPDATE businesses SET status='ACTIVE' WHERE id=?",(self.bid,))
        repo.replace_business_services(self.bid,['Catatan lama tanpa format, Rp100.000 termasuk konsultasi'])
        repo.replace_business_faqs(self.bid,['Jam buka? | Senin sampai Jumat','Catatan FAQ lama tanpa pemisah'])
        self.client=hub.app.test_client()
        self.client.post('/login',data={'email':'knowledge@test.com','password':'password123'})
        self.url=f'/business/{self.bid}/memory'

    def state(self):
        return (repo.get_business_profile(self.bid),repo.get_business_services(self.bid),repo.get_business_faqs(self.bid))

    def form(self):
        profile,services,faqs=self.state()
        cards=knowledge.editor(self.bid,services,faqs)
        data=MultiDict({'knowledge_form':'v2','knowledge_revision':cards['revision']})
        for key in knowledge.PROFILE_FIELDS:data[key]=profile.get(key) or ''
        for kind in ('services','faqs'):
            for card in cards[kind]:
                data.add(kind+'_id',card['id'])
                for key in knowledge.SECTION_FIELDS[kind]:data.add(kind+'_'+key,card.get(key,'') or '')
        return data

    def test_legacy_readable_noop_preserves_exact_rows(self):
        before=self.state()
        page=self.client.get(self.url)
        self.assertEqual(page.status_code,200)
        self.assertIn(b'Catatan lama tanpa format',page.data)
        self.assertIn(b'Catatan FAQ lama tanpa pemisah',page.data)
        self.assertEqual(self.client.post(self.url,data=self.form()).status_code,302)
        self.assertEqual(self.state(),before)
        self.assertIsNone(knowledge.latest(self.bid))

    def test_structured_edit_retains_ids_and_archives_original(self):
        before=self.state();data=self.form()
        data['services_name']='Konsultasi';data['services_description']='Diskusi 1 jam'
        data['services_pricing']='Sesuai penawaran';data['services_inclusions']='Catatan tertulis'
        data['services_duration']='1 jam';data['services_notes']='Jadwal dikonfirmasi tim'
        data.setlist('faqs_question',['Jam buka?','Bisa datang langsung?'])
        data.setlist('faqs_answer',['Senin–Jumat 09–17','Harus membuat janji'])
        data['category']='Konsultan'
        with patch.object(ai_onboarding,'normalize_business_data',side_effect=AssertionError('NO AI')):
            response=self.client.post(self.url,data=data)
        self.assertEqual(response.status_code,302)
        profile,services,faqs=self.state()
        self.assertEqual(services[0]['id'],before[1][0]['id'])
        self.assertEqual(faqs[1]['id'],before[2][1]['id'])
        self.assertEqual(services[0]['service_name'],'Konsultasi')
        self.assertIn('Sesuai penawaran',services[0]['raw_input'])
        self.assertIsNone(services[0]['price_from'])
        self.assertEqual(faqs[1]['answer'],'Harus membuat janji')
        snapshot=json.loads(knowledge.latest(self.bid)['snapshot_json'])
        self.assertEqual(snapshot['services'],before[1]);self.assertEqual(snapshot['faqs'],before[2])
        cards=knowledge.editor(self.bid,services,faqs)
        self.assertEqual(cards['services'][0]['duration'],'1 jam')
        config=repo.get_tenant_config_row(self.bid)['config']
        self.assertEqual(config['knowledge']['faq'][1]['answer'],'Harus membuat janji')
        self.assertEqual(config['business_type'],'Konsultan')
        self.assertEqual(repo.get_business(self.bid)['status'],'ACTIVE')

    def test_add_service_and_faq_without_deleting_old_rows(self):
        before=self.state();data=self.form()
        for kind,values in [('services',dict(name='Produk baru',pricing='Rp50.000')),('faqs',dict(question='Berapa lama?',answer='Dua hari',category='Proses'))]:
            data.add(kind+'_id','')
            for key in knowledge.SECTION_FIELDS[kind]:data.add(kind+'_'+key,values.get(key,''))
        self.assertEqual(self.client.post(self.url,data=data).status_code,302)
        after=self.state()
        self.assertEqual(after[1][0],before[1][0]);self.assertEqual(after[2][:2],before[2])
        self.assertEqual(len(after[1]),2);self.assertEqual(len(after[2]),3)

    def test_editing_notes_preserves_normalized_prices_and_other_config(self):
        db.execute('UPDATE business_services SET service_name=?, price_from=?, price_to=?, currency=?, needs_review=? WHERE business_id=?',
                   ('Konsultasi',100000,200000,'IDR',False,self.bid))
        config = knowledge.provisioning.build_tenant_config(self.bid)
        config['custom_existing_setting'] = {'keep': True}
        repo.save_tenant_config(self.bid, config)
        data=self.form();data['services_notes']='Jadwal sesuai kesepakatan'
        self.assertEqual(self.client.post(self.url,data=data).status_code,302)
        row=repo.get_business_services(self.bid)[0]
        self.assertEqual((row['price_from'],row['price_to'],row['currency']),(100000,200000,'IDR'))
        saved=repo.get_tenant_config_row(self.bid)['config']
        self.assertEqual(saved['custom_existing_setting'],{'keep':True})
        self.assertEqual(saved['knowledge']['services'][0]['price_from'],100000)

    def test_readiness_score_and_missing_prices(self):
        profile,services,faqs=self.state();cards=knowledge.editor(self.bid,services,faqs)
        result=knowledge.readiness(profile,services,faqs,{},cards)
        self.assertEqual(result['score'],83)
        self.assertEqual(result['missing'],['Jam operasional belum diisi.'])
        profile['operating_hours']='09–17'
        self.assertEqual(knowledge.readiness(profile,services,faqs,{},cards)['score'],100)
        services[0]['raw_input']='Harga belum diketahui'
        result=knowledge.readiness(profile,services,faqs,{},cards)
        self.assertIn('1 layanan belum memiliki informasi harga atau ketentuan penawaran.',result['missing'])

    def test_optional_requirements_follow_features_and_relevance(self):
        profile,services,faqs=self.state();cards=knowledge.editor(self.bid,services,faqs)
        basic=knowledge.readiness(profile,services,faqs,{},cards)
        self.assertNotIn('booking',[c['key'] for c in basic['checks']])
        self.assertNotIn('payment',[c['key'] for c in basic['checks']])
        self.assertNotIn('address',[c['key'] for c in basic['checks']])
        profile.update(appointment_enabled=True,online_or_offline='offline')
        pro=knowledge.readiness(profile,services,faqs,{'appointment':True,'payment_conversation':True},cards)
        self.assertTrue({'booking','payment','address'}.issubset({c['key'] for c in pro['checks']}))
        profile['appointment_enabled']=False
        self.assertNotIn('booking',[c['key'] for c in knowledge.readiness(profile,services,faqs,{'appointment':True},cards)['checks']])

    def test_tenant_authorization_and_row_injection(self):
        other=repo.create_user('other-knowledge@test.com',security.hash_password('password123'))
        bid=repo.create_business(other,'Other','AI_ADMIN_BASIC')
        repo.replace_business_services(bid,['Private service'])
        row=repo.get_business_services(bid)[0]
        self.assertEqual(self.client.get(f'/business/{bid}/memory').status_code,404)
        self.assertEqual(self.client.post(f'/business/{bid}/memory',data=self.form()).status_code,404)
        data=self.form();data['services_id']=str(row['id'])
        self.assertEqual(self.client.post(self.url,data=data).status_code,400)
        self.assertEqual(repo.get_business_services(bid)[0]['raw_input'],'Private service')

    def test_csrf_and_login_required(self):
        with patch.dict(hub.app.config,{'CLIENT_HUB_FORCE_CSRF_IN_TESTS':True}):
            self.assertEqual(self.client.post(self.url,data=self.form()).status_code,400)
        self.assertEqual(hub.app.test_client().get(self.url).status_code,302)

    def test_package_security_fields_ignored(self):
        data=self.form();data.update({'category':'Jasa','package':'AI_ADMIN_PRO','appointment_enabled':'on','payment_instructions':'injected','trusted_owner_phone':'injected','features_enabled':'all'})
        self.assertEqual(self.client.post(self.url,data=data).status_code,302)
        profile=repo.get_business_profile(self.bid)
        self.assertNotEqual(profile.get('payment_instructions'),'injected')
        self.assertEqual(repo.get_business(self.bid)['package'],'AI_ADMIN_BASIC')
        self.assertFalse((repo.get_tenant_features(self.bid) or {}).get('owner_commands'))
        db.execute("UPDATE businesses SET package='NONE' WHERE id=?",(self.bid,))
        self.assertEqual(self.client.get(self.url).status_code,403)

    def test_mobile_structured_template_and_no_ai_button(self):
        page=self.client.get(self.url).data.decode()
        for text in ['Ajari Kilas Brain tentang bisnismu','data-knowledge-section="services"','name="faqs_question"','name="faqs_answer"','grid-template-columns:1fr','minmax(0,1fr)']:
            self.assertIn(text,page)
        self.assertNotIn('name="faq_raw"',page);self.assertNotIn('question | answer',page)
        class Controls(HTMLParser):
            def handle_starttag(parser, tag, attrs):
                self.assertNotEqual(tag, 'table')
                if tag in ('button', 'a', 'form', 'input'):
                    self.assertNotIn('ai-writing-help', str(attrs))
                    self.assertNotIn('ai-faq-suggest', str(attrs))
        Controls().feed(page)

    def test_stale_revision_and_omitted_rows_rejected(self):
        stale=self.form();data=self.form();data['category']='Jasa'
        self.client.post(self.url,data=data)
        stale['tone']='baru'
        self.assertEqual(self.client.post(self.url,data=stale).status_code,400)
        data=self.form();data.setlist('faqs_id',[])
        for key in knowledge.SECTION_FIELDS['faqs']:data.setlist('faqs_'+key,[])
        self.assertEqual(self.client.post(self.url,data=data).status_code,400)
        self.assertEqual(len(repo.get_business_faqs(self.bid)),2)

    def test_save_rolls_back_on_failure(self):
        before=self.state();data=self.form();data['category']='Jasa'
        original_dumps = json.dumps
        def fail_snapshot(value, *args, **kwargs):
            if isinstance(value, dict) and set(value) == {'profile','services','faqs','config'}:
                raise RuntimeError('simulated')
            return original_dumps(value, *args, **kwargs)
        with patch.object(knowledge.json,'dumps',side_effect=fail_snapshot):
            self.assertEqual(self.client.post(self.url,data=data).status_code,302)
        self.assertEqual(self.state(),before);self.assertIsNone(knowledge.latest(self.bid))

    def test_migration_idempotent_preserves_history(self):
        data=self.form();data['category']='Jasa';self.client.post(self.url,data=data)
        before=self.state();revision=knowledge.latest(self.bid)
        db.init_schema()
        self.assertEqual(self.state(),before);self.assertEqual(knowledge.latest(self.bid),revision)

if __name__=='__main__':unittest.main()
