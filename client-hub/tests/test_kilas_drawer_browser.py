"""Focused real drawer interactions, scroll and typography with synthetic local chats."""
import logging
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import test_kilas_autonomous_agent as fixture
from kilas_ai import agent_store, store, automation_store
from kilas_chat_sidebar_browser_helpers import open_chat_sidebar, click_new_chat
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
                    drawer = page.locator('.premium-sidebar')
                    mobile = width < 761
                    if mobile:
                        assert drawer.evaluate('(el)=>el.inert')
                        page.locator('[data-premium-menu]').click()
                        expect(drawer.locator('[data-premium-close]')).to_be_focused()
                    expect(drawer).to_be_visible()
                    assert drawer.locator('[data-chat-sidebar] .ai-history').count()==1
                    assert page.locator('.kilas-home-workspace .ai-history,.home-history').count()==0
                    drawer.locator('.kilas-profile-menu>summary').click();drawer.locator('.kilas-profile-language>summary').click()
                    drawer.locator('.kilas-profile-options a').last.scroll_into_view_if_needed()
                    expect(drawer.locator('.kilas-profile-options a').last).to_be_in_viewport()
                    fit = drawer.locator('select[name=language]').evaluate("""el => {
                        const style=getComputedStyle(el), canvas=document.createElement('canvas'), ctx=canvas.getContext('2d');
                        ctx.font=style.font;
                        return {text:ctx.measureText(el.selectedOptions[0].textContent).width,
                            available:el.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight)-24};
                    }""")
                    assert fit['available'] >= fit['text'], (language, width, fit)
                    assert drawer.evaluate('(el)=>el.scrollWidth<=el.clientWidth')
                    page.screenshot(path=str(captures / f'{language}-{width}.png'))
                    if mobile:
                        drawer.locator('select[name=language]').focus();page.keyboard.press('Tab')
                        expect(drawer.locator('.language-selector button')).to_be_focused()
                        drawer.locator('.kilas-profile-options a').last.focus();page.keyboard.press('Tab')
                        expect(drawer.locator('.premium-brand')).to_be_focused()
                        drawer.locator('.kilas-profile-menu>summary').click()
                        page.keyboard.press('Escape')
                        expect(page.locator('[data-premium-menu]')).to_be_focused()
                        page.locator('[data-premium-menu]').click();drawer.locator('[data-premium-close]').click()
                        expect(page.locator('[data-premium-menu]')).to_have_attribute('aria-expanded','false')
                        page.locator('[data-premium-menu]').click()
                        page.locator('.premium-backdrop').click(position={'x':width-5,'y':300})
                        assert not page.locator('body').evaluate('el=>el.classList.contains("premium-menu-open")')
                    if drawer.locator('.kilas-profile-menu').get_attribute('open') is not None:drawer.locator('.kilas-profile-menu>summary').click()
                    open_chat_sidebar(page)
                    rows=page.locator('[data-chat-sidebar] .ai-history a')
                    assert rows.count()==6
                    assert rows.first.get_attribute('title').startswith('Halo.')
                    assert rows.first.get_attribute('aria-current')=='page'
                    dimensions=rows.evaluate_all('(rows)=>rows.map(el=>({height:el.getBoundingClientRect().height,wrap:getComputedStyle(el).whiteSpace,ellipsis:getComputedStyle(el).textOverflow}))')
                    assert all(row=={'height':44,'wrap':'nowrap','ellipsis':'ellipsis'} for row in dimensions),dimensions
                    assert rows.first.evaluate('el=>el.scrollWidth>el.clientWidth')
                    panel=page.locator('#premium-sidebar')
                    assert panel.evaluate('el=>el.getBoundingClientRect().height<=innerHeight+1&&getComputedStyle(el).overflowY==="auto"')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    # Preview stays compact while the original full history retains all20 records.
                    panel.locator('.chat-history-all[href*="view=history"]').click()
                    expect(page.locator('.agent-main .agent-chats a[href*="conversation="]')).to_have_count(20)
                    page.locator(f'.agent-main .agent-chats a[href$="conversation={ids[-2]}"]').click()
                    page.wait_for_load_state('networkidle');assert f'conversation={ids[-2]}' in page.url
                    page.reload(wait_until='networkidle');assert f'conversation={ids[-2]}' in page.url
                    if mobile:page.locator('[data-premium-menu]').click()
                    drawer.locator('.kilas-profile-menu>summary').click();drawer.locator('.kilas-profile-language>summary').click()
                    drawer.locator('select[name=language]').select_option('en' if language=='id' else 'id')
                    drawer.locator('.language-selector button').click();page.wait_for_load_state('networkidle')
                    assert page.locator('html').get_attribute('lang')==('en' if language=='id' else 'id')
                    click_new_chat(page,agent=True,name='New Chat')
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
                open_chat_sidebar(page)
                assert page.locator('[data-chat-sidebar] .ai-history a').count()==count
                if not count:expect(page.locator('.ai-sidebar-empty')).to_be_visible()
                if count:assert page.locator('[data-chat-sidebar] .ai-history a').bounding_box()['height']==44
                page.screenshot(path=str(captures/f'count-{count}-360.png'))
            # Legacy saved conversations retain active history and native logout.
            thread=store.create_thread(owner)
            store.rename_thread(owner,thread,'Percakapan lama sintetis dengan judul yang panjang untuk pemeriksaan drawer')
            page.goto(f'{origin}/kilas-ai/threads/{thread}',wait_until='networkidle')
            open_chat_sidebar(page)
            expect(page.locator('.ai-history-item[aria-current=page]')).to_be_visible()
            assert page.locator('.ai-history-item').bounding_box()['height']==44
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(captures/'legacy-360.png'))
            open_chat_sidebar(page)
            page.locator('.kilas-profile-menu>summary').click();page.locator('.kilas-profile-options a').last.click();page.wait_for_load_state('networkidle')
            assert not page.locator('.premium-sidebar').count()
            context.close()
            for zone in ('Asia/Bangkok', 'Europe/London'):
                context = browser.new_context(timezone_id=zone)
                context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin}])
                page = context.new_page()
                page.goto(f'{origin}/kilas-ai/agent', wait_until='networkidle')
                assert automation_store.setting(owner) == zone
                assert page.locator('[name=browser_timezone]').input_value() == zone
                assert not page.locator('.premium-navigation a[href*="view=settings"]').count()
                context.close()
            browser.close()
        print('PASS drawer: 12 language/width combinations; empty/one/many/long title; six-preview/full20 history/open/reload/new chat; language; focus/Escape/backdrop; bounded scroll/no overflow')
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
