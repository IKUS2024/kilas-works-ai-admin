"""Independent-parser recovery with real PDFs, bounded child processes and original bytes."""
import io
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from reportlab.pdfgen import canvas
from pypdf import PdfWriter
from test_finance_phase6a import pdf_bytes
from test_finance_pdf_routing import secured_pdf
import file_utils

WORKER=Path(file_utils.__file__).with_name('finance_receipt_pdf.py')


def run_worker(raw,hook='',structural=False):
    code='import sys,runpy,pypdf;'+hook+';sys.argv='+repr([str(WORKER),'--document']+(['--validate-only'] if structural else []))+';runpy.run_path('+repr(str(WORKER))+',run_name="__main__")'
    result=subprocess.run([sys.executable,'-c',code],input=raw,capture_output=True,timeout=10,check=True)
    return json.loads(result.stdout),result.stderr


def bank_export():
    stream=io.BytesIO();doc=canvas.Canvas(stream,pageCompression=1)
    doc.drawString(40,780,'BANK CENTRAL ASIA - MUTASI REKENING - IDR')
    doc.drawString(40,755,'PERIODE JUNI 2026')
    doc.drawString(40,730,'01/06/2026 TRANSFER MASUK 1.000.000,00 CR')
    doc.drawString(40,705,'02/06/2026 PEMBAYARAN 250.000,00 DB')
    doc.save()
    # Representative bank-export xref defect; QPDF and permissive readers recover objects.
    return re.sub(rb'startxref\s+\d+',b'startxref\n1',stream.getvalue())


class RecoveryTests(unittest.TestCase):
    def test_real_bca_style_xref_defect_classifiable(self):
        raw=bank_export()
        file_utils.validate_finance_pdf('export.pdf',raw)
        self.assertTrue(file_utils.validate_bank_pdf('export.pdf',raw)[1])
    def test_secondary_parser_accepts_primary_structure_exception(self):
        hook="pypdf.PdfReader=lambda *a,**k:(_ for _ in ()).throw(ValueError('PRIVATE'))"
        for raw in (pdf_bytes(text=True),bank_export(),secured_pdf()):
            with self.subTest(size=len(raw)):
                result,logs=run_worker(raw,hook,True)
                self.assertEqual(result,{'text':''});self.assertIn(b'vision_fallback',logs)
                self.assertNotIn(b'PRIVATE',logs)
    def test_secondary_password_and_page_limits_still_reject(self):
        hook="pypdf.PdfReader=lambda *a,**k:(_ for _ in ()).throw(ValueError('primary failed'))"
        for raw,code in [(secured_pdf('secret'),'encrypted/password_required'),(pdf_bytes(21),'page_limit'),(b'%PDF-1.4\ntruncated\n%%EOF','malformed_pdf')]:
            self.assertEqual(run_worker(raw,hook,True)[0],{'error':code})
    def test_text_and_font_exceptions_do_not_invalidate_structure(self):
        for exception in ('ValueError','KeyError'):
            hook='pypdf._page.PageObject.extract_text=lambda *a,**k:(_ for _ in ()).throw('+exception+"('PRIVATE FONT'))"
            result,logs=run_worker(pdf_bytes(text=True),hook)
            self.assertEqual(result,{'text':''});self.assertIn(b'text_extraction_failed',logs)
            self.assertNotIn(b'PRIVATE',logs)
    def test_actual_image_only_pdf_uses_original_document(self):
        import finance_bank_extract as extraction
        import base64
        stream=io.BytesIO();Image.new('RGB',(400,300),'white').save(stream,'PDF')
        raw=stream.getvalue();file_utils.validate_finance_pdf('scan.pdf',raw)
        content=extraction.provider_content(extraction.validate_sources([('scan.pdf',raw)]))[0]
        self.assertEqual(content['type'],'document');self.assertEqual(base64.b64decode(content['source']['data']),raw)
    def test_worker_memory_failure_is_not_retried_as_corruption(self):
        hook="pypdf.PdfReader=lambda *a,**k:(_ for _ in ()).throw(MemoryError())"
        self.assertEqual(run_worker(pdf_bytes(),hook,True)[0],{'error':'resource_limit'})
    def test_truncated_pdf_rejected(self):
        raw=pdf_bytes(text=True)
        with self.assertRaises(file_utils.UploadRejected):file_utils.validate_finance_pdf('bad.pdf',raw[:len(raw)//2])
    def test_original_pdf_from_recovered_worker_reaches_recognition(self):
        # Run the real secondary parser in the same isolated worker used by production.
        import test_finance_assistant_inline as fixture
        case=fixture.InlineTests();case.setUp()
        try:
            case.model({'workflow':'BANK_STATEMENT'})
            raw=bank_export();real_run=subprocess.run
            def worker(args,**kwargs):
                if args[-1]=='--validate-only':
                    result,stderr=run_worker(kwargs['input'],"pypdf.PdfReader=lambda *a,**k:(_ for _ in ()).throw(ValueError())",True)
                    return subprocess.CompletedProcess(args,0,json.dumps(result).encode(),stderr)
                return real_run(args,**kwargs)
            # Avoid recursively intercepting the -c harness.
            original_worker=run_worker
            def bounded(raw,hook='',structural=False):
                with patch.object(subprocess,'run',real_run):return original_worker(raw,hook,structural)
            with patch(__name__+'.run_worker',bounded),patch.object(subprocess,'run',worker):
                response=case.client.post(case.path+'/recognize',data={'sources':(io.BytesIO(raw),'private.pdf'),'text':''})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json['workflow'],'BANK_STATEMENT')
            content=case.http.call_args.kwargs['json']['messages'][0]['content'][0]
            import base64
            self.assertEqual(base64.b64decode(content['source']['data']),raw)
        finally:case.doCleanups()

if __name__=='__main__':unittest.main()
