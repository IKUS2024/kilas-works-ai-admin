"""Focused Kilas AI chat persistence, stream and provider fallback tests."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-ai-chat-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "kilas-ai-chat-test-only"
os.environ["KILAS_AI_ENABLED"] = "true"
os.environ.pop("DATABASE_URL", None)

import app  # noqa: E402
import db  # noqa: E402
import repo  # noqa: E402
from kilas_ai import providers, store  # noqa: E402


class ChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.app
        cls.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        cls.a = repo.create_user("chat-a@example.test", "hash")
        cls.b = repo.create_user("chat-b@example.test", "hash")

    def client_for(self, owner):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=owner, role="CLIENT_OWNER", _csrf_token="chat-csrf")
        return client

    def test_thread_actions_and_foreign_probe(self):
        a = self.client_for(self.a)
        b = self.client_for(self.b)
        created = a.post("/kilas-ai/threads", data={"mode": "FAST", "csrf_token": "chat-csrf"})
        self.assertEqual(created.status_code, 303)
        thread_id = int(created.location.rsplit("/", 1)[-1])
        self.assertEqual(store.thread(self.a, thread_id)["selected_mode"], "FAST")
        self.assertEqual(b.get(created.location).status_code, 404)
        self.assertEqual(b.post(created.location + "/rename", data={"title": "stolen", "csrf_token": "chat-csrf"}).status_code, 404)
        self.assertEqual(b.post(created.location + "/delete", data={"csrf_token": "chat-csrf"}).status_code, 404)
        self.assertEqual(a.post(created.location + "/rename", data={"title": "Research", "csrf_token": "chat-csrf"}).status_code, 303)
        self.assertIn("Research", a.get(created.location).text)
        self.assertEqual(a.post(created.location + "/delete", data={"csrf_token": "chat-csrf"}).status_code, 303)
        self.assertEqual(a.get(created.location).status_code, 404)

    def test_stream_persists_once_and_duplicate_send_is_cached(self):
        client = self.client_for(self.a)
        thread_id = store.create_thread(self.a)
        key = "chatop_0123456789abcdef"
        payload = {"content": "Halo, bantu tulis ide.", "mode": "SMART", "operation_key": key}
        events = iter([{"type": "provider", "provider": "openai", "model": "configured-model"},
                       {"type": "delta", "text": "Tentu, "}, {"type": "delta", "text": "mari mulai."},
                       {"type": "usage", "input_tokens": 11, "output_tokens": 7},
                       {"type": "finish", "reason": "stop"}])
        with patch.object(providers, "stream", return_value=events):
            response = client.post(f"/kilas-ai/threads/{thread_id}/send", json=payload,
                                   headers={"X-CSRF-Token": "chat-csrf"})
            self.assertEqual(response.status_code, 200)
            self.assertIn("mari mulai", response.get_data(as_text=True))
        rows = store.messages(self.a, thread_id)
        self.assertEqual([row["role"] for row in rows], ["user", "assistant"])
        self.assertEqual(rows[1]["content"], "Tentu, mari mulai.")
        self.assertEqual(store.thread(self.a, thread_id)["title"], "Halo, bantu tulis ide.")
        with patch.object(providers, "stream", side_effect=AssertionError("duplicate provider call")):
            duplicate = client.post(f"/kilas-ai/threads/{thread_id}/send", json=payload,
                                    headers={"X-CSRF-Token": "chat-csrf"})
            self.assertIn("cached", duplicate.get_data(as_text=True))
        self.assertEqual(len(store.messages(self.a, thread_id)), 2)

    def test_provider_fallback_and_both_fail(self):
        with patch.dict(os.environ, {"KILAS_AI_SMART_PRIMARY": "openai", "KILAS_AI_OPENAI_SMART_MODEL": "gpt-6-sol",
                                     "KILAS_AI_ANTHROPIC_SMART_MODEL": "claude-sonnet-5", "OPENAI_API_KEY": "test",
                                     "ANTHROPIC_API_KEY": "test"}):
            def broken(*_):
                raise providers.ProviderError("failed")
                yield
            with patch.object(providers, "_openai", broken), patch.object(providers, "_anthropic", return_value=iter([
                {"type": "delta", "text": "Fallback works"}, {"type": "finish", "reason": "end_turn"}])):
                events = list(providers.stream("SMART", [{"role": "user", "content": "hello"}]))
            self.assertEqual("".join(event["text"] for event in events if event["type"] == "delta"), "Fallback works")
            with patch.object(providers, "_openai", broken), patch.object(providers, "_anthropic", broken):
                with self.assertRaises(providers.ProviderError):
                    list(providers.stream("SMART", [{"role": "user", "content": "hello"}]))

    def test_routing_rejects_old_models_and_expensive_fast_fallback(self):
        with patch.dict(os.environ, {"KILAS_AI_FAST_PRIMARY": "openai", "KILAS_AI_OPENAI_FAST_MODEL": "gpt-6-luna",
                                     "KILAS_AI_ANTHROPIC_FAST_MODEL": "claude-haiku-4-5-20251001",
                                     "KILAS_AI_OPENAI_SMART_MODEL": "gpt-6-sol", "KILAS_AI_ANTHROPIC_SMART_MODEL": "claude-sonnet-5",
                                     "KILAS_AI_OPENAI_EXPERT_MODEL": "gpt-6-sol", "KILAS_AI_ANTHROPIC_EXPERT_MODEL": "claude-sonnet-5",
                                     "OPENAI_API_KEY": "test", "ANTHROPIC_API_KEY": "test"}):
            self.assertEqual([(p, m) for p, m, _ in providers.candidates("FAST")], [("openai", "gpt-6-luna")])
            self.assertEqual([m for _, m, _ in providers.candidates("SMART")], ["gpt-6-sol", "claude-sonnet-5"])
            self.assertEqual([m for _, m, _ in providers.candidates("EXPERT")], ["gpt-6-sol", "claude-sonnet-5"])
            with patch.dict(os.environ, {"KILAS_AI_OPENAI_FAST_MODEL": "gpt-4.1-mini", "KILAS_AI_OPENAI_SMART_MODEL": "gpt-4.1"}):
                self.assertEqual(list(providers.candidates("FAST")), [])
                self.assertEqual([m for _, m, _ in providers.candidates("SMART")], ["claude-sonnet-5"])

    def test_csrf_and_bounds(self):
        client = self.client_for(self.a)
        thread_id = store.create_thread(self.a)
        path = f"/kilas-ai/threads/{thread_id}/send"
        self.assertEqual(client.post(path, json={"content": "hi", "operation_key": "valid_1234567890123456"}).status_code, 400)
        self.assertEqual(client.post(path, json={"content": "x" * 12001, "operation_key": "valid_1234567890123456"},
                                     headers={"X-CSRF-Token": "chat-csrf"}).status_code, 400)
        self.assertEqual(self.client_for(self.b).post(path, json={"content": "hi", "operation_key": "valid_1234567890123456"},
                                                    headers={"X-CSRF-Token": "chat-csrf"}).status_code, 404)

    def test_share_read_only_and_revoke(self):
        owner = self.client_for(self.a)
        public = self.app.test_client()
        thread_id = store.create_thread(self.a)
        store.append_user_once(self.a, thread_id, "Safe shared text", "FAST", "share_0123456789abcdef")
        response = owner.post(f"/kilas-ai/threads/{thread_id}/share", data={"csrf_token": "chat-csrf"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("chat-a@example.test", response.text)
        token = response.text.split("/kilas-ai/shared/", 1)[1].split('"', 1)[0]
        link = "/kilas-ai/shared/" + token
        shared = public.get(link)
        self.assertEqual(shared.status_code, 200)
        self.assertIn("Safe shared text", shared.text)
        self.assertNotIn("chat-a@example.test", shared.text)
        self.assertEqual(public.get("/kilas-ai/shared/random-token").status_code, 404)
        self.assertEqual(self.client_for(self.b).post(f"/kilas-ai/threads/{thread_id}/revoke", data={"csrf_token": "chat-csrf"}).status_code, 404)
        self.assertEqual(owner.post(f"/kilas-ai/threads/{thread_id}/revoke", data={"csrf_token": "chat-csrf"}).status_code, 303)
        self.assertEqual(public.get(link).status_code, 404)

    def test_regenerate_reuses_original_user_message(self):
        client = self.client_for(self.a)
        thread_id = store.create_thread(self.a)
        store.append_user_once(self.a, thread_id, "Explain this", "SMART", "original_0123456789abcdef")
        key = "regenerate_0123456789abcdef"
        events = iter([{"type": "provider", "provider": "anthropic", "model": "configured"},
                       {"type": "delta", "text": "A new answer"}, {"type": "finish", "reason": "end_turn"}])
        with patch.object(providers, "stream", return_value=events):
            response = client.post(f"/kilas-ai/threads/{thread_id}/regenerate",
                json={"mode": "SMART", "operation_key": key}, headers={"X-CSRF-Token": "chat-csrf"})
            self.assertIn("A new answer", response.get_data(as_text=True))
        rows = store.messages(self.a, thread_id)
        self.assertEqual([row["role"] for row in rows], ["user", "assistant"])
        self.assertEqual(rows[1]["content"], "A new answer")
        with patch.object(providers, "stream", side_effect=AssertionError("duplicate regeneration")):
            repeat = client.post(f"/kilas-ai/threads/{thread_id}/regenerate",
                json={"mode": "SMART", "operation_key": key}, headers={"X-CSRF-Token": "chat-csrf"})
            self.assertIn("cached", repeat.get_data(as_text=True))
        self.assertEqual(len(store.messages(self.a, thread_id)), 2)


if __name__ == "__main__":
    unittest.main()
