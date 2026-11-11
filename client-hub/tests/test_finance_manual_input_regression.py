"""Disposable manual-entry regressions; no production data or external IO."""
from datetime import date
from unittest.mock import patch
import unittest
import test_finance_approved_revisions as fixture
import db, finance_service as finance, finance_branches as branches


class ManualInputRegressionTests(unittest.TestCase):
    setUp = fixture.ApprovedFinanceTests.setUp

    def post(self, branch, **values):
        return self.client.post(self.url + '/transactions?branch_id=' + str(branch), data=values)

    def category_fields(self, branch):
        with branches.scope(self.b, branch, self.uid):
            categories = finance.list_categories(self.b, 'EXPENSE', include_children=True, actor_user_id=self.uid)
        child = next(c for c in categories if c.get('parent_category_id') and c['is_active'])
        return dict(category_id=child['parent_category_id'], subcategory_id=child['id'])

    def test_bank_add_then_income_and_expense_in_both_workspaces(self):
        for branch in (self.branch, self.personal):
            name = 'Synthetic input bank ' + str(branch)
            response = self.client.post(self.url + '/accounts?branch_id=' + str(branch), data=dict(
                name=name, account_type='BANK', currency='IDR', opening_balance='1.234,56', return_view='accounts'))
            self.assertEqual(response.status_code, 303)
            account = db.query_one('SELECT * FROM finance_accounts WHERE name=?', (name,))
            self.assertEqual((account['branch_id'], account['opening_balance_minor']), (branch, 123456))
            for direction in ('INCOME', 'EXPENSE'):
                values = dict(direction=direction, account_id=account['id'], amount='12,34',
                              occurred_on='2026-09-10', description='Synthetic manual input')
                if direction == 'EXPENSE':
                    values.update(self.category_fields(branch), submission_key=str(branch).zfill(32))
                self.assertEqual(self.post(branch, **values).status_code, 303)
            rows = db.query_all('SELECT direction,amount_minor,branch_id FROM finance_transactions WHERE account_id=? ORDER BY id', (account['id'],))
            self.assertEqual([(r['direction'], r['amount_minor'], r['branch_id']) for r in rows],
                             [('INCOME', 1234, branch), ('EXPENSE', 1234, branch)])

    def test_future_and_invalid_dates_rejected_with_no_ledger_write(self):
        with patch.object(finance, 'business_today', return_value=date(2026, 11, 11)):
            for occurred_on in ('2026-11-12', '2026-02-30', 'not-a-date'):
                for direction in ('INCOME', 'EXPENSE'):
                    values = dict(direction=direction, account_id=self.a, amount='12.34', occurred_on=occurred_on,
                                  description='Synthetic rejected date')
                    if direction == 'EXPENSE':
                        values.update(self.category_fields(self.branch), submission_key='d'*32)
                    self.assertEqual(self.post(self.branch, **values).status_code, 303)
                    self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n'], 0)
        with self.client.session_transaction() as state:
            self.assertTrue(any(kind == 'error' for kind, _ in state['_flashes']))

    def test_cross_workspace_accounts_and_foreign_categories_rejected(self):
        values = dict(direction='EXPENSE', account_id=self.a, amount='12.34', occurred_on='2026-09-10', submission_key='e'*32)
        values.update(self.category_fields(self.branch))
        for branch, overrides in ((self.branch, {'account_id': self.pa}), (self.personal, {}),
                                  (self.branch, {'category_id': finance.list_categories(self.other, 'EXPENSE')[0]['id'], 'subcategory_id': ''}),
                                  (self.branch, {'category_id': self.cat, 'subcategory_id': ''})):
            self.assertEqual(self.post(branch, **dict(values, **overrides)).status_code, 303)
            self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n'], 0)

    def test_missing_required_subcategory_is_rejected(self):
        fields = self.category_fields(self.branch)
        self.assertEqual(self.post(self.branch, direction='EXPENSE', account_id=self.a, amount='12.34',
                         occurred_on='2026-09-10', submission_key='f'*32, category_id=fields['category_id']).status_code, 303)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n'], 0)


if __name__ == '__main__':
    unittest.main()
