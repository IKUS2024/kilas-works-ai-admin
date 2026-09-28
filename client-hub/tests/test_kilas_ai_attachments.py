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
        self.assertEqual(seen[0][0], "SMART")
        blocks = seen[0][1][-1]["content"]
        self.assertEqual(blocks[1]["type"], "image_url")
        self.assertIn("A relevant note", blocks[0]["text"])
        item = store.attachment_list(self.a, thread_id)[0]
        path = f"/kilas-ai/threads/{thread_id}/attachments/{item['id']}"
        self.assertEqual(client.get(path).data, sample_image())
        self.assertEqual(self.client_for(self.b).get(path).status_code, 404)


if __name__ == "__main__":
    unittest.main()
