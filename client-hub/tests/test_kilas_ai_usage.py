"""Focused account quota, period, cost and pre-provider denial tests."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-ai-usage-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "kilas-ai-usage-test-only"
os.environ["KILAS_AI_ENABLED"] = "true"
os.environ["KILAS_AI_BURST_PER_MINUTE"] = "100"
os.environ.pop("DATABASE_URL", None)

import app  # noqa: E402
import db  # noqa: E402
import repo  # noqa: E402
from kilas_ai import providers, store, usage  # noqa: E402


class UsageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.app
        cls.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        cls.owner = repo.create_user("usage-owner@example.test", "hash")
        cls.other = repo.create_user("usage-other@example.test", "hash")
        cls.free = repo.create_user("usage-free@example.test", "hash")

    def client_for(self, owner):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=owner, role="CLIENT_OWNER", _csrf_token="usage-csrf")
        return client

    def test_free_chat_daily_and_period(self):
        owner = self.free
        thread_id = store.create_thread(owner)
        for index in range(10):
            key = "freefast_" + str(index).zfill(16)
            plan, operations = usage.reserve(owner, thread_id, key, "FAST", "CHAT")
            self.assertEqual(plan, "FREE")
            usage.finish(owner, key, operations, success=True, provider="openai", model="unknown-model",
                         usage={"input_tokens": 3, "output_tokens": 4})
        self.assertEqual(usage.snapshot(owner)["usage"]["Chat"]["used"], 10)
        with self.assertRaises(usage.UsageLimit):
            usage.reserve(owner, thread_id, "freefast_limit_012345", "FAST", "CHAT")
        plan, operations = usage.reserve(owner, thread_id, "freesearch_0123456789", "FAST", "WEB")
        self.assertEqual(operations, ("WEB_SEARCH",))
        usage.finish(owner, "freesearch_0123456789", operations, success=True)
        row = db.query_one("SELECT estimated_cost_usd FROM kilas_ai_usage WHERE user_id=? AND operation_key=?",
                           (owner, "freefast_" + str(0).zfill(16)))
        self.assertIsNone(row["estimated_cost_usd"])

    def test_paid_limits_expiry_and_unknown_cost(self):
        now = datetime.now(timezone.utc)
        start, end = (now - timedelta(days=1)).isoformat(), (now + timedelta(days=29)).isoformat()
        db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) "
                   "VALUES (?,?, 'ACTIVE',?,?)", (self.owner, "PLUS", start, end))
        self.assertEqual(usage.effective_plan(self.owner)["plan"], "PLUS")
        self.assertEqual(usage.PLANS["PLUS"]["CHAT"], 600)
        self.assertEqual(usage.PLANS["PLUS"]["WEB_SEARCH"], 15)
        self.assertEqual(usage.PLANS["PRO"]["CHAT"], 1500)
        self.assertEqual(usage.PLANS["MAX"]["WEB_SEARCH"], 80)
        self.assertIsNone(usage.estimate("unknown", 100, 100, "CHAT"))
        with patch.dict(os.environ, {"KILAS_AI_MODEL_PRICING_JSON": '{"priced":{"input_per_million_usd":1,"output_per_million_usd":2}}'}):
            self.assertEqual(usage.estimate("priced", 1000000, 1000000, "CHAT"), "3.000000")
        db.execute("UPDATE kilas_ai_subscriptions SET period_end=? WHERE user_id=?",
                   ((now - timedelta(hours=1)).isoformat(), self.owner))
        self.assertEqual(usage.effective_plan(self.owner)["plan"], "FREE")

    def test_client_model_request_cannot_override_auto_routing(self):
        client = self.client_for(self.other)
        thread_id = store.create_thread(self.other)
        events = iter([{"type": "provider", "provider": "openai", "model": "gpt-6-luna"},
                       {"type": "delta", "text": "Halo"}])
        with patch.object(providers, "stream", return_value=events) as streamed:
            response = client.post(f"/kilas-ai/threads/{thread_id}/send", json={
                "content": "Halo", "mode": "EXPERT", "operation_key": "expertdeny_0123456789"},
                headers={"X-CSRF-Token": "usage-csrf"})
            self.assertIn("Halo", response.get_data(as_text=True))
            self.assertEqual(streamed.call_args.args[0], "FAST")

    def test_paid_cost_guard_protects_premium_tools_but_keeps_fast_available(self):
        now = datetime.now(timezone.utc)
        db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PLUS','ACTIVE',?,?)",
                   (self.other, (now - timedelta(days=1)).isoformat(), (now + timedelta(days=29)).isoformat()))
        db.execute("INSERT INTO kilas_ai_usage(user_id,thread_id,operation_key,operation_type,mode,status,estimated_cost_usd,created_at) "
                   "VALUES (?,?,?,?,?,'COMPLETE',?,?)",
                   (self.other, store.create_thread(self.other), "prior_cost_0123456789", "CHAT", "SMART", "1.82", now.isoformat()))
        thread_id = store.create_thread(self.other)
        with self.assertRaises(usage.UsageLimit):
            usage.reserve(self.other, thread_id, "guard_smart_0123456789", "SMART", "CHAT")
        plan, operations = usage.reserve(self.other, thread_id, "guard_fast_0123456789", "FAST", "CHAT")
        self.assertEqual((plan, operations), ("PLUS", ("CHAT",)))
        usage.finish(self.other, "guard_fast_0123456789", operations, success=False)


if __name__ == "__main__":
    unittest.main()
