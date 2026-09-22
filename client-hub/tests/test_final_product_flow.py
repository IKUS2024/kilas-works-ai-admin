"""Final release journeys, offline. Ordinary member, disposable SQLite; no admin entitlement bypass."""
import base64
import io
import os
import uuid
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
import test_finance_phase6b as prior
import db,repo,security
import finance_service as f
import finance_entitlements as e
import finance_subscription as billing
import finance_analyst as analyst
import finance_operator as operator
import finance_receipts as receipts
import finance_bank_extract as extract
import finance_invoice_view as sharing
import product_flow

app=prior.app


class FinalFlowTests(unittest.TestCase):
    def setUp(self):
        prior.BankTests.setUp(self)
        __import__("catalog_service").seed_catalog_if_needed()
        self.environment=patch.dict(os.environ,{'KILAS_FINANCE_ACCESS_MODE':'self_service','KILAS_FINANCE_BETA':'off',
            'KILAS_FINANCE_ANALYST_ENABLED':'on','KILAS_FINANCE_OPERATOR_ENABLED':'on',
            'KILAS_FINANCE_ANALYST_BUSINESS_IDS':'','KILAS_FINANCE_OPERATOR_BUSINESS_IDS':'',
            'KILAS_FINANCE_PAYMENT_BANK_NAME':'TEST BANK','KILAS_FINANCE_PAYMENT_BANK_ACCOUNT':'TEST ACCOUNT',
            'KILAS_FINANCE_PAYMENT_BANK_HOLDER':'TEST HOLDER'})
        self.environment.start();self.addCleanup(self.environment.stop)
        self.clock=patch.object(e,'now',return_value=datetime(2026,9,17,10,tzinfo=timezone.utc));self.time=self.clock.start();self.addCleanup(self.clock.stop)
        self.admin=repo.create_user('payment-admin@example.test','unused',role='KILAS_ADMIN')
        self.setup_url=f'/business/{self.b}/finance-subscription'
    race=prior.BankTests.race
    tx=prior.BankTests.tx
    ledger=prior.BankTests.ledger
    snapshot=prior.BankTests.snapshot
    def trial(self):return e.start_trial(self.b,self.uid)
    def bill(self):return billing.create_bill(self.b,self.uid,uuid.uuid4().hex)
    def proof(self,bill):return billing.upload_proof(self.b,bill,self.uid,'proof.png',self.raw)
    def verified(self):
        bill=self.bill();self.proof(bill);billing.review(self.b,bill,self.admin,True);return bill
    def test_public_three_products(self):
        response=app.test_client().get('/products');self.assertEqual(response.status_code,200)
        for text in ('499.000','149.000','99.000','Harga promo pengguna awal','7 hari','Layanan Kreatif','Tanpa trial'):self.assertIn(text,response.text)
    def test_public_catalog_has_real_keys(self):
        response=app.test_client().get('/products');self.assertIn('value="content_basic"',response.text)
    def test_get_and_login_do_not_activate(self):
        before=self.snapshot();self.client.get(self.setup_url);self.client.get('/dashboard');self.assertEqual(before,self.snapshot())
    def test_dashboard_regular_customer(self):self.assertEqual(self.client.get('/dashboard').status_code,200)
    def test_fresh_account_dashboard_only_asks_for_business(self):
        email='fresh-onboarding@example.test';password='password123'
        repo.create_user(email,security.hash_password(password),role='CLIENT_OWNER',full_name='Fresh User')
        client=app.test_client()
        login=client.post('/login',data={'email':email,'password':password})
        self.assertEqual(login.status_code,302)
        body=client.get('/dashboard').get_data(as_text=True)
        self.assertIn('Tambah Bisnis',body)
        self.assertIn('＋ Tambah Bisnis',body)
        self.assertNotIn('Bisnis aktif',body)
        self.assertNotIn('Belum ada bisnis. Pilih produk untuk memulai.',body)
        self.assertNotIn('Pesanan Layanan',body)
    def test_not_activated_read_only(self):
        self.assertFalse(e.state(self.b)['active']);self.assertEqual(self.client.get(self.url).status_code,200)
        with self.assertRaises(f.FinanceError):self.tx()
    def test_finance_workspace_entry_skips_chooser_keeps_legacy_data_in_business_and_personal_separate(self):
        import finance_branches as branches
        self.trial()
        business_branch=branches.list_branches(
            self.b,self.uid,workspace_type='BUSINESS')[0]
        with branches.scope(self.b,business_branch['id'],self.uid):
            legacy=self.tx()
        mapping=db.query_one(
            'SELECT workspace_type,owner_user_id FROM finance_branch_workspaces '
            'WHERE business_id=? AND branch_id=?',
            (self.b,business_branch['id']))
        self.assertEqual(mapping['workspace_type'],'BUSINESS')
        self.assertIsNone(mapping['owner_user_id'])

        entry=self.client.get(f'/business/{self.b}/finance/workspaces')
        self.assertEqual(entry.status_code,303)
        self.assertIn(f'/business/{self.b}/finance',entry.location)
        self.assertIn(f'branch_id={business_branch["id"]}',entry.location)

        entered=self.client.post(
            f'/business/{self.b}/finance/workspaces/PERSONAL')
        self.assertEqual(entered.status_code,303)
        personal=branches.list_branches(
            self.b,self.uid,workspace_type='PERSONAL')
        self.assertEqual(len(personal),1)
        self.assertEqual(personal[0]['name'],'Pribadi')
        self.assertIn(f'branch_id={personal[0]["id"]}',entered.location)

        with branches.scope(self.b,personal[0]['id'],self.uid):
            self.assertEqual(f.list_transactions(self.b,actor_user_id=self.uid),[])
            personal_income={row['name'] for row in f.list_categories(
                self.b,'INCOME',actor_user_id=self.uid)}
            personal_expense={row['name'] for row in f.list_categories(
                self.b,'EXPENSE',actor_user_id=self.uid)}
            self.assertIn('Gaji',personal_income)
            self.assertIn('Freelance / Side Job',personal_income)
            self.assertIn('Kesehatan',personal_expense)
            self.assertIn('Belanja Pribadi',personal_expense)
            self.assertIn('Cicilan / Utang',personal_expense)
            self.assertNotIn('Penjualan / Jasa',personal_income)
            custom=f.create_category(
                self.b,'EXPENSE','Hobi Pribadi',actor_user_id=self.uid)
            self.assertIn('Hobi Pribadi',{row['name'] for row in f.list_categories(
                self.b,'EXPENSE',actor_user_id=self.uid)})
            account=f.list_accounts(self.b,actor_user_id=self.uid)[0]
            category=next(row for row in f.list_categories(
                self.b,'EXPENSE',actor_user_id=self.uid)
                if row['name']=='Makanan & Belanja Harian')
            personal_tx=f.create_transaction(
                self.b,'EXPENSE',12345,account['id'],category['id'],
                '2026-09-17',actor_user_id=self.uid)

        with branches.scope(self.b,business_branch['id'],self.uid):
            f.ensure_finance_defaults(self.b,actor_user_id=self.uid)
            business_ids={row['id'] for row in f.list_transactions(
                self.b,actor_user_id=self.uid)}
            self.assertIn(legacy,business_ids)
            self.assertNotIn(personal_tx,business_ids)
            business_categories={row['name'] for row in f.list_categories(
                self.b,'EXPENSE',actor_user_id=self.uid)}
            for name in (
                'Produksi / HPP','Gaji & Tenaga Kerja','Marketing & Promosi',
                'Software & Langganan','Transportasi & Pengiriman',
                'Bank & Pembayaran','Pajak & Asuransi','Makan & Operasional Tim'):
                self.assertIn(name,business_categories)
            self.assertNotIn('Hobi Pribadi',business_categories)
            self.assertNotIn('Belanja Pribadi',business_categories)

            marketing=next(row for row in f.list_categories(
                self.b,'EXPENSE',actor_user_id=self.uid)
                if row['name']=='Marketing & Promosi')
            marketing_children={row['name'] for row in f.list_category_children(
                self.b,marketing['id'],actor_user_id=self.uid)}
            self.assertEqual(
                marketing_children,
                {'Meta Ads','Google Ads','TikTok Ads','Influencer / KOL',
                 'Produksi Konten','Promo / Diskon'})

            # Default categories remain fully user-manageable. Re-opening Finance
            # must not recreate a renamed or deleted default.
            f.update_category_workspace_setting(
                self.b,marketing['id'],name='Promosi Bisnis',
                actor_user_id=self.uid)
            bank=next(row for row in f.list_categories(
                self.b,'EXPENSE',actor_user_id=self.uid)
                if row['name']=='Bank & Pembayaran')
            f.update_category_workspace_setting(
                self.b,bank['id'],deactivate=True,actor_user_id=self.uid)
            f.ensure_finance_defaults(self.b,actor_user_id=self.uid)
            after={row['name'] for row in f.list_categories(
                self.b,'EXPENSE',actor_user_id=self.uid)}
            self.assertIn('Promosi Bisnis',after)
            self.assertNotIn('Marketing & Promosi',after)
            self.assertNotIn('Bank & Pembayaran',after)

        personal_page=self.client.get(
            f'/business/{self.b}/finance?branch_id={personal[0]["id"]}')
        self.assertEqual(personal_page.status_code,200)
        self.assertIn('KILAS FINANCE · PRIBADI',personal_page.text)
        self.assertIn('data terpisah dari Bisnis',personal_page.text)
        self.assertNotIn('Ganti ruang / cabang',personal_page.text)
        self.assertIn('AI Finance',personal_page.text)
        self.assertIn('Buat Invoice',personal_page.text)
        self.assertIn('>Invoice<',personal_page.text)

        # Personal and Business share the same paid/trial entitlement and feature
        # set, while the branch-scoped ledger remains isolated.
        for path in ('assistant','analyst','invoices/new'):
            allowed=self.client.get(
                f'/business/{self.b}/finance/{path}?branch_id={personal[0]["id"]}')
            self.assertEqual(allowed.status_code,200)

    def test_returning_active_finance_customer_skips_setup_and_chooser(self):
        self.trial()
        with self.client.session_transaction() as session:
            session['product_intent']='finance'
        direct=self.client.get('/products/continue')
        self.assertEqual(direct.status_code,303)
        self.assertIn(f'/business/{self.b}/finance/workspaces',direct.location)
        opened=self.client.get(direct.location)
        self.assertEqual(opened.status_code,303)
        self.assertIn(f'/business/{self.b}/finance',opened.location)
        self.assertNotIn('/finance/workspaces',opened.location)

    def test_first_finance_onboarding_only_asks_owner_name_and_locked_email(self):
        email='finance-first@example.test';password='password123'
        repo.create_user(email,security.hash_password(password),role='CLIENT_OWNER',full_name='Finance First')
        client=app.test_client()
        self.assertEqual(client.post('/login',data={'email':email,'password':password}).status_code,302)
        self.assertEqual(client.post('/products/select',data={'product':'finance'}).status_code,303)
        page=client.get('/products/continue')
        self.assertEqual(page.status_code,200)
        self.assertIn('Mulai Kilas Finance',page.text)
        self.assertIn('name="owner_name"',page.text)
        self.assertIn(email,page.text)
        self.assertIn('readonly',page.text)
        self.assertNotIn('Pilih ruang Finance',page.text)
        import re
        match=re.search(r'name="setup_identity" value="([a-f0-9]{32})"',page.text)
        self.assertIsNotNone(match)
        started=client.post('/products/continue',data={
            'create':'yes','setup_identity':match.group(1),'owner_name':'Nama Finance Baru'
        })
        self.assertEqual(started.status_code,303)
        opened=client.get(started.location)
        self.assertEqual(opened.status_code,303)
        self.assertIn('/finance',opened.location)
        self.assertNotIn('/finance/workspaces',opened.location)
        saved=repo.get_user_by_email(email)
        self.assertEqual(saved['full_name'],'Nama Finance Baru')

    def test_personal_invoice_defaults_use_owner_identity_and_need_no_business_address(self):
        import finance_branches as branches
        import finance_invoice_editor as editor
        self.trial()
        personal_id=branches.ensure_personal(self.b,self.uid)
        with branches.scope(self.b,personal_id,self.uid):
            defaults=editor.defaults(self.b,self.uid)
            owner=repo.get_user_by_id(self.uid)
            self.assertEqual(defaults['sender']['name'],owner['full_name'] or owner['email'].split('@')[0])
            self.assertEqual(defaults['sender']['email'],owner['email'])
            self.assertEqual(defaults['sender']['address'],'')
            self.assertEqual(defaults['sender']['phone'],'')
            customer=f.create_customer(self.b,'Personal Client',actor_user_id=self.uid)
            invoice=editor.create(
                self.b,customer,
                dict(sender=defaults['sender'],recipient={'name':'Personal Client'},payment=defaults['payment'],reference=''),
                actor_user_id=self.uid,submission_key=uuid.uuid4().hex,
                issue_date='2026-09-17',due_date='2026-09-17',currency='IDR',
                notes='',items=[dict(description='Jasa pribadi',quantity=1,unit_price_minor=100000)])
            self.assertIsNotNone(invoice)
            self.assertEqual(f.get_finance_invoice(self.b,invoice,self.uid)['branch_id'],personal_id)

    def test_account_pribadi_profile_photos_and_invoice_defaults(self):
        import finance_branches as branches
        import finance_invoice_editor as editor
        self.trial()

        page=self.client.get('/account')
        self.assertEqual(page.status_code,200)
        self.assertIn('data-account-tab="personal"',page.text)
        self.assertIn('>Pribadi</button>',page.text)
        self.assertIn('data-profile-edit',page.text)
        self.assertIn('Edit profil Pribadi',page.text)
        self.assertIn('Data invoice Pribadi',page.text)
        self.assertNotIn('class="profile-photo-row"',page.text)
        self.assertIn('Ganti Foto Bisnis',page.text)

        identity=self.client.post('/account',data={
            'action':'profile','full_name':'Irvan Personal',
        })
        self.assertEqual(identity.status_code,303)
        self.assertTrue(identity.location.endswith('#personal'))

        saved=self.client.post('/account',data={
            'action':'personal_profile',
            'full_name':'Irvan Personal Edited',
            'phone':'08123456789',
            'address':'Alamat Pribadi 1',
            'tax_id':'NPWP-P',
            'website':'https://example.test',
            'payment_method':'Transfer Bank',
            'payment_bank_name':'BCA',
            'payment_account_number':'123456',
            'payment_account_name':'Irvan Personal',
            'payment_instructions':'Bayar sesuai invoice',
        })
        self.assertEqual(saved.status_code,303)
        self.assertTrue(saved.location.endswith('#personal'))

        self.assertEqual(repo.get_user_by_id(self.uid)['full_name'],'Irvan Personal Edited')

        personal_id=branches.ensure_personal(self.b,self.uid)
        with branches.scope(self.b,personal_id,self.uid):
            defaults=editor.defaults(self.b,self.uid)
        self.assertEqual(defaults['sender']['name'],'Irvan Personal Edited')
        self.assertEqual(defaults['sender']['email'],repo.get_user_by_id(self.uid)['email'])
        self.assertEqual(defaults['sender']['phone'],'08123456789')
        self.assertEqual(defaults['sender']['address'],'Alamat Pribadi 1')
        self.assertEqual(defaults['payment']['bank'],'BCA')
        self.assertEqual(defaults['payment']['account_number'],'123456')

        png=base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z0aAAAAAASUVORK5CYII=')
        photo=self.client.post('/account',data={
            'action':'personal_photo',
            'photo':(io.BytesIO(png),'profile.png'),
        },content_type='multipart/form-data')
        self.assertEqual(photo.status_code,303)
        personal_photo=self.client.get('/account/photo')
        self.assertEqual(personal_photo.status_code,200)
        self.assertEqual(personal_photo.mimetype,'image/png')

        business_photo=self.client.post('/account',data={
            'action':'business_photo','business_id':str(self.b),
            'photo':(io.BytesIO(png),'business.png'),
        },content_type='multipart/form-data')
        self.assertEqual(business_photo.status_code,303)
        served=self.client.get(f'/account/business/{self.b}/photo')
        self.assertEqual(served.status_code,200)
        self.assertEqual(served.mimetype,'image/png')

    def test_trial_exact_seven_days(self):
        self.trial();self.assertEqual(e.parse(e.state(self.b)['until'])-self.time.return_value,timedelta(days=7))
    def test_trial_expiry_exact_boundary(self):
        self.trial();self.time.return_value+=timedelta(days=7);self.assertEqual(e.state(self.b)['status'],'EXPIRED')
        with self.assertRaises(f.FinanceError):self.tx()
    def test_one_instant_before_expiry(self):
        self.trial();self.time.return_value+=timedelta(days=7,microseconds=-1);self.assertTrue(e.state(self.b)['active'])
    def test_timezone_wib(self):self.assertIn('17:00 WIB',self.trial()['until_local'])
    def test_trial_repeat_immutable(self):
        first=self.trial();self.time.return_value+=timedelta(days=2);self.assertEqual(first,self.trial())
    def test_expired_trial_cannot_restart(self):
        self.trial();self.time.return_value+=timedelta(days=8);self.assertEqual(self.trial()['status'],'EXPIRED')
    def test_rename_does_not_reset_trial(self):
        first=self.trial();db.execute('UPDATE businesses SET business_name=? WHERE id=?',('New name',self.b));self.assertEqual(first,self.trial())
    def test_trial_concurrent(self):
        result=self.race([self.trial,self.trial]);self.assertEqual(result[0],result[1]);self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_entitlements')['n'],1)
    def test_trial_requires_explicit_terms(self):
        self.assertEqual(self.client.post(self.setup_url,data={'action':'trial'}).status_code,400);self.assertFalse(e.state(self.b)['active'])
    def test_trial_post_no_ledger(self):
        self.assertEqual(self.client.post(self.setup_url,data={'action':'trial','terms':'yes'}).status_code,303);self.assertFalse(self.ledger())
    def test_trial_rollback_audit_failure(self):
        with patch.object(repo,'write_audit',side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):self.trial()
        self.assertFalse(e.state(self.b)['active'])
    def test_brain_independent(self):
        db.execute("UPDATE businesses SET status='SUSPENDED' WHERE id=?",(self.b,));self.trial();self.tx()
        self.assertEqual(repo.get_business(self.b)['status'],'SUSPENDED');self.assertIsNone(db.query_one('SELECT id FROM subscriptions WHERE business_id=?',(self.b,)))
    def test_member_trial_all_capabilities_without_allowlist(self):
        self.trial();self.assertTrue(analyst.enabled(self.b));self.assertTrue(operator.enabled(self.b));self.tx();self.assertEqual(len(self.ledger()),1)
    def test_capability_explicitly_disabled(self):
        self.trial()
        with patch.dict(os.environ,KILAS_FINANCE_ANALYST_ENABLED='off'):self.assertFalse(analyst.enabled(self.b))
    def test_emergency_disable_precedence(self):
        self.trial()
        with patch.dict(os.environ,KILAS_FINANCE_EMERGENCY_DISABLE='on'):
            self.assertFalse(analyst.enabled(self.b))
            with self.assertRaises(f.FinanceError):self.tx()
    def test_internal_beta_remains_allowlisted(self):
        with patch.dict(os.environ,KILAS_FINANCE_ACCESS_MODE='internal_beta'):
            self.assertFalse(analyst.enabled(self.b));self.assertEqual(self.client.get(self.url).status_code,404)
    def test_expired_direct_receipt_no_provider(self):
        with app.app_context():
            with self.assertRaises(f.FinanceError):receipts.analyze(self.b,self.uid,'receipt.png',self.raw)
        self.http.assert_not_called()
    def test_expired_direct_bank_no_provider(self):
        source=extract.validate_sources([('statement.csv',self.csv)])
        with self.assertRaises(f.FinanceError):extract.extract(source,self.uid,self.b)
        self.http.assert_not_called()
    def test_expired_direct_operator_no_provider(self):
        with self.assertRaises(f.FinanceError):operator.prepare(self.b,self.uid,{})
        self.http.assert_not_called()
    def test_direct_analyst_requires_context_owner(self):
        self.assertEqual(analyst.generate('q',{})[1],'access_unavailable');self.http.assert_not_called()
    def test_expired_route_ai_no_quota(self):
        response=self.client.post(self.url+'/assistant/route',json={'text':'catat bensin','mode':'auto','files':[]})
        self.assertEqual(response.status_code,403);self.http.assert_not_called()
    def test_expired_new_share_denied(self):
        with self.assertRaises(f.FinanceError):sharing.create_token(self.b,1,self.uid)
    def test_expired_historical_share_resolves(self):
        with app.app_context():token=sharing.signer().dumps({'purpose':'finance_invoice_view','business_id':self.b,'invoice_id':1})
        with app.app_context():self.assertEqual(sharing.resolve_token(token),(self.b,1))
    def test_server_price_and_pending_no_access(self):
        ident=self.bill();row=billing.bill(self.b,ident,self.uid);self.assertEqual(row['amount_minor'],99000);self.assertFalse(e.state(self.b)['active'])
    def test_legacy_regular_price_bill_still_verifies_during_promo(self):
        ident=self.bill();db.execute('UPDATE finance_subscription_bills SET amount_minor=? WHERE business_id=? AND id=?',(149000,self.b,ident))
        self.proof(ident);billing.review(self.b,ident,self.admin,True);self.assertEqual(e.state(self.b)['status'],'PAID_ACTIVE')
    def test_bill_repeat_same_pending(self):self.assertEqual(self.bill(),self.bill())
    def test_bill_concurrent(self):
        result=self.race([self.bill,self.bill]);self.assertEqual(result[0],result[1])
    def test_proof_does_not_activate(self):
        ident=self.bill();self.assertEqual(self.proof(ident)['status'],'REVIEW');self.assertFalse(e.state(self.b)['active']);self.http.assert_not_called()
    def test_proof_reject_spoof(self):
        with self.assertRaises(__import__('file_utils').UploadRejected):billing.upload_proof(self.b,self.bill(),self.uid,'fake.png',b'not an image')
    def test_only_admin_verifies(self):
        ident=self.bill();self.proof(ident)
        with self.assertRaises(f.FinanceError):billing.review(self.b,ident,self.uid,True)
    def test_verified_finance_only(self):
        self.verified();self.assertEqual(e.state(self.b)['status'],'PAID_ACTIVE');self.assertFalse(self.ledger());self.assertIsNone(db.query_one('SELECT id FROM subscriptions WHERE business_id=?',(self.b,)))
    def test_verify_replay_once(self):
        ident=self.verified();first=e.state(self.b);self.time.return_value+=timedelta(days=1);billing.review(self.b,ident,self.admin,True);self.assertEqual(first,e.state(self.b))
    def test_concurrent_verification_once(self):
        ident=self.bill();self.proof(ident);fn=lambda:billing.review(self.b,ident,self.admin,True)
        result=self.race([fn,fn]);self.assertEqual(result[0],result[1]);self.assertEqual(e.parse(e.state(self.b)['until'])-self.time.return_value,timedelta(days=30))
    def test_verify_reject_race_one_wins(self):
        ident=self.bill();self.proof(ident)
        result=self.race([lambda:billing.review(self.b,ident,self.admin,True),lambda:billing.review(self.b,ident,self.admin,False)])
        self.assertEqual(sorted(x[0] for x in result),['conflict','ok'])
    def test_early_renewal_from_paid_end(self):
        self.verified();first=e.parse(e.state(self.b)['until']);self.time.return_value+=timedelta(days=3)
        ident=self.bill();billing.upload_proof(self.b,ident,self.uid,'next.jpg',prior.image_bytes('JPEG'));billing.review(self.b,ident,self.admin,True)
        self.assertEqual(e.parse(e.state(self.b)['until']),first+timedelta(days=30))
    def test_rejected_proof_no_access(self):
        ident=self.bill();self.proof(ident);billing.review(self.b,ident,self.admin,False);self.assertFalse(e.state(self.b)['active'])
    def test_trial_blocks_new_bill_and_hides_existing_bill(self):
        ident=self.bill();self.trial();first=e.state(self.b)
        with self.assertRaises(f.FinanceError):self.bill()
        with self.assertRaises(f.FinanceError):self.proof(ident)
        page=self.client.get(self.setup_url);self.assertNotIn('Langganan Finance',page.text);self.assertNotIn(f'Tagihan #{ident}',page.text)
        self.assertEqual(self.client.get(f'/business/{self.b}/finance-bills/{ident}').status_code,303);self.assertEqual(first,e.state(self.b))
        self.time.return_value+=timedelta(days=7);page=self.client.get(self.setup_url);self.assertIn('Langganan Finance',page.text);self.assertIn(f'Tagihan #{ident}',page.text);self.assertIn('99.000',page.text)
    def test_approve_rollback(self):
        ident=self.bill();self.proof(ident)
        with patch.object(repo,'write_audit',side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError):billing.review(self.b,ident,self.admin,True)
        self.assertEqual(billing.bill(self.b,ident,self.uid)['status'],'REVIEW');self.assertFalse(e.state(self.b)['active'])
    def test_payment_details_required(self):
        with patch.dict(os.environ,KILAS_FINANCE_PAYMENT_BANK_ACCOUNT=''):
            with self.assertRaises(f.FinanceError):self.bill()
    def test_cross_tenant_bill_denied(self):
        ident=self.bill()
        with self.assertRaises(f.FinanceError):billing.bill(self.b,ident,self.other_uid)
        with self.assertRaises(f.FinanceError):billing.bill(self.other,ident,self.other_uid)
    def test_cross_tenant_trial_denied(self):
        with self.assertRaises(f.FinanceError):e.start_trial(self.other,self.uid)
    def test_all_product_pages_no_store(self):
        ident=self.bill()
        for url in ('/products','/products/continue',self.setup_url,f'/business/{self.b}/finance-bills/{ident}','/account/bills'):
            self.assertIn('no-store',self.client.get(url).headers.get('Cache-Control',''))
    def test_product_choice_continuation_only(self):
        self.client.post('/products/select',data={'product':'finance'})
        with self.client.session_transaction() as session:self.assertEqual(session['product_intent'],'finance')
        self.assertFalse(e.state(self.b)['active'])
    def test_invalid_redirect_intents(self):
        for key in ('https://evil.test','//evil.test','%2f%2fevil.test','finance?business_id=9','AI_ADMIN_PRO'):
            self.assertEqual(self.client.post('/products/select',data={'product':key}).status_code,400)
    def test_login_rotation_preserves_only_allowlisted_intent(self):
        with app.test_request_context():
            from flask import session
            session.update(product_intent='finance',_csrf_token='old',unsafe='removed')
            security.login_user(repo.get_user_by_id(self.uid));self.assertEqual(session['product_intent'],'finance');self.assertNotIn('_csrf_token',session);self.assertNotIn('unsafe',session)
    def test_create_business_idempotent(self):
        identity=uuid.uuid4().hex
        self.assertEqual(product_flow.create_business(self.uid,'New',identity),product_flow.create_business(self.uid,'New',identity))
    def test_create_business_concurrent(self):
        identity=uuid.uuid4().hex;fn=lambda:product_flow.create_business(self.uid,'New',identity)
        result=self.race([fn,fn]);self.assertEqual(result[0],result[1])
    def test_business_name_not_identity(self):
        self.assertNotEqual(product_flow.create_business(self.uid,'Same',uuid.uuid4().hex),product_flow.create_business(self.uid,'Same',uuid.uuid4().hex))
    def test_finance_setup_no_ledger_and_replay(self):
        biz=repo.create_business(self.uid,'Fresh',package='NONE');a=e.setup(biz,self.uid,'Bank','BANK',50000)
        self.assertEqual(e.setup(biz,self.uid,'Another','CASH',999),a);self.assertFalse(f.list_transactions(biz));self.assertEqual(f.list_accounts(biz)[0]['opening_balance_minor'],50000)
    def test_reuse_existing_business(self):
        self.client.post('/products/select',data={'product':'finance'});before=len(repo.list_businesses_for_user(self.uid))
        response=self.client.post('/products/continue',data={'business_id':self.b})
        self.assertIn(f'/business/{self.b}/finance',response.location)
        self.assertEqual(e.state(self.b)['status'],'TRIAL_ACTIVE')
        self.assertEqual(before,len(repo.list_businesses_for_user(self.uid)))

    def test_dashboard_focuses_one_owned_product_lane_at_a_time(self):
        finance=self.client.get('/dashboard')
        self.assertEqual(finance.status_code,200)
        self.assertIn('class="product-switcher"',finance.text)
        self.assertIn('<h2>Kilas Finance</h2>',finance.text)
        self.assertNotIn('<h2>AI Admin</h2>',finance.text)

        brain=self.client.get('/dashboard?product=brain')
        self.assertEqual(brain.status_code,200)
        self.assertIn('<h2>AI Admin</h2>',brain.text)
        self.assertNotIn('<h2>Kilas Finance</h2>',brain.text)

    def test_finance_only_customer_never_sees_ai_admin_lane_on_dashboard(self):
        email='finance-only-dashboard@example.test';password='password123'
        uid=repo.create_user(email,security.hash_password(password),role='CLIENT_OWNER',full_name='Finance Only')
        biz=repo.create_business(uid,'Finance Only Biz',package='NONE')
        f.ensure_finance_defaults(biz,actor_user_id=uid)
        client=app.test_client()
        self.assertEqual(client.post('/login',data={'email':email,'password':password}).status_code,302)
        page=client.get('/dashboard')
        self.assertEqual(page.status_code,200)
        self.assertIn('<h2>Kilas Finance</h2>',page.text)
        self.assertNotIn('<h2>AI Admin</h2>',page.text)
        self.assertNotIn('class="product-switcher"',page.text)

    def test_dashboard_trial_is_one_click_and_bootstraps_defaults(self):
        biz=repo.create_business(self.uid,'Quick Trial',package='NONE')
        self.assertEqual(f.list_accounts(biz,actor_user_id=self.uid),[])
        response=self.client.post(f'/business/{biz}/finance-trial/start')
        self.assertEqual(response.status_code,303)
        self.assertIn(f'/business/{biz}/finance',response.location)
        self.assertEqual(e.state(biz)['status'],'TRIAL_ACTIVE')
        accounts=f.list_accounts(biz,actor_user_id=self.uid)
        self.assertTrue(any(a['currency']=='IDR' and a['is_active'] for a in accounts))
        categories=f.list_categories(biz,actor_user_id=self.uid)
        self.assertTrue(any(row['direction']=='INCOME' for row in categories))
        self.assertTrue(any(row['direction']=='EXPENSE' for row in categories))
        self.assertEqual(f.list_transactions(biz,actor_user_id=self.uid),[])

    def test_finance_product_new_business_starts_trial_directly(self):
        self.client.post('/products/select',data={'product':'finance'})
        before={b['id'] for b in repo.list_businesses_for_user(self.uid)}
        response=self.client.post('/products/continue',data={
            'create':'yes','setup_identity':uuid.uuid4().hex,'business_name':'Trial Baru'})
        self.assertEqual(response.status_code,303)
        after=repo.list_businesses_for_user(self.uid)
        created=next(b for b in after if b['id'] not in before)
        self.assertIn(f'/business/{created["id"]}/finance',response.location)
        self.assertEqual(e.state(created['id'])['status'],'TRIAL_ACTIVE')
        self.assertEqual(f.list_transactions(created['id'],actor_user_id=self.uid),[])
    def test_brain_setup_no_payment_activation(self):
        biz=repo.create_business(self.uid,'Brain',package='NONE');self.client.post('/products/select',data={'product':'brain'})
        response=self.client.post('/products/continue',data={'business_id':biz});self.assertIn('/wizard/basics',response.location);self.assertEqual(repo.get_business(biz)['package'],'AI_ADMIN');self.assertNotEqual(repo.get_business(biz)['status'],'ACTIVE')
    def test_personal_creative_keeps_service(self):
        self.client.post('/products/select',data={'product':'content_basic'});response=self.client.post('/products/continue',data={})
        self.assertEqual(response.status_code,200);self.assertIn('/services/content_basic/checkout-fixed',response.text)
    def test_csrf_all_new_mutations(self):
        app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=True
        for url in ('/products/select','/products/continue',self.setup_url,
                    f'/business/{self.b}/finance-trial/start',
                    f'/business/{self.b}/finance-bills/1/review'):
            self.assertEqual(self.client.post(url,data={}).status_code,400)
    def test_xss_business_escaped(self):
        db.execute('UPDATE businesses SET business_name=? WHERE id=?',('<script>bad()</script>',self.b));response=self.client.get(self.setup_url)
        self.assertNotIn('<script>bad()</script>',response.text);self.assertIn('&lt;script&gt;',response.text)
    def test_no_chat_storage_or_localstorage(self):
        tables=db.query_all("SELECT name FROM sqlite_master WHERE type='table'");self.assertFalse(any('chat' in x['name'] and 'finance' in x['name'] for x in tables))
        self.assertNotIn('localStorage',(Path(__file__).parents[1]/'static/finance_assistant.js').read_text())
    def test_camera_and_general_upload(self):
        response=self.client.get(self.url+'/assistant');self.assertIn('capture="environment"',response.text);self.assertIn('.pdf,.csv',response.text)
    def recurring(self):
        self.trial();return f.create_recurring_expense(self.b,'Rent',100,self.a,self.expense['id'],'MONTHLY','2026-09-01',actor_user_id=self.uid)
    def test_recurring_preview_zero_write(self):
        self.recurring();before=self.snapshot();rows=f.preview_due_recurring_expenses(self.b,'2026-09-17',self.uid);self.assertEqual(len(rows),1);self.assertEqual(before,self.snapshot())
    def test_recurring_selected_once(self):
        self.recurring();choice=f.preview_due_recurring_expenses(self.b,'2026-09-17',self.uid)[0]['selection']
        for _ in range(2):f.process_due_recurring_expenses(self.b,'2026-09-17',self.uid,selected=[choice])
        self.assertEqual(len(self.ledger()),1)
    def test_recurring_concurrent(self):
        self.recurring();choice=f.preview_due_recurring_expenses(self.b,'2026-09-17',self.uid)[0]['selection']
        fn=lambda:f.process_due_recurring_expenses(self.b,'2026-09-17',self.uid,selected=[choice])
        result=self.race([fn,fn]);self.assertEqual(sum(x[1]['posted_count'] for x in result),1)
    def test_recurring_unselected_not_advanced(self):
        rule=self.recurring();f.process_due_recurring_expenses(self.b,'2026-09-17',self.uid,selected=['999:2026-09-01'])
        self.assertEqual(f.get_recurring_expense(self.b,rule)['next_due_on'],'2026-09-01');self.assertFalse(self.ledger())
    def test_no_bulk_post_without_selection(self):
        self.recurring();response=self.client.post(self.url+'/recurring/process');self.assertEqual(response.status_code,303);self.assertFalse(self.ledger())
    def test_migration_parity_and_constraints(self):
        base=Path(__file__).parents[1]/'migrations';pg=(base/'0032_finance_subscription_postgres.sql').read_text()
        for table in ('finance_entitlements','finance_subscription_bills','product_business_setups'):
            self.assertIn(table,pg);self.assertIsNotNone(db.query_one("SELECT name FROM sqlite_master WHERE name=?",(table,)))
        self.assertIn('BYTEA',pg);self.assertIn('idx_finance_bill_pending',pg)
    def test_brain_checkout_get_is_read_only(self):
        db.execute("UPDATE businesses SET package='AI_ADMIN' WHERE id=?",(self.b,))
        ready=patch.object(repo,'required_fields_missing',return_value=[]);ready.start();self.addCleanup(ready.stop)
        before=self.snapshot();response=self.client.get(f'/business/{self.b}/ai-admin/checkout')
        self.assertEqual(response.status_code,200);self.assertEqual(before,self.snapshot())
        self.assertIn('Buat Pesanan',response.text)
    def test_brain_checkout_post_idempotent(self):
        db.execute("UPDATE businesses SET package='AI_ADMIN' WHERE id=?",(self.b,))
        ready=patch.object(repo,'required_fields_missing',return_value=[]);ready.start();self.addCleanup(ready.stop)
        url=f'/business/{self.b}/ai-admin/checkout';a=self.client.post(url);b=self.client.post(url)
        self.assertEqual(a.location,b.location);self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM projects WHERE business_id=? AND catalog_key='ai_admin'",(self.b,))['n'],1)
    def test_customer_cannot_review_bill_route(self):
        ident=self.bill();self.proof(ident)
        response=self.client.post(f'/business/{self.b}/finance-bills/{ident}/review',data={'decision':'approve'})
        self.assertEqual(response.status_code,400);self.assertFalse(e.state(self.b)['active'])
    def test_bill_human_review_page(self):
        ident=self.bill();self.proof(ident)
        with self.client.session_transaction() as session:session['user_id']=self.admin
        response=self.client.get(f'/business/{self.b}/finance-bills/{ident}')
        self.assertEqual(response.status_code,200);self.assertIn('Aksi Admin',response.text)
    def test_dashboard_business_selection_scoped(self):
        self.assertEqual(self.client.post('/products/dashboard-business',data={'business_id':self.other}).status_code,404)
        self.assertEqual(self.client.post('/products/dashboard-business',data={'business_id':self.b}).status_code,303)
    def test_finance_schema_missing_fails_closed(self):
        db.execute('DROP TABLE finance_entitlements')
        with self.assertRaises(Exception):self.tx()
        self.assertFalse(self.ledger())
    def test_billing_no_raw_filename_or_amount_audit(self):
        ident=self.bill();billing.upload_proof(self.b,ident,self.uid,'PRIVATE_FILENAME.png',self.raw);billing.review(self.b,ident,self.admin,True)
        rows=db.query_all("SELECT detail FROM audit_log WHERE business_id=? AND action LIKE 'FINANCE_SUBSCRIPTION_%'",(self.b,))
        for row in rows:
            self.assertEqual(row['detail'],f'bill_id={ident}')
    def test_valid_payment_duplicate_proof_no_second_extension(self):
        self.verified();before=e.state(self.b);next_bill=self.bill()
        with self.assertRaises(f.FinanceError):self.proof(next_bill)
        self.assertEqual(e.state(self.b),before)
    def test_late_renewal_from_verification_time(self):
        self.verified();self.time.return_value+=timedelta(days=35);ident=self.bill()
        billing.upload_proof(self.b,ident,self.uid,'renew.jpg',prior.image_bytes('JPEG'));billing.review(self.b,ident,self.admin,True)
        self.assertEqual(e.parse(e.state(self.b)['until'])-self.time.return_value,timedelta(days=30))
    def test_trial_blocks_payment_upload_for_preexisting_bill(self):
        ident=self.bill();self.trial();first=e.state(self.b)
        with self.assertRaises(f.FinanceError):self.proof(ident)
        self.assertEqual(e.state(self.b),first)
    def test_trial_requires_account(self):
        biz=repo.create_business(self.uid,'No account',package='NONE')
        with self.assertRaises(f.FinanceError):e.start_trial(biz,self.uid)
    def test_invalid_opening_balance_rejected(self):
        with self.assertRaises(f.FinanceError):e.setup(self.b,self.uid,'Bank','BANK',1.5)
    def test_setup_concurrent_single_account(self):
        biz=repo.create_business(self.uid,'New setup',package='NONE');fn=lambda:e.setup(biz,self.uid,'Kas','CASH',0)
        result=self.race([fn,fn]);self.assertEqual(result[0],result[1]);self.assertEqual(len(f.list_accounts(biz)),1)
    def test_paid_before_first_account_can_complete_setup(self):
        biz=repo.create_business(self.uid,'Paid first',package='NONE')
        ident=billing.create_bill(biz,self.uid,uuid.uuid4().hex)
        billing.upload_proof(biz,ident,self.uid,'proof.png',self.raw)
        billing.review(biz,ident,self.admin,True)
        url=f'/business/{biz}/finance-subscription'
        response=self.client.post(url,data={'action':'setup','name':'Kas','account_type':'CASH','opening_balance':'0'})
        self.assertEqual(response.status_code,303)
        self.assertEqual(len(f.list_accounts(biz,actor_user_id=self.uid)),1)
        self.assertFalse(f.list_transactions(biz,actor_user_id=self.uid))
        self.assertEqual(e.state(biz)['status'],'PAID_ACTIVE')
    def test_expired_paid_without_account_cannot_use_setup_exemption(self):
        biz=repo.create_business(self.uid,'Expired before setup',package='NONE')
        ident=billing.create_bill(biz,self.uid,uuid.uuid4().hex)
        billing.upload_proof(biz,ident,self.uid,'proof.png',self.raw)
        billing.review(biz,ident,self.admin,True)
        self.time.return_value+=timedelta(days=30)
        with self.assertRaises(f.FinanceError):e.setup(biz,self.uid,'Kas','CASH',0)
        self.assertFalse(f.list_accounts(biz,actor_user_id=self.uid))
    def test_expired_bank_stage_direct_blocked(self):
        source=extract.validate_sources([('statement.csv',self.csv)])
        with self.assertRaises(f.FinanceError):__import__('finance_bank_service').stage(self.b,self.a,source,[self.row],self.uid)
        self.assertFalse(self.ledger())
    def test_expiry_between_operator_draft_and_confirm(self):
        import json
        self.trial()
        # A real managed signed draft, with deterministic model interpretation mocked.
        fields={'amount_minor':100000,'description':'bensin'}
        with app.app_context(),patch.object(operator,'interpret',return_value=fields):
            draft=operator.prepare(self.b,self.uid,{'action':'create_expense','request':'catat bensin 100000','date':'2026-09-17','account_id':self.a,'category_id':self.expense['id'],'invoice_id':None})
            self.time.return_value+=timedelta(days=7)
            with self.assertRaises(ValueError):operator.confirm(self.b,self.uid,draft['token'])
        self.assertFalse(self.ledger());self.http.assert_not_called()
    def test_recurring_void_not_recreated(self):
        self.recurring();choice=f.preview_due_recurring_expenses(self.b,'2026-09-17',self.uid)[0]['selection']
        f.process_due_recurring_expenses(self.b,'2026-09-17',self.uid,selected=[choice]);tx=self.ledger()[0]
        f.void_transaction(self.b,tx['id'],actor_user_id=self.uid)
        f.process_due_recurring_expenses(self.b,'2026-09-17',self.uid,selected=[choice]);self.assertEqual(len(self.ledger()),1);self.assertEqual(self.ledger()[0]['status'],'VOID')

    def test_bill_request_replay_after_verified_returns_original(self):
        key=uuid.uuid4().hex;ident=billing.create_bill(self.b,self.uid,key);self.proof(ident);billing.review(self.b,ident,self.admin,True)
        self.assertEqual(billing.create_bill(self.b,self.uid,key),ident)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_subscription_bills')['n'],1)
    def test_two_pending_request_keys_replay_same_verified_bill(self):
        a,b=uuid.uuid4().hex,uuid.uuid4().hex
        ident=billing.create_bill(self.b,self.uid,a);self.assertEqual(billing.create_bill(self.b,self.uid,b),ident)
        self.proof(ident);billing.review(self.b,ident,self.admin,True)
        self.assertEqual(billing.create_bill(self.b,self.uid,b),ident)
