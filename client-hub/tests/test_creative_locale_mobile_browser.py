"""Four app languages and mobile geometry, using disposable synthetic checkout data."""
import json, logging, os, shutil, threading
from pathlib import Path
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from test_creative_checkout import CreativeCheckoutTests
from creative_i18n import CATALOG


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case=CreativeCheckoutTests('test_repeated_submit_and_persistence');case.id=lambda:'creative-locale-mobile';case.setUp()
    server=make_server('127.0.0.1',0,case.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    out=Path(os.environ.get('KILAS_LOCALE_SCREENSHOTS','/tmp/kilas-locale-mobile'));out.mkdir(parents=True,exist_ok=True)
    results=[]
    try:
        invoice,_=case.create()
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (360,393,430,1180):
                for lang in ('id','en','es','zh'):
                    ctx=browser.new_context(viewport={'width':width,'height':900},reduced_motion='reduce')
                    cookie=case.client.get_cookie('session')
                    ctx.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':lang,'url':origin,'httpOnly':True}])
                    ctx.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                    page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    for name,path in [('products','/products/catalog'),('creative','/creative-services/'),('checkout','/creative-services/checkout/creative_social_basic'),('payment',f'/creative-services/payment/{invoice}')]:
                        page.goto(origin+path,wait_until='networkidle')
                        assert page.locator('html').get_attribute('lang')==lang,(name,lang)
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(name,width,lang)
                        if name=='creative':
                            assert page.locator('[data-cs-id][data-cs-en]').evaluate_all('(els)=>els.every(e=>e.textContent===e.getAttribute("data-cs-"+document.documentElement.lang))')
                            assert page.locator('[data-cs-alt-id]').evaluate_all('(els)=>els.every(e=>e.alt===e.getAttribute("data-cs-alt-"+document.documentElement.lang))')
                            assert page.locator('.studio-portfolio-copy h2').evaluate('e=>getComputedStyle(e,"::after").content')=='none'
                            if width<700:assert page.locator('.cs-business-info dd').first.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)')==16
                            page.locator('#contact').screenshot(path=str(out/f'contact-{lang}-{width}.png'))
                            page.locator('#cs-brief-needs').fill('Keep my original customer text. 1.25 example.com')
                            page.locator('.cs-brief-prepare').click()
                            assert 'Keep my original customer text. 1.25 example.com' in page.locator('#cs-brief-message').input_value()
                        elif name=='products':
                            if width<600:assert page.locator('.catalog-card h2').first.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)')==21
                        else:
                            heading=CATALOG['Checkout' if name=='checkout' else 'Pembayaran'][lang]
                            assert page.locator('h1').inner_text()==heading
                            assert not page.locator('h1').inner_text().endswith('.')
                            image=page.locator('.selected-service img');image.evaluate('(e)=>e.decode()')
                            metrics=image.evaluate('e=>{let r=e.getBoundingClientRect();return [r.width/r.height,e.naturalWidth/e.naturalHeight,getComputedStyle(e).objectFit]}')
                            assert abs(metrics[0]-metrics[1])<.02 and metrics[2]=='contain',metrics
                            if name=='checkout':
                                assert page.locator('label[for=name]>span').first.inner_text()==CATALOG['Nama lengkap'][lang]
                                page.locator('#notes').fill('Customer text. example.com 1.25')
                                page.locator('#addon').select_option('micro')
                                assert page.locator('#notes').input_value()=='Customer text. example.com 1.25'
                                assert page.locator('#total').inner_text()=='Rp6.500.000'
                        page.screenshot(path=str(out/f'{name}-{lang}-{width}.png'),full_page=True)
                        results.append({'page':name,'width':width,'language':lang,'result':'PASS'})
                    assert not errors,errors
                    ctx.close()
            # No preference means the same English default as App Language
            ctx=browser.new_context();page=ctx.new_page();page.goto(origin+'/creative-services/')
            assert page.locator('html').get_attribute('lang')=='en'
            page.locator('[data-cs-language=es]').click()
            page.wait_for_function('document.documentElement.lang === "es"')
            assert next(c['value'] for c in ctx.cookies() if c['name']=='kilas_language')=='es'
            assert next(c['httpOnly'] for c in ctx.cookies() if c['name']=='kilas_language')
            page.goto(origin+'/creative-services/checkout/creative_event_basic')
            assert page.locator('html').get_attribute('lang')=='es'
            ctx.close();browser.close()
        (out/'results.json').write_text(json.dumps(results,indent=2))
        print(f'PASS {len(results)} language/mobile cases; screenshots: {out}')
    finally:server.shutdown();case.tearDown()

if __name__=='__main__':main()
