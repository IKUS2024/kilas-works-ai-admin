"""Reported Android drawer/history and keyboard identity regressions; no paid IO."""
import json
import logging
import os
import threading
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_experience as fixture
from kilas_ai import store, chat_models, image_models


def main():
    output = Path(os.environ.get('KILAS_MOBILE_SCREENSHOTS', '/tmp/kilas-mobile-correction'))
    output.mkdir(parents=True, exist_ok=True)
    case = fixture.ExperienceTests('test_starters_follow_ui_language_without_changing_models')
    case.setUp()
    app = fixture.home.fixture.base.f.fixture.app.app
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    report = {'paid_calls': 0, 'physical_android': False, 'drawers': [], 'keyboard': []}
    for i in range(14):
        thread = store.create_thread(case.owner)
        store.rename_thread(case.owner, thread, f'Saved conversation {i}: a long meaningful title for mobile')
        store.append_user_once(case.owner, thread, 'Synthetic saved message.', 'SMART', f'mobile-qa-{i}')
    try:
        with patch.object(chat_models, 'check', side_effect=lambda m: {**chat_models.spec(m), 'available': True, 'images': True, 'status': 'verified'}), patch.object(image_models, 'check', side_effect=lambda m: {**image_models.spec(m), 'available': True, 'status': 'verified'}), sync_playwright() as p:
            browser = p.chromium.launch(headless=True,executable_path='/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None)
            for width, height in ((360, 650), (393, 708), (320, 568), (820, 1000), (1440, 900)):
                context = browser.new_context(viewport={'width': width, 'height': height}, has_touch=width < 761, reduced_motion='reduce')
                cookie = case.client().get_cookie('session')
                context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin}, {'name': 'kilas_language', 'value': 'en', 'url': origin}])
                page = context.new_page()
                errors = []
                writes = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('request', lambda r: writes.append(r.url) if r.method == 'POST' else None)
                page.route('**/*', lambda r: r.continue_() if r.request.url.startswith(origin) else r.abort())
                # Audio previously omitted the base sidebar CSS although it rendered the same drawer.
                for route, name in (('/products/start', 'chat'),):
                    page.goto(origin + route, wait_until='networkidle')
                    expect(page.locator('link[href*="kilas_chat_sidebar.css"]')).to_have_count(1)
                    page.locator('[data-premium-menu]').click()
                    rail = page.locator('#premium-sidebar')
                    first = rail.locator('.ai-history>a').first
                    expect(first).to_be_visible()
                    bounds = rail.evaluate('''e=>{const r=s=>e.querySelector(s).getBoundingClientRect(), h=r('.ai-history'), f=r('.kilas-sidebar-profile'), b=r('.chat-product-entry button');return {height:h.height,historyBottom:h.bottom,profileTop:f.top,financeDisplay:getComputedStyle(e.querySelector('.chat-product-entry button')).display,financeBorder:getComputedStyle(e.querySelector('.chat-product-entry button')).borderTopWidth,financeHeight:b.height,firstTop:r('.ai-history>a').top,firstBottom:r('.ai-history>a').bottom}}''')
                    assert bounds['height'] >= 64 and bounds['historyBottom'] <= bounds['profileTop'] + 1, (name, width, bounds)
                    assert bounds['firstTop'] >= 0 and bounds['firstBottom'] <= height, (name, width, bounds)
                    assert bounds['financeDisplay'] == 'flex' and bounds['financeBorder'] == '0px', (name, width, bounds)
                    page.screenshot(path=str(output / f'{name}-drawer-{width}.png'))
                    # On very short viewports the outer drawer also scrolls to its account footer.
                    rail.locator('.kilas-sidebar-profile').evaluate('e=>e.scrollIntoView({block:"end"})')
                    assert rail.locator('.kilas-sidebar-profile').evaluate('e=>e.getBoundingClientRect().bottom<=innerHeight+1'), (name, width, 'account footer clipped')
                    if width == 320:
                        page.screenshot(path=str(output / f'{name}-drawer-footer-{width}.png'))
                    listing = rail.locator('.ai-history')
                    listing.evaluate('e=>e.scrollTop=e.scrollHeight')
                    assert listing.evaluate('e=>e.scrollHeight<=e.clientHeight||e.scrollTop>0'), (name, width, 'history cannot scroll')
                    rail.locator('[data-chat-history-expand]').click()
                    expect(rail.locator('[data-chat-history-expand]')).to_have_attribute('aria-expanded', 'true')
                    rail.locator('[data-chat-history-toggle]').click()
                    expect(rail.locator('[data-chat-history-content]')).to_be_hidden()
                    rail.locator('[data-chat-history-toggle]').click()
                    page.keyboard.press('Escape')
                    expect(rail).to_have_attribute('inert', '')
                    report['drawers'].append({'route': name, 'width': width, **bounds})
                page.goto(origin + '/products/start', wait_until='networkidle')
                if width < 761:
                    # Visual viewport simulation preserves the layout viewport, like Android keyboard resize.
                    page.add_init_script('''(()=>{const v=new EventTarget();Object.assign(v,{height:innerHeight,width:innerWidth,offsetTop:0,offsetLeft:0,scale:1});Object.defineProperty(window,'visualViewport',{value:v});window.qaViewport=(height,top=0,scale=1)=>{Object.assign(v,{height,offsetTop:top,scale,width:innerWidth/scale});v.dispatchEvent(new Event('resize'))}})()''')
                    page.reload(wait_until='networkidle')
                    field = page.locator('#ai-input')
                    for repeat in range(2):
                        field.fill('Retained unsent mobile draft')
                        field.focus()
                        page.evaluate('qaViewport(390, 12)')
                        expect(page.locator('.kilas-reference-header .premium-brand span')).to_be_visible()
                        expect(page.locator('.ai-empty .kilas-new-chat-logo')).to_be_visible()
                        expect(page.locator('.ai-empty h1')).to_be_visible()
                        geometry = page.evaluate('''()=>{const r=s=>document.querySelector(s).getBoundingClientRect();return {logo:r('.ai-empty .kilas-new-chat-logo').toJSON(),welcome:r('.ai-empty h1').toJSON(),composer:r('#ai-composer').toJSON(),header:r('.kilas-reference-header').toJSON()}}''')
                        assert geometry['logo']['top'] >= geometry['header']['bottom'] and geometry['welcome']['bottom'] <= geometry['composer']['top'], geometry
                        assert geometry['composer']['bottom'] <= 402, geometry
                        if repeat == 0:
                            page.screenshot(path=str(output / f'keyboard-logo-{width}.png'))
                        page.locator('[data-premium-menu]').click()
                        page.locator('#premium-sidebar .kilas-sidebar-profile').evaluate('e=>e.scrollIntoView({block:"end"})')
                        assert page.locator('#premium-sidebar .kilas-sidebar-profile').evaluate('e=>e.getBoundingClientRect().bottom<=402'), width
                        if width == 320 and repeat == 0:
                            page.screenshot(path=str(output / 'keyboard-drawer-footer-320.png'))
                        page.locator('#premium-sidebar [data-premium-close]').click()
                        expect(field).to_have_value('Retained unsent mobile draft')
                        field.blur()
                        page.evaluate(f'qaViewport({height})')
                    # A real saved transcript, multiple pending files and a multiline draft.
                    page.goto(origin + f'/kilas-ai/threads/{thread}', wait_until='networkidle')
                    field.fill('Long draft\n' * 8)
                    page.locator('#ai-files').set_input_files([{'name': f'long-attachment-name-{i}.txt', 'mimeType': 'text/plain', 'buffer': b'synthetic'} for i in range(2)])
                    page.evaluate('qaViewport(390,12)')
                    expect(page.locator('.ai-empty')).to_be_hidden()
                    overlap = page.evaluate('''()=>{const r=s=>document.querySelector(s).getBoundingClientRect();return {messages:r('#ai-messages').toJSON(),pending:r('#ai-pending').toJSON(),composer:r('#ai-composer').toJSON()}}''')
                    assert overlap['messages']['bottom'] <= overlap['composer']['top'] + 1 and overlap['pending']['top'] >= overlap['composer']['top'], overlap
                    assert overlap['composer']['bottom'] <= 402, overlap
                    page.screenshot(path=str(output / f'keyboard-transcript-{width}.png'))
                    page.locator('#ai-pending button').first.click()
                    expect(page.locator('#ai-pending .ai-pending-item')).to_have_count(1)
                    page.evaluate('qaViewport(300, 20, 1.5)')
                    assert page.locator('#ai-composer').evaluate('e=>e.getBoundingClientRect().bottom<=320'), width
                    report['keyboard'].append({'width': width, 'identity': geometry, 'transcript': overlap})
                assert not errors and not writes, (errors, writes)
                context.close()
            browser.close()
        (output / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
    finally:
        server.shutdown()
        case.doCleanups()


if __name__ == '__main__':
    main()
