"""Regression for disposable branch deletion with the current workspace schema."""
import unittest
from unittest.mock import patch
import test_finance_branches as prior
import db
import repo
import finance_service as finance
import finance_branches as branches


class BranchDeleteRecoveryTests(unittest.TestCase):
    setUp = prior.BranchTests.setUp
    scope = prior.BranchTests.scope
    test_empty_branch_deletion = prior.BranchTests.test_delete_empty_branch_removes_it_instead_of_leaving_nonactive_choice
    test_last_active_branch = prior.BranchTests.test_branch_routes_and_last_active_guard

    def test_budget_and_payee_history_archive_instead_of_delete(self):
        for kind in ('budget', 'payee'):
            with self.subTest(kind=kind):
                ident = branches.create_branch(self.b, kind, self.uid)
                with self.scope(ident):
                    if kind == 'budget':
                        record = finance.set_monthly_budget(self.b, '2026-09', self.expense['id'], 10000, actor_user_id=self.uid)
                    else:
                        record = finance.create_payee(self.b, 'Supplier', actor_user_id=self.uid)
                table = 'finance_budgets' if kind == 'budget' else 'finance_payees'
                before = db.query_one('SELECT * FROM ' + table + ' WHERE id=?', (record,))
                with self.scope(self.ba):
                    branches.update_record(self.b, 'branch', ident, deactivate=True, actor_user_id=self.uid)
                self.assertFalse(branches.get(self.b, ident)['is_active'])
                self.assertEqual(db.query_one('SELECT * FROM ' + table + ' WHERE id=?', (record,)), before)
                self.assertIsNotNone(db.query_one('SELECT * FROM finance_branch_workspaces WHERE business_id=? AND branch_id=?', (self.b, ident)))

    def test_delete_audit_failure_rolls_back_accounts_workspace_and_branch(self):
        ident = branches.create_branch(self.b, 'Rollback', self.uid)
        before = list(db.get_connection().iterdump())
        with self.scope(self.ba), patch.object(repo, 'write_audit', side_effect=RuntimeError('audit failure')):
            with self.assertRaisesRegex(RuntimeError, 'audit failure'):
                branches.update_record(self.b, 'branch', ident, deactivate=True, actor_user_id=self.uid)
        self.assertEqual(list(db.get_connection().iterdump()), before)


if __name__ == '__main__':
    unittest.main()
