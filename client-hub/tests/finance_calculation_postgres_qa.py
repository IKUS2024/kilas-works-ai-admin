"""Native calculation parity; imports the existing strict loopback-only QA guard."""
import unittest
import finance_edit_postgres_qa as fixture
import finance_expense_entries as expenses

f, db, branches = fixture.f, fixture.db, fixture.branches


class NativeCalculationTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativeEditTests.setUpClass.__func__)
    setUp = fixture.NativeEditTests.setUp

    def test_category_totals_beyond_bigint_remain_python_integers(self):
        with branches.scope(self.bid, self.branch, self.uid):
            for value in (2**63 - 1, 17):
                f.create_transaction(self.bid, 'EXPENSE', value, self.a, self.exp, '2026-09-10')
            for rows in (f.get_expense_category_totals(self.bid, '2026-09-01', '2026-09-30'),
                         f.get_entry_summary(self.bid, '2026-09-01', '2026-09-30', 'EXPENSE',
                                             group_parents=True, actor_user_id=self.uid)):
                self.assertEqual(rows[0]['amount_minor'], 2**63 + 16)
                self.assertIs(type(rows[0]['amount_minor']), int)
            cash = f.get_cash_totals(self.bid, category_id=self.exp, actor_user_id=self.uid)
            self.assertEqual(cash[0]['total_expense_minor'], 2**63 + 16)

    def test_split_summaries_filters_parent_count_and_total_balance(self):
        with branches.scope(self.bid, self.branch, self.uid):
            parent = f.create_category(self.bid, 'EXPENSE', 'Native parent')
            children = [f.create_category(self.bid, 'EXPENSE', name, parent_category_id=parent)
                        for name in ('Native first', 'Native second')]
            splits = [dict(category_id=children[0], amount_minor=6001),
                      dict(category_id=children[1], amount_minor=3999)]
            tx = expenses.save(self.bid, self.uid, amount_minor=10000, currency='IDR',
                account_id=self.a, category_id=children[0], occurred_on='2026-09-10',
                description='Native 100% split', splits=splits, submission_key='a'*32)
            grouped = f.get_entry_summary(self.bid, '2026-09-01', '2026-09-30', 'EXPENSE',
                group_parents=True, search='100%', actor_user_id=self.uid)
            self.assertEqual([(r['summary_key'], r['amount_minor'], r['transaction_count']) for r in grouped],
                             [(parent, 10000, 1)])
            selected = f.get_entry_summary(self.bid, '2026-09-01', '2026-09-30', 'EXPENSE',
                category_ids=[children[1]], account_id=self.a, actor_user_id=self.uid)
            self.assertEqual(selected[0]['amount_minor'], 3999)
            cash = f.get_cash_totals(self.bid, category_id=children[1], actor_user_id=self.uid)
            self.assertEqual(cash[0]['total_expense_minor'], 3999)
            for dimension in (None, 'account', 'customer', 'project', 'branch'):
                cash = f.get_cash_totals(self.bid, group_by=dimension, actor_user_id=self.uid)
                self.assertEqual(sum(r['total_expense_minor'] for r in cash), 10000)
                self.assertEqual(sum(r['transaction_count'] for r in cash), 1)
            balances = {r['id']: r for r in f.get_account_balance_report(self.bid, '2026-09-30', self.uid)}
            self.assertEqual(balances[self.a]['balance_minor'], -10000)
            f.void_transaction(self.bid, tx, actor_user_id=self.uid)
            self.assertEqual(f.get_cash_totals(self.bid, category_id=children[1], actor_user_id=self.uid), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
