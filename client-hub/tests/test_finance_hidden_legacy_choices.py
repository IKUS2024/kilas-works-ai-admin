import unittest
from flask import template_rendered
from unittest.mock import patch
import test_finance_expense_entries as fixture
import db,finance_service as f,finance_branches as branches,finance_category_catalog as catalog,finance_expense_entries as expenses

class HiddenLegacyChoices(unittest.TestCase):
 setUp=fixture.ExpenseEntryTests.setUp
 def legacy(self):
  with branches.scope(self.b,self.personal,self.uid):
   ids=[r['category_id'] for r in db.query_all("SELECT s.category_id FROM finance_category_workspace_settings s JOIN finance_categories c ON c.id=s.category_id WHERE s.business_id=? AND s.scope_key=? AND c.direction='EXPENSE'",(self.b,'PERSONAL:'+str(self.uid)))]
   marks=','.join('?' for _ in ids)
   for table,column in (('finance_category_preferences','category_id'),('finance_catalog_items','category_id'),('finance_category_workspace_settings','category_id'),('finance_category_hierarchy','child_category_id'),('finance_categories','id')):db.execute('DELETE FROM '+table+' WHERE '+column+' IN ('+marks+')',ids)
   db.execute('DELETE FROM finance_category_catalog_versions WHERE business_id=? AND scope_key=?',(self.b,'PERSONAL:'+str(self.uid)))
   catalog._sync_reference(self.b,self.uid,f._category_scope(self.b,self.uid))
   obsolete=db.query_one("SELECT category_id FROM finance_catalog_items WHERE business_id=? AND scope_key=? AND canonical_key='v2.housing.1'",(self.b,'PERSONAL:'+str(self.uid)))['category_id']
   valid=db.query_one("SELECT category_id FROM finance_catalog_items WHERE business_id=? AND scope_key=? AND canonical_key='v2.housing.2'",(self.b,'PERSONAL:'+str(self.uid)))['category_id']
   tx=f.create_transaction(self.b,'EXPENSE',10001,self.pa,valid,'2025-01-01',actor_user_id=self.uid)
   return obsolete,valid,tx
 def test_direct_legacy_edit_does_not_offer_unrelated_obsolete_choice(self):
  obsolete,valid,tx=self.legacy();contexts=[]
  def capture(sender,template,context,**extra):contexts.append(context)
  with template_rendered.connected_to(capture,fixture.fixture.app):response=self.client.get(self.url+f'/transactions/{tx}/edit?branch_id={self.personal}')
  self.assertEqual(response.status_code,200)
  self.assertNotIn(obsolete,{r['id'] for r in contexts[-1]['categories']})
  with branches.scope(self.b,self.personal,self.uid):
   self.assertNotIn(obsolete,{r['id'] for r in f.list_categories(self.b,'EXPENSE',include_children=True,actor_user_id=self.uid)})
   self.assertTrue(f._category_setting_by_id(self.b,obsolete,self.uid)['is_active'])
   self.assertTrue(db.query_one('SELECT id FROM finance_categories WHERE id=?',(obsolete,)))
 def test_dashboard_add_and_split_template_hide_obsolete_preserve_custom_and_final(self):
  obsolete,valid,tx=self.legacy();contexts=[]
  with branches.scope(self.b,self.personal,self.uid):
   custom=f.create_category(self.b,'EXPENSE','Hipotek Kedua',actor_user_id=self.uid)
   before=[dict(r) for r in db.query_all('SELECT * FROM finance_transactions')]
   old_ids={r['id'] for r in db.query_all('SELECT * FROM finance_categories')}
  def capture(sender,template,context,**extra):contexts.append(context)
  with template_rendered.connected_to(capture,fixture.fixture.app):response=self.client.get(self.url,query_string=dict(branch_id=self.personal,view='transactions',direction='EXPENSE'))
  self.assertEqual(response.status_code,200)
  self.assertNotIn('value="'+str(obsolete)+'"',response.text)
  self.assertIn('value="'+str(custom)+'"',response.text)
  self.assertIn('data-expense-split-template',response.text)
  with branches.scope(self.b,self.personal,self.uid):
   active=f.list_categories(self.b,'EXPENSE',include_children=True,actor_user_id=self.uid)
   proven={r['category_id'] for r in db.query_all("SELECT category_id FROM finance_catalog_items WHERE business_id=? AND scope_key=?",(self.b,'PERSONAL:'+str(self.uid)))}
   roots=[r for r in active if r['id'] in proven and r.get('parent_category_id') is None]
   self.assertEqual([r['display_name'] for r in roots],[v[1] for v in catalog.EXPENSE_V4])
   self.assertEqual(sum(r['id'] in proven and r.get('parent_category_id') is not None for r in active),42)
   self.assertTrue(old_ids.issubset({r['id'] for r in db.query_all('SELECT * FROM finance_categories')}))
   self.assertEqual([dict(r) for r in db.query_all('SELECT * FROM finance_transactions')],before)
 def test_historical_inactive_choice_and_splits_remain_editable_without_new_use(self):
  obsolete,valid,tx=self.legacy()
  with branches.scope(self.b,self.personal,self.uid):
   historical=expenses.save(self.b,self.uid,amount_minor=10001,account_id=self.pa,category_id=obsolete,occurred_on='2025-01-01',currency='IDR',splits=[dict(category_id=obsolete,amount_minor=5000),dict(category_id=valid,amount_minor=5001)],submission_key='f'*32)
   before=expenses.allocations(self.b,historical,self.uid);row=dict(f.get_transaction(self.b,historical,actor_user_id=self.uid))
  page=self.client.get(self.url+f'/transactions/{historical}/edit?branch_id={self.personal}');self.assertEqual(page.status_code,200)
  self.assertIn('value="'+str(obsolete)+'"',page.text)
  with branches.scope(self.b,self.personal,self.uid):
   selected=next(v for v in expenses.edit_categories(self.b,historical,self.uid) if v['id']==obsolete)
   self.assertTrue(selected['retained']);self.assertFalse(selected['is_active'])
   expenses.save(self.b,self.uid,transaction_id=historical,amount_minor=10001,account_id=self.pa,category_id=obsolete,occurred_on='2025-01-01',currency='IDR',splits=before,notes='Only note changed',expected_updated_at=row['updated_at'])
   self.assertEqual(expenses.allocations(self.b,historical,self.uid),before)
   self.assertEqual(f.get_transaction(self.b,historical,actor_user_id=self.uid)['amount_minor'],10001)
   self.assertEqual(f.count_transactions(self.b,actor_user_id=self.uid),2)
   with self.assertRaises(f.FinanceError):expenses.validate(self.b,10001,[dict(category_id=obsolete,amount_minor=5000),dict(category_id=valid,amount_minor=5001)],self.uid)
 def test_business_edit_does_not_initialize_personal_and_readonly_still_readable(self):
  with branches.scope(self.b,self.branch,self.uid):
   cat=next(v['id'] for v in f.list_categories(self.b,'EXPENSE',include_children=True,actor_user_id=self.uid) if not f.list_category_children(self.b,v['id'],actor_user_id=self.uid))
   tx=f.create_transaction(self.b,'EXPENSE',100,self.a,cat,'2025-01-01',actor_user_id=self.uid)
   with patch.object(f,'sync_business_category_catalog') as synchronize:expenses.edit_categories(self.b,tx,self.uid)
   synchronize.assert_not_called()
  obsolete,valid,tx=self.legacy()
  with branches.scope(self.b,self.personal,self.uid),patch.object(f,'sync_business_category_catalog',side_effect=f.FinanceError('finance_read_only')):
   self.assertTrue(expenses.edit_categories(self.b,tx,self.uid))
if __name__=='__main__':unittest.main()
