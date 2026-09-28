"""Focused flag, account isolation and schema checks for Kilas AI milestone 1."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_db_file = tempfile.mktemp(prefix="kilas-ai-foundation-", suffix=".sqlite")
os.environ["CLIENT_HUB_DB_PATH"] = _db_file
os.environ["SECRET_KEY"] = "kilas-ai-foundation-test-only"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("KILAS_AI_ENABLED", None)

import app  # noqa: E402
import db  # noqa: E402
import repo  # noqa: E402
from kilas_ai import store  # noqa: E402


class KilasAIFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.app
        cls.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        cls.owner_a = repo.create_user("kilas-ai-a@example.test", "test-hash", role="CLIENT_OWNER")
        cls.owner_b = repo.create_user("kilas-ai-b@example.test", "test-hash", role="CLIENT_OWNER")
        cls.admin = repo.create_user("kilas-ai-admin@example.test", "test-hash", role="KILAS_ADMIN")

    def client_for(self, user_id=None, role="CLIENT_OWNER"):
        client = self.app.test_client()
        if user_id:
            with client.session_transaction() as session:
                session.update(user_id=user_id, role=role, _csrf_token="kilas-ai-test-csrf")
        return client

    def test_flag_off_hides_picker_and_denies_route_and_post(self):
        client = self.client_for(self.owner_a)
        with patch.dict(os.environ, {"KILAS_AI_ENABLED": "false"}):
            picker = client.get("/products/start")
            self.assertEqual(picker.status_code, 200)
            self.assertNotIn('value="kilas_ai"', picker.text)
            self.assertEqual(client.get("/kilas-ai").status_code, 404)
            self.assertEqual(client.post("/products/start", data={"product": "kilas_ai", "csrf_token": "kilas-ai-test-csrf"}).status_code, 404)

    def test_flag_on_selects_account_without_creating_business(self):
        client = self.client_for(self.owner_a)
        before = db.query_one("SELECT COUNT(*) AS n FROM businesses")["n"]
        with patch.dict(os.environ, {"KILAS_AI_ENABLED": "true"}):
            picker = client.get("/products/start")
            self.assertIn('value="kilas_ai"', picker.text)
            response = client.post("/products/start", data={"product": "kilas_ai", "csrf_token": "kilas-ai-test-csrf"})
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.location, "/kilas-ai")
            self.assertIn("Kilas AI", client.get(response.location).text)
            self.assertEqual(client.get("/products/start").status_code, 200)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM businesses")["n"], before)

    def test_anonymous_and_admin_cannot_open_account_workspace(self):
        with patch.dict(os.environ, {"KILAS_AI_ENABLED": "true"}):
            self.assertEqual(self.client_for().get("/kilas-ai").status_code, 302)
            self.assertEqual(self.client_for(self.admin, "KILAS_ADMIN").get("/kilas-ai").status_code, 404)

    def test_threads_are_user_owned_and_delete_is_scoped(self):
        a_thread = store.create_thread(self.owner_a)
        b_thread = store.create_thread(self.owner_b)
        self.assertIsNone(store.thread(self.owner_a, b_thread))
        self.assertFalse(store.rename_thread(self.owner_a, b_thread, "Not mine"))
        self.assertFalse(store.delete_thread(self.owner_a, b_thread))
        self.assertEqual(store.thread(self.owner_b, b_thread)["title"], "Chat baru")
        self.assertTrue(store.rename_thread(self.owner_a, a_thread, "My chat"))
        self.assertEqual(store.thread(self.owner_a, a_thread)["title"], "My chat")
        self.assertEqual([row["id"] for row in store.list_threads(self.owner_a)], [a_thread])
        self.assertTrue(store.delete_thread(self.owner_a, a_thread))
        self.assertIsNone(store.thread(self.owner_a, a_thread))

    def test_schema_is_additive_and_account_scoped(self):
        tables = {row["name"] for row in db.query_all("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'kilas_ai_%'")}
        self.assertTrue({"kilas_ai_threads", "kilas_ai_messages", "kilas_ai_attachments", "kilas_ai_usage",
                         "kilas_ai_subscriptions", "kilas_ai_invoices", "kilas_ai_payments"}.issubset(tables))
        for table in tables - {"kilas_ai_schema_releases"}:
            columns = {row["name"] for row in db.query_all("PRAGMA table_info(" + table + ")")}
            self.assertIn("user_id", columns, table) if table != "kilas_ai_messages" else self.assertIn("thread_id", columns)


if __name__ == "__main__":
    unittest.main()
