"""Inactive wallet foundation; isolated SQLite, synthetic proofs, no provider IO."""
import io
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db
from kilas_ai import credit_wallet as wallet, credit_wallet_schema as schema, usage
from werkzeug.datastructures import FileStorage


class WalletTests(unittest.TestCase):
    def setUp(self):
        db._discard_cached_connection()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name)/'wallet.sqlite')
        self.patches = [patch.object(db, 'BACKEND', 'sqlite'), patch.object(db, 'SQLITE_PATH', self.path)]
        for item in self.patches: item.start()
        with sqlite3.connect(self.path) as conn:
            conn.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,role TEXT NOT NULL)')
            conn.executemany('INSERT INTO users VALUES (?,?)', [(1,'CLIENT_OWNER'),(2,'CLIENT_OWNER'),(3,'KILAS_ADMIN')])
            schema.apply(conn)

    def tearDown(self):
        db._discard_cached_connection()
        for item in reversed(self.patches): item.stop()
        self.tmp.cleanup()

    def proof(self, user, ident):
        with patch('file_utils.validate_project_attachment_upload', return_value=('proof.png','image/png')):
            wallet.submit_proof(user, ident, FileStorage(stream=io.BytesIO(b'synthetic'), filename='proof.png', content_type='image/png'))

    def fund(self, user=1, key='purchase'):
        ident=wallet.create_purchase(user,key)
        self.proof(user,ident)
        wallet.review(ident,3,'VERIFIED')
        return ident

    def test_proof_is_not_payment_and_review_is_idempotent(self):
        ident=wallet.create_purchase(1,'purchase')
        self.assertEqual(wallet.create_purchase(1,'purchase'),ident)
        self.proof(1,ident)
        self.assertEqual(wallet.balance(1)['balance_milli'],0)
        with self.assertRaises(wallet.WalletError): wallet.review(ident,2,'VERIFIED')
        wallet.review(ident,3,'VERIFIED'); wallet.review(ident,3,'VERIFIED')
        self.assertEqual(wallet.balance(1)['balance_milli'],2000000)
        self.assertIsNone(wallet.order(2,ident))
        with self.assertRaises(wallet.WalletError): wallet.review(ident,3,'REJECTED')

    def test_capture_release_and_conflicting_retries(self):
        self.fund()
        wallet.reserve(1,'image',125000);wallet.reserve(1,'image',125000)
        self.assertEqual(wallet.balance(1)['reserved_milli'],125000)
        with self.assertRaises(wallet.WalletError): wallet.reserve(1,'image',126000)
        with self.assertRaises(wallet.WalletError): wallet.settle(1,'image',126000)
        wallet.settle(1,'image',100000);wallet.settle(1,'image',100000)
        self.assertEqual(wallet.balance(1),dict(balance_milli=1900000,reserved_milli=0,available_milli=1900000))
        wallet.reserve(1,'failed',5000);wallet.release(1,'failed');wallet.release(1,'failed')
        with self.assertRaises(wallet.WalletError): wallet.reserve(1,'failed',5000)
        with self.assertRaises(wallet.WalletError): wallet.settle(1,'failed',1000)
        with self.assertRaises(wallet.WalletError): wallet.release(1,'image')

    def test_concurrent_overspend_is_denied(self):
        self.fund()
        def reserve(n):
            try: wallet.reserve(1,'parallel-'+str(n),200000);return True
            except wallet.WalletError:return False
        with ThreadPoolExecutor(max_workers=8) as pool: accepted=list(pool.map(reserve,range(24)))
        self.assertEqual(sum(accepted),10)
        self.assertEqual(wallet.balance(1)['available_milli'],0)
        self.assertEqual(wallet.balance(2)['reserved_milli'],0)

    def test_concurrent_reviews_credit_once(self):
        ident=wallet.create_purchase(1,'purchase');self.proof(1,ident)
        with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(lambda _:wallet.review(ident,3,'VERIFIED'),range(16)))
        self.assertEqual(wallet.balance(1)['balance_milli'],2000000)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_credit_events WHERE kind='PURCHASE'")['n'],1)

    def test_no_expiry_and_reads_do_not_mutate(self):
        self.fund()
        before=db.query_all('SELECT * FROM kilas_credit_accounts')
        with patch.object(usage,'_now',return_value=usage._now().replace(year=2099)):
            self.assertEqual(wallet.balance(1)['available_milli'],2000000)
        wallet.balance(2)
        self.assertEqual(before,db.query_all('SELECT * FROM kilas_credit_accounts'))

    def test_invalid_and_cross_account_requests_fail_closed(self):
        self.fund()
        for value in (True,0,-1,1.5,'1000',10**13):
            with self.assertRaises(wallet.WalletError):wallet.reserve(1,'invalid',value)
        with self.assertRaises(wallet.WalletError):wallet.reserve(2,'other',1)
        with self.assertRaises(wallet.WalletError):wallet.settle(2,'other',0)
        with self.assertRaises(wallet.WalletError):wallet.reserve(999,'missing',1)
        ident=wallet.create_purchase(1,'another')
        with self.assertRaises(wallet.WalletError):self.proof(2,ident)
        with self.assertRaises(wallet.WalletError):wallet.review(ident,3,'VERIFIED')

    def test_rejection_requires_new_proof_before_credit(self):
        ident=wallet.create_purchase(1,'purchase');self.proof(1,ident)
        wallet.review(ident,3,'REJECTED')
        with self.assertRaises(wallet.WalletError):wallet.review(ident,3,'VERIFIED')
        self.proof(1,ident);wallet.review(ident,3,'VERIFIED')
        self.assertEqual(wallet.balance(1)['balance_milli'],2000000)

    def test_ledger_reconciles_balance_and_holds(self):
        self.fund();wallet.reserve(1,'one',100000);wallet.settle(1,'one',90000)
        wallet.reserve(1,'two',20000)
        sums=db.query_one('SELECT SUM(balance_delta) AS balance,SUM(reserved_delta) AS reserved FROM kilas_credit_events WHERE user_id=1')
        balance=wallet.balance(1)
        self.assertEqual((sums['balance'],sums['reserved']),(balance['balance_milli'],balance['reserved_milli']))

if __name__=='__main__':unittest.main()
