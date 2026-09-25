"""Offline invoice document/share regressions. Only disposable fixture databases."""
from io import BytesIO
from pypdf import PdfReader
import os
import unittest
from pathlib import Path
from unittest.mock import patch
import test_finance_phase2a as prior
import db
import finance_service as f
import finance_invoice_view as view

app=prior.app


class InvoicePresentationTests(unittest.TestCase):
    setUp=prior.ReceivablesTests.setUp
    draft=prior.ReceivablesTests.draft
    issued=prior.ReceivablesTests.issued
    pay=prior.ReceivablesTests.pay

    def path(self,i):return self.url+'/invoices/'+str(i)
    def snapshot(self):return '\n'.join(db.get_connection().iterdump())
    def token(self,i):
        with app.test_request_context():return view.create_token(self.b,i,self.uid)
    def public(self,token):return app.test_client().get('/finance/invoice-share/'+token)
    def sign(self,data):
        with app.test_request_context():return view.signer().dumps(data)

    def test_draft_document_and_number_preserved(self):
        i=self.draft();response=self.client.get(self.path(i))
        self.assertEqual(response.status_code,200)
        self.assertIn(b'DRAFT',response.data);self.assertIn(f'KFIN-2026-{i:06d}'.encode(),response.data)
        self.assertNotIn(b'Share Invoice',response.data);self.assertIn(b'Terbitkan Invoice',response.data)
        self.assertIn(b'Unduh PDF',response.data)

    def test_cross_tenant_owner_access(self):
        other=f.create_finance_invoice(self.other,self.oc,'2026-09-01','2026-09-30',[dict(description='private',quantity=1,unit_price_minor=900)])
        for suffix in ('','/print'):
            self.assertEqual(self.client.get(self.path(other)+suffix).status_code,404)
        self.assertEqual(self.client.post(self.path(other)+'/share').status_code,404)

    def test_unauthenticated_internal_view_denied(self):
        i=self.issued();client=app.test_client()
        self.assertIn(client.get(self.path(i)).status_code,(302,401))
        self.assertIn(client.get(self.path(i)+'/print').status_code,(302,401))
        self.assertIn(client.post(self.path(i)+'/share').status_code,(302,401))

    def test_published_totals_partial_and_balance(self):
        i=self.issued();self.pay(i,100)
        with app.test_request_context():doc=view.document(self.b,i,self.uid)
        self.assertEqual(doc['totals']['total_minor'],250);self.assertEqual(doc['totals']['paid_minor'],100)
        self.assertEqual(doc['totals']['outstanding_minor'],150)
        response=self.public(self.token(i))
        for text in ('DIBAYAR SEBAGIAN','Rp2,50','Rp1,00','Rp1,50'):self.assertIn(text.encode(),response.data)

    def test_paid_and_overdue_status(self):
        i=self.issued()
        response=self.public(self.token(i));self.assertIn(b'LEWAT JATUH TEMPO',response.data)
        self.pay(i,250)
        response=self.public(self.token(i));self.assertIn(b'LUNAS',response.data)
        self.assertNotIn(b'LEWAT JATUH TEMPO',response.data)
        self.assertIn(b'Rp0',response.data)

    def test_open_nonoverdue(self):
        i=self.draft(due_date='2099-09-20');f.issue_finance_invoice(self.b,i)
        response=self.public(self.token(i))
        self.assertIn(b'TERBIT',response.data);self.assertNotIn(b'LEWAT JATUH TEMPO',response.data)

    def test_share_generation_readonly_valid_url(self):
        i=self.issued();before=self.snapshot()
        with patch.dict(os.environ,{'PUBLIC_APP_BASE_URL':'https://app.example.test'}):
            response=self.client.post(self.path(i)+'/share')
        self.assertEqual(response.status_code,200);self.assertEqual(before,self.snapshot())
        self.assertIn(b'https://app.example.test/finance/invoice-share/',response.data)
        self.assertIn(b'Copy Link',response.data);self.assertIn(b'Buka Tampilan Pelanggan',response.data)
        self.assertIn(b'no-store',response.headers['Cache-Control'].encode())

    def test_draft_and_void_cannot_generate_share(self):
        i=self.draft()
        with self.assertRaises(ValueError):self.token(i)
        self.assertEqual(self.client.post(self.path(i)+'/share').status_code,404)
        f.issue_finance_invoice(self.b,i);token=self.token(i);f.void_finance_invoice(self.b,i)
        self.assertEqual(self.public(token).status_code,404)
        with self.assertRaises(ValueError):self.token(i)

    def test_signed_token_for_draft_still_rejected(self):
        i=self.draft();token=self.sign(dict(purpose='finance_invoice_view',business_id=self.b,invoice_id=i))
        self.assertEqual(self.public(token).status_code,404)

    def test_valid_public_token_only_one_invoice(self):
        i=self.issued();other=self.draft(notes='UNRELATED-FINANCE-PRIVATE')
        before=self.snapshot();response=self.public(self.token(i))
        self.assertEqual(response.status_code,200);self.assertEqual(before,self.snapshot())
        self.assertNotIn(b'UNRELATED-FINANCE-PRIVATE',response.data)
        self.assertNotIn(f'KFIN-2026-{other:06d}'.encode(),response.data)

    def test_tampered_signature_before_any_invoice_query(self):
        token=self.token(self.issued())
        with patch.object(f,'get_finance_invoice',side_effect=AssertionError('Query before signature verification')):
            self.assertEqual(self.public('x'+token).status_code,404)
            self.assertEqual(self.public('invalid').status_code,404)

    def test_signed_mismatch_invalid_purpose_and_types(self):
        i=self.issued()
        for data in (dict(purpose='finance_invoice_view',business_id=self.other,invoice_id=i),
                     dict(purpose='other',business_id=self.b,invoice_id=i),
                     dict(purpose='finance_invoice_view',business_id=True,invoice_id=i),
                     dict(purpose='finance_invoice_view',business_id=self.b,invoice_id=i,extra=True)):
            self.assertEqual(self.public(self.sign(data)).status_code,404)

    def test_other_purpose_signature_rejected(self):
        from itsdangerous import URLSafeTimedSerializer
        token=URLSafeTimedSerializer(app.secret_key,salt='kilas-finance-operator-v1').dumps(dict(business_id=self.b,invoice_id=self.issued()))
        self.assertEqual(self.public(token).status_code,404)

    def test_expired_token(self):
        i=self.issued()
        with app.test_request_context(),patch('itsdangerous.timed.TimestampSigner.get_timestamp',return_value=100):token=view.create_token(self.b,i,self.uid)
        self.assertEqual(self.public(token).status_code,404)

    def test_public_url_ids_cannot_override_signed_target(self):
        token=self.token(self.issued());before=self.snapshot()
        response=app.test_client().get('/finance/invoice-share/'+token+f'?business_id={self.other}&invoice_id=999')
        self.assertEqual(response.status_code,200);self.assertNotIn(b'PRIVATE CUSTOMER',response.data)
        self.assertEqual(before,self.snapshot())

    def test_public_readonly_methods_and_no_controls(self):
        token=self.token(self.issued());client=app.test_client();before=self.snapshot()
        response=client.get('/finance/invoice-share/'+token)
        for text in (b'<form',b'Catat Pembayaran',b'Terbitkan Invoice',b'Batalkan Invoice',b'Dashboard',b'Logout',b'payment_key',b'created_by_user_id',b'csrf_token',b'/operator',b'Riwayat pembayaran'):
            self.assertNotIn(text,response.data)
        for method in ('post','put','delete','patch'):self.assertEqual(getattr(client,method)('/finance/invoice-share/'+token).status_code,405)
        self.assertEqual(before,self.snapshot())

    def test_customer_notes_payment_notes_and_account_private(self):
        i=self.issued();self.pay(i,100,note='INTERNAL-PAYMENT-NOTE')
        db.execute('UPDATE finance_customers SET notes=? WHERE id=?',('INTERNAL-CUSTOMER-NOTE',self.c))
        db.execute('UPDATE finance_accounts SET name=? WHERE id=?',('PRIVATE-BANK-ACCOUNT',self.a))
        response=self.public(self.token(i))
        for value in ('INTERNAL-PAYMENT-NOTE','INTERNAL-CUSTOMER-NOTE','PRIVATE-BANK-ACCOUNT'):self.assertNotIn(value.encode(),response.data)

    def test_text_escaped_in_all_views(self):
        dangerous='<script>alert("x")</script>'
        db.execute('UPDATE finance_customers SET name=? WHERE id=?',(dangerous,self.c))
        i=self.draft(notes=dangerous,items=[dict(description=dangerous,quantity=1,unit_price_minor=10)]);f.issue_finance_invoice(self.b,i)
        for response in (self.client.get(self.path(i)),self.client.get(self.path(i)+'/print'),self.public(self.token(i))):
            if response.mimetype=='application/pdf':
                text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(response.data)).pages)
                self.assertIn(dangerous,text)  # Literal text, never interpreted as markup.
            else:
                self.assertNotIn(dangerous.encode(),response.data);self.assertIn(b'&lt;script&gt;',response.data)

    def test_print_page_no_navigation_or_internal_controls(self):
        i=self.issued();response=self.client.get(self.path(i)+'/print')
        for text in (b'<nav',b'Client Hub',b'<form',b'Catat Pembayaran'):self.assertNotIn(text,response.data)
        self.assertEqual(response.mimetype,'application/pdf')
        self.assertTrue(response.data.startswith(b'%PDF-'))
        text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(response.data)).pages)
        self.assertIn('Rp2,50',text)
        css=(Path(__file__).resolve().parents[1]/'static/finance_invoice.css').read_text()
        self.assertIn('@page{size:A4;margin:14mm}',css)
        self.assertIn('table-header-group',css);self.assertIn('.invoice-toolbar,.invoice-controls{display:none!important}',css)

    def test_mobile_layout_and_clipboard_fallback(self):
        root=Path(__file__).resolve().parents[1]
        css=(root/'static/finance_invoice.css').read_text();js=(root/'static/finance_invoice.js').read_text()
        self.assertIn('max-width:600px',css);self.assertIn('overflow-wrap:anywhere',css)
        self.assertIn('input.select()',js);self.assertNotIn('innerHTML',js);self.assertNotIn('fetch(',js)

    def test_configuration_fail_safe_and_no_host_header_fallback(self):
        i=self.issued()
        for base in ('','http://app.example.test','https://user:password@example.test','https://app.example.test/?x=1'):
            with patch.dict(os.environ,{'PUBLIC_APP_BASE_URL':base}):
                self.assertEqual(self.client.post(self.path(i)+'/share').status_code,503)
        with app.test_request_context(),patch.dict(app.config,{'TESTING':False,'SECRET_KEY':'short'}):
            with self.assertRaises(ValueError):view.create_token(self.b,i,self.uid)

    def test_csrf_share_and_secret_not_rendered(self):
        i=self.issued();app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=True
        self.assertEqual(self.client.post(self.path(i)+'/share').status_code,400)
        self.client.get(self.path(i))
        with self.client.session_transaction() as session:csrf=session['_csrf_token']
        with patch.dict(os.environ,{'PUBLIC_APP_BASE_URL':'https://app.example.test'}):
            response=self.client.post(self.path(i)+'/share',data={'csrf_token':csrf})
        self.assertEqual(response.status_code,200)
        self.assertNotIn(str(app.secret_key).encode(),response.data)

    def test_public_headers_and_uniform_unavailable(self):
        token=self.token(self.issued());response=self.public(token)
        self.assertEqual(response.headers['Referrer-Policy'],'no-referrer');self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertIn('noindex',response.headers['X-Robots-Tag'])
        unknown=self.sign(dict(purpose='finance_invoice_view',business_id=self.b,invoice_id=99999))
        self.assertEqual(self.public('bad').data,self.public(unknown).data)

    def test_no_external_calls_and_no_ai_on_render_share(self):
        i=self.issued();before=self.snapshot()
        # Fixture forbids all requests.Session HTTP. No provider or external sender invoked.
        with patch.dict(os.environ,{'PUBLIC_APP_BASE_URL':'https://app.example.test'}):
            self.assertEqual(self.client.post(self.path(i)+'/share').status_code,200)
        self.assertEqual(self.public(self.token(i)).status_code,200)
        self.assertEqual(self.client.get(self.path(i)+'/print').status_code,200)
        self.assertEqual(before,self.snapshot())


if __name__=='__main__':unittest.main()
