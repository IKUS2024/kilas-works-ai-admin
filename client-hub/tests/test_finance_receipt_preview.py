"""Shared receipt preview markup and unchanged private receipt persistence."""
import hashlib,io,unittest
from werkzeug.datastructures import FileStorage
import test_finance_expense_entries as fixture
import db,finance_service as f,finance_branches as branches,finance_expense_entries as expense

class ReceiptPreviewTests(unittest.TestCase):
 setUp=fixture.ExpenseEntryTests.setUp
 def saved(self):
  with branches.scope(self.b,self.branch,self.uid):
   leaf=next(v['id'] for v in f.list_categories(self.b,'EXPENSE',include_children=True,actor_user_id=self.uid) if not f.list_category_children(self.b,v['id'],actor_user_id=self.uid))
   photo=fixture.ExpenseEntryTests.photo(self)
   tx=expense.save(self.b,self.uid,amount_minor=12345,account_id=self.a,category_id=leaf,occurred_on='2025-01-01',currency='IDR',receipt=photo,submission_key='a'*32)
   return tx,leaf,photo
 def test_shared_preview_clear_markup_all_four_locales(self):
  tx,leaf,photo=self.saved()
  for language,label in (('id','Hapus foto struk'),('en','Remove receipt photo'),('es','Quitar foto del recibo'),('zh','移除收据照片')):
   self.client.set_cookie('kilas_language',language)
   for branch in (self.branch,self.personal):
    page=self.client.get(self.url,query_string=dict(branch_id=branch,view='transactions',direction='EXPENSE'))
    self.assertEqual(page.status_code,200);self.assertIn('data-expense-photo-preview',page.text);self.assertIn('type="button" class="expense-photo-clear"',page.text);self.assertIn('aria-label="'+label+'"',page.text)
    self.assertIn('accept="image/jpeg,image/png,image/webp"',page.text)
   page=self.client.get(self.url+f'/transactions/{tx}/edit?branch_id={self.branch}')
   self.assertEqual(page.status_code,200);self.assertIn('aria-label="'+label+'"',page.text);self.assertIn(f'/transactions/{tx}/receipt',page.text)
 def test_edit_without_pending_replacement_preserves_saved_receipt(self):
  tx,leaf,photo=self.saved()
  with branches.scope(self.b,self.branch,self.uid):
   row=f.get_transaction(self.b,tx,actor_user_id=self.uid);selected=next(v for v in f.list_categories(self.b,'EXPENSE',include_children=True,actor_user_id=self.uid) if v['id']==leaf)
  original=dict(db.query_one('SELECT * FROM finance_expense_receipts WHERE transaction_id=?',(tx,)))
  data=dict(branch_id=self.branch,category_id=selected.get('parent_category_id') or leaf,subcategory_id=leaf if selected.get('parent_category_id') else '',account_id=self.a,amount='123.45',occurred_on='2025-01-01',notes='Receipt replacement removed before Save',expected_updated_at=row['updated_at'])
  response=self.client.post(self.url+f'/transactions/{tx}/edit',data=data)
  self.assertEqual(response.status_code,303);self.assertEqual(dict(db.query_one('SELECT * FROM finance_expense_receipts WHERE transaction_id=?',(tx,))),original)
  response=self.client.get(self.url+f'/transactions/{tx}/receipt?branch_id={self.branch}');self.assertEqual(response.status_code,200);self.assertEqual(hashlib.sha256(response.data).hexdigest(),photo['digest'])
  self.assertEqual(self.client.get(self.url+f'/transactions/{tx}/receipt?branch_id={self.personal}').status_code,404)
 def test_no_pending_file_does_not_mean_delete_and_pdf_remains_unsupported(self):
  self.assertIsNone(expense.photo(FileStorage(stream=io.BytesIO(b''),filename='')))
  with self.assertRaises(f.FinanceError):expense.photo(FileStorage(stream=io.BytesIO(b'%PDF-1.7\n'),filename='receipt.pdf'))
if __name__=='__main__':unittest.main()
