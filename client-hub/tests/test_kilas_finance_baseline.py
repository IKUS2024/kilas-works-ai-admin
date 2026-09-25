"""Phase 7 audit: real standalone Finance, no Core schemas or Bridge prerequisites."""
import os
import unittest
from unittest.mock import patch
import test_finance_phase2a as prior
import db
import finance_service as finance
import finance_branches as branches
import finance_entitlements as entitlements


class StandaloneBoundaryTests(unittest.TestCase):
    def setUp(self):
        prior.ReceivablesTests.setUp(self)
        self.branch=branches.list_branches(self.b,self.uid)[0]['id']

    def draft(self,customer=None,key=None):
        return finance.create_finance_invoice(self.b,customer or self.c,'2026-09-01','2026-09-15',
            [dict(description='Jasa',quantity=1,unit_price_minor=200000000)],
            actor_user_id=self.uid,idempotency_key=key)

    def test_finance_only_routes_without_core_tables(self):
        self.assertEqual(db.query_all("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'kw_core_%'"),[])
        with patch.dict(os.environ,{'KILAS_CORE_V2_ENABLED':'false','KILAS_CUSTOMERS_V2_ENABLED':'false',
                                  'KILAS_JOBS_V2_ENABLED':'false','KILAS_FINANCE_BRIDGE_ENABLED':'false'}):
            for path in ('','/receivables?section=invoices','/reports','/assistant'):
                with self.subTest(path=path): self.assertEqual(self.client.get(self.url+path).status_code,200)

    def test_existing_compound_boundary_atomically_rolls_back_all_writes(self):
        db.execute('CREATE TABLE qa_core_link(invoice_id INTEGER)')
        customer_count=len(finance.list_customers(self.b))
        with self.assertRaisesRegex(RuntimeError,'link failure'):
            with branches.scope(self.b,self.branch,self.uid),finance._write(self.b,self.uid):
                customer=finance.create_customer(self.b,'Explicit customer',actor_user_id=self.uid,idempotency_key='a'*32)
                invoice=self.draft(customer,'b'*32)
                db.execute('INSERT INTO qa_core_link VALUES (?)',(invoice,))
                raise RuntimeError('link failure')
        self.assertEqual(len(finance.list_customers(self.b)),customer_count)
        self.assertEqual(finance.list_finance_invoices(self.b),[])
        self.assertEqual(db.query_all('SELECT * FROM qa_core_link'),[])

    def test_service_replay_branch_and_authoritative_payment_readback(self):
        with branches.scope(self.b,self.branch,self.uid):
            with finance._write(self.b,self.uid):
                c=finance.create_customer(self.b,'Explicit customer',actor_user_id=self.uid,idempotency_key='c'*32)
                invoice=self.draft(c,'d'*32)
            self.assertEqual(finance.create_customer(self.b,'Explicit customer',actor_user_id=self.uid,idempotency_key='c'*32),c)
            self.assertEqual(self.draft(c,'d'*32),invoice)
            self.assertEqual(finance.get_finance_invoice(self.b,invoice)['branch_id'],self.branch)
            self.assertEqual(finance.get_finance_invoice(self.b,invoice)['status'],'DRAFT')
            self.assertEqual(finance.list_transactions(self.b),[])
            finance.issue_finance_invoice(self.b,invoice,actor_user_id=self.uid)
            for n in (1,2):
                finance.record_invoice_payment(self.b,invoice,100000000,'2026-09-10',self.a,self.cat,
                    actor_user_id=self.uid,idempotency_key='baseline-payment-'+str(n))
                self.assertEqual(finance.get_finance_invoice(self.b,invoice)['status'],'PARTIALLY_PAID' if n==1 else 'PAID')
                self.assertEqual(finance.get_invoice_totals(self.b,invoice)['outstanding_minor'],200000000-n*100000000)
            self.assertEqual(len(finance.list_transactions(self.b)),2)

    def test_expired_emergency_and_all_branch_writes_fail_closed(self):
        invoice=self.draft()
        with patch.dict(os.environ,{'KILAS_FINANCE_ACCESS_MODE':'self_service','KILAS_FINANCE_UNLIMITED_TRIAL':'false'}):
            with self.assertRaisesRegex(finance.FinanceError,'finance_read_only'): self.draft()
            self.assertEqual(finance.get_invoice_totals(self.b,invoice)['total_minor'],200000000)
        with patch.dict(os.environ,{'KILAS_FINANCE_EMERGENCY_DISABLE':'true'}):
            with self.assertRaisesRegex(finance.FinanceError,'finance_read_only'): self.draft()
        with branches.scope(self.b,None,self.uid):
            with self.assertRaisesRegex(finance.FinanceError,'all_branches_read_only'): self.draft()


if __name__=='__main__': unittest.main()
