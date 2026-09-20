"""Bounded PDF validation before classification and original-document fallback, offline."""
import base64
import io
import subprocess
import unittest
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from test_finance_phase6a import pdf_bytes
import test_finance_assistant_inline as inline
import file_utils
import finance_ai_safety as safety
import finance_bank_extract as extraction
import finance_service as finance


def secured_pdf(password='', text=True):
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(pdf_bytes(text=text))))
    writer.encrypt(user_password=password, owner_password='owner-only-password')
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class PDFValidationTests(unittest.TestCase):
    def test_generic_validation_does_not_extract_text_or_use_bank_validator(self):
        run = subprocess.run
        def structural(args, **kwargs):
            self.assertIn('--validate-only', args)
            self.assertNotIn('--bank-statement', args)
            return run(args, **kwargs)
        with patch.object(subprocess, 'run', side_effect=structural), patch.object(
                file_utils, 'validate_bank_pdf', side_effect=AssertionError('bank before classification')):
            for raw in (pdf_bytes(text=True), pdf_bytes(), secured_pdf()):
                file_utils.validate_finance_pdf('document.pdf', raw)

    def test_text_and_scanned_pdf_keep_original_bytes(self):
        for text in (True, False):
            raw = pdf_bytes(text=text)
            source = extraction.validate_sources([('document.pdf', raw)])
            self.assertEqual(source['sources'][0]['raw'], raw)
            content = extraction.provider_content(source)[0]
            self.assertEqual(content['type'], 'text' if text else 'document')
            if not text:
                self.assertEqual(base64.b64decode(content['source']['data']), raw)

    def test_readable_security_flag_keeps_receipt_and_bank_paths(self):
        for text in (True, False):
            raw = secured_pdf(text=text)
            self.assertTrue(PdfReader(io.BytesIO(raw)).is_encrypted)
            file_utils.validate_finance_pdf('document.pdf', raw)
            self.assertEqual(bool(file_utils.validate_bank_pdf('document.pdf', raw)[1]), text)
            self.assertEqual(bool(file_utils.validate_receipt_upload('document.pdf', raw)[2]), text)

    def test_rejection_reasons_are_exact_and_private(self):
        for raw, reason in (
            (secured_pdf('private-opening-password'), 'encrypted/password_required'),
            (pdf_bytes(21), 'page_limit'),
            (b'%PDF malformed PRIVATE DOCUMENT TEXT 998877', 'malformed_pdf'),
            (b'%PDF' + b'x' * (10 * 1024 * 1024), 'size_limit'),
        ):
            with self.subTest(reason=reason), self.assertLogs('kilas.finance_ai', 'INFO') as logs:
                with self.assertRaises(file_utils.UploadRejected) as raised:
                    file_utils.validate_finance_pdf('PRIVATE_ACCOUNT_998877.pdf', raw)
                self.assertEqual(raised.exception.code, reason)
            self.assertEqual(logs.output, ['INFO:kilas.finance_ai:FINANCE_AI pdf_reason=' + reason])

    def test_generic_twenty_page_boundary_receipt_limit_remains_ten(self):
        file_utils.validate_finance_pdf('document.pdf', pdf_bytes(20))
        with self.assertRaises(file_utils.UploadRejected) as raised:
            file_utils.validate_receipt_upload('document.pdf', pdf_bytes(11))
        self.assertEqual(raised.exception.code, 'page_limit')

    def test_parser_timeout_rejected_without_provider_or_retry(self):
        with patch.object(subprocess, 'run', side_effect=subprocess.TimeoutExpired('PRIVATE', 8)) as run:
            with self.assertRaises(file_utils.UploadRejected) as raised:
                file_utils.validate_bank_pdf('private.pdf', pdf_bytes())
        self.assertEqual(raised.exception.code, 'parser_timeout')
        self.assertEqual(run.call_count, 1)

    def test_resource_limit_and_malformed_worker_output_fail_closed(self):
        for failure, reason in ((subprocess.CalledProcessError(-9, 'PRIVATE'), 'resource_limit'),
                                (subprocess.CalledProcessError(-24, 'PRIVATE'), 'resource_limit')):
            with patch.object(subprocess, 'run', side_effect=failure), self.assertLogs('kilas.finance_ai') as logs:
                with self.assertRaises(file_utils.UploadRejected) as raised:
                    file_utils.validate_finance_pdf('private.pdf', pdf_bytes())
            self.assertEqual(raised.exception.code, reason)
            self.assertNotIn('PRIVATE', ''.join(logs.output))
        result = subprocess.CompletedProcess([], 0, b'{"unexpected":"PRIVATE"}', b'PRIVATE')
        with patch.object(subprocess, 'run', return_value=result):
            with self.assertRaises(file_utils.UploadRejected) as raised:
                file_utils.validate_finance_pdf('private.pdf', pdf_bytes())
        self.assertEqual(raised.exception.code, 'malformed_pdf')

    def test_untrusted_log_reason_is_allowlisted(self):
        with self.assertLogs('kilas.finance_ai') as logs:
            safety.pdf_event('PRIVATE document text 998877')
        self.assertEqual(logs.output, ['INFO:kilas.finance_ai:FINANCE_AI pdf_reason=malformed_pdf'])


