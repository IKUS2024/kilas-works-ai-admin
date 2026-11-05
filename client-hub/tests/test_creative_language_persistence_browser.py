"""Exercise real CSRF-protected /language POST and HttpOnly preference persistence."""
import json,logging,shutil,threading
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from test_creative_checkout import CreativeCheckoutTests


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case=CreativeCheckoutTests('test_repeated_submit_and_persistence');case.id=lambda:'creative-language-persistence';case.setUp()
    server=make_server('127.0.0.1',0,case.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    results=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            ctx=browser.new_context(viewport={'width':393,'height':900})
            cookie=case.client.get_cookie('session');ctx.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
            ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
            page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            for lang in ('id','en','es','zh'):
                page.goto(origin+'/creative-services/',wait_until='networkidle')
                response=ctx.request.post(origin+'/language',form={'language':lang,'csrf_token':page.locator('#creative-app-context').evaluate('e=>JSON.parse(e.textContent).csrfToken'),'next':'/creative-services/'},max_redirects=0)
                assert response.status==303,response.status
                assert 'HttpOnly' in response.headers['set-cookie']
                assert 'SameSite=Lax' in response.headers['set-cookie']
                loaded = page.reload(wait_until='networkidle')
                assert loaded.headers['cache-control']=='private, no-store'
                expect(page.locator('html')).to_have_attribute('lang',lang)
                assert 'kilas_language' not in page.evaluate('document.cookie')
                assert next(c for c in ctx.cookies() if c['name']=='kilas_language')['httpOnly']
                assert page.title()=='Kilas Works — '+{'id':'Jasa Kreatif','en':'Creative Services','es':'Servicios creativos','zh':'创意服务'}[lang]
                page.goto(origin+'/products/catalog',wait_until='networkidle');expect(page.locator('html')).to_have_attribute('lang',lang)
                page.locator('.catalog-services').click();page.wait_for_load_state('networkidle');expect(page.locator('html')).to_have_attribute('lang',lang)
                page.goto(origin+'/creative-services/checkout/creative_event_basic',wait_until='networkidle');expect(page.locator('html')).to_have_attribute('lang',lang)
                page.go_back(wait_until='networkidle');expect(page.locator('html')).to_have_attribute('lang',lang)
                # Local control must persist through the same protected endpoint and preserve edited input
                page.locator('#cs-brief-message').evaluate("e=>e.value='Keep edited customer draft. 1.25 example.com'")
                next_lang={'id':'en','en':'es','es':'zh','zh':'id'}[lang]
                with page.expect_response(lambda response:response.url==origin+'/language' and response.request.method=='POST') as saved:
                    page.locator('[data-cs-language='+next_lang+']').click()
                assert saved.value.status==303
                expect(page.locator('[data-cs-language='+next_lang+']')).to_be_enabled()
                expect(page.locator('html')).to_have_attribute('lang',next_lang)
                assert next(c for c in ctx.cookies() if c['name']=='kilas_language')['value']==next_lang
                assert page.locator('#cs-brief-message').input_value()=='Keep edited customer draft. 1.25 example.com'
                page.reload(wait_until='networkidle');expect(page.locator('html')).to_have_attribute('lang',next_lang)
                results.append({'language':lang,'real_language_post':True,'http_only':True,'reload_catalog_checkout_back':True,'local_button_post_csrf':True,'edited_draft_preserved':True})
            # Invalid CSRF must not replace the preference
            response=ctx.request.post(origin+'/language',form={'language':'en','csrf_token':'invalid','next':'/creative-services/'},max_redirects=0)
            assert response.status==400
            page.reload(wait_until='networkidle');expect(page.locator('html')).to_have_attribute('lang','id')
            assert not errors,errors
            browser.close()
        out=Path('/tmp/kilas-language-persistence.json');out.write_text(json.dumps(results,indent=2));print('PASS real /language POST, HttpOnly, reload/navigation/back, CSRF and local controls in all 4 languages')
    finally:server.shutdown();case.tearDown()

if __name__=='__main__':main()
