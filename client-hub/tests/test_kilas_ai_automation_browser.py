"""Automation desktop, tablet and mobile creation without horizontal overflow."""
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-ai-automation-browser-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "kilas-ai-automation-browser-test"
os.environ["KILAS_AI_ENABLED"] = "true"
os.environ["KILAS_AI_AUTOMATION_ENABLED"] = "true"
os.environ.pop("DATABASE_URL", None)

import app  # noqa: E402
import repo  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402


def main():
    server = make_server("127.0.0.1", 0, app.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for width, height in ((1440, 900), (820, 900), (390, 844), (320, 700)):
                owner = repo.create_user(f"automation-browser-{width}@example.test", "hash")
                client = app.app.test_client()
                with client.session_transaction() as user_session:
                    user_session.update(user_id=owner, role="CLIENT_OWNER", _csrf_token="browser-csrf")
                cookie = client.get_cookie(app.app.config.get("SESSION_COOKIE_NAME", "session"))
                context = browser.new_context(viewport={"width": width, "height": height}, timezone_id="Asia/Jakarta")
                context.add_cookies([{"name": cookie.key, "value": cookie.value, "url": origin}])
                page = context.new_page()
                page.goto(origin + "/kilas-ai/automation", wait_until="networkidle")
                assert page.get_by_role("heading", name="AI Agent", exact=True).is_visible()
                assert page.locator("#auto-zone").input_value() == "Asia/Jakarta"
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "home overflow")
                page.get_by_role("link", name="+ Beri tugas ke Agent").click()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "form overflow")
                page.locator("#auto-instruction").fill("Ingetin gue bayar listrik.")
                assert page.locator("#auto-schedule-mode").input_value() == "once"
                page.locator("#auto-schedule-mode").select_option("daily")
                assert page.locator("#auto-run-date").is_hidden()
                assert page.locator("#auto-run-time").is_visible()
                page.locator("#auto-schedule-mode").select_option("weekly")
                assert page.locator("#auto-weekday").is_visible()
                page.locator("#auto-schedule-mode").select_option("monthly")
                assert page.locator("#auto-month-day").is_visible()
                page.locator("#auto-schedule-mode").select_option("once")
                assert page.locator("#auto-run-date").get_attribute("min")
                page.locator("#auto-run-date").fill("2000-01-01")
                assert not page.locator("#auto-run-date").evaluate("el => el.checkValidity()")
                page.locator("#auto-run-date").fill("2099-10-02")
                page.locator("#auto-run-time").fill("08:00")
                page.locator("#auto-timezone").fill("Asia/Bangkok")
                page.get_by_role("button", name="Lihat pratinjau").click()
                assert page.get_by_text("Periksa sebelum aktif").is_visible()
                assert page.get_by_text("Asia/Bangkok", exact=True).is_visible()
                assert page.get_by_role("button", name="Aktifkan tugas").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "preview overflow")
                page.get_by_role("button", name="Aktifkan tugas").click()
                page.wait_for_url("**/kilas-ai/automation")
                assert page.get_by_text("Ingetin gue bayar listrik.").count() >= 1
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "list overflow")
                page.get_by_role("link", name="Edit", exact=True).click()
                assert page.get_by_role("heading", name="Edit tugas Agent").is_visible()
                assert page.locator("#auto-run-date").input_value() == "2099-10-02"
                assert page.locator("#auto-run-time").input_value() == "08:00"
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "edit overflow")
                page.goto(origin + "/kilas-ai/automation", wait_until="networkidle")
                page.get_by_role("button", name="Jeda").click()
                page.get_by_role("link", name="Dijeda", exact=True).click()
                assert page.get_by_text("Dijeda", exact=True).count() >= 1
                page.get_by_role("link", name="Lihat hasil").click()
                assert page.get_by_text("Belum ada hasil.", exact=False).is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "results overflow")
                page.goto(origin + "/kilas-ai/usage", wait_until="networkidle")
                assert page.get_by_role("heading", name="Langganan").is_visible()
                assert page.get_by_text("Penggunaan periode ini").count() == 0
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "usage overflow")
                page.goto(origin + "/kilas-ai", wait_until="networkidle")
                assert page.locator(".ai-mode-tabs").get_by_role("link", name="AI Agent").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "chat nav overflow")
                context.close()
            browser.close()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
