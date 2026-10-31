"""Public Creative Services UI smoke. GET only; WhatsApp is never opened or sent.

--local exercises the same checks against the maintained source without network.
"""
import argparse
import functools
import http.server
import json
from pathlib import Path
import threading
import sys
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--local', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(root/'client-hub/tests'))
    from test_creative_studio_browser import check_contrast
    output = Path('/tmp/creative-services-live-smoke')
    output.mkdir(exist_ok=True)
    server = None
    if args.local:
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.path = self.path.replace('/creative-services/', '/', 1)
                super().do_GET()
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(root/'creative-services-site')))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        origins = [(f'http://127.0.0.1:{server.server_port}', '/creative-services/')]
    else:
        origins = [('https://kilas-works-client-hub.onrender.com','/creative-services/'), ('https://app.kilasworks.id','/creative-services/'), ('https://kilasworks-creative-services.onrender.com','/')]
    reports = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path='/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None)
            for origin, path in origins:
                for width in (393, 1440):
                    for locale in ('id', 'en'):
                        context = browser.new_context(viewport={'width': width, 'height': 852}, reduced_motion='reduce')
                        context.add_cookies([{'name': 'kilas_language', 'value': locale, 'url': origin}])
                        external, writes, errors = [], [], []
                        def route(r):
                            url = urlsplit(r.request.url)
                            if r.request.method != 'GET':
                                writes.append(r.request.url); r.abort()
                            elif url.netloc != urlsplit(origin).netloc:
                                external.append(r.request.url); r.abort()
                            else:
                                r.continue_()
                        context.route('**/*', route)
                        page = context.new_page()
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        response = page.goto(origin+path, wait_until='networkidle')
                        assert response.status == 200
                        expect(page.locator('html')).to_have_attribute('lang', locale)
                        expect(page.locator('#cs-title')).to_contain_text('Momen jadi cerita.' if locale == 'id' else 'Moments into stories.')
                        expect(page.locator('[data-service-choice]')).to_have_count(2)
                        expect(page.locator('footer a').last).to_have_attribute('href','https://app.kilasworks.id/products/start')
                        check_contrast(page)
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), (origin, width, locale)
                        for image in page.locator('img[src*="illustrations/"]').all():
                            if image.is_visible():
                                image.scroll_into_view_if_needed()
                                page.wait_for_function('(e)=>e.complete&&e.naturalWidth>0', arg=image.element_handle())
                        page.mouse.move(0, 0)
                        page.evaluate('document.activeElement?.blur();scrollTo(0,0)')
                        host = urlsplit(origin).hostname
                        page.screenshot(path=str(output/f'{host}-{locale}-{width}.png'), full_page=True)
                        if width == 393:
                            page.locator('[data-cs-menu]').click()
                            expect(page.locator('#studio-navigation')).to_be_visible()
                            page.keyboard.press('Escape')
                            expect(page.locator('[data-cs-menu]')).to_have_attribute('aria-expanded', 'false')
                        for kind in ('event', 'social'):
                            page.locator(f'[data-service-choice="{kind}"]').click()
                            expect(page.locator(f'#cs-{kind}')).to_be_visible()
                            expect(page.locator(f'#cs-{kind} .cs-card')).to_have_count(3)
                            if kind == 'social':
                                expect(page.locator('#cs-addons-title')).to_be_visible()
                            page.locator(f'#cs-{kind} [data-service-id]').first.click()
                            page.locator('#cs-brief-date').fill('2026-11-20')
                            page.locator('#cs-brief-location').fill('UI smoke — no send')
                            page.locator('#cs-brief-needs').fill('Synthetic public-browser check. Do not send.')
                            page.locator('.cs-brief-prepare').click()
                            expect(page.locator('#cs-brief-review-panel')).to_have_attribute('open', '')
                            message = page.locator('#cs-brief-message').input_value()
                            assert all(value in message for value in ('Basic', '2026-11-20', 'UI smoke — no send'))
                            edited = message+'\nManual edit & safe <text>.'
                            page.locator('#cs-brief-message').fill(edited)
                            href = page.locator('#cs-contact-whatsapp').get_attribute('href')
                            assert parse_qs(urlsplit(href).query)['text'] == [edited]
                            assert urlsplit(href).netloc == 'wa.me'
                            page.locator('.brand').click()
                        page.locator('#cs-brief-message').fill('  ')
                        expect(page.locator('#cs-contact-whatsapp')).to_have_attribute('aria-disabled', 'true')
                        before = page.url
                        page.locator('#cs-contact-whatsapp').click(force=True)
                        assert page.url == before and len(context.pages) == 1
                        assert not external and not writes and not errors, (external, writes, errors)
                        reports.append({'origin': origin, 'locale': locale, 'width': width, 'result': 'PASS', 'writes': 0, 'external_sends': 0, 'provider_calls': 0})
                        context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps(reports, indent=2))
        print(json.dumps(reports, indent=2))
    finally:
        if server:
            server.shutdown()


if __name__ == '__main__':
    main()
