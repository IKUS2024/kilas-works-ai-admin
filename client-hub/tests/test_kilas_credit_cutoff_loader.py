"""Strict disabled cutover, loader/checksum and rollback rehearsal; no production."""
import json
import os
import unittest
from datetime import timedelta
from unittest.mock import patch
import db
from kilas_ai import credit_activation as activation,credit_policy as policy,credit_wallet as wallet,usage
from test_kilas_credit_wallet import WalletTests


class CutoffTests(unittest.TestCase):
    setUp=WalletTests.setUp
    tearDown=WalletTests.tearDown
    fund=WalletTests.fund
    proof=WalletTests.proof

    def fixture(self):
        value={'version':'customer-credit-v1','rates':{'CHAT':{'milli':1000,'units':1}}}
        flags=patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'no','KILAS_CREDIT_CUTOFF_CANDIDATE_ENABLED':'yes','KILAS_CREDIT_ACTIVATION_VERSION':activation.VERSION,'KILAS_CREDIT_POLICY_RELEASE_SHA':'a'*40,'KILAS_CREDIT_TARIFFS_JSON':json.dumps(value)})
        flags.start();self.addCleanup(flags.stop)
        db.execute('CREATE TABLE kilas_ai_usage(id INTEGER PRIMARY KEY,user_id INTEGER,operation_key TEXT,operation_type TEXT,status TEXT,created_at TEXT)')
        cutoff=usage._now();before=(cutoff-timedelta(seconds=1)).isoformat()
        db.execute("INSERT INTO kilas_ai_usage VALUES (1,1,'old-image','IMAGE_GENERATION','COMPLETE',?)",(before,))
        self.args=dict(cutoff=cutoff.isoformat(),release_sha='a'*40,tariff_digest=policy.fingerprint(value),snapshot={'observed_at':cutoff.isoformat(),'meter_version':activation.METER,'unresolved_nonowner_records':0,'accepted_operations':0,'high_watermarks':{'image':1}},baselines=[{'user_id':1,'feature':'IMAGE','period_start':'LIFETIME','units':1,'provenance':'successful_usage'}])
        return flags

    def test_authoritative_baseline_loader_restart_and_real_new_usage_are_not_double_counted(self):
        self.fixture();self.assertTrue(activation.prepare(**self.args));self.assertFalse(activation.prepare(**self.args))
        for _ in range(2):
            db._discard_cached_connection()
            with wallet._locked(1) as conn:self.assertEqual(policy.remaining_in(conn,1,'IMAGE',usage._now()),0)
        db.execute("INSERT INTO kilas_ai_usage VALUES (2,2,'new-image','IMAGE_GENERATION','COMPLETE',?)",(usage._now().isoformat(),))
        with wallet._locked(2) as conn:self.assertEqual(policy.remaining_in(conn,2,'IMAGE',usage._now()),0)
        self.assertEqual(wallet.balance(1)['balance_milli'],0)

    def test_disabled_hold_allows_settlement_but_no_new_admission_and_no_legacy_fallback(self):
        self.fixture();activation.prepare(**self.args)
        with self.assertRaisesRegex(wallet.WalletError,'hold'):activation.gate(1)
        with patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'yes'}):
            policy.admit(1,'accepted','CHAT',1,'a'*64)
        policy.finish(1,'accepted',1,success=True)
        with self.assertRaises(wallet.WalletError):policy.admit(1,'new','CHAT',1,'b'*64)
        self.assertEqual(db.query_one("SELECT status FROM kilas_credit_admissions WHERE operation_key='accepted'")['status'],'CAPTURED')

    def test_tampered_baseline_tariff_schema_release_and_missing_marker_fail_closed(self):
        self.fixture()
        with self.assertRaisesRegex(wallet.WalletError,'required'):activation.gate(1)
        activation.prepare(**self.args)
        for field,value in [('KILAS_CREDIT_POLICY_RELEASE_SHA','b'*40),('KILAS_CREDIT_TARIFFS_JSON','{}'),('KILAS_CREDIT_ACTIVATION_VERSION','wrong')]:
            with patch.dict(os.environ,{field:value}):
                with self.assertRaises(wallet.WalletError):activation.gate(1)
        with patch.object(activation,'schema_checksum',return_value='changed'):
            with self.assertRaisesRegex(wallet.WalletError,'changed'):activation.gate(1)
        db.execute('UPDATE kilas_credit_quota_baselines SET units=0')
        with self.assertRaisesRegex(wallet.WalletError,'changed'):activation.gate(1)

    def test_snapshot_claim_cannot_hide_active_operations_or_missing_lifetime_baseline(self):
        self.fixture()
        db.execute("INSERT INTO kilas_ai_usage VALUES (2,2,'active','CHAT','PENDING',?)",(usage._now().isoformat(),))
        with self.assertRaisesRegex(wallet.WalletError,'not_drained'):activation.prepare(**self.args)
        db.execute('DELETE FROM kilas_ai_usage WHERE id=2')
        with self.assertRaisesRegex(wallet.WalletError,'incomplete'):activation.prepare(**{**self.args,'baselines':[]})
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_activation')['n'],0)


if __name__=='__main__':unittest.main()
