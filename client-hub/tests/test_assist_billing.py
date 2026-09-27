"""Final auditable pricing over the existing purchase and subscription authority."""
import json
import unittest
from datetime import timedelta
import test_client_hub_v1 as fixture
import assist_billing as billing
import catalog_service
import payment_service
import subscription_service as subs

repo,db=fixture.repo,fixture.db

class BillingTests(unittest.TestCase):
    def setUp(self):
        fixture.reset_db();catalog_service.seed_catalog_if_needed()
        self.owner=repo.create_user('owner@test.invalid','hash')
        self.admin=repo.create_user('admin@test.invalid','hash',role='KILAS_ADMIN')
        self.bid=repo.create_business(self.owner,'Business','AI_ADMIN')

    def purchase(self,plan):
        project=billing.purchase(self.bid,self.owner,plan)
        invoice=payment_service.checkout(project,self.bid,self.owner)
        payment=payment_service.get_payment_for_invoice(invoice)
        db.execute("UPDATE payments SET status='UNDER_REVIEW' WHERE id=?",(payment['id'],))
        return project,invoice,payment['id']

    def test_launch_then_normal_renewal_and_verified_retry(self):
        for plan in ('ai_admin','ai_admin_pro'):
            self.assertEqual(billing.offer(self.bid,plan)['amount'],99000)
        pid,iid,payment=self.purchase('ai_admin')
        self.assertEqual(billing.purchase(self.bid,self.owner,'ai_admin'),pid)
        snapshot=fixture.projects_repo.get_project(pid)['requirements']['assist_pricing']
        self.assertEqual(snapshot['rule_id'],billing.ASSIST_LAUNCH_RULE['id'])
        self.assertEqual(snapshot['discount'],200000)
        self.assertIsNone(subs.get_subscription(self.bid))
        payment_service.verify_payment(payment,self.bid,self.admin)
        first=subs.get_subscription(self.bid)
        self.assertEqual(first['status'],'ACTIVE')
        payment_service.verify_payment(payment,self.bid,self.admin)
        self.assertEqual(subs.get_subscription(self.bid)['period_end'],first['period_end'])
        self.assertEqual(billing.offer(self.bid,'ai_admin')['amount'],299000)
        _,next_iid,next_payment=self.purchase('ai_admin')
        self.assertNotEqual(iid,next_iid)
        self.assertEqual(payment_service.get_invoice(next_iid)['amount'],299000)
        payment_service.verify_payment(next_payment,self.bid,self.admin)
        self.assertEqual(subs._parse(subs.get_subscription(self.bid)['period_end'])-subs._parse(first['period_end']),timedelta(days=30))
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM subscriptions')['n'],1)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n'],0)

    def test_pro_upgrade_requires_verified_payment_and_retains_training(self):
        _,_,payment=self.purchase('ai_admin')
        payment_service.verify_payment(payment,self.bid,self.admin)
        repo.replace_business_faqs(self.bid,['Harga tidak boleh diubah tanpa izin'])
        before=repo.get_business_faqs(self.bid)
        _,invoice,payment=self.purchase('ai_admin_pro')
        self.assertEqual(payment_service.get_invoice(invoice)['amount'],799000)
        self.assertEqual(repo.get_business(self.bid)['package'],'AI_ADMIN')
        payment_service.verify_payment(payment,self.bid,self.admin)
        self.assertEqual(repo.get_business(self.bid)['package'],'AI_ADMIN_PRO')
        self.assertEqual(subs.get_subscription(self.bid)['plan_key'],'ai_admin_pro')
        self.assertEqual(repo.get_business_faqs(self.bid),before)
        current=subs.get_subscription(self.bid)['period_end']
        payment_service.verify_payment(payment,self.bid,self.admin)
        self.assertEqual(subs.get_subscription(self.bid)['period_end'],current)

    def test_catalog_revision_keeps_historical_invoice_amounts(self):
        _,iid,_=self.purchase('ai_admin')
        catalog_service.seed_catalog_if_needed()
        self.assertEqual(payment_service.get_invoice(iid)['amount'],99000)
        self.assertEqual(catalog_service.get_catalog_item('ai_admin')['price_amount'],299000)
        self.assertEqual(catalog_service.get_catalog_item('ai_admin_pro')['price_amount'],799000)
        self.assertTrue(catalog_service.get_catalog_item('ai_admin_pro')['is_active'])
        other=repo.create_user('other@test.invalid','hash')
        with self.assertRaisesRegex(ValueError,'not_found'):billing.purchase(self.bid,other,'ai_admin')

    def test_signup_first_public_pricing(self):
        page=fixture.fresh_client().get('/')
        self.assertEqual(page.status_code,200)
        for value in ('Starter','Pro','99.000','299.000','799.000','register'):
            self.assertIn(value,page.text)
        self.assertNotIn('Tidak ada trial',page.text)

    def test_owner_checkout_post_creates_one_purchase_and_reuses_retry(self):
        repo.upsert_business_profile(self.bid,dict(category='Jasa',short_description='Foto produk',primary_language='id'))
        client=fixture.fresh_client()
        with client.session_transaction() as session:
            session['user_id']=self.owner
            session['csrf_token']='checkout-test'
        path=f'/business/{self.bid}/ai-admin/checkout?plan=ai_admin_pro'
        first=client.post(path,data={'csrf_token':'checkout-test'})
        retry=client.post(path,data={'csrf_token':'checkout-test'})
        self.assertEqual(first.status_code,302)
        self.assertEqual(first.location,retry.location)
        project=billing.pending(self.bid)
        self.assertIsNotNone(project)
        self.assertEqual(fixture.projects_repo.get_project(project['id'])['requirements']['assist_pricing']['amount'],99000)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM projects WHERE business_id=?',(self.bid,))['n'],1)

    def test_checkout_without_operational_or_whatsapp_fields_for_both_plans(self):
        import assist_connections
        for plan in ('ai_admin','ai_admin_pro'):
            with self.subTest(plan=plan):
                bid=repo.create_business(self.owner,'Checkout '+plan,'AI_ADMIN_PRO')
                repo.upsert_business_profile(bid,dict(category='Jasa',short_description='Foto produk',primary_language='id'))
                missing=repo.required_fields_missing(bid)
                for field in ('operating_hours','online_or_offline','business_phone','trusted_owner_phone'):
                    self.assertIn(field,missing)
                client=fixture.fresh_client()
                with client.session_transaction() as session:
                    session.update(user_id=self.owner,csrf_token='checkout-test')
                path=f'/business/{bid}/ai-admin/checkout?plan={plan}'
                page=client.get(path)
                self.assertEqual(page.status_code,200)
                self.assertIn('Tinjau langganan Kilas Assist',page.text)
                result=client.post(path,data={'csrf_token':'checkout-test'})
                self.assertEqual(result.status_code,302)
                self.assertIn('/checkout',result.location)
                self.assertNotIn('/wizard/',result.location)
                self.assertEqual(client.get(result.location).status_code,200)
                project=billing.pending(bid)
                self.assertEqual(project['catalog_key'],plan)
                self.assertIsNone(subs.get_subscription(bid))
                self.assertFalse(payment_service.has_verified_ai_admin_payment(bid))
                invoice=payment_service.checkout(project['id'],bid,self.owner)
                payment=payment_service.get_payment_for_invoice(invoice)
                db.execute("UPDATE payments SET status='UNDER_REVIEW' WHERE id=?",(payment['id'],))
                payment_service.verify_payment(payment['id'],bid,self.admin)
                self.assertEqual(subs.get_subscription(bid)['status'],'ACTIVE')
                self.assertEqual(assist_connections.get(bid)['state'],'Pending')
                self.assertFalse((repo.get_whatsapp_config(bid) or {}).get('connection_status')=='CONNECTED')
                with self.assertRaises(ValueError):
                    assist_connections.activate(bid,dict(id=self.admin,role='KILAS_ADMIN'))
                self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n'],0)

    def test_checkout_still_requires_identity_authorized_account_and_valid_plan(self):
        client=fixture.fresh_client()
        path=f'/business/{self.bid}/ai-admin/checkout'
        self.assertEqual(client.get(path).status_code,302)
        with client.session_transaction() as session:
            session.update(user_id=self.owner,csrf_token='checkout-test')
        self.assertIn('/wizard/',client.get(path).location)
        repo.upsert_business_profile(self.bid,dict(category='Jasa',short_description='Foto produk',primary_language='id'))
        self.assertEqual(client.get(path+'?plan=not-a-plan').status_code,400)
        self.assertEqual(client.post(path+'?plan=not-a-plan',data={'csrf_token':'checkout-test'}).status_code,400)
        other=repo.create_user('foreign@test.invalid','hash')
        with client.session_transaction() as session:
            session['user_id']=other
        self.assertEqual(client.get(path).status_code,404)
        self.assertEqual(client.post(path,data={'csrf_token':'checkout-test'}).status_code,404)
        self.assertIsNone(billing.pending(self.bid))

if __name__=='__main__':unittest.main()
