"""Focused real-source parsing, image persistence and share isolation checks."""
import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-ai-tools-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "kilas-ai-tools-test-only"
os.environ["KILAS_AI_ENABLED"] = "true"
os.environ.pop("DATABASE_URL", None)

from PIL import Image  # noqa: E402
import app  # noqa: E402
import repo  # noqa: E402
from kilas_ai import providers, routing, store, tools, usage  # noqa: E402
import db  # noqa: E402


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def web_result(urls, answer="Supported finding."):
    return FakeResponse({"output": [{"type": "web_search_call", "status": "completed"},
        {"type": "message", "content": [{"type": "output_text", "text": answer,
            "annotations": [{"type": "url_citation", "url": url, "title": "Actual source"} for url in urls]}]}],
        "usage": {"input_tokens": 20, "output_tokens": 30}})


def image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 128, 30)).save(output, "PNG")
    return output.getvalue()


class ToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.app
        cls.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        cls.owner = repo.create_user("tool-owner@example.test", "hash")
        cls.foreign = repo.create_user("tool-foreign@example.test", "hash")

    def client_for(self, owner):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=owner, role="CLIENT_OWNER", _csrf_token="tool-csrf")
        return client

    def test_logo_creation_routes_to_real_image_tool_not_chat_svg(self):
        self.assertEqual(routing.tool_for("buat logo bagus buat kilas works"), "IMAGE_GENERATE")
        self.assertEqual(routing.tool_for("create a clean wordmark for Kilas Works"), "IMAGE_GENERATE")
        self.assertEqual(routing.tool_for("buat kode SVG logo Kilas Works"), "CHAT")
        prompt = routing.enhance_image_prompt("buat logo bagus buat Kilas Works", "buat logo bagus buat Kilas Works")
        self.assertIn("bukan kode SVG/HTML", prompt)

    def test_web_uses_only_returned_sources(self):
        data = {"output": [{"type": "web_search_call", "status": "completed"},
                           {"type": "message", "content": [{"type": "output_text", "text": "Current fact",
                               "annotations": [{"type": "url_citation", "url": "https://example.org/source", "title": "Example source"}]}]}],
                "usage": {"input_tokens": 12, "output_tokens": 8}}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test", "KILAS_AI_OPENAI_WEB_MODEL": "configured-web"}), \
             patch.object(tools.requests, "post", return_value=FakeResponse(data)) as post:
            answer = tools.web_search([{"role": "user", "content": "Find current fact"}])
            self.assertEqual(post.call_args.kwargs["json"]["tool_choice"], "required")
            self.assertEqual(post.call_args.kwargs["json"]["max_output_tokens"], 2048)
            self.assertEqual(post.call_args.kwargs["json"]["max_tool_calls"], 1)
            self.assertEqual(answer["citations"], [{"url": "https://example.org/source", "title": "Example source"}])
            data["output"][1]["content"][0]["annotations"] = []
            with self.assertRaises(tools.ToolUnavailable):
                tools.web_search([{"role": "user", "content": "Find current fact"}])

    def test_simple_search_uses_one_luna_call_and_real_sources(self):
        for question in ("harga emas hari ini", "siapa CEO X sekarang"):
            with self.subTest(question=question), \
                 patch.dict(os.environ, {"OPENAI_API_KEY": "test", "KILAS_AI_OPENAI_WEB_MODEL": "gpt-6-luna"}), \
                 patch.object(tools.requests, "post", return_value=web_result(["https://example.org/current"])) as post:
                result = tools.web_search([{"role": "user", "content": question}], mode="SMART", plan="MAX")
                self.assertEqual(result["search_calls"], 1)
                self.assertEqual(result["citations"][0]["url"], "https://example.org/current")
                self.assertEqual(result["model"], "gpt-6-luna")
                self.assertEqual(post.call_count, 1)
                self.assertEqual(post.call_args.kwargs["json"]["max_tool_calls"], 1)

    def test_research_uses_bounded_distinct_queries_and_cited_sol_synthesis(self):
        question = "Bandingkan tiga kompetitor AI berdasarkan harga, fitur dan target pasar dari beberapa sumber."
        first = web_result(["https://brand.example/pricing?utm_source=search"], "Harga resmi tersedia.")
        second = web_result(["https://brand.example/pricing", "https://journal.example/review",
                             "https://other.example/features"], "Temuan pembanding. " * 22)
        synthesis = FakeResponse({"output": [{"type": "message", "content": [
            {"type": "output_text", "text": "Harga dari sumber resmi [1]. Ulasan independen berbeda [2]."}]}],
            "usage": {"input_tokens": 50, "output_tokens": 40}})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test", "KILAS_AI_OPENAI_WEB_MODEL": "gpt-6-luna",
                                  "KILAS_AI_OPENAI_SMART_MODEL": "gpt-6-sol"}), \
             patch.object(tools.requests, "post", side_effect=[first, second, synthesis]) as post:
            result = tools.web_search([{"role": "user", "content": question}], plan="PRO")
        self.assertEqual(result["search_calls"], 2)
        self.assertEqual(result["model"], "gpt-6-luna")
        self.assertIn("[1]", result["text"])
        self.assertEqual(len(result["citations"]), 3)
        self.assertEqual(post.call_args_list[0].kwargs["json"]["model"], "gpt-6-luna")
        self.assertNotEqual(post.call_args_list[0].kwargs["json"]["input"], post.call_args_list[1].kwargs["json"]["input"])
        self.assertEqual(post.call_args_list[2].kwargs["json"]["reasoning"], {"effort": "medium"})
        self.assertNotIn("tools", post.call_args_list[2].kwargs["json"])

    def test_research_plan_caps_and_early_stop(self):
        question = "Riset kompetitor AI untuk UMKM Indonesia dari beberapa sumber."
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test", "KILAS_AI_OPENAI_WEB_MODEL": "gpt-6-luna"}):
            for plan, cap in (("FREE", 1), ("PLUS", 5), ("PRO", 5), ("MAX", 5)):
                hits = []
                def search(*args, **kwargs):
                    hits.append(kwargs["json"])
                    return web_result([f"https://source{len(hits)}.example/fact"], "One fact.")
                with self.subTest(plan=plan), patch.object(tools.requests, "post", side_effect=search), \
                     patch.object(tools, "_synthesize_research", return_value=("Answer [1].", "gpt-6-sol", {})):
                    result = tools.web_search([{"role": "user", "content": question}], plan=plan)
                    self.assertEqual(result["search_calls"], cap)
                    self.assertEqual(len(hits), cap)
            with patch.object(tools.requests, "post", return_value=web_result(
                    ["https://one.example/a", "https://two.example/b", "https://three.example/c"],
                    "Well-supported comparison. " * 20)) as post:
                result = tools.web_search([{"role": "user", "content": question}], plan="MAX")
                self.assertEqual(result["search_calls"], 1)
                self.assertEqual(post.call_count, 1)

    def test_research_partial_failure_and_all_failure(self):
        context = [{"role": "user", "content": "riset pasar dari beberapa sumber"}]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test", "KILAS_AI_OPENAI_WEB_MODEL": "gpt-6-luna"}), \
             patch.object(tools.requests, "post", side_effect=[web_result(["https://one.example/a"]),
                tools.requests.RequestException(), tools.requests.RequestException()]):
            result = tools.web_search(context, plan="PLUS", max_calls=3)
            self.assertEqual(result["citations"][0]["url"], "https://one.example/a")
            self.assertEqual(result["search_calls"], 3)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test", "KILAS_AI_OPENAI_WEB_MODEL": "gpt-6-luna"}), \
             patch.object(tools.requests, "post", side_effect=tools.requests.RequestException()):
            with self.assertRaises(tools.ToolUnavailable):
                tools.web_search(context, plan="PLUS")

    def test_research_uses_bounded_prior_text_and_one_quota_row(self):
        owner = repo.create_user("tool-research-owner@example.test", "hash")
        client = self.client_for(owner)
        thread_id = store.create_thread(owner)
        store.append_user_once(owner, thread_id, "Bandingkan Halo AI dan Cekat AI", "FAST", "researchcontext_0123456789")
        store.append_assistant(owner, thread_id, "Halo AI dan Cekat AI adalah dua platform.", "FAST",
                               "openai", "gpt-6-luna", "researchcontext_0123456789", {"status": "complete"})
        context = [{"role": "user", "content": "Bandingkan Halo AI dan Cekat AI"},
                   {"role": "assistant", "content": "Keduanya platform AI."},
                   {"role": "user", "content": "sekarang cari harga terbaru keduanya dari beberapa sumber"}]
        self.assertIn("Halo AI", tools._search_text(context))
        self.assertTrue(tools.research_requested(context))
        document_context = [{"role": "user", "content": "cek apakah aturan ini masih berlaku\n\nTeks berikut berhasil diekstrak dari lampiran 'aturan.pdf'.\n<isi_lampiran>\n" + "isi dokumen " * 2000}]
        self.assertIn("cek apakah aturan ini masih berlaku", tools._search_text(document_context))
        self.assertFalse(tools.research_requested(document_context))
        result = {"text": "Harga terbaru dari sumber [1].", "citations": [{"url": "https://example.org/price", "title": "Price"}],
                  "model": "gpt-6-sol", "search_calls": 3, "research": True,
                  "usage": {"input_tokens": 100, "output_tokens": 80, "web_search_calls": 3}}
        with patch.object(tools, "web_search_steps", return_value=[{"result": result}]) as search, \
             patch.object(providers, "stream", side_effect=AssertionError("normal chat must not run")):
            response = client.post(f"/kilas-ai/threads/{thread_id}/send", json={
                "content": "sekarang cari harga terbaru keduanya dari beberapa sumber", "search": True,
                "operation_key": "researchsend_0123456789abcdef"}, headers={"X-CSRF-Token": "tool-csrf"})
            self.assertIn("event: sources", response.get_data(as_text=True))
        self.assertIn("Halo AI", search.call_args.args[0][0]["content"])
        self.assertEqual(search.call_args.kwargs["max_calls"], 1)
        rows = db.query_all("SELECT operation_type,status FROM kilas_ai_usage WHERE thread_id=?", (thread_id,))
        self.assertEqual([(row["operation_type"], row["status"]) for row in rows], [("WEB_SEARCH", "COMPLETE")])
        self.assertGreaterEqual(float(usage.estimate("gpt-6-sol", 100, 80, "WEB_SEARCH", 3)), 0.03)

    def test_image_generation_is_durable_and_owned(self):
        client = self.client_for(self.owner)
        thread_id = store.create_thread(self.owner)
        result = {"raw": image_bytes(), "mime": "image/png", "model": "configured-image", "usage": {}}
        with patch.object(tools, "image", return_value=result):
            response = client.post(f"/kilas-ai/threads/{thread_id}/send", json={
                "content": "Draw a storefront",
                "operation_key": "toolgen_0123456789abcdef"}, headers={"X-CSRF-Token": "tool-csrf"})
            self.assertIn("image", response.get_data(as_text=True))
        stored = store.attachment_list(self.owner, thread_id)
        self.assertEqual(len(stored), 1)
        path = f"/kilas-ai/threads/{thread_id}/attachments/{stored[0]['id']}"
        self.assertEqual(client.get(path).data, image_bytes())
        self.assertEqual(self.client_for(self.foreign).get(path).status_code, 404)
        self.assertIn("Gambar selesai dibuat", client.get(f"/kilas-ai/threads/{thread_id}").text)

    def test_image_edit_requires_supplied_image(self):
        client = self.client_for(self.owner)
        thread_id = store.create_thread(self.owner)
        response = client.post(f"/kilas-ai/threads/{thread_id}/send", json={
            "content": "hapus background foto ini",
            "operation_key": "tooledit_0123456789abcdef"}, headers={"X-CSRF-Token": "tool-csrf"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Upload gambar terlebih dahulu", response.json["error"])
        self.assertEqual(store.messages(self.owner, thread_id), [])
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_ai_usage WHERE thread_id=?", (thread_id,))["n"], 0)

    def test_typo_image_request_uses_real_tool_without_text_fallback(self):
        owner = repo.create_user("tool-typo-image@example.test", "hash")
        client = self.client_for(owner)
        thread_id = store.create_thread(owner)
        result = {"raw": image_bytes(), "mime": "image/png", "model": "gpt-image-2", "usage": {}}
        with patch.object(tools, "image", return_value=result) as image_tool, \
             patch.object(providers, "stream", side_effect=AssertionError("text fallback must not run")):
            response = client.post(f"/kilas-ai/threads/{thread_id}/send", json={
                "content": "gamabar mobil", "operation_key": "typoimage_0123456789abcdef"},
                headers={"X-CSRF-Token": "tool-csrf"})
            body = response.get_data(as_text=True)
        self.assertIn("event: image", body)
        self.assertIn("event: done", body)
        self.assertEqual(image_tool.call_args.args[0], "gamabar mobil")
        self.assertEqual(len(store.attachment_list(owner, thread_id)), 1)
        self.assertEqual(db.query_one("SELECT operation_type FROM kilas_ai_usage WHERE thread_id=?", (thread_id,))["operation_type"],
                         "IMAGE_GENERATION")

    def test_image_edit_with_upload_and_owner_only_asset(self):
        owner = repo.create_user("tool-edit-upload@example.test", "hash")
        client = self.client_for(owner)
        thread_id = store.create_thread(owner)
        result = {"raw": image_bytes(), "mime": "image/png", "model": "gpt-image-2", "usage": {}}
        with patch.object(tools, "image", return_value=result) as image_tool, \
             patch.object(providers, "stream", side_effect=AssertionError("text fallback must not run")):
            response = client.post(f"/kilas-ai/threads/{thread_id}/send", data={
                "csrf_token": "tool-csrf", "content": "background putih",
                "operation_key": "uploadedit_0123456789abcdef",
                "attachments": [(io.BytesIO(image_bytes()), "source.png", "image/png")],
            }, content_type="multipart/form-data")
            self.assertIn("event: image", response.get_data(as_text=True))
        self.assertEqual(image_tool.call_args.args[1]["filename"], "source.png")
        generated = store.attachment_list(owner, thread_id)[-1]
        path = f"/kilas-ai/threads/{thread_id}/attachments/{generated['id']}"
        self.assertEqual(client.get(path).data, image_bytes())
        self.assertEqual(self.client_for(self.foreign).get(path).status_code, 404)
        self.assertEqual(db.query_one("SELECT operation_type FROM kilas_ai_usage WHERE thread_id=?", (thread_id,))["operation_type"],
                         "IMAGE_EDIT")

    def test_short_edit_followup_uses_same_threads_uploaded_image(self):
        owner = repo.create_user("tool-edit-followup@example.test", "hash")
        client = self.client_for(owner)
        thread_id = store.create_thread(owner)
        message_id, _ = store.append_user_once(owner, thread_id, "Lihat foto ini", "FAST", "sourcephoto_0123456789")
        store.save_attachments(owner, thread_id, message_id, [{"filename": "photo.png", "mime_type": "image/png",
            "byte_size": len(image_bytes()), "content": image_bytes(), "extracted_text": None}])
        result = {"raw": image_bytes(), "mime": "image/png", "model": "gpt-image-2", "usage": {}}
        with patch.object(tools, "image", return_value=result) as image_tool:
            response = client.post(f"/kilas-ai/threads/{thread_id}/send", json={
                "content": "edit ini", "operation_key": "followupedit_0123456789"},
                headers={"X-CSRF-Token": "tool-csrf"})
            self.assertIn("event: image", response.get_data(as_text=True))
        self.assertEqual(image_tool.call_args.args[1]["filename"], "photo.png")

    def test_short_image_creation_followup_carries_visual_concept(self):
        owner = repo.create_user("tool-concept-followup@example.test", "hash")
        client = self.client_for(owner)
        thread_id = store.create_thread(owner)
        store.append_user_once(owner, thread_id, "Buat konsep poster kopi premium.", "FAST", "posterconcept_0123456789")
        store.append_assistant(owner, thread_id, "Konsep poster kopi premium dengan latar cokelat.",
                               "FAST", "openai", "gpt-6-luna", "posterconcept_0123456789", {"status": "complete"})
        result = {"raw": image_bytes(), "mime": "image/png", "model": "gpt-image-2", "usage": {}}
        with patch.object(tools, "image", return_value=result) as image_tool:
            response = client.post(f"/kilas-ai/threads/{thread_id}/send", json={
                "content": "sekarang bikin gambarnya", "operation_key": "posterimage_0123456789"},
                headers={"X-CSRF-Token": "tool-csrf"})
            self.assertIn("event: image", response.get_data(as_text=True))
        self.assertIn("latar cokelat", image_tool.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
