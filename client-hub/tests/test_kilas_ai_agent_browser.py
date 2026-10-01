"""Bounded Agent desktop/tablet/mobile navigation and overflow check."""
import os
import sys
import tempfile
import threading
from cryptography.fernet import Fernet

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-agent-browser-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "kilas-agent-browser-test"
os.environ["KILAS_AI_ENABLED"] = "true"
os.environ["KILAS_AI_AUTOMATION_ENABLED"] = "true"
os.environ["KILAS_GOOGLE_CLIENT_ID"] = "browser-fixture-client"
os.environ["KILAS_GOOGLE_CLIENT_SECRET"] = "browser-fixture-secret"
os.environ["KILAS_GOOGLE_REDIRECT_URI"] = "https://app.example.test/kilas-ai/agent/connections/google/callback"
os.environ["KILAS_CONNECTOR_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ.pop("DATABASE_URL", None)

import app  # noqa: E402
import db  # noqa: E402
import repo  # noqa: E402
from kilas_ai import agent_planner, automation_schedule as schedule, automation_store as store, connectors  # noqa: E402
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
                owner = repo.create_user(f"agent-browser-{width}@example.test", "hash")
                client = app.app.test_client()
                with client.session_transaction() as state:
                    state.update(user_id=owner, role="CLIENT_OWNER", _csrf_token="agent-browser-csrf")
                cookie = client.get_cookie(app.app.config.get("SESSION_COOKIE_NAME", "session"))
                context = browser.new_context(viewport={"width": width, "height": height}, timezone_id="Asia/Jakarta")
                context.add_cookies([{"name": cookie.key, "value": cookie.value, "url": origin}])
                page = context.new_page()
                page.goto(origin + "/kilas-ai/agent", wait_until="networkidle")
                assert page.get_by_role("heading", name="Agent Chat").is_visible()
                assert page.locator("#agent-message").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "chat overflow")
                spec = schedule.parse("Setiap hari jam 8 cari berita AI terbaru.")
                spec["title"] = "Rangkuman pasar untuk tim kerja dan pelanggan " + ("Nama proyek panjang " * 12)
                store.create(owner, spec)
                page.get_by_role("link", name="Tugas aktif").click()
                assert page.get_by_text("Rangkuman pasar untuk tim kerja").count() >= 1
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "long task overflow")
                page.get_by_role("link", name="Koneksi", exact=True).first.click()
                assert page.get_by_role("heading", name="Belum ada koneksi eksternal").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "connections overflow")
                page.get_by_role("link", name="Aktivitas", exact=True).first.click()
                assert page.get_by_text("Belum ada aktivitas.").is_visible()
                page.get_by_role("link", name="Agent Chat").click()
                page.locator("#agent-message").fill("setiap pagi cek email penting gue")
                page.get_by_role("button", name="Kirim").click()
                assert page.get_by_text("Kilas butuh akses Gmail", exact=False).is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "reply overflow")
                stamp = connectors.stamp()
                long_email = ("very-long-business-account-name-" * 4) + "@example.test"
                db.execute("INSERT INTO kilas_ai_connections "
                    "(user_id,provider,display_identity,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
                    "VALUES (?,'GOOGLE',?,'CONNECTED',?,'{}','browser-fixture',?,?)",
                    (owner, long_email,
                     '["https://www.googleapis.com/auth/gmail.readonly",'
                     '"https://www.googleapis.com/auth/gmail.compose",'
                     '"https://www.googleapis.com/auth/gmail.send"]', stamp, stamp))
                connectors.propose_action(owner, "gmail.send", "wilson@example.test",
                    {"to": "wilson@example.test", "subject": "Pertemuan",
                     "body": "Besok jam 2 bisa."})
                page.goto(origin + "/kilas-ai/agent?view=connections", wait_until="networkidle")
                assert page.get_by_text(long_email).is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "long identity overflow")
                page.goto(origin + "/kilas-ai/agent?view=chat", wait_until="networkidle")
                assert page.get_by_role("heading", name="Periksa sebelum dikirim").is_visible()
                assert page.get_by_role("button", name="Konfirmasi tindakan").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "approval overflow")
                context.close()
            browser.close()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
