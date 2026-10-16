"""Owner-only Personal entry and reset safeguards; destructive checks are local disposable fixtures."""
import json
import re
import threading
import unittest
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from flask import template_rendered
from html.parser import HTMLParser
from urllib.parse import parse_qs,urlsplit
import test_finance_approved_revisions as prior
import finance_service as f
import finance_branches as branches
import finance_reset as reset
import finance_personal as personal
import db,repo


class Elements(HTMLParser):
    def __init__(self,html):super().__init__();self.items=[];self.feed(html)
    def handle_starttag(self,tag,attrs):self.items.append((tag,dict(attrs)))


class PersonalResetTests(unittest.TestCase):
    setUp=prior.ApprovedFinanceTests.setUp
    page=prior.ApprovedFinanceTests.page

    def legacy_empty_personal(self,business_id,user_id):
        # Simulate a pre-release duplicate using disposable fixture rows only.
        now=repo._now()
        branch=db.insert_returning_id('INSERT INTO finance_branches(business_id,name,created_at,updated_at) VALUES (?,?,?,?)',
            (business_id,'Pribadi legacy '+str(user_id),now,now))
        db.execute('INSERT INTO finance_branch_workspaces(business_id,branch_id,workspace_type,owner_user_id,created_at) VALUES (?,?,?,?,?)',
            (business_id,branch,'PERSONAL',user_id,now))
        account=db.insert_returning_id("INSERT INTO finance_accounts(business_id,branch_id,name,account_type,currency,opening_balance_minor,created_at,updated_at) VALUES (?,?,'Kas','CASH','IDR',0,?,?)",
            (business_id,branch,now,now))
        return branch,account

    def seed_personal(self):
        with branches.scope(self.b,self.personal,self.uid):
            bca=f.create_account(self.b,'BCA existing','BANK',opening_balance_minor=12000,actor_user_id=self.uid)
            bank=f.create_account(self.b,'Second existing bank','BANK',opening_balance_minor=34000,actor_user_id=self.uid)
            income=f.list_categories(self.b,'INCOME',actor_user_id=self.uid)[0]['id']
            expense=f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid)[0]['id']
            tx=f.create_transaction(self.b,'INCOME',500,bca,income,'2026-09-10',description='Personal fixture',actor_user_id=self.uid)
            f.set_monthly_budget(self.b,'2026-09',expense,5000,'IDR',actor_user_id=self.uid)
            transfer=f.record_internal_transfer(self.b,bca,bank,200,'2026-09-10',idempotency_key='a'*32,actor_user_id=self.uid)
        return bca,bank,tx,transfer

    def prepare(self):
        with branches.scope(self.b,self.personal,self.uid):return reset.prepare(self.b,self.personal,actor_user_id=self.uid)

    def complete(self,key,**kw):
        data=dict(actor_user_id=self.uid,confirmation='RESET',acknowledged='yes');data.update(kw)
        with branches.scope(self.b,self.personal,self.uid):return reset.complete(self.b,self.personal,key,**data)

    def finance_rows(self,exclude_requests=True):
        names=[r['name'] for r in db.query_all("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ? ORDER BY name",('finance_%',))]
        return {name:db.query_all('SELECT * FROM '+name) for name in names if not (exclude_requests and name=='finance_reset_requests')}

    def test_personal_has_no_branch_management_and_business_keeps_it(self):
        html,_=self.page(self.personal)
        self.assertNotIn('data-dashboard-open="branch-dialog"',html)
        self.assertNotIn('id="finance-app-branch"',html)
        self.assertNotIn('id="branch-dialog"',html)
        html,_=self.page()
        self.assertIn('data-dashboard-open="branch-dialog"',html)
        self.assertIn('id="finance-app-branch"',html)
        self.assertEqual(self.client.post(self.url+'/branches',data=dict(branch_id=self.personal,name='Forbidden')).status_code,403)

    def test_existing_personal_banks_render_and_selected_bank_receives_income(self):
        bca,bank,_,_=self.seed_personal()
        before_accounts=db.query_all('SELECT * FROM finance_accounts')
        html,ctx=self.page(self.personal,view='transactions',direction='INCOME',account_id=bank)
        form=re.search(r'<form id="add-transaction".*?</form>',html,re.S).group()
        selector=re.search(r'<select id="transaction-account".*?</select>',form,re.S).group()
        options=[a for tag,a in Elements(selector).items if tag=='option' and a.get('value')]
        self.assertEqual({int(a['value']) for a in options},{self.pa,bca,bank})
        self.assertTrue(any(a['value']==str(bank) and 'selected' in a for a in options))
        self.client.post(self.url+'/transactions',data=dict(branch_id=self.personal,direction='INCOME',description='Chosen bank',
            occurred_on='2026-09-11',amount='10.25',account_id=bank))
        row=db.query_one('SELECT * FROM finance_transactions WHERE description=?',('Chosen bank',))
        self.assertEqual((row['account_id'],row['branch_id'],row['amount_minor']),(bank,self.personal,1025))
        self.assertEqual(before_accounts,db.query_all('SELECT * FROM finance_accounts'))

    def test_reset_launch_is_only_on_personal_and_business_dashboard(self):
        before=self.finance_rows(False)
        for branch in (self.personal,self.branch):
            html,_=self.page(branch)
            self.assertEqual(html.count('class="finance-reset-launch"'),1)
            navigation=re.search(r'<nav class="finance-primary-navigation">.*?</nav>',html,re.S).group()
            self.assertIn('class="finance-reset-launch"',navigation)
            self.assertIn('/reset/prepare?',navigation)
            context_bar=html[html.index('<div class="finance-context-toolbar'):]
            self.assertNotIn('class="finance-reset-launch"',context_bar)
            for query in (dict(view='accounts'),dict(view='transactions'),dict(view='transactions',direction='INCOME'),dict(view='transactions',direction='EXPENSE')):
                html,_=self.page(branch,**query)
                self.assertNotIn('class="finance-reset-launch"',html)
            for endpoint in ('operations','budget','payees','receivables','reports','assistant'):
                response=self.client.get(self.url+'/'+endpoint,query_string=dict(branch_id=branch,month='2026-09'))
                if endpoint=='assistant':self.assertIn(response.status_code,(200,404))
                else:self.assertEqual(response.status_code,200,endpoint)
                self.assertNotIn('class="finance-reset-launch"',response.text)
        self.assertEqual(before,self.finance_rows(False))

    def test_dashboard_reset_launch_keeps_owner_visibility_rules(self):
        db.execute("UPDATE business_memberships SET role_in_business='STAFF' WHERE business_id=? AND user_id=?",(self.b,self.uid))
        html,_=self.page(self.branch)
        self.assertNotIn('class="finance-reset-launch"',html)
        html,_=self.page(self.personal)
        self.assertIn('class="finance-reset-launch"',html)

    def test_account_selection_rejects_business_other_owner_and_other_personal_context(self):
        bca,bank,_,_=self.seed_personal()
        db.execute("INSERT INTO business_memberships(business_id,user_id,role_in_business) VALUES (?,?,'OWNER')",(self.b,self.other_uid))
        private=branches.ensure_personal(self.b,self.other_uid)
        with branches.scope(self.b,private,self.other_uid):
            f.ensure_finance_defaults(self.b,actor_user_id=self.other_uid)
            other=f.list_accounts(self.b,actor_user_id=self.other_uid)[0]['id']
        other_business=repo.create_business(self.uid,'Separate own business')
        own_other,own_other_account=self.legacy_empty_personal(other_business,self.uid)
        for account in (self.a,self.dest,other,own_other_account):
            before=self.finance_rows()
            self.client.post(self.url+'/transactions',data=dict(branch_id=self.personal,direction='INCOME',description='Forbidden',
                occurred_on='2026-09-10',amount='1',account_id=account))
            self.assertEqual(before,self.finance_rows())
        with branches.scope(self.b,self.personal,self.uid),self.assertRaises(f.FinanceError):
            f.list_entry_accounts(self.b,actor_user_id=self.other_uid)

    def test_prepare_and_review_never_reset_financial_data(self):
        self.seed_personal();before=self.finance_rows();key=self.prepare()
        with branches.scope(self.b,self.personal,self.uid):
            preview=reset.preview(self.b,self.personal,key,actor_user_id=self.uid)
        self.assertEqual(before,self.finance_rows())
        self.assertEqual((preview['accounts'],preview['transactions'],preview['transfers'],preview['budgets']),(3,1,1,1))
        self.assertFalse(preview['expired']);self.assertFalse(preview['changed'])

    def test_final_confirmation_and_server_request_are_both_required(self):
        self.seed_personal();key=self.prepare();before=self.finance_rows()
        for confirmation,ack in (('',None),('RESET',None),('reset','yes')):
            with self.assertRaises(f.FinanceError):self.complete(key,confirmation=confirmation,acknowledged=ack)
        with self.assertRaises(f.FinanceError):self.complete('b'*32)
        self.assertEqual(before,self.finance_rows())
        self.client.post(self.url+'/reset',data=dict(branch_id=self.personal,confirmation='RESET',acknowledged='yes'))
        self.assertEqual(before,self.finance_rows())

    def test_scoped_reset_zeroes_balance_budgets_transfers_and_preserves_other_space(self):
        bca,bank,tx,transfer=self.seed_personal()
        f.create_transaction(self.b,'INCOME',999,self.a,self.cat,'2026-09-10',actor_user_id=self.uid)
        before_business=f.get_transaction(self.b,db.query_one('SELECT MAX(id) AS n FROM finance_transactions')['n'])
        identities=(db.query_all('SELECT * FROM users'),db.query_all('SELECT * FROM businesses'),db.query_all('SELECT * FROM business_memberships'))
        key=self.prepare();self.complete(key)
        with branches.scope(self.b,self.personal,self.uid):
            self.assertTrue(all(r['balance_minor']==0 for r in f.get_account_balance_report(self.b,'2026-09-30',self.uid)))
            self.assertEqual(f.get_finance_summary(self.b,'2026-09-01','2026-09-30',actor_user_id=self.uid)['total_income_minor'],0)
            self.assertEqual(f.list_monthly_budgets(self.b,'2026-09',actor_user_id=self.uid),[])
            self.assertEqual(f.list_internal_transfers(self.b,actor_user_id=self.uid)[0]['status'],'VOID')
        self.assertEqual(f.get_transaction(self.b,tx)['status'],'VOID')
        self.assertEqual(before_business,f.get_transaction(self.b,before_business['id']))
        self.assertEqual(identities,(db.query_all('SELECT * FROM users'),db.query_all('SELECT * FROM businesses'),db.query_all('SELECT * FROM business_memberships')))
        self.assertEqual(db.query_one('SELECT count(*) AS n FROM finance_accounts WHERE branch_id=?',(self.personal,))['n'],3)
        self.assertTrue(db.query_one("SELECT 1 FROM audit_log WHERE action='FINANCE_RESET_CONFIRMED'"))

    def test_changed_data_requires_new_warning(self):
        self.seed_personal();key=self.prepare()
        with branches.scope(self.b,self.personal,self.uid):f.update_account_opening_balance(self.b,self.pa,456,actor_user_id=self.uid)
        before=self.finance_rows()
        with self.assertRaisesRegex(f.FinanceError,'reset_data_changed'):self.complete(key)
        self.assertEqual(before,self.finance_rows())

    def test_expired_request_does_not_reset(self):
        self.seed_personal();key=self.prepare();before=self.finance_rows()
        with patch.object(reset,'_now',return_value=reset._now()+timedelta(minutes=11)),self.assertRaisesRegex(f.FinanceError,'reset_expired'):
            self.complete(key)
        self.assertEqual(before,self.finance_rows())

    def test_target_tampering_and_other_actor_are_rejected(self):
        self.seed_personal();key=self.prepare();before=self.finance_rows()
        with branches.scope(self.b,self.branch,self.uid),self.assertRaises(f.FinanceError):
            reset.complete(self.b,self.branch,key,actor_user_id=self.uid,confirmation='RESET',acknowledged='yes')
        self.assertEqual(before,self.finance_rows())
        with branches.scope(self.b,self.personal,self.uid),self.assertRaises(f.FinanceError):
            reset.complete(self.b,self.personal,key,actor_user_id=self.other_uid,confirmation='RESET',acknowledged='yes')

    def test_duplicate_confirmation_preserves_later_new_income(self):
        bca,_,_,_=self.seed_personal();key=self.prepare();self.complete(key)
        with branches.scope(self.b,self.personal,self.uid):
            category=f.list_categories(self.b,'INCOME',actor_user_id=self.uid)[0]['id']
            tx=f.create_transaction(self.b,'INCOME',888,bca,category,'2026-09-11',actor_user_id=self.uid)
        self.complete(key)
        self.assertEqual(f.get_transaction(self.b,tx)['status'],'POSTED')
        self.assertEqual(db.query_one("SELECT count(*) AS n FROM audit_log WHERE action='FINANCE_RESET_CONFIRMED'")['n'],1)

    def test_late_failure_rolls_back_entire_reset_and_consumption(self):
        self.seed_personal();key=self.prepare();before=self.finance_rows(False)
        original=f._audit
        def fail(bid,actor,action,*args):
            if action=='FINANCE_RESET_CONFIRMED':raise RuntimeError('synthetic late failure')
            return original(bid,actor,action,*args)
        with patch.object(f,'_audit',side_effect=fail),self.assertRaises(RuntimeError):self.complete(key)
        self.assertEqual(before,self.finance_rows(False))
        self.complete(key)

    def test_concurrent_duplicate_confirmations_reset_once(self):
        self.seed_personal();key=self.prepare();barrier=threading.Barrier(2)
        def worker(_):
            try:barrier.wait();return self.complete(key)
            finally:
                if getattr(db._local,'conn',None):db._local.conn.close();db._local.conn=None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(worker,range(2)))
        self.assertEqual(results,[key,key])
        self.assertEqual(db.query_one("SELECT count(*) AS n FROM audit_log WHERE action='FINANCE_RESET_CONFIRMED'")['n'],1)

    def test_prepare_requires_csrf_and_does_not_accept_staff_business_owner(self):
        prior.app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=True
        self.assertEqual(self.client.post(self.url+'/reset/prepare',data=dict(branch_id=self.personal)).status_code,400)
        prior.app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=False
        db.execute("UPDATE business_memberships SET role_in_business='STAFF' WHERE business_id=? AND user_id=?",(self.b,self.uid))
        self.assertEqual(self.client.post(self.url+'/reset/prepare',data=dict(branch_id=self.branch)).status_code,403)
        with branches.scope(self.b,self.branch,self.uid),self.assertRaises(f.FinanceError):f.reset_branch_finance(self.b,self.uid)

    def test_reset_covers_invoice_payments_recurring_fx_and_bank_staging(self):
        bca,bank,_,_=self.seed_personal()
        with branches.scope(self.b,self.personal,self.uid):
            income=f.list_categories(self.b,'INCOME',actor_user_id=self.uid)[0]['id']
            expense=f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid)[0]['id']
            invoice=f.create_finance_invoice(self.b,self.c,'2026-09-01','2026-09-15',
                [dict(description='Synthetic service',quantity=1,unit_price_minor=200)],actor_user_id=self.uid)
            f.issue_finance_invoice(self.b,invoice,actor_user_id=self.uid)
            f.record_invoice_payment(self.b,invoice,200,'2026-09-10',bca,income,
                idempotency_key='synthetic-reset-payment',actor_user_id=self.uid)
            recurring=f.create_recurring_expense(self.b,'Synthetic recurring',100,bca,expense,'MONTHLY','2026-09-10',actor_user_id=self.uid)
            usd=f.create_account(self.b,'Synthetic USD','BANK','USD',1000,actor_user_id=self.uid)
            f.record_currency_exchange(self.b,bca,usd,100,2,'2026-09-10',actor_user_id=self.uid)
            now=repo._now()
            batch=db.insert_returning_id('INSERT INTO finance_bank_imports(business_id,branch_id,account_id,source_kind,display_label,file_hash,source_count,status,imported_by_user_id,created_at,updated_at) VALUES (?,?,?, ?,?,?,?, ?,?,?,?)',
                (self.b,self.personal,bca,'CSV','Synthetic only','f'*64,1,'OPEN',self.uid,now,now))
            db.execute('INSERT INTO finance_bank_rows(business_id,import_id,row_index,row_hash,occurred_on,direction,amount_minor,description,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                (self.b,batch,1,'e'*64,'2026-09-10','INCOME',100,'Synthetic pending',now,now))
            db.execute('INSERT INTO finance_bank_extraction_reviews(business_id,import_id,row_index,metadata) VALUES (?,?,?,?)',
                (self.b,batch,1,'{}'))
        payment_before=db.query_all('SELECT * FROM finance_invoice_payments')
        categories_before=db.query_all('SELECT * FROM finance_categories')
        self.complete(self.prepare())
        with branches.scope(self.b,self.personal,self.uid):
            self.assertTrue(all(row['balance_minor']==0 for row in f.get_account_balance_report(self.b,'2026-09-30',self.uid)))
            self.assertEqual(f.get_receivables_summary(self.b,actor_user_id=self.uid)['open_invoice_count'],0)
            self.assertEqual(f.get_currency_exchange(self.b,db.query_one('SELECT id FROM finance_fx_exchanges')['id'],self.uid)['status'],'VOID')
        self.assertEqual(db.query_one('SELECT status FROM finance_invoices WHERE id=?',(invoice,))['status'],'VOID')
        self.assertFalse(db.query_one('SELECT is_active FROM finance_recurring_expenses WHERE id=?',(recurring,))['is_active'])
        self.assertEqual(db.query_one('SELECT status FROM finance_bank_imports WHERE id=?',(batch,))['status'],'CANCELLED')
        self.assertEqual(payment_before,db.query_all('SELECT * FROM finance_invoice_payments'))
        self.assertEqual(categories_before,db.query_all('SELECT * FROM finance_categories'))
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_bank_rows WHERE import_id=?',(batch,))['n'],1)

    def test_canonical_personal_routing_reuses_banks_across_business_entry_points(self):
        bca,bank,_,_=self.seed_personal()
        other_business=repo.create_business(self.uid,'Second own business')
        legacy,legacy_account=self.legacy_empty_personal(other_business,self.uid)
        before=self.finance_rows()
        response=self.client.get('/finance/personal',query_string=dict(branch_id=legacy,view='transactions',direction='INCOME'))
        self.assertEqual(response.status_code,303)
        self.assertIn('/business/'+str(self.b)+'/finance',response.location)
        self.assertEqual(parse_qs(urlsplit(response.location).query)['branch_id'],[str(self.personal)])
        response=self.client.get(f'/business/{other_business}/finance',query_string=dict(branch_id=legacy,view='transactions',direction='INCOME'))
        self.assertEqual(response.status_code,303)
        self.assertIn('branch_id='+str(self.personal),response.location)
        response=self.client.post(f'/business/{other_business}/finance/workspaces/PERSONAL')
        self.assertEqual(response.status_code,303)
        self.assertIn('/business/'+str(self.b)+'/finance',response.location)
        self.assertEqual(before,self.finance_rows())
        html,_=self.page(self.personal,view='transactions',direction='INCOME')
        self.assertNotIn('finance-personal-context',html)
        self.assertIn('BCA existing',html);self.assertIn('Second existing bank',html)
        # A stale form from the empty legacy context cannot post into that context.
        self.client.post(f'/business/{other_business}/finance/transactions',data=dict(branch_id=legacy,
            direction='INCOME',account_id=legacy_account,description='Forbidden stale',amount='1',occurred_on='2026-09-10'))
        self.assertEqual(before,self.finance_rows())

    def test_duplicate_personal_creation_is_rejected_without_new_records(self):
        other_business=repo.create_business(self.uid,'No duplicate destination')
        before=self.finance_rows()
        with self.assertRaisesRegex(f.FinanceError,'personal_home_elsewhere'):
            branches.ensure_personal(other_business,self.uid)
        self.assertEqual(before,self.finance_rows())

    def test_legacy_unique_populated_dataset_is_resolved_without_merging(self):
        self.seed_personal()
        other_business=repo.create_business(self.uid,'Legacy empty destination')
        legacy,_=self.legacy_empty_personal(other_business,self.uid)
        db.execute('DELETE FROM finance_personal_homes WHERE user_id=?',(self.uid,))
        before=self.finance_rows()
        home=personal.resolve_home(self.uid)
        self.assertEqual((home['business_id'],home['branch_id']),(self.b,self.personal))
        self.assertEqual(before,self.finance_rows())
        self.assertNotEqual(home['branch_id'],legacy)

    def test_two_populated_personal_datasets_require_explicit_migration(self):
        self.seed_personal()
        other_business=repo.create_business(self.uid,'Legacy populated conflict')
        legacy,account=self.legacy_empty_personal(other_business,self.uid)
        db.execute("UPDATE finance_accounts SET name='Legacy bank',opening_balance_minor=123 WHERE id=?",(account,))
        before=self.finance_rows()
        with self.assertRaisesRegex(f.FinanceError,'personal_context_conflict'):personal.resolve_home(self.uid)
        response=self.client.get('/finance/personal')
        self.assertEqual(response.status_code,409)
        self.assertEqual(before,self.finance_rows())

    def test_business_reset_excludes_other_branches_including_inactive_and_personal(self):
        self.seed_personal()
        personal_before=db.query_all('SELECT * FROM finance_accounts WHERE branch_id=?',(self.personal,))
        second=branches.create_branch(self.b,'Second Business branch',self.uid)
        with branches.scope(self.b,second,self.uid):
            account=f.list_accounts(self.b,actor_user_id=self.uid)[0]['id']
            f.update_account_opening_balance(self.b,account,777,actor_user_id=self.uid)
            category=f.list_categories(self.b,'INCOME',actor_user_id=self.uid)[0]['id']
            tx=f.create_transaction(self.b,'INCOME',555,account,category,'2026-09-10',actor_user_id=self.uid)
        db.execute('UPDATE finance_branches SET is_active=FALSE WHERE id=?',(second,))
        with branches.scope(self.b,self.branch,self.uid):
            key=reset.prepare(self.b,self.branch,actor_user_id=self.uid)
            preview=reset.preview(self.b,self.branch,key,actor_user_id=self.uid)
            self.assertEqual(preview['target']['branch_ids'],[self.branch])
            reset.complete(self.b,self.branch,key,actor_user_id=self.uid,confirmation='RESET',acknowledged='yes')
        self.assertEqual(db.query_one('SELECT opening_balance_minor FROM finance_accounts WHERE id=?',(account,))['opening_balance_minor'],777)
        self.assertEqual(f.get_transaction(self.b,tx)['status'],'POSTED')
        self.assertEqual(personal_before,db.query_all('SELECT * FROM finance_accounts WHERE branch_id=?',(self.personal,)))
        self.assertEqual(f.get_transaction(self.b,db.query_one('SELECT MIN(id) AS n FROM finance_transactions')['n'])['status'],'POSTED')

    def test_new_business_branch_does_not_expand_existing_confirmation(self):
        with branches.scope(self.b,self.branch,self.uid):key=reset.prepare(self.b,self.branch,actor_user_id=self.uid)
        created=branches.create_branch(self.b,'Created after warning',self.uid)
        with branches.scope(self.b,created,self.uid):
            account=f.list_accounts(self.b,actor_user_id=self.uid)[0]['id']
            f.update_account_opening_balance(self.b,account,789,actor_user_id=self.uid)
        before=db.query_all('SELECT * FROM finance_accounts WHERE branch_id=?',(created,))
        with branches.scope(self.b,self.branch,self.uid):
            reset.complete(self.b,self.branch,key,actor_user_id=self.uid,confirmation='RESET',acknowledged='yes')
        self.assertEqual(before,db.query_all('SELECT * FROM finance_accounts WHERE branch_id=?',(created,)))

    def test_business_atomic_failure_does_not_partially_reset_branches(self):
        second=branches.create_branch(self.b,'Rollback branch',self.uid)
        with branches.scope(self.b,self.branch,self.uid):key=reset.prepare(self.b,self.branch,actor_user_id=self.uid)
        before=self.finance_rows(False)
        original=f._reset_branch_records
        def fail(bid,branch,uid):
            original(bid,branch,uid)
            raise RuntimeError('synthetic selected-branch failure')
        with branches.scope(self.b,self.branch,self.uid),patch.object(f,'_reset_branch_records',side_effect=fail),self.assertRaises(RuntimeError):
            reset.complete(self.b,self.branch,key,actor_user_id=self.uid,confirmation='RESET',acknowledged='yes')
        self.assertEqual(before,self.finance_rows(False))

    def test_reset_warning_names_target_and_requires_separate_typed_acknowledgement(self):
        self.seed_personal();before=self.finance_rows()
        response=self.client.post(self.url+'/reset/prepare',data=dict(branch_id=self.personal))
        self.assertEqual(response.status_code,303)
        warning=self.client.get(response.location)
        self.assertEqual(warning.status_code,200)
        for text in ('Verifikasi Reset Data Finance','Finance Pribadi','receivable','name="confirmation"','name="acknowledged"','name="request_key"'):
            self.assertIn(text,warning.text)
        self.assertEqual(before,self.finance_rows())
        key=re.search(r'name="request_key" value="([a-f0-9]{32})"',warning.text).group(1)
        self.client.post(self.url+'/reset',data=dict(branch_id=self.personal,request_key=key,confirmation='RESET'))
        self.assertEqual(before,self.finance_rows())
        self.client.post(self.url+'/reset',data=dict(branch_id=self.personal,request_key=key,confirmation='RESET',acknowledged='yes'))
        with branches.scope(self.b,self.personal,self.uid):self.assertTrue(all(r['balance_minor']==0 for r in f.get_account_balance_report(self.b,'2026-09-30',self.uid)))

    def test_personal_mode_preserves_previous_business_context_without_creating_another_personal(self):
        self.seed_personal()
        secondary=repo.create_business(self.uid,'Remembered Business')
        f.ensure_finance_defaults(secondary,actor_user_id=self.uid)
        selected=branches.list_branches(secondary,self.uid)[0]['id']
        self.assertEqual(self.client.get(f'/business/{secondary}/finance',query_string=dict(branch_id=selected,month='2026-09')).status_code,200)
        response=self.client.post(f'/business/{secondary}/finance/workspaces/PERSONAL')
        self.assertEqual(response.status_code,303)
        self.assertIn('/business/'+str(self.b)+'/finance',response.location)
        html,ctx=self.page(self.personal)
        self.assertEqual((ctx['finance_ui']['business_return_id'],ctx['finance_ui']['business_return_branch']),(secondary,selected))
        self.assertIn('/business/'+str(secondary)+'/finance/workspaces/BUSINESS',html)
        response=self.client.post(f'/business/{secondary}/finance/workspaces/BUSINESS',data=dict(return_branch_id=selected))
        self.assertIn('branch_id='+str(selected),response.location)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM finance_branch_workspaces WHERE workspace_type='PERSONAL' AND owner_user_id=?",(self.uid,))['n'],1)


    def test_business_confirmation_cannot_be_rebound_to_another_branch(self):
        second=branches.create_branch(self.b,'Not selected',self.uid)
        with branches.scope(self.b,self.branch,self.uid):key=reset.prepare(self.b,self.branch,actor_user_id=self.uid)
        before=self.finance_rows(False)
        with branches.scope(self.b,second,self.uid),self.assertRaises(f.FinanceError):
            reset.complete(self.b,second,key,actor_user_id=self.uid,confirmation='RESET',acknowledged='yes')
        self.assertEqual(before,self.finance_rows(False))
