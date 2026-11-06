"""Admission policy tests use synthetic tariffs; none is a proposed live price."""
import json
import os
from unittest.mock import patch
from test_kilas_credit_wallet import WalletTests
from kilas_ai import credit_policy as policy, usage, credit_wallet as wallet


class PolicyTests(WalletTests):
    def setUp(self):
        super().setUp()
        self.flags=patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'yes','KILAS_CREDIT_TARIFFS_JSON':json.dumps({'version':'customer-credit-v1','rates':{'CHAT':{'milli':1000,'units':1},'IMAGE':{'milli':5000,'units':1}}})})
        self.flags.start()

    def tearDown(self):
        self.flags.stop();super().tearDown()

    def test_free_daily_boundary_then_explicit_paid_consent(self):
        self.fund()
        for n in range(70):
            key='free-'+str(n)
            self.assertTrue(policy.admit(1,key,'CHAT',1,policy.fingerprint({'text':key}))['dispatch'])
            policy.finish(1,key,1,success=True)
        with self.assertRaisesRegex(wallet.WalletError,'consent'):policy.admit(1,'paid','CHAT',1,'a'*64)
        token=__import__('db').query_one("SELECT token FROM kilas_credit_consents WHERE user_id=1 AND operation_key='paid'")['token']
        policy.consent(1,token,True)
        self.assertEqual(policy.admit(1,'paid','CHAT',1,'a'*64)['source'],'PAID')
        with patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'no'}):policy.finish(1,'paid',1,success=True)
        self.assertEqual(wallet.balance(1)['balance_milli'],1999000)

    def test_owner_is_pinned_not_role_or_qa_list(self):
        with wallet._locked(1) as conn:
            usage._query(conn,"INSERT INTO users(id,role,email) VALUES (9,'CLIENT_OWNER','irvankarnavi@gmail.com')")
            self.assertTrue(policy.owner(conn,9));self.assertFalse(policy.owner(conn,1));self.assertFalse(policy.owner(conn,3))
            usage._query(conn,"UPDATE users SET email='different@example.test' WHERE id=9")
            self.assertFalse(policy.owner(conn,9))
        with patch.dict(os.environ,{'KILAS_AI_INTERNAL_QA_EMAILS':'any@example.test','KILAS_APP_FREE_TEST_ENABLED':'true'}):
            self.assertEqual(policy.admit(1,'normal','CHAT',1,'a'*64)['source'],'FREE')

    def test_request_fingerprint_and_terminal_never_redispatch(self):
        policy.admit(1,'one','CHAT',1,'a'*64);policy.finish(1,'one',1,success=True)
        self.assertFalse(policy.admit(1,'one','CHAT',1,'a'*64)['dispatch'])
        with self.assertRaisesRegex(wallet.WalletError,'idempotency'):policy.admit(1,'one','CHAT',1,'b'*64)

    def test_unknown_outcome_stays_held_and_does_not_retry(self):
        policy.admit(1,'image','IMAGE',1,'a'*64)
        policy.finish(1,'image',0,success=False)
        self.assertFalse(policy.admit(1,'image','IMAGE',1,'a'*64)['dispatch'])
        with self.assertRaises(wallet.WalletError):policy.admit(1,'next','IMAGE',1,'b'*64)
        policy.finish(1,'image',0,success=False,definitive_failure=True)
        self.assertEqual(policy.admit(1,'next','IMAGE',1,'b'*64)['source'],'FREE')

    def test_unapproved_tariffs_partial_duration_and_disabled_policy_fail_closed(self):
        self.fund()
        with self.assertRaisesRegex(wallet.WalletError,'not_approved'):policy.admit(1,'ocr','RECEIPT',1,'a'*64,spending_ceiling=1000)
        with self.assertRaisesRegex(wallet.WalletError,'not_approved'):policy.admit(1,'long','TRANSLATOR',180001,'b'*64,spending_ceiling=1000)
        with patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'no'}):
            with self.assertRaisesRegex(wallet.WalletError,'disabled'):policy.admit(1,'off','CHAT',1,'c'*64)

    def test_historical_lifetime_trial_is_not_replenished(self):
        from kilas_ai import credit_wallet_schema
        with wallet._locked(1) as conn:
            usage._query(conn,'CREATE TABLE kilas_ai_usage(user_id BIGINT,operation_key TEXT,operation_type TEXT,status TEXT,created_at TEXT)')
            usage._query(conn,"INSERT INTO kilas_ai_usage VALUES (1,'old-sponsored','IMAGE_GENERATION','COMPLETE',?)",(usage._now().isoformat(),))
        for _ in range(3):
            with wallet._locked(1) as conn:
                credit_wallet_schema.apply(conn)
                self.assertEqual(policy.remaining_in(conn,1,'IMAGE',usage._now()),0)
        self.assertEqual(wallet.balance(1)['balance_milli'],0)

if __name__=='__main__':
    import unittest
    unittest.main()
