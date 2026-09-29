"""Focused natural routing and one-action/one-unit contract."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-ai-routing-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "kilas-ai-routing-test-only"
os.environ.pop("DATABASE_URL", None)

import app  # noqa: E402
import db  # noqa: E402
import repo  # noqa: E402
from kilas_ai import routing, store, usage  # noqa: E402


class RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner = repo.create_user("routing-owner@example.test", "hash")
        cls.thread = store.create_thread(cls.owner)

    def test_default_and_complex_modes(self):
        for prompt in ("Halo", "Buat caption singkat", "Ringkas paragraf ini", "Terjemahkan kalimat ini"):
            self.assertEqual(routing.mode_for(prompt), "FAST")
        self.assertEqual(routing.mode_for("Debug implementasi kode ini dan jelaskan akar masalah"), "SMART")
        self.assertEqual(routing.mode_for("Bandingkan dokumen", [{"extracted_text": "a"}, {"extracted_text": "b"}]), "SMART")

    def test_natural_tools_and_analysis(self):
        image = [{"mime_type": "image/png"}]
        document = [{"mime_type": "application/pdf", "extracted_text": "isi"}]
        for prompt in ("buat gambar mobil", "buatkan gambar mobil", "bikinin gambar mobil",
                       "gambar mobil dong", "gambarin mobil", "gamabar mobil", "gmbar mobil",
                       "gmbaar mobil", "gambarr mobil", "buat ilustrasi kucing kecil di bawah bulan",
                       "buat poster kopi", "buatkan gambar apapun ya", "create an image of a car",
                       "draw a cat", "sekarang bikin gambarnya"):
            with self.subTest(prompt=prompt):
                self.assertEqual(routing.tool_for(prompt), "IMAGE_GENERATE")
        for prompt in ("Buat gambar kucing di Tokyo", "Apa itu image generation?",
                       "jelaskan cara buat gambar", "kenapa gambar ini bagus?",
                       "model gambar apa yang dipakai?", "berapa harga generate image?",
                       "halo", "buat caption instagram", "tolong translate ini",
                       "ringkas paragraf ini", "apa itu PDF?", "cara edit foto di Photoshop gimana?"):
            expected = "IMAGE_GENERATE" if prompt.startswith("Buat gambar") else "CHAT"
            with self.subTest(prompt=prompt):
                self.assertEqual(routing.tool_for(prompt), expected)
        for prompt in ("hapus background", "background putih", "ubah bajunya hitam",
                       "ganti warna mobil jadi merah", "edit ini", "rapihin foto ini",
                       "buat lebih terang", "hilangkan orang di belakang", "crop ini", "retouch wajahnya"):
            with self.subTest(prompt=prompt):
                self.assertEqual(routing.tool_for(prompt, image), "IMAGE_EDIT")
        self.assertEqual(routing.tool_for("hapus background foto ini"), "IMAGE_EDIT")
        for prompt in ("buat pdf", "buatkan PDF", "bikinin pdf", "jadikan pdf",
                       "buat ini jadi pdf", "dalam bentuk pdf", "buat file pdf", "export ke pdf",
                       "simpan jadi pdf", "buatkan dongeng ini dalam bentuk pdf",
                       "buat proposal ini lalu jadikan pdf",
                       "bikinin saya dongeng dan buatkan dalam bentuk pdf",
                       "bikinin saya dongeng pendek dan buatkan dalam bentuk pdf"):
            with self.subTest(prompt=prompt):
                self.assertEqual(routing.tool_for(prompt), "PDF")
        self.assertEqual(routing.tool_for("pdfnya dong", has_previous_content=True), "PDF")
        self.assertEqual(routing.tool_for("jadikan jawaban tadi PDF", has_previous_content=True), "PDF")
        self.assertEqual(routing.tool_for("Ringkas PDF ini", document), "CHAT")
        self.assertEqual(routing.tool_for("Apa isi gambar ini?", image), "CHAT")
        self.assertEqual(routing.tool_for("Buat jawaban tadi jadi PDF", pdf_request=True), "PDF")
        self.assertEqual(routing.tool_for("Cari informasi terbaru", search=True), "WEB")
        self.assertEqual(routing.tool_for("buatkan gambar apapun ya", search=True), "WEB")
        self.assertIn("Konsep sebelumnya:", routing.image_prompt(
            "sekarang bikin gambarnya", "Konsep poster kopi premium dengan latar cokelat."))
        enhanced = routing.enhance_image_prompt("buat manusia lagi nyanyi dengan gaya watercolor")
        self.assertIn("manusia lagi nyanyi", enhanced)
        self.assertIn("watercolor", enhanced)
        self.assertIn("mulut terbuka", enhanced)
        self.assertEqual(routing.enhance_image_prompt("buat poster kopi"), "buat poster kopi")

    def test_one_primary_quota_unit_and_legacy_rows(self):
        for tool, expected in (("CHAT", "CHAT"), ("WEB", "WEB_SEARCH"),
                               ("IMAGE_GENERATE", "IMAGE_GENERATION"), ("IMAGE_EDIT", "IMAGE_EDIT"),
                               ("PDF", "PDF")):
            self.assertEqual(usage._operations("FAST", tool), (expected,))
        old_key = "historical-web-0123456789"
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        for kind in ("CHAT", "WEB_SEARCH"):
            db.execute("INSERT INTO kilas_ai_usage(user_id,thread_id,operation_key,operation_type,mode,status,created_at) "
                       "VALUES (?,?,?,?,?,'COMPLETE',?)", (self.owner, self.thread, old_key, kind, "FAST", now))
        state = usage.snapshot(self.owner)["usage"]
        self.assertEqual(state["Chat"]["used"], 0)
        self.assertEqual(state["Search"]["used"], 1)
        self.assertEqual((usage.PLANS["FREE"]["CHAT"], usage.PLANS["FREE"]["CHAT_DAILY"]), (100, 10))
        self.assertEqual((usage.PLANS["PLUS"]["CHAT"], usage.PLANS["PRO"]["CHAT"], usage.PLANS["MAX"]["CHAT"]),
                         (600, 1500, 3000))


if __name__ == "__main__":
    unittest.main()
