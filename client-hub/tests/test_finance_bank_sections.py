"""Synthetic multi-page bank export. No real customer/statement data is used here."""
import io
import json
import unittest
from unittest.mock import patch
from reportlab.pdfgen import canvas
import test_finance_phase6b as prior
import finance_bank_extract as x
import finance_bank_statement as s
import finance_bank_service as bank
import finance_assistant_flow as flow
import finance_service as f
import finance_ai_safety as safety
import db

IDR='''REKENING CONTOH
PERIODE : APRIL 2025
MATA UANG : IDR
TANGGAL KETERANGAN CBG MUTASI SALDO
01/04 SALDO AWAL 10,000.00
01/04 BIAYA ADM 0123 100.00 DB 9,900.00
20/04 DB OTOMATIS CARD PAYMENT
SYNTHETIC-REFERENCE-A
0123 200.00 DB 9,700.00
30/04 DB DEBIT DOMESTIK
TEST MERCHANT
300.00 DB 9,400.00
30/04 TRSF E-BANKING DB TEST-PAYMENT
TEST TELECOM
400.00 DB
30/04 TRSF E-BANKING DB TEST-FX-PAIR
USD0.50
SETORAN AWAL POKET
VALAS
SYNTHETIC OWNER
800.00 DB
30/04 KR OTOMATIS TEST-CREDIT-A
TEST SENDER A
AutoCr-PL
2,000.00
30/04 KR OTOMATIS TEST-CREDIT-B
TEST SENDER B
AutoCr-PL
3,000.00
30/04 KR OTOMATIS TEST-CREDIT-C
TEST SENDER C
remittance tran
AutoCr-PL
4,000.00
30/04 BUNGA 12.34
30/04 PAJAK BUNGA 2.34 DB 17,210.00
SALDO AWAL : 10,000.00
MUTASI CR : 9,012.34 4
MUTASI DB : 1,802.34 6
SALDO AKHIR : 17,210.00
Bersambung ke halaman berikut'''
USD='''REKENING CONTOH
PERIODE : APRIL 2025
MATA UANG : USD
FASILITAS : POKET VALAS
TANGGAL KETERANGAN CBG MUTASI SALDO
30/04 SALDO AWAL 0.00
30/04 TRSF E-BANKING CR TEST-FX-PAIR
IDR800.00
SETORAN AWAL POKET
VALAS
SYNTHETIC OWNER
0.50 0.50
30/04 KR OTOMATIS TEST-CREDIT-D
TEST SENDER D
USD8.25
/REFERENCE/TEST
8.25 8.75
SALDO AWAL : 0.00
MUTASI CR : 8.75 2
MUTASI DB : 0.00 0
SALDO AKHIR : 8.75'''


def statement_pdf(pages=(IDR,USD)):
    stream=io.BytesIO();doc=canvas.Canvas(stream)
    for page in pages:
        text=doc.beginText(30,810);text.setFont('Helvetica',9);text.setLeading(13)
        for line in page.splitlines():text.textLine(line)
        doc.drawText(text);doc.showPage()
    doc.save();return stream.getvalue()


