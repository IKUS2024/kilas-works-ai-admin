"""Focused durable attachment, extraction, multimodal and isolation checks."""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-ai-files-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "kilas-ai-files-test-only"
os.environ["KILAS_AI_ENABLED"] = "true"
os.environ.pop("DATABASE_URL", None)

from PIL import Image  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402
from werkzeug.datastructures import FileStorage  # noqa: E402
import app  # noqa: E402
import repo  # noqa: E402
from kilas_ai import attachments, providers, store  # noqa: E402


def upload(raw, name, mime):
    return FileStorage(stream=io.BytesIO(raw), filename=name, content_type=mime)


def sample_pdf():
    stream = io.BytesIO()
    page = canvas.Canvas(stream)
    page.drawString(50, 750, "Invoice for document analysis")
    page.save()
    return stream.getvalue()


def sample_docx():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Document fact</w:t></w:r></w:p></w:body></w:document>')
    return stream.getvalue()


def sample_image():
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), (240, 105, 32)).save(stream, "PNG")
    return stream.getvalue()


class AttachmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.app
        cls.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        cls.a = repo.create_user("file-a@example.test", "hash")
        cls.b = repo.create_user("file-b@example.test", "hash")

    def client_for(self, owner):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=owner, role="CLIENT_OWNER", _csrf_token="file-csrf")
        return client

    def test_plan_attachment_counts_remain_bounded_and_account_specific(self):
        self.assertEqual([attachments.limits(plan)["max_files"] for plan in ("FREE", "PLUS", "PRO", "MAX")],
                         [2, 3, 4, 5])
        self.assertEqual(attachments.limits("FREE")["max_file_bytes"], 2 * 1024 * 1024)
        self.assertEqual(attachments.limits("FREE")["max_image_bytes"], 100 * 1024 * 1024)
        for plan, allowed in (("FREE", 2), ("PLUS", 3), ("PRO", 4), ("MAX", 5)):
            files = [upload(b"small text", f"note-{index}.txt", "text/plain") for index in range(allowed)]
            self.assertEqual(len(attachments.prepare_many(files, plan=plan)), allowed)
            extra = upload(b"small text", "extra.txt", "text/plain")
            with self.assertRaises(attachments.AttachmentError):
                attachments.prepare_many(files + [extra], plan=plan)

    def test_document_types_extract_bounded_text(self):
        cases = [(sample_pdf(), "info.pdf", "application/pdf", "Invoice"),
                 (sample_docx(), "info.docx", attachments.MIMES["docx"], "Document fact"),
                 (b"hello text", "info.txt", "text/plain", "hello text"),
                 (b"a,b\n1,2", "info.csv", "text/csv", "a,b")]
        for raw, name, mime, expected in cases:
            with self.subTest(name=name):
                result = attachments.prepare(upload(raw, name, mime))
                self.assertIn(expected, result["extracted_text"])
                self.assertLessEqual(len(result["extracted_text"]), attachments.MAX_EXTRACTED_CHARS)

    def test_invalid_content_and_size_rejected(self):
        cases = [(b"not a pdf", "fake.pdf", "application/pdf"),
                 (b"<script>x</script>", "fake.png", "image/png"),
                 (b"x", "bad.exe", "application/octet-stream"),
                 (b"x" * (attachments.MAX_FILE_BYTES + 1), "big.txt", "text/plain")]
        for raw, name, mime in cases:
            with self.subTest(name=name), self.assertRaises(attachments.AttachmentError):
                attachments.prepare(upload(raw, name, mime))

    def test_valid_phone_photo_above_legacy_two_mb_is_accepted(self):
        stream = io.BytesIO()
        image = Image.frombytes("RGB", (1024, 1024), os.urandom(1024 * 1024 * 3))
        image.save(stream, "PNG")
        raw = stream.getvalue()
        self.assertGreater(len(raw), attachments.MAX_FILE_BYTES)
        self.assertLess(len(raw), attachments.MAX_IMAGE_BYTES)

        result = attachments.prepare(upload(raw, "s25-photo.png", "image/png"))
        self.assertEqual(result["content"], raw)
        self.assertEqual(result["byte_size"], len(raw))
        self.assertEqual(result["mime_type"], "image/png")

    def test_multiple_files_durable_and_provider_receives_image(self):
        client = self.client_for(self.a)
        thread_id = store.create_thread(self.a)
        seen = []

        def fake_stream(mode, context):
            seen.append((mode, context))
            yield {"type": "provider", "provider": "openai", "model": "configured"}
            yield {"type": "delta", "text": "Gambar dan dokumen diterima."}
            yield {"type": "finish", "reason": "stop"}

        payload = {"csrf_token": "file-csrf", "content": "Bandingkan ini", "mode": "SMART",
                   "operation_key": "files_0123456789abcdef",
                   "attachments": [(io.BytesIO(sample_image()), "photo.png", "image/png"),
                                   (io.BytesIO(b"A relevant note"), "note.txt", "text/plain")]}
        with patch.object(providers, "stream", side_effect=fake_stream):
            response = client.post(f"/kilas-ai/threads/{thread_id}/send", data=payload,
                                   content_type="multipart/form-data")
            self.assertEqual(response.status_code, 200)
            self.assertIn("Gambar", response.get_data(as_text=True))
        self.assertEqual(len(store.attachment_list(self.a, thread_id)), 2)
        self.assertEqual(seen[0][0], "FAST")
        blocks = seen[0][1][-1]["content"]
        self.assertEqual(blocks[1]["type"], "image_url")
        self.assertIn("A relevant note", blocks[0]["text"])
        item = store.attachment_list(self.a, thread_id)[0]
        path = f"/kilas-ai/threads/{thread_id}/attachments/{item['id']}"
        self.assertEqual(client.get(path).data, sample_image())
        self.assertEqual(self.client_for(self.b).get(path).status_code, 404)

    def test_pdf_text_reaches_provider_as_readable_document(self):
        client = self.client_for(self.a)
        thread_id = store.create_thread(self.a)
        captured = []

        def fake_stream(mode, context):
            captured.extend(context)
            yield {"type": "provider", "provider": "openai", "model": "configured"}
            yield {"type": "delta", "text": "Invoice for document analysis"}
            yield {"type": "finish", "reason": "stop"}

        with patch.object(providers, "stream", side_effect=fake_stream):
            response = client.post(f"/kilas-ai/threads/{thread_id}/send", data={
                "csrf_token": "file-csrf", "content": "Apa isi PDF ini?", "mode": "FAST",
                "operation_key": "pdf_text_0123456789abcdef",
                "attachments": [(io.BytesIO(sample_pdf()), "info.pdf", "application/pdf")],
            }, content_type="multipart/form-data")
            self.assertEqual(response.status_code, 200)
            self.assertIn("Invoice", response.get_data(as_text=True))
        prompt = captured[-1]["content"]
        self.assertIn("Teks berikut berhasil diekstrak", prompt)
        self.assertIn("<isi_lampiran>\nInvoice for document analysis\n</isi_lampiran>", prompt)


if __name__ == "__main__":
    unittest.main()
