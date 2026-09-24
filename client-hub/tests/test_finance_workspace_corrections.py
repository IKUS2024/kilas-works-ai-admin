"""Audited correction commands: real owner, immutable business and atomic history."""
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import test_finance_phase2a as fixture
import db, repo, finance_branches as branches
f = fixture.f


class WorkspaceCorrectionTests(unittest.TestCase):
    def setUp(self):
        fixture.ReceivablesTests.setUp(self)
        self.source = branches.list_branches(self.b, self.uid)[0]['id']
        self.target = branches.ensure_personal(self.b, self.uid)
        with branches.scope(self.b, self.source, self.uid):
            self.account = f.create_account(self.b, 'Correction Bank', 'BANK',
                opening_balance_minor=12345, actor_user_id=self.uid)
            self.tx = f.create_transaction(self.b, 'INCOME', 789, self.account,
                self.cat, '2026-09-10', description='Keep economics', actor_user_id=self.uid)

    def dump(self):
        return '\n'.join(db.get_connection().iterdump())

    def move(self, source=None, target=None, tx=None):
        with branches.scope(self.b, source or self.source, self.uid):
            return f.move_transaction_workspace(self.b, tx or self.tx,
                target or self.target, actor_user_id=self.uid)

    def account_move(self, source, account, target):
        with branches.scope(self.b, source, self.uid):
            return f.move_account_workspace(self.b, account, target, actor_user_id=self.uid)

    def test_original_economics_survive_many_reverse_moves_and_raw_guards(self):
        original = dict(f.get_transaction(self.b, self.tx, actor_user_id=self.uid))
        for n in range(6):
            source, target = (self.source, self.target) if n % 2 == 0 else (self.target, self.source)
            self.move(source, target)
            row = dict(f.get_transaction(self.b, self.tx, actor_user_id=self.uid))
            for key in original:
                if key not in ('branch_id','branch_name','account_id','category_id','updated_at','relocation_version'):
                    self.assertEqual(row[key], original[key], key)
            self.assertEqual(row['relocation_version'], n+1)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions WHERE id=?',(self.tx,))['n'],1)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_workspace_corrections')['n'],6)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transaction_revisions WHERE transaction_id=?',(self.tx,))['n'],6)
        for sql, args in (
            ('UPDATE finance_transactions SET branch_id=? WHERE id=?',(self.target,self.tx)),
            ('UPDATE finance_transactions SET relocation_version=0 WHERE id=?',(self.tx,)),
            ('UPDATE finance_transactions SET business_id=? WHERE id=?',(self.other,self.tx)),
            ('UPDATE finance_workspace_corrections SET actor_user_id=?',(self.other_uid,)),
            ('DELETE FROM finance_workspace_corrections',()),
        ):
            before=self.dump()
            with self.assertRaises(Exception): db.execute(sql,args)
            self.assertEqual(self.dump(),before)

    def test_cannot_replay_old_correction_with_plain_sql(self):
        self.move(); self.move(self.target,self.source)
        first=db.query_one('SELECT * FROM finance_workspace_corrections ORDER BY id LIMIT 1')
        before=self.dump()
        with self.assertRaises(Exception):
            db.execute('UPDATE finance_transactions SET branch_id=?,account_id=?,category_id=?,relocation_version=?,updated_at=? WHERE id=?',
                (first['target_branch_id'],first['target_account_id'],first['target_category_id'],first['version'],first['created_at'],self.tx))
        self.assertEqual(self.dump(),before)

    def test_owner_required_even_for_direct_service_calls(self):
        for actor in (None,self.other_uid):
            before=self.dump()
            with branches.scope(self.b,self.source,self.uid),self.assertRaises(f.FinanceError):
                f.move_transaction_workspace(self.b,self.tx,self.target,actor_user_id=actor)
            self.assertEqual(self.dump(),before)
        db.execute("UPDATE business_memberships SET role_in_business='STAFF' WHERE business_id=? AND user_id=?",(self.b,self.uid))
        before=self.dump()
        with self.assertRaises(f.FinanceError):self.move()
        self.assertEqual(self.dump(),before)

    def test_other_owner_personal_workspace_and_foreign_business_denied(self):
        db.execute("INSERT INTO business_memberships(business_id,user_id,role_in_business) VALUES (?,?,'OWNER')",(self.b,self.other_uid))
        private=branches.ensure_personal(self.b,self.other_uid)
        foreign=branches.list_branches(self.other,self.other_uid)[0]['id']
        for target in (private,foreign):
            before=self.dump()
            with self.assertRaises(f.FinanceError):self.move(target=target)
            self.assertEqual(self.dump(),before)

    def test_late_audit_failure_rolls_back_everything(self):
        real=f._audit
        def fail(bid,actor,action,*args):
            if action=='FINANCE_ACCOUNT_WORKSPACE_MOVED': raise RuntimeError('audit down')
            return real(bid,actor,action,*args)
        before=self.dump()
        with patch.object(f,'_audit',side_effect=fail),self.assertRaises(RuntimeError):
            self.account_move(self.source,self.account,self.target)
        self.assertEqual(self.dump(),before)

    def test_first_http_move_failure_leaves_no_destination(self):
        # Use untouched other business, whose Personal workspace does not exist.
        other_account=f.list_accounts(self.other,actor_user_id=self.other_uid)[0]['id']
        category=f.list_categories(self.other,'INCOME',actor_user_id=self.other_uid)[0]['id']
        tx=f.create_transaction(self.other,'INCOME',90,other_account,category,'2026-09-10',actor_user_id=self.other_uid)
        branch=branches.list_branches(self.other,self.other_uid)[0]['id']
        with self.client.session_transaction() as session:session['user_id']=self.other_uid
        before=self.dump()
        with patch.object(f,'_workspace_move_revision',side_effect=RuntimeError('late failure')),self.assertRaises(RuntimeError):
            self.client.post(f'/business/{self.other}/finance/transactions/{tx}/move-workspace',data={'branch_id':str(branch)})
        self.assertEqual(self.dump(),before)
        self.assertEqual(branches.list_branches(self.other,self.other_uid,workspace_type='PERSONAL'),[])

    def test_account_opening_reverse_and_retry_preserve_total_cash(self):
        moved=self.account_move(self.source,self.account,self.target)
        target_account=moved['target_account_id']
        again=self.account_move(self.source,self.account,self.target)
        self.assertEqual(again['target_account_id'],target_account)
        returned=self.account_move(self.target,target_account,self.source)
        self.assertEqual(returned['target_account_id'],self.account)
        self.assertEqual(f.get_account(self.b,self.account,actor_user_id=self.uid)['opening_balance_minor'],12345)
        self.assertEqual(f.get_account(self.b,target_account,actor_user_id=self.uid)['opening_balance_minor'],0)
        self.assertEqual(sum(r['balance_minor'] for r in f.get_account_balance_report(self.b,'2026-09-30',self.uid)),13134)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions WHERE business_id=?',(self.b,))['n'],1)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_workspace_opening_history')['n'],3)
        with self.assertRaises(Exception):db.execute('DELETE FROM finance_workspace_opening_history')

    def test_concurrent_transaction_move_has_one_winner(self):
        barrier=threading.Barrier(2)
        def worker(_):
            try:
                barrier.wait()
                try:self.move();return True
                except f.FinanceError:return False
            finally:
                if getattr(db._local,'conn',None):db._local.conn.close();db._local.conn=None
        with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(worker,range(2)))
        self.assertEqual(sorted(result),[False,True])
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_workspace_corrections')['n'],1)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions WHERE id=?',(self.tx,))['n'],1)

    def test_processed_recurring_and_import_accounts_are_protected(self):
        expense=f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid)[0]['id']
        with branches.scope(self.b,self.source,self.uid):
            rule=f.create_recurring_expense(self.b,'Protected schedule',10,self.account,expense,'MONTHLY','2026-09-10',actor_user_id=self.uid)
        # Even a reserved posting with no ledger must not be detached.
        db.execute('INSERT INTO finance_recurring_postings(business_id,recurring_expense_id,scheduled_on,created_at) VALUES (?,?,?,?)',(self.b,rule,'2026-09-10',repo._now()))
        before=self.dump()
        with self.assertRaises(f.FinanceError):self.account_move(self.source,self.account,self.target)
        self.assertEqual(self.dump(),before)

    def test_reconciled_manual_transaction_cannot_leave_bank_history(self):
        now=repo._now()
        batch=db.insert_returning_id(
            'INSERT INTO finance_bank_imports(business_id,branch_id,account_id,source_kind,'
            'display_label,file_hash,source_count,imported_by_user_id,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?)',
            (self.b,self.source,self.account,'CSV','Synthetic','a'*64,1,self.uid,now,now))
        db.execute('INSERT INTO finance_bank_rows(business_id,import_id,row_index,row_hash,'
                   'occurred_on,direction,amount_minor,description,reconciliation_status,'
                   'matched_transaction_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                   (self.b,batch,1,'b'*64,'2026-09-10','INCOME',789,'Synthetic','MATCHED',self.tx,now,now))
        before=self.dump()
        with self.assertRaises(f.FinanceError):self.move()
        self.assertEqual(self.dump(),before)
        with self.assertRaises(f.FinanceError):self.account_move(self.source,self.account,self.target)
        self.assertEqual(self.dump(),before)

    def test_correction_foreign_keys_preserve_row_history(self):
        self.move()
        before=self.dump()
        with self.assertRaises(Exception):db.execute('DELETE FROM finance_transactions WHERE id=?',(self.tx,))
        self.assertEqual(self.dump(),before)

    def test_migration_repeat_preserves_history_and_guard(self):
        self.move()
        row=dict(f.get_transaction(self.b,self.tx,actor_user_id=self.uid))
        history=[dict(r) for r in db.query_all('SELECT * FROM finance_workspace_corrections')]
        db.init_schema();db.init_schema()
        self.assertEqual(dict(f.get_transaction(self.b,self.tx,actor_user_id=self.uid)),row)
        self.assertEqual([dict(r) for r in db.query_all('SELECT * FROM finance_workspace_corrections')],history)
        with self.assertRaises(Exception):db.execute('UPDATE finance_transactions SET branch_id=? WHERE id=?',(self.source,self.tx))


if __name__=='__main__':unittest.main()
