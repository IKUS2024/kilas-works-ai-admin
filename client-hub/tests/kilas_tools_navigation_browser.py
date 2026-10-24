"""Tools have account/back navigation; conversation drawer stays in Chat. No provider IO."""
import json
import logging
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_experience as fixture
from kilas_ai import chat_models, image_models


def main():
    case=fixture.ExperienceTests('test_starters_follow_ui_language_without_changing_models');case.setUp()
    app=fixture.home.fixture.base.f.fixture.app.app
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    report=[];output=Path('/tmp/kilas-tools-navigation');output.mkdir(exist_ok=True)
    try:
        with patch.object(chat_models,'check',side_effect=lambda m:{**chat_models.spec(m),'available':True,'images':True,'status':'verified'}),patch.object(image_models,'check',side_effect=lambda m:{**image_models.spec(m),'available':True,'status':'verified'}),sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None)
            for locale in ('en','id'):
                for width,height in ((320,568),(390,844),(820,1000),(1440,900)):
                    context=browser.new_context(viewport={'width':width,'height':height},has_touch=width<761)
                    cookie=case.client().get_cookie('session')
                    context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':locale,'url':origin}])
                    page=context.new_page();errors=[];writes=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('request',lambda r:writes.append(r.url) if r.method=='POST' else None)
                    page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                    for name,path in (('credits','/kilas-ai/usage'),('billing','/kilas-ai/usage?view=legacy'),('voiceover','/kilas-translator?mode=voiceover'),('translator','/kilas-translator?mode=translate'),('interpreter','/kilas-translator/interpreter'),('live','/kilas-translator/live')):
                        response=page.goto(origin+path,wait_until='networkidle');assert response.status==200,(path,response.status)
                        expect(page.locator('.kilas-tool-header')).to_have_count(1)
                        for selector in ('#premium-sidebar','[data-premium-menu]','.premium-backdrop','[data-chat-sidebar]','script[src*="kilas_premium.js"]','script[src*="kilas_chat_sidebar.js"]','link[href*="kilas_chat_sidebar.css"]'):
                            expect(page.locator(selector)).to_have_count(0)
                        assert page.locator('html').get_attribute('lang')==locale
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(name,width)
                        assert page.locator('.kilas-tool-header').evaluate('e=>e.getBoundingClientRect().left>=0')
                        if name=='credits':
                            assert page.locator('.credits-frame').evaluate('e=>getComputedStyle(e).marginLeft')=='0px'
                            page.screenshot(path=str(output/f'{name}-{locale}-{width}.png'))
                        page.locator('.kilas-tool-home').click();page.wait_for_load_state('networkidle')
                        expect(page.locator('#premium-sidebar')).to_have_count(1)
                        page.locator('[data-premium-menu]').click();expect(page.locator('#premium-sidebar')).not_to_have_attribute('inert','')
                        page.keyboard.press('Escape');expect(page.locator('#premium-sidebar')).to_have_attribute('inert','')
                        page.go_back(wait_until='networkidle');expect(page.locator('#premium-sidebar')).to_have_count(0)
                        report.append({'locale':locale,'width':width,'page':name,'no_drawer_back_chat_return':'PASS'})
                    assert not errors and not writes,(errors,writes)
                    context.close()
            browser.close()
        print(json.dumps(report))
    finally:
        server.shutdown();case.doCleanups()

if __name__=='__main__':main()
