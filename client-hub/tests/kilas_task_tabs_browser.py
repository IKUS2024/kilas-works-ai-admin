"""Tab geometry and native navigation on disposable data; provider IO is blocked."""
import json
import logging
import threading
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

import test_kilas_home as home
from kilas_ai import chat_models, image_models, live_translator


MEASURE = """row => {
 const box = e => {const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};
 return {row:box(row),scroll:row.scrollWidth,client:row.clientWidth,
 tabs:[...row.children].map(e=>({box:box(e),label:box(e.querySelector('span')),
 icon:box(e.querySelector('svg')),font:getComputedStyle(e).font,
 border:getComputedStyle(e).borderColor,background:getComputedStyle(e).backgroundColor,
 active:e.matches('[aria-current=page],[aria-pressed=true]')}))};
}"""


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case = home.HomeTests('test_old_routes_still_render')
    case.id = lambda: 'task-tabs-browser'
    case.setUp()
    server = make_server('127.0.0.1', 0, home.fixture.base.f.fixture.app.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    output = Path('/tmp/kilas-task-tabs')
    output.mkdir(exist_ok=True)
    report = []
    try:
        with patch.object(live_translator, 'ready', return_value=True), \
             patch.object(chat_models, 'check', side_effect=lambda m: {**chat_models.spec(m), 'available': True, 'images': True, 'status': 'verified'}), \
             patch.object(image_models, 'check', side_effect=lambda m: {**image_models.spec(m), 'available': True, 'status': 'verified'}), \
             sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
            for locale in ('en', 'id'):
                for width in (320, 360, 390, 600, 601, 760, 768, 1024, 1440):
                    context = browser.new_context(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                    cookie = case.client().get_cookie('session')
                    context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin},
                                         {'name': 'kilas_language', 'value': locale, 'url': origin}])
                    context.route('**/*', lambda r: r.continue_() if r.request.url.startswith(origin) else r.abort())
                    page = context.new_page()
                    errors, posts = [], []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
                    baseline = None

                    def verify(active):
                        nonlocal baseline
                        row = page.locator('.kilas-task-navigation .home-task-choices')
                        expect(row).to_have_count(1)
                        assert row.inner_text().splitlines() == ['AI Chat', 'Translator', 'Voice Over']
                        expect(row.locator('[aria-current=page],[aria-pressed=true]')).to_have_text(active)
                        metrics = row.evaluate(MEASURE)
                        assert metrics['scroll'] <= metrics['client'] + 1, metrics
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, active)
                        widths = [t['box']['w'] for t in metrics['tabs']]
                        assert max(widths) - min(widths) < 1
                        assert len({t['font'] for t in metrics['tabs']}) == 1
                        assert len({t['box']['y'] for t in metrics['tabs']}) == 1
                        for t in metrics['tabs']:
                            b, label, icon = t['box'], t['label'], t['icon']
                            assert b['h'] == 52
                            assert label['x'] >= b['x'] and label['right'] <= b['right'], t
                            assert icon['x'] >= b['x'] and icon['right'] <= label['x'], t
                            assert abs(label['y'] + label['h']/2 - (b['y'] + b['h']/2)) < 1
                            assert abs(icon['y'] + icon['h']/2 - (b['y'] + b['h']/2)) < 1
                            assert (t['border'] == 'rgb(255, 101, 12)') == t['active']
                            assert (t['background'] == 'rgb(255, 241, 230)') == t['active']
                        signature = [metrics['row']['x'], metrics['row']['w'], *widths]
                        if baseline is None:
                            baseline = signature
                        assert all(abs(a-b) < 1 for a, b in zip(baseline, signature)), (baseline, signature)
                        return metrics

                    paths = [('AI Chat', '/products/start'), ('Translator', '/kilas-translator/live'),
                             ('Voice Over', '/kilas-translator?mode=voiceover'), ('Translator', '/kilas-translator/interpreter')]
                    for active, path in paths:
                        response = page.goto(origin + path, wait_until='networkidle')
                        assert response.status == 200
                        metrics = verify(active)
                        if active == 'Voice Over':
                            expect(page.locator('#reference-script-paste,#voice-assist-copy,.voice-duration-note')).to_have_count(0)
                        if locale == 'en' and width in (320, 1440):
                            name = 'interpreter' if path.endswith('interpreter') else active.replace(' ', '-').lower()
                            page.screenshot(path=str(output / f'{name}-{width}.png'))
                        report.append({'locale': locale, 'width': width, 'path': path, 'row': metrics['row'], 'result': 'PASS'})

                    # Repeated real links, including back/forward, retain selected state and geometry.
                    page.goto(origin + '/products/start', wait_until='networkidle')
                    for _ in range(2):
                        page.locator('.kilas-task-navigation a').filter(has_text='Translator').click()
                        page.wait_for_load_state('networkidle'); verify('Translator')
                        page.locator('[data-kilas-feature=voiceover]').click()
                        page.wait_for_load_state('networkidle'); verify('Voice Over')
                        page.go_back(wait_until='networkidle'); verify('Translator')
                        page.go_back(wait_until='networkidle'); verify('AI Chat')
                        page.go_forward(wait_until='networkidle'); verify('Translator')
                        page.locator('[data-kilas-feature=chat]').click()
                        page.wait_for_load_state('networkidle'); verify('AI Chat')

                    # Keyboard navigation uses normal DOM order and a visible focus ring.
                    first = page.locator('[data-home-task=chat]')
                    first.focus()
                    page.keyboard.press('Tab')
                    expect(page.locator('.kilas-task-navigation a').filter(has_text='Translator')).to_be_focused()
                    assert page.locator(':focus').evaluate("e=>getComputedStyle(e).outlineStyle==='solid'&&parseFloat(getComputedStyle(e).outlineWidth)>=2")
                    page.keyboard.press('Enter');page.wait_for_load_state('networkidle');verify('Translator')
                    assert not errors, errors
                    assert all(url.endswith('/kilas-ai/work/preferences') for url in posts), posts
                    context.close()
                    print(f'PASS {locale} {width}: geometry, labels, active state, switching, history, keyboard', flush=True)
            browser.close()
        (output / 'verification.json').write_text(json.dumps(report, indent=2))
    finally:
        server.shutdown()
        case.doCleanups()


if __name__ == '__main__':
    main()
