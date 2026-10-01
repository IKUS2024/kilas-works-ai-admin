"""Public legal pages required for OAuth/provider verification stay anonymous and complete."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-legal-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "synthetic-legal-pages-test-only"
os.environ.pop("DATABASE_URL", None)

import app  # noqa: E402


class PublicLegalPagesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.app.test_client()

    def test_privacy_is_public_and_google_ready(self):
        response = self.client.get("/privacy", follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Kebijakan Privasi Kilas Works", response.text)
        self.assertIn("Google API Services User Data Policy", response.text)
        self.assertIn("Limited Use requirements", response.text)
        self.assertIn("Gmail", response.text)
        self.assertIn("setelah pengguna menyetujui", response.text)
        self.assertIn("tidak meminta izin untuk membaca Gmail", response.text)
        self.assertEqual(response.headers.get("X-Robots-Tag"), "index, follow")

    def test_terms_is_public_and_links_privacy(self):
        response = self.client.get("/terms", follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ketentuan Layanan Kilas Works", response.text)
        self.assertIn('href="/privacy"', response.text)
        self.assertIn("CV Kilas Teknologi Kreatif", response.text)
        self.assertEqual(response.headers.get("X-Robots-Tag"), "index, follow")


if __name__ == "__main__":
    unittest.main()
