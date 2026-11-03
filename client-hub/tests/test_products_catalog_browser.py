"""Catalog navigation in Chromium with disposable data and no external IO."""
import json
import logging
import os
import re
import shutil
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_home as fixture
from kilas_chat_sidebar_browser_helpers import open_chat_sidebar


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case=fixture.HomeTests('test_old_routes_still_render');case.id=lambda:'products-catalog-browser';case.setUp()
    app=fixture.fixture.base.f.fixture.app.app
    server=make_server('127.0.0.1',0,app,threaded=True)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_CATALOG_SCREENSHOTS','/tmp/products-catalog-qa'));output.mkdir(parents=True,exist_ok=True)
    results=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            cookie=case.client().get_cookie('session')
            for width,height in ((320,740),(390,844),(1440,1000)):
                for language in ('en','id','es','zh'):
                    context=browser.new_context(viewport={'width':width,'height':height},reduced_motion='reduce')
                    context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':language,'url':origin}])
                    def route_request(route):
                        if route.request.url.startswith(origin):route.continue_()
                        elif route.request.url=='https://shotcut.org/download/':route.fulfill(status=200,content_type='text/html',body='<h1>Intercepted official destination</h1>')
                        else:route.abort()
                    context.route('**/*',route_request)
                    page=context.new_page();page.set_default_timeout(10000);page.set_default_navigation_timeout(10000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    for path,field in (('/products/start','#ai-input'),('/kilas-ai/agent?conversation='+str(case.conversation),'#agent-message')):
                        page.goto(origin+path,wait_until='networkidle');page.locator(field).fill('Keep this unsent draft')
                        for attempt in range(2):
                            print('catalog navigation',width,language,path,attempt,flush=True)
                            sidebar=open_chat_sidebar(page);link=sidebar.locator('[data-products-catalog]')
                            link.focus();expect(link).to_be_focused();page.keyboard.press('Enter');page.wait_for_url(re.compile(r'/products/catalog\?'));page.wait_for_load_state('networkidle')
                            assert '/products/catalog?' in page.url
                            expect(page.locator('#premium-sidebar,[data-premium-menu]')).to_have_count(0)
                            expect(page.locator('.catalog-card')).to_have_count(3)
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                            cards=page.locator('.catalog-card').all()
                            first,second,third=[c.bounding_box() for c in cards]
                            assert (second['y']>first['y']) if width<=900 else (abs(second['y']-first['y'])<1)
                            if path=='/products/start' and attempt==0:page.screenshot(path=str(output/f'{language}-{width}.png'),full_page=True)
                            download=page.locator('a[href="https://shotcut.org/download/"]');download.focus()
                            assert download.evaluate('e=>getComputedStyle(e).outlineStyle')!='none'
                            with context.expect_page() as opened:page.keyboard.press('Enter')
                            print('popup opened',flush=True);popup=opened.value;popup.wait_for_load_state();assert popup.url=='https://shotcut.org/download/'
                            assert popup.evaluate('window.opener===null');popup.close()
                            print('return to chat',flush=True);page.locator('.catalog-back').click();page.wait_for_load_state('networkidle')
                            assert page.url==origin+path;expect(page.locator(field)).to_have_value('Keep this unsent draft')
                        print('history check',flush=True)
                        # Native Back/Forward must retain the text even without a new link click.
                        open_chat_sidebar(page).locator('[data-products-catalog]').click();page.wait_for_load_state('networkidle')
                        page.go_back(wait_until='networkidle');expect(page.locator(field)).to_have_value('Keep this unsent draft')
                        page.once('dialog',lambda d:d.accept());page.go_forward(wait_until='networkidle');expect(page.locator('.catalog-card')).to_have_count(3)
                        page.go_back(wait_until='networkidle');expect(page.locator(field)).to_have_value('Keep this unsent draft')
                        page.locator(field).fill('')
                        results.append({'width':width,'language':language,'path':path,'result':'PASS'})
                    page.goto(origin+'/products/catalog?return_to=https://evil.example',wait_until='networkidle')
                    page.locator('.catalog-services').click();page.wait_for_load_state('networkidle')
                    assert page.url==origin+'/creative-services/'
                    expect(page.locator('.cs-back-home')).to_have_attribute('href','/products/start')
                    page.go_back(wait_until='networkidle');expect(page.locator('.catalog-card')).to_have_count(3)
                    expect(page.locator('.catalog-back')).to_have_attribute('href','/products/start')
                    # A login interruption reveals no catalog; returning as the same owner restores its chat draft.
                    page.goto(origin+'/products/start',wait_until='networkidle');page.locator('#ai-input').fill('Draft before login interruption')
                    sidebar=open_chat_sidebar(page);context.clear_cookies();sidebar.locator('[data-products-catalog]').click();page.wait_for_load_state('networkidle')
                    assert '/login' in page.url;expect(page.locator('.catalog-card')).to_have_count(0)
                    context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                    page.goto(origin+'/products/start',wait_until='networkidle');expect(page.locator('#ai-input')).to_have_value('Draft before login interruption')
                    assert not errors,errors
                    context.close()
            browser.close()
        report={'result':'PASS','cases':results,'external_download':'intercepted; destination separately verified read-only','production_mutations':0}
        (output/'results.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:
        server.shutdown();worker.join(3);case.doCleanups()


if __name__=='__main__':main()
