"""Work-only Chromium smoke at desktop, tablet and narrow mobile widths."""
import os
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-work-ui-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "kilas-work-ui-test-only"
os.environ["KILAS_WORK_ENABLED"] = "true"
os.environ.pop("DATABASE_URL", None)

import app  # noqa: E402
import repo  # noqa: E402
from kilas_work import engine, store  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402


def main():
    server = make_server("127.0.0.1", 0, app.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with patch.object(engine, "respond", return_value={"answer": "Pekerjaan uji selesai.",
                          "usage": {"input_tokens": 100, "output_tokens": 40},
                          "charged_micro": 30, "web_calls": 0, "citations": []}), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for width, height in ((1440, 900), (820, 1024), (390, 844), (320, 700)):
                owner = repo.create_user(f"kilas-work-ui-{width}@example.test", "hash")
                client = app.app.test_client()
                with client.session_transaction() as state:
                    state.update(user_id=owner, role="CLIENT_OWNER", _csrf_token="work-ui-csrf")
                cookie = client.get_cookie(app.app.config.get("SESSION_COOKIE_NAME", "session"))
                context = browser.new_context(viewport={"width": width, "height": height})
                context.add_cookies([{"name": cookie.key, "value": cookie.value, "url": origin}])
                page = context.new_page()
                page.goto(origin + "/kilas-work", wait_until="networkidle")
                assert page.get_by_role("heading", name="Apa yang ingin kamu kerjakan?").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "home")
                page.locator("#work-message").fill("Bantu ringkas laporan ini")
                page.get_by_role("button", name="Kirim").click()
                page.get_by_text("Pekerjaan uji selesai.").wait_for()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "thread")
                assert len(store.threads(owner)) == 1
                page.goto(origin + "/kilas-work/usage", wait_until="networkidle")
                assert page.get_by_text("Kuota Percobaan").first.is_visible()
                assert page.get_by_text("Work Plus").first.is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "usage")
                context.close()
            browser.close()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
