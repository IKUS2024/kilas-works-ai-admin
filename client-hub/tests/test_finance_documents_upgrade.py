"""Document review/posting against current minor-unit and scope contracts."""
import base64
import json
import unittest
from unittest.mock import patch
import test_finance_phase6b as prior
from test_finance_bank_sections import statement_pdf
import finance_bank_extract as x
import finance_bank_service as bank
import finance_service as f
import finance_branches as branches
import file_utils

class DocumentUpgradeTests(unittest.TestCase):
    setUp=prior.BankTests.setUp
    fields=prior.BankTests.fields

    def model(self,rows,readable=True):
        return {'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(dict(rows=rows,readable=readable))}]}

    def test_pdf_sections_preserve_two_decimals_currency_and_direction(self):
        source=x.validate_sources([('statement.pdf',statement_pdf())])
        rows,_=x.extract(source,self.uid,self.b,'IDR')
        self.assertEqual(len(rows),10)
        self.assertEqual(rows[0]['amount_minor'],10000)
        self.assertEqual(rows[8]['amount_minor'],1234)
        self.assertEqual(rows[9]['amount_minor'],234)
        self.assertEqual(sum(r['direction']=='EXPENSE' for r in rows),6)
        self.assertTrue(all(r['transaction_date'].startswith('2025-04-') for r in rows))
        self.http.assert_not_called()

    def test_zero_rows_text_retries_original_pdf_and_never_succeeds_empty(self):
        raw=prior.pdf_bytes(text=True)
        source=x.validate_sources([('statement.pdf',raw)])
        row=dict(self.row,currency='IDR',amount='1000.25')
        self.response.json.side_effect=[self.model([],False),self.model([row])]
        rows,_=x.extract(source,self.uid,self.b,'IDR')
        self.assertEqual(rows[0]['amount_minor'],100025)
        calls=self.http.call_args_list
        self.assertEqual(calls[0].kwargs['json']['messages'][0]['content'][0]['type'],'text')
        document=calls[1].kwargs['json']['messages'][0]['content'][0]
        self.assertEqual(document['type'],'document')
        self.assertEqual(base64.b64decode(document['source']['data']),raw)
        self.response.json.side_effect=[self.model([],False),self.model([],False)]
        with self.assertRaisesRegex(x.BankError,'parser_uncertain'):x.extract(source,self.uid,self.b,'IDR')

    def test_image_and_scan_pdf_keep_real_media_and_minor_values(self):
        for name,raw,kind in [('screenshot.png',self.raw,'image'),('scan.pdf',prior.pdf_bytes(),'document')]:
            self.response.json.return_value=self.model([dict(self.row,currency='IDR',amount='250000.50')])
            source=x.validate_sources([(name,raw)])
            rows,_=x.extract(source,self.uid,self.b,'IDR')
            self.assertEqual(rows[0]['amount_minor'],25000050)
            content=self.http.call_args.kwargs['json']['messages'][0]['content'][0]
            self.assertEqual(content['type'],kind)

    def test_csv_review_posting_duplicate_and_foreign_tenant(self):
        raw=b'date,description,debit,credit,reference\n2026-09-17,Test purchase,1000.25,0,QA-CSV-UNIQUE\n'
        ident,_=bank.analyze(self.b,self.a,[('statement.csv',raw)],self.uid)
        self.assertEqual(f.list_transactions(self.b),[])
        row=bank.get_rows(self.b,ident,self.uid)[0]
        self.assertEqual(row['amount_minor'],100025)
        bank.open_import(self.b,ident,0,self.uid)
        bank.decide(self.b,ident,row['id'],'post',self.uid,fields=self.fields())
        self.assertEqual(f.list_transactions(self.b)[0]['amount_minor'],100025)
        self.assertEqual(bank.analyze(self.b,self.a,[('statement.csv',raw)],self.uid)[0],ident)
        self.assertEqual(len(f.list_transactions(self.b)),1)
        with self.assertRaises(ValueError):bank.get_rows(self.other,ident,self.other_uid)

    def test_invalid_mime_and_ambiguous_direction_reject_before_provider(self):
        with self.assertRaises((ValueError,file_utils.UploadRejected)):
            x.validate_sources([('receipt.png',b'<html>not an image</html>')])
        with self.assertRaises(ValueError):x.parse_csv(b'date,description,debit,credit\n2026-09-17,Unclear,100,100\n')
        self.http.assert_not_called()

if __name__=='__main__':unittest.main()
