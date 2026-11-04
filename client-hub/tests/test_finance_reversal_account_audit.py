"""Reversals must not restore hidden balances to zeroed archived accounts."""
import unittest
import test_finance_approved_revisions as fixture
import finance_service as f
import finance_branches as branches
import db


class ReversalAccountTests(unittest.TestCase):
    setUp=fixture.ApprovedFinanceTests.setUp

    def test_transfer_void_requires_active_accounts_and_is_atomic(self):
        with branches.scope(self.b,self.branch,self.uid):
            f.update_account_opening_balance(self.b,self.a,10000,actor_user_id=self.uid)
            ident=f.record_internal_transfer(self.b,self.a,self.dest,10000,'2026-09-10',actor_user_id=self.uid,idempotency_key='f'*32)
            branches.update_record(self.b,'account',self.a,deactivate=True,actor_user_id=self.uid)
            before=list(db.get_connection().iterdump())
            with self.assertRaisesRegex(f.FinanceError,'account_unavailable'):
                f.void_internal_transfer(self.b,ident,actor_user_id=self.uid)
            self.assertEqual(list(db.get_connection().iterdump()),before)
            self.assertEqual(f.create_account(self.b,'Kas','CASH',actor_user_id=self.uid),self.a)
            f.void_internal_transfer(self.b,ident,actor_user_id=self.uid)
            self.assertEqual(sum(r['balance_minor'] for r in f.get_balance_totals_by_currency(self.b,'2026-09-30',self.uid)),30000)

    def test_expense_void_requires_active_account_and_is_atomic(self):
        with branches.scope(self.b,self.branch,self.uid):
            f.update_account_opening_balance(self.b,self.a,10000,actor_user_id=self.uid)
            category=f.list_categories(self.b,'EXPENSE')[0]['id']
            ident=f.create_transaction(self.b,'EXPENSE',10000,self.a,category,'2026-09-10',actor_user_id=self.uid)
            branches.update_record(self.b,'account',self.a,deactivate=True,actor_user_id=self.uid)
            before=list(db.get_connection().iterdump())
            with self.assertRaisesRegex(f.FinanceError,'account_unavailable'):
                f.void_transaction(self.b,ident,actor_user_id=self.uid)
            self.assertEqual(list(db.get_connection().iterdump()),before)
            self.assertEqual(f.create_account(self.b,'Kas','CASH',actor_user_id=self.uid),self.a)
            f.void_transaction(self.b,ident,actor_user_id=self.uid)
            self.assertEqual(sum(r['balance_minor'] for r in f.get_balance_totals_by_currency(self.b,'2026-09-30',self.uid)),30000)

    def test_reassigning_expense_cannot_restore_hidden_balance(self):
        with branches.scope(self.b,self.branch,self.uid):
            f.update_account_opening_balance(self.b,self.a,10000,actor_user_id=self.uid)
            category=f.list_categories(self.b,'EXPENSE')[0]['id']
            ident=f.create_transaction(self.b,'EXPENSE',10000,self.a,category,'2026-09-10',actor_user_id=self.uid)
            branches.update_record(self.b,'account',self.a,deactivate=True,actor_user_id=self.uid)
            before=list(db.get_connection().iterdump())
            with self.assertRaisesRegex(f.FinanceError,'account_unavailable'):
                f.update_transaction(self.b,ident,account_id=self.dest,actor_user_id=self.uid)
            self.assertEqual(list(db.get_connection().iterdump()),before)

    def test_exchange_void_and_edit_cannot_restore_hidden_currency_balance(self):
        with branches.scope(self.b,self.branch,self.uid):
            f.update_account_opening_balance(self.b,self.a,10000,actor_user_id=self.uid)
            usd=f.create_account(self.b,'Dollar','BANK',currency='USD',actor_user_id=self.uid)
            ident=f.record_currency_exchange(self.b,self.a,usd,10000,100,'2026-09-10',actor_user_id=self.uid)
            branches.update_record(self.b,'account',self.a,deactivate=True,actor_user_id=self.uid)
            before=list(db.get_connection().iterdump())
            for action in (lambda:f.void_currency_exchange(self.b,ident,actor_user_id=self.uid),
                           lambda:f.update_currency_exchange(self.b,ident,5000,100,actor_user_id=self.uid)):
                with self.assertRaisesRegex(f.FinanceError,'account_unavailable'):action()
                self.assertEqual(list(db.get_connection().iterdump()),before)
