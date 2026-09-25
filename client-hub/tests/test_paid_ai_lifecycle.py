"""Real paid lifecycle, independent channel gating; synthetic isolated records only."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import test_business_hub_v2_phase_a as fixture
import db, repo, catalog_service, projects_repo, payment_service as pay
import subscription_service as subs
import provisioning
from public_chat import security as web_security, schema, store

class PaidLifecycleTests(unittest.TestCase):
    def setUp(self):
        fixture.reset_db(); catalog_service.seed_catalog_if_needed(); schema.apply_schema()
        self.uid=repo.create_user('paid-qa@example.test','unused')
        self.admin=repo.create_user('admin-paid-qa@example.test','unused',role='KILAS_ADMIN')
        self.bid=repo.create_business(self.uid,'Paid QA','AI_ADMIN_PRO')
        db.execute("UPDATE businesses SET status='APPROVED' WHERE id=?",(self.bid,))
        pid=projects_repo.create_fixed_price_project(self.bid,catalog_service.get_catalog_item('ai_admin_pro'),self.uid)
        iid=pay.checkout(pid,self.bid,self.uid)
        self.pid=pay.get_payment_for_invoice(iid)['id']
        db.execute("UPDATE payments SET status='UNDER_REVIEW' WHERE id=?",(self.pid,))
        self.flags=patch.dict(os.environ,KILAS_CORE_V2_ENABLED='true',KILAS_CORE_V2_TEST_BUSINESS_IDS=str(self.bid),KILAS_WEB_CHAT_ENABLED='true')
        self.flags.start(); self.addCleanup(self.flags.stop)
    def verify(self):
        pay.verify_payment(self.pid,self.bid,self.admin)
    def historical(self,age=10):
        stamp=(datetime.now(timezone.utc)-timedelta(days=age)).isoformat()
        db.execute("UPDATE payments SET status='VERIFIED',verified_at=? WHERE id=?",(stamp,self.pid))
        db.execute("UPDATE invoices SET status='PAID' WHERE id=(SELECT invoice_id FROM payments WHERE id=?)",(self.pid,))
        return stamp
    def test_verified_payment_creates_entitlement_without_whatsapp(self):
        self.assertFalse(web_security.available(repo.get_business(self.bid)))
        self.verify(); sub=subs.get_subscription(self.bid)
        stamp=subs._parse(pay.get_payment(self.pid)['verified_at'])
        self.assertEqual(subs._parse(sub['period_start']),stamp)
        self.assertEqual(subs._parse(sub['period_end']),stamp+timedelta(days=30))
        self.assertFalse(repo.get_business(self.bid)['whatsapp_connected'])
        self.assertTrue(web_security.available(repo.get_business(self.bid)))
        channel=store.ensure_channel(self.bid)
        client=fixture.FLASK_APP.test_client()
        self.assertEqual(client.get('/chat/'+channel['slug']).status_code,200)
        with self.assertRaises(provisioning.ProvisioningError):
            provisioning.activate_tenant(self.bid,{'id':self.admin,'role':'KILAS_ADMIN'})
        self.assertEqual(repo.get_business(self.bid)['status'],'APPROVED')
    def test_unpaid_and_finance_only_denied(self):
        with self.assertRaises(ValueError):subs.establish_paid_subscription(self.bid,self.admin)
        other=repo.create_business(self.uid,'Finance QA','NONE')
        with self.assertRaises(ValueError):subs.establish_paid_subscription(other,self.admin)
        self.assertFalse(web_security.available(repo.get_business(other)))
        self.assertIsNone(subs.get_subscription(other))
    def test_historical_evidence_and_concurrent_retry(self):
        stamp=self.historical()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:subs.establish_paid_subscription(self.bid,self.admin),range(2)))
        self.assertEqual(results[0],results[1])
        self.assertEqual(subs._parse(results[0]['period_start']),subs._parse(stamp))
        self.assertEqual(db.query_one('SELECT count(*) n FROM subscriptions WHERE business_id=?',(self.bid,))['n'],1)
        self.assertEqual(db.query_one("SELECT count(*) n FROM audit_log WHERE business_id=? AND action='SUBSCRIPTION_PAYMENT_EVIDENCE'",(self.bid,))['n'],1)
    def test_duplicate_verified_payment_same_invoice_is_one_period(self):
        stamp=self.historical()
        iid=pay.get_payment(self.pid)['invoice_id']
        db.execute("INSERT INTO payments (business_id,invoice_id,status,verified_at) VALUES (?,?,'VERIFIED',?)",
                   (self.bid,iid,stamp))
        evidence=subs.verified_payment_period(self.bid)
        self.assertEqual(evidence['payment_ids'],[self.pid])
        self.assertEqual(subs._parse(evidence['period_end']),subs._parse(stamp)+timedelta(days=30))

    def test_existing_active_and_grace_period_never_reset(self):
        self.verify()
        for state in ('ACTIVE','GRACE'):
            db.execute('UPDATE subscriptions SET status=? WHERE business_id=?',(state,self.bid))
            before=subs.get_subscription(self.bid)
            self.verify();subs.establish_paid_subscription(self.bid,self.admin)
            self.assertEqual(before,subs.get_subscription(self.bid))
    def test_expired_history_does_not_get_new_active_period(self):
        self.historical(60)
        self.assertEqual(subs.establish_paid_subscription(self.bid,self.admin)['status'],'SUSPENDED')
        self.assertFalse(web_security.available(repo.get_business(self.bid)))
    def test_missing_date_fails_closed(self):
        self.historical();db.execute('UPDATE payments SET verified_at=NULL WHERE id=?',(self.pid,))
        with self.assertRaises(ValueError):subs.establish_paid_subscription(self.bid,self.admin)
        self.assertIsNone(subs.get_subscription(self.bid))
    def test_payment_and_audit_rollback_if_entitlement_fails(self):
        with patch.object(subs,'create_subscription_with_explicit_period',side_effect=RuntimeError('qa failure')):
            with self.assertRaises(RuntimeError):self.verify()
        self.assertEqual(pay.get_payment(self.pid)['status'],'UNDER_REVIEW')
        self.assertIsNone(subs.get_subscription(self.bid))
        self.assertEqual(db.query_one("SELECT count(*) n FROM audit_log WHERE business_id=? AND action='PAYMENT_VERIFIED'",(self.bid,))['n'],0)

if __name__=='__main__': unittest.main()
