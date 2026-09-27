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

if __name__=='__main__':unittest.main()
