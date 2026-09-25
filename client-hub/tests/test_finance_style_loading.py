"""Prevent Finance's shell/content from painting before its render-blocking CSS."""
from html.parser import HTMLParser
import unittest
import test_finance_ui_integrity as fixture


class Styles(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.in_head=False; self.links=[]; self.body_styles=[]
        self.feed(html)
    def handle_starttag(self, tag, attrs):
        if tag=='head': self.in_head=True
        attrs=dict(attrs)
        if tag=='link' and attrs.get('rel')=='stylesheet':
            self.links.append((self.in_head,attrs))
        if tag=='style' and not self.in_head: self.body_styles.append(attrs)
    def handle_endtag(self, tag):
        if tag=='head': self.in_head=False


class FinanceStyleLoadingTests(unittest.TestCase):
    setUp=fixture.UnifiedFinanceTests.setUp
    page=fixture.UnifiedFinanceTests.page

    def test_every_customer_finance_view_blocks_paint_on_styles(self):
        invoice=fixture.f.create_finance_invoice(self.b,self.c,'2026-09-01','2026-09-30',
            [dict(description='Test',quantity=1,unit_price_minor=100)],actor_user_id=self.uid)
        transaction=fixture.f.create_transaction(self.b,'INCOME',100,self.a,self.cat,'2026-09-01',actor_user_id=self.uid)
        pages=[('',{}),('',{'view':'transactions'}),('',{'view':'transactions','direction':'INCOME'}),
            ('',{'view':'transactions','direction':'EXPENSE'}),('',{'view':'accounts'}),('',{'view':'accounts','account_id':self.a}),
            ('/operations',{}),('/budget',{}),('/receivables',{'section':'invoices'}),('/receivables',{'section':'customers'}),
            ('/invoices/new',{}),('/invoices/'+str(invoice),{}),('/invoices/'+str(invoice)+'/edit',{}),
            ('/invoices/settings',{}),('/payees',{}),('/reports',{}),('/assistant',{}),('/receipts/new',{}),
            ('/transactions/'+str(transaction)+'/edit',{})]
        for suffix,params in pages:
            with self.subTest(page=suffix,params=params):
                html,_=self.page(suffix,**params)
                parsed=Styles(html)
                self.assertTrue(parsed.links)
                self.assertTrue(all(in_head for in_head,_ in parsed.links),'Stylesheet discovered after body started')
                self.assertIn('kilas_ui.css',parsed.links[-1][1]['href'],'Package shell overrides must load after Finance styles')
                self.assertIn('finance_ui.css',parsed.links[-2][1]['href'])
                self.assertEqual(sum('finance_ui.css' in attrs['href'] for _,attrs in parsed.links),1)
                for _,attrs in parsed.links:
                    self.assertNotIn('onload',attrs)
                    self.assertNotEqual(attrs.get('media'),'print')
                self.assertLess(html.index('finance_ui.css'),html.index('class="finance-app-sidebar"'))

    def test_dashboard_chart_styles_remain_conditional(self):
        for params,expected in [({},True),({'view':'transactions'},False),({'view':'accounts'},False)]:
            html,_=self.page(**params)
            self.assertEqual('finance_dashboard.css' in html,expected)

    def test_non_finance_login_does_not_load_finance_styles(self):
        html=self.client.get('/login').text
        self.assertNotIn('finance_ui.css',html)
        self.assertNotIn('finance_home.css',html)