class SectionTests(unittest.TestCase):
    setUp=prior.BankTests.setUp
    fields=prior.BankTests.fields

    def source(self):return x.validate_sources([('synthetic.pdf',statement_pdf())])
    def extract(self,currency='IDR'):
        source=self.source();rows,fallback=x.extract(source,self.uid,self.b,currency)
        self.assertFalse(fallback);return source,rows
    def usd_account(self):return f.create_account(self.b,'Synthetic USD',currency='USD',actor_user_id=self.uid)

    def test_real_pdf_pages_counts_summary_exclusion_multiline_and_year(self):
        source,rows=self.extract()
        self.assertEqual(source['sources'][0]['text'].count('\f'),1)
        self.assertEqual(len(rows),10);self.assertEqual(source['currencies'],['IDR','USD'])
        self.assertEqual(sum(r['direction']=='EXPENSE' for r in rows),6)
        self.assertTrue(all(r['transaction_date'].startswith('2025-04-') for r in rows))
        self.assertIn('SETORAN AWAL POKET VALAS SYNTHETIC OWNER',rows[4]['description'])
        self.assertFalse(any('SALDO' in r['description'] or 'MUTASI' in r['description'] for r in rows))
        self.http.assert_not_called()
        _,usd=self.extract('USD');self.assertEqual([r['amount_minor'] for r in usd],[50,825])

    def test_decimal_precision_preserved_and_held(self):
        source,rows=self.extract()
        self.assertEqual(source['row_reviews']['9']['original_amount'],'12.34')
        self.assertEqual(source['row_reviews']['10']['original_amount'],'2.34')
        self.assertEqual(rows[8]['amount_minor'],12)

    def test_summaries_reconcile_or_fall_back_without_partial_acceptance(self):
        for text in (IDR.replace('9,012.34 4','9,012.34 5'),IDR.replace('17,210.00','17,211.00'),
                     IDR.replace('APRIL 2025','APRIL'),IDR.replace('20/04','31/04'),
                     IDR.replace('20/04','20/05'),IDR.replace('200.00 DB','not-an-amount')):
            self.assertIsNone(s.parse(text))

    def test_currency_mismatch_never_invents_rows(self):
        with self.assertRaisesRegex(x.BankError,'currency_mismatch'):self.extract('EUR')
        self.http.assert_not_called()

    def test_fx_and_precision_holds_survive_edit_and_block_ledger_writes(self):
        ident,_=bank.analyze(self.b,self.a,[('synthetic.pdf',statement_pdf())],self.uid)
        rows=bank.get_rows(self.b,ident,self.uid)
        held=[r for r in rows if r['held_for_review']];self.assertEqual(len(held),3)
        self.assertTrue(held[0]['extraction_review']['fx'])
        original=held[0]
        bank.edit_row(self.b,ident,original['id'],0,dict(transaction_date=original['occurred_on'],
            description='Edited description',direction=original['direction'],amount_minor=original['amount_minor'],reference=None),self.uid)
        bank.open_import(self.b,ident,1,self.uid)
        for row in held:
            with self.assertRaisesRegex(f.FinanceError,'bank_extraction_review_required'):
                bank.decide(self.b,ident,row['id'],'post',self.uid,fields=self.fields())
        self.assertEqual(f.list_transactions(self.b),[])
        self.assertEqual(bank.get_import(self.b,ident,self.uid)['extraction']['currencies'],['IDR','USD'])

    def test_separate_accounts_same_file_and_idempotent_confirmation(self):
        usd=self.usd_account();files=[('synthetic.pdf',statement_pdf())]
        a,_=bank.analyze(self.b,self.a,files,self.uid);b,_=bank.analyze(self.b,usd,files,self.uid)
        self.assertNotEqual(a,b)
        self.assertEqual(len(bank.get_rows(self.b,a,self.uid)),10)
        self.assertEqual(len(bank.get_rows(self.b,b,self.uid)),2)
        self.assertEqual(bank.analyze(self.b,self.a,files,self.uid),(a,False))
        with prior.app.test_request_context('/'):
            result=flow._bank_confirm(self.b,self.uid,dict(import_id=a,revision=0))
            self.assertEqual(result['held_count'],3)
            self.assertEqual(result['posted_count'],7)
            second=flow._bank_confirm(self.b,self.uid,dict(import_id=a,revision=0))
            self.assertEqual(second['posted_count'],0)
        self.assertEqual(len(f.list_transactions(self.b)),7)
        self.assertTrue(all(r['currency']=='IDR' for r in f.list_transactions(self.b)))

    def test_text_fallback_sends_only_selected_section_and_visual_keeps_currency(self):
        source=self.source()
        source['sources'][0]['text']=source['sources'][0]['text'].replace('9,012.34 4','9,012.34 5')
        response=dict(rows=[dict(self.row,currency='IDR',amount='100000')],readable=True)
        self.response.json.return_value['content'][0]['text']=json.dumps(response)
        rows,_=x.extract(source,self.uid,self.b)
        text=self.http.call_args.kwargs['json']['messages'][0]['content'][0]['text']
        self.assertNotIn('TEST-CREDIT-D',text);self.assertIn('TEST-CREDIT-C',text)
        self.assertEqual(rows,[self.row])

    def test_visual_mixed_rows_filtered_and_unknown_currency_rejected(self):
        from test_finance_phase6a import pdf_bytes
        source=x.validate_sources([('scan.pdf',pdf_bytes())])
        result=dict(readable=True,rows=[dict(self.row,currency='IDR',amount='100000'),
            dict(self.row,currency='USD',amount='12.34',amount_minor=1234)])
        self.response.json.return_value['content'][0]['text']=json.dumps(result)
        rows,_=x.extract(source,self.uid,self.b);self.assertEqual(rows,[self.row])
        self.assertEqual(source['currencies'],['IDR','USD'])
        result['rows'][0].pop('currency')
        self.response.json.return_value['content'][0]['text']=json.dumps(result)
        with self.assertRaisesRegex(x.BankError,'invalid_result'):x.extract(source,self.uid,self.b)

    def test_provider_failure_types_and_no_empty_import(self):
        for status,reason in ((429,'rate_limited'),(503,'upstream_failure')):
            safety._RATE.clear();self.response.status_code=status
            with self.assertRaisesRegex(x.BankError,reason):
                bank.analyze(self.b,self.a,[('image.png',self.raw)],self.uid)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_bank_imports')['n'],0)

    def test_local_rate_limit_is_retryable_not_unreadable(self):
        with patch.object(safety,'allow_attempt',return_value=False),self.assertRaisesRegex(x.BankError,'rate_limited'):
            x.extract(x.validate_sources([('image.png',self.raw)]),self.uid,self.b)
        self.http.assert_not_called()

    def test_deterministic_text_still_works_without_provider_quota(self):
        with patch.object(safety,'allow_attempt',return_value=False):
            self.assertEqual(len(self.extract()[1]),10)

    def test_shared_reference_cross_currency_legs_are_held(self):
        source=dict(kind='IMAGES',sources=[])
        rows=[dict(self.row,currency='IDR',amount='800',reference='PAIR-SYNTHETIC'),
              dict(self.row,currency='USD',amount='0.50',direction='INCOME',reference='PAIR-SYNTHETIC')]
        for currency in ('IDR','USD'):
            result=x.select_rows(source,rows,currency)
            self.assertEqual(len(result),1);self.assertTrue(source['row_reviews']['1']['fx'])

    def test_visual_retry_failure_remains_typed_and_private(self):
        from test_finance_phase6a import pdf_bytes
        import base64
        source=x.validate_sources([('synthetic.pdf',pdf_bytes(text=True))])
        self.response.json.return_value['content'][0]['text']='malformed PRIVATE MODEL OUTPUT'
        with self.assertLogs('kilas.finance_ai',level='INFO') as logs:
            with self.assertRaisesRegex(x.BankError,'invalid_result'):x.extract(source,self.uid,self.b)
        self.assertEqual(self.http.call_count,2)
        final=self.http.call_args.kwargs['json']['messages'][0]['content'][0]
        self.assertEqual(base64.b64decode(final['source']['data']),source['sources'][0]['raw'])
        self.assertNotIn('PRIVATE',str(logs.output))

    def test_network_timeout_and_provider_failure_do_not_trigger_visual_retry(self):
        from test_finance_phase6a import pdf_bytes
        for error,reason in ((x.requests.Timeout('PRIVATE'),'timeout'),
                             (x.requests.ConnectionError('PRIVATE'),'network_failure')):
            safety._RATE.clear();self.http.reset_mock();self.http.side_effect=error
            with self.assertRaisesRegex(x.BankError,reason):
                x.extract(x.validate_sources([('synthetic.pdf',pdf_bytes(text=True))]),self.uid,self.b)
            self.assertEqual(self.http.call_count,1)

    def test_fx_detection_does_not_flag_plain_foreign_income(self):
        rows=s.parse(IDR+'\f'+USD)
        self.assertEqual(sum(s.possible_fx(r['description'],r['currency']) for r in rows),2)

