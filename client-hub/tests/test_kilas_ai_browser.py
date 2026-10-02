"""Focused Chromium checks for the new Kilas AI desktop and mobile surfaces."""
import io
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
from PIL import Image  # noqa: E402
from kilas_ai import providers, store, tools  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402


def stream_reply(*_):
    yield {"type": "provider", "provider": "openai", "model": "mock-browser"}
    yield {"type": "delta", "text": "Jawaban uji Kilas AI."}
    yield {"type": "usage", "input_tokens": 4, "output_tokens": 6}
    yield {"type": "finish", "reason": "stop"}


def sample_image():
    output = io.BytesIO()
    Image.new("RGB", (8, 8), (242, 128, 42)).save(output, "PNG")
    return output.getvalue()


def main():
    server = make_server("127.0.0.1", 0, app.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with patch.object(providers, "stream", side_effect=stream_reply), \
             patch.object(tools, "web_search_steps", return_value=[{"result": {"text": "Fakta dengan sumber.",
                "citations": [{"url": "https://example.org/source", "title": "Sumber uji"}],
                "model": "gpt-6-luna", "usage": {"input_tokens": 100, "output_tokens": 50}}}]), \
             patch.object(tools, "image", return_value={"raw": sample_image(), "mime": "image/png",
                "model": "gpt-image-2", "usage": {}}), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for width, height in ((1440, 900), (768, 1024), (390, 844), (320, 700)):
                owner = repo.create_user(f"kilas-ai-browser-{width}@example.test", "hash")
                client = app.app.test_client()
                with client.session_transaction() as session:
                    session.update(user_id=owner, role="CLIENT_OWNER", _csrf_token="browser-csrf")
                cookie = client.get_cookie(app.app.config.get("SESSION_COOKIE_NAME", "session"))
                context = browser.new_context(viewport={"width": width, "height": height})
                context.add_cookies([{"name": cookie.key, "value": cookie.value, "url": origin}])
                page = context.new_page()
                page.goto(origin + "/kilas-ai", wait_until="networkidle")
                assert page.get_by_role("heading", name="Apa yang ingin kamu kerjakan?").is_visible()
                assert page.get_by_text("Tanya sesuatu, cari informasi, atau bahas lampiranmu.").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "empty")
                if width <= 760:
                    page.get_by_role("button", name="Buka riwayat").click()
                page.get_by_role("link", name="+ Chat baru").click()
                assert page.url.endswith("/kilas-ai")
                assert store.list_threads(owner) == []
                assert page.get_by_role("heading", name="Apa yang ingin kamu kerjakan?").is_visible()
                assert page.locator(".ai-shell").get_attribute("data-max-files") == "2"
                # Closed mobile history is now inert and visually hidden.
                assert page.locator(".ai-sidebar-plan").text_content().strip() == "Kilas AI"
                if width <= 760:
                    page.get_by_role("button", name="Buka riwayat").click()
                    assert page.locator("#ai-sidebar").is_visible()
                    page.locator("[data-ai-close]").click()
                page.locator("#ai-files").set_input_files({"name": "note.txt", "mimeType": "text/plain", "buffer": b"Hello browser"})
                assert page.locator("#ai-pending .ai-pending-item").count() == 1
                page.get_by_role("button", name="Hapus lampiran note.txt").click()
                assert page.locator("#ai-pending .ai-pending-item").count() == 0
                assert page.locator("#ai-tool,#ai-mode").count() == 0
                assert page.locator("#ai-search").count() == 1
                page.locator("#ai-input").fill("Halo Kilas AI")
                page.get_by_role("button", name="Kirim").click()
                page.get_by_text("Jawaban uji Kilas AI.").wait_for()
                assert page.locator(".ai-assistant .ai-copy").count() == 1
                page.wait_for_url("**/kilas-ai/threads/*")
                assert len(store.list_threads(owner)) == 1
                assert page.locator(".ai-user .ai-message-text").first.inner_text() == "Halo Kilas AI"
                assert store.thread(owner, int(page.url.rsplit("/", 1)[1]))["selected_mode"] == "FAST"
                page.locator("#ai-input").fill("Pesan kedua")
                page.get_by_role("button", name="Kirim").click()
                page.locator(".ai-user .ai-message-text").nth(1).wait_for()
                assert page.locator(".ai-user .ai-message-text").nth(1).inner_text() == "Pesan kedua"
                page.locator(".ai-assistant .ai-copy").nth(1).wait_for()
                gap = page.evaluate("""() => {const a=document.querySelectorAll('.ai-message');return a[2].getBoundingClientRect().top-a[1].getBoundingClientRect().bottom;}""")
                assert gap < 100, (width, "message gap", gap)
                page.reload(wait_until="networkidle")
                assert page.get_by_text("Jawaban uji Kilas AI.").first.is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "answer")
                page.locator("#ai-input").fill("Buat jawaban tadi jadi PDF.")
                page.get_by_role("button", name="Kirim").click()
                page.locator(".ai-file-card").wait_for()
                assert page.get_by_role("link", name="Download").count() == 1
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "pdf")
                page.locator("#ai-search").check()
                page.locator("#ai-input").fill("Cari informasi uji")
                page.get_by_role("button", name="Kirim").click()
                page.get_by_role("link", name="Sumber uji").wait_for()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "web")
                page.locator("#ai-search").uncheck()
                page.locator("#ai-input").fill("Buat gambar uji")
                page.get_by_role("button", name="Kirim").click()
                page.locator(".ai-image-result img").wait_for()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "image")
                count = len(store.list_threads(owner))
                if width <= 760:
                    page.get_by_role("button", name="Buka riwayat").click()
                page.get_by_role("link", name="+ Chat baru").click()
                assert page.url.endswith("/kilas-ai")
                assert page.get_by_role("heading", name="Apa yang ingin kamu kerjakan?").is_visible()
                assert page.locator("#ai-tool,#ai-mode").count() == 0
                assert len(store.list_threads(owner)) == count
                legacy = store.create_thread(owner, "SMART")
                page.goto(origin + f"/kilas-ai/threads/{legacy}", wait_until="networkidle")
                assert page.get_by_role("heading", name="Apa yang ingin kamu kerjakan?").is_visible()
                assert page.locator(".ai-messages").is_hidden()
                assert page.locator("#ai-composer").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "legacy empty")
                page.goto(origin + "/kilas-ai/usage", wait_until="networkidle")
                assert page.get_by_role("heading", name="Langganan").is_visible()
                assert page.get_by_text("Rp99.000").is_visible()
                assert page.get_by_text("Paket Free").count() == 0
                assert page.get_by_text("Penggunaan periode ini").count() == 0
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "plans")
                page.get_by_label("Nominal").fill("20000")
                page.get_by_role("button", name="Tambah kapasitas").click()
                page.wait_for_url("**/kilas-ai/topups/*")
                assert page.get_by_role("heading", name="Kapasitas Tambahan").is_visible()
                assert page.get_by_text("Rp20.000").is_visible()
                assert page.get_by_label("Bukti transfer (gambar atau PDF, maksimal 5 MB)").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "topup invoice")
                page.get_by_role("link", name="Langganan & tagihan").click()
                assert page.get_by_role("heading", name="Kilas AI").is_visible()
                page.get_by_role("button", name="Mulai berlangganan").click()
                page.wait_for_url("**/kilas-ai/invoices/*")
                assert page.get_by_text("7610267551").is_visible()
                overflow = page.evaluate("""() => ({page: document.documentElement.scrollWidth,
                    culprits: [...document.querySelectorAll('body *')].filter(el => el.getBoundingClientRect().right > innerWidth + 1)
                    .slice(0, 8).map(el => [el.tagName, el.className, Math.round(el.getBoundingClientRect().right)])})""")
                assert overflow["page"] <= width, (width, "invoice", overflow)
                context.close()
            admin_id = repo.create_user("kilas-ai-browser-admin@example.test", "hash", role="KILAS_ADMIN")
            admin_client = app.app.test_client()
            with admin_client.session_transaction() as session:
                session.update(user_id=admin_id, role="KILAS_ADMIN", _csrf_token="browser-csrf")
            admin_cookie = admin_client.get_cookie(app.app.config.get("SESSION_COOKIE_NAME", "session"))
            for width, height in ((1440, 900), (768, 1024), (390, 844), (320, 700)):
                context = browser.new_context(viewport={"width": width, "height": height})
                context.add_cookies([{"name": admin_cookie.key, "value": admin_cookie.value, "url": origin}])
                page = context.new_page()
                for section in ("overview", "customers", "kilas-ai", "finance", "payments", "usage-cost", "settings"):
                    page.goto(origin + "/platform/" + section, wait_until="networkidle")
                    assert page.get_by_role("heading", name=dict((("kilas-ai", "Kilas AI"), ("finance", "Kilas Finance"), ("usage-cost", "Usage & Cost"))).get(section, section.title()), exact=True).first.is_visible()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, section)
                page.get_by_role("link", name="Keluar").first.click()
                page.wait_for_url("**/login*")
                context.close()
            browser.close()
    finally:
        server.shutdown()
    print("Kilas AI Chromium desktop/tablet/mobile chat, attachment, billing and overflow checks passed")


if __name__ == "__main__":
    main()
