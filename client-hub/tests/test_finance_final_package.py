"""Final catalog, scanner and Business Income contracts. No external calls."""
import io,json,unittest
from unittest.mock import patch
from itsdangerous import URLSafeTimedSerializer
from PIL import Image
import test_finance_expense_entries as fixture
import db,finance_service as f,finance_branches as branches,finance_category_catalog as catalog
import finance_receipts as receipts,finance_entitlements as entitlements
from kilas_ai import usage

class FinalFinanceTests(unittest.TestCase):
 setUp=fixture.ExpenseEntryTests.setUp
 def photo(self):
  stream=io.BytesIO();Image.new('RGB',(20,20),'white').save(stream,'PNG');return stream.getvalue()
 def result(self,category=None):return dict(merchant_name='Synthetic shop',transaction_date='2026-09-10',total_minor=1234500,currency='IDR',receipt_number='TEST-1',description='Synthetic purchase',suggested_category_name=category,readable=True)
 def scanner(self,result=None):
  from contextlib import ExitStack
  stack=ExitStack();self.addCleanup(stack.close)
  stack.enter_context(patch('kilas_ai.workspace_execution_access.entitled',return_value=True))
  stack.enter_context(patch('finance_receipts.signer',return_value=URLSafeTimedSerializer('synthetic-test-signing-key-only',salt='receipt-test')))
  stack.enter_context(patch('finance_ai_safety.allow_attempt',return_value=True))
  model=stack.enter_context(patch('kilas_ai.chat_models.check',return_value={'available':True,'images':True}))
  reserve=stack.enter_context(patch('kilas_ai.usage.reserve',return_value=('PRO',('CHAT',))))
  finish=stack.enter_context(patch('kilas_ai.usage.finish'))
  stream=stack.enter_context(patch('kilas_ai.providers._openai',return_value=iter([{'type':'usage','input_tokens':200,'output_tokens':100},{'type':'delta','text':json.dumps(result or self.result())},{'type':'finish','reason':'stop'}])))
  return reserve,finish,stream
 def test_business_income_no_category_customer_account_credit_and_edit_preserves_legacy(self):
  self.client.post(self.url+'/transactions',data=dict(branch_id=self.branch,direction='INCOME',account_id=self.a,amount='100.01',occurred_on='2026-09-10',description='Synthetic income'))
  row=db.query_one('SELECT * FROM finance_transactions ORDER BY id DESC LIMIT 1');self.assertIsNotNone(row);self.assertEqual(row['amount_minor'],10001);self.assertIsNone(row['customer_id'])
  legacy=f.create_transaction(self.b,'INCOME',321,self.a,self.cat,'2026-09-10',customer_id=self.c,counterparty_name='Legacy customer',actor_user_id=self.uid)
  old=f.get_transaction(self.b,legacy,actor_user_id=self.uid)
  page=self.client.get(self.url+f'/transactions/{legacy}/edit?branch_id={self.branch}');self.assertNotIn('name="category_id"',page.text)
  response=self.client.post(self.url+f'/transactions/{legacy}/edit',data=dict(branch_id=self.branch,account_id=self.a,amount='4.32',occurred_on='2026-09-10',description='Edited income',expected_updated_at=old['updated_at']))
  self.assertEqual(response.status_code,303)
  new=f.get_transaction(self.b,legacy,actor_user_id=self.uid);self.assertEqual((new['category_id'],new['customer_id'],new['counterparty_name']),(old['category_id'],old['customer_id'],old['counterparty_name']));self.assertEqual(new['amount_minor'],432)
  with branches.scope(self.b,self.branch,self.uid):self.assertEqual(f.get_account_balance_report(self.b,'2026-09-30',self.uid)[0]['income_minor'],10433)
 def test_personal_income_still_requires_description_and_foreign_account_denied(self):
  before=db.query_one('SELECT count(*) n FROM finance_transactions')['n']
  self.client.post(self.url+'/transactions',data=dict(branch_id=self.personal,direction='INCOME',account_id=self.pa,amount='1',occurred_on='2026-09-10'))
  self.client.post(self.url+'/transactions',data=dict(branch_id=self.branch,direction='INCOME',account_id=self.pa,amount='1',occurred_on='2026-09-10'))
  self.assertEqual(db.query_one('SELECT count(*) n FROM finance_transactions')['n'],before)
 def test_scanner_http_review_no_autosave_then_exact_idempotent_confirmation(self):
  reserve,finish,stream=self.scanner()
  response=self.client.post(self.url+'/receipts/analyze',data={'branch_id':self.branch,'receipt':(io.BytesIO(self.photo()),'receipt.png')})
  self.assertEqual(response.status_code,200);self.assertIn('Synthetic shop',response.text);self.assertIn('12345.00',response.text);self.assertEqual(db.query_one('SELECT count(*) n FROM finance_transactions')['n'],0)
  import re
  token=re.search('name="analysis_token" value="([^"]+)"',response.text)[1]
  with branches.scope(self.b,self.branch,self.uid):category=receipts.options(self.b,self.uid)[1][0]['id']
  data=dict(branch_id=self.branch,analysis_token=token,confirmed='yes',currency='IDR',amount='12345.00',occurred_on='2026-09-10',account_id=str(self.a),category_id=str(category),merchant_name='Reviewed shop',description='Edited review')
  for _ in range(2):self.assertEqual(self.client.post(self.url+'/receipts/confirm',data=data).status_code,302)
  self.assertEqual(db.query_one('SELECT count(*) n FROM finance_transactions')['n'],1);self.assertEqual(reserve.call_count,1);self.assertEqual(stream.call_count,1);self.assertTrue(finish.call_args.kwargs['success'])
  saved=db.query_one('SELECT * FROM finance_transactions ORDER BY id DESC LIMIT 1')
  page=self.client.get(self.url+f'/transactions/{saved["id"]}/edit?branch_id={self.branch}');self.assertIn('data-expense-category-only',page.text);self.assertIn('data-expense-cascade',page.text)
  with branches.scope(self.b,self.branch,self.uid):
   selected=next(v for v in receipts.options(self.b,self.uid)[1] if v['id']==category);parent=selected.get('parent_category_id') or category
  response=self.client.post(self.url+f'/transactions/{saved["id"]}/edit',data=dict(branch_id=self.branch,account_id=self.a,amount='12345.00',occurred_on='2026-09-10',category_id=parent,subcategory_id=category if parent!=category else '',description='Reviewed edit',expected_updated_at=saved['updated_at']))
  self.assertEqual(response.status_code,303);self.assertEqual(db.query_one('SELECT count(*) n FROM finance_transactions')['n'],1)
  args=stream.call_args;self.assertEqual(args.args[0],'gpt-6-luna');self.assertEqual(args.kwargs['profile']['output_tokens'],2048);self.assertTrue(args.kwargs['response_format']['json_schema']['strict'])
 def test_scanner_unavailable_suggestion_not_invented_and_invalid_category_denied(self):
  value=self.result('Foreign unavailable category');self.scanner(value)
  with fixture.fixture.app.test_request_context('/'),branches.scope(self.b,self.branch,self.uid):
   review=receipts.analyze(self.b,self.uid,'receipt.png',self.photo());self.assertIsNone(review['extraction']['suggested_category_name']);self.assertEqual(review['extraction']['total_minor'],1234500)
   fields=dict(confirmed='yes',currency='IDR',amount='1',occurred_on='2026-09-10',account_id=str(self.a),category_id=str(db.query_one('SELECT id FROM finance_categories WHERE business_id=? AND direction=?',(self.other,'EXPENSE'))['id']),merchant_name='',description='')
   with self.assertRaises(ValueError):receipts.confirm(self.b,self.uid,review['token'],fields)
   with self.assertRaises(ValueError):receipts.resolve_token(review['token'],self.other,self.other_uid)
 def test_scanner_capacity_idempotent_and_ambiguous_failure_do_not_retry(self):
  reserve,finish,stream=self.scanner()
  with fixture.fixture.app.test_request_context('/'),branches.scope(self.b,self.branch,self.uid):
   reserve.return_value=(None,())
   with self.assertRaisesRegex(receipts.ReceiptError,'already_analyzed'):receipts.extract(self.photo(),'image/png',None,[],self.b,self.uid)
   stream.assert_not_called();reserve.side_effect=usage.UsageLimit('Synthetic capacity')
   with self.assertRaisesRegex(receipts.ReceiptError,'capacity_unavailable'):receipts.extract(self.photo(),'image/png',None,[],self.b,self.uid)
   stream.assert_not_called();reserve.side_effect=None;reserve.return_value=('PRO',('CHAT',));stream.return_value=iter([])
   with self.assertRaises(receipts.ReceiptError):receipts.extract(self.photo(),'image/png',None,[],self.b,self.uid)
   self.assertEqual(stream.call_count,1);self.assertTrue(finish.call_args.kwargs['usage']['billing_unknown']);self.assertFalse(finish.call_args.kwargs['success'])
 def test_scanner_scope_entitlement_csrf_invalid_photo_and_other_ai_remain_blocked(self):
  with patch('kilas_ai.workspace_execution_access.entitled',return_value=False),patch('kilas_ai.providers._openai') as provider:
   response=self.client.post(self.url+'/receipts/analyze',data={'branch_id':self.branch,'receipt':(io.BytesIO(self.photo()),'receipt.png')});self.assertEqual(response.status_code,403);provider.assert_not_called()
  self.assertEqual(self.client.get(self.url+f'/receipts/new?branch_id={self.personal}').status_code,404)
  for path in ('analyst','operator','assistant','bank-imports/new'):self.assertEqual(self.client.get(self.url+'/'+path).status_code,404)
  fixture.fixture.app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=True
  self.assertEqual(self.client.post(self.url+'/receipts/analyze',data={'branch_id':self.branch}).status_code,400)
  fixture.fixture.app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=False
  self.scanner()
  response=self.client.post(self.url+'/receipts/analyze',data={'branch_id':self.branch,'receipt':(io.BytesIO(b'not an image'),'receipt.png')});self.assertEqual(response.status_code,400)
 def test_final_sync_no_permanent_deletion_ambiguous_history_retained(self):
  with branches.scope(self.b,self.personal,self.uid):
   rows=f.list_categories(self.b,'EXPENSE',include_children=True,include_inactive=True,actor_user_id=self.uid)
   ids={r['id'] for r in rows};ledger=next(v for v in rows if v['is_active'] and v.get('parent_category_id'))
   tx=f.create_transaction(self.b,'EXPENSE',100,self.pa,ledger['id'],'2026-09-10',actor_user_id=self.uid);old=dict(f.get_transaction(self.b,tx,actor_user_id=self.uid))
   before=db.query_one('SELECT count(*) n FROM finance_categories')['n'];f.ensure_finance_defaults(self.b,actor_user_id=self.uid)
   self.assertEqual(before,db.query_one('SELECT count(*) n FROM finance_categories')['n']);self.assertEqual(dict(f.get_transaction(self.b,tx,actor_user_id=self.uid)),old)
   self.assertTrue(ids.issubset({r['id'] for r in f.list_categories(self.b,'EXPENSE',include_children=True,include_inactive=True,actor_user_id=self.uid)}))
   version=db.query_one('SELECT changes_json FROM finance_category_catalog_versions WHERE business_id=? AND scope_key=? AND version=3',(self.b,'PERSONAL:'+str(self.uid)));self.assertTrue(json.loads(version['changes_json']))
 def test_final_default_manual_archive_is_not_resurrected(self):
  with branches.scope(self.b,self.personal,self.uid):
   root=f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid)[0];child=f.list_category_children(self.b,root['id'],actor_user_id=self.uid)[0];catalog.edit(self.b,self.uid,child['id'],deactivate=True);f.ensure_finance_defaults(self.b,actor_user_id=self.uid);self.assertFalse(f._category_setting_by_id(self.b,child['id'],self.uid,include_inactive=True)['is_active'])
 def test_cleanup_read_only_snapshot_unchanged_refs_and_scope_fail_closed(self):
  import finance_category_cleanup as cleanup
  with branches.scope(self.b,self.personal,self.uid):
   root=next(v for v in f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid) if v['name']=='Rumah / Sewa');child=f.list_category_children(self.b,root['id'],actor_user_id=self.uid)[0]
   before=db.query_one('SELECT count(*) n FROM audit_log')['n'];snapshot=cleanup.snapshot(self.b,self.uid,[child['id']]);self.assertEqual(cleanup.dry_run(self.b,self.uid,snapshot)['permanent_deletion_authorized'],False);self.assertEqual(db.query_one('SELECT count(*) n FROM audit_log')['n'],before)
   f.create_transaction(self.b,'EXPENSE',100,self.pa,child['id'],'2026-09-10',actor_user_id=self.uid)
   with self.assertRaisesRegex(ValueError,'cleanup_references_changed'):cleanup.dry_run(self.b,self.uid,snapshot)
   with self.assertRaises(ValueError):cleanup.snapshot(self.b,self.other_uid,[child['id']])
if __name__=='__main__':unittest.main()
