"""Synthetic cash-basis plans, scopes, exact minor units, and immutable history."""
import io,json,unittest
from unittest.mock import patch
from datetime import date
from werkzeug.datastructures import FileStorage
from PIL import Image
import test_finance_expense_entries as fixture
import db,finance_service as f,finance_branches as branches,finance_installments as plans
import finance_expense_entries as expense,finance_category_catalog as catalog

class PurchasePlanTests(unittest.TestCase):
 setUp=fixture.ExpenseEntryTests.setUp
 categories=fixture.ExpenseEntryTests.categories
 splits=fixture.ExpenseEntryTests.splits
 def create(self,**changes):
  values=dict(amount_minor=12345,currency='IDR',account_id=self.a,category_id=self.categories()[0],purchase_on='2025-08-10',submission_key='b'*32,duration='1',unit='YEARS',frequency='MONTHLY',first_date='2025-09-30',splits=self.splits(),notes='Synthetic purchase',payee='Synthetic shop')
  values.update(changes);return plans.create(self.b,self.uid,**values)
 def items(self,ident):return db.query_all('SELECT * FROM finance_installment_items WHERE plan_id=? ORDER BY sequence',(ident,))
 def test_year_month_custom_schedule_and_exact_rounding_dates(self):
  for unit,duration,freq,count in [('YEARS','1','MONTHLY',12),('MONTHS','12','MONTHLY',12),('YEARS','2','QUARTERLY',8),('YEARS','3','YEARLY',3)]:
   months,rows=plans.schedule(10001,duration=duration,unit=unit,frequency=freq,first_date='2025-01-31')
   self.assertEqual(len(rows),count);self.assertEqual(sum(r['amount_minor'] for r in rows),10001);self.assertTrue(all(r['amount_minor']>0 for r in rows))
   if count==12:self.assertEqual([r['due_on'] for r in rows[:3]],['2025-01-31','2025-02-28','2025-03-31'])
  _,rows=plans.schedule(10001,duration=3,unit='MONTHS',frequency='CUSTOM',first_date='2025-01-31',custom_dates=['2025-01-31','2025-02-15','2025-03-20'],per_payment=3000,count='3')
  self.assertEqual([r['amount_minor'] for r in rows],[3000,3000,4001])
  for changes in [dict(count='99'),dict(per_payment=6000),dict(duration='0'),dict(unit='DAYS'),dict(frequency='CUSTOM',custom_dates=['2025-01-31','2025-01-31'])]:
   with self.assertRaises(f.FinanceError):plans.schedule(10001,**dict(dict(duration=3,unit='MONTHS',frequency='MONTHLY',first_date='2025-01-31'),**changes))
 def test_plan_never_debits_purchase_payments_allocate_once_and_retry_is_atomic(self):
  with branches.scope(self.b,self.branch,self.uid):
   ident=self.create();self.assertEqual(self.create(),ident)
   rows=self.items(ident);self.assertEqual(len(rows),12);self.assertEqual(f.count_transactions(self.b,actor_user_id=self.uid),0)
   for row in rows:
    first=f.record_recurring_payment(self.b,row['recurring_id'],row['due_on'],row['due_on'],actor_user_id=self.uid,account_id=self.a)
    again=f.record_recurring_payment(self.b,row['recurring_id'],row['due_on'],row['due_on'],actor_user_id=self.uid,account_id=self.a)
    self.assertEqual(first['ledger_transaction_id'],again['ledger_transaction_id']);self.assertFalse(again['created'])
   self.assertEqual(f.count_transactions(self.b,actor_user_id=self.uid),12)
   balance={r['id']:r for r in f.get_account_balance_report(self.b,'2026-10-01',self.uid)};self.assertEqual(balance[self.a]['expense_minor'],12345)
   totals={r['category_id']:r['amount_minor'] for r in f.get_category_totals(self.b,'2025-01-01','2026-10-01','EXPENSE',actor_user_id=self.uid)}
   self.assertEqual({v['category_id']:v['amount_minor'] for v in self.splits()},totals)
   with self.assertRaisesRegex(f.FinanceError,'expense_submission_conflict'):self.create(amount_minor=12346,splits=None)
 def test_personal_is_canonical_and_business_branch_foreign_access_rejected(self):
  with branches.scope(self.b,self.personal,self.uid):
   ident=self.create(account_id=self.pa,splits=None)
   self.assertIsNotNone(plans.get(self.b,ident,self.uid));self.assertEqual(f.count_transactions(self.b,actor_user_id=self.uid),0)
  with branches.scope(self.b,self.branch,self.uid):
   self.assertIsNone(plans.get(self.b,ident,self.uid))
   with self.assertRaises(f.FinanceError):self.create(account_id=self.pa,splits=None)
  self.assertEqual(self.client.get(self.url+f'/installments/{ident}?branch_id={self.branch}').status_code,404)
 def test_cross_form_key_conflict_and_receipt_error_roll_back_all_schedules(self):
  with branches.scope(self.b,self.branch,self.uid):
   ident=self.create()
   with self.assertRaisesRegex(f.FinanceError,'expense_submission_conflict'):expense.save(self.b,self.uid,amount_minor=12345,account_id=self.a,category_id=self.categories()[0],occurred_on='2026-09-10',currency='IDR',submission_key='b'*32)
   before=db.query_one('SELECT COUNT(*) AS n FROM finance_recurring_expenses')['n']
   receipt=dict(name='safe.jpg',mime='image/jpeg',raw=b'synthetic',digest='synthetic')
   with patch.object(expense,'receipt_capacity',side_effect=f.FinanceError('expense_receipt_capacity')):
    with self.assertRaises(f.FinanceError):self.create(submission_key='c'*32,receipt=receipt)
   self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_recurring_expenses')['n'],before)
   self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_installment_plans')['n'],1)
 def test_paid_installment_and_future_rule_cannot_silently_change_purchase_total_or_category(self):
  with branches.scope(self.b,self.branch,self.uid):
   ident=self.create();row=self.items(ident)[0];rule=f.get_recurring_expense(self.b,row['recurring_id'],self.uid)
   for changes in [dict(amount_minor=row['amount_minor']+1),dict(cadence='WEEKLY'),dict(end_on=None),dict(next_due_on='2025-10-01')]:
    params=dict(name=rule['name'],amount_minor=rule['amount_minor'],account_id=self.a,category_id=rule['category_id'],cadence='MONTHLY',next_due_on=row['due_on'],end_on=row['due_on'],actor_user_id=self.uid);params.update(changes)
    with self.assertRaises(f.FinanceError):f.update_recurring_expense(self.b,rule['id'],**params)
   payment=f.record_recurring_payment(self.b,rule['id'],row['due_on'],row['due_on'],actor_user_id=self.uid,account_id=self.a)
   with self.assertRaisesRegex(f.FinanceError,'installment_payment_locked'):f.update_bill_payment(self.b,payment['ledger_transaction_id'],actor_user_id=self.uid,amount_minor=100)
 def test_personal_reference_groups_children_order_localized_and_custom_names_unchanged(self):
  with branches.scope(self.b,self.personal,self.uid):
   custom=f.create_category(self.b,'EXPENSE','My custom groceries',actor_user_id=self.uid)
   for language in ('id','en','es','zh'):
    with fixture.fixture.app.test_request_context('/',headers={'Cookie':'kilas_language='+language}):
     roots=f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid)
     expected=['Home/Rent','Food','Utilities','Personal Item','Transportation','Entertainment','Medical','Holiday','Bank Charge','Misc/one-time']
     self.assertEqual([v['name'] for v in roots[:10]],expected)
     self.assertEqual(next(v for v in roots if v['id']==custom)['display_name'],'My custom groceries')
     self.assertEqual([v['display_name'] for v in roots[:10]],expected)
     for root,(_,_,_,children) in zip(roots[:10],catalog.EXPENSE_V4):self.assertEqual([v['display_name'] for v in f.list_category_children(self.b,root['id'],actor_user_id=self.uid)],[pair[1] for pair in children])
   before=db.query_one('SELECT COUNT(*) AS n FROM finance_categories')['n'];f.ensure_finance_defaults(self.b,actor_user_id=self.uid);self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_categories')['n'],before)
 def test_receipt_private_route_and_plan_render_never_show_purchase_as_paid(self):
  image=io.BytesIO();Image.new('RGB',(10,10),'white').save(image,'JPEG')
  receipt=expense.photo(FileStorage(stream=io.BytesIO(image.getvalue()),filename='synthetic.jpg'))
  with branches.scope(self.b,self.branch,self.uid):ident=self.create(receipt=receipt)
  response=self.client.get(self.url+f'/installments/{ident}?branch_id={self.branch}');self.assertEqual(response.status_code,200)
  raw=self.client.get(self.url+f'/installments/{ident}/receipt?branch_id={self.branch}');self.assertEqual(raw.data,image.getvalue());self.assertEqual(raw.headers['Cache-Control'],'private, no-store')
  self.assertEqual(self.client.get(self.url+f'/installments/{ident}/receipt?branch_id={self.personal}').status_code,404)
 def test_next_month_and_stop_configuration_reuse_unpaid_rules_and_preserve_paid_history(self):
  self.client.set_cookie('kilas_language','en')
  with branches.scope(self.b,self.branch,self.uid):
   category=self.categories()[0]
   fields=dict(name='Synthetic recurring',amount='100.01',currency='IDR',category_id=category,cadence='MONTHLY',next_due_on='2026-10-31',begin_next_month='1',end_mode='DATE',end_on='2027-01-31')
   selected=next(v for v in f.list_categories(self.b,'EXPENSE',include_children=True,actor_user_id=self.uid) if v['id']==category)
   if selected.get('parent_category_id'):fields.update(category_id=selected['parent_category_id'],subcategory_id=category)
   with patch.object(f,'business_today',return_value=date(2026,10,18)):
    response=self.client.post(self.url+f'/recurring?branch_id={self.branch}',data=fields)
   self.assertEqual(response.status_code,303);rule=f.list_recurring_expenses(self.b,actor_user_id=self.uid)[0]
   self.assertEqual(rule['next_due_on'],'2026-11-30');self.assertEqual(rule['end_on'],'2027-01-31');self.assertEqual(f.count_transactions(self.b,actor_user_id=self.uid),0)
   # Changing the future schedule neither creates nor edits a paid posting.
   f.update_recurring_expense(self.b,rule['id'],name=rule['name'],amount_minor=rule['amount_minor'],account_id=self.a,category_id=category,cadence='MONTHLY',next_due_on='2025-01-31',end_on='2025-03-31',actor_user_id=self.uid)
   paid=f.record_recurring_payment(self.b,rule['id'],'2025-01-31','2025-01-31',actor_user_id=self.uid,account_id=self.a)
   before=dict(f.get_transaction(self.b,paid['ledger_transaction_id'],actor_user_id=self.uid))
   f.update_recurring_expense(self.b,rule['id'],name='Updated',amount_minor=10001,account_id=self.a,category_id=category,cadence='MONTHLY',next_due_on='2025-02-28',end_on=None,actor_user_id=self.uid)
   self.assertEqual(dict(f.get_transaction(self.b,paid['ledger_transaction_id'],actor_user_id=self.uid)),before)
 def test_concurrent_identical_save_has_one_plan_and_finite_schedule(self):
  from concurrent.futures import ThreadPoolExecutor
  from threading import Barrier
  barrier=Barrier(2)
  def create(_):
   try:
    with branches.scope(self.b,self.branch,self.uid):barrier.wait();return self.create()
   finally:db._discard_cached_connection()
  with ThreadPoolExecutor(max_workers=2) as pool:ids=list(pool.map(create,range(2)))
  self.assertEqual(ids[0],ids[1]);self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_installment_plans')['n'],1);self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_recurring_expenses')['n'],12)
 def test_builtin_rename_and_unknown_legacy_category_remain_customer_owned(self):
  with branches.scope(self.b,self.personal,self.uid):
   roots=f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid);chosen=roots[0]
   f.update_category_workspace_setting(self.b,chosen['id'],name='Custom home label',actor_user_id=self.uid)
   custom=f.create_category(self.b,'EXPENSE','Belanja Pribadi',actor_user_id=self.uid)
   f.sync_business_category_catalog(self.b,actor_user_id=self.uid)
   with fixture.fixture.app.test_request_context('/',headers={'Cookie':'kilas_language=en'}):
    rows=f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid);self.assertEqual(next(v for v in rows if v['id']==chosen['id'])['display_name'],'Custom home label');self.assertEqual(next(v for v in rows if v['id']==custom)['display_name'],'Belanja Pribadi')
 def test_dashboard_six_card_order_and_instant_dynamic_account_filter_contract(self):
  self.client.set_cookie('kilas_language','en')
  response=self.client.get(self.url+f'?branch_id={self.branch}&month=2026-09');self.assertEqual(response.status_code,200)
  import re
  self.assertEqual(re.findall('data-finance-metric="([^"]+)"',response.text),['income','expense','account','bill','invoice','people'])
  response=self.client.get(self.url+f'?branch_id={self.branch}&month=2026-09&view=transactions&direction=EXPENSE')
  self.assertIn('data-finance-instant-filter',response.text)
  match=re.search(r'<form class="finance-transaction-search".*?</form>',response.text,re.S)
  self.assertIsNotNone(match);self.assertIn('value="'+str(self.a)+'"',match[0]);self.assertNotIn('Apply',match[0])
 def test_existing_exact_category_is_reused_without_guessing_custom_provenance(self):
  import repo
  owner=repo.create_user('catalog-owner@example.test','unused');business=repo.create_business(owner,'Synthetic second business');personal=branches.ensure_personal(business,owner)
  with branches.scope(business,personal,owner):
   custom=f.create_category(business,'EXPENSE','Transportasi',actor_user_id=owner)
   f.ensure_finance_defaults(business,actor_user_id=owner)
   with fixture.fixture.app.test_request_context('/',headers={'Cookie':'kilas_language=en'}):
    rows=f.list_categories(business,'EXPENSE',actor_user_id=owner)
    # The new final built-in and the unproven customer-owned root stay distinct.
    self.assertEqual(len([v for v in rows if v['name']=='Transportasi']),1)
    self.assertEqual(len([v for v in rows if v['display_name']=='Transportation' and v['builtin_default']]),1)
    self.assertEqual(next(v for v in rows if v['id']==custom)['display_name'],'Transportasi')
 def test_business_defaults_are_distinct_localized_without_translating_custom_names(self):
  with branches.scope(self.b,self.branch,self.uid):
   custom=f.create_category(self.b,'EXPENSE','Customer-owned ABC',actor_user_id=self.uid)
   for language in ('id','en','es','zh'):
    with fixture.fixture.app.test_request_context('/',headers={'Cookie':'kilas_language='+language}):
     rows=f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid)
     self.assertEqual(len([v for v in rows if v['builtin_default']]),10)
     self.assertEqual(next(v for v in rows if v['id']==custom)['display_name'],'Customer-owned ABC')
     self.assertNotIn('housing',[v['canonical_key'] for v in db.query_all('SELECT canonical_key FROM finance_catalog_items WHERE business_id=? AND scope_key=?',(self.b,'BUSINESS'))])
     self.assertIn('Home/Rent',[v['display_name'] for v in rows])

 def test_plan_linked_account_cannot_move_away_from_scoped_schedule(self):
  with branches.scope(self.b,self.branch,self.uid):
   ident=self.create()
   with self.assertRaisesRegex(f.FinanceError,'workspace_move_managed'):
    f.move_account_workspace(self.b,self.a,self.personal,actor_user_id=self.uid)
   self.assertEqual(plans.get(self.b,ident,self.uid)['account_id'],self.a)
   self.assertEqual(len(self.items(ident)),12)
   self.assertEqual(f.count_transactions(self.b,actor_user_id=self.uid),0)
