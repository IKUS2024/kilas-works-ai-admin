"""Inactive wallet foundation; isolated SQLite, synthetic proofs, no provider IO."""
import io
import os
import hashlib
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
        self.pg=os.environ.get('KILAS_CREDIT_TEST_POSTGRES')
        if self.pg:
            from urllib.parse import urlparse
            target=urlparse(self.pg)
            if target.hostname not in ('127.0.0.1','localhost') or target.path!='/kilas_credit_qa':
                raise RuntimeError('PostgreSQL wallet tests require the isolated loopback QA database')
            import psycopg2
            self.pg_patch=[patch.object(db,'BACKEND','postgres'),patch.object(db,'DATABASE_URL',self.pg),patch.object(db,'psycopg2',psycopg2,create=True)]
            for item in self.pg_patch:item.start()
            with psycopg2.connect(self.pg) as reset:
                with reset.cursor() as cursor:
                    cursor.execute('DROP SCHEMA IF EXISTS credit_wallet_test CASCADE; CREATE SCHEMA credit_wallet_test')
            self.options=patch.object(db,'_postgres_connect_kwargs',return_value={'options':'-c search_path=credit_wallet_test'})
            self.options.start()
        conn=usage._connect()
        try:
            usage._query(conn,'CREATE TABLE users(id INTEGER PRIMARY KEY,role TEXT NOT NULL,email TEXT)')
            for uid,role in [(1,'CLIENT_OWNER'),(2,'CLIENT_OWNER'),(3,'KILAS_ADMIN')]:usage._query(conn,'INSERT INTO users(id,role) VALUES (?,?)',(uid,role))
            schema.apply(conn)
            conn.commit()
        finally:conn.close()

    def tearDown(self):
        db._discard_cached_connection()
        if self.pg:
            self.options.stop()
            for item in reversed(self.pg_patch):item.stop()
        for item in reversed(self.patches): item.stop()
        self.tmp.cleanup()

    def reserve(self,user,key,amount,**kwargs):
        return wallet.reserve(user,key,amount,fingerprint=kwargs.get('fingerprint',hashlib.sha256(key.encode()).hexdigest()))

    def proof(self, user, ident):
        with patch('file_utils.validate_project_attachment_upload', return_value=('proof.png','image/png')):
            wallet.submit_proof(user, ident, FileStorage(stream=io.BytesIO(b'synthetic'), filename='proof.png', content_type='image/png'))

    def fund(self, user=1, key='purchase'):
        ident=wallet.create_purchase(user,key)
        self.proof(user,ident)
        wallet.review(ident,3,'VERIFIED',transfer_reference='TX-'+ident)
        return ident

    def test_proof_is_not_payment_and_review_is_idempotent(self):
        ident=wallet.create_purchase(1,'purchase')
        self.assertEqual(wallet.create_purchase(1,'purchase'),ident)
        self.proof(1,ident)
        self.assertEqual(wallet.balance(1)['balance_milli'],0)
        with self.assertRaises(wallet.WalletError): wallet.review(ident,2,'VERIFIED')
        wallet.review(ident,3,'VERIFIED',transfer_reference='TX-'+ident); wallet.review(ident,3,'VERIFIED',transfer_reference='TX-'+ident)
        self.assertEqual(wallet.balance(1)['balance_milli'],2000000)
        self.assertIsNone(wallet.order(2,ident))
        with self.assertRaises(wallet.WalletError): wallet.review(ident,3,'REJECTED')

    def test_capture_release_and_conflicting_retries(self):
        self.fund()
        self.reserve(1,'image',125000);self.reserve(1,'image',125000)
        self.assertEqual(wallet.balance(1)['reserved_milli'],125000)
        with self.assertRaises(wallet.WalletError): self.reserve(1,'image',126000)
        with self.assertRaises(wallet.WalletError): wallet.settle(1,'image',126000)
        wallet.settle(1,'image',100000);wallet.settle(1,'image',100000)
        self.assertEqual(wallet.balance(1),dict(balance_milli=1900000,reserved_milli=0,available_milli=1900000))
        self.reserve(1,'failed',5000);wallet.release(1,'failed');wallet.release(1,'failed')
        with self.assertRaises(wallet.WalletError): self.reserve(1,'failed',5000)
        with self.assertRaises(wallet.WalletError): wallet.settle(1,'failed',1000)
        with self.assertRaises(wallet.WalletError): wallet.release(1,'image')

    def test_concurrent_overspend_is_denied(self):
        self.fund()
        def reserve(n):
            try: self.reserve(1,'parallel-'+str(n),200000);return True
            except wallet.WalletError:return False
        with ThreadPoolExecutor(max_workers=8) as pool: accepted=list(pool.map(reserve,range(24)))
        self.assertEqual(sum(accepted),10)
        self.assertEqual(wallet.balance(1)['available_milli'],0)
        self.assertEqual(wallet.balance(2)['reserved_milli'],0)

    def test_concurrent_reviews_credit_once(self):
        ident=wallet.create_purchase(1,'purchase');self.proof(1,ident)
        with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(lambda _:wallet.review(ident,3,'VERIFIED',transfer_reference='TX-'+ident),range(16)))
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
            with self.assertRaises(wallet.WalletError):self.reserve(1,'invalid',value)
        with self.assertRaises(wallet.WalletError):self.reserve(2,'other',1)
        with self.assertRaises(wallet.WalletError):wallet.settle(2,'other',0)
        with self.assertRaises(wallet.WalletError):self.reserve(999,'missing',1)
        ident=wallet.create_purchase(1,'another')
        with self.assertRaises(wallet.WalletError):self.proof(2,ident)
        with self.assertRaises(wallet.WalletError):wallet.review(ident,3,'VERIFIED',transfer_reference='TX-'+ident)

    def test_rejection_requires_new_proof_before_credit(self):
        ident=wallet.create_purchase(1,'purchase');self.proof(1,ident)
        wallet.review(ident,3,'REJECTED')
        with self.assertRaises(wallet.WalletError):wallet.review(ident,3,'VERIFIED',transfer_reference='TX-'+ident)
        self.proof(1,ident);wallet.review(ident,3,'VERIFIED',transfer_reference='TX-'+ident)
        self.assertEqual(wallet.balance(1)['balance_milli'],2000000)

    def test_ledger_reconciles_balance_and_holds(self):
        self.fund();self.reserve(1,'one',100000);wallet.settle(1,'one',90000)
        self.reserve(1,'two',20000)
        sums=db.query_one('SELECT SUM(balance_delta) AS balance,SUM(reserved_delta) AS reserved FROM kilas_credit_events WHERE user_id=1')
        balance=wallet.balance(1)
        self.assertEqual((sums['balance'],sums['reserved']),(balance['balance_milli'],balance['reserved_milli']))

    def test_transfer_reference_cannot_credit_multiple_orders(self):
        first=self.fund();second=wallet.create_purchase(2,'another');self.proof(2,second)
        with self.assertRaises(wallet.WalletError):wallet.review(second,3,'VERIFIED',transfer_reference='TX-'+first)
        self.assertEqual(wallet.balance(2)['balance_milli'],0)
        self.assertEqual(wallet.order(2,second)['status'],'UNDER_REVIEW')
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_reviews')['n'],1)

    def test_changed_same_price_payload_cannot_reuse_operation(self):
        self.fund();self.reserve(1,'same-key',1000,fingerprint='a'*64)
        with self.assertRaises(wallet.WalletError):self.reserve(1,'same-key',1000,fingerprint='b'*64)
        wallet.settle(1,'same-key',1000)
        self.assertEqual(self.reserve(1,'same-key',1000,fingerprint='a'*64),'CAPTURED')
        with self.assertRaises(wallet.WalletError):wallet.review(wallet.create_purchase(2,'missing-ref'),3,'VERIFIED')

    def test_migration_reapplication_preserves_legacy_lots_and_wallet(self):
        self.fund()
        with wallet._locked(1) as conn:
            usage._query(conn,'CREATE TABLE kilas_ai_topup_credits(order_id BIGINT PRIMARY KEY,user_id BIGINT,total_micro BIGINT,expires_at TEXT)')
            usage._query(conn,"INSERT INTO kilas_ai_topup_credits VALUES (42,1,987654,'2030-01-01')")
        before=db.query_all('SELECT * FROM kilas_ai_topup_credits')
        balance=wallet.balance(1)
        self.assertTrue(schema.apply_release())
        self.assertFalse(schema.apply_release())
        self.assertEqual(before,db.query_all('SELECT * FROM kilas_ai_topup_credits'))
        self.assertEqual(balance,wallet.balance(1))
        # Operational rollback disables admission; no destructive schema rollback.
        with patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'no'}):
            self.assertEqual(balance,wallet.balance(1))

    def test_duplicate_proof_is_review_signal_not_automatic_rejection(self):
        first=self.fund();second=wallet.create_purchase(2,'second');self.proof(2,second)
        digests=db.query_all('SELECT proof_digest FROM kilas_credit_orders ORDER BY id')
        self.assertEqual(digests[0]['proof_digest'],digests[1]['proof_digest'])
        wallet.review(second,3,'VERIFIED',transfer_reference='DISTINCT-CONFIRMED-TRANSFER')
        self.assertEqual(wallet.balance(2)['balance_milli'],2000000)

    def test_concurrent_cross_account_duplicate_transfer_is_credited_once(self):
        one=wallet.create_purchase(1,'one');two=wallet.create_purchase(2,'two')
        self.proof(1,one);self.proof(2,two)
        def verify(ident):
            try:wallet.review(ident,3,'VERIFIED',transfer_reference='SHARED-BANK-TX');return True
            except wallet.WalletError:return False
        with ThreadPoolExecutor(max_workers=2) as pool:accepted=list(pool.map(verify,(one,two)))
        self.assertEqual(sum(accepted),1)
        self.assertEqual(wallet.balance(1)['balance_milli']+wallet.balance(2)['balance_milli'],2000000)

if __name__=='__main__':unittest.main()
