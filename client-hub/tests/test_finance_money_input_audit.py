"""Localized money input must not turn decimal fractions into thousands."""
import unittest
import test_finance_approved_revisions as fixture
import db
import finance_service as f
import finance_branches as branches
from routes_finance import currency_amount


class MoneyInputAuditTests(unittest.TestCase):
    setUp = fixture.ApprovedFinanceTests.setUp

    def test_mixed_separators_use_last_separator_as_decimal(self):
        for currency in ('IDR', 'USD', 'EUR'):
            for text, expected in [('1,234.567',123457), ('1.234,567',123457),
                                   ('1,234,567.891',123456789), ('1.234.567,891',123456789),
                                   ('1,234.564',123456), ('1.234,565',123457)]:
                with self.subTest(currency=currency,text=text):
                    self.assertEqual(currency_amount(text,currency),expected)
                    self.assertEqual(currency_amount('-'+text,currency,signed=True),-expected)
        for text in ('1,234','1.234'):
            self.assertEqual(currency_amount(text,'IDR'),123400)
        for text in ('1,234,567','1.234.567'):
            self.assertEqual(currency_amount(text,'IDR'),123456700)

    def test_malformed_mixed_grouping_rejected(self):
        for text in ('1,234.567,890','1.234,567.890','12,34.567','12.34,567','1,234.1234567'):
            with self.subTest(text=text),self.assertRaises(f.FinanceError):
                currency_amount(text,'IDR')

    def test_transaction_route_preserves_fractional_input(self):
        for text in ('1,234.567','1.234,567'):
            response=self.client.post(self.url+'/transactions',data=dict(branch_id=self.branch,
                direction='INCOME',amount=text,account_id=self.a,occurred_on='2026-09-10',description=text))
            self.assertEqual(response.status_code,303)
            row=db.query_one('SELECT * FROM finance_transactions WHERE description=?',(text,))
            self.assertEqual(row['amount_minor'],123457)

    def test_transfer_route_conserves_exact_parsed_amount(self):
        response=self.client.post(self.url+'/internal-transfers',data=dict(branch_id=self.branch,
            from_account_id=self.a,to_account_id=self.dest,amount='1.234,567',
            occurred_on='2026-09-10',idempotency_key='c'*32))
        self.assertEqual(response.status_code,303)
        transfer=db.query_one('SELECT * FROM finance_internal_transfers')
        self.assertIsNotNone(transfer)
        self.assertEqual(transfer['amount_minor'],123457)
        with branches.scope(self.b,self.branch,self.uid):
            rows={r['id']:r for r in f.get_account_balance_report(self.b,'2026-09-30',self.uid)}
            self.assertEqual(rows[self.a]['balance_minor'],-123457)
            self.assertEqual(rows[self.dest]['balance_minor'],20000+123457)

    def test_invoice_payment_route_posts_exact_minor_units(self):
        with branches.scope(self.b,self.branch,self.uid):
            invoice=f.create_finance_invoice(self.b,self.c,'2026-09-01','2026-09-30',
                [dict(description='Service',quantity=1,unit_price_minor=200000000)],actor_user_id=self.uid)
            f.issue_finance_invoice(self.b,invoice,actor_user_id=self.uid)
        response=self.client.post(self.url+f'/invoices/{invoice}/payments',data=dict(branch_id=self.branch,
            amount='1,234.567',paid_on='2026-09-10',account_id=self.a,
            category_id=self.cat,payment_key='d'*32))
        self.assertEqual(response.status_code,303)
        payment=db.query_one('SELECT * FROM finance_invoice_payments')
        self.assertIsNotNone(payment)
        self.assertEqual(payment['amount_minor'],123457)
        row=db.query_one('SELECT * FROM finance_transactions WHERE id=?',(payment['ledger_transaction_id'],))
        self.assertEqual(row['amount_minor'],123457)
