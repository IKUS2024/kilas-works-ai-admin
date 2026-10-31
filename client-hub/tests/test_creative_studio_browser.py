"""Creative Studio local browser acceptance; external traffic and sends blocked."""
import functools, http.server, json, logging, os, threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import sync_playwright, expect


def check_contrast(page):
    values=page.evaluate(r"""()=>{
      const selectors=['body','.studio-hero h1','.studio-accent','.studio-hero-description','.studio-hero-actions .button','.cs-service-choice h2','.cs-service-choice p','.studio-package-tags>span','.studio-portfolio h2','.studio-portfolio p','.studio-portfolio a','.contact h2','.contact-grid>div>p','.cs-brief label','.cs-brief-prepare','.cs-brief-review summary','.contact-notice','.footer>span'];
      const rgb=s=>(s.match(/[\d.]+/g)||[]).map(Number);
      const lum=c=>c.slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
      return selectors.flatMap(selector=>[...document.querySelectorAll(selector)].filter(e=>e.getClientRects().length).map(e=>{
        let ancestor=e,bg;while(ancestor){let c=rgb(getComputedStyle(ancestor).backgroundColor);if(c.length===3||c[3]===1){bg=c;break;}ancestor=ancestor.parentElement;}
        bg=bg||[255,255,255];let a=lum(rgb(getComputedStyle(e).color)),b=lum(bg);
        return {selector,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
      }));
    }""")
    assert values and all(item['ratio']>=4.49 for item in values),[item for item in values if item['ratio']<4.49]
    return len(values)


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
            browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None)
            for width in (1440,1024,820,393,360,320):
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
                def images_ready():
                    for image in page.locator('img[src*="illustrations/"]').all():
                        if image.is_visible():
                            image.scroll_into_view_if_needed()
                            page.wait_for_function('(e)=>e.complete&&e.naturalWidth>0',arg=image.element_handle())
                    page.mouse.move(0,0)
                    page.evaluate('document.activeElement?.blur();scrollTo(0,0)')
                images_ready()
                check_contrast(page)
                expect(page.locator('#cs-brief-review-panel')).not_to_have_attribute('open','')
                if width<=700:
                    page.locator('[data-cs-menu]').click()
                    expect(page.locator('[data-cs-menu]')).to_have_attribute('aria-expanded','true')
                    expect(page.locator('#studio-navigation')).to_be_visible()
                    page.keyboard.press('Escape')
                    expect(page.locator('[data-cs-menu]')).to_have_attribute('aria-expanded','false')
                    expect(page.locator('#studio-navigation')).not_to_be_visible()
                page.locator('[data-cs-language="en"]').click()
                expect(page.locator('#cs-title')).to_contain_text('Moments into stories.')
                expect(page.locator('.studio-hero-main')).to_have_attribute('alt','Illustration of a videographer filming an event')
                images_ready()
                if width in (393,1440):page.screenshot(path=str(output/f'home-en-{width}.png'),full_page=True)
                page.locator('[data-cs-language="id"]').click()
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
                    images_ready()
                    if kind=='event':
                        premium=page.locator('#cs-event .cs-premium')
                        expect(premium.locator('.cs-price')).to_have_text('Rp5.000.000')
                        expect(premium).to_contain_text('1 fotografer + 1 videografer')
                        expect(premium).not_to_contain_text('2 fotografer')
                        expect(premium).to_contain_text('Pengambilan video udara menggunakan drone')
                        expect(premium.locator('.cs-drone-note')).to_have_text('Pengambilan gambar drone menyesuaikan cuaca, kondisi lokasi, dan izin penerbangan.')
                        expect(page.locator('#cs-social .cs-drone-note')).to_have_count(0)
                        if width in (393,1440):premium.screenshot(path=str(output/f'event-premium-id-{width}.png'),animations='disabled')
                    page.screenshot(path=str(output/f'{kind}-{width}.png'),full_page=True)
                    page.locator('[data-cs-language="en"]').click();fits()
                    expect(page.locator('html')).to_have_attribute('lang','en')
                    expect(page.locator(f'#cs-{kind} h1')).to_have_text('Event Photography & Videography' if kind=='event' else 'Social Media Content Plan')
                    if kind=='event':
                        expect(premium).to_contain_text('1 photographer + 1 videographer')
                        expect(premium).not_to_contain_text('2 photographers')
                        expect(premium).to_contain_text('Aerial video footage captured with a drone')
                        expect(premium.locator('.cs-drone-note')).to_have_text('Drone filming is subject to weather, site conditions, and flight permissions.')
                        if width in (393,1440):premium.screenshot(path=str(output/f'event-premium-en-{width}.png'),animations='disabled')
                    page.locator('[data-cs-language="id"]').click()
                    choice=page.locator('#cs-event .cs-premium [data-service-id]') if kind=='event' else page.locator('#cs-social [data-service-id]').first
                    choice.click()
                    page.wait_for_url('**/#contact')
                    page.locator('#cs-brief-date').fill('2026-11-20')
                    page.locator('#cs-brief-location').fill('Jakarta')
                    page.locator('#cs-brief-needs').fill('Brief sintetis untuk pengujian.')
                    page.locator('.cs-brief-prepare').click()
                    expect(page.locator('#cs-brief-review-panel')).to_have_attribute('open','')
                    message=page.locator('#cs-brief-message').input_value()
                    assert all(s in message for s in ('Premium' if kind=='event' else 'Basic','2026-11-20','Jakarta','Brief sintetis'))
                    assert '2 fotografer' not in message and '2 photographers' not in message
                    edited=message+'\nEdit saya & karakter <aman>.'
                    page.locator('#cs-brief-message').fill(edited)
                    href=page.locator('#cs-contact-whatsapp').get_attribute('href')
                    assert parse_qs(urlsplit(href).query)['text']==[edited]
                    page.locator('[data-cs-language="en"]').click()
                    expect(page.locator('#cs-brief-message')).to_have_value(edited)
                    page.go_back();page.go_forward()
                    expect(page.locator('#cs-brief-message')).to_have_value(edited)
                    if kind=='event':
                        page.locator('.cs-brief-prepare').click()
                        english=page.locator('#cs-brief-message').input_value()
                        assert 'Event Photography & Videography — Premium' in english
                        assert '2 photographers' not in english
                        assert parse_qs(urlsplit(page.locator('#cs-contact-whatsapp').get_attribute('href')).query)['text']==[english]
                    page.locator('.brand').click();page.locator('.brand').click()
                    expect(page.locator('#cs-title')).to_be_visible();fits()
                    page.locator('[data-cs-language="id"]').click()
                # Reload uses the saved UI language; language switch itself retains the edited draft.
                page.locator('[data-cs-language="en"]').click();page.reload(wait_until='networkidle')
                expect(page.locator('html')).to_have_attribute('lang','en')
                expect(page.locator('#cs-title')).to_contain_text('Moments into stories.')
                page.locator('#cs-brief-review-panel summary').click()
                # Empty messages cannot open WhatsApp, nor can preparing a draft send it.
                page.locator('#cs-brief-message').fill('  ')
                expect(page.locator('#cs-contact-whatsapp')).to_have_attribute('aria-disabled','true')
                before=page.url;page.locator('#cs-contact-whatsapp').click(force=True);assert page.url==before
                assert len(context.pages)==1
                assert not writes and not external and not errors,(writes,external,errors)
                reports.append({'width':width,'layout_navigation_language_editable_brief_no_external_io':'PASS'})
                context.close()
            for width in (393,1440):
                context=browser.new_context(viewport={'width':width,'height':900},reduced_motion='reduce')
                page=context.new_page();page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                for kind in ('event','social'):
                    page.goto(origin+'/creative-services-site/#cs-'+kind,wait_until='networkidle')
                    page.evaluate('document.fonts.ready')
                    for image in page.locator('img[src*="illustrations/"]').all():
                        if image.is_visible():
                            image.scroll_into_view_if_needed()
                            page.wait_for_function('(e)=>e.complete&&e.naturalWidth>0',arg=image.element_handle())
                    page.mouse.move(0,0);page.evaluate('document.activeElement?.blur();scrollTo(0,0)')
                    page.screenshot(path=str(output/f'{kind}-clean-{width}.png'),full_page=True)
                context.close()
            # No-JS deep links remain usable and never load third-party galleries.
            context=browser.new_context(java_script_enabled=False,viewport={'width':390,'height':844})
            page=context.new_page();page.goto(origin+'/creative-services-site/#cs-event')
            expect(page.locator('#cs-event')).to_be_visible()
            expect(page.locator('[data-cs-menu]')).not_to_be_visible()
            browser.close()
        (output/'verification.json').write_text(json.dumps(reports,indent=2))
        print(json.dumps(reports,indent=2))
    finally:server.shutdown()

if __name__=='__main__':main()
