"""Catalog lifecycle regression; synthetic local data only."""
import json,unittest
import test_finance_expense_entries as fixture
import db,repo,finance_service as f,finance_branches as branches,finance_category_catalog as catalog

class CatalogInitializationTests(unittest.TestCase):
 setUp=fixture.ExpenseEntryTests.setUp
 def old_home(self,tag):
  owner=repo.create_user(tag+'@example.test','unused');bid=repo.create_business(owner,'Synthetic '+tag);branch=branches.ensure_personal(bid,owner)
  return bid,owner,branch
 def node(self,bid,owner,key,name,parent=None):
  ident=f._create_category(bid,'EXPENSE','fixture-'+key,owner);f._ensure_category_setting(bid,ident,name,owner)
  if parent:f._link_category_parent(bid,ident,parent)
  catalog.mark(bid,'PERSONAL:'+str(owner),key,ident,0,name);return ident
 def test_irvan_like_pre_v2_dining_out_identity_is_not_renamed(self):
  bid,owner,branch=self.old_home('older-catalog')
  with branches.scope(bid,branch,owner):
   home=self.node(bid,owner,'housing','Tempat Tinggal');food=self.node(bid,owner,'food','Makanan & Belanja');child=self.node(bid,owner,'food.1','Makan di Luar',food)
   before=dict(db.query_one('SELECT * FROM finance_categories WHERE id=?',(child,)))
   f.ensure_finance_defaults(bid,actor_user_id=owner)
   self.assertEqual(f._category_setting_by_id(bid,child,owner,include_inactive=True)['name'],'Makan di Luar')
   self.assertEqual(dict(db.query_one('SELECT * FROM finance_categories WHERE id=?',(child,))),before)
   self.assertEqual(db.query_one('SELECT builtin_name FROM finance_catalog_items WHERE category_id=?',(child,))['builtin_name'],'Makan di Luar')
   self.assertFalse(db.query_one('SELECT 1 FROM finance_category_catalog_versions WHERE business_id=? AND version=2',(bid,)))
 def test_fresh_catalog_has_only_final_expense_nodes(self):
  bid,owner,branch=self.old_home('fresh-catalog')
  with branches.scope(bid,branch,owner):
   f.ensure_finance_defaults(bid,actor_user_id=owner)
   rows=db.query_all("SELECT m.* FROM finance_catalog_items m JOIN finance_categories c ON c.id=m.category_id WHERE m.business_id=? AND c.direction='EXPENSE'",(bid,))
   self.assertEqual(len(rows),56)
   self.assertTrue(all(r['canonical_key'].startswith('v3.') for r in rows))
   self.assertEqual([r['name'] for r in f.list_categories(bid,'EXPENSE',actor_user_id=owner)],[r[1] for r in catalog.PERSONAL_V3])
 def test_existing_v2_upgrades_without_rewriting_obsolete_identity(self):
  bid,owner,branch=self.old_home('v2-catalog')
  with branches.scope(bid,branch,owner):
   catalog._sync_reference(bid,owner,f._category_scope(bid,owner))
   obsolete=db.query_one("SELECT * FROM finance_catalog_items WHERE business_id=? AND canonical_key='v2.housing.1'",(bid,))
   before=dict(db.query_one('SELECT * FROM finance_categories WHERE id=?',(obsolete['category_id'],)))
   f.ensure_finance_defaults(bid,actor_user_id=owner)
   self.assertEqual(dict(db.query_one('SELECT * FROM finance_categories WHERE id=?',(obsolete['category_id'],))),before)
   self.assertEqual(dict(db.query_one('SELECT * FROM finance_catalog_items WHERE category_id=?',(obsolete['category_id'],))),dict(obsolete))
   self.assertFalse(f._category_setting_by_id(bid,obsolete['category_id'],owner,include_inactive=True)['is_active'])
 def test_partial_v3_reuses_proven_nodes_and_preserves_custom_names(self):
  bid,owner,branch=self.old_home('partial-catalog')
  with branches.scope(bid,branch,owner):
   root=self.node(bid,owner,'v3.housing','Rumah / Sewa');child=self.node(bid,owner,'v3.housing.0','Sewa',root)
   custom=f.create_category(bid,'EXPENSE','Unknown custom name',actor_user_id=owner)
   f.ensure_finance_defaults(bid,actor_user_id=owner)
   self.assertEqual(f.list_categories(bid,'EXPENSE',actor_user_id=owner)[0]['id'],root)
   self.assertEqual(f.list_category_children(bid,root,actor_user_id=owner)[0]['id'],child)
   self.assertEqual(f._category_setting_by_id(bid,custom,owner)['name'],'Unknown custom name')
 def test_completed_v3_never_recreates_deleted_obsolete_rows_or_resets_edits(self):
  bid,owner,branch=self.old_home('cleaned-catalog')
  with branches.scope(bid,branch,owner):
   catalog._sync_reference(bid,owner,f._category_scope(bid,owner))
   obsolete=db.query_one("SELECT category_id FROM finance_catalog_items WHERE business_id=? AND canonical_key='v2.housing.1'",(bid,))['category_id']
   f.ensure_finance_defaults(bid,actor_user_id=owner)
   root=f.list_categories(bid,'EXPENSE',actor_user_id=owner)[0]['id']
   catalog.edit(bid,owner,root,name='Customer edited home',icon_key='care')
   leaf=f.list_category_children(bid,root,actor_user_id=owner)[0]['id'];catalog.edit(bid,owner,leaf,deactivate=True)
   for table,column in (('finance_category_preferences','category_id'),('finance_catalog_items','category_id'),('finance_category_workspace_settings','category_id'),('finance_category_hierarchy','child_category_id'),('finance_categories','id')):db.execute('DELETE FROM '+table+' WHERE '+column+'=?',(obsolete,))
   # Even missing historical v2 completion metadata must not trigger v2 again.
   db.execute('DELETE FROM finance_category_catalog_versions WHERE business_id=? AND version=2',(bid,))
   before={table:[dict(r) for r in db.query_all('SELECT * FROM '+table)] for table in ('finance_categories','finance_category_workspace_settings','finance_category_preferences','finance_catalog_items','finance_category_hierarchy')}
   for _ in range(3):f.ensure_finance_defaults(bid,actor_user_id=owner)
   for table,rows in before.items():self.assertEqual([dict(r) for r in db.query_all('SELECT * FROM '+table)],rows)
   self.assertIsNone(db.query_one('SELECT id FROM finance_categories WHERE id=?',(obsolete,)))
   self.assertFalse(db.query_one('SELECT 1 FROM finance_catalog_items WHERE business_id=? AND canonical_key=?',(bid,'v2.housing.1')))
if __name__=='__main__':unittest.main()
