"""2026 studio acceptance: local-only browser regression, never sends messages."""
import functools, http.server, json, shutil, threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import sync_playwright, expect


def main():
    root=Path(__file__).resolve().parents[2]
    output=Path('/tmp/creative-rate-card-qa');output.mkdir(exist_ok=True)
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(root/'creative-services-site')))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    reports=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (320,393,820,1440):
                ctx=browser.new_context(viewport={'width':width,'height':900},reduced_motion='reduce')
                ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(origin,wait_until='networkidle')
                for lang in ('id','en','es','zh'):
                    page.locator('[data-cs-language='+lang+']').click()
                    assert page.locator('html').get_attribute('lang')==lang
                    for sid in ('event','social','commercial','editing'):
                        page.goto(origin+'/#cs-'+sid,wait_until='networkidle')
                        expect(page.locator('#cs-'+sid)).to_be_visible()
                        expect(page.locator('#cs-service-choices')).to_be_hidden()
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,lang,sid)
                        assert page.locator('.cs-panel:visible').count()==1
                        assert page.locator('#cs-'+sid+' h1').evaluate('e=>e.getBoundingClientRect().top')>=page.locator('.header').evaluate('e=>e.getBoundingClientRect().bottom'),(width,lang,sid,'covered')
                        if sid=='editing':
                            expect(page.locator('#cs-editing')).to_contain_text('Rp250.000')
                            expect(page.locator('#cs-editing')).to_contain_text('Basic Social Media Editing')
                            assert page.locator('#cs-editing .cs-card').count()==4
                            expect(page.locator('#cs-editing')).to_contain_text('Rp350.000–Rp500.000')
                            expect(page.locator('#cs-editing')).to_contain_text('Rp600.000–Rp900.000')
                            expect(page.locator('#cs-editing')).to_contain_text('Rp1.500.000')
                        quote=page.locator('#cs-'+sid+' [data-quote-choice]').first
                        selected=quote.get_attribute('data-service-'+lang)
                        quote.click()
                        expect(page).to_have_url(origin+'/#contact')
                        expect(page.locator('#selected-service')).to_be_visible()
                        assert selected in page.locator('#selected-service').inner_text()
                        assert selected in page.locator('#cs-brief-message').input_value()
                        if lang=='id' and width in (393,1440):
                            page.goto(origin+'/#cs-'+sid,wait_until='networkidle')
                            page.screenshot(path=str(output/f'{sid}-{width}.png'),full_page=True)
                    page.goto(origin,wait_until='networkidle')
                    for dest in ('#portfolio','#service-list','#portfolio','#contact','#service-list'):
                        if width<=1100:page.locator('[data-cs-menu]').click()
                        page.locator('#studio-navigation a[href="'+dest+'"]').click()
                        expect(page).to_have_url(origin+'/'+dest)
                        assert page.locator('.header').get_attribute('class')=='header'
                        top=page.locator(dest).evaluate('e=>e.getBoundingClientRect().top')
                        bottom=page.locator('.header').evaluate('e=>e.getBoundingClientRect().bottom')
                        assert top>=bottom-1,(width,lang,dest,top,bottom)
                    # Same destination click must still navigate and close the menu.
                    if width<=1100:page.locator('[data-cs-menu]').click()
                    page.locator('#studio-navigation a[href="#service-list"]').click()
                    assert page.locator('.header').get_attribute('class')=='header'
                    page.locator('[data-service-choice=event]').click()
                    page.locator('#cs-event .cs-service-tabs a[href="#cs-commercial"]').click()
                    expect(page.locator('#cs-commercial')).to_be_visible()
                    page.go_back();expect(page.locator('#cs-event')).to_be_visible()
                    page.go_forward();expect(page.locator('#cs-commercial')).to_be_visible()
                    page.locator('#cs-commercial .cs-back-services').click()
                    expect(page.locator('#cs-service-choices')).to_be_visible()
                    page.locator('#cs-brief-needs').fill('Synthetic brief, do not send.')
                    page.locator('.cs-brief-prepare').click()
                    assert 'Synthetic brief, do not send.' in page.locator('#cs-brief-message').input_value()
                    assert 'Synthetic brief' in parse_qs(urlsplit(page.locator('#cs-contact-whatsapp').get_attribute('href')).query)['text'][0]
                    if width<=1100:
                        page.locator('[data-cs-menu]').click();page.keyboard.press('Escape')
                        expect(page.locator('[data-cs-menu]')).to_have_attribute('aria-expanded','false')
                    page.goto(origin,wait_until='networkidle')
                    assert page.locator('[data-cs-id][data-cs-en]').evaluate_all('(es)=>es.every(e=>e.textContent===e.getAttribute("data-cs-"+document.documentElement.lang))')
                    if lang=='id' and width in (393,1440):page.screenshot(path=str(output/f'home-{width}.png'),full_page=True)
                    assert not errors,errors
                    reports.append({'width':width,'language':lang,'views':4,'result':'PASS'})
                ctx.close()
            browser.close()
        (output/'results.json').write_text(json.dumps(reports,indent=2))
        print('PASS: 64 detail views, 16 home states, anchors/menu/back/forward, selected quote, four languages, no external sends.')
    finally:server.shutdown()

if __name__=='__main__':main()
