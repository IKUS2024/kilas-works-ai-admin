"""Focused real drawer interactions, scroll and typography with synthetic local chats."""
import logging
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import test_kilas_autonomous_agent as fixture
from kilas_ai import agent_store, store
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    app = fixture.app.app
    app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
    owner = fixture.repo.create_user('drawer-synthetic@example.test', 'hash')
    ids = []
    for index in range(20):
        cid = agent_store.new_conversation(owner)
        title = ('Halo. Jelaskan arus kas untuk bisnis kecil dengan banyak pesanan dan jadwal pembayaran berbeda' if index == 19 else f'Percakapan sintetis {index + 1}')
        fixture.db.execute('UPDATE kilas_ai_conversations SET title=? WHERE id=?', (title, cid))
        ids.append(cid)
    agent_store.append(owner, 'user', 'Pesan QA sintetis tersimpan.', ids[-1])
    agent_store.append(owner, 'assistant', 'Jawaban QA sintetis tersimpan.', ids[-1])
    client = app.test_client()
    with client.session_transaction() as state:
        state.update(user_id=owner, role='CLIENT_OWNER', _csrf_token='drawer-csrf')
    cookie = client.get_cookie('session')
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    captures = Path(tempfile.gettempdir()) / 'kilas-drawer-qa'
    captures.mkdir(exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for language in ('id', 'en'):
                for width in (320, 360, 390, 430, 768, 1024):
                    context = browser.new_context(viewport={'width': width, 'height': 844}, has_touch=width <= 430)
                    context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin}, {'name': 'kilas_language', 'value': language, 'url': origin}])
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(f'{origin}/kilas-ai/agent?conversation={ids[-1]}', wait_until='networkidle')
                    drawer = page.locator('.ai-drawer')
                    mobile = width < 761
                    if mobile:
                        assert drawer.evaluate('(el)=>el.inert')
                        page.locator('[data-ai-menu]').click()
                        expect(page.locator('[data-ai-close]')).to_be_focused()
                        assert page.locator('.ai-main').evaluate('(el)=>el.inert')
                    expect(drawer).to_be_visible()
                    page.wait_for_function('Math.abs(document.querySelector(".ai-drawer").getBoundingClientRect().x)<1')
                    rows = drawer.locator('.ai-history a')
                    assert rows.count() == 20
                    assert rows.first.get_attribute('title').startswith('Halo.'), (language, width, rows.first.get_attribute('title'))
                    assert rows.first.get_attribute('aria-current') == 'page'
                    dimensions = rows.evaluate_all('(rows)=>rows.map(el=>({height:el.getBoundingClientRect().height,wrap:getComputedStyle(el).whiteSpace,ellipsis:getComputedStyle(el).textOverflow}))')
                    assert all(row == {'height': 44, 'wrap': 'nowrap', 'ellipsis': 'ellipsis'} for row in dimensions), dimensions
                    assert rows.first.evaluate('(el)=>el.scrollWidth>el.clientWidth'), 'Long title must truncate'
                    history = drawer.locator('.ai-history')
                    assert history.evaluate('(el)=>el.scrollHeight>el.clientHeight')
                    history.evaluate('(el)=>el.scrollTop=el.scrollHeight')
                    assert history.evaluate('(el)=>el.scrollTop>0')
                    assert drawer.locator('.ai-drawer-signout').bounding_box()['y'] + 44 <= 844
                    history.evaluate('(el)=>el.scrollTop=0')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    fit = drawer.locator('select[name=language]').evaluate('''el => {
                        const style=getComputedStyle(el), canvas=document.createElement('canvas'), ctx=canvas.getContext('2d');
                        ctx.font=style.font;
                        return {text:ctx.measureText(el.selectedOptions[0].textContent).width,
                            available:el.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight)-24};
                    }''')
                    assert fit['available'] >= fit['text'], (language, width, fit)
                    assert drawer.evaluate('(el)=>el.scrollWidth<=el.clientWidth'), (language, width, drawer.evaluate('(el)=>[el.scrollWidth,el.clientWidth]'))
                    page.screenshot(path=str(captures / f'{language}-{width}.png'))
                    if mobile:
                        # Native select remains in the focus trap; wrap from sign out to brand.
                        drawer.locator('select[name=language]').focus()
                        page.keyboard.press('Tab')
                        expect(drawer.locator('.language-selector button')).to_be_focused()
                        drawer.locator('.ai-drawer-signout').focus()
                        page.keyboard.press('Tab')
                        expect(drawer.locator('.ai-brand')).to_be_focused()
                        page.keyboard.press('Escape')
                        expect(page.locator('[data-ai-menu]')).to_be_focused()
                        page.locator('[data-ai-menu]').click()
                        page.locator('[data-ai-close]').click()
                        expect(page.locator('[data-ai-menu]')).to_have_attribute('aria-expanded', 'false')
                        page.locator('[data-ai-menu]').click()
                        page.locator('[data-ai-backdrop]').click(position={'x': width - 5, 'y': 300})
                        assert not page.locator('.ai-shell').evaluate('(el)=>el.classList.contains("menu-open")')
                        page.locator('[data-ai-menu]').click()
                    rows.nth(1).click()
                    page.wait_for_load_state('networkidle')
                    assert f'conversation={ids[-2]}' in page.url
                    page.reload(wait_until='networkidle')
                    assert f'conversation={ids[-2]}' in page.url
                    # Language uses the unchanged real form and persists across refresh.
                    if mobile:
                        page.locator('[data-ai-menu]').click()
                    drawer.locator('select[name=language]').select_option('en' if language == 'id' else 'id')
                    drawer.locator('.language-selector button').click()
                    page.wait_for_load_state('networkidle')
                    assert page.locator('html').get_attribute('lang') == ('en' if language == 'id' else 'id')
                    if mobile:
                        page.locator('[data-ai-menu]').click()
                    page.locator('.agent-new-chat button').click()
                    page.wait_for_load_state('networkidle')
                    assert f'conversation={ids[-2]}' not in page.url
                    assert not page.locator('.agent-message-user').count()
                    assert not errors, errors
                    context.close()
                    fixture.db.execute('DELETE FROM kilas_ai_conversations WHERE user_id=? AND id>?', (owner, ids[-1]))
            # Server-rendered zero and one history entries remain compact.
            context = browser.new_context(viewport={'width':360,'height':640})
            context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
            page = context.new_page()
            for count in (0, 1):
                with patch.object(agent_store, 'recent_conversations', return_value=[{'id':ids[-1], 'title':'Chat QA'}] if count else []):
                    page.goto(f'{origin}/kilas-ai/agent?conversation={ids[-1]}',wait_until='networkidle')
                page.locator('[data-ai-menu]').click()
                page.wait_for_function('Math.abs(document.querySelector(".ai-drawer").getBoundingClientRect().x)<1')
                assert page.locator('.ai-drawer .ai-history a').count() == count
                if not count:
                    expect(page.locator('.ai-sidebar-empty')).to_be_visible()
                if count:
                    assert page.locator('.ai-history a').bounding_box()['height'] == 44
                page.screenshot(path=str(captures / f'count-{count}-360.png'))
            # Legacy saved conversations use the same drawer without changing history storage.
            thread = store.create_thread(owner)
            store.rename_thread(owner, thread, 'Percakapan lama sintetis dengan judul yang panjang untuk pemeriksaan drawer')
            page.goto(f'{origin}/kilas-ai/threads/{thread}', wait_until='networkidle')
            page.locator('[data-ai-menu]').click()
            page.wait_for_function('Math.abs(document.querySelector(".ai-drawer").getBoundingClientRect().x)<1')
            expect(page.locator('.ai-history-item[aria-current=page]')).to_be_visible()
            assert page.locator('.ai-history-item').bounding_box()['height'] == 44
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(captures / 'legacy-360.png'))
            page.locator('.ai-drawer-signout').click()
            page.wait_for_load_state('networkidle')
            # Logout confirmation/redirect is the existing authentication route.
            assert not page.locator('.ai-drawer').count()
            context.close()
            browser.close()
        print('PASS drawer: 12 language/width combinations; empty/one/many/long title; history/open/reload/new chat; language; focus/Escape/backdrop; scroll/no overflow')
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
