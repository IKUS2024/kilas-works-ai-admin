"""Calculation regressions against disposable ledgers; external IO is mocked."""
from datetime import date
from decimal import Decimal
import unittest
from unittest.mock import patch

from flask import template_rendered
import test_finance_approved_revisions as fixture
import db
import finance_branches as branches
import finance_dashboard_view as dashboard
import finance_expense_entries as expense_entries
import finance_service as finance


class CalculationAuditTests(unittest.TestCase):
    setUp = fixture.ApprovedFinanceTests.setUp

    def test_category_aggregates_remain_exact_beyond_signed_bigint(self):
        with branches.scope(self.b, self.branch, self.uid):
            category = finance.list_categories(self.b, 'EXPENSE')[0]['id']
            for direction, category_id in [('EXPENSE', category), ('INCOME', self.cat)]:
                for amount in (2**63 - 1, 17):
                    finance.create_transaction(self.b, direction, amount, self.a,
                                               category_id, '2026-09-10')
                rows = finance.get_category_totals(self.b, '2026-09-01', '2026-09-30',
                                                  direction, account_id=self.a)
                self.assertEqual(rows[0]['amount_minor'], 2**63 + 16)
                self.assertIs(type(rows[0]['amount_minor']), int)
                self.assertEqual(rows[0]['transaction_count'], 2)
            expenses = finance.get_expense_category_totals(self.b, '2026-09-01', '2026-09-30')
            self.assertEqual(expenses[0]['amount_minor'], 2**63 + 16)

    def test_postgres_category_numeric_aggregate_is_normalized_to_integer(self):
        with branches.scope(self.b, self.branch, self.uid), \
                patch.object(finance, '_scope'), patch.object(branches, 'predicate', return_value=''), \
                patch.object(db, 'BACKEND', 'postgres'), \
                patch.object(db, 'query_all', return_value=[dict(category_id=1, currency='IDR',
                    amount_minor=Decimal(2**63 + 16), transaction_count=2)]) as query:
            for rows in (finance.get_category_totals(self.b, '2026-09-01', '2026-09-30', 'EXPENSE'),
                         finance.get_expense_category_totals(self.b, '2026-09-01', '2026-09-30')):
                self.assertEqual(rows[0]['amount_minor'], 2**63 + 16)
                self.assertIs(type(rows[0]['amount_minor']), int)
            self.assertIn('SUM(amount_minor)', query.call_args.args[0])

    def trend(self, values, rates):
        with branches.scope(self.b, self.branch, self.uid):
            usd = finance.create_account(self.b, 'Synthetic dollar', currency='USD')
            expense = finance.list_categories(self.b, 'EXPENSE')[0]['id']
            for day, direction, amount in values:
                finance.create_transaction(self.b, direction, amount, usd,
                    self.cat if direction == 'INCOME' else expense, day, currency='USD')
            return dashboard.build(self.b, self.uid, '2026-09', date(2026, 9, 30),
                'IDR', rates, lambda *args: [], trend_months=2)

    def test_chart_range_converts_native_total_once_across_months(self):
        result = self.trend([('2026-08-01', 'INCOME', 1), ('2026-09-01', 'INCOME', 1)],
                            {'rates': {'IDR': '1', 'USD': '0.25'}})
        self.assertEqual([r['income_minor'] for r in result['trend']], [0, 0])
        self.assertEqual(result['income_display'], 'Rp0,01')
        self.assertEqual(result['net_minor'], 1)
        self.assertFalse(result['chart_empty'])

    def test_chart_net_converts_native_net_before_rounding(self):
        result = self.trend([('2026-09-01', 'INCOME', 2), ('2026-09-02', 'EXPENSE', 1)],
                            {'rates': {'IDR': '1', 'USD': '0.4'}})
        self.assertEqual(result['income_display'], 'Rp0,01')
        self.assertEqual(result['expense_display'], 'Rp0,00')
        self.assertEqual(result['trend'][-1]['net_minor'], 0)
        self.assertEqual(result['net_minor'], 0)

    def test_chart_rounding_with_realistic_usd_idr_rate(self):
        result = self.trend([('2026-08-01', 'INCOME', 1), ('2026-09-01', 'INCOME', 1)],
                            {'rates': {'IDR': '1', 'USD': '15750.25'}})
        self.assertEqual([r['income_minor'] for r in result['trend']], [15750, 15750])
        self.assertEqual(result['income_display'], 'Rp315,01')
        self.assertEqual(result['net_minor'], 31501)

    def test_missing_fx_keeps_chart_unavailable_even_when_native_net_is_zero(self):
        result = self.trend([('2026-09-01', 'INCOME', 1), ('2026-09-02', 'EXPENSE', 1)],
                            {'rates': {'IDR': '1'}})
        # Fixture snapshot also must be unavailable (never call a real FX provider).
        # The existing fixture returns USD, so test the build with that provider off.
        with patch('finance_fx.snapshot', return_value={'rates': {'IDR': '1'}}), \
                branches.scope(self.b, self.branch, self.uid):
            result = dashboard.build(self.b, self.uid, '2026-09', date(2026, 9, 30),
                'IDR', {'rates': {'IDR': '1'}}, lambda *args: [], trend_months=2)
        self.assertFalse(result['chart_valid'])
        self.assertEqual(result['income_display'], 'Kurs belum lengkap')
        self.assertEqual(result['net_minor'], 0)

    def test_budget_fetches_fx_for_expenses_on_inactive_accounts(self):
        with branches.scope(self.b, self.branch, self.uid):
            account = finance.create_account(self.b, 'Retired USD', currency='USD')
            category = finance.list_categories(self.b, 'EXPENSE')[0]['id']
            finance.create_transaction(self.b, 'EXPENSE', 100, account, category,
                                       '2026-09-10', currency='USD')
            db.execute('UPDATE finance_accounts SET is_active=FALSE WHERE id=?', (account,))
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        def snapshot(codes):
            return {'rates': {code: '15000' if code == 'USD' else '1' for code in codes}}
        with patch('finance_fx.snapshot', side_effect=snapshot), \
                template_rendered.connected_to(capture, fixture.app):
            response = self.client.get(self.url + '/budget', query_string={
                'branch_id': self.branch, 'month': '2026-09'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(contexts[-1]['total_spent_display'], 'Rp15.000,00')

    def test_budget_totals_include_retired_category_history(self):
        with branches.scope(self.b, self.branch, self.uid):
            category = finance.create_category(self.b, 'EXPENSE', 'Synthetic retired category')
            finance.set_monthly_budget(self.b, '2026-09', category, 10000, actor_user_id=self.uid)
            finance.create_transaction(self.b, 'EXPENSE', 2500, self.a, category, '2026-09-10')
            finance.update_category_workspace_setting(self.b, category, deactivate=True,
                                                     actor_user_id=self.uid)
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, fixture.app):
            response = self.client.get(self.url + '/budget', query_string={
                'branch_id': self.branch, 'month': '2026-09'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(contexts[-1]['total_budget_display'], 'Rp100,00')
        self.assertEqual(contexts[-1]['total_spent_display'], 'Rp25,00')
        self.assertEqual(contexts[-1]['remaining_display'], 'Rp75,00')

    def split_expense(self):
        parent = finance.create_category(self.b, 'EXPENSE', 'Synthetic parent')
        first = finance.create_category(self.b, 'EXPENSE', 'Synthetic first', parent_category_id=parent)
        second = finance.create_category(self.b, 'EXPENSE', 'Synthetic second', parent_category_id=parent)
        other = finance.create_category(self.b, 'EXPENSE', 'Synthetic other')
        parts = [dict(category_id=first, amount_minor=6000),
                 dict(category_id=second, amount_minor=3000),
                 dict(category_id=other, amount_minor=1000)]
        tx = expense_entries.save(self.b, self.uid, amount_minor=10000, currency='IDR',
            account_id=self.a, category_id=first, occurred_on='2026-09-10',
            description='Synthetic 100% allocation', splits=parts, submission_key='d'*32)
        return parent, first, second, other, tx

    def entry(self, **changes):
        options = dict(actor_user_id=self.uid)
        options.update(changes)
        return finance.get_entry_summary(self.b, '2026-09-01', '2026-09-30', 'EXPENSE', **options)

    def test_entry_splits_parent_counts_secondary_filters_and_http_display(self):
        with branches.scope(self.b, self.branch, self.uid):
            parent, first, second, other, tx = self.split_expense()
            rows = {r['summary_key']: r for r in self.entry()}
            self.assertEqual({k: r['amount_minor'] for k, r in rows.items()},
                             {first: 6000, second: 3000, other: 1000})
            grouped = {r['summary_key']: r for r in self.entry(group_parents=True)}
            self.assertEqual(grouped[parent]['amount_minor'], 9000)
            self.assertEqual(grouped[parent]['transaction_count'], 1)
            self.assertEqual(grouped[other]['transaction_count'], 1)
            selected = self.entry(category_ids=[second], account_id=self.a, search='100%')
            self.assertEqual(selected[0]['amount_minor'], 3000)
            self.assertEqual(self.entry(category_ids=[]), [])
            self.assertEqual(self.entry(account_id=self.dest), [])
            self.assertEqual(self.entry(search='100_'), [])
            self.assertEqual(finance.get_entry_summary(self.b, '2026-08-01', '2026-08-31',
                             'EXPENSE', actor_user_id=self.uid), [])
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, fixture.app):
            response = self.client.get(self.url, query_string=dict(branch_id=self.branch,
                month='2026-09', view='transactions', direction='EXPENSE'))
        self.assertEqual(response.status_code, 200)
        rows = {r['category_id']: r for r in contexts[-1]['ledger_category_rows']}
        self.assertEqual(rows[parent]['display_amount'], 'Rp90,00')
        self.assertEqual(rows[parent]['transaction_count'], 1)
        with branches.scope(self.b, self.personal, self.uid):
            self.assertEqual(self.entry(), [])
        with branches.scope(self.b, self.branch, self.uid):
            finance.void_transaction(self.b, tx, actor_user_id=self.uid)
            self.assertEqual(self.entry(), [])

    def test_cash_category_allocations_do_not_multiply_other_dimensions(self):
        with branches.scope(self.b, self.branch, self.uid):
            parent, first, second, other, tx = self.split_expense()
            finance.create_transaction(self.b, 'INCOME', 20000, self.a, self.cat, '2026-09-10')
            finance.create_transaction(self.b, 'EXPENSE', 2000, self.a, other, '2026-09-10')
            rows = finance.get_cash_totals(self.b, group_by='category', actor_user_id=self.uid)
            expenses = {r['entity_id']: r['total_expense_minor'] for r in rows if r['total_expense_minor']}
            self.assertEqual(expenses, {first: 6000, second: 3000, other: 3000})
            filtered = finance.get_cash_totals(self.b, category_id=second, account_id=self.a,
                                              actor_user_id=self.uid)
            self.assertEqual(filtered[0]['total_expense_minor'], 3000)
            self.assertEqual(filtered[0]['transaction_count'], 1)
            for dimension in (None, 'account', 'customer', 'project', 'branch'):
                rows = finance.get_cash_totals(self.b, group_by=dimension, actor_user_id=self.uid)
                self.assertEqual(sum(r['total_income_minor'] for r in rows), 20000)
                self.assertEqual(sum(r['total_expense_minor'] for r in rows), 12000)
                self.assertEqual(sum(r['transaction_count'] for r in rows), 3)
            self.assertEqual(finance.get_cash_totals(self.b, category_id=second,
                account_id=self.dest, actor_user_id=self.uid), [])
            self.assertEqual(finance.get_cash_totals(self.b, '2026-08-01', '2026-08-31',
                category_id=second, actor_user_id=self.uid), [])

    def test_personal_income_source_summary_remains_integer_and_unsplit(self):
        with branches.scope(self.b, self.personal, self.uid):
            category = finance.list_categories(self.b, 'INCOME')[0]['id']
            for description, amount in [('Salary', 123), ('Salary', 456), (None, 1)]:
                finance.create_transaction(self.b, 'INCOME', amount, self.pa, category,
                                           '2026-09-10', description=description)
            rows = finance.get_entry_summary(self.b, '2026-09-01', '2026-09-30', 'INCOME',
                sources=True, group_parents=True, actor_user_id=self.uid)
            self.assertEqual({r['summary_key']: (r['amount_minor'], r['transaction_count']) for r in rows},
                             {'Salary': (579, 2), 'Pemasukan': (1, 1)})


if __name__ == '__main__':
    unittest.main()
