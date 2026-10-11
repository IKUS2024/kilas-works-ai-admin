"""One baseline/final batch for the four remaining copy surfaces, no paid IO."""
import json
import os
import shutil
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_kilas_remaining_copy import RemainingCopyTests
import test_kilas_tabs_copy as tabs_fixture


def main():
    stage = os.environ.get('KILAS_REMAINING_COPY_STAGE', 'final')
    case = RemainingCopyTests('test_owned_pages_keep_controls_prices_terms_and_service_content')
    case.id = lambda: 'remaining-copy-browser'
    case.setUp()
    server = make_server('127.0.0.1', 0, tabs_fixture.fixture.app.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    output = Path(os.environ.get('KILAS_REMAINING_COPY_SCREENSHOTS', '/tmp/kilas-remaining-copy'))/stage
    output.mkdir(parents=True, exist_ok=True)
    report = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=shutil.which('chromium'), args=['--no-sandbox'])
            for width in (320, 1440):
                context = browser.new_context(viewport={'width': width, 'height': 1000})
                cookie = case.client.get_cookie('session')
                context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin}])
                page = context.new_page(); errors = []; posts = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: posts.append(request.url) if request.method == 'POST' else None)
                page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin) else route.abort())
                for key, path in case.paths.items():
                    response = page.goto(origin+path, wait_until='networkidle')
                    assert response.status == 200, (key, response.status)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, key)
                    if stage == 'final':
                        if key == 'settings': expect(page.locator('.subscription-header p')).to_have_count(0)
                        if key == 'account': expect(page.locator('.account-head h1')).to_have_text('Akun saya')
                        if key == 'services':
                            info = page.get_by_text('Info layanan', exact=True)
                            expect(info).to_have_count(3)
                            info.first.click(); expect(page.locator('.service-summary').first).to_be_visible()
                            info.first.click()
                    page.screenshot(path=str(output/f'{key}-{width}.png'))
                    report.append({'surface': key, 'width': width, 'status': 'PASS'})
                assert not errors, errors
                assert not posts, posts
                context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps({'pages': report, 'provider_io': False, 'posts': 0}, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        server.shutdown(); case.doCleanups()


if __name__ == '__main__': main()
