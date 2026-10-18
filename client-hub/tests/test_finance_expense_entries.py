"""Synthetic local expense/receipt/split/accounting and private route contracts."""
import hashlib,io,json,unittest
from unittest.mock import patch
from werkzeug.datastructures import FileStorage
from PIL import Image
import test_finance_approved_revisions as fixture
import db,finance_service as f,finance_branches as branches,finance_expense_entries as expense

class ExpenseEntryTests(unittest.TestCase):
    setUp=fixture.ApprovedFinanceTests.setUp
    def categories(self):
        return [c['id'] for c in f.list_categories(self.b,'EXPENSE',include_children=True,actor_user_id=self.uid) if not f.list_category_children(self.b,c['id'],actor_user_id=self.uid)]
    def save(self,**changes):
        with branches.scope(self.b,self.branch,self.uid):
            ids=self.categories();values=dict(amount_minor=12345,account_id=self.a,category_id=ids[0],occurred_on='2026-09-10',currency='IDR',submission_key='a'*32,notes='Synthetic note',counterparty_name='Synthetic payee')
            values.update(changes);return expense.save(self.b,self.uid,**values)
    def splits(self):
        with branches.scope(self.b,self.branch,self.uid):
            ids=self.categories();return [dict(category_id=ids[0],amount_minor=10000),dict(category_id=ids[1],amount_minor=2345)]
    def test_one_ledger_debit_allocated_reports_exact_retry_void(self):
        values=self.splits();tx=self.save(splits=values);self.assertEqual(self.save(splits=values),tx)
        with branches.scope(self.b,self.branch,self.uid):
            self.assertEqual(f.count_transactions(self.b,actor_user_id=self.uid),1)
            self.assertEqual(f.get_account_balance_report(self.b,'2026-09-30',self.uid)[0]['expense_minor'],12345)
            totals=f.get_expense_category_totals(self.b,'2026-09-01','2026-09-30',actor_user_id=self.uid)
            self.assertEqual(sum(r['amount_minor'] for r in totals),12345)
            self.assertEqual({r['category_id']:r['amount_minor'] for r in totals},{r['category_id']:r['amount_minor'] for r in values})
            self.assertEqual(sum(r['amount_minor'] for r in f.get_category_breakdown(self.b,'2026-09-01','2026-09-30',self.uid)),12345)
            self.assertEqual(len(f.get_report_transactions(self.b,'2026-09-01','2026-09-30',self.uid)),1)
            self.assertEqual(f.count_transactions(self.b,category_id=values[1]['category_id'],actor_user_id=self.uid),1)
            f.void_transaction(self.b,tx,actor_user_id=self.uid)
            self.assertEqual(f.get_expense_category_totals(self.b,'2026-09-01','2026-09-30',actor_user_id=self.uid),[])
            self.assertEqual(self.save(splits=values),tx)
    def test_bad_sums_foreign_category_duplicate_conflict_rollback(self):
        for values in [self.splits()[:1],[dict(v,amount_minor=1) for v in self.splits()],self.splits()*2]:
            with self.assertRaises(f.FinanceError):self.save(splits=values)
        othercat=f.list_categories(self.other,'EXPENSE')[0]['id'];bad=self.splits();bad[0]['category_id']=othercat
        with self.assertRaises(f.FinanceError):self.save(splits=bad)
        tx=self.save()
        with self.assertRaisesRegex(f.FinanceError,'expense_submission_conflict'):self.save(amount_minor=54321)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n'],1)
    def test_edit_split_and_legacy_amounts_account_once(self):
        tx=self.save(splits=self.splits())
        with branches.scope(self.b,self.branch,self.uid):
            row=f.get_transaction(self.b,tx,actor_user_id=self.uid)
            with self.assertRaisesRegex(f.FinanceError,'expense_split_required'):f.update_transaction(self.b,tx,actor_user_id=self.uid,amount_minor=999)
            values=self.splits();values[1]['amount_minor']=3456
            self.save(transaction_id=tx,amount_minor=13456,splits=values,expected_updated_at=row['updated_at'])
            self.assertEqual(f.get_account_balance_report(self.b,'2026-09-30',self.uid)[0]['expense_minor'],13456)
            self.assertEqual(sum(r['amount_minor'] for r in f.get_category_totals(self.b,'2026-09-01','2026-09-30','EXPENSE',actor_user_id=self.uid)),13456)
            self.assertEqual(len(expense.allocations(self.b,tx,self.uid)),2)
            with self.assertRaises(f.FinanceError):f.move_transaction_workspace(self.b,tx,self.personal,actor_user_id=self.uid)
    def test_concurrent_same_submission_is_one_parent_and_no_duplicate_allocations(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        values=self.splits();barrier=threading.Barrier(2)
        def save(_):barrier.wait();return self.save(splits=values)
        with ThreadPoolExecutor(max_workers=2) as pool:ids=list(pool.map(save,range(2)))
        self.assertEqual(ids[0],ids[1])
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n'],1)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_expense_allocations')['n'],2)

    def test_exact_currency_precision_under_over_and_account_edit_reversal(self):
        with branches.scope(self.b,self.branch,self.uid):
            account=f.create_account(self.b,'Synthetic USD','BANK',currency='USD',actor_user_id=self.uid)
            values=self.splits();values[0]['amount_minor']=5000;values[1]['amount_minor']=5001
            tx=self.save(account_id=account,currency='USD',amount_minor=10001,splits=values)
            for amount in (10000,10002):
                with self.assertRaisesRegex(f.FinanceError,'expense_split_total'):self.save(account_id=account,currency='USD',amount_minor=amount,splits=values,submission_key='e'*32)
            self.assertEqual(sum(r['amount_minor'] for r in f.get_category_totals(self.b,'2026-09-01','2026-09-30','EXPENSE',actor_user_id=self.uid)),10001)
            row=f.get_transaction(self.b,tx,actor_user_id=self.uid)
            second=f.create_account(self.b,'Synthetic USD target','BANK',currency='USD',actor_user_id=self.uid)
            self.save(transaction_id=tx,account_id=second,currency='USD',amount_minor=10001,splits=values,expected_updated_at=row['updated_at'])
            balances={r['id']:r for r in f.get_account_balance_report(self.b,'2026-09-30',self.uid)}
            self.assertEqual(balances[account]['expense_minor'],0);self.assertEqual(balances[second]['expense_minor'],10001)

    def test_forged_subcategory_http_never_posts_or_stores_receipt(self):
        with branches.scope(self.b,self.branch,self.uid):
            categories=f.list_categories(self.b,'EXPENSE',include_children=True,actor_user_id=self.uid)
            child=next(c for c in categories if c.get('parent_category_id'))
            parent=next(c for c in categories if not c.get('parent_category_id') and c['id']!=child['parent_category_id'])
        response=self.client.post(self.url+'/transactions?branch_id='+str(self.branch),data=dict(direction='EXPENSE',amount='100.01',account_id=str(self.a),category_id=str(parent['id']),subcategory_id=str(child['id']),occurred_on='2026-09-10',submission_key='f'*32))
        self.assertEqual(response.status_code,303)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n'],0)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_expense_receipts')['n'],0)

    def photo(self):
        raw=io.BytesIO();Image.new('RGB',(10,10),'white').save(raw,'JPEG');raw.seek(0)
        return expense.photo(FileStorage(stream=raw,filename='receipt.jpg'))
    def test_private_photo_validated_foreign_branch_cancel_and_commit_rollback(self):
        photo=self.photo();tx=self.save(receipt=photo)
        route=f'{self.url}/transactions/{tx}/receipt?branch_id={self.branch}'
        response=self.client.get(route);self.assertEqual(response.status_code,200);self.assertEqual(response.data,photo['raw'])
        self.assertIn('attachment',response.headers['Content-Disposition']);self.assertIn('private',response.headers['Cache-Control'])
        self.assertEqual(self.client.get(f'{self.url}/transactions/{tx}/receipt?branch_id={self.personal}').status_code,404)
        self.assertIsNone(f.get_transaction(self.other,tx,actor_user_id=self.other_uid))
        with self.assertRaises(f.FinanceError):expense.photo(FileStorage(stream=io.BytesIO(b'<svg/>'),filename='receipt.jpg'))
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_expense_receipts')['n'],1)
        with patch.object(f,'_audit',side_effect=RuntimeError('synthetic commit failure')):
            with self.assertRaises(RuntimeError):self.save(submission_key='b'*32,receipt=photo)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n'],1)
    def test_post_split_receipt_precision_edit_and_render_all_locales(self):
        values=self.splits();categories={c['id']:c for c in f.list_categories(self.b,'EXPENSE',include_children=True,actor_user_id=self.uid)}
        def parent(value):return categories[value['category_id']].get('parent_category_id') or value['category_id']
        data=dict(direction='EXPENSE',amount='123.45',account_id=str(self.a),category_id=str(parent(values[0])),occurred_on='2026-09-10',notes='Example notes',counterparty_name='Example optional payee',submission_key='c'*32,split_enabled='1',split_category_id=[str(parent(v)) for v in values],split_subcategory_id=[str(v['category_id']) if categories[v['category_id']].get('parent_category_id') else '' for v in values],split_amount=['100.00','23.45'])
        result=self.client.post(self.url+'/transactions?branch_id='+str(self.branch),data=data)
        self.assertEqual(result.status_code,303)
        row=db.query_one('SELECT * FROM finance_transactions');self.assertIsNotNone(row)
        self.assertEqual(row['amount_minor'],12345);self.assertEqual(row['notes'],'Example notes')
        self.client.post(self.url+'/transactions?branch_id='+str(self.branch),data=data)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n'],1)
        for locale in ('id','en','es','zh'):
            self.client.set_cookie('kilas_language',locale)
            result=self.client.get(self.url,query_string={'branch_id':self.branch,'direction':'EXPENSE','view':'transactions','month':'2026-09'})
            self.assertEqual(result.status_code,200);self.assertIn('data-expense-form',result.text)
            self.assertEqual(self.client.get(f'{self.url}/transactions/{row["id"]}/edit?branch_id={self.branch}').status_code,200)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n'],1)
    def test_personal_scope_stays_personal_and_foreign_account_rejected(self):
        with branches.scope(self.b,self.personal,self.uid):
            ids=self.categories();tx=expense.save(self.b,self.uid,amount_minor=12345,account_id=self.pa,category_id=ids[0],occurred_on='2026-09-10',currency='IDR',submission_key='d'*32)
        self.assertEqual(db.query_one('SELECT branch_id FROM finance_transactions WHERE id=?',(tx,))['branch_id'],self.personal)
        with self.assertRaises(f.FinanceError):self.save(account_id=self.pa)

if __name__=='__main__':unittest.main()