class DocumentFlowTests(unittest.TestCase):
    from test_finance_assistant_inline import InlineTests as _fixture
    setUp=_fixture.setUp
    document=_fixture.document
    model=_fixture.model
    confirm=_fixture.confirm

    def test_multi_currency_account_choice_and_signed_context_override(self):
        usd=f.create_account(self.b,'USD pocket synthetic',currency='USD',actor_user_id=self.uid)
        another=f.create_account(self.b,'Another IDR',actor_user_id=self.uid)
        raw=statement_pdf()
        result=self.document('BANK_STATEMENT',raw,'synthetic.pdf')
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json['kind'],'document_account')
        self.assertIn('IDR, USD',result.json['message'])
        choices=result.json['fields'][0]['options']
        self.assertEqual({c['value'] for c in choices},{str(self.a),str(usd),str(another)})
        import hashlib
        with prior.app.test_request_context('/'):
            context=flow.seal(self.b,self.uid,'document',dict(currency='IDR',hashes=[hashlib.sha256(raw).hexdigest()]))
        result=self.document('BANK_STATEMENT',raw,'synthetic.pdf',account_id=str(usd),document_context=context)
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json['count'],2)
        self.assertIn('Bagian IDR',result.json['message'])
        result=self.confirm(result.json['token']);self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json['held_count'],1);self.assertEqual(result.json['posted_count'],1)
        ledger=f.list_transactions(self.b)
        self.assertEqual([r['currency'] for r in ledger],['USD'])
        self.assertEqual(ledger[0]['amount_minor'],825)

    def test_idr_account_warning_and_confirmation_replay(self):
        raw=statement_pdf()
        result=self.document('BANK_STATEMENT',raw,'synthetic.pdf',account_id=str(self.a))
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json['count'],10);self.assertIn('Bagian USD',result.json['message'])
        self.assertIn('ditahan',result.json['message']);self.assertEqual(f.list_transactions(self.b),[])
        for _ in range(2):
            response=self.confirm(result.json['token']);self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(f.list_transactions(self.b)),7)
        retry=self.document('BANK_STATEMENT',raw,'synthetic.pdf',account_id=str(self.a))
        self.confirm(retry.json['token']);self.assertEqual(len(f.list_transactions(self.b)),7)

    def test_provider_failure_http_messages_and_retry(self):
        for status,expected in ((429,429),(503,503)):
            safety._RATE.clear();self.response.status_code=status
            response=self.document('BANK_STATEMENT',account_id=str(self.a))
            self.assertEqual(response.status_code,expected,response.text)
            self.assertNotIn('PDF asli',response.json['error']);self.assertNotIn('rusak',response.json['error'])
        self.response.status_code=200;self.model(self.result)
        response=self.document('BANK_STATEMENT',account_id=str(self.a))
        self.assertEqual(response.status_code,200,response.text);self.assertTrue(response.json['ready'])
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_bank_imports')['n'],1)

    def test_classification_rate_limit_is_not_unknown_document(self):
        self.response.status_code=429
        response=self.client.post(self.path+'/recognize',data={'sources':(io.BytesIO(self.raw),'synthetic.png'),'text':''})
        self.assertEqual(response.status_code,429,response.text)
        self.assertIn('dibatasi',response.json['error'])

    def test_review_html_shows_holds_and_original_precision(self):
        ident,_=bank.analyze(self.b,self.a,[('synthetic.pdf',statement_pdf())],self.uid)
        response=self.client.get(self.url+'/bank-imports/'+str(ident))
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('12.34 IDR',response.text);self.assertIn('Kemungkinan transfer FX',response.text)
        self.assertIn('IDR, USD',response.text)

    def test_migration_is_idempotent_with_existing_review(self):
        ident,_=bank.analyze(self.b,self.a,[('synthetic.pdf',statement_pdf())],self.uid)
        before=bank.extraction_metadata(self.b,ident)
        db.init_schema()
        self.assertEqual(bank.extraction_metadata(self.b,ident),before)

if __name__=='__main__':unittest.main()
