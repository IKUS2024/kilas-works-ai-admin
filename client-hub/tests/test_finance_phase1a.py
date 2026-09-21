from finance_test_clock import closed_period
"""Offline Phase 1A ledger tests. No UI or production integrations."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop('DATABASE_URL', None)
os.environ.pop('ANTHROPIC_API_KEY', None)
import db
import repo
import projects_repo
import finance_service as f


class FinanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db.SQLITE_PATH = self.temp.name + '/finance.db'
        db._local.conn = None
        db.init_schema()
        self.users = [repo.create_user(f'user{i}@example.test', 'unused') for i in range(2)]
        self.biz = [repo.create_business(u, f'Business {i}') for i, u in enumerate(self.users)]
        for b in self.biz:
            f.ensure_finance_defaults(b)
        self.b = self.biz[0]
        self.a = f.list_accounts(self.b)[0]['id']
        self.c = f.list_categories(self.b, 'INCOME')[0]['id']
        self.e = f.list_categories(self.b, 'EXPENSE')[0]['id']

    def tearDown(self):
        if getattr(db._local, 'conn', None):
            db._local.conn.close()
        db._local.conn = None
        self.temp.cleanup()

    def create(self, **changes):
        args = dict(business_id=self.b, direction='INCOME', amount_minor=100,
                    account_id=self.a, category_id=self.c, occurred_on='2026-09-01')
        args.update(changes)
        return f.create_transaction(**args)

    def test_schema_idempotent_preserves_existing_rows(self):
        tx = self.create()
        before = db.query_all('SELECT * FROM businesses ORDER BY id')
        db.init_schema()
        # Also execute the additive migration itself again, independently of migration bookkeeping.
        db.get_connection().executescript((Path(db.__file__).parent / 'migrations/0028_finance_foundation_sqlite.sql').read_text())
        self.assertEqual(before, db.query_all('SELECT * FROM businesses ORDER BY id'))
        self.assertEqual(f.get_transaction(self.b, tx)['amount_minor'], 100)

    def test_defaults_idempotent_and_tenant_scoped(self):
        before = db.query_all('SELECT * FROM audit_log ORDER BY id')
        for b in self.biz * 3:
            f.ensure_finance_defaults(b)
            self.assertEqual(len(f.list_accounts(b)), 1)
            self.assertEqual(len(f.list_categories(b)), 10)
        self.assertEqual(before, db.query_all('SELECT * FROM audit_log ORDER BY id'))
        self.assertEqual(
            [row['name'] for row in f.list_categories(self.b,'EXPENSE')],
            list(f.DEFAULT_CATEGORIES['EXPENSE']))
        utility=next(row for row in f.list_categories(self.b,'EXPENSE') if row['name']=='Utilitas')
        children=f.list_category_children(self.b,utility['id'])
        self.assertEqual(
            [row['name'] for row in children],
            list(f.DEFAULT_CATEGORY_CHILDREN['EXPENSE']['Utilitas']))
        self.assertTrue(all(row['parent_category_id']==utility['id'] for row in children))
        all_expense=f.list_categories(self.b,'EXPENSE',include_children=True)
        self.assertEqual(len(all_expense),len(f.DEFAULT_CATEGORIES['EXPENSE'])+len(children))
        db.execute('UPDATE finance_accounts SET is_active=FALSE, opening_balance_minor=123 WHERE business_id=?', (self.b,))
        f.ensure_finance_defaults(self.b)
        self.assertEqual(f.list_accounts(self.b), [])
        self.assertEqual(f.list_accounts(self.b, True)[0]['opening_balance_minor'], 123)

    def test_default_category_migration_hides_unused_legacy_defaults_without_rewriting_history(self):
        legacy=f.create_category(self.b,'EXPENSE','Transport')
        tx=f.create_transaction(self.b,'EXPENSE',100,self.a,legacy,'2026-09-01')
        db.init_schema()
        all_rows=f.list_categories(self.b,'EXPENSE',True)
        legacy_row=next(row for row in all_rows if row['id']==legacy)
        self.assertFalse(legacy_row['is_active'])
        self.assertEqual(f.get_transaction(self.b,tx)['category_id'],legacy)
        active=[row['name'] for row in f.list_categories(self.b,'EXPENSE')]
        self.assertEqual(active,list(f.DEFAULT_CATEGORIES['EXPENSE']))

    def test_utility_subcategory_selection_is_required_and_resolves_to_child(self):
        utility=next(row for row in f.list_categories(self.b,'EXPENSE') if row['name']=='Utilitas')
        children=f.list_category_children(self.b,utility['id'])
        electricity=next(row for row in children if row['name']=='Listrik')
        with self.assertRaisesRegex(f.FinanceError,'subcategory_required'):
            f.resolve_category_selection(self.b,'EXPENSE',utility['id'])
        resolved=f.resolve_category_selection(
            self.b,'EXPENSE',utility['id'],electricity['id'])
        self.assertEqual(resolved,electricity['id'])
        with self.assertRaisesRegex(f.FinanceError,'subcategory_unavailable'):
            f.resolve_category_selection(
                self.b,'EXPENSE',utility['id'],f.list_categories(self.b,'EXPENSE')[0]['id'])

    def test_account_category_creation_and_validation(self):
        a = f.create_account(self.b, 'Bank', 'BANK', 'idr', 123)
        self.assertEqual(f.list_accounts(self.b)[1]['currency'], 'IDR')
        self.assertIsInstance(a, int)
        c = f.create_category(self.b, 'EXPENSE', 'Office')
        self.assertIn(c, [r['id'] for r in f.list_categories(self.b, 'EXPENSE')])
        for fn in (lambda: f.create_account(self.b, 'Bad', 'INVALID'),
                   lambda: f.create_account(self.b, 'Float', opening_balance_minor=1.5),
                   lambda: f.create_category(self.b, 'INVALID', 'Bad')):
            with self.assertRaises(f.FinanceError): fn()

    def test_readding_hidden_account_and_category_reactivates_without_duplicate(self):
        account = f.create_account(self.b, 'BCA', 'BANK', 'IDR', 123)
        category = f.create_category(self.b, 'EXPENSE', 'Office')
        db.execute('UPDATE finance_accounts SET is_active=FALSE WHERE business_id=? AND id=?', (self.b, account))
        db.execute('UPDATE finance_categories SET is_active=FALSE WHERE business_id=? AND id=?', (self.b, category))
        self.assertEqual(f.create_account(self.b, 'BCA', 'BANK', 'IDR', 999), account)
        self.assertEqual(f.create_category(self.b, 'EXPENSE', 'Office'), category)
        restored = next(a for a in f.list_accounts(self.b) if a['id'] == account)
        self.assertEqual(restored['opening_balance_minor'], 123)
        self.assertTrue(restored['is_active'])
        self.assertTrue(next(c for c in f.list_categories(self.b, 'EXPENSE') if c['id'] == category)['is_active'])
        self.assertEqual(len([a for a in f.list_accounts(self.b, True) if a['name']=='BCA']), 1)
        self.assertEqual(len([c for c in f.list_categories(self.b, 'EXPENSE', True) if c['name']=='Office']), 1)

    def test_create_update_and_audit(self):
        tx = self.create(actor_user_id=self.users[0], source_type='MANUAL', source_ref='external-ref')
        row = f.update_transaction(self.b, tx, amount_minor=300, description=' Updated ', actor_user_id=self.users[0])
        self.assertEqual(row['description'], 'Updated')
        self.assertEqual(row['amount_minor'], 300)
        self.assertEqual(row['created_by_user_id'], self.users[0])
        audit = db.query_all("SELECT * FROM audit_log WHERE action LIKE 'FINANCE_TRANSACTION_%'")
        self.assertEqual(len(audit), 2)
        self.assertNotIn('external-ref', str(audit))
        with self.assertRaises(f.FinanceError): f.update_transaction(self.b, tx, status='VOID')

    def test_cross_tenant_read_update_void(self):
        tx = self.create()
        other = self.biz[1]
        self.assertIsNone(f.get_transaction(other, tx))
        self.assertEqual(f.list_transactions(other), [])
        for fn in (lambda: f.update_transaction(other, tx, amount_minor=1), lambda: f.void_transaction(other, tx)):
            with self.assertRaises(f.FinanceError): fn()
        self.assertEqual(f.get_transaction(self.b, tx)['amount_minor'], 100)

    def test_actor_membership_checks(self):
        for fn in (lambda: f.list_accounts(self.b, actor_user_id=self.users[1]),
                   lambda: f.list_categories(self.b, actor_user_id=self.users[1]),
                   lambda: f.list_transactions(self.b, actor_user_id=self.users[1]),
                   lambda: self.create(actor_user_id=self.users[1]),
                   lambda: f.ensure_finance_defaults(self.b, actor_user_id=self.users[1])):
            with self.assertRaises(f.FinanceError): fn()
        self.assertEqual(len(f.list_accounts(self.b, actor_user_id=self.users[0])), 1)

    def test_cross_account_category_project_rejected_on_create_and_update(self):
        other = self.biz[1]
        project = projects_repo.create_fixed_price_project(other, dict(category='CONTENT', catalog_key='content_basic', name='Test', price_amount=123), self.users[1], draft=True)
        changes = [dict(account_id=f.list_accounts(other)[0]['id']),
                   dict(category_id=f.list_categories(other, 'INCOME')[0]['id']), dict(project_id=project)]
        tx = self.create()
        for change in changes:
            with self.assertRaises(f.FinanceError): self.create(**change)
            with self.assertRaises(f.FinanceError): f.update_transaction(self.b, tx, **change)
        self.assertEqual(db.query_one('SELECT final_price FROM projects WHERE id=?', (project,))['final_price'], 123)

    def test_direction_and_inactive_references(self):
        with self.assertRaises(f.FinanceError): self.create(category_id=self.e)
        db.execute('UPDATE finance_categories SET is_active=FALSE WHERE business_id=? AND id=?', (self.b, self.c))
        with self.assertRaises(f.FinanceError): self.create()

    def test_amount_rejects_nonpositive_float_bool_string_overflow(self):
        for value in (0, -1, 1.1, True, '100', None, 2**63):
            with self.subTest(value=value), self.assertRaises(f.FinanceError): self.create(amount_minor=value)

    def test_integer_precision_and_summary_overflow(self):
        value = 2**63-1
        tx = self.create(amount_minor=value)
        self.create(amount_minor=value)
        self.assertEqual(f.get_transaction(self.b, tx)['amount_minor'], value)
        self.assertEqual(db.query_one('SELECT typeof(amount_minor) AS t FROM finance_transactions WHERE id=?', (tx,))['t'], 'integer')
        self.assertEqual(f.get_finance_summary(self.b, '2026-09-01', '2026-09-01')['total_income_minor'], value*2)

    def test_void_preserves_history_and_is_idempotent(self):
        tx = self.create()
        first = f.void_transaction(self.b, tx, self.users[0])
        self.assertEqual(first['status'], 'VOID')
        self.assertEqual(first, f.void_transaction(self.b, tx, self.users[0]))
        self.assertEqual(len(f.list_transactions(self.b)), 1)
        self.assertEqual(f.get_finance_summary(self.b, '2026-09-01', '2026-09-30')['net_cashflow_minor'], 0)
        with self.assertRaises(f.FinanceError): f.update_transaction(self.b, tx, amount_minor=200)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM audit_log WHERE action='FINANCE_TRANSACTION_VOIDED'")['n'], 1)

    @closed_period
    def test_summary_inclusive_dates_currency_and_tenant(self):
        self.create(amount_minor=100, occurred_on='2026-09-01')
        self.create(amount_minor=40, direction='EXPENSE', category_id=self.e, occurred_on='2026-09-30')
        self.create(amount_minor=999, occurred_on='2026-10-01')
        usd = f.create_account(self.b, 'USD', currency='USD')
        self.create(amount_minor=555, account_id=usd, currency='usd')
        self.assertEqual(f.get_finance_summary(self.b, '2026-09-01', '2026-09-30'), dict(currency='IDR', total_income_minor=100, total_expense_minor=40, net_cashflow_minor=60))
        self.assertEqual(f.get_finance_summary(self.biz[1], '2026-09-01', '2026-09-30')['net_cashflow_minor'], 0)
        with self.assertRaises(f.FinanceError): self.create(currency='USD')
        self.assertEqual(f.get_finance_summaries(self.b,'2026-09-01','2026-09-30')[1]['currency'],'USD')
        self.assertEqual(f.get_finance_summaries(self.b,'2026-09-01','2026-09-30')[1]['total_income_minor'],555)
        balances=f.get_account_balance_report(self.b,'2026-09-30')
        self.assertEqual(next(a for a in balances if a['currency']=='USD')['balance_minor'],555)
        with self.assertRaisesRegex(f.FinanceError,'unsupported_currency'):f.create_account(self.b,'Crypto',currency='BTC')

    def test_list_filters_dates_and_validation(self):
        self.create(occurred_on='2026-09-03')
        second = self.create(occurred_on='2026-09-04')
        self.assertEqual(f.list_transactions(self.b, limit=1)[0]['id'], second)
        self.assertEqual(len(f.list_transactions(self.b, end_date='2026-09-03')), 1)
        for value in ('2026-02-30', '20260901', 'yesterday'):
            with self.assertRaises(f.FinanceError): self.create(occurred_on=value)
        with self.assertRaises(f.FinanceError): f.get_finance_summary(self.b, '2026-10-01', '2026-09-01')

    def test_audit_failure_rolls_back_transaction(self):
        with patch.object(repo, 'write_audit', side_effect=RuntimeError('test audit failure')):
            with self.assertRaises(RuntimeError): self.create()
        self.assertEqual(f.list_transactions(self.b), [])
        self.create()  # transaction state recovered

    def test_sqlite_constraints_prevent_cross_tenant_account_even_without_service(self):
        tx = self.create()
        with self.assertRaises(Exception):
            db.execute('UPDATE finance_transactions SET account_id=? WHERE business_id=? AND id=?', (f.list_accounts(self.biz[1])[0]['id'], self.b, tx))
        self.assertEqual(f.get_transaction(self.b, tx)['account_id'], self.a)


if __name__ == '__main__':
    unittest.main()
