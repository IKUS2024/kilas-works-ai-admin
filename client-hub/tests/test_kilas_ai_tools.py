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
from kilas_ai import store, tools  # noqa: E402


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
                "content": "Draw a storefront", "mode": "SMART", "tool": "IMAGE_GENERATE",
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
            "content": "Change color", "mode": "FAST", "tool": "IMAGE_EDIT",
            "operation_key": "tooledit_0123456789abcdef"}, headers={"X-CSRF-Token": "tool-csrf"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Upload gambar terlebih dahulu", response.json["error"])
        self.assertEqual(store.messages(self.owner, thread_id), [])


if __name__ == "__main__":
    unittest.main()
