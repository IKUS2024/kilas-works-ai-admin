"""Read-only reporting/export calculations, privacy, boundaries and limits. Offline only."""
import csv
from datetime import date,timedelta
import io
from pathlib import Path
import os
import unittest
from unittest.mock import patch
import zipfile
import test_finance_phase2a as prior
import finance_reports as reports

f,db,repo,app=prior.f,prior.db,prior.repo,prior.app


class ReportsTests(unittest.TestCase):
    def setUp(self):
        prior.ReceivablesTests.setUp(self)
        self.exp=f.list_categories(self.b,'EXPENSE')[0]['id']
        self.project=db.insert_returning_id("INSERT INTO projects (business_id,project_type,pricing_mode,title,status,created_by_user_id) VALUES (?,'CONTENT','CUSTOM_QUOTE','My project','REQUESTED',?)",(self.b,self.uid))
        self.filters=reports.parse_filters(dict(start='2026-09-01',end='2026-09-30',as_of='2026-09-30',commitment_start='2026-09-01',commitment_end='2026-09-30'))
        self.query='?start=2026-09-01&end=2026-09-30&as_of=2026-09-30&commitment_start=2026-09-01&commitment_end=2026-09-30'

    def tx(self,amount=100,direction='INCOME',**kw):
        args=dict(business_id=self.b,direction=direction,amount_minor=amount,account_id=self.a,category_id=self.cat if direction=='INCOME' else self.exp,occurred_on='2026-09-15',customer_id=self.c,project_id=self.project)
        args.update(kw);return f.create_transaction(**args)

    def invoice(self,due='2026-09-15',status='ISSUED',issue='2026-01-01'):
        i=f.create_finance_invoice(self.b,self.c,issue,due,[dict(description='Service',quantity=1,unit_price_minor=250)])
        if status!='DRAFT':f.issue_finance_invoice(self.b,i)
        if status=='VOID':f.void_finance_invoice(self.b,i)
        if status=='PAID':self.pay(i,250)
        return i

    def pay(self,i,amount,paid_on='2026-09-15'):
        return f.record_invoice_payment(self.b,i,amount,paid_on,self.a,self.cat,idempotency_key=f'invoice-payment-{i}-{amount}-{paid_on}')

    def parse_csv(self,data):return list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))

    def test_cashflow_category_counts_percent_and_void(self):
        self.tx(100);self.tx(200);self.tx(50,'EXPENSE')
        void=self.tx(999);f.void_transaction(self.b,void)
        self.tx(800,occurred_on='2026-10-01')
        result=f.get_cashflow_report(self.b,'2026-09-01','2026-09-30')
        self.assertEqual(result,dict(total_income_minor=300,total_expense_minor=50,net_cashflow_minor=250,transaction_count=3))
        rows=f.get_category_breakdown(self.b,'2026-09-01','2026-09-30')
        self.assertEqual([r['percentage'] for r in rows],['100.00','100.00'])
        self.assertEqual(rows[1]['transaction_count'],2)
        self.assertEqual(f.get_category_breakdown(self.other,'2026-09-01','2026-09-30'),[])

    def test_category_sort_and_integer_ratio(self):
        bcat=f.create_category(self.b,'INCOME','B category');acat=f.create_category(self.b,'INCOME','A category')
        self.tx(100,category_id=bcat);self.tx(100,category_id=acat);self.tx(100)
        rows=f.get_category_breakdown(self.b,'2026-09-01','2026-09-30')
        self.assertTrue(all(r['percentage']=='33.33' for r in rows))
        self.assertEqual([r['name'] for r in rows],sorted(r['name'] for r in rows))

    def test_account_balances_idr_inactive_and_asof(self):
        db.execute('UPDATE finance_accounts SET opening_balance_minor=500 WHERE business_id=? AND id=?',(self.b,self.a))
        self.tx(200,occurred_on='2026-08-01');self.tx(50,'EXPENSE');self.tx(800,occurred_on='2026-10-01')
        void=self.tx(999);f.void_transaction(self.b,void)
        f.create_account(self.b,'Dollar',currency='USD',opening_balance_minor=1000)
        db.execute('UPDATE finance_accounts SET is_active=FALSE WHERE business_id=? AND id=?',(self.b,self.a))
        rows=f.get_account_balance_report(self.b,'2026-09-30')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['balance_minor'],650)
        self.assertEqual(rows[0]['income_minor'],200);self.assertFalse(rows[0]['is_active'])

    def test_customer_project_contributions_and_period(self):
        self.tx(200);self.tx(50,'EXPENSE')
        void=self.tx(99,'EXPENSE');f.void_transaction(self.b,void)
        self.tx(1,customer_id=None,project_id=None)
        customer=f.get_customer_contribution_report(self.b,'2026-09-01','2026-09-30')[0]
        project=f.get_project_contribution_report(self.b,'2026-09-01','2026-09-30')[0]
        self.assertEqual(customer['name'],'Customer <test>');self.assertEqual(customer['transaction_count'],2)
        self.assertEqual(project['title'],'My project');self.assertEqual(project['net_cash_contribution_minor'],150)
        self.assertEqual(customer['net_cash_contribution_minor'],150)

    def test_aging_exact_boundaries_and_partial(self):
        asof=date(2026,9,30)
        for late in (-1,0,1,30,31,60,61,90,91):
            i=self.invoice((asof-timedelta(days=late)).isoformat())
            if late==91:self.pay(i,100)
        self.invoice(status='DRAFT');self.invoice(status='VOID');self.invoice(status='PAID')
        result=f.get_receivables_aging(self.b,'2026-09-30')
        self.assertEqual([r['amount_minor'] for r in result['buckets']],[500,500,500,500,150])
        self.assertEqual([r['invoice_count'] for r in result['buckets']],[2,2,2,2,1])
        self.assertEqual(result['total_outstanding_minor'],2150);self.assertEqual(result['total_overdue_minor'],1650)

    def test_aging_payments_asof_and_future_issue(self):
        i=self.invoice(due='2026-09-01');self.pay(i,100,paid_on='2026-09-20')
        self.invoice(due='2026-10-01',issue='2026-10-01')
        self.assertEqual(f.get_receivables_aging(self.b,'2026-09-15')['total_outstanding_minor'],250)
        self.assertEqual(f.get_receivables_aging(self.b,'2026-09-30')['total_outstanding_minor'],150)

    def test_commitments_weekly_month_end_and_no_writes(self):
        f.create_recurring_expense(self.b,'Monthly',100,self.a,self.exp,'MONTHLY','2024-01-31',project_id=self.project)
        f.create_recurring_expense(self.b,'Weekly',50,self.a,self.exp,'WEEKLY','2024-02-01',end_on='2024-02-15')
        before=f.list_recurring_expenses(self.b)
        result=f.get_upcoming_recurring_commitments(self.b,'2024-02-01','2024-03-31')
        self.assertEqual([r['scheduled_on'] for r in result if r['name']=='Monthly'],['2024-02-29','2024-03-31'])
        self.assertEqual([r['scheduled_on'] for r in result if r['name']=='Weekly'],['2024-02-01','2024-02-08','2024-02-15'])
        self.assertEqual(before,f.list_recurring_expenses(self.b));self.assertEqual(f.list_transactions(self.b),[])
        f.deactivate_recurring_expense(self.b,before[0]['id'])
        self.assertTrue(all(r['name']!='Monthly' for r in f.get_upcoming_recurring_commitments(self.b,'2024-02-01','2024-03-31')))

    def test_forecast_cap_and_old_rule_fast_forward(self):
        f.create_recurring_expense(self.b,'Weekly',50,self.a,self.exp,'WEEKLY','2000-01-01')
        with patch.object(f,'MAX_COMMITMENT_OCCURRENCES',2):
            with self.assertRaises(f.FinanceError):f.get_upcoming_recurring_commitments(self.b,'2026-09-01','2026-09-30')
        self.assertEqual(f.list_transactions(self.b),[])

    def test_monthly_trend_boundaries_partial_month_and_zero_months(self):
        self.tx(100,occurred_on='2026-08-31');self.tx(200,occurred_on='2026-09-01')
        self.tx(50,'EXPENSE',occurred_on='2026-09-30');self.tx(999,occurred_on='2026-10-01')
        trend=f.get_monthly_cashflow_trend(self.b,'2026-07','2026-09')
        self.assertEqual([r['net_cashflow_minor'] for r in trend],[0,100,150])
        part=f.get_monthly_cashflow_trend(self.b,'2026-09','2026-09',start_date='2026-09-10',end_date='2026-09-30')
        self.assertEqual(part[0]['net_cashflow_minor'],-50)
        with self.assertRaises(f.FinanceError):f.get_monthly_cashflow_trend(self.b,'2025-09','2026-09')

    def test_integer_money_beyond_float_precision(self):
        value=2**63-1;self.tx(value);self.tx(value)
        self.assertEqual(f.get_cashflow_report(self.b,'2026-09-01','2026-09-30')['total_income_minor'],value*2)
        self.assertEqual(f.get_account_balance_report(self.b,'2026-09-30')[0]['balance_minor'],value*2)

    def test_csv_formula_neutralization_and_normal_text(self):
        for text in ('=SUM(A1:A2)','+cmd','-1+2','@evil','   =SUM(A1:A2)','\t@evil','\r\n+cmd'):
            self.assertEqual(reports.csv_cell(text),"'"+text)
        self.assertEqual(reports.csv_cell('Pemasukan jasa'),'Pemasukan jasa')
        self.assertEqual(reports.csv_cell(-100),'-100')

    def test_transaction_csv_bom_quoting_and_numeric_history(self):
        self.tx(1500000,description='=SUM(A1:A2)',counterparty_name='Vendor, "A"\nB')
        v=self.tx(50,'EXPENSE');f.void_transaction(self.b,v)
        data=reports.export_csv('transactions',self.b,self.filters,self.uid)
        self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
        rows=self.parse_csv(data);self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['nominal_rupiah'],'1500000')
        self.assertEqual(rows[0]['deskripsi'],"'=SUM(A1:A2)")
        self.assertEqual(rows[0]['pihak_lawan'],'Vendor, "A"\nB');self.assertEqual(rows[1]['status'],'Dibatalkan')
        self.assertEqual(f.list_transactions(self.b)[-1]['description'],'=SUM(A1:A2)')

    def test_join_tenant_scope_export_and_actor(self):
        op=db.insert_returning_id("INSERT INTO projects (business_id,project_type,pricing_mode,title,status,created_by_user_id) VALUES (?,'CONTENT','CUSTOM_QUOTE','PRIVATE PROJECT','REQUESTED',?)",(self.other,self.other_uid))
        oa=f.create_account(self.other,'PRIVATE ACCOUNT');oc=f.create_category(self.other,'INCOME','PRIVATE CATEGORY')
        f.create_transaction(self.other,'INCOME',999,oa,oc,'2026-09-01',customer_id=self.oc,project_id=op,description='PRIVATE TRANSACTION')
        self.tx()
        for name in ('transactions','customers','projects','accounts','category_breakdown'):
            self.assertNotIn('PRIVATE',reports.export_csv(name,self.b,self.filters,self.uid).decode('utf-8-sig'))
        with self.assertRaises(f.FinanceError):reports.export_csv('transactions',self.other,self.filters,self.uid)
        # Defensive joined labels still do not leak if an old DB row's project/customer link is wrong.
        db.execute('UPDATE finance_transactions SET project_id=?,customer_id=? WHERE business_id=?',(op,self.oc,self.b))
        row=f.get_report_transactions(self.b,'2026-09-01','2026-09-30')[0]
        self.assertIsNone(row['project_name']);self.assertIsNone(row['customer_name'])

    def test_finance_invoice_export_period_and_platform_separation(self):
        prior.catalog_service.seed_catalog_if_needed()
        project=prior.projects_repo.create_fixed_price_project(self.b,prior.catalog_service.get_catalog_item('content_basic'),self.uid)
        prior.payment_service.checkout(project,self.b,self.uid)
        before={t:db.query_all('SELECT * FROM '+t) for t in ('invoices','payments')}
        self.invoice(issue='2026-09-01');self.invoice(issue='2026-08-01')
        foreign=f.create_finance_invoice(self.other,self.oc,'2026-09-01','2026-09-15',[dict(description='PRIVATE ITEM',quantity=1,unit_price_minor=888)])
        rows=self.parse_csv(reports.export_csv('invoices',self.b,self.filters,self.uid))
        self.assertEqual(len(rows),1);self.assertTrue(rows[0]['nomor_invoice'].startswith('KFIN-'))
        self.assertNotIn('PRIVATE',str(rows));self.assertEqual(before,{t:db.query_all('SELECT * FROM '+t) for t in before})

    def test_zip_expected_names_and_identical_csv_builders(self):
        self.tx()
        result=self.client.get(self.url+'/reports/export/all.zip'+self.query)
        self.assertEqual(result.status_code,200);self.assertEqual(result.mimetype,'application/zip')
        self.assertIn('attachment;',result.headers['Content-Disposition'])
        with zipfile.ZipFile(io.BytesIO(result.data)) as z:
            self.assertEqual(z.namelist(),[n+'.csv' for n in reports.REPORT_NAMES])
            for name in reports.REPORT_NAMES:
                single=self.client.get(self.url+'/reports/export/'+name+'.csv'+self.query)
                self.assertEqual(single.status_code,200)
                self.assertEqual(z.read(name+'.csv'),single.data)

    def test_route_auth_beta_and_header_safety(self):
        paths=('/reports','/reports/export/transactions.csv','/reports/export/invoices.csv','/reports/export/all.zip')
        for path in paths:
            self.assertEqual(app.test_client().get(self.url+path).status_code,302)
            self.assertEqual(self.client.get(f'/business/{self.other}/finance'+path).status_code,404)
        os.environ['KILAS_FINANCE_BETA']='off'
        for path in paths:self.assertEqual(self.client.get(self.url+path).status_code,404)
        admin=repo.create_user('reports-admin@example.test','unused',role='KILAS_ADMIN')
        with self.client.session_transaction() as session:session['user_id']=admin
        self.assertEqual(self.client.get(self.url+'/reports').status_code,200)
        result=self.client.get(self.url+'/reports/export/transactions.csv'+self.query+'&filename=evil')
        self.assertNotIn('evil',result.headers['Content-Disposition'])
        self.assertEqual(self.client.get(self.url+'/reports/export/evil.csv').status_code,404)

    def test_invalid_filters_and_presets(self):
        for args in ({'start':'wrong'},{'start':'2026-02-30'},{'start':'2026-10-01','end':'2026-09-01'},
                     {'start':'2025-01-01','end':'2026-01-02'},{'start':'2025-01-01','end':'2026-01-01'},
                     {'preset':'evil'},{'as_of':'secret-value'},{'commitment_start':'2025-01-01','commitment_end':'2026-01-02'}):
            with self.assertRaises(f.FinanceError):reports.parse_filters(args,today=date(2026,9,15))
        self.assertEqual(reports.parse_filters({'preset':'three'},date(2026,1,15))['start'],'2025-11-01')
        self.assertEqual(reports.parse_filters({'preset':'year'},date(2026,9,15))['start'],'2026-01-01')
        result=self.client.get(self.url+'/reports/export/all.zip?start=SECRET')
        self.assertEqual(result.status_code,400);self.assertNotIn('SECRET',result.get_data(as_text=True))

    def test_limits_do_not_truncate_csv_or_zip(self):
        self.tx();self.tx()
        with patch.object(f,'MAX_REPORT_ROWS',1):
            with self.assertRaises(f.FinanceError):reports.export_csv('transactions',self.b,self.filters,self.uid)
            result=self.client.get(self.url+'/reports/export/all.zip'+self.query)
            self.assertEqual(result.status_code,400);self.assertFalse(result.data.startswith(b'PK'))
        with patch.object(reports,'MAX_CSV_BYTES',10):
            with self.assertRaises(f.FinanceError):reports.csv_bytes(['header'],[['text']])
        with patch.object(reports,'MAX_BUNDLE_BYTES',10):
            with self.assertRaises(f.FinanceError):reports.export_zip(self.b,self.filters,self.uid)

    def test_print_report_empty_states_no_writes_and_scoped_files(self):
        before={t:db.query_all('SELECT * FROM '+t) for t in ('audit_log','finance_transactions','finance_recurring_postings','finance_invoices')}
        result=self.client.get(self.url+'/reports'+self.query)
        self.assertEqual(result.status_code,200)
        html=result.get_data(as_text=True)
        for text in ('window.print()','Cetak / Simpan PDF','@media print','Belum ada data','bukan laporan laba rugi akuntansi','belum tentu sama dengan saldo bank aktual'):
            self.assertIn(text,html)
        self.assertEqual(before,{t:db.query_all('SELECT * FROM '+t) for t in before})
        self.assertIn('no-store',result.headers['Cache-Control'])


if __name__=='__main__':unittest.main()
