"""Dedicated Finance directions stay fixed while existing ledger filters survive navigation."""
import re
import unittest
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit
from flask import template_rendered
import test_finance_approved_revisions as prior
import finance_service as f
import finance_branches as branches


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__();self.items=[];self.feed(html)
    def handle_starttag(self, tag, attrs):
        self.items.append((tag, dict(attrs)))


def section(html, pattern):
    match=re.search(pattern, html, re.S)
    assert match, pattern
    return match.group()


def hidden_values(html):
    return {a['name']:a.get('value','') for tag,a in Elements(html).items
            if tag=='input' and a.get('type')=='hidden' and a.get('name')}


class DirectionFilterTests(unittest.TestCase):
    setUp=prior.ApprovedFinanceTests.setUp

    def page(self, query):
        contexts=[]
        def capture(sender, template, context, **extra):contexts.append(context)
        with template_rendered.connected_to(capture,prior.app):response=self.client.get(self.url,query_string=query)
        self.assertEqual(response.status_code,200)
        return response.text,contexts[-1]

    def cases(self):
        for branch,account in ((self.branch,self.a),(self.personal,self.pa)):
            for direction in ('INCOME','EXPENSE'):
                yield branch,account,direction

    def seed(self):
        categories={}
        for branch,account,direction in self.cases():
            with branches.scope(self.b,branch,self.uid):
                category=f.list_categories(self.b,direction,actor_user_id=self.uid)[0]['id']
                categories[(branch,direction)]=category
                for _ in range(12):
                    f.create_transaction(self.b,direction,100,account,category,'2026-09-10',
                                         description='Filter target',actor_user_id=self.uid)
                f.create_transaction(self.b,direction,900,account,category,'2026-09-10',
                                     description='Excluded search',actor_user_id=self.uid)
        return categories

    def query(self, branch, account, direction, category=None):
        result=dict(branch_id=str(branch),view='transactions',direction=direction,period_mode='month',
                    month='2026-09',account_id=str(account),search='Filter target',display_currency='IDR')
        if category:result['category_id']=str(category)
        return result

    def assert_query(self, url, expected):
        values=parse_qs(urlsplit(url).query)
        for key,value in expected.items():self.assertEqual(values.get(key),[str(value)],(key,url))

    def test_dedicated_lists_hide_type_and_keep_hidden_direction_in_both_modes(self):
        for branch,account,direction in self.cases():
            with self.subTest(branch=branch,direction=direction):
                html,_=self.page(self.query(branch,account,direction))
                form=section(html,r'<form class="finance-transaction-search".*?</form>')
                direction_controls=[(tag,a) for tag,a in Elements(form).items if a.get('name')=='direction']
                self.assertEqual(direction_controls,[('input',{'type':'hidden','name':'direction','value':direction})])
                self.assertNotIn('Jenis',form)
                add=section(html,r'<form id="add-transaction".*?</form>')
                self.assertFalse(any(tag=='select' and a.get('name')=='direction' for tag,a in Elements(add).items))

    def test_generic_all_transactions_keeps_type_choice_in_both_modes(self):
        for branch in (self.branch,self.personal):
            html,_=self.page(dict(branch_id=branch,view='transactions',month='2026-09'))
            form=section(html,r'<form class="finance-transaction-search".*?</form>')
            self.assertEqual(len([a for tag,a in Elements(form).items if tag=='select' and a.get('name')=='direction']),1)

    def test_filter_submission_and_pagination_keep_effective_direction(self):
        self.seed()
        for branch,account,direction in self.cases():
            with self.subTest(branch=branch,direction=direction):
                query=self.query(branch,account,direction)
                html,_=self.page(query)
                form=section(html,r'<form class="finance-transaction-search".*?</form>')
                submitted=dict(hidden_values(form),search=query['search'],account_id=query['account_id'])
                html,ctx=self.page(submitted)
                self.assertEqual(ctx['transaction_total'],12)
                self.assertTrue(all(r['direction']==direction and r['account_id']==account for r in ctx['transactions']))
                pagination=section(html,r'<nav class="finance-pagination".*?</nav>')
                for tag,a in Elements(pagination).items:
                    if tag=='a':self.assert_query(a['href'],query)
                next_url=next(a['href'] for tag,a in Elements(pagination).items if tag=='a' and a.get('aria-label')=='Halaman berikutnya')
                _,second=self.page({k:v[0] for k,v in parse_qs(urlsplit(next_url).query).items()})
                self.assertEqual(second['transaction_page'],2);self.assertEqual(len(second['transactions']),2)
                self.assertTrue(all(r['direction']==direction for r in second['transactions']))

    def test_month_links_preserve_account_search_category_and_direction(self):
        categories=self.seed()
        for branch,account,direction in self.cases():
            query=self.query(branch,account,direction,categories[(branch,direction)])
            html,_=self.page(query)
            nav=section(html,r'<nav class="finance-month-nav finance-ledger-month".*?</nav>')
            links=[a['href'] for tag,a in Elements(nav).items if tag=='a']
            self.assertTrue(links)
            for link in links:
                expected={k:v for k,v in query.items() if k!='month'}
                self.assert_query(link,expected)
            self.assert_query(links[0],dict(month='2026-08',page='1'))

    def test_period_dialog_month_preserves_ledger_context_through_redirect(self):
        categories=self.seed()
        for branch,account,direction in self.cases():
            query=self.query(branch,account,direction,categories[(branch,direction)])
            html,_=self.page(query)
            form=section(html,r'<dialog id="period-dialog".*?</form>')
            submitted=dict(hidden_values(form),period_mode='month',period_month='08',period_year='2026')
            response=self.client.get(self.url,query_string=submitted)
            self.assertEqual(response.status_code,302)
            self.assert_query(response.location,dict(query,month='2026-08'))

    def test_period_dialog_range_preserves_ledger_context_through_redirect(self):
        categories=self.seed()
        for branch,account,direction in self.cases():
            query=self.query(branch,account,direction,categories[(branch,direction)])
            html,_=self.page(query)
            form=section(html,r'<dialog id="period-dialog".*?</form>')
            submitted=dict(hidden_values(form),period_mode='range',range_start_month='08',range_start_year='2026',
                           range_end_month='09',range_end_year='2026')
            response=self.client.get(self.url,query_string=submitted)
            self.assertEqual(response.status_code,302)
            expected={k:v for k,v in query.items() if k not in ('month','period_mode')}
            self.assert_query(response.location,dict(expected,period_mode='range',range_start='2026-08',range_end='2026-09'))
