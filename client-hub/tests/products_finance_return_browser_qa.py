"""Existing Finance customer catalog round trips; disposable DB and intercepted network."""
import json
import logging
import os
from unittest.mock import patch
import shutil
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_kilas_sidebar_products import SidebarProductsTests
import test_kilas_home as fixture
from kilas_chat_sidebar_browser_helpers import open_chat_sidebar


def main():
    case=SidebarProductsTests('test_existing_finance_session_can_return_to_catalog_without_relaxing_guards')
    case.id=lambda: "finance-return-browser"
    case.setUp()
    enabled=patch.dict(os.environ,{"KILAS_AI_ENABLED":"true"})
    enabled.start();case.addCleanup(enabled.stop)
    own,other=case.finance_fixture()
    before=case.snapshot(own,other)
    app=fixture.fixture.base.f.fixture.app.app
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path('/tmp/products-finance-return-qa');output.mkdir(exist_ok=True)
    results=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (390,1440):
                cookie=case.client().get_cookie('session')
                context=browser.new_context(viewport={'width':width,'height':900})
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                def route_request(route):
                    if route.request.url.startswith(origin):route.continue_()
                    elif route.request.url=='https://shotcut.org/download/':route.fulfill(body='Official target intercepted locally')
                    else:route.abort()
                context.route('**/*',route_request)
                page=context.new_page();page.set_default_timeout(10000)
                page.goto(origin+'/products/start')
                page.locator('#ai-input').fill('Unsent Finance return draft')
                open_chat_sidebar(page).locator('[data-products-catalog]').click()
                page.locator('.catalog-card form button').click()
                page.wait_for_url('**/business/**')
                # Visit chooser just as browser Back from the live Finance dashboard does.
                page.goto(origin+'/products/finance')
                for attempt in range(2):
                    link=open_chat_sidebar(page).locator('[data-products-catalog]')
                    link.focus();page.keyboard.press('Enter')
                    expect(page.locator('.catalog-card')).to_have_count(3)
                    expect(page.locator('#premium-sidebar')).to_have_count(0)
                    page.go_back();page.wait_for_url('**/products/finance')
                    page.go_forward();expect(page.locator('.catalog-card')).to_have_count(3)
                    page.reload();expect(page.locator('.catalog-card')).to_have_count(3)
                    page.locator('a[href="/creative-services/"]').click()
                    page.wait_for_url('**/creative-services/')
                    page.go_back();expect(page.locator('.catalog-card')).to_have_count(3)
                    with context.expect_page() as opened:
                        page.locator('a[href="https://shotcut.org/download/"]').click()
                    popup=opened.value;popup.wait_for_load_state()
                    assert popup.url=='https://shotcut.org/download/' and popup.evaluate('window.opener===null')
                    popup.close()
                    page.screenshot(path=str(output/f'catalog-from-finance-{width}.png'),full_page=True)
                    page.locator('.catalog-back').click();page.wait_for_url('**/products/start')
                    expect(page.locator('#ai-input')).to_have_value('Unsent Finance return draft')
                    page.goto(origin+'/products/finance')
                page.goto(origin+'/products/catalog?return_to=/products/start')
                expect(page.locator('.catalog-card')).to_have_count(3)
                # Revocation interrupts history safely instead of serving a cached catalog.
                if width==1440:
                    page.goto(origin+'/logout');page.go_back();page.wait_for_url('**/login')
                    page.goto(origin+'/products/catalog');page.wait_for_url('**/login')
                context.close();results.append({'width':width,'passed':True})
            browser.close()
        assert before==case.snapshot(own,other)
        (output/'results.json').write_text(json.dumps(results,indent=2))
        print(json.dumps(results))
    finally:
        server.shutdown();case.doCleanups()


if __name__=='__main__':main()
