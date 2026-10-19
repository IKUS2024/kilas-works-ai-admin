"""Real bounded PDFs and selected Astra thread persistence; all providers mocked."""
import io
import random
import unittest
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader
import test_kilas_thread_documents as threads
from kilas_ai import pdf, providers, store


def table_source(columns=8, rows=40):
    return ('# Synthetic Table\n\n| ' + ' | '.join(f'C{i}' for i in range(columns)) + ' |\n'
            + '| ' + ' | '.join('---' for _ in range(columns)) + ' |\n'
            + '\n'.join('| ' + ' | '.join(f'R{row:02}C{col}' for col in range(columns)) + ' |'
                        for row in range(1, rows + 1)))


def long_source(sections):
    return '# Synthetic Many Pages\n\n' + '\n\n'.join(
        f'## Section {i}\n\nThis is synthetic content.' for i in range(sections))


class RendererBoundaries(unittest.TestCase):
    def test_all_table_rows_and_eight_columns_are_retained(self):
        for professional in (False, True):
            with self.subTest(professional=professional):
                result = pdf.render(table_source(), professional=professional)
                pages = PdfReader(io.BytesIO(result['content']), strict=True).pages
                text = ''.join(page.extract_text() for page in pages)
                for row in range(1, 41):
                    for col in range(8):
                        self.assertIn(f'R{row:02}C{col}', text)
                self.assertEqual(result['extracted_text'], table_source())

    def test_invalid_tables_fail_instead_of_dropping_cells(self):
        for source in (table_source(columns=9), table_source() + '\n| Unequal | row |',
                       '# Single Row\n\n| Only | row |'):
            with self.subTest(source=source[:40]), self.assertRaisesRegex(ValueError, 'invalid_document_table'):
                pdf.render(source)

    def test_source_limit_rejects_instead_of_silently_truncating(self):
        prefix, suffix = '# Source Boundary\n\n', '\n\nLASTSENTINEL'
        length = pdf.MAX_MARKDOWN - len(prefix) - len(suffix)
        source = prefix + ('A ' * ((length + 1) // 2))[:length] + suffix
        result = pdf.render(source)
        self.assertEqual(len(source), 24000)
        self.assertEqual(result['extracted_text'], source)
        self.assertIn('LASTSENTINEL', ''.join(page.extract_text() for page in
                      PdfReader(io.BytesIO(result['content']), strict=True).pages))
        with self.assertRaisesRegex(ValueError, 'document_too_long'):
            pdf.render(source + 'x')

    def test_fifty_pages_reopen_and_page_fifty_one_is_rejected(self):
        result = pdf.render(long_source(490))
        pages = PdfReader(io.BytesIO(result['content']), strict=True).pages
        self.assertEqual(len(pages), 50)
        self.assertGreater(len(result['content']), 65536)
        self.assertIn('Section 489', pages[-1].extract_text())
        with self.assertRaisesRegex(ValueError, 'document_page_limit'):
            pdf.render(long_source(500))

    def test_real_pdf_over_eight_mib_is_rejected(self):
        image = io.BytesIO()
        Image.frombytes('RGB', (1600, 1600), random.Random(72).randbytes(1600 * 1600 * 3)).save(image, format='PNG')
        self.assertEqual(pdf.MAX_BYTES, 8 * 1024 * 1024)
        with self.assertRaisesRegex(ValueError, 'invalid_generated_pdf'):
            pdf.render('# Oversized Image\n\nSynthetic content.', logo=image.getvalue())


class AstraThreadDocuments(unittest.TestCase):
    setUp = threads.ThreadDocuments.setUp
    client = threads.ThreadDocuments.client
    submit = threads.ThreadDocuments.submit
    stream = threads.ThreadDocuments.stream

    def test_small_and_fifty_page_astra_files_survive_reload_and_remain_owned(self):
        for label, source in [('small', table_source()), ('large', long_source(490))]:
            with self.subTest(label=label):
                key = 'astra_pdf_' + label + '_000000000001'
                with patch.object(providers, 'stream', side_effect=self.stream(source)) as author, \
                     patch('e2b.Sandbox.create', side_effect=AssertionError('Trusted PDF rendering needs no VM')):
                    response = self.submit('gpt-6-astra', 'Buat PDF laporan sintetis.', agent=False, key=key)
                    self.assertIn('event: file', response.text)
                    self.assertEqual(author.call_args.args[1].selected_model, 'gpt-6-astra')
                    self.submit('gpt-6-astra', 'Buat PDF laporan sintetis.', agent=False, key=key)
                    author.assert_called_once()
                item = store.attachment_list(self.owner, self.thread)[-1]
                path = f'/kilas-ai/threads/{self.thread}/attachments/{item["id"]}'
                response = self.client().get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, bytes(store.attachment(self.owner, self.thread, item['id'])['content']))
                self.assertIn('attachment;', response.headers['Content-Disposition'])
                self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
                self.assertIn('sandbox', response.headers['Content-Security-Policy'])
                reloaded = self.client().get(f'/kilas-ai/threads/{self.thread}')
                self.assertIn(item['filename'], reloaded.text)
                self.assertIn(path, reloaded.text)
                self.assertEqual(self.client(self.other).get(path).status_code, 404)
                another = store.create_thread(self.owner)
                self.assertEqual(self.client().get(f'/kilas-ai/threads/{another}/attachments/{item["id"]}').status_code, 404)
                pages = PdfReader(io.BytesIO(response.data), strict=True).pages
                text = ''.join(page.extract_text() for page in pages)
                self.assertIn('R40C7' if label == 'small' else 'Section 489', text)
                if label == 'large':
                    self.assertEqual(len(pages), 50)
                    self.assertGreater(len(response.data), 65536)
                print(f'ASTRA_PDF_EVIDENCE profile={label} bytes={len(response.data)} pages={len(pages)} owned_reload_download=True')

    def test_rejected_pdf_never_publishes_success_or_attachment(self):
        for index, source in enumerate((table_source(columns=9), long_source(500), 'x' * 24001)):
            with patch.object(providers, 'stream', side_effect=self.stream(source)):
                response = self.submit('gpt-6-astra', 'Buat PDF laporan sintetis.', agent=False,
                                       key='astra_pdf_reject_' + str(index).zfill(18))
            self.assertIn('event: error', response.text)
            self.assertNotIn('event: file', response.text)
            self.assertFalse(store.attachment_list(self.owner, self.thread))


if __name__ == '__main__':
    unittest.main()
