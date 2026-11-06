"""Cutoff rehearsal only: no production data or runtime activation."""
import unittest
from datetime import timedelta
from unittest.mock import patch
import db
from kilas_ai import credit_activation as activation, credit_wallet as wallet, usage
from test_kilas_credit_wallet import WalletTests


class ActivationTests(unittest.TestCase):
    setUp=WalletTests.setUp
    tearDown=WalletTests.tearDown
    fund=WalletTests.fund
    proof=WalletTests.proof

    def candidate(self):
        now=usage._now().isoformat()
        return dict(cutoff=now,release_sha='a'*40,tariff_digest='b'*64,
            snapshot={'observed_at':now,'meter_version':activation.METER,'unresolved_nonowner_records':0,'accepted_operations':0,'high_watermarks':{'image':12,'interpreter':29}},
            baselines=[{'user_id':1,'feature':'IMAGE','period_start':'LIFETIME','units':1,'provenance':'successful_usage'}])

    def test_immutable_restart_reapplication_never_replenishes_or_converts_balance(self):
        self.fund();before=wallet.balance(1);candidate=self.candidate()
        self.assertTrue(activation.prepare(**candidate));self.assertFalse(activation.prepare(**candidate))
        db._discard_cached_connection();self.assertFalse(activation.prepare(**candidate))
        self.assertEqual(wallet.balance(1),before)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_quota_baselines')['n'],1)
        with self.assertRaisesRegex(wallet.WalletError,'immutable'):activation.prepare(**{**candidate,'release_sha':'c'*40})
        self.assertEqual(db.query_one('SELECT units FROM kilas_credit_quota_baselines')['units'],1)

    def test_missing_customer_metering_active_operations_stale_audit_and_flag_reject(self):
        candidate=self.candidate()
        for field in ('unresolved_nonowner_records','accepted_operations'):
            with self.assertRaisesRegex(wallet.WalletError,'review_required'):activation.prepare(**{**candidate,'snapshot':{**candidate['snapshot'],field:1}})
        with self.assertRaisesRegex(wallet.WalletError,'stale'):activation.prepare(**{**candidate,'snapshot':{**candidate['snapshot'],'observed_at':(usage._now()-timedelta(minutes=6)).isoformat()}})
        with patch.dict('os.environ',{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'yes'}):
            with self.assertRaisesRegex(wallet.WalletError,'disabled'):activation.prepare(**candidate)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_activation')['n'],0)

    def test_unverified_source_conversion_owner_or_duplicate_baseline_reject(self):
        candidate=self.candidate();row=candidate['baselines'][0]
        for wrong in ({**row,'provenance':'output_duration_estimate'},{**row,'user_id':9}):
            with self.assertRaises(wallet.WalletError):activation.prepare(**{**candidate,'baselines':[wrong]})
        with self.assertRaisesRegex(wallet.WalletError,'duplicate'):activation.prepare(**{**candidate,'baselines':[row,row]})
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_events')['n'],0)


if __name__=='__main__':unittest.main()
