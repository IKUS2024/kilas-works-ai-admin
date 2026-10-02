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
        before = len(store.list_threads(self.a))
        empty = a.get("/kilas-ai")
        self.assertIn("Apa yang ingin kamu lakukan?", empty.text)
        self.assertIn("Tanya sesuatu, cari informasi, atau bahas lampiranmu.", empty.text)
        fresh = a.post("/kilas-ai/threads", data={"mode": "FAST", "csrf_token": "chat-csrf"})
        self.assertEqual(fresh.status_code, 303)
        self.assertEqual(fresh.location, "/kilas-ai")
        self.assertEqual(len(store.list_threads(self.a)), before)
        self.assertEqual(a.post("/kilas-ai/threads", json={"mode": "FAST"},
                                headers={"X-CSRF-Token": "chat-csrf"}).status_code, 400)
        created = a.post("/kilas-ai/threads", json={"mode": "FAST", "first_message": "Halo"},
                         headers={"X-CSRF-Token": "chat-csrf"})
        self.assertEqual(created.status_code, 201)
        thread_id = created.json["thread_id"]
        self.assertEqual(len(store.list_threads(self.a)), before + 1)
        self.assertEqual(store.thread(self.a, thread_id)["selected_mode"], "FAST")
        self.assertIn("Apa yang ingin kamu lakukan?", a.get(created.json["url"]).text)
        self.assertEqual(b.get(created.json["url"]).status_code, 404)
        self.assertEqual(b.post(created.json["url"] + "/rename", data={"title": "stolen", "csrf_token": "chat-csrf"}).status_code, 404)
        self.assertEqual(b.post(created.json["url"] + "/delete", data={"csrf_token": "chat-csrf"}).status_code, 404)
        self.assertEqual(a.post(created.json["url"] + "/rename", data={"title": "Research", "csrf_token": "chat-csrf"}).status_code, 303)
        self.assertIn("Apa yang ingin kamu lakukan?", a.get(created.json["url"]).text)
        self.assertEqual(a.post(created.json["url"] + "/delete", data={"csrf_token": "chat-csrf"}).status_code, 303)
        self.assertEqual(a.get(created.json["url"]).status_code, 404)

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
            streamed = response.get_data(as_text=True)
            self.assertIn("mari mulai", streamed)
            self.assertIn("event: activity", streamed)
            self.assertNotIn("chain-of-thought", streamed)
        rows = store.messages(self.a, thread_id)
        self.assertEqual([row["role"] for row in rows], ["user", "assistant"])
        self.assertEqual(rows[1]["content"], "Tentu, mari mulai.")
        self.assertEqual(store.thread(self.a, thread_id)["title"], "Halo, bantu tulis ide.")
        with patch.object(providers, "stream", side_effect=AssertionError("duplicate provider call")):
            duplicate = client.post(f"/kilas-ai/threads/{thread_id}/send", json=payload,
                                    headers={"X-CSRF-Token": "chat-csrf"})
            self.assertIn("cached", duplicate.get_data(as_text=True))
        self.assertEqual(len(store.messages(self.a, thread_id)), 2)

    def test_luna_failure_never_promotes_to_expensive_fallback(self):
        with patch.dict(os.environ,{"OPENAI_API_KEY":"test","ANTHROPIC_API_KEY":"test","KILAS_AI_OPENAI_SMART_MODEL":"gpt-6-sol","KILAS_AI_ANTHROPIC_SMART_MODEL":"claude-sonnet-5"}),patch.object(providers,"_openai",side_effect=providers.ProviderError("failed")),patch.object(providers,"_anthropic") as expensive:
            with self.assertRaises(providers.ProviderError):
                list(providers.stream("SMART",[{"role":"user","content":"hello"}]))
            expensive.assert_not_called()

    def test_routing_rejects_old_models_and_expensive_fast_fallback(self):
        with patch.dict(os.environ,{"OPENAI_API_KEY":"test","ANTHROPIC_API_KEY":"test","KILAS_AI_OPENAI_SMART_MODEL":"gpt-6-sol"}):
            for mode in ("FAST","SMART","EXPERT"):
                self.assertEqual([(p,m) for p,m,_ in providers.candidates(mode)],[("openai","gpt-6-luna")])
            with patch.dict(os.environ,{"KILAS_AI_CHAT_MODEL":"gpt-6.1-sol"}):
                with self.assertRaises(providers.ProviderError):
                    list(providers.candidates("FAST"))

    def test_provider_requests_set_real_reasoning_controls(self):
        class EmptyResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def raise_for_status(self):
                pass

            def iter_lines(self, **_):
                return iter(())

        messages = [{"role": "user", "content": "Analyze this"}]
        with patch.object(providers.requests, "post", return_value=EmptyResponse()) as post:
            list(providers._openai("gpt-6-luna", "test", messages, "FAST"))
            self.assertEqual(post.call_args.kwargs["json"]["reasoning_effort"], "medium")
            list(providers._openai("gpt-6-sol", "test", messages, "SMART"))
            self.assertEqual(post.call_args.kwargs["json"]["reasoning_effort"], "medium")
            list(providers._openai("gpt-6-sol", "test", messages, "EXPERT"))
            self.assertEqual(post.call_args.kwargs["json"]["reasoning_effort"], "medium")
            list(providers._anthropic("claude-sonnet-5", "test", messages, "SMART"))
            self.assertEqual(post.call_args.kwargs["json"]["thinking"], {"type": "adaptive"})
            self.assertEqual(post.call_args.kwargs["json"]["output_config"], {"effort": "medium"})

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
