"""Native currency/archived-account invariants with strict disposable-DB guard."""
import unittest
import finance_edit_postgres_qa as fixture
import finance_installments as plans

f,db,branches=fixture.f,fixture.db,fixture.branches


class NativeInvariantTests(unittest.TestCase):
    setUpClass=classmethod(fixture.NativeEditTests.setUpClass.__func__)
    setUp=fixture.NativeEditTests.setUp

    def snapshot(self):
        return {t:db.query_all('SELECT * FROM '+t+' WHERE business_id=? ORDER BY id',(self.bid,))
                for t in ('finance_accounts','finance_transactions','finance_transaction_revisions',
                          'finance_internal_transfers','finance_recurring_expenses','finance_installment_plans',
                          'finance_workspace_corrections','audit_log')}

    def test_installment_currency_lock_and_same_currency_edit(self):
        with branches.scope(self.bid,self.branch,self.uid):
            ident=plans.create(self.bid,self.uid,amount_minor=10000,currency='IDR',account_id=self.a,
                category_id=self.exp,purchase_on='2025-08-10',submission_key='b'*32,duration='2',
                unit='MONTHS',frequency='MONTHLY',first_date='2025-09-30')
            item=db.query_one('SELECT * FROM finance_installment_items WHERE plan_id=? ORDER BY sequence',(ident,))
            rule=f.get_recurring_expense(self.bid,item['recurring_id'],self.uid)
            usd=f.create_account(self.bid,'Dollar','BANK',currency='USD',actor_user_id=self.uid)
            values=dict(name=rule['name'],amount_minor=5000,account_id=usd,category_id=self.exp,
                cadence='MONTHLY',next_due_on=rule['next_due_on'],end_on=rule['end_on'],actor_user_id=self.uid)
            before=self.snapshot()
            with self.assertRaisesRegex(f.FinanceError,'installment_payment_locked'):
                f.update_recurring_expense(self.bid,rule['id'],**values)
            self.assertEqual(self.snapshot(),before)
            values['account_id']=self.target
            f.update_recurring_expense(self.bid,rule['id'],**values)
            self.assertEqual(f.get_recurring_expense(self.bid,rule['id'],self.uid)['currency'],'IDR')

    def test_archived_transfer_reversal_is_atomic(self):
        with branches.scope(self.bid,self.branch,self.uid):
            f.update_account_opening_balance(self.bid,self.a,10000,actor_user_id=self.uid)
            ident=f.record_internal_transfer(self.bid,self.a,self.target,10000,'2026-09-10',actor_user_id=self.uid,idempotency_key='f'*32)
            branches.update_record(self.bid,'account',self.a,deactivate=True,actor_user_id=self.uid)
            before=self.snapshot()
            with self.assertRaisesRegex(f.FinanceError,'account_unavailable'):
                f.void_internal_transfer(self.bid,ident,actor_user_id=self.uid)
            self.assertEqual(self.snapshot(),before)

    def test_archived_expense_void_and_reassignment_are_atomic(self):
        with branches.scope(self.bid,self.branch,self.uid):
            f.update_account_opening_balance(self.bid,self.a,10000,actor_user_id=self.uid)
            ident=f.create_transaction(self.bid,'EXPENSE',10000,self.a,self.exp,'2026-09-10',actor_user_id=self.uid)
            branches.update_record(self.bid,'account',self.a,deactivate=True,actor_user_id=self.uid)
            before=self.snapshot()
            for action in (lambda:f.void_transaction(self.bid,ident,actor_user_id=self.uid),
                           lambda:f.update_transaction(self.bid,ident,account_id=self.target,actor_user_id=self.uid)):
                with self.assertRaisesRegex(f.FinanceError,'account_unavailable'):action()
                self.assertEqual(self.snapshot(),before)

    def test_workspace_move_rejects_inactive_original_account_before_mapping(self):
        target=branches.ensure_personal(self.bid,self.uid)
        with branches.scope(self.bid,self.branch,self.uid):
            f.update_account_opening_balance(self.bid,self.a,10000,actor_user_id=self.uid)
            ident=f.create_transaction(self.bid,'EXPENSE',10000,self.a,self.exp,'2026-09-10',actor_user_id=self.uid)
            branches.update_record(self.bid,'account',self.a,deactivate=True,actor_user_id=self.uid)
            before=self.snapshot()
            with self.assertRaisesRegex(f.FinanceError,'account_unavailable'):
                f.move_transaction_workspace(self.bid,ident,target,actor_user_id=self.uid)
            self.assertEqual(self.snapshot(),before)


if __name__=='__main__':unittest.main(verbosity=2)
