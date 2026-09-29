"""Focused Work trial, billing, account isolation and route contracts."""
import io
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-work-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "kilas-work-test-only"
os.environ["KILAS_WORK_ENABLED"] = "true"
os.environ.pop("DATABASE_URL", None)

import app  # noqa: E402
import db  # noqa: E402
import repo  # noqa: E402
from kilas_work import artifacts, billing, engine, quota, store  # noqa: E402
from werkzeug.datastructures import FileStorage  # noqa: E402


class WorkFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.app
        cls.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        cls.admin = repo.create_user("work-admin@example.test", "hash", role="KILAS_ADMIN")

    def owner(self, name):
        return repo.create_user("work-" + name + "@example.test", "hash")

    def client(self, user_id, role="CLIENT_OWNER"):
        client = self.app.test_client()
        with client.session_transaction() as state:
            state.update(user_id=user_id, role=role, _csrf_token="work-csrf")
        return client

    def proof(self, user_id, order_id):
        with patch("file_utils.validate_project_attachment_upload", return_value=("proof.png", "image/png")):
            billing.submit_proof(user_id, order_id, FileStorage(stream=io.BytesIO(b"synthetic proof"),
                                 filename="proof.png", content_type="image/png"))

    def test_launch_catalog_is_affordable_and_bounded(self):
        self.assertEqual(quota.PLANS, {"PLUS": 29000, "PRO": 69000, "MAX": 129000})
        self.assertEqual(quota.TOPUPS, {"MINI": 29000, "EXTRA": 59000, "POWER": 99000})
        self.assertEqual(quota._trial_micro(), 300000)
        self.assertLessEqual(quota.FORECAST_MICRO["BROWSER"] * 3, quota._trial_micro())
        self.assertGreater(quota.FORECAST_MICRO["BROWSER"] * 4, quota._trial_micro())

    def test_trial_once_isolated_and_exhausts_without_reset(self):
        owner, other = self.owner("trial"), self.owner("other")
        thread = store.create_thread(owner, "Test")
        state = quota.snapshot(owner)
        self.assertEqual(state["trial_label"], "Masih tersedia")
        for index in range(60):
            key = "trial-" + str(index)
            quota.reserve(owner, thread, key, "CHAT")
            quota.finish(owner, key, success=True, actual_micro=5000)
        self.assertFalse(quota.snapshot(owner)["trial_available"])
        with self.assertRaises(quota.QuotaError):
            quota.reserve(owner, thread, "trial-exhausted", "CHAT")
        quota.ensure_account(owner)
        self.assertFalse(quota.snapshot(owner)["trial_available"])
        self.assertTrue(quota.snapshot(other)["trial_available"])
        self.assertEqual(self.client(other).get(f"/kilas-work/threads/{thread}").status_code, 404)

    def test_verified_plan_and_topup_only_no_double_credit(self):
        owner = self.owner("billing")
        topup = billing.create_order(owner, "TOPUP", "MINI")
        self.assertFalse(quota.snapshot(owner)["topup_available"])
        self.proof(owner, topup)
        self.assertFalse(quota.snapshot(owner)["topup_available"])
        with self.assertRaises(billing.BillingError):
            billing.review(topup, owner, "VERIFIED")
        billing.review(topup, self.admin, "VERIFIED")
        self.assertFalse(billing.review(topup, self.admin, "VERIFIED"))
        self.assertTrue(quota.snapshot(owner)["topup_available"])
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_work_credits WHERE order_id=?", (topup,))["n"], 1)
        plan = billing.create_order(owner, "PLAN", "PLUS")
        self.proof(owner, plan)
        billing.review(plan, self.admin, "REJECTED")
        self.assertIsNone(quota.snapshot(owner)["plan"])
        self.proof(owner, plan)
        billing.review(plan, self.admin, "VERIFIED")
        self.assertEqual(quota.snapshot(owner)["plan"], "PLUS")
        self.assertTrue(quota.snapshot(owner)["topup_available"])

    def test_topup_earliest_expiry_and_account_owned_download(self):
        owner, other = self.owner("credits"), self.owner("credits-other")
        first = billing.create_order(owner, "TOPUP", "MINI")
        self.proof(owner, first)
        billing.review(first, self.admin, "VERIFIED")
        second = billing.create_order(owner, "TOPUP", "EXTRA")
        self.proof(owner, second)
        billing.review(second, self.admin, "VERIFIED")
        credits = db.query_all("SELECT id,total_micro,expires_at FROM kilas_work_credits WHERE user_id=? ORDER BY id", (owner,))
        self.assertEqual(len(credits), 2)
        thread = store.create_thread(owner, "Private")
        message = store.add_message(owner, thread, "assistant", "A file")
        file_id = store.add_file(owner, thread, message, {"filename": "report.txt", "mime_type": "text/plain",
                                                         "content": b"private", "extracted_text": "private"})
        self.assertEqual(self.client(owner).get(f"/kilas-work/threads/{thread}/files/{file_id}").status_code, 200)
        self.assertEqual(self.client(other).get(f"/kilas-work/threads/{thread}/files/{file_id}").status_code, 404)
        db.execute("UPDATE kilas_work_credits SET expires_at=? WHERE id=?",
                   ((quota.now() - timedelta(days=1)).isoformat(), credits[0]["id"]))
        self.assertTrue(quota.snapshot(owner)["topup_available"])
        self.assertEqual(quota.snapshot(owner)["topup_percent"], 100)

    def test_natural_routing_defaults_economically(self):
        self.assertEqual(engine.route("Tolong ringkas catatan ini"), ("CHAT", "gpt-6-luna"))
        self.assertEqual(engine.route("Buat PDF laporan ini"), ("PDF", "gpt-6-luna"))
        self.assertEqual(engine.route("Riset mendalam beberapa situs"), ("WEB", "gpt-6-sol"))
        self.assertEqual(engine.route("Buka website contoh.com dan klik menu"), ("BROWSER", "gpt-6-luna"))

    def test_topup_consumes_earliest_expiry_and_survives_renewal(self):
        owner = self.owner("fifo")
        first = billing.create_order(owner, "TOPUP", "MINI")
        self.proof(owner, first)
        billing.review(first, self.admin, "VERIFIED")
        second = billing.create_order(owner, "TOPUP", "EXTRA")
        self.proof(owner, second)
        billing.review(second, self.admin, "VERIFIED")
        credits = db.query_all("SELECT id,total_micro FROM kilas_work_credits WHERE user_id=? ORDER BY id", (owner,))
        db.execute("UPDATE kilas_work_credits SET expires_at=? WHERE id=?",
                   ((quota.now() + timedelta(days=40)).isoformat(), credits[0]["id"]))
        db.execute("UPDATE kilas_work_credits SET expires_at=? WHERE id=?",
                   ((quota.now() + timedelta(days=70)).isoformat(), credits[1]["id"]))
        db.execute("INSERT INTO kilas_work_topup_debits(user_id,credit_id,operation_key,reserved_micro,"
                   "charged_micro,status) VALUES (?,?,?,?,?,'COMPLETE')",
                   (owner, credits[0]["id"], "prior", credits[0]["total_micro"] - 30000,
                    credits[0]["total_micro"] - 30000))
        thread = store.create_thread(owner, "FIFO")
        quota.ensure_account(owner)
        db.execute("UPDATE kilas_work_accounts SET trial_total_micro=10000 WHERE user_id=?", (owner,))
        for index in range(2):
            key = "fifo-" + str(index)
            quota.reserve(owner, thread, key, "CHAT")
            quota.finish(owner, key, success=True, actual_micro=5000)
        quota.reserve(owner, thread, "fifo-image", "IMAGE")
        debits = db.query_all("SELECT credit_id,reserved_micro FROM kilas_work_topup_debits "
                              "WHERE operation_key='fifo-image' ORDER BY id")
        self.assertEqual([(row["credit_id"], row["reserved_micro"]) for row in debits],
                         [(credits[0]["id"], 30000), (credits[1]["id"], 50000)])
        quota.finish(owner, "fifo-image", success=True, actual_micro=70000)
        self.assertFalse(quota.finish(owner, "fifo-image", success=True, actual_micro=70000))
        before = quota.snapshot(owner)["topup_percent"]
        plan = billing.create_order(owner, "PLAN", "PLUS")
        self.proof(owner, plan)
        billing.review(plan, self.admin, "VERIFIED")
        self.assertEqual(quota.snapshot(owner)["topup_percent"], before)
        with patch.object(quota, "now", return_value=quota.now() + timedelta(days=91)):
            self.assertFalse(quota.snapshot(owner)["topup_available"])

    def test_variable_cost_is_not_flat(self):
        cheap = quota.estimate_micro("gpt-6-luna", 1000, 300)
        strong = quota.estimate_micro("gpt-6-sol", 1000, 300)
        researched = quota.estimate_micro("gpt-6-luna", 1000, 300, web_calls=2)
        self.assertLess(cheap, strong)
        self.assertLess(cheap, researched)
        self.assertIsNone(quota.estimate_micro("unknown-model", 1000, 300))

    def test_explicit_code_file_becomes_account_owned_artifact(self):
        owner, other = self.owner("code-file"), self.owner("code-file-other")
        thread = store.create_thread(owner, "Code")
        message = store.add_message(owner, thread, "assistant", "Code ready")
        result = artifacts.from_answer("Buat file laporan.py", "```python\nprint('Kilas')\n```")
        self.assertEqual(result["filename"], "laporan.py")
        file_id = store.add_file(owner, thread, message, result)
        self.assertIsNone(store.file(other, thread, file_id))
        self.assertEqual(store.file(owner, thread, file_id)["content"], b"print('Kilas')")
        other_thread = store.create_thread(other, "Other")
        with self.assertRaises(ValueError):
            store.add_file(other, other_thread, message, result)
        self.assertIsNone(artifacts.from_answer("Jelaskan Python", "print('Kilas')"))


if __name__ == "__main__":
    unittest.main()