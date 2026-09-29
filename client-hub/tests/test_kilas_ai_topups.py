"""Focused Kuota Kilas payment, credit, fair-use, expiry and isolation contracts."""
import io
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-ai-topups-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "kilas-ai-topups-test-only"
os.environ["KILAS_AI_ENABLED"] = "true"
os.environ["KILAS_AI_BURST_PER_MINUTE"] = "1000"
os.environ["KILAS_AI_MAX_PER_HOUR"] = "2000"
os.environ.pop("DATABASE_URL", None)

import app  # noqa: E402
import db  # noqa: E402
import repo  # noqa: E402
from kilas_ai import store, topups, usage  # noqa: E402
from werkzeug.datastructures import FileStorage  # noqa: E402


class TopupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.app
        cls.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        cls.admin = repo.create_user("topup-admin@example.test", "hash", role="KILAS_ADMIN")

    def new_owner(self, label):
        return repo.create_user("topup-" + label + "@example.test", "hash")

    def client_for(self, owner, role="CLIENT_OWNER"):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=owner, role=role, _csrf_token="topup-csrf")
        return client

    def verified(self, owner, pack="MINI", when=None):
        order_id = topups.create_order(owner, pack)
        with patch("file_utils.validate_project_attachment_upload", return_value=("proof.png", "image/png")):
            topups.submit_proof(owner, order_id, FileStorage(stream=io.BytesIO(b"synthetic proof"),
                                filename="proof.png", content_type="image/png"))
        if when:
            with patch.object(usage, "_now", return_value=when):
                topups.review(order_id, self.admin, "VERIFIED")
        else:
            topups.review(order_id, self.admin, "VERIFIED")
        return order_id

    def seed_base(self, owner, thread_id, operation, count, mode="FAST"):
        now = usage._now().isoformat()
        for index in range(count):
            db.execute("INSERT INTO kilas_ai_usage(user_id,thread_id,operation_key,operation_type,mode,status,quota_source,estimated_cost_usd,created_at) "
                       "VALUES (?,?,?,?,?,'COMPLETE','BASE','0',?)",
                       (owner, thread_id, f"seed-{operation}-{thread_id}-{index}", operation, mode, now))

    def test_payment_gate_idempotency_owner_isolation_and_rejection(self):
        owner, other = self.new_owner("gate"), self.new_owner("gate-other")
        client, foreign = self.client_for(owner), self.client_for(other)
        order_id = topups.create_order(owner, "MINI")
        self.assertEqual(balance_percent(owner), 0)
        self.assertEqual(balance_percent(other), 0)
        self.assertEqual(foreign.get(f"/kilas-ai/topups/{order_id}").status_code, 404)
        self.assertEqual(client.get(f"/kilas-ai/topups/{order_id}").status_code, 200)
        self.assertEqual(balance_percent(owner), 0)
        with patch("file_utils.validate_project_attachment_upload", return_value=("proof.png", "image/png")):
            topups.submit_proof(owner, order_id, FileStorage(stream=io.BytesIO(b"synthetic proof"),
                                filename="proof.png", content_type="image/png"))
        self.assertEqual(balance_percent(owner), 0)
        with self.assertRaises(topups.TopupError):
            topups.review(order_id, other, "VERIFIED")
        topups.review(order_id, self.admin, "REJECTED")
        self.assertEqual(balance_percent(owner), 0)
        with patch("file_utils.validate_project_attachment_upload", return_value=("proof.png", "image/png")):
            topups.submit_proof(owner, order_id, FileStorage(stream=io.BytesIO(b"synthetic proof 2"),
                                filename="proof.png", content_type="image/png"))
        topups.review(order_id, self.admin, "VERIFIED")
        topups.review(order_id, self.admin, "VERIFIED")
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_ai_topup_credits WHERE order_id=?", (order_id,))["n"], 1)
        self.assertGreater(balance_percent(owner), 0)
        self.assertEqual(balance_percent(other), 0)
        self.assertEqual(len(invoice_numbers(owner)), 1)

    def test_base_counts_remain_and_topup_serves_chat_search_image_pdf(self):
        owner = self.new_owner("base")
        self.verified(owner)
        thread = store.create_thread(owner)
        self.seed_base(owner, thread, "CHAT", 10)
        self.seed_base(owner, thread, "WEB_SEARCH", 3)
        self.seed_base(owner, thread, "IMAGE_GENERATION", 2)
        self.seed_base(owner, thread, "PDF", 10)
        for tool, operation in (("CHAT", "CHAT"), ("WEB", "WEB_SEARCH"),
                                ("IMAGE_GENERATE", "IMAGE_GENERATION"), ("PDF", "PDF")):
            key = "topup-base-" + operation.lower() + "-0123456789"
            plan, operations = usage.reserve(owner, thread, key, "FAST", tool)
            self.assertEqual((plan, operations), ("FREE", (operation,)))
            self.assertEqual(db.query_one("SELECT quota_source FROM kilas_ai_usage WHERE user_id=? AND operation_key=?",
                                          (owner, key))["quota_source"], "TOPUP")
            usage.finish(owner, key, operations, success=True, provider="openai", model="gpt-6-luna",
                         usage={"input_tokens": 100, "output_tokens": 20})
        state = usage.snapshot(owner)
        self.assertEqual(state["usage"]["Chat"]["used"], 10)
        self.assertEqual(state["usage"]["Search"]["used"], 3)
        self.assertEqual(state["usage"]["Gambar"]["used"], 2)
        self.assertEqual(state["usage"]["PDF"]["used"], 10)
        self.assertTrue(state["creative_high"])
        self.assertLess(state["topup"]["percent"], 100)

    def test_image_fair_use_does_not_disable_base_chat_or_search(self):
        owner = self.new_owner("fair")
        thread = store.create_thread(owner)
        self.seed_base(owner, thread, "IMAGE_EDIT", 2)
        with self.assertRaises(usage.UsageLimit):
            usage.reserve(owner, thread, "fair-image-0123456789", "FAST", "IMAGE_GENERATE")
        for tool in ("CHAT", "WEB"):
            key = "fair-" + tool.lower() + "-0123456789"
            plan, operations = usage.reserve(owner, thread, key, "FAST", tool)
            self.assertEqual(plan, "FREE")
            self.assertEqual(db.query_one("SELECT quota_source FROM kilas_ai_usage WHERE operation_key=?", (key,))["quota_source"], "BASE")
            usage.finish(owner, key, operations, success=False)

    def test_topup_earliest_expiry_multiple_purchases_and_renewal(self):
        owner = self.new_owner("expiry")
        now = usage._now()
        first = self.verified(owner, "MINI", now)
        second = self.verified(owner, "EXTRA", now + timedelta(days=1))
        self.assertNotEqual(first, second)
        credits = db.query_all("SELECT id,total_micro,expires_at FROM kilas_ai_topup_credits WHERE user_id=? ORDER BY expires_at", (owner,))
        self.assertEqual(len(credits), 2)
        first_id, second_id = credits[0]["id"], credits[1]["id"]
        db.execute("INSERT INTO kilas_ai_topup_debits(credit_id,user_id,operation_key,operation_type,reserved_micro,charged_micro,status) "
                   "VALUES (?,?,?,?,?,?,'COMPLETE')", (first_id, owner, "prior-credit", "IMAGE_GENERATION",
                                                    credits[0]["total_micro"] - 30000, credits[0]["total_micro"] - 30000))
        thread = store.create_thread(owner)
        self.seed_base(owner, thread, "IMAGE_GENERATION", 2)
        key = "earliest-image-0123456789"
        _, operations = usage.reserve(owner, thread, key, "FAST", "IMAGE_GENERATE")
        debits = db.query_all("SELECT credit_id,reserved_micro FROM kilas_ai_topup_debits WHERE operation_key=? ORDER BY id", (key,))
        self.assertEqual([(item["credit_id"], item["reserved_micro"]) for item in debits],
                         [(first_id, 30000), (second_id, 50000)])
        usage.finish(owner, key, operations, success=True, provider="openai", model="gpt-image-2")
        before = topups.balance(owner)["percent"]
        start = now + timedelta(days=20)
        db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PLUS','ACTIVE',?,?)",
                   (owner, start.isoformat(), (start + timedelta(days=30)).isoformat()))
        self.assertEqual(topups.balance(owner)["percent"], before)
        with patch.object(usage, "_now", return_value=now + timedelta(days=90, hours=12)):
            self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_ai_topup_credits WHERE user_id=?", (owner,))["n"], 2)
            self.assertGreater(balance_percent(owner), 0)  # second purchase remains valid one extra day
        with patch.object(usage, "_now", return_value=now + timedelta(days=92)):
            self.assertEqual(balance_percent(owner), 0)

    def test_paid_premium_guard_uses_topup_but_keeps_economical_chat(self):
        owner = self.new_owner("guard")
        now = usage._now()
        thread = store.create_thread(owner)
        db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PLUS','ACTIVE',?,?)",
                   (owner, (now - timedelta(days=1)).isoformat(), (now + timedelta(days=29)).isoformat()))
        db.execute("INSERT INTO kilas_ai_usage(user_id,thread_id,operation_key,operation_type,mode,status,estimated_cost_usd,created_at) "
                   "VALUES (?,?,?,?,?,'COMPLETE',?,?)", (owner, thread, "cost-prior", "CHAT", "SMART", "1.43", now.isoformat()))
        _, fast = usage.reserve(owner, thread, "guard-fast-0123456789", "FAST", "CHAT")
        self.assertEqual(db.query_one("SELECT quota_source FROM kilas_ai_usage WHERE operation_key='guard-fast-0123456789'")["quota_source"], "BASE")
        usage.finish(owner, "guard-fast-0123456789", fast, success=False)
        with self.assertRaises(usage.UsageLimit):
            usage.reserve(owner, thread, "guard-image-no-credit", "FAST", "IMAGE_GENERATE")
        self.verified(owner)
        _, image = usage.reserve(owner, thread, "guard-image-with-credit", "FAST", "IMAGE_GENERATE")
        self.assertEqual(db.query_one("SELECT quota_source FROM kilas_ai_usage WHERE operation_key='guard-image-with-credit'")["quota_source"], "TOPUP")
        usage.finish(owner, "guard-image-with-credit", image, success=False)


def balance_percent(owner):
    return topups.balance(owner)["percent"]


def invoice_numbers(owner):
    return [item["invoice_number"] for item in topups.owner_orders(owner)]


if __name__ == "__main__":
    unittest.main()
