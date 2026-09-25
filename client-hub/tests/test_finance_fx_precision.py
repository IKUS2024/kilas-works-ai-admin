import unittest
from decimal import Decimal, localcontext
import finance_fx as fx


class FxPrecisionTests(unittest.TestCase):
    def test_combined_total_rounds_once(self):
        rows=[{'currency':'USD','balance_minor':1},{'currency':'SGD','balance_minor':1}]
        # Each source cent converts to 0.25 IDR minor units; round only the sum.
        rates={'rates':{'IDR':'1','USD':'0.25','SGD':'0.25'}}
        self.assertEqual(fx.convert_total(rows,'IDR',rates),1)
        self.assertEqual(fx.to_idr(1,'USD',rates),0)
        self.assertEqual(fx.to_idr(1,'SGD',rates),0)

    def test_missing_rate_returns_none_not_partial_total(self):
        rows=[{'currency':'IDR','balance_minor':1000000},{'currency':'USD','balance_minor':10000}]
        self.assertIsNone(fx.convert_total(rows,'IDR',{'rates':{'IDR':'1'}}))

    def test_exact_large_money_format(self):
        self.assertEqual(fx.format_money(9223372036854775807,'USD'),
                         'US$92,233,720,368,547,758.07')
        self.assertEqual(fx.format_money(100000000,'IDR'),'Rp1.000.000,00')
        self.assertEqual(fx.format_money(100000025,'IDR'),'Rp1.000.000,25')

    def test_reference_pair_uses_decimal(self):
        rates={'rates':{'IDR':'1','USD':'17857.14','SGD':'13000'}}
        with localcontext() as context:
            context.prec = 60
            expected = Decimal('17857.14') / Decimal('13000')
        self.assertEqual(fx.reference_pair('USD','SGD',rates), expected)


if __name__=='__main__':
    unittest.main()
