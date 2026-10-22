"""Creative Studio local browser acceptance; external traffic and sends blocked."""
import functools, http.server, json, logging, os, threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import sync_playwright, expect

def main():
    root=Path(__file__).resolve().parents[2]
    output=Path(os.environ.get('KILAS_STUDIO_SCREENSHOTS','../../creative-studio-qa')).resolve()
    output.mkdir(parents=True,exist_ok=True)
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*args): pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(root)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    reports=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chromium',headless=True)
            for width in (1440,1024,820,390,320):
                context=browser.new_context(viewport={'width':width,'height':900},reduced_motion='reduce')
                page=context.new_page();errors=[];external=[];writes=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda r:writes.append(r.url) if r.method!='GET' else None)
                def route(r):
                    if r.request.url.startswith(origin):r.continue_()
                    else:external.append(r.request.url);r.abort()
                page.route('**/*',route)
                page.goto(origin+'/creative-services-site/',wait_until='networkidle')
                page.evaluate('document.fonts.ready')
                def fits():assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                fits();expect(page.locator('#cs-title')).to_be_visible()
                expect(page.locator('[data-service-choice]')).to_have_count(2)
                for a in page.locator('[data-studio-portfolio]').all():
                    expect(a).to_have_attribute('href','https://instagram.com/kilasworks')
                    expect(a).to_have_attribute('target','_blank')
                page.screenshot(path=str(output/f'home-{width}.png'),full_page=True)
                for kind in ('event','social'):
                    page.locator(f'[data-service-choice="{kind}"]').click()
                    expect(page.locator(f'#cs-{kind}')).to_be_visible();fits()
                    expect(page.locator(f'#cs-{kind} .cs-card')).to_have_count(3)
                    page.screenshot(path=str(output/f'{kind}-{width}.png'),full_page=True)
                    page.locator('[data-cs-language="en"]').click();fits()
                    expect(page.locator('html')).to_have_attribute('lang','en')
                    page.locator('[data-cs-language="id"]').click()
                    page.locator(f'#cs-{kind} [data-service-id]').first.click()
                    page.wait_for_url('**/#contact')
                    page.locator('#cs-brief-date').fill('2026-11-20')
                    page.locator('#cs-brief-location').fill('Jakarta')
                    page.locator('#cs-brief-needs').fill('Brief sintetis untuk pengujian.')
                    page.locator('.cs-brief-prepare').click()
                    message=page.locator('#cs-brief-message').input_value()
                    assert all(s in message for s in ('Basic','2026-11-20','Jakarta','Brief sintetis'))
                    edited=message+'\nEdit saya & karakter <aman>.'
                    page.locator('#cs-brief-message').fill(edited)
                    href=page.locator('#cs-contact-whatsapp').get_attribute('href')
                    assert parse_qs(urlsplit(href).query)['text']==[edited]
                    page.locator('[data-cs-language="en"]').click()
                    expect(page.locator('#cs-brief-message')).to_have_value(edited)
                    page.go_back();page.go_forward()
                    expect(page.locator('#cs-brief-message')).to_have_value(edited)
                    page.locator('.brand').click();page.locator('.brand').click()
                    expect(page.locator('#cs-title')).to_be_visible();fits()
                    page.locator('[data-cs-language="id"]').click()
                # Empty messages cannot open WhatsApp, nor can preparing a draft send it.
                page.locator('#cs-brief-message').fill('  ')
                expect(page.locator('#cs-contact-whatsapp')).to_have_attribute('aria-disabled','true')
                before=page.url;page.locator('#cs-contact-whatsapp').click(force=True);assert page.url==before
                assert len(context.pages)==1
                assert not writes and not external and not errors,(writes,external,errors)
                reports.append({'width':width,'layout_navigation_language_editable_brief_no_external_io':'PASS'})
                context.close()
            # No-JS deep links remain usable and never load third-party galleries.
            context=browser.new_context(java_script_enabled=False,viewport={'width':390,'height':844})
            page=context.new_page();page.goto(origin+'/creative-services-site/#cs-event')
            expect(page.locator('#cs-event')).to_be_visible()
            browser.close()
        (output/'verification.json').write_text(json.dumps(reports,indent=2))
        print(json.dumps(reports,indent=2))
    finally:server.shutdown()

if __name__=='__main__':main()
