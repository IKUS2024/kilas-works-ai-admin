"""Exact old Personal seed reproduction: 23 effective choices -> ten, no data rewrite."""
import json,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import test_finance_expense_entries as fixture
import db,repo
import finance_service as f,finance_branches as branches
import finance_category_catalog as catalog
import finance_expense_entries as expenses

EXPECTED=['Home/Rent','Food','Utilities','Personal Item','Transportation','Entertainment','Medical','Holiday','Bank Charge','Misc/one-time']
BEFORE=['Home/Rent','Food','Transportasi','Utilities','Personal Item','Utilitas','Kesehatan','Transportation','Entertainment','Medical','Holiday','Bank Charge','Misc/one-time','Asuransi','Belanja Pribadi','Biaya Tak Terduga','Cicilan / Utang','Donasi','Hiburan','Keluarga','Makanan & Belanja Harian','Pendidikan','Tempat Tinggal / Sewa']

class LegacySeedProvenanceTests(unittest.TestCase):
 setUp=fixture.ExpenseEntryTests.setUp
 def legacy(self):
  owner=repo.create_user('legacy-seed@example.test','unused');bid=repo.create_business(owner,'Synthetic exact legacy');branch=branches.ensure_personal(bid,owner)
  self.started=datetime(2026,10,3,1,35,48,988075,tzinfo=timezone.utc);stamp=(self.started+timedelta(microseconds=17004)).isoformat();old='2026-09-23T12:53:13.398232+00:00'
  db.execute('UPDATE finance_branch_workspaces SET created_at=? WHERE business_id=? AND branch_id=?',(self.started.isoformat(),bid,branch))
  db.execute("UPDATE audit_log SET created_at=? WHERE business_id=? AND action='FINANCE_PERSONAL_WORKSPACE_CREATED' AND detail=?",((self.started-timedelta(milliseconds=26)).isoformat(),bid,'finance_record_id='+str(branch)))
  roots={};new=[];all_seed=[]
  def node(direction,name,index,reused=False,parent=None):
   ident=f._create_category(bid,direction,name,owner);f._ensure_category_setting(bid,ident,name,owner)
   if parent:f._link_category_parent(bid,ident,parent)
   made=(self.started+timedelta(milliseconds=100+index*20)).isoformat();created=old if reused else made
   db.execute('UPDATE finance_categories SET created_at=?,updated_at=? WHERE id=?',(created,created,ident))
   db.execute('UPDATE finance_category_workspace_settings SET created_at=?,updated_at=? WHERE business_id=? AND scope_key=? AND category_id=?',(made,made,bid,'PERSONAL:'+str(owner),ident))
   if not reused:new.append(ident)
   all_seed.append(ident);return ident
  with branches.scope(bid,branch,owner):
   for i,name in enumerate(catalog.LEGACY_PERSONAL_INCOME):node('INCOME',name,i)
   reused={'Utilitas','Transportasi','Biaya Tak Terduga','Makanan & Belanja Harian','Asuransi'}
   for i,name in enumerate(catalog.LEGACY_PERSONAL_ROOTS):roots[name]=node('EXPENSE',name,i+5,name in reused)
   utilities=[]
   for i,name in enumerate(catalog.LEGACY_PERSONAL_UTILITIES):utilities.append(node('EXPENSE',name,i+20,True,roots['Utilitas']))
   for ident in new:db.execute("UPDATE audit_log SET created_at=? WHERE business_id=? AND action='FINANCE_CATEGORY_CREATED' AND detail=?",(stamp,bid,'finance_record_id='+str(ident)))
   # v1 reused exact legacy names conservatively as customer-owned, even though
   # these scoped choices came from the proven original initialization batch.
   for key,name,order in [('utilities','Utilitas',300),('transport','Transportasi',200),('health','Kesehatan',400)]:catalog.mark(bid,'PERSONAL:'+str(owner),key,roots[name],order,'__customer_owned__')
   for i,ident in enumerate(utilities[:4]):catalog.mark(bid,'PERSONAL:'+str(owner),'utilities.'+str(i),ident,300+i,'__customer_owned__')
   for root_name,key,names in [('Transportasi','transport',('Bahan Bakar','Parkir','Tol','Sewa Mobil','Transportasi Umum')),('Kesehatan','health',('Perawatan Medis','Obat'))]:
    for i,name in enumerate(names):
     ident=f._create_category(bid,'EXPENSE','__kilas_fixture_'+key+str(i),owner);f._ensure_category_setting(bid,ident,name,owner);f._link_category_parent(bid,ident,roots[root_name]);catalog.mark(bid,'PERSONAL:'+str(owner),key+'.'+str(i),ident,i,name)
   account=f.create_account(bid,'Synthetic legacy cash','CASH',actor_user_id=owner)
   tx=f.create_transaction(bid,'EXPENSE',10001,account,roots['Transportasi'],'2025-01-01',actor_user_id=owner)
   f.ensure_finance_defaults(bid,actor_user_id=owner)
  return bid,owner,branch,roots,utilities,tx
 def names(self,bid,owner):return [r['display_name'] for r in f.list_categories(bid,'EXPENSE',actor_user_id=owner)]
 def snapshot(self):return {t:[dict(r) for r in db.query_all('SELECT * FROM '+t)] for t in ['finance_categories','finance_category_workspace_settings','finance_category_hierarchy','finance_catalog_items','finance_category_preferences','finance_category_catalog_versions','finance_transactions','finance_expense_allocations','finance_recurring_expenses']}
 def test_exact_reported_23_choice_legacy_becomes_ten_without_any_stored_row_changes(self):
  bid,owner,branch,roots,utilities,tx=self.legacy()
  with branches.scope(bid,branch,owner):
   with patch.object(catalog,'_legacy_seed_ids',return_value=set()):self.assertEqual(self.names(bid,owner),BEFORE)
   before=self.snapshot();self.assertEqual(self.names(bid,owner),EXPECTED);self.assertEqual(before,self.snapshot())
   all_rows=f.list_categories(bid,'EXPENSE',include_inactive=True,include_children=True,actor_user_id=owner)
   self.assertTrue(set(roots.values())|set(utilities)<={r['id'] for r in all_rows if r['default_retired']})
   self.assertTrue(f._category_setting_by_id(bid,roots['Utilitas'],owner)['is_active'])
   edit=expenses.edit_categories(bid,tx,owner);self.assertTrue(next(r for r in edit if r['id']==roots['Transportasi'])['retained'])
   self.assertEqual(f.get_transaction(bid,tx,actor_user_id=owner)['category_id'],roots['Transportasi'])
 def test_real_edit_even_to_same_label_prevents_legacy_proof(self):
  bid,owner,branch,roots,_,_=self.legacy()
  with branches.scope(bid,branch,owner):
   catalog.edit(bid,owner,roots['Utilitas'],name='Utilitas')
   self.assertIn('Utilitas',self.names(bid,owner))
 def test_later_custom_child_is_preserved_with_its_original_parent(self):
  bid,owner,branch,roots,_,_=self.legacy()
  with branches.scope(bid,branch,owner):
   child=f.create_category(bid,'EXPENSE','Customer solar contract',parent_category_id=roots['Utilitas'],actor_user_id=owner)
   self.assertIn('Utilitas',self.names(bid,owner))
   self.assertEqual(f.list_category_children(bid,roots['Utilitas'],actor_user_id=owner)[0]['id'],child)
 def test_missing_or_coarse_or_mixed_audit_batch_cannot_classify_custom_rows(self):
  bid,owner,branch,roots,_,_=self.legacy()
  with branches.scope(bid,branch,owner):
   for mode in ('missing','coarse','mixed','wrong_owner'):
    with self.subTest(mode=mode):
     before=[dict(r) for r in db.query_all('SELECT * FROM audit_log')]
     if mode=='missing':db.execute("DELETE FROM audit_log WHERE business_id=? AND action='FINANCE_PERSONAL_WORKSPACE_CREATED'",(bid,))
     if mode=='coarse':db.execute("UPDATE audit_log SET created_at='2026-10-03T01:35:49+00:00' WHERE business_id=? AND action='FINANCE_CATEGORY_CREATED'",(bid,))
     if mode=='mixed':db.execute("UPDATE audit_log SET created_at='2026-10-03T01:35:49.123456+00:00' WHERE business_id=? AND detail=? AND action='FINANCE_CATEGORY_CREATED'",(bid,'finance_record_id='+str(roots['Keluarga'])))
     if mode=='wrong_owner':db.execute("UPDATE audit_log SET actor_user_id=? WHERE business_id=? AND action='FINANCE_CATEGORY_CREATED'",(self.uid,bid))
     self.assertEqual(self.names(bid,owner),BEFORE)
     # Synthetic fixture rollback only; production diagnosis uses read-only SQL.
     db.execute('DELETE FROM audit_log')
     for row in before:
      columns=list(row);db.execute('INSERT INTO audit_log ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',tuple(row[c] for c in columns))
 def test_policy_disable_restores_legacy_choices_and_business_scope_never_uses_personal_proof(self):
  bid,owner,branch,roots,_,_=self.legacy()
  with branches.scope(bid,branch,owner):
   policy=catalog._expense_policy(bid,f._category_scope(bid,owner));policy['enabled']=False
   db.execute('UPDATE finance_category_catalog_versions SET changes_json=? WHERE business_id=? AND scope_key=? AND version=4',(json.dumps(policy),bid,'PERSONAL:'+str(owner)))
   self.assertEqual(set(self.names(bid,owner)),set(catalog.LEGACY_PERSONAL_ROOTS))
  with branches.scope(self.b,self.branch,self.uid):self.assertEqual(catalog._legacy_seed_ids(self.b,f._category_scope(self.b,self.uid),{}),set())

if __name__=='__main__':unittest.main()
