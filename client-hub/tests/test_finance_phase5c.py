"""Offline collection workspace regressions using disposable SQLite fixtures."""
import os
import unittest
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch
import test_finance_phase2a as prior
import db
import finance_service as f
import finance_collections as c
import finance_invoice_view as sharing

app=prior.app


class CollectionsTests(unittest.TestCase):
    setUp=prior.ReceivablesTests.setUp
    draft=prior.ReceivablesTests.draft
    issued=prior.ReceivablesTests.issued
    pay=prior.ReceivablesTests.pay

    def invoice(self,days=1,customer=None):
        due=date.today()-timedelta(days=days)
        i=self.draft(customer_id=customer or self.c,issue_date=(due-timedelta(days=10)).isoformat(),due_date=due.isoformat())
        f.issue_finance_invoice(self.b,i);return i

    def path(self,customer=None):return f'{self.url}/customers/{customer or self.c}/statement'
    def snapshot(self):return '\n'.join(db.get_connection().iterdump())
    def token(self):
        with app.test_request_context():return c.create_token(self.b,self.c,self.uid)
    def public(self,t):return app.test_client().get('/finance/statement-share/'+t)

    def test_all_aging_boundaries_and_counts(self):
        for days in (-7,0,1,30,31,60,61,90,91):self.invoice(days)
        data=c.position(self.b,self.uid)
        self.assertEqual([b['invoice_count'] for b in data['aging']['buckets']],[2,2,2,2,1])
        self.assertEqual([b['amount_minor'] for b in data['aging']['buckets']],[500,500,500,500,250])
        self.assertEqual(data['aging']['total_outstanding_minor'],2250)
        self.assertEqual(data['aging']['total_overdue_minor'],1750)
        self.assertEqual(data['aging']['open_invoice_count'],9)
        self.assertEqual(data['aging']['overdue_invoice_count'],7)

    def test_draft_void_paid_excluded(self):
        self.draft();i=self.invoice();f.void_finance_invoice(self.b,i)
        i=self.invoice();self.pay(i,250,paid_on=date.today().isoformat())
        self.assertEqual(c.position(self.b,self.uid)['rows'],[])

    def test_partial_payment_remaining_and_shared_phase3(self):
        i=self.invoice(20);self.pay(i,100,paid_on=date.today().isoformat())
        data=c.position(self.b,self.uid)
        self.assertEqual(data['rows'][0]['outstanding_minor'],150)
        self.assertEqual(data['rows'][0]['paid_minor'],100)
        self.assertEqual(data['aging']['buckets'],f.get_receivables_aging(self.b,date.today().isoformat())['buckets'])

    def test_order_overdue_balance_due_customer(self):
        a=self.invoice(5);b=self.invoice(40);self.pay(b,100,paid_on=date.today().isoformat())
        second=f.create_customer(self.b,'AAA');d=self.invoice(3,second)
        data=c.position(self.b,self.uid)
        self.assertEqual([r['id'] for r in c.queue(data)['rows']],[b,a,d])
        self.assertEqual(c.queue(data,'balance')['rows'][-1]['id'],b)
        self.assertEqual(c.queue(data,'due')['rows'][0]['id'],b)
        self.assertEqual(c.queue(data,'customer')['rows'][0]['id'],d)

    def test_due_soon_boundary(self):
        for days in (-8,-7,0,1):self.invoice(days)
        data=c.position(self.b,self.uid)
        self.assertEqual(c.queue(data,view='soon')['count'],2)
        self.assertEqual(c.queue(data,view='overdue')['count'],1)

    def test_tenant_isolation_context_and_routes(self):
        foreign=f.create_finance_invoice(self.other,self.oc,'2026-01-01','2026-01-02',[dict(description='secret',quantity=1,unit_price_minor=999)])
        f.issue_finance_invoice(self.other,foreign)
        self.assertEqual(c.position(self.b,self.uid)['rows'],[])
        with self.assertRaises(f.FinanceError):c.position(self.other,self.uid)
        self.assertEqual(self.client.get(self.url+f'/invoices/{foreign}/reminder').status_code,404)
        for suffix in ('','/print','/share'):
            method=self.client.post if suffix=='/share' else self.client.get
            self.assertEqual(method(self.path(self.oc)+suffix).status_code,404)
        self.assertIn(self.client.get(f'/business/{self.other}/finance/collections').status_code,(403,404))

    def test_statement_only_customer_and_amounts(self):
        i=self.invoice();self.pay(i,100,paid_on=date.today().isoformat())
        other=f.create_customer(self.b,'NOTTHISCUSTOMER');other_i=self.invoice(20,other)
        data=c.statement(self.b,self.c,self.uid)
        self.assertEqual(len(data['rows']),1)
        self.assertEqual(data['rows'][0]['total_minor'],250)
        self.assertEqual(data['rows'][0]['paid_minor'],100)
        self.assertEqual(data['aging']['total_outstanding_minor'],150)
        self.assertEqual(data['aging']['total_overdue_minor'],150)
        response=self.client.get(self.path())
        self.assertEqual(response.status_code,200)
        self.assertNotIn(f.get_finance_invoice(self.b,other_i)['invoice_number'].encode(),response.data)
        self.assertNotIn(b'NOTTHISCUSTOMER',response.data)

    def test_statement_invoice_navigation_is_authenticated_only(self):
        i=self.invoice()
        href=f'{self.url}/invoices/{i}'.encode()
        self.assertIn(href,self.client.get(self.path()).data)
        self.assertNotIn(href,self.client.get(self.path()+'/print').data)
        self.assertNotIn(href,self.public(self.token()).data)
        self.assertNotIn('id',c.statement(self.b,self.c)['rows'][0])

    def test_statement_empty_after_full_payment(self):
        i=self.invoice();self.pay(i,250,paid_on=date.today().isoformat())
        response=self.public(self.token())
        self.assertEqual(response.status_code,200)
        self.assertIn(b'Tidak ada piutang terbuka',response.data)
        self.assertIn(b'Rp0',response.data)

    def test_unauthenticated_access(self):
        client=app.test_client()
        for p in (self.url+'/collections',self.path(),self.path()+'/print',self.url+'/invoices/1/reminder'):
            self.assertIn(client.get(p).status_code,(302,401))
        self.assertIn(client.post(self.path()+'/share').status_code,(302,401))

    def test_finance_beta_gate(self):
        with patch.dict(os.environ,{'KILAS_FINANCE_BETA':'off'}):
            self.assertEqual(self.client.get(self.url+'/collections').status_code,404)
            self.assertEqual(self.client.post(self.path()+'/share').status_code,404)

    def test_queue_markup_navigation_and_filters(self):
        i=self.invoice()
        response=self.client.get(self.url+'/collections?sort=balance&view=overdue')
        self.assertEqual(response.status_code,200)
        for text in ('Statement Customer','Catat Pembayaran','Siapkan Reminder','Rp250','1 hari terlambat'):
            self.assertIn(text.encode(),response.data)
        markup=(Path(__file__).parents[1]/'templates/finance_collections.html').read_text()
        self.assertNotIn('<table',markup)
        self.assertIn(self.path().encode(),self.client.get(self.url+'/receivables').data)

    def test_invalid_filters(self):
        for query in ('sort=bad','view=bad','page=-1','page=x'):
            self.assertEqual(self.client.get(self.url+'/collections?'+query).status_code,400)

    def test_pagination_no_n_plus_one_and_no_silent_truncation(self):
        for _ in range(3):self.invoice()
        with patch.object(db,'query_all',wraps=db.query_all) as queries:
            data=c.position(self.b,self.uid)
        self.assertEqual(queries.call_count,1)
        with patch.object(c,'PAGE_SIZE',2):
            self.assertEqual(len(c.queue(data,page=1)['rows']),2)
            self.assertEqual(len(c.queue(data,page=2)['rows']),1)
        with patch.object(f,'MAX_REPORT_ROWS',2):
            self.assertEqual(self.client.get(self.url+'/collections').status_code,503)
            self.assertEqual(self.client.get(self.path()).status_code,503)

    def test_print_standalone_and_mobile_styles(self):
        self.invoice();response=self.client.get(self.path()+'/print')
        self.assertEqual(response.status_code,200)
        for text in (b'<nav',b'<form',b'csrf_token',b'Catat Pembayaran',b'Bagikan Statement'):self.assertNotIn(text,response.data)
        self.assertIn(b'invoice-toolbar',response.data)
        css=(Path(__file__).parents[1]/'static/finance_invoice.css').read_text()
        for text in ('size:A4','margin:14mm','max-width:600px','display:block','table-header-group','break-inside:avoid','display:none!important'):self.assertIn(text,css)

    def test_html_escaping(self):
        db.execute('UPDATE finance_customers SET name=? WHERE id=? AND business_id=?',('<script>alert(1)</script>',self.c,self.b))
        i=self.invoice();db.execute('UPDATE finance_invoices SET invoice_number=?,notes=? WHERE business_id=? AND id=?',('<img src=x onerror=alert(1)>','PRIVATE-NOTE',self.b,i))
        for response in (self.client.get(self.path()),self.client.get(self.path()+'/print'),self.public(self.token()),self.client.get(self.url+f'/invoices/{i}/reminder')):
            self.assertNotIn(b'<script>alert',response.data);self.assertNotIn(b'<img src=x',response.data)
            self.assertIn(b'&lt;script&gt;',response.data);self.assertNotIn(b'PRIVATE-NOTE',response.data)

    def test_reminder_both_tones_exact_remaining(self):
        i=self.invoice();self.pay(i,100,paid_on=date.today().isoformat())
        for tone in ('friendly','firm'):
            text=c.reminder(self.b,i,self.uid,tone)
            self.assertIn('Rp150',text);self.assertIn('Customer <test>',text)
            self.assertIn(f.get_finance_invoice(self.b,i)['invoice_number'],text)
            self.assertNotIn('Rp250',text)
            self.assertEqual(self.client.get(self.url+f'/invoices/{i}/reminder?tone={tone}').status_code,200)

    def test_reminder_unavailable_for_draft_void_paid_current(self):
        ids=[self.draft(),self.invoice(-1),self.invoice(0)]
        v=self.invoice();f.void_finance_invoice(self.b,v);ids.append(v)
        p=self.invoice();self.pay(p,250,paid_on=date.today().isoformat());ids.append(p)
        for i in ids:self.assertEqual(self.client.get(self.url+f'/invoices/{i}/reminder').status_code,404)
        self.assertEqual(self.client.get(self.url+f'/invoices/{self.invoice()}/reminder?tone=bad').status_code,404)

    def test_no_finance_writes_or_external_calls(self):
        i=self.invoice();before=self.snapshot()
        with patch.dict(os.environ,{'PUBLIC_APP_BASE_URL':'https://app.example.test'}):
            responses=[self.client.get(self.url+'/collections'),self.client.get(self.path()),
                       self.client.get(self.path()+'/print'),self.client.post(self.path()+'/share'),
                       self.public(self.token()),self.client.get(self.url+f'/invoices/{i}/reminder')]
        self.assertTrue(all(r.status_code==200 for r in responses))
        self.assertEqual(before,self.snapshot()) # fixture blocks all HTTP

    def test_share_valid_readonly_private_projection(self):
        self.invoice();response=self.public(self.token())
        self.assertEqual(response.status_code,200)
        for x in (b'csrf_token',b'<form',b'customer_id',b'business_id',b'Catat Pembayaran',b'PRIVATE CUSTOMER'):
            self.assertNotIn(x,response.data)
        self.assertNotIn(str(app.secret_key).encode(),response.data)
        for method in ('post','put','patch','delete'):
            self.assertEqual(getattr(app.test_client(),method)('/finance/statement-share/'+self.token()).status_code,405)

    def test_public_statement_excludes_other_customer_invoices(self):
        own=self.invoice()
        other=f.create_customer(self.b,'UNRELATED-CUSTOMER')
        foreign=self.invoice(30,other)
        r=self.public(self.token())
        self.assertEqual(r.status_code,200)
        self.assertIn(f.get_finance_invoice(self.b,own)['invoice_number'].encode(),r.data)
        self.assertNotIn(f.get_finance_invoice(self.b,foreign)['invoice_number'].encode(),r.data)
        self.assertNotIn(b'UNRELATED-CUSTOMER',r.data)

    def test_tampered_checked_before_query(self):
        token=self.token()
        with patch.object(f,'get_customer',side_effect=AssertionError('must verify first')):
            self.assertEqual(self.public('x'+token).status_code,404)
            self.assertEqual(self.public('bad').status_code,404)

    def test_expiry(self):
        token=self.token()
        with patch('itsdangerous.timed.TimestampSigner.get_timestamp',return_value=9999999999):
            self.assertEqual(self.public(token).status_code,404)

    def test_wrong_business_customer_and_invalid_payloads(self):
        for data in (dict(purpose='finance_customer_statement',business_id=self.b,customer_id=self.oc),
                     dict(purpose='other',business_id=self.b,customer_id=self.c),
                     dict(purpose='finance_customer_statement',business_id=True,customer_id=self.c),
                     dict(purpose='finance_customer_statement',business_id=self.b,customer_id=self.c,extra=1)):
            with app.test_request_context():token=sharing.signer().dumps(data)
            self.assertEqual(self.public(token).status_code,404)

    def test_invoice_and_statement_purposes_not_interchangeable(self):
        i=self.invoice()
        with app.test_request_context():it=sharing.create_token(self.b,i,self.uid)
        self.assertEqual(self.public(it).status_code,404)
        self.assertEqual(app.test_client().get('/finance/invoice-share/'+self.token()).status_code,404)

    def test_share_csrf_and_canonical_url(self):
        app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=True
        self.assertEqual(self.client.post(self.path()+'/share').status_code,400)
        self.client.get(self.path())
        with self.client.session_transaction() as session:csrf=session['_csrf_token']
        with patch.dict(os.environ,{'PUBLIC_APP_BASE_URL':'https://app.example.test'}):
            r=self.client.post(self.path()+'/share',data={'csrf_token':csrf})
            with app.test_request_context(base_url='https://evil.test'):
                self.assertEqual(sharing.base_url(),'https://app.example.test')
        self.assertEqual(r.status_code,200)
        self.assertIn(b'https://app.example.test/finance/statement-share/',r.data)
        self.assertNotIn(b'https://evil.test',r.data)

    def test_missing_configuration_fails_safe(self):
        with patch.dict(os.environ,{'PUBLIC_APP_BASE_URL':''}):self.assertEqual(self.client.post(self.path()+'/share').status_code,503)
        with app.test_request_context(),patch.dict(app.config,{'TESTING':False,'SECRET_KEY':'short'}):
            with self.assertRaises(ValueError):c.create_token(self.b,self.c,self.uid)

    def test_privacy_and_safe_error(self):
        r=self.public(self.token())
        self.assertIn('no-store',r.headers['Cache-Control']);self.assertEqual(r.headers['Referrer-Policy'],'no-referrer')
        self.assertEqual(r.headers['X-Frame-Options'],'DENY')
        token=self.token()
        with patch.object(c,'statement',side_effect=RuntimeError('PRIVATE-SECRET')):
            r=self.public(token)
        self.assertEqual(r.status_code,503);self.assertNotIn(b'PRIVATE-SECRET',r.data)

    def test_clipboard_fallback_no_sending(self):
        js=(Path(__file__).parents[1]/'static/finance_collections.js').read_text()
        self.assertIn('input.select()',js);self.assertIn('Belum dikirim',js)
        self.assertNotIn('fetch(',js);self.assertNotIn('innerHTML',js)

    def test_query_ids_do_not_override_signed_customer(self):
        r=app.test_client().get('/finance/statement-share/'+self.token()+f'?business_id={self.other}&customer_id={self.oc}')
        self.assertEqual(r.status_code,200);self.assertNotIn(b'PRIVATE CUSTOMER',r.data)


if __name__=='__main__':unittest.main()
