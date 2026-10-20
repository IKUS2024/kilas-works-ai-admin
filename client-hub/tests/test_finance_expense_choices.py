"""Expense-only reversible language policy and untouched historical references."""
import unittest
import test_finance_expense_entries as fixture
import finance_service as f, finance_branches as branches, finance_expense_entries as expense, db
from finance_expense_choices import hidden_from_expense_picker as hidden

class ExpenseChoiceTests(unittest.TestCase):
 setUp=fixture.ExpenseEntryTests.setUp
 def test_effective_labels_whole_words_and_ambiguous_english(self):
  for label in ('Home/Rent','Food','Utilities','Air','Film','Gas','Laundry','Internet','Bonus','Vegas travel','SewaBali Studio','Toll road','Transportation','Bank Charge','Marketing','Packaging','Software','Hosting / Domain','AI / API'):
   with self.subTest(label=label):self.assertFalse(hidden(dict(direction='EXPENSE',name=label)))
  for label in ('Transportasi','Biaya Bank','Software & Langganan','Pajak','Administrasi & Profesional','Makanan & Belanja Harian','BBM','Bahan Baku','Transportasi Daring','BPJS / Ketenagakerjaan'):
   with self.subTest(label=label):self.assertTrue(hidden(dict(direction='EXPENSE',name=label)))
  self.assertTrue(hidden(dict(direction='EXPENSE',name='Air'),parent_label='Utilitas'))
  self.assertFalse(hidden(dict(direction='EXPENSE',name='Air'),parent_label='Utilities'))
  self.assertFalse(hidden(dict(direction='INCOME',name='Gaji')))
  self.assertFalse(hidden(dict(direction='EXPENSE',name='Makanan',display_name='Food')))
 def test_both_scopes_no_storage_mutation_english_child_and_historical_ids_preserved(self):
  for branch in (self.personal,self.branch):
   with branches.scope(self.b,branch,self.uid):
    f.ensure_finance_defaults(self.b,actor_user_id=self.uid)
    parent=f.create_category(self.b,'EXPENSE','Biaya Sewa',actor_user_id=self.uid)
    child=f.create_category(self.b,'EXPENSE','Customer studio rental',parent_category_id=parent,actor_user_id=self.uid)
    english=f.create_category(self.b,'EXPENSE','English equipment',actor_user_id=self.uid)
    indo=f.create_category(self.b,'EXPENSE','Peralatan Kecil',parent_category_id=english,actor_user_id=self.uid)
    account=self.pa if branch==self.personal else self.a
    tx=f.create_transaction(self.b,'EXPENSE',12345,account,child,'2026-09-10',actor_user_id=self.uid)
    tables=['finance_categories','finance_category_workspace_settings','finance_category_hierarchy','finance_transactions','finance_expense_allocations','finance_catalog_items','finance_category_preferences','finance_category_catalog_versions']
    before={t:[dict(r) for r in db.query_all('SELECT * FROM '+t)] for t in tables}
    rows=f.list_categories(self.b,'EXPENSE',include_children=True,actor_user_id=self.uid);byid={r['id']:r for r in rows}
    self.assertTrue(byid[parent]['expense_picker_hidden']);self.assertFalse(byid[child]['expense_picker_hidden']);self.assertEqual(byid[child]['parent_category_id'],parent)
    self.assertTrue(byid[indo]['expense_picker_hidden']);self.assertFalse(byid[english]['expense_picker_hidden'])
    self.assertEqual(f.resolve_category_selection(self.b,'EXPENSE',english,actor_user_id=self.uid),english)
    self.assertEqual(f.resolve_category_selection(self.b,'EXPENSE',parent,child,actor_user_id=self.uid),child)
    self.assertEqual(f.resolve_category_selection(self.b,'EXPENSE',parent,child,actor_user_id=self.uid,retained_id=child),child)
    self.assertEqual(f.get_transaction(self.b,tx,actor_user_id=self.uid)['category_id'],child)
    self.assertTrue(next(r for r in expense.edit_categories(self.b,tx,self.uid) if r['id']==child)['retained'])
    self.assertEqual(before,{t:[dict(r) for r in db.query_all('SELECT * FROM '+t)] for t in tables})
    self.assertEqual(sum(r['amount_minor'] for r in f.get_expense_category_totals(self.b,'2026-09-01','2026-09-30',actor_user_id=self.uid)),12345)

 def test_ajax_refresh_returns_same_picker_flags_without_mutating_other_scopes(self):
  response=self.client.post(self.url+'/categories?branch_id='+str(self.branch),data=dict(action='create',direction='EXPENSE',name='Biaya Transfer'),headers={'X-Requested-With':'XMLHttpRequest'})
  self.assertEqual(response.status_code,201)
  payload=response.get_json();created=payload['category']['id'];choice=next(r for r in payload['options'] if r['id']==created)
  self.assertTrue(choice['expense_picker_hidden'])
  self.assertTrue(all(not r['expense_picker_hidden'] for r in payload['options'] if r['name'] in ('Home/Rent','Food','Utilities')))
  with branches.scope(self.b,self.personal,self.uid):self.assertNotIn(created,{r['id'] for r in f.list_categories(self.b,'EXPENSE',include_children=True,actor_user_id=self.uid)})
