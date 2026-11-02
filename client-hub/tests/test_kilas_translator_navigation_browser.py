"""Real Chromium taps/navigation on disposable accounts; no mic/provider traffic."""
import json
import logging
import os
import threading
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server
import test_kilas_home as home
from kilas_ai import audio_routes, live_gemini, live_translator, store


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case = home.HomeTests('test_old_routes_still_render')
    case.id = lambda: 'translator-navigation-browser'
    case.setUp()
    app = home.fixture.base.f.fixture.app.app
    ident = store.create_thread(case.owner)
    store.append_user_once(case.owner, ident, 'Stored synthetic Chat history', 'FAST', 'nav-history-12345')
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    output = Path(os.environ.get('KILAS_NAV_SCREENSHOTS', '/tmp/kilas-translator-navigation-20261102'))
    output.mkdir(parents=True, exist_ok=True)
    report = []
    try:
        with patch.object(live_translator, 'ready', return_value=False), \
             patch.object(live_gemini, 'ready', return_value=False), \
             patch.object(audio_routes, '_native_default_ready', return_value=False), sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
            for width in (360, 393, 820, 1440):
                context = browser.new_context(viewport={'width': width, 'height': 844}, has_touch=width < 761)
                cookie = case.client().get_cookie('session')
                context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin}])
                context.add_init_script("window.qaMics=0;navigator.mediaDevices.getUserMedia=()=>{qaMics++;return Promise.reject(Error('No microphone in navigation QA'))}")
                context.route('**/*', lambda r: r.continue_() if r.request.url.startswith(origin) else r.abort())
                page = context.new_page()
                errors, writes = [], []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('request', lambda r: writes.append(r.url) if r.method == 'POST' else None)
                for locale in ('id', 'en'):
                    context.add_cookies([{'name': 'kilas_language', 'value': locale, 'url': origin}])
                    for path in ('/products/start', f'/kilas-ai/threads/{ident}'):
                        page.goto(origin + path, wait_until='networkidle')
                        link = page.locator('.home-task-choices a[href="/kilas-translator/live"]')
                        expect(link).to_be_visible()
                        expect(link).not_to_have_attribute('aria-disabled', 'true')
                        hit = link.evaluate('e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}')
                        assert hit, (width, locale, path)
                        if width < 761:
                            link.tap()
                        else:
                            link.click()
                        page.wait_for_url('**/kilas-translator/live')
                        page.wait_for_load_state('networkidle')
                        expect(page.locator('#live-setup-form button[type=submit]')).to_be_disabled()
                        assert page.locator('#premium-sidebar,[data-chat-sidebar]').count() == 0
                        assert page.evaluate('qaMics') == 0
                        if path == '/products/start' and width in (393, 1440):
                            page.screenshot(path=str(output / f'translator-{locale}-{width}.png'), full_page=True)
                        page.reload(wait_until='networkidle')
                        expect(page.locator('#live-setup-form button[type=submit]')).to_be_disabled()
                        page.go_back(wait_until='networkidle')
                        expect(page.locator('#ai-composer')).to_be_visible()
                        if path != '/products/start':
                            expect(page.locator('#ai-messages')).to_contain_text('Stored synthetic Chat history')
                        page.go_forward(wait_until='networkidle')
                        expect(page.locator('#live-setup-form')).to_be_visible()
                        page.locator('.home-task-choices a[data-kilas-feature="voiceover"]').click()
                        page.wait_for_load_state('networkidle')
                        expect(page.locator('#audio-script')).to_be_visible()
                        assert page.evaluate('qaMics') == 0
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                        report.append({'width': width, 'locale': locale, 'surface': path, 'result': 'PASS'})
                assert not errors and not writes, (errors, writes)
                context.close()
            browser.close()
        (output / 'verification.json').write_text(json.dumps({'mic_calls': 0, 'paid_calls': 0, 'checks': report}, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        server.shutdown()
        case.doCleanups()


if __name__ == '__main__':
    main()
