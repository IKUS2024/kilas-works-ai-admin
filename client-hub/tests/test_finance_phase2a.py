from finance_test_clock import closed_period
"""Offline Finance receivables, integer money, isolation and atomic posting tests."""
import os
import re
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from werkzeug.datastructures import MultiDict
import test_business_hub_v2_phase_a as fixture
import db, repo, finance_service as f
import catalog_service, projects_repo, payment_service

app = fixture.FLASK_APP


class ReceivablesTests(unittest.TestCase):
    def setUp(self):
        fixture.reset_db()
        self.env=patch.dict(os.environ,{'KILAS_FINANCE_BETA':'on'});self.env.start();self.addCleanup(self.env.stop)
        self.http=patch('requests.sessions.Session.request',side_effect=AssertionError('No HTTP'));self.http.start();self.addCleanup(self.http.stop)
        self.uid=repo.create_user('receivable@example.test','unused')
        self.other_uid=repo.create_user('other@example.test','unused')
        self.b=repo.create_business(self.uid,'Business')
        self.other=repo.create_business(self.other_uid,'Other business')
        f.ensure_finance_defaults(self.b);f.ensure_finance_defaults(self.other)
        self.c=f.create_customer(self.b,'Customer <test>',phone='example-phone',email='test@example.test',actor_user_id=self.uid)
        self.oc=f.create_customer(self.other,'PRIVATE CUSTOMER')
        self.a=f.list_accounts(self.b)[0]['id'];self.cat=f.list_categories(self.b,'INCOME')[0]['id']
        self.client=app.test_client()
        with self.client.session_transaction() as session: session['user_id']=self.uid
        self.url=f'/business/{self.b}/finance'
        app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=False
        self.addCleanup(lambda: app.config.update(CLIENT_HUB_FORCE_CSRF_IN_TESTS=False))

    def draft(self,**kw):
        args=dict(business_id=self.b,customer_id=self.c,issue_date='2026-09-01',due_date='2026-09-15',
                  items=[dict(description='Service',quantity=2,unit_price_minor=100),dict(description='Extra',quantity=1,unit_price_minor=50)],actor_user_id=self.uid)
        args.update(kw);return f.create_finance_invoice(**args)

    def issued(self):
        i=self.draft();f.issue_finance_invoice(self.b,i,actor_user_id=self.uid);return i

    def pay(self,i,amount=100,key='payment-submission-key-1',**kw):
        args=dict(business_id=self.b,invoice_id=i,amount_minor=amount,paid_on='2026-09-10',account_id=self.a,
                  income_category_id=self.cat,actor_user_id=self.uid,idempotency_key=key)
        args.update(kw);return f.record_invoice_payment(**args)

    def test_migration_repeat_and_repair_index_preserves_manual_history(self):
        tx=f.create_transaction(self.b,'INCOME',123,self.a,self.cat,'2026-09-01')
        self.draft()
        before=f.get_transaction(self.b,tx)
        db.execute('DROP INDEX idx_finance_transactions_business_customer')
        db.init_schema();db.init_schema()
        self.assertEqual(before,f.get_transaction(self.b,tx))
        self.assertIsNone(before['customer_id'])
        self.assertEqual([r['name'] for r in db.query_all('PRAGMA index_info(idx_finance_transactions_business_customer)')],['business_id','customer_id'])

    def test_customer_scope_lengths_and_safe_audit(self):
        self.assertIsNone(f.get_customer(self.other,self.c))
        self.assertEqual(len(f.list_customers(self.b)),1)
        with self.assertRaises(f.FinanceError):f.get_customer(self.b,self.c,actor_user_id=self.other_uid)
        with self.assertRaises(f.FinanceError):f.create_customer(self.b,'x'*161)
        audit=db.query_all("SELECT detail FROM audit_log WHERE action='FINANCE_CUSTOMER_CREATED'")
        self.assertNotIn('example-phone',str(audit));self.assertNotIn('Customer <test>',str(audit))

    def test_invoice_items_integer_totals_and_number(self):
        i=self.draft()
        self.assertEqual(f.get_finance_invoice(self.b,i)['invoice_number'],f'KFIN-2026-{i:06d}')
        t=f.get_invoice_totals(self.b,i)
        self.assertEqual(t['total_minor'],250);self.assertIs(type(t['total_minor']),int)
        self.assertEqual(len(f.list_invoice_items(self.b,i)),2)
        self.assertEqual(f.get_finance_invoice(self.b,i)['status'],'DRAFT')

    def test_invalid_dates_items_float_overflow(self):
        with self.assertRaises(f.FinanceError):self.draft(due_date='2026-08-01')
        for q,p in ((0,1),(True,1),(1.5,1),(1,-1),(1,1.1),(2,2**62),(1,2**63)):
            with self.subTest(q=q,p=p),self.assertRaises(f.FinanceError):self.draft(items=[dict(description='a',quantity=q,unit_price_minor=p)])
        with self.assertRaises(f.FinanceError):self.draft(items=[dict(description='a',quantity=1,unit_price_minor=2**62)]*2)
        for items in ([],[dict(description='',quantity=1,unit_price_minor=1)],'not a list'):
            with self.assertRaises(f.FinanceError):self.draft(items=items)
        self.assertEqual(f.list_finance_invoices(self.b),[])

    def test_issue_and_terminal_states(self):
        i=self.draft();f.issue_finance_invoice(self.b,i)
        self.assertEqual(f.get_finance_invoice(self.b,i)['status'],'ISSUED')
        with self.assertRaises(f.FinanceError):f.issue_finance_invoice(self.b,i)
        f.void_finance_invoice(self.b,i)
        with self.assertRaises(f.FinanceError):f.issue_finance_invoice(self.b,i)
        with self.assertRaises(f.FinanceError):self.pay(i)
        self.assertEqual(len(f.list_invoice_items(self.b,i)),2)
        with self.assertRaises(f.FinanceError):self.pay(self.draft())

    def test_partial_full_exactly_one_income_per_payment(self):
        i=self.issued();p=self.pay(i)
        self.assertEqual(f.get_finance_invoice(self.b,i)['status'],'PARTIALLY_PAID')
        payment=f.list_invoice_payments(self.b,i)[0]
        ledger=f.get_transaction(self.b,payment['ledger_transaction_id'])
        self.assertEqual(payment['id'],p)
        for k,v in dict(direction='INCOME',amount_minor=100,customer_id=self.c,status='POSTED',source_type='FINANCE_INVOICE_PAYMENT',source_ref=str(p)).items():self.assertEqual(ledger[k],v)
        self.pay(i,150,'payment-submission-key-2')
        self.assertEqual(f.get_invoice_totals(self.b,i)['outstanding_minor'],0)
        self.assertEqual(f.get_finance_invoice(self.b,i)['status'],'PAID')
        self.assertEqual(len(f.list_transactions(self.b)),2)
        with self.assertRaises(f.FinanceError):self.pay(i,1,'payment-submission-key-3')

    def test_overpayment_and_invalid_money_no_writes(self):
        i=self.issued()
        for amount in (251,0,-1,1.1,True):
            with self.assertRaises(f.FinanceError):self.pay(i,amount)
        self.assertEqual(f.list_invoice_payments(self.b,i),[]);self.assertEqual(f.list_transactions(self.b),[])

    def test_retry_returns_same_payment_even_after_paid(self):
        i=self.issued();first=self.pay(i,250)
        self.assertEqual(self.pay(i,250),first)
        self.assertEqual(len(f.list_transactions(self.b)),1)
        self.assertEqual(len(f.list_invoice_payments(self.b,i)),1)
        with self.assertRaises(f.FinanceError):self.pay(i,249)

    def test_failure_rolls_back_all_then_retry_once(self):
        i=self.issued()
        original=repo.write_audit
        def failing(*args,**kw):
            if args[2]=='FINANCE_INVOICE_PAYMENT_RECORDED':raise RuntimeError('mock failure')
            return original(*args,**kw)
        with patch.object(repo,'write_audit',side_effect=failing):
            with self.assertRaises(RuntimeError):self.pay(i)
        self.assertEqual(f.list_transactions(self.b),[]);self.assertEqual(f.list_invoice_payments(self.b,i),[])
        self.assertEqual(f.get_finance_invoice(self.b,i)['status'],'ISSUED')
        self.pay(i);self.pay(i)
        self.assertEqual(len(f.list_transactions(self.b)),1)

    def test_invoice_creation_audit_failure_rolls_back_items(self):
        with patch.object(repo,'write_audit',side_effect=RuntimeError('audit')):
            with self.assertRaises(RuntimeError):self.draft()
        self.assertEqual(f.list_finance_invoices(self.b),[])
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_invoice_items')['n'],0)

    def test_concurrent_sqlite_payment_retries(self):
        i=self.issued();barrier=threading.Barrier(2)
        def worker(_):
            try:
                barrier.wait();return self.pay(i,150)
            finally:
                if getattr(db._local,'conn',None):db._local.conn.close();db._local.conn=None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(worker,range(2)))
        self.assertEqual(results[0],results[1]);self.assertEqual(len(f.list_transactions(self.b)),1)

    def test_concurrent_sqlite_distinct_payments_cannot_overpay(self):
        i=self.issued();barrier=threading.Barrier(2)
        def worker(n):
            try:
                barrier.wait()
                try:return self.pay(i,150,f'concurrent-payment-{n}')
                except f.FinanceError:return 'rejected'
            finally:
                if getattr(db._local,'conn',None):db._local.conn.close();db._local.conn=None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(worker,range(2)))
        self.assertEqual(results.count('rejected'),1)
        self.assertEqual(f.get_invoice_totals(self.b,i)['paid_minor'],150)

    def test_paid_invoice_and_linked_ledger_cannot_void_or_edit(self):
        i=self.issued();self.pay(i)
        with self.assertRaises(f.FinanceError):f.void_finance_invoice(self.b,i)
        tx=f.list_invoice_payments(self.b,i)[0]['ledger_transaction_id']
        with self.assertRaises(f.FinanceError):f.void_transaction(self.b,tx)
        with self.assertRaises(f.FinanceError):f.update_transaction(self.b,tx,amount_minor=1)
        self.assertEqual(f.get_transaction(self.b,tx)['amount_minor'],100)

    def test_cross_tenant_invoice_customer_payment_references(self):
        i=self.issued();self.pay(i)
        self.assertIsNone(f.get_finance_invoice(self.other,i))
        for action in (lambda:f.list_invoice_items(self.other,i),lambda:f.list_invoice_payments(self.other,i),
                       lambda:self.draft(customer_id=self.oc),lambda:f.issue_finance_invoice(self.other,i),
                       lambda:f.void_finance_invoice(self.other,i)):
            with self.assertRaises(f.FinanceError):action()
        for kw in (dict(account_id=f.list_accounts(self.other)[0]['id']),dict(income_category_id=f.list_categories(self.other,'INCOME')[0]['id']),
                   dict(income_category_id=f.list_categories(self.b,'EXPENSE')[0]['id'])):
            with self.assertRaises(f.FinanceError):self.pay(i,50,'new-payment-key-123',**kw)

    @closed_period
    def test_manual_customer_link_and_contribution(self):
        with self.assertRaises(f.FinanceError):f.create_transaction(self.b,'INCOME',1,self.a,self.cat,'2026-09-01',customer_id=self.oc)
        i=self.issued();self.pay(i,100)
        expense=f.list_categories(self.b,'EXPENSE')[0]['id']
        t=f.create_transaction(self.b,'EXPENSE',40,self.a,expense,'2026-09-02',customer_id=self.c)
        f.create_transaction(self.b,'INCOME',999,self.a,self.cat,'2026-10-01',customer_id=self.c)
        report=f.get_customer_cash_contribution(self.b,'2026-09-01','2026-09-30')[0]
        self.assertEqual(report['net_cash_contribution_minor'],60)
        f.void_transaction(self.b,t)
        self.assertEqual(f.get_customer_cash_contribution(self.b,'2026-09-01','2026-09-30')[0]['net_cash_contribution_minor'],100)
        self.assertEqual(f.get_customer_cash_contribution(self.other,'2026-09-01','2026-09-30'),[])

    def test_receivables_excludes_draft_void_paid_and_due_today(self):
        self.draft();v=self.issued();f.void_finance_invoice(self.b,v)
        paid=self.issued();self.pay(paid,250)
        partial=self.issued();self.pay(partial,50,'partial-payment-key')
        later=self.draft(due_date='2026-09-16');f.issue_finance_invoice(self.b,later)
        summary=f.get_receivables_summary(self.b,today='2026-09-16')
        self.assertEqual({key:summary[key] for key in ('total_outstanding_minor','overdue_outstanding_minor','open_invoice_count','overdue_invoice_count')},dict(total_outstanding_minor=450,overdue_outstanding_minor=200,open_invoice_count=2,overdue_invoice_count=1))

    def test_platform_commerce_untouched_with_colliding_ids(self):
        catalog_service.seed_catalog_if_needed()
        item=catalog_service.get_catalog_item('content_basic')
        project=projects_repo.create_fixed_price_project(self.b,item,self.uid)
        platform_id=payment_service.checkout(project,self.b,self.uid)
        before={t:db.query_all('SELECT * FROM '+t) for t in ('invoices','payments','projects')}
        finance_id=self.issued()
        self.assertEqual(finance_id,platform_id)  # independent tables intentionally collide
        self.pay(finance_id,250)
        self.assertTrue(f.get_finance_invoice(self.b,finance_id)['invoice_number'].startswith('KFIN-'))
        self.assertEqual(before,{t:db.query_all('SELECT * FROM '+t) for t in before})
        second_platform=payment_service.checkout(project,self.b,self.uid)
        self.assertEqual(second_platform,platform_id)

    def test_new_routes_gate_scope_and_csrf(self):
        i=self.draft()
        paths=['/customers','/invoices/new',f'/invoices/{i}/issue',f'/invoices/{i}/void',f'/invoices/{i}/payments']
        app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=True
        for path in paths:self.assertEqual(self.client.post(self.url+path).status_code,400)
        app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=False
        for path in ['/receivables','/invoices/new',f'/invoices/{i}']:
            self.assertEqual(self.client.get(f'/business/{self.other}/finance'+path).status_code,404)
        for path in paths:self.assertEqual(self.client.post(f'/business/{self.other}/finance'+path).status_code,404)
        os.environ['KILAS_FINANCE_BETA']='off'
        self.assertEqual(self.client.get(self.url+'/receivables').status_code,404)
        admin=repo.create_user('admin@example.test','unused',role='KILAS_ADMIN')
        with self.client.session_transaction() as session:session['user_id']=admin
        self.assertEqual(self.client.get(self.url+'/receivables').status_code,200)

    def test_ui_create_issue_pay_double_submit_and_print(self):
        form=MultiDict({'customer_id':str(self.c),'issue_date':'2026-09-01','due_date':'2026-09-15'})
        form.update(dict(currency='IDR',submission_key='a'*32,sender_name='Business',sender_address='Office',sender_phone='08123',recipient_name='Customer <test>'))
        for d,q,p in [('One','2','100'),('Two','1','50')]:
            form.add('item_description',d);form.add('quantity',q);form.add('unit_price',p)
        result=self.client.post(self.url+'/invoices/new',data=form)
        self.assertEqual(result.status_code,303)
        detail=__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(result.location).path;i=f.list_finance_invoices(self.b)[0]['id']
        self.assertIn('Terbitkan Invoice',self.client.get(detail).get_data(as_text=True))
        self.client.post(detail+'/issue')
        html=self.client.get(detail).get_data(as_text=True)
        self.assertIn('window.print()',html);self.assertIn('Customer &lt;test&gt;',html)
        key=re.search(r'name="payment_key" value="([^"]+)"',html)[1]
        data=dict(amount='100',paid_on='2026-09-10',account_id=self.a,category_id=self.cat,payment_key=key)
        for _ in range(2):self.assertEqual(self.client.post(detail+'/payments',data=data).status_code,303)
        self.assertEqual(len(f.list_invoice_payments(self.b,i)),1)
        html=self.client.get(self.url+'/receivables?section=invoices').get_data(as_text=True)
        self.assertIn('Dibayar sebagian',html);self.assertIn('Rp150',html)

    def test_ui_customer_create_manual_dropdown_and_no_get_writes(self):
        before=db.query_all('SELECT * FROM audit_log')
        for path in ('','/receivables','/invoices/new'):self.assertEqual(self.client.get(self.url+path).status_code,200)
        self.assertEqual(before,db.query_all('SELECT * FROM audit_log'))
        self.assertEqual(self.client.post(self.url+'/customers',data={'name':'New customer'}).status_code,303)
        self.assertIn('name="customer_id"',self.client.get(self.url).get_data(as_text=True))
        self.assertEqual(len(f.list_customers(self.b)),2)


    def test_payment_account_active_idr_and_key_conflict(self):
        i=self.issued()
        usd=f.create_account(self.b,'Dollar',currency='USD')
        with self.assertRaises(f.FinanceError):self.pay(i,account_id=usd)
        db.execute('UPDATE finance_accounts SET is_active=FALSE WHERE business_id=? AND id=?',(self.b,self.a))
        with self.assertRaises(f.FinanceError):self.pay(i)
        db.execute('UPDATE finance_accounts SET is_active=TRUE WHERE business_id=? AND id=?',(self.b,self.a))
        self.pay(i)
        with self.assertRaises(f.FinanceError):self.pay(self.issued())
        self.assertEqual(len(f.list_transactions(self.b)),1)

    def test_invoice_foreign_id_on_own_route_and_logged_out(self):
        foreign=self.draft(business_id=self.other,customer_id=self.oc,actor_user_id=self.other_uid)
        for suffix in ('','/issue','/void','/payments'):
            path=self.url+f'/invoices/{foreign}'+suffix
            if suffix=='/payments':
                result=self.client.post(path,data=dict(amount='1',paid_on='2026-09-10',account_id=self.a,category_id=self.cat,payment_key='tampered-form-key-123'))
            else:result=(self.client.post if suffix else self.client.get)(path)
            self.assertEqual(result.status_code,404)
            self.assertNotIn('PRIVATE CUSTOMER',result.get_data(as_text=True))
        anonymous=app.test_client()
        self.assertEqual(anonymous.get(self.url+'/receivables').status_code,302)
        os.environ['KILAS_FINANCE_BETA']='off'
        for suffix in ('/customers','/invoices/new','/invoices/1/issue','/invoices/1/void','/invoices/1/payments'):
            self.assertEqual(self.client.post(self.url+suffix).status_code,404)

    def test_max_int_invoice_and_zero_price_line(self):
        i=self.draft(items=[dict(description='Free',quantity=1,unit_price_minor=0),dict(description='Exact',quantity=1,unit_price_minor=2**63-1)])
        f.issue_finance_invoice(self.b,i)
        self.assertEqual(f.get_invoice_totals(self.b,i)['total_minor'],2**63-1)
        self.pay(i,2**63-1)
        self.assertEqual(f.get_invoice_totals(self.b,i)['outstanding_minor'],0)
        self.assertIs(type(f.list_transactions(self.b)[0]['amount_minor']),int)

    def test_manual_update_cross_customer_and_reserved_source_rejected(self):
        tx=f.create_transaction(self.b,'INCOME',1,self.a,self.cat,'2026-09-01',customer_id=self.c)
        for changes in (dict(customer_id=self.oc),dict(source_type='FINANCE_INVOICE_PAYMENT')):
            with self.assertRaises(f.FinanceError):f.update_transaction(self.b,tx,**changes)
        with self.assertRaises(f.FinanceError):f.create_transaction(self.b,'INCOME',1,self.a,self.cat,'2026-09-01',source_type='FINANCE_INVOICE_PAYMENT')
        self.assertEqual(f.get_transaction(self.b,tx)['customer_id'],self.c)

    def test_postgres_migration_definitions_and_bound_parameters(self):
        root=Path(__file__).parents[1]
        sql=(root/'migrations/0029_finance_receivables_postgres.sql').read_text()
        self.assertIn('ADD COLUMN IF NOT EXISTS customer_id BIGINT',sql)
        self.assertIn('UNIQUE(business_id,idempotency_key)',sql)
        for table in ('finance_customers','finance_invoices','finance_invoice_items','finance_invoice_payments'):
            self.assertIn('CREATE TABLE IF NOT EXISTS '+table,sql)
        self.assertNotRegex(sql.upper(),r'\b(REAL|DOUBLE|FLOAT|DROP|DELETE)\b')
        original=db.BACKEND
        try:
            db.BACKEND='postgres'
            self.assertEqual(db._adapt_placeholders('SELECT id FROM finance_invoices WHERE business_id=? AND id=?'),
                             'SELECT id FROM finance_invoices WHERE business_id=%s AND id=%s')
        finally:db.BACKEND=original


if __name__=='__main__':unittest.main()
