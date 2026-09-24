"""Headless mobile browser QA for the disposable Public Web Chat harness.

Run the harness first on 127.0.0.1:8765. This script uses only synthetic fixture data.
"""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("KILAS_PUBLIC_CHAT_QA_BASE", "http://127.0.0.1:8765").rstrip("/")
OUT = Path(os.environ.get("KILAS_PUBLIC_CHAT_QA_OUT", "/tmp/kilas-browser-qa"))
OUT.mkdir(parents=True, exist_ok=True)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        owner_ctx = browser.new_context(viewport={"width": 390, "height": 844})
        owner = owner_ctx.new_page()
        owner.goto(BASE + "/dev/owner/7", wait_until="networkidle")
        expect(owner.locator("[data-web-share]").first).to_be_visible()
        share = owner.locator("[data-web-share]").first
        endpoint = share.get_attribute("data-url")
        csrf = share.get_attribute("data-csrf")
        response = owner_ctx.request.post(
            BASE + endpoint,
            headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
            data={},
        )
        assert response.ok, response.text()
        chat_path = response.json()["path"]
        assert chat_path.startswith("/chat/")
        owner.screenshot(path=str(OUT / "01_owner_share.png"), full_page=True)

        customer_ctx = browser.new_context(viewport={"width": 390, "height": 844})
        customer = customer_ctx.new_page()
        customer.goto(BASE + chat_path, wait_until="networkidle")
        expect(customer.locator("textarea#web-message")).to_be_enabled(timeout=10_000)
        expect(customer.get_by_text("Ada yang bisa kami bantu?")).to_be_visible()
        customer.locator("textarea#web-message").fill("Jam buka sampai jam berapa?")
        customer.get_by_role("button", name="Kirim").click()
        expect(customer.get_by_text("Halo! Kedai Demo buka pukul 09.00–17.00. Ada yang bisa kami bantu?")).to_be_visible(timeout=10_000)
        customer.screenshot(path=str(OUT / "02_customer_ai_reply.png"), full_page=True)

        owner.goto(BASE + "/business/7/inbox?channel=web", wait_until="networkidle")
        expect(owner.get_by_text("Percakapan web")).to_be_visible()
        conversation = owner.locator("a.web-conversation").first
        expect(conversation).to_be_visible()
        conversation.click()
        expect(owner.get_by_role("button", name="Ambil alih")).to_be_visible()
        owner.get_by_role("button", name="Ambil alih").click()
        reply = owner.locator("#web-owner-message")
        expect(reply).to_be_enabled(timeout=10_000)
        reply.fill("Kami bantu langsung ya.")
        owner.get_by_role("button", name="Kirim balasan").click()
        expect(owner.get_by_text("Kami bantu langsung ya.")).to_be_visible(timeout=10_000)
        owner.screenshot(path=str(OUT / "03_owner_takeover.png"), full_page=True)

        expect(customer.get_by_text("Kami bantu langsung ya.")).to_be_visible(timeout=10_000)
        customer.screenshot(path=str(OUT / "04_customer_human_reply.png"), full_page=True)

        other_ctx = browser.new_context(viewport={"width": 390, "height": 844})
        other = other_ctx.new_page()
        other.goto(BASE + "/dev/owner/8", wait_until="networkidle")
        blocked = other.goto(BASE + "/business/7/inbox?channel=web", wait_until="domcontentloaded")
        assert blocked.status == 404, blocked.status

        customer_ctx.close()
        owner_ctx.close()
        other_ctx.close()
        browser.close()

    print("PASS: mobile browser QA — public chat, AI reply, Inbox, takeover, human reply, tenant isolation")
    print(f"Screenshots: {OUT}")


if __name__ == "__main__":
    main()
