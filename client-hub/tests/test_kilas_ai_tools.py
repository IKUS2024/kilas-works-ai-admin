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
from kilas_ai import providers, store, tools  # noqa: E402
import db  # noqa: E402


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


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
