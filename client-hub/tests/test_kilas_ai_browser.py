"""Focused Chromium checks for the new Kilas AI desktop and mobile surfaces."""
import os
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-ai-browser-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "kilas-ai-browser-test-only"
os.environ["KILAS_AI_ENABLED"] = "true"
os.environ.pop("DATABASE_URL", None)

import app  # noqa: E402
import repo  # noqa: E402
from kilas_ai import providers  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402


def stream_reply(*_):
    yield {"type": "provider", "provider": "openai", "model": "mock-browser"}
    yield {"type": "delta", "text": "Jawaban uji Kilas AI."}
    yield {"type": "usage", "input_tokens": 4, "output_tokens": 6}
    yield {"type": "finish", "reason": "stop"}


def main():
    owner = repo.create_user("kilas-ai-browser@example.test", "hash")
    client = app.app.test_client()
    with client.session_transaction() as session:
        session.update(user_id=owner, role="CLIENT_OWNER", _csrf_token="browser-csrf")
    cookie = client.get_cookie(app.app.config.get("SESSION_COOKIE_NAME", "session"))
    server = make_server("127.0.0.1", 0, app.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with patch.object(providers, "stream", side_effect=stream_reply), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for width, height in ((1440, 900), (768, 1024), (390, 844), (320, 700)):
                context = browser.new_context(viewport={"width": width, "height": height})
                context.add_cookies([{"name": cookie.key, "value": cookie.value, "url": origin}])
                page = context.new_page()
                page.goto(origin + "/kilas-ai", wait_until="networkidle")
                assert page.get_by_role("heading", name="Apa yang ingin kamu kerjakan?").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "empty")
                page.get_by_role("button", name="+ Chat baru").first.click()
                page.wait_for_url("**/kilas-ai/threads/*")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "chat")
                if width <= 760:
                    page.get_by_role("button", name="Buka riwayat").click()
                    assert page.locator("#ai-sidebar").is_visible()
                    page.get_by_role("button", name="Tutup riwayat").click()
                page.locator("#ai-files").set_input_files({"name": "note.txt", "mimeType": "text/plain", "buffer": b"Hello browser"})
                assert page.locator("#ai-pending .ai-pending-item").count() == 1
                page.get_by_role("button", name="Hapus lampiran note.txt").click()
                assert page.locator("#ai-pending .ai-pending-item").count() == 0
                page.locator("#ai-input").fill("Halo Kilas AI")
                page.get_by_role("button", name="Kirim").click()
                page.get_by_text("Jawaban uji Kilas AI.").wait_for()
                page.reload(wait_until="networkidle")
                assert page.get_by_text("Jawaban uji Kilas AI.").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "answer")
                page.goto(origin + "/kilas-ai/usage", wait_until="networkidle")
                assert page.get_by_role("heading", name="Paket & penggunaan").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "plans")
                page.get_by_role("button", name="Pilih Plus").click()
                page.wait_for_url("**/kilas-ai/invoices/*")
                assert page.get_by_text("7610267551").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "invoice")
                context.close()
            browser.close()
    finally:
        server.shutdown()
    print("Kilas AI Chromium desktop/tablet/mobile chat, attachment, billing and overflow checks passed")


if __name__ == "__main__":
    main()