class PDFAssistantTests(unittest.TestCase):
    setUp = inline.InlineTests.setUp
    model = inline.InlineTests.model
    document = inline.InlineTests.document
    receipt_model = inline.InlineTests.receipt_model
    snapshot = inline.InlineTests.snapshot

    def recognize(self, raw):
        return self.client.post(self.path + '/recognize', data={
            'sources': (io.BytesIO(raw), 'private.pdf'), 'text': ''})

    def test_pdf_auto_classification_uses_generic_validation_for_all_workflows(self):
        before = self.snapshot()
        for workflow in ('RECEIPT', 'BANK_STATEMENT', 'HANDWRITTEN_NOTE'):
            self.model({'workflow': workflow})
            with patch.object(file_utils, 'validate_bank_pdf', side_effect=AssertionError('too early')):
                response = self.recognize(pdf_bytes(text=True))
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json['workflow'], workflow)
            content = self.http.call_args.kwargs['json']['messages'][0]['content'][0]
            self.assertEqual(content['type'], 'document')
        self.assertEqual(self.snapshot(), before)

    def test_readable_flagged_receipt_classifies_then_returns_review(self):
        raw = secured_pdf()
        self.model({'workflow': 'RECEIPT'})
        self.assertEqual(self.recognize(raw).json['workflow'], 'RECEIPT')
        self.receipt_model()
        response = self.document('RECEIPT', raw, 'receipt.pdf')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json['ready'])
        self.assertIn('token', response.json)
        self.assertEqual(finance.list_transactions(self.b), [])

    def test_scanned_pdf_classifies_then_bank_or_notes_review_without_write(self):
        for workflow in ('BANK_STATEMENT', 'HANDWRITTEN_NOTE'):
            raw = secured_pdf(text=False) if workflow == 'BANK_STATEMENT' else pdf_bytes()
            self.model({'workflow': workflow})
            self.assertEqual(self.recognize(raw).json['workflow'], workflow)
            self.model(self.result)
            response = self.document(workflow, raw, 'document.pdf')
            self.assertEqual(response.status_code, 200, response.text)
            content = self.http.call_args.kwargs['json']['messages'][0]['content'][0]
            self.assertEqual(base64.b64decode(content['source']['data']), raw)
        self.assertEqual(finance.list_transactions(self.b), [])

    def test_text_parser_failure_reaches_original_pdf_ai_review(self):
        raw = pdf_bytes(text=True)
        self.model(self.result)
        run = subprocess.run
        def fail_text(args, **kwargs):
            if '--validate-only' not in args:
                return subprocess.CompletedProcess(args,0,b'{"error":"malformed_pdf"}',b'')
            return run(args, **kwargs)
        with patch.object(subprocess, 'run', side_effect=fail_text):
            response = self.document('BANK_STATEMENT', raw, 'document.pdf')
        self.assertEqual(response.status_code, 200, response.text)
        content = self.http.call_args.kwargs['json']['messages'][0]['content'][0]
        self.assertEqual(base64.b64decode(content['source']['data']), raw)
        self.assertEqual(finance.list_transactions(self.b), [])

    def test_unsafe_pdfs_reject_inline_before_ai(self):
        for raw in (secured_pdf('private-password'), pdf_bytes(21), b'%PDF malformed'):
            self.http.reset_mock()
            response = self.recognize(raw)
            self.assertEqual(response.status_code, 400)
            self.assertTrue(response.is_json)
            self.assertIn('error', response.json)
            self.assertNotIn('<html', response.text)
            self.http.assert_not_called()


if __name__ == '__main__':
    unittest.main()
