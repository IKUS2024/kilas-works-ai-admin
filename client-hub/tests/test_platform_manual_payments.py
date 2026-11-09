"""Unified manual payments: isolated SQLite, real services/auth, no provider or live IO.

Run: python tests/test_platform_manual_payments.py
"""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# PostgreSQL is admitted only by the loopback/schema-isolated companion runner.
_pg_schema = getattr(sys.modules.get('db'), '_platform_payments_qa_schema', None)
if not _pg_schema:
    os.environ['CLIENT_HUB_DB_PATH'] = tempfile.mktemp(suffix='-platform-payments.sqlite')
os.environ['SECRET_KEY'] = 'synthetic-platform-payments-only'
os.environ['KILAS_AI_ENABLED'] = 'true'
if not _pg_schema:
    os.environ.pop('DATABASE_URL', None)

import app
import db
import repo
import finance_subscription
import platform_payments
from kilas_ai import billing, topups, audio_billing, audio_store, usage
from auth_test_helpers import authenticate
from PIL import Image
from werkzeug.datastructures import FileStorage


class ManualPaymentsTests(unittest.TestCase):
    def setUp(self):
        app.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        self.owner = repo.create_user(uuid4().hex+'@example.test', 'hash')
        self.admin = repo.create_user(uuid4().hex+'@example.test', 'hash', role='KILAS_ADMIN')
        self.business = repo.create_business(self.owner, 'Synthetic Finance '+uuid4().hex, 'AI_ADMIN')
        self.client = app.app.test_client()
        authenticate(self.client, repo.get_user_by_id(self.admin), _csrf_token='test-csrf')
        self.env = patch.dict(os.environ, {
            'KILAS_FINANCE_ACCESS_MODE':'self_service',
            'KILAS_FINANCE_PAYMENT_BANK_NAME':'TEST BANK',
            'KILAS_FINANCE_PAYMENT_BANK_ACCOUNT':'TEST ACCOUNT',
            'KILAS_FINANCE_PAYMENT_BANK_HOLDER':'TEST HOLDER'})
        self.env.start(); self.addCleanup(self.env.stop)
        out = io.BytesIO()
        Image.new('RGB', (2, 2), tuple(bytes.fromhex(uuid4().hex[:6]))).save(out, format='PNG')
        self.proof = out.getvalue()
        self.ids = {}

    def upload(self):
        return FileStorage(io.BytesIO(self.proof), filename='proof.png', content_type='image/png')

    def seed(self, kind, with_proof=True):
        if kind == 'subscription':
            invoice = billing.create_invoice(self.owner, 'PLUS')
            if with_proof: billing.submit_proof(self.owner, invoice, self.upload())
            row = billing.proof_status(self.owner, invoice)
            ident = row['id'] if row else None
            self.invoice = invoice
        elif kind == 'capacity':
            ident = topups.create_order(self.owner, 'MINI')
            if with_proof: topups.submit_proof(self.owner, ident, self.upload())
        elif kind == 'translator':
            ident = audio_billing.create(self.owner, 'MINUTE')
            if with_proof: audio_billing.proof(self.owner, ident, self.upload())
        else:
            ident = finance_subscription.create_bill(self.business, self.owner, uuid4().hex)
            if with_proof: finance_subscription.upload_proof(self.business, ident, self.owner, 'proof.png', self.proof)
        self.ids[kind] = ident
        return ident

    def post(self, kind, decision='VERIFIED', **extra):
        return self.client.post(f'/platform/payments/{kind}/{self.ids[kind]}/review',
            data={'csrf_token':'test-csrf', 'decision':decision, **extra})

    def row(self, kind):
        table = {'subscription':'kilas_ai_payments','capacity':'kilas_ai_topup_orders',
                 'translator':'kilas_audio_orders','finance':'finance_subscription_bills'}[kind]
        return db.query_one(f'SELECT * FROM {table} WHERE id=?', (self.ids[kind],))

    def entitlement(self, kind):
        if kind == 'subscription':
            return db.query_one('SELECT plan,status,period_start,period_end FROM kilas_ai_subscriptions WHERE user_id=?', (self.owner,))
        if kind == 'capacity':
            return db.query_all('SELECT order_id,total_micro,expires_at FROM kilas_ai_topup_credits WHERE user_id=?', (self.owner,))
        if kind == 'translator':
            return db.query_one('SELECT seconds FROM kilas_audio_balances WHERE user_id=?', (self.owner,))
        return db.query_one('SELECT paid_until FROM finance_entitlements WHERE business_id=?', (self.business,))

    def test_approve_once_activates_each_product_and_replay_never_grants_twice(self):
        for kind in ('subscription','capacity','translator','finance'):
            with self.subTest(kind=kind):
                self.seed(kind)
                response = self.post(kind)
                self.assertEqual(response.status_code, 303)
                self.assertEqual(response.location, '/platform/payments')
                self.assertEqual(self.row(kind)['status'], 'VERIFIED')
                first = self.entitlement(kind)
                self.assertTrue(first)
                self.assertEqual(self.post(kind).status_code, 303)
                self.assertEqual(first, self.entitlement(kind))
        self.assertEqual(self.entitlement('subscription')['plan'], 'PLUS')
        self.assertEqual(self.entitlement('translator')['seconds'], audio_store.PACKS['MINUTE'][0])
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n'], 0)

    def test_reject_each_product_never_activates_and_is_replay_safe(self):
        for kind in ('subscription','capacity','translator','finance'):
            with self.subTest(kind=kind):
                self.seed(kind)
                self.assertEqual(self.post(kind, 'REJECTED').status_code, 303)
                self.assertEqual(self.row(kind)['status'], 'REJECTED')
                self.assertFalse(self.entitlement(kind))
                self.assertEqual(self.post(kind, 'REJECTED').status_code, 303)
                self.assertFalse(self.entitlement(kind))

    def test_conflicting_second_decision_never_reverses_approval(self):
        for kind in ('subscription','capacity','translator','finance'):
            self.seed(kind); self.post(kind)
            first = self.entitlement(kind)
            self.post(kind, 'REJECTED')
            self.assertEqual(self.row(kind)['status'], 'VERIFIED')
            self.assertEqual(first, self.entitlement(kind))

    def test_csrf_required_for_every_product(self):
        for kind in ('subscription','capacity','translator','finance'):
            ident = self.seed(kind)
            response = self.client.post(f'/platform/payments/{kind}/{ident}/review', data={'decision':'VERIFIED'})
            self.assertEqual(response.status_code, 400)
            self.assertFalse(self.entitlement(kind))

    def test_customer_cannot_review_read_queue_or_read_proofs(self):
        for kind in ('subscription','capacity','translator','finance'): self.seed(kind)
        authenticate(self.client, repo.get_user_by_id(self.owner), _csrf_token='test-csrf')
        self.assertEqual(self.client.get('/platform/payments').status_code, 403)
        for kind, ident in self.ids.items():
            self.assertEqual(self.post(kind).status_code, 403)
            self.assertEqual(self.client.get(f'/platform/payments/{kind}/{ident}/proof').status_code, 403)
            self.assertFalse(self.entitlement(kind))

    def test_proofs_return_exact_bytes_to_admin(self):
        for kind in ('subscription','capacity','translator','finance'):
            ident = self.seed(kind)
            response = self.client.get(f'/platform/payments/{kind}/{ident}/proof')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'image/png')
            self.assertEqual(response.data, self.proof)

    def test_invalid_kind_or_id_does_not_mutate(self):
        for route in ('unknown/1', 'translator/99999999', 'finance/99999999', 'subscription/99999999', 'capacity/99999999'):
            self.assertEqual(self.client.get('/platform/payments/'+route+'/proof').status_code, 404)
            response = self.client.post('/platform/payments/'+route+'/review', data={'csrf_token':'test-csrf','decision':'VERIFIED'})
            self.assertIn(response.status_code, (303,400,404))
        self.assertIsNone(self.entitlement('translator'))

    def test_invalid_decision_is_not_treated_as_approval_or_rejection(self):
        for kind in ('subscription','capacity','translator','finance'):
            self.seed(kind)
            before = self.row(kind)['status']
            self.assertIn(self.post(kind, 'approve').status_code, (400,303))
            self.assertEqual(self.row(kind)['status'], before)
            self.assertFalse(self.entitlement(kind))

    def test_finance_business_id_is_resolved_from_bill_not_form(self):
        self.seed('finance')
        other = repo.create_business(self.owner, 'Other synthetic', 'AI_ADMIN')
        self.assertEqual(self.post('finance', business_id=str(other)).status_code, 303)
        self.assertTrue(self.entitlement('finance'))
        self.assertIsNone(db.query_one('SELECT paid_until FROM finance_entitlements WHERE business_id=?', (other,)))

    def test_default_queue_history_product_filters_and_get_are_read_only(self):
        for kind in ('subscription','capacity','translator','finance'): self.seed(kind)
        before = {kind:self.row(kind) for kind in self.ids}
        for kind, ident in self.ids.items():
            response = self.client.get('/platform/payments?product='+kind)
            self.assertEqual(response.status_code, 200)
            self.assertIn(f'/platform/payments/{kind}/{ident}/review', response.text)
            for other, other_id in self.ids.items():
                if other != kind: self.assertNotIn(f'/platform/payments/{other}/{other_id}/review', response.text)
        self.assertEqual(before, {kind:self.row(kind) for kind in self.ids})
        for kind in self.ids: self.post(kind)
        queue = self.client.get('/platform/payments').text
        history = self.client.get('/platform/payments?status=history').text
        for kind, ident in self.ids.items():
            self.assertNotIn(f'/platform/payments/{kind}/{ident}/review', queue)
            self.assertIn(f'/platform/payments/{kind}/{ident}/proof', history)
            self.assertNotIn(f'/platform/payments/{kind}/{ident}/review', history)

    def test_unsubmitted_payments_cannot_be_approved(self):
        for kind in ('capacity','translator','finance'):
            self.seed(kind, with_proof=False)
            first = self.row(kind)['status']
            self.post(kind)
            self.assertEqual(self.row(kind)['status'], first)
            self.assertFalse(self.entitlement(kind))

    def test_product_transactions_rollback_if_entitlement_write_fails(self):
        for kind, statement in (
            ('subscription', 'INSERT INTO kilas_ai_subscriptions'),
            ('capacity', 'INSERT INTO kilas_ai_topup_credits'),
            ('translator', 'UPDATE kilas_audio_orders SET status='),
        ):
            with self.subTest(kind=kind):
                self.seed(kind)
                query = usage._query
                def fail(conn, sql, *args, **kwargs):
                    if sql.startswith(statement):
                        raise RuntimeError('synthetic entitlement failure')
                    return query(conn, sql, *args, **kwargs)
                with patch.object(usage, '_query', side_effect=fail):
                    with self.assertRaises(RuntimeError): self.post(kind)
                self.assertEqual(self.row(kind)['status'], 'UNDER_REVIEW')
                self.assertFalse(self.entitlement(kind))

    def test_concurrent_approve_is_once_for_every_product(self):
        for kind in ('subscription','capacity','translator','finance'):
            with self.subTest(kind=kind):
                ident = self.seed(kind)
                def settle(_):
                    return platform_payments.review(kind, ident, self.admin, 'VERIFIED')
                with ThreadPoolExecutor(max_workers=2) as pool:
                    list(pool.map(settle, range(2)))
                first = self.entitlement(kind)
                self.assertTrue(first)
                self.assertEqual(self.row(kind)['status'], 'VERIFIED')
                self.post(kind)
                self.assertEqual(first, self.entitlement(kind))
                if kind == 'capacity': self.assertEqual(len(first), 1)
                if kind == 'translator': self.assertEqual(first['seconds'], 60)

    def test_queue_pagination_is_stable_and_filters_are_bound(self):
        original = self.seed('translator')
        for index in range(34):
            db.execute("INSERT INTO kilas_audio_orders (user_id,invoice_number,pack,seconds,amount_idr,status,proof_filename,proof_mime_type,proof_content,created_at,updated_at) "
                "SELECT user_id,?,pack,seconds,amount_idr,status,proof_filename,proof_mime_type,proof_content,created_at,updated_at FROM kilas_audio_orders WHERE id=?",
                ('QA-'+uuid4().hex, original))
        email = repo.get_user_by_id(self.owner)['email']
        first = platform_payments.queue('translator', query=email)
        second = platform_payments.queue('translator', query=email, page=2)
        self.assertEqual(first['total'], 35)
        self.assertEqual(len(first['rows']), 30)
        self.assertEqual(len(second['rows']), 5)
        self.assertTrue(first['has_next'])
        self.assertFalse(second['has_next'])
        ids = [row['payment_id'] for row in first['rows']+second['rows']]
        self.assertEqual(len(set(ids)), 35)
        self.assertEqual(platform_payments.queue(query="' OR 1=1 --")['total'], 0)

    def test_admin_translator_console_gets_preserve_every_application_table(self):
        import platform_console
        self.seed('translator')
        self.post('translator')
        second = audio_billing.create(self.owner, 'FIVE')
        audio_billing.proof(self.owner, second, self.upload())
        email = repo.get_user_by_id(self.owner)['email']

        def snapshot():
            # Snapshot complete rows, not just counts: catches status, balance,
            # entitlement, audit and auth mutations anywhere in this synthetic DB.
            if db.BACKEND == 'postgres':
                tables = db.query_all("SELECT table_name AS name FROM information_schema.tables "
                    "WHERE table_schema=current_schema() AND table_type='BASE TABLE'")
            else:
                tables = db.query_all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            def encode(value):
                return bytes(value).hex() if isinstance(value, (bytes, bytearray, memoryview)) else str(value)
            return {table['name']: sorted(json.dumps(row, sort_keys=True, default=encode)
                for row in db.query_all('SELECT * FROM "'+table['name'].replace('"', '""')+'"'))
                for table in tables}

        before = snapshot()
        self.assertGreaterEqual(platform_console.overview()['translator'], 1)
        directory = platform_console.customers(query=email, product='translator')
        self.assertEqual(directory['total'], 1)
        self.assertEqual(directory['rows'][0]['id'], self.owner)
        self.assertEqual(directory['rows'][0]['translator_used'], 1)
        detail = platform_console.ai_customer(self.owner)
        self.assertEqual(detail['audio_seconds'], 60)
        self.assertEqual(len(detail['audio_orders']), 2)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_orders WHERE user_id=?',
                                    (self.owner,))['n'], 2)
        for path in ('/platform/', '/platform/overview', '/platform/translator',
                     '/platform/customers?product=translator', f'/platform/customers/{self.owner}'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn('Translator', response.text)
            if path not in ('/platform/', '/platform/overview'):
                self.assertIn(email, response.text)
        self.assertEqual(before, snapshot())

    def test_finance_transaction_rolls_back_if_audit_fails(self):
        self.seed('finance')
        with patch.object(repo, 'write_audit', side_effect=RuntimeError('synthetic rollback')):
            with self.assertRaises(RuntimeError): self.post('finance')
        self.assertEqual(self.row('finance')['status'], 'REVIEW')
        self.assertFalse(self.entitlement('finance'))


if __name__ == '__main__':
    unittest.main()
