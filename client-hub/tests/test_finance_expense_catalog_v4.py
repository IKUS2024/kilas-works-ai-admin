"""Ten owner-approved expense defaults, reversible presentation only; local fixtures."""
import json
import unittest
import test_finance_expense_entries as fixture
import db,repo
import finance_service as f
import finance_branches as branches
import finance_category_catalog as catalog
import finance_expense_entries as expenses

EXPECTED=['Home/Rent','Food','Utilities','Personal Item','Transportation','Entertainment','Medical','Holiday','Bank Charge','Misc/one-time']

class ExpenseCatalogV4Tests(unittest.TestCase):
 setUp=fixture.ExpenseEntryTests.setUp
 def bare(self,tag):
  owner=repo.create_user(tag+'@example.test','unused');bid=repo.create_business(owner,'Synthetic '+tag);branch=branches.ensure_personal(bid,owner)
  return bid,owner,branch
 def seed(self,bid,owner,key,name,parent=None):
  ident=f._create_category(bid,'EXPENSE','legacy-'+key,owner);f._ensure_category_setting(bid,ident,name,owner)
  if parent:f._link_category_parent(bid,ident,parent)
  catalog.mark(bid,f._category_scope(bid,owner)['scope_key'],key,ident,0,name)
  return ident
 def snapshot(self,tables):return {table:[dict(r) for r in db.query_all('SELECT * FROM '+table)] for table in tables}
 def test_fresh_both_scopes_exact_ten_english_in_every_locale_and_existing_children_only(self):
  for branch in (self.personal,self.branch):
   with branches.scope(self.b,branch,self.uid):
    for locale in ('id','en','es','zh'):
     with fixture.fixture.app.test_request_context('/',headers={'Cookie':'kilas_language='+locale}):
      roots=f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid)
      self.assertEqual([r['display_name'] for r in roots],EXPECTED)
      self.assertTrue(all(r['builtin_default'] for r in roots))
      personal=branch==self.personal
      for root,(key,_,_,children) in zip(roots,catalog.EXPENSE_V4):
       approved=children if personal else catalog.BUSINESS_UTILITY_V4 if key=='utilities' else ()
       self.assertEqual([r['display_name'] for r in f.list_category_children(self.b,root['id'],actor_user_id=self.uid)],[pair[1] for pair in approved])
 def test_v3_upgrade_preserves_every_historical_row_relation_split_balance_and_schedule(self):
  bid,owner,branch=self.bare('v4-history')
  with branches.scope(bid,branch,owner):
   with f._write(bid,owner):catalog._sync_final(bid,owner,f._category_scope(bid,owner))
   roots=f.list_categories(bid,'EXPENSE',actor_user_id=owner);insurance=next(r for r in roots if r['name']=='Asuransi');kids=f.list_category_children(bid,insurance['id'],actor_user_id=owner)
   account=f.create_account(bid,'Synthetic cash','CASH',actor_user_id=owner)
   tx=expenses.save(bid,owner,amount_minor=10001,account_id=account,category_id=kids[0]['id'],occurred_on='2025-01-01',currency='IDR',submission_key='e'*32,splits=[dict(category_id=kids[0]['id'],amount_minor=5000),dict(category_id=kids[1]['id'],amount_minor=5001)])
   rule=f.create_recurring_expense(bid,'Synthetic insurance',1000,account,kids[0]['id'],'MONTHLY','2025-02-01',actor_user_id=owner)
   tables=['finance_transactions','finance_expense_allocations','finance_expense_entries','finance_recurring_expenses','finance_category_hierarchy','finance_categories','finance_category_workspace_settings']
   before=self.snapshot(tables);balance=f.get_account_balance_report(bid,'2025-01-31',owner)
   f.ensure_finance_defaults(bid,actor_user_id=owner)
   after=self.snapshot(tables)
   for table,rows in before.items():
    for row in rows:self.assertIn(row,after[table],table)
   self.assertEqual(before['finance_transactions'],after['finance_transactions']);self.assertEqual(before['finance_expense_allocations'],after['finance_expense_allocations']);self.assertEqual(before['finance_recurring_expenses'],after['finance_recurring_expenses'])
   self.assertEqual(balance,f.get_account_balance_report(bid,'2025-01-31',owner))
   self.assertNotIn(insurance['id'],[r['id'] for r in f.list_categories(bid,'EXPENSE',actor_user_id=owner)])
   self.assertTrue(f._category_setting_by_id(bid,kids[0]['id'],owner)['is_active'])
   edit=expenses.edit_categories(bid,tx,owner);self.assertTrue({insurance['id'],kids[0]['id'],kids[1]['id']} <= {r['id'] for r in edit})
   self.assertEqual(f.resolve_category_selection(bid,'EXPENSE',insurance['id'],kids[0]['id'],actor_user_id=owner,retained_id=kids[0]['id']),kids[0]['id'])
   with self.assertRaises(f.FinanceError):f.resolve_category_selection(bid,'EXPENSE',insurance['id'],kids[0]['id'],actor_user_id=owner)
   # Existing scheduled posting still resolves the unchanged legacy identity.
   scheduled=f._transaction_data(bid,dict(direction='EXPENSE',amount_minor=1000,currency='IDR',account_id=account,category_id=kids[0]['id'],occurred_on='2025-02-01',description=None,counterparty_name=None,project_id=None,customer_id=None,source_type=None,source_ref=None),scheduled=True)
   self.assertEqual(scheduled['category_id'],kids[0]['id'])
 def test_only_proven_duplicates_hidden_unknown_custom_and_custom_parent_context_survive(self):
  bid,owner,branch=self.bare('v4-provenance')
  with branches.scope(bid,branch,owner):
   a=self.seed(bid,owner,'old.a','Rumah / Sewa');b=self.seed(bid,owner,'old.b','Home/Rent')
   insurance=self.seed(bid,owner,'old.insurance','Asuransi');custom=f.create_category(bid,'EXPENSE','My policy',parent_category_id=insurance,actor_user_id=owner)
   unknown=f.create_category(bid,'EXPENSE','Insurance',actor_user_id=owner)
   edited=self.seed(bid,owner,'old.edited','Gaji');catalog.edit(bid,owner,edited,name='Owner salary group')
   before=self.snapshot(['finance_categories','finance_category_workspace_settings','finance_category_hierarchy'])
   f.ensure_finance_defaults(bid,actor_user_id=owner)
   rows=f.list_categories(bid,'EXPENSE',include_children=True,actor_user_id=owner);ids={r['id'] for r in rows}
   self.assertNotIn(a,ids);self.assertNotIn(b,ids)
   self.assertTrue({unknown,edited,insurance,custom} <= ids)
   self.assertEqual(next(r['display_name'] for r in rows if r['id']==unknown),'Insurance')
   self.assertEqual(next(r['display_name'] for r in rows if r['id']==edited),'Owner salary group')
   defaults=[r for r in rows if r['builtin_default'] and not r['parent_category_id']];self.assertEqual([r['display_name'] for r in defaults],EXPECTED)
   for table,records in before.items():
    for record in records:self.assertIn(record,self.snapshot([table])[table])
 def test_policy_is_idempotent_and_disable_restores_old_choices_without_deleting_any_rows(self):
  bid,owner,branch=self.bare('v4-reverse')
  with branches.scope(bid,branch,owner):
   old=self.seed(bid,owner,'old.insurance','Asuransi')
   f.ensure_finance_defaults(bid,actor_user_id=owner);before=self.snapshot(['finance_categories','finance_category_workspace_settings','finance_catalog_items','finance_category_preferences','finance_category_catalog_versions'])
   for _ in range(3):f.ensure_finance_defaults(bid,actor_user_id=owner)
   self.assertEqual(before,self.snapshot(list(before)))
   policy=catalog._expense_policy(bid,f._category_scope(bid,owner));policy['enabled']=False
   db.execute('UPDATE finance_category_catalog_versions SET changes_json=? WHERE business_id=? AND scope_key=? AND version=4',(json.dumps(policy),bid,'PERSONAL:'+str(owner)))
   self.assertEqual([r['id'] for r in f.list_categories(bid,'EXPENSE',actor_user_id=owner)],[old])
   self.assertEqual(before['finance_categories'],self.snapshot(['finance_categories'])['finance_categories'])
 def test_income_and_other_tenants_unchanged_and_custom_edits_archives_not_resurrected(self):
  before=self.snapshot(['finance_categories','finance_category_workspace_settings'])
  with branches.scope(self.b,self.personal,self.uid):
   roots=f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid);catalog.edit(self.b,self.uid,roots[0]['id'],name='My home');catalog.edit(self.b,self.uid,roots[1]['id'],deactivate=True)
   f.ensure_finance_defaults(self.b,actor_user_id=self.uid)
   rows=f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid)
   self.assertIn('My home',[r['display_name'] for r in rows]);self.assertNotIn(roots[1]['id'],[r['id'] for r in rows])
   with self.assertRaises(f.FinanceError):f.list_categories(self.b,'EXPENSE',actor_user_id=self.other_uid)
  after=self.snapshot(list(before));expense_ids={r['id'] for r in after['finance_categories'] if r['direction']=='EXPENSE' and r['business_id']==self.b}
  for table in before:
   protected=lambda r:r.get('business_id')!=self.b or (r['id'] if table=='finance_categories' else r['category_id']) not in expense_ids
   self.assertEqual([r for r in before[table] if protected(r)],[r for r in after[table] if protected(r)])

 def test_concurrent_initialization_is_one_policy_and_no_duplicate_defaults(self):
  from concurrent.futures import ThreadPoolExecutor
  from threading import Barrier
  bid,owner,branch=self.bare('v4-concurrent');barrier=Barrier(2)
  def run(_):
   try:
    with branches.scope(bid,branch,owner):barrier.wait();f.ensure_finance_defaults(bid,actor_user_id=owner)
   finally:db._discard_cached_connection()
  with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,range(2)))
  with branches.scope(bid,branch,owner):
   rows=f.list_categories(bid,'EXPENSE',include_children=True,actor_user_id=owner)
   self.assertEqual(len(rows),52);self.assertEqual(len({r['id'] for r in rows}),52)
   self.assertEqual(db.query_one('SELECT count(*) n FROM finance_category_catalog_versions WHERE business_id=? AND version=4',(bid,))['n'],1)
 def test_direct_business_edit_initializes_only_expense_policy(self):
  with branches.scope(self.b,self.branch,self.uid):
   root=f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid)[0]
   tx=f.create_transaction(self.b,'EXPENSE',100,self.a,root['id'],'2025-01-01',actor_user_id=self.uid)
   db.execute('DELETE FROM finance_category_catalog_versions WHERE business_id=? AND scope_key=? AND version=4',(self.b,'BUSINESS'))
   income=[dict(r) for r in f.list_categories(self.b,'INCOME',include_inactive=True,include_children=True,actor_user_id=self.uid)]
   expenses.edit_categories(self.b,tx,self.uid)
   self.assertTrue(catalog._expense_policy(self.b,f._category_scope(self.b,self.uid)))
   self.assertEqual(income,[dict(r) for r in f.list_categories(self.b,'INCOME',include_inactive=True,include_children=True,actor_user_id=self.uid)])

 def test_first_finance_setup_keeps_balance_and_seeds_only_current_expenses_on_open(self):
  import finance_entitlements as entitlement
  bid=repo.create_business(self.uid,'Fresh setup',package='NONE')
  account=entitlement.setup(bid,self.uid,'Synthetic bank','BANK',50000)
  self.assertEqual(entitlement.setup(bid,self.uid,'Ignored replay','CASH',999),account)
  branch=f.list_accounts(bid,actor_user_id=self.uid)[0]['branch_id']
  response=self.client.get(f'/business/{bid}/finance?branch_id={branch}&view=transactions&direction=EXPENSE')
  self.assertEqual(response.status_code,200)
  with branches.scope(bid,branch,self.uid):
   self.assertEqual([r['display_name'] for r in f.list_categories(bid,'EXPENSE',actor_user_id=self.uid)],EXPECTED)
   self.assertEqual(db.query_one("SELECT count(*) n FROM finance_categories WHERE business_id=? AND direction='EXPENSE'",(bid,))['n'],17)
   self.assertFalse(f.list_transactions(bid));self.assertEqual(f.list_accounts(bid)[0]['opening_balance_minor'],50000)
 def test_activation_initialization_does_not_create_unmarked_legacy_duplicates(self):
  from unittest.mock import patch
  import finance_entitlements as entitlement
  import routes_products
  bid=repo.create_business(self.uid,'Activation fixture',package='NONE')
  states=[dict(active=False,status='NOT_ACTIVATED',trial_used=False),dict(active=True,status='FREE',trial_used=False)]
  with fixture.fixture.app.test_request_context('/'),patch.object(entitlement,'state',side_effect=states):
   target=routes_products._start_finance_trial_now(bid,repo.get_user_by_id(self.uid))
  self.assertIn('/finance',target)
  self.assertEqual([r['display_name'] for r in f.list_categories(bid,'EXPENSE',actor_user_id=self.uid)],EXPECTED)
  self.assertEqual(db.query_one("SELECT count(*) n FROM finance_categories WHERE business_id=? AND direction='EXPENSE'",(bid,))['n'],17)
  self.assertFalse(f.list_transactions(bid))

 def test_management_alias_lookup_never_revives_duplicate_or_renames_historical_seed(self):
  bid,owner,branch=self.bare('v4-alias-management')
  with branches.scope(bid,branch,owner):
   legacy=self.seed(bid,owner,'old.home','Rumah / Sewa')
   f.ensure_finance_defaults(bid,actor_user_id=owner)
   before=dict(db.query_one('SELECT * FROM finance_category_workspace_settings WHERE category_id=?',(legacy,)))
   self.assertEqual(f.create_category(bid,'EXPENSE','Home/Rent',actor_user_id=owner),legacy)
   self.assertEqual(before,dict(db.query_one('SELECT * FROM finance_category_workspace_settings WHERE category_id=?',(legacy,))))
  bid,owner,branch=self.bare('v4-duplicate-management')
  with branches.scope(bid,branch,owner):
   a=self.seed(bid,owner,'old.id','Rumah / Sewa');b=self.seed(bid,owner,'old.en','Home/Rent')
   old=f._create_category(bid,'EXPENSE','Insurance',owner);f._ensure_category_setting(bid,old,'Insurance',owner);catalog.mark(bid,'PERSONAL:'+str(owner),'old.insurance',old,0,'Insurance')
   f.ensure_finance_defaults(bid,actor_user_id=owner)
   home=next(r for r in f.list_categories(bid,'EXPENSE',actor_user_id=owner) if r['display_name']=='Home/Rent')
   self.assertNotIn(home['id'],(a,b))
   catalog.edit(bid,owner,home['id'],deactivate=True)
   self.assertEqual(f.create_category(bid,'EXPENSE','Home/Rent',actor_user_id=owner),home['id'])
   custom=f.create_category(bid,'EXPENSE','Insurance',actor_user_id=owner)
   self.assertNotEqual(custom,old)
   self.assertNotIn(old,{r['id'] for r in f.list_categories(bid,'EXPENSE',actor_user_id=owner)})
   self.assertTrue(db.query_one('SELECT id FROM finance_categories WHERE id=?',(old,)))

if __name__=='__main__':unittest.main()
