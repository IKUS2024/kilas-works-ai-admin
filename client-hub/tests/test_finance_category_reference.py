"""Scoped reference/presentation controls; disposable ledgers, no external IO."""
import json,unittest
from unittest.mock import patch
from werkzeug.datastructures import MultiDict
import test_finance_expense_entries as fixture
import db,repo,finance_service as f,finance_branches as branches
import finance_category_catalog as catalog,finance_expense_entries as expenses,finance_personal
class CategoryReferenceTests(unittest.TestCase):
 setUp=fixture.ExpenseEntryTests.setUp
 def rows(self,scope=None,**kw):
  with branches.scope(self.b,scope or self.personal,self.uid):return f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid,**kw)
 def test_exact_reference_order_children_four_locales_and_no_invented_children(self):
  expected=['Home/Rent','Utilities','Food/Groceries','Departmental','Entertainment','Car/Auto','Insurance/Medical','Misc/One-time','Investment','Bank Charge','Salaries']
  expected_children=[['Mortgage','Mortgage-2nd','Rent','Association fee','Property tax'],['Electricity','Gas/Heating','Telephone','CellPhone','Internet','Cable/Dish','Water','Garbage','Laundry','Cleaning'],['Groceries','Restaurant/Fast food'],['Clothing','Personal items','Kids/Toys','Books/Magazines','Beauty Care'],['Movies','DVD rental','Music','Appstore','Tune Core','Musik Produce'],['Gasoline','Auto Loan','Service Car','e-Toll','Online Transportation','Parking'],['Insurance - Auto','Insurance - Home','Insurance - Medical','Medical Expenses/Co-pay','Treatment'],['Air tickets','Hotel/Lodging','Gifts/Charity','Family'],[],[],[]]
  with branches.scope(self.b,self.personal,self.uid):
   custom=f.create_category(self.b,'EXPENSE','Customer name ABC',actor_user_id=self.uid)
   before=db.query_one('SELECT count(*) AS n FROM finance_categories')['n']
   for language in ('id','en','es','zh'):
    with fixture.fixture.app.test_request_context('/',headers={'Cookie':'kilas_language='+language}):
     roots=f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid)
     self.assertEqual([v['name'] for v in roots[:11]],[v[1] for v in catalog.PERSONAL_V2])
     if language=='en':self.assertEqual([v['display_name'] for v in roots[:11]],expected)
     self.assertEqual(next(v['display_name'] for v in roots if v['id']==custom),'Customer name ABC')
     for index,(root,(_,_,_,names)) in enumerate(zip(roots,catalog.PERSONAL_V2)):
      children=f.list_category_children(self.b,root['id'],actor_user_id=self.uid);self.assertEqual([v['name'] for v in children],list(names));self.assertTrue(all(v['display_name'] for v in children))
      if language=='en':self.assertEqual([v['display_name'] for v in children],expected_children[index])
   f.ensure_finance_defaults(self.b,actor_user_id=self.uid);self.assertEqual(db.query_one('SELECT count(*) AS n FROM finance_categories')['n'],before)
   self.assertEqual(finance_personal.resolve_home(self.uid)['branch_id'],self.personal)
 def test_known_legacy_ids_links_and_transaction_survive_version_update_and_journal(self):
  owner=repo.create_user('reference-legacy@example.test','unused');business=repo.create_business(owner,'Synthetic legacy');personal=branches.ensure_personal(business,owner)
  with branches.scope(business,personal,owner):
   root=f._create_category(business,'EXPENSE','private-old-house',owner);f._ensure_category_setting(business,root,'Tempat Tinggal',owner);catalog.mark(business,'PERSONAL:'+str(owner),'housing',root,0,'Tempat Tinggal')
   child=f._create_category(business,'EXPENSE','private-old-rent',owner);f._ensure_category_setting(business,child,'Sewa',owner);f._link_category_parent(business,child,root);catalog.mark(business,'PERSONAL:'+str(owner),'housing.0',child,1,'Sewa')
   account=f.list_accounts(business,actor_user_id=owner)[0]['id'];tx=f.create_transaction(business,'EXPENSE',10001,account,child,'2025-01-01',actor_user_id=owner);before=dict(f.get_transaction(business,tx,actor_user_id=owner))
   f.ensure_finance_defaults(business,actor_user_id=owner)
   rows=f.list_categories(business,'EXPENSE',include_children=True,actor_user_id=owner);self.assertEqual(next(v['id'] for v in rows if v['name']=='Rumah / Sewa'),root);self.assertEqual(next(v['id'] for v in rows if v['name']=='Sewa'),child)
   self.assertEqual(dict(f.get_transaction(business,tx,actor_user_id=owner)),before);self.assertEqual(db.query_one('SELECT parent_category_id FROM finance_category_hierarchy WHERE child_category_id=?',(child,))['parent_category_id'],root)
   self.assertEqual(db.query_one('SELECT category_id FROM finance_catalog_items WHERE business_id=? AND canonical_key=?',(business,'housing'))['category_id'],root)
   journal=db.query_one('SELECT changes_json FROM finance_category_catalog_versions WHERE business_id=?',(business,));self.assertTrue(any(v.get('before',{}).get('category_id')==root for v in json.loads(journal['changes_json'])))
 def test_edited_builtin_and_unknown_same_name_are_not_renamed_or_merged(self):
  with branches.scope(self.b,self.personal,self.uid):
   root=self.rows()[0]
   with fixture.fixture.app.test_request_context('/',headers={'Cookie':'kilas_language=en'}):
    localized=next(v for v in self.rows() if v['id']==root['id']);catalog.edit(self.b,self.uid,root['id'],name=localized['display_name'],icon_key='home');self.assertEqual(f._category_setting_by_id(self.b,root['id'],self.uid)['name'],root['name'])
   catalog.edit(self.b,self.uid,root['id'],name='Customer renamed home',icon_key='digital')
   for lang in ('en','zh'):
    with fixture.fixture.app.test_request_context('/',headers={'Cookie':'kilas_language='+lang}):self.assertEqual(next(v['display_name'] for v in self.rows() if v['id']==root['id']),'Customer renamed home')
   f.ensure_finance_defaults(self.b,actor_user_id=self.uid);self.assertEqual(next(v['name'] for v in self.rows() if v['id']==root['id']),'Customer renamed home')
 def test_parent_filtered_create_same_named_children_and_server_relations(self):
  with branches.scope(self.b,self.personal,self.uid):
   roots=self.rows();a,b=roots[0]['id'],roots[1]['id']
   x=f.create_category(self.b,'EXPENSE','Custom child',parent_category_id=a,actor_user_id=self.uid);y=f.create_category(self.b,'EXPENSE','Custom child',parent_category_id=b,actor_user_id=self.uid);self.assertNotEqual(x,y)
   self.assertEqual(f.resolve_category_selection(self.b,'EXPENSE',a,x,actor_user_id=self.uid),x)
   with self.assertRaises(f.FinanceError):f.resolve_category_selection(self.b,'EXPENSE',b,x,actor_user_id=self.uid)
   with self.assertRaises(f.FinanceError):f.create_category(self.b,'EXPENSE','Foreign child',parent_category_id=self.categories_business()[0],actor_user_id=self.uid)
 def categories_business(self):
  with branches.scope(self.b,self.branch,self.uid):return [v['id'] for v in f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid)]
 def test_http_order_icon_archive_and_invalid_requests_are_atomic_and_scoped(self):
  roots=self.rows();ids=[v['id'] for v in roots];url=self.url+'/categories?branch_id='+str(self.personal);headers={'X-Requested-With':'XMLHttpRequest'}
  data=MultiDict([('csrf_token','finance-csrf'),('action','order'),('direction','EXPENSE')]+[('category_ids',str(v)) for v in reversed(ids)])
  self.assertEqual(self.client.post(url,data=data,headers=headers).status_code,200);self.assertEqual([v['id'] for v in self.rows()],list(reversed(ids)))
  bad=MultiDict(data);bad.setlist('category_ids',[str(v) for v in ids[:-1]]+[str(self.categories_business()[0])]);self.assertEqual(self.client.post(url,data=bad,headers=headers).status_code,400);self.assertEqual([v['id'] for v in self.rows()],list(reversed(ids)))
  before=db.query_one('SELECT count(*) AS n FROM finance_categories')['n'];self.assertEqual(self.client.post(url,data=dict(csrf_token='finance-csrf',action='create',direction='EXPENSE',name='Bad icon',icon_key='javascript:bad'),headers=headers).status_code,400);self.assertEqual(db.query_one('SELECT count(*) AS n FROM finance_categories')['n'],before)
  ident=ids[-1]
  self.assertEqual(self.client.post(url,data=dict(csrf_token='finance-csrf',action='edit',direction='EXPENSE',category_id=ident,name='Custom payroll',icon_key='work'),headers=headers).status_code,200)
  self.assertEqual(self.client.post(url,data=dict(csrf_token='finance-csrf',action='delete',direction='EXPENSE',category_id=ident),headers=headers).status_code,200)
  with branches.scope(self.b,self.personal,self.uid):f.ensure_finance_defaults(self.b,actor_user_id=self.uid)
  self.assertNotIn(ident,[v['id'] for v in self.rows()]);self.assertTrue(db.query_one('SELECT id FROM finance_categories WHERE id=?',(ident,)))
 def test_archived_expense_and_splits_edit_unchanged_without_changing_reports_or_links(self):
  with branches.scope(self.b,self.personal,self.uid):
   root=self.rows()[0];children=f.list_category_children(self.b,root['id'],actor_user_id=self.uid);a,b=children[0]['id'],children[1]['id']
   tx=expenses.save(self.b,self.uid,amount_minor=10001,account_id=self.pa,category_id=a,occurred_on='2025-01-01',currency='IDR',splits=[dict(category_id=a,amount_minor=5000),dict(category_id=b,amount_minor=5001)],submission_key='d'*32)
   f.update_category_workspace_setting(self.b,root['id'],deactivate=True,actor_user_id=self.uid)
   before=expenses.allocations(self.b,tx,self.uid);data=MultiDict([('csrf_token','finance-csrf'),('amount','100.01'),('account_id',str(self.pa)),('occurred_on','2025-01-01'),('split_enabled','1'),('notes','Edited note')])
   for child,amount in ((a,'50'),(b,'50.01')):data.add('split_category_id',str(root['id']));data.add('split_subcategory_id',str(child));data.add('split_amount',amount)
   page=self.client.get(self.url+f'/transactions/{tx}/edit?branch_id={self.personal}');self.assertEqual(page.status_code,200);self.assertIn(str(a),page.text)
   response=self.client.post(self.url+f'/transactions/{tx}/edit?branch_id={self.personal}',data=data);self.assertEqual(response.status_code,303)
   self.assertEqual(f.get_transaction(self.b,tx,actor_user_id=self.uid)['notes'],'Edited note');self.assertEqual(expenses.allocations(self.b,tx,self.uid),before)
   with self.assertRaises(f.FinanceError):expenses.validate(self.b,10001,before,self.uid)
   self.assertEqual(f.count_transactions(self.b,actor_user_id=self.uid),1)
 def test_pre_reference_customer_renamed_parent_keeps_its_children_and_ids(self):
  owner=repo.create_user('reference-custom-legacy@example.test','unused');business=repo.create_business(owner,'Synthetic custom legacy');personal=branches.ensure_personal(business,owner)
  with branches.scope(business,personal,owner):
   root=f._create_category(business,'EXPENSE','private-custom-house',owner);f._ensure_category_setting(business,root,'Customer home legacy',owner);catalog.mark(business,'PERSONAL:'+str(owner),'housing',root,0,'Tempat Tinggal')
   child=f._create_category(business,'EXPENSE','private-custom-maintenance',owner);f._ensure_category_setting(business,child,'Perawatan',owner);f._link_category_parent(business,child,root);catalog.mark(business,'PERSONAL:'+str(owner),'housing.1',child,1,'Perawatan')
   f.ensure_finance_defaults(business,actor_user_id=owner);self.assertTrue(f._category_setting_by_id(business,root,owner)['is_active']);self.assertTrue(f._category_setting_by_id(business,child,owner)['is_active']);self.assertEqual(f._category_setting_by_id(business,root,owner)['name'],'Customer home legacy');self.assertEqual(f.list_category_children(business,root,actor_user_id=owner)[0]['id'],child)
   fresh=next(v for v in f.list_categories(business,'EXPENSE',actor_user_id=owner) if v['name']=='Rumah / Sewa');self.assertNotEqual(root,fresh['id'])
 def test_archive_shared_business_category_cannot_break_active_bill_in_another_branch(self):
  other=branches.create_branch(self.b,'Other synthetic branch',self.uid)
  with branches.scope(self.b,other,self.uid):
   f.ensure_finance_defaults(self.b,actor_user_id=self.uid);account=f.list_accounts(self.b,actor_user_id=self.uid)[0]['id'];leaf=next(v for v in f.list_categories(self.b,'EXPENSE',include_children=True,actor_user_id=self.uid) if not f.list_category_children(self.b,v['id'],actor_user_id=self.uid));f.create_recurring_expense(self.b,'Synthetic other-branch bill',1000,account,leaf['id'],'MONTHLY','2025-01-31',actor_user_id=self.uid)
  with branches.scope(self.b,self.branch,self.uid):
   with self.assertRaisesRegex(f.FinanceError,'category_in_use'):catalog.edit(self.b,self.uid,leaf['id'],deactivate=True)
   self.assertTrue(f._category_setting_by_id(self.b,leaf['id'],self.uid)['is_active'])
