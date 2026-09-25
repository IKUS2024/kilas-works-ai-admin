"""Offline recurring expense and project cash movement tests, including independent SQLite writers."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from datetime import date
import test_finance_phase2a as prior

f,db,repo,app=prior.f,prior.db,prior.repo,prior.app
spec=importlib.util.spec_from_file_location('finance_cron',Path(__file__).parents[1]/'scripts/process_finance_recurring.py')
cron=importlib.util.module_from_spec(spec);spec.loader.exec_module(cron)


class RecurringTests(unittest.TestCase):
    def setUp(self):
        prior.ReceivablesTests.setUp(self)
        self.exp=f.list_categories(self.b,'EXPENSE')[0]['id']
        self.project=db.insert_returning_id("INSERT INTO projects (business_id,project_type,pricing_mode,title,status,created_by_user_id) VALUES (?,'CONTENT','CUSTOM_QUOTE','My project','REQUESTED',?)",(self.b,self.uid))
        self.op=db.insert_returning_id("INSERT INTO projects (business_id,project_type,pricing_mode,title,status,created_by_user_id) VALUES (?,'CONTENT','CUSTOM_QUOTE','PRIVATE project','REQUESTED',?)",(self.other,self.other_uid))

    def rule(self,**kw):
        args=dict(business_id=self.b,name='Routine',amount_minor=100,account_id=self.a,category_id=self.exp,
                  cadence='MONTHLY',next_due_on='2026-01-31',project_id=self.project,actor_user_id=self.uid)
        args.update(kw);return f.create_recurring_expense(**args)

    def test_migration_idempotency_and_indexes(self):
        r=self.rule();f.process_due_recurring_expenses(self.b,'2026-01-31')
        before=f.get_recurring_expense(self.b,r)
        db.init_schema();db.init_schema()
        self.assertEqual(before,f.get_recurring_expense(self.b,r))
        self.assertEqual(len(f.list_recurring_postings(self.b,r)),1)
        self.assertEqual([r['name'] for r in db.query_all('PRAGMA index_info(idx_finance_recurring_business_due)')],['business_id','is_active','next_due_on'])

    def test_monthly_anchor_no_drift(self):
        r=self.rule();result=f.process_due_recurring_expenses(self.b,'2026-04-30')
        self.assertEqual(result['posted_count'],4)
        self.assertEqual([p['scheduled_on'] for p in f.list_recurring_postings(self.b,r)],['2026-01-31','2026-02-28','2026-03-31','2026-04-30'])
        self.assertEqual(f.get_recurring_expense(self.b,r)['next_due_on'],'2026-05-31')
        self.assertEqual(f.get_recurring_expense(self.b,r)['anchor_day'],31)

    def test_leap_february_and_weekly(self):
        r=self.rule(next_due_on='2024-01-31');f.process_due_recurring_expenses(self.b,'2024-03-31')
        self.assertEqual([p['scheduled_on'] for p in f.list_recurring_postings(self.b,r)],['2024-01-31','2024-02-29','2024-03-31'])
        f.deactivate_recurring_expense(self.b,r)
        weekly=self.rule(cadence='WEEKLY',next_due_on='2026-01-01')
        f.process_due_recurring_expenses(self.b,'2026-01-15')
        self.assertEqual([p['scheduled_on'] for p in f.list_recurring_postings(self.b,weekly)],['2026-01-01','2026-01-08','2026-01-15'])
        self.assertIsNone(f.get_recurring_expense(self.b,weekly)['anchor_day'])

    def test_inactive_and_end_on_stop(self):
        r=self.rule(end_on='2026-02-28')
        f.process_due_recurring_expenses(self.b,'2026-12-31')
        self.assertEqual(len(f.list_recurring_postings(self.b,r)),2)
        self.assertFalse(f.get_recurring_expense(self.b,r)['is_active'])
        r2=self.rule();f.deactivate_recurring_expense(self.b,r2)
        f.process_due_recurring_expenses(self.b,'2027-01-01')
        self.assertEqual(f.list_recurring_postings(self.b,r2),[])
        self.assertEqual(f.list_recurring_expenses(self.b),[])

    def test_exact_once_and_due_date_ledger_values(self):
        r=self.rule(counterparty_name='Vendor',description='Bill')
        for _ in range(3):f.process_due_recurring_expenses(self.b,'2026-01-31')
        postings=f.list_recurring_postings(self.b,r);self.assertEqual(len(postings),1)
        tx=f.get_transaction(self.b,postings[0]['ledger_transaction_id'])
        for k,v in dict(direction='EXPENSE',amount_minor=100,currency='IDR',project_id=self.project,
                        occurred_on='2026-01-31',source_type='FINANCE_RECURRING_EXPENSE',source_ref=str(postings[0]['id']),counterparty_name='Vendor',description='Bill').items():self.assertEqual(tx[k],v)
        self.assertEqual(len(f.list_transactions(self.b)),1)
        audit=db.query_all("SELECT detail FROM audit_log WHERE action='FINANCE_RECURRING_POSTED'")
        self.assertNotIn('Vendor',str(audit));self.assertNotIn('Bill',str(audit))

    def test_explicit_payment_uses_paid_on_not_due_on_and_replay_is_idempotent(self):
        r=self.rule(next_due_on='2026-01-31')
        first=f.record_recurring_payment(self.b,r,'2026-01-31','2026-02-05',self.uid)
        second=f.record_recurring_payment(self.b,r,'2026-01-31','2026-02-05',self.uid)
        self.assertTrue(first['created'])
        self.assertFalse(second['created'])
        self.assertEqual(first['ledger_transaction_id'],second['ledger_transaction_id'])
        tx=f.get_transaction(self.b,first['ledger_transaction_id'],actor_user_id=self.uid)
        self.assertEqual(tx['occurred_on'],'2026-02-05')
        self.assertEqual(f.get_finance_summary(self.b,'2026-01-01','2026-01-31')['total_expense_minor'],0)
        self.assertEqual(f.get_finance_summary(self.b,'2026-02-01','2026-02-28')['total_expense_minor'],100)
        self.assertEqual(f.list_recurring_postings(self.b,r)[0]['scheduled_on'],'2026-01-31')

    def test_explicit_payment_can_be_early_and_future_payment_date_is_rejected(self):
        early=self.rule(next_due_on='2026-03-31')
        result=f.record_recurring_payment(self.b,early,'2026-03-31','2026-02-05',self.uid)
        tx=f.get_transaction(self.b,result['ledger_transaction_id'],actor_user_id=self.uid)
        self.assertEqual(tx['occurred_on'],'2026-02-05')
        self.assertEqual(f.list_recurring_postings(self.b,early)[0]['scheduled_on'],'2026-03-31')

        future=self.rule(next_due_on='2026-04-30')
        with self.assertRaises(f.FinanceError):
            f.record_recurring_payment(self.b,future,'2026-04-30','9999-12-31',self.uid)
        self.assertEqual(f.list_recurring_postings(self.b,future),[])

    def test_concurrent_ui_cron_paths_one_posting(self):
        r=self.rule();barrier=threading.Barrier(2)
        def worker(_):
            try:
                barrier.wait();return f.process_due_recurring_expenses(self.b,'2026-01-31')
            finally:
                if getattr(db._local,'conn',None):db._local.conn.close();db._local.conn=None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(worker,range(2)))
        self.assertEqual(sum(x['posted_count'] for x in results),1)
        self.assertEqual(len(f.list_recurring_postings(self.b,r)),1)

    def test_ledger_failure_rolls_back_occurrence_and_date(self):
        r=self.rule()
        with patch.object(f,'_insert_transaction',side_effect=RuntimeError('mock ledger failure')):
            with self.assertRaises(RuntimeError):f.process_due_recurring_expenses(self.b,'2026-02-28')
        self.assertEqual(f.list_recurring_postings(self.b,r),[])
        self.assertEqual(f.get_recurring_expense(self.b,r)['next_due_on'],'2026-01-31')
        self.assertEqual(f.list_transactions(self.b),[])
        self.assertEqual(f.process_due_recurring_expenses(self.b,'2026-02-28')['posted_count'],2)

    def test_audit_failure_rolls_back_whole_batch(self):
        r=self.rule();original=repo.write_audit
        def fail(*args,**kw):
            if args[2]=='FINANCE_RECURRING_POSTED':raise RuntimeError('mock audit')
            return original(*args,**kw)
        with patch.object(repo,'write_audit',side_effect=fail):
            with self.assertRaises(RuntimeError):f.process_due_recurring_expenses(self.b,'2026-02-28')
        self.assertEqual(f.list_transactions(self.b),[]);self.assertEqual(f.list_recurring_postings(self.b,r),[])

    def test_cap_and_catchup_remains(self):
        r=self.rule(cadence='WEEKLY',next_due_on='2020-01-01')
        result=f.process_due_recurring_expenses(self.b,'2026-01-01')
        self.assertEqual(result['posted_count'],100);self.assertTrue(result['has_more']);self.assertTrue(result['limit_reached'])
        self.assertEqual(len(f.list_recurring_postings(self.b,r)),100)
        self.assertEqual(f.process_due_recurring_expenses(self.b,'2026-01-01',max_occurrences=2)['posted_count'],2)
        for limit in (0,101,True,1.5):
            with self.assertRaises(f.FinanceError):f.process_due_recurring_expenses(self.b,'2026-01-01',max_occurrences=limit)

    def test_existing_bill_keeps_archived_category_but_new_manual_writes_reject_it(self):
        rule=self.rule()
        # Historical category overrides may already be archived; scheduled history
        # retains its identity. New manual transactions must still use active options.
        db.execute('UPDATE finance_category_workspace_settings SET is_active=FALSE '
                   'WHERE business_id=? AND category_id=?',(self.b,self.exp))
        self.assertFalse(f.recurring_needs_attention(self.b,rule))
        with self.assertRaisesRegex(f.FinanceError,'category_unavailable'):
            f.create_transaction(self.b,'EXPENSE',100,self.a,self.exp,'2026-01-31',actor_user_id=self.uid)
        self.assertEqual(f.list_transactions(self.b),[])
        paid=f.record_recurring_payment(self.b,rule,'2026-01-31','2026-02-05',self.uid)
        self.assertTrue(paid['created'])
        transactions=f.list_transactions(self.b)
        self.assertEqual(len(transactions),1)
        self.assertEqual(transactions[0]['category_id'],self.exp)
        self.assertEqual(transactions[0]['amount_minor'],100)
        self.assertEqual(transactions[0]['occurred_on'],'2026-02-05')

    def test_invalid_account_category_stays_due_and_can_recover(self):
        r=self.rule()
        # Simulate an invalid stored reference without weakening the write guards.
        for table,value,column,invalid,valid in [('finance_accounts',self.a,'is_active',False,True),('finance_categories',self.exp,'direction','INCOME','EXPENSE')]:
            db.execute(f'UPDATE {table} SET {column}=? WHERE business_id=? AND id=?',(invalid,self.b,value))
            result=f.process_due_recurring_expenses(self.b,'2026-01-31')
            self.assertEqual(result['posted_count'],0);self.assertEqual(result['needs_attention_count'],1)
            self.assertTrue(f.recurring_needs_attention(self.b,r))
            self.assertEqual(f.get_recurring_expense(self.b,r)['next_due_on'],'2026-01-31')
            db.execute(f'UPDATE {table} SET {column}=? WHERE business_id=? AND id=?',(valid,self.b,value))
        self.assertEqual(f.process_due_recurring_expenses(self.b,'2026-01-31')['posted_count'],1)

    def test_cross_tenant_rule_read_deactivate_and_process(self):
        r=self.rule()
        self.assertIsNone(f.get_recurring_expense(self.other,r))
        for action in (lambda:f.deactivate_recurring_expense(self.other,r),lambda:f.list_recurring_postings(self.other,r),
                       lambda:f.process_due_recurring_expenses(self.b,'2026-01-31',actor_user_id=self.other_uid)):
            with self.assertRaises(f.FinanceError):action()
        self.assertEqual(f.process_due_recurring_expenses(self.other,'2026-01-31')['posted_count'],0)
        self.assertEqual(f.list_recurring_postings(self.b,r),[])

    def test_cross_refs_currency_and_income_category_rejected(self):
        for kw in (dict(account_id=f.list_accounts(self.other)[0]['id']),dict(category_id=f.list_categories(self.other,'EXPENSE')[0]['id']),
                   dict(project_id=self.op),dict(category_id=self.cat)):
            with self.assertRaises(f.FinanceError):self.rule(**kw)
        self.assertEqual(f.list_recurring_expenses(self.b),[])

    def test_amount_enum_dates_and_int_precision(self):
        for amount in (0,-1,True,1.5,'100',2**63):
            with self.assertRaises(f.FinanceError):self.rule(amount_minor=amount)
        with self.assertRaises(f.FinanceError):self.rule(cadence='YEARLY')
        with self.assertRaises(f.FinanceError):self.rule(end_on='2026-01-01')
        r=self.rule(amount_minor=2**63-1);f.process_due_recurring_expenses(self.b,'2026-01-31')
        self.assertEqual(f.list_transactions(self.b)[0]['amount_minor'],2**63-1)
        self.assertIs(type(f.list_transactions(self.b)[0]['amount_minor']),int)

    def test_project_contribution_void_and_no_regeneration(self):
        r=self.rule();f.process_due_recurring_expenses(self.b,'2026-01-31')
        f.create_transaction(self.b,'INCOME',300,self.a,self.cat,'2026-01-05',project_id=self.project)
        self.assertEqual(f.get_project_cash_contribution(self.b,'2026-01-01','2026-01-31')[0]['net_cash_contribution_minor'],200)
        tx=f.list_recurring_postings(self.b,r)[0]['ledger_transaction_id'];f.void_transaction(self.b,tx)
        f.process_due_recurring_expenses(self.b,'2026-01-31')
        report=f.get_project_cash_contribution(self.b,'2026-01-01','2026-01-31')[0]
        self.assertEqual(report['expense_minor'],0);self.assertEqual(report['transaction_count'],1)
        self.assertEqual(f.get_finance_summary(self.b,'2026-01-01','2026-01-31')['total_expense_minor'],0)
        self.assertEqual(len(f.list_recurring_postings(self.b,r)),1)
        # Recovery of a cursor pointing at an existing VOID occurrence must not regenerate it.
        db.execute('UPDATE finance_recurring_expenses SET next_due_on=? WHERE business_id=? AND id=?',('2026-01-31',self.b,r))
        self.assertEqual(f.process_due_recurring_expenses(self.b,'2026-01-31')['posted_count'],0)
        self.assertEqual(f.get_transaction(self.b,tx)['status'],'VOID')

    def test_managed_recurring_no_rewrite_manual_still_editable(self):
        r=self.rule();f.process_due_recurring_expenses(self.b,'2026-01-31')
        tx=f.list_recurring_postings(self.b,r)[0]['ledger_transaction_id']
        with self.assertRaises(f.FinanceError):f.update_transaction(self.b,tx,amount_minor=1)
        with self.assertRaises(f.FinanceError):f.create_transaction(self.b,'EXPENSE',1,self.a,self.exp,'2026-01-01',source_type='FINANCE_RECURRING_EXPENSE')
        manual=f.create_transaction(self.b,'EXPENSE',1,self.a,self.exp,'2026-01-01')
        self.assertEqual(f.update_transaction(self.b,manual,amount_minor=2)['amount_minor'],2)

    def test_report_only_scoped_posted_idr_linked_dates(self):
        oa=f.list_accounts(self.other)[0]['id'];oc=f.list_categories(self.other,'INCOME')[0]['id']
        f.create_transaction(self.other,'INCOME',999,oa,oc,'2026-01-01',project_id=self.op)
        f.create_transaction(self.b,'INCOME',7,self.a,self.cat,'2026-01-01')
        f.create_transaction(self.b,'INCOME',8,self.a,self.cat,'2026-02-01',project_id=self.project)
        usd=f.create_account(self.b,'USD',currency='USD')
        f.create_transaction(self.b,'INCOME',9,usd,self.cat,'2026-01-01',project_id=self.project,currency='USD')
        rows=f.get_project_cash_contribution(self.b,'2026-01-01','2026-01-31');self.assertEqual([(r['currency'],r['income_minor']) for r in rows],[('USD',9)])
        self.assertEqual(f.get_project_cash_contribution(self.other,'2026-01-01','2026-01-31')[0]['income_minor'],999)

    def test_cron_is_read_only_and_never_posts_due_bills(self):
        self.rule()
        self.rule(business_id=self.other,account_id=f.list_accounts(self.other)[0]['id'],category_id=f.list_categories(self.other,'EXPENSE')[0]['id'],project_id=self.op,actor_user_id=self.other_uid)
        output=io.StringIO()
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
            self.assertEqual(cron.run('2026-01-31'),0)
            self.assertEqual(cron.run('2026-01-31'),0)
        self.assertIn('auto_post=disabled',output.getvalue())
        self.assertEqual(f.list_transactions(self.b),[])
        self.assertEqual(f.list_transactions(self.other),[])
        self.assertEqual(f.list_recurring_postings(self.b,f.list_recurring_expenses(self.b)[0]['id']),[])

    def test_ui_get_read_only_projects_scoped_and_beta(self):
        self.rule();before=f.list_transactions(self.b)
        html=self.client.get(self.url+'/operations?section=projects').get_data(as_text=True)
        self.assertIn('Tagihan',html);self.assertNotIn('PRIVATE project',html)
        self.assertIn('Arus Kas Proyek',html);self.assertEqual(before,f.list_transactions(self.b))
        html=self.client.get(self.url).get_data(as_text=True)
        self.assertIn('name="project_id"',html);self.assertNotIn('PRIVATE project',html)
        self.assertIn('name="customer_id"',html)
        self.assertEqual(self.client.get(f'/business/{self.other}/finance/operations').status_code,404)
        os.environ['KILAS_FINANCE_BETA']='off'
        self.assertEqual(self.client.get(self.url+'/operations').status_code,404)
        admin=repo.create_user('admin-recurring@example.test','unused',role='KILAS_ADMIN')
        with self.client.session_transaction() as session:session['user_id']=admin
        self.assertEqual(self.client.get(self.url+'/operations').status_code,200)

    def test_ui_posts_csrf_gate_and_scoped_deactivate(self):
        r=self.rule();app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=True
        paths=['/recurring','/recurring/process',f'/recurring/{r}/deactivate']
        for p in paths:self.assertEqual(self.client.post(self.url+p).status_code,400)
        app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=False
        for p in paths:self.assertEqual(self.client.post(f'/business/{self.other}/finance'+p).status_code,404)
        foreign=self.rule(business_id=self.other,account_id=f.list_accounts(self.other)[0]['id'],category_id=f.list_categories(self.other,'EXPENSE')[0]['id'],project_id=self.op,actor_user_id=self.other_uid)
        self.assertEqual(self.client.post(self.url+f'/recurring/{foreign}/deactivate').status_code,404)
        os.environ['KILAS_FINANCE_BETA']='off'
        for p in paths:self.assertEqual(self.client.post(self.url+p).status_code,404)

    def test_ui_create_process_deactivate_and_anchor_not_trusted(self):
        data=dict(name='Routine',amount='123',account_id=self.a,category_id=self.exp,cadence='MONTHLY',next_due_on='2026-01-31',anchor_day='1',project_id=self.project)
        self.assertEqual(self.client.post(self.url+'/recurring',data=data).status_code,303)
        r=f.list_recurring_expenses(self.b)[0]
        self.assertEqual(r['anchor_day'],31)
        self.assertEqual(self.client.post(self.url+'/recurring/process',data={'occurrence':f"{r['id']}:2026-01-31",'paid_on':'2026-01-31','account_id':self.a}).status_code,303)
        transactions=f.list_transactions(self.b)
        self.assertEqual(len(transactions),1)
        self.assertEqual(transactions[0]['amount_minor'],12300)
        self.assertEqual(transactions[0]['occurred_on'],'2026-01-31')
        self.assertEqual(self.client.post(self.url+f'/recurring/{r["id"]}/deactivate').status_code,303)
        self.assertFalse(f.get_recurring_expense(self.b,r['id'])['is_active'])


    def test_occurrence_unique_and_postgres_schema_types(self):
        r=self.rule();f.process_due_recurring_expenses(self.b,'2026-01-31')
        with self.assertRaises(Exception):
            db.execute('INSERT INTO finance_recurring_postings (business_id,recurring_expense_id,scheduled_on,created_at) VALUES (?,?,?,?)',(self.b,r,'2026-01-31','test'))
        self.assertEqual(len(f.list_recurring_postings(self.b,r)),1)
        sql=(Path(__file__).parents[1]/'migrations/0030_finance_recurring_postgres.sql').read_text()
        self.assertIn('amount_minor BIGINT',sql)
        self.assertIn('UNIQUE(business_id,recurring_expense_id,scheduled_on)',sql)
        self.assertIn('ledger_transaction_id BIGINT UNIQUE',sql)
        self.assertNotRegex(sql.upper(),r'\b(REAL|DOUBLE|FLOAT|DROP|DELETE)\b')

    def test_cron_setup_failure_sanitized_and_attention_not_execution_failure(self):
        output=io.StringIO()
        with patch.object(db,'query_one',side_effect=RuntimeError('SECRET DATABASE_URL')),contextlib.redirect_stderr(output):
            self.assertEqual(cron.run('2026-01-31'),1)
        self.assertNotIn('SECRET',output.getvalue())
        self.rule();db.execute('UPDATE finance_accounts SET is_active=FALSE WHERE business_id=? AND id=?',(self.b,self.a))
        before='\n'.join(db.get_connection().iterdump())
        output=io.StringIO()
        with contextlib.redirect_stdout(output):self.assertEqual(cron.run('2026-01-31'),0)
        self.assertEqual(before,'\n'.join(db.get_connection().iterdump()))
        self.assertIn('auto_post=disabled',output.getvalue());self.assertIn('due_rules=1',output.getvalue());self.assertEqual(f.list_transactions(self.b),[])


if __name__=='__main__':unittest.main()
