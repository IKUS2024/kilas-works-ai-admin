"""No Chat options row; native tasks and composer survive mobile keyboard reflow."""
import json,logging,os,threading
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_chat_models as fixture
import app


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case=fixture.RouteTests('test_catalog_auth_csrf_and_owner_isolation');case.id=lambda:'options-removed';case.setUp()
    server=make_server('127.0.0.1',0,app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    out=Path(os.environ.get('KILAS_OPTIONS_QA','/tmp/kilas-options-removed'));out.mkdir(exist_ok=True)
    report=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/chromium')
            for width in (1440,390,320):
                context=browser.new_context(viewport={'width':width,'height':844});cookie=case.client().get_cookie('session')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}]);page=context.new_page();errors=[];writes=[]
                page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:writes.append(r.url) if r.method not in ('GET','HEAD') else None)
                page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                page.goto(origin+'/products/start',wait_until='networkidle')
                expect(page.locator('.home-chat-options')).to_have_count(0)
                for task in ('chat','voiceover'):
                    expect(page.locator('[data-home-task="'+task+'"]').first).to_be_visible()
                expect(page.locator('.home-tool-selector a[href="/kilas-translator/live"]')).to_be_visible()
                expect(page.locator('#ai-input')).to_be_visible();expect(page.locator('#ai-send')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                if width<500:
                    page.locator('#ai-input').focus()
                    page.evaluate("Object.defineProperty(visualViewport,'height',{configurable:true,value:470});visualViewport.dispatchEvent(new Event('resize'))")
                    expect(page.locator('.home-chat-options')).to_have_count(0)
                    for task in ('chat','voiceover'):expect(page.locator('[data-home-task="'+task+'"]').first).to_be_visible()
                    assert page.locator('#ai-send').evaluate('e=>e.getBoundingClientRect().bottom<=visualViewport.height+visualViewport.offsetTop+1')
                    page.evaluate("delete visualViewport.height;visualViewport.dispatchEvent(new Event('resize'))")
                page.screenshot(path=str(out/f'chat-{width}.png'),full_page=True)
                assert not errors and not writes,(errors,writes)
                report.append({'width':width,'options_row':'absent','tasks_composer':'PASS','page_errors':0,'network_writes':0});context.close()
            browser.close()
    finally:server.shutdown();case.tearDown()
    (out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))

if __name__=='__main__':main()
