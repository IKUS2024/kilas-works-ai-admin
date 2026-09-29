"""Focused PDF generation, follow-up, durability and account isolation."""
import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-ai-pdf-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "kilas-ai-pdf-test-only"
os.environ["KILAS_AI_ENABLED"] = "true"
os.environ.pop("DATABASE_URL", None)

from pypdf import PdfReader  # noqa: E402
import app  # noqa: E402
import db  # noqa: E402
import repo  # noqa: E402
from kilas_ai import pdf, providers, store, usage  # noqa: E402


class PdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.app
        cls.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        cls.owner = repo.create_user("pdf-owner@example.test", "hash")
        cls.other = repo.create_user("pdf-other@example.test", "hash")

    def client_for(self, owner):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=owner, role="CLIENT_OWNER", _csrf_token="pdf-csrf")
        return client

    def send(self, client, thread_id, content, key, draft):
        seen = []

        def stream(mode, context):
            seen.append(context[-1]["content"])
            yield {"type": "provider", "provider": "openai", "model": "gpt-6-luna"}
            yield {"type": "delta", "text": draft}
            yield {"type": "usage", "input_tokens": 100, "output_tokens": 200}
            yield {"type": "finish", "reason": "stop"}

        with patch.object(providers, "stream", side_effect=stream):
            response = client.post(f"/kilas-ai/threads/{thread_id}/send", json={
                "content": content, "mode": "FAST", "tool": "CHAT", "operation_key": key,
            }, headers={"X-CSRF-Token": "pdf-csrf"})
            self.assertEqual(response.status_code, 200)
            self.assertIn("event: file", response.get_data(as_text=True))
            self.assertIn("event: done", response.get_data(as_text=True))
        return seen[0]

    def test_real_pdf_followup_and_owner_only_download(self):
        owner = self.client_for(self.owner)
        thread_id = store.create_thread(self.owner)
        first = self.send(owner, thread_id, "Buat proposal ini jadi PDF.", "pdf_first_0123456789abcdef",
            "# Proposal Kegiatan\n\n## Ringkasan\nAcara untuk pelanggan.\n\n| Paket | Harga |\n|---|---|\n| Dasar | Rp100.000 |")
        self.assertIn("Markdown", first)
        stored = store.attachment_list(self.owner, thread_id)
        self.assertEqual(len(stored), 1)
        path = f"/kilas-ai/threads/{thread_id}/attachments/{stored[0]['id']}"
        opened = owner.get(path + "?inline=1")
        self.assertEqual(opened.status_code, 200)
        self.assertIn("inline", opened.headers["Content-Disposition"])
        self.assertTrue(opened.data.startswith(b"%PDF"))
        self.assertGreater(len(opened.data), 1000)
        self.assertIn("Proposal Kegiatan", PdfReader(io.BytesIO(opened.data)).pages[0].extract_text())
        self.assertEqual(self.client_for(self.other).get(path).status_code, 404)
        self.assertIn("ai-file-card", owner.get(f"/kilas-ai/threads/{thread_id}").text)
        second = self.send(owner, thread_id, "Covernya lebih premium dan tambahkan tabel harga.",
            "pdf_second_0123456789abcdef", "# Proposal Kegiatan Baru\n\n## Harga\n| Paket | Harga |\n|---|---|\n| Premium | Rp200.000 |")
        self.assertIn("Proposal Kegiatan", second)
        self.assertEqual(len(store.attachment_list(self.owner, thread_id)), 2)
        self.assertNotEqual(stored[0]["id"], store.attachment_list(self.owner, thread_id)[1]["id"])
        second_id = store.attachment_list(self.owner, thread_id)[1]["id"]
        second_pdf = owner.get(f"/kilas-ai/threads/{thread_id}/attachments/{second_id}").data
        self.assertGreaterEqual(len(PdfReader(io.BytesIO(second_pdf)).pages), 2)
        rows = db.query_all("SELECT operation_type,status FROM kilas_ai_usage WHERE user_id=? ORDER BY id", (self.owner,))
        self.assertEqual([row["operation_type"] for row in rows], ["PDF", "PDF"])
        self.assertTrue(all(row["status"] == "COMPLETE" for row in rows))
        with self.assertRaises(usage.UsageLimit):
            usage.reserve(self.owner, thread_id, "pdf_third_0123456789abcdef", "FAST", "PDF")

    def test_pdf_detection_does_not_capture_information_question(self):
        self.assertFalse(pdf.is_request("Apa itu file PDF?"))
        self.assertTrue(pdf.is_request("Buat jawaban tadi jadi PDF."))
        self.assertFalse(pdf.is_request("Tambahkan tabel harga"))
        self.assertTrue(pdf.is_request("Tambahkan tabel harga", "# Dokumen lama"))

    def test_combined_story_pdf_request_uses_real_file(self):
        owner_id = repo.create_user("pdf-story-request@example.test", "hash")
        owner = self.client_for(owner_id)
        thread_id = store.create_thread(owner_id)
        self.send(owner, thread_id, "bikinin saya dongeng pendek dan buatkan dalam bentuk pdf",
                  "storypdf_0123456789abcdef", "# Dongeng Kucing\n\nSeekor kucing kecil melihat bulan.")
        files = store.attachment_list(owner_id, thread_id)
        self.assertEqual(len(files), 1)
        response = owner.get(f"/kilas-ai/threads/{thread_id}/attachments/{files[0]['id']}")
        self.assertTrue(response.data.startswith(b"%PDF"))
        self.assertIn("Seekor kucing", PdfReader(io.BytesIO(response.data)).pages[0].extract_text())
        self.assertEqual(self.client_for(self.other).get(
            f"/kilas-ai/threads/{thread_id}/attachments/{files[0]['id']}").status_code, 404)
        self.assertEqual(db.query_one("SELECT operation_type FROM kilas_ai_usage WHERE thread_id=?", (thread_id,))["operation_type"],
                         "PDF")

    def test_short_pdf_followup_keeps_story_in_provider_context(self):
        owner_id = repo.create_user("pdf-story-followup@example.test", "hash")
        owner = self.client_for(owner_id)
        thread_id = store.create_thread(owner_id)
        store.append_user_once(owner_id, thread_id, "Buat dongeng anak tentang kucing.", "FAST", "storysource_0123456789")
        story = "# Dongeng Kucing\n\nSeekor kucing kecil menjelajah hutan."
        store.append_assistant(owner_id, thread_id, story, "FAST", "openai", "gpt-6-luna",
                               "storysource_0123456789", {"status": "complete"})
        self.send(owner, thread_id, "pdfnya dong", "storyfollow_0123456789abcdef", story)
        self.assertTrue(any(row["role"] == "assistant" and story in row["content"]
                            for row in store.context(owner_id, thread_id)))
        self.assertEqual(len(store.attachment_list(owner_id, thread_id)), 1)


if __name__ == "__main__":
    unittest.main()
