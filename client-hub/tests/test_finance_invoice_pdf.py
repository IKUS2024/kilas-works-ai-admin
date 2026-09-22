"""Invoice PDF rendering stays real PDF and independent from database writes."""
import unittest
import finance_invoice_pdf


class InvoicePdfTests(unittest.TestCase):
    def test_build_paid_and_open_invoice_pdf(self):
        base = dict(
            issuer='Kilas Works',
            customer=dict(name='Customer Test', email='test@example.com', phone='08123456789'),
            items=[
                dict(description='Jasa foto', quantity=1, unit_price_minor=200000000),
                dict(description='Editing', quantity=2, unit_price_minor=25000000),
            ],
        )
        for status, paid, outstanding in (
            ('ISSUED', 0, 250000000),
            ('PARTIALLY_PAID', 100000000, 150000000),
            ('PAID', 250000000, 0),
        ):
            doc=dict(
                base,
                invoice=dict(
                    invoice_number='KFIN-2026-000001',
                    status=status,
                    issue_date='2026-09-22',
                    due_date='2026-09-30',
                    currency='IDR',
                    notes='Terima kasih.',
                ),
                totals=dict(
                    total_minor=250000000,
                    paid_minor=paid,
                    outstanding_minor=outstanding,
                    overdue=False,
                ),
            )
            payload=finance_invoice_pdf.build(doc)
            self.assertTrue(payload.startswith(b'%PDF-'))
            self.assertGreater(len(payload),1000)


if __name__=='__main__':
    unittest.main()
