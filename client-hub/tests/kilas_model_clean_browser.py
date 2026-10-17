"""Clean selectors and optional composer cost preview; no provider inference."""
import json,shutil,threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_chat_models as f
from kilas_ai import chat_models,image_models


def main():
    case=f.RouteTests('test_catalog_auth_csrf_and_owner_isolation');case.setUp()
    server=make_server('127.0.0.1',0,f.fixture.fixture.base.f.fixture.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}';output=Path('/tmp/kilas-model-clean-browser');output.mkdir(exist_ok=True);rows=[]
    try:
        with patch.object(chat_models,'check',side_effect=f.available),patch.object(image_models,'check',side_effect=lambda m:{**image_models.spec(m),'available':True,'status':'verified'}),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for scheme in ('light','dark'):
                for width in (320,768,1440):
                    context=browser.new_context(viewport={'width':width,'height':900},color_scheme=scheme)
                    cookie=case.client().get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                    for surface,path in [('home','/products/start'),('agent',f'/kilas-ai/agent?conversation={case.conversation}'),('legacy',f'/kilas-ai/threads/{case.thread}')]:
                        page.goto(origin+path,wait_until='networkidle')
                        trigger=page.locator('[data-model-kind=chat] .chat-model-trigger');image_trigger=page.locator('[data-model-kind=image] .chat-model-trigger')
                        expect(trigger).not_to_contain_text('Pilih model');expect(image_trigger).not_to_contain_text('Model gambar')
                        header=page.locator('.home-workspace-top')
                        assert 'US$' not in header.inner_text() and 'USD' not in header.inner_text()
                        trigger.click();dialog=page.locator('#chat-model-dialog');expect(dialog.locator('.chat-model-option')).to_have_count(10)
                        assert 'Pilihan berlaku' not in dialog.inner_text() and 'Kode tidak' not in dialog.inner_text() and 'US$' not in dialog.inner_text()
                        expect(dialog.locator('.model-provider-icon')).to_have_count(10)
                        dialog.get_by_role('radio',name='Claude Sonnet 5.5',exact=False).click()
                        image_trigger.click();dialog=page.locator('#image-model-dialog');expect(dialog.locator('.chat-model-option')).to_have_count(6)
                        assert 'US$' not in dialog.inner_text() and 'Urutan biaya' not in dialog.inner_text() and 'Satu gambar' not in dialog.inner_text()
                        dialog.get_by_role('radio',name='Gemini 3 Pro Image',exact=False).click()
                        expect(trigger.locator('img')).to_have_attribute('data-provider','anthropic');expect(image_trigger.locator('img')).to_have_attribute('data-provider','google')
                        expect(page.locator('[data-image-cost-disclosure]')).to_have_count(0)
                        assert 'US$' not in page.locator('body').inner_text()
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        group=page.locator('.chat-model-controls').bounding_box();head=header.bounding_box();assert abs(group['x']+group['width']/2-head['x']-head['width']/2)<2
                        assert page.locator('.chat-model-trigger .model-provider-icon').evaluate_all("nodes=>nodes.every(e=>e.complete&&e.naturalWidth>0&&getComputedStyle(e).backgroundColor==='rgb(255, 255, 255)'&&e.getBoundingClientRect().width===23&&e.getBoundingClientRect().height===23)")
                        if scheme=='light' and surface=='home':page.screenshot(path=str(output/f'home-{width}.png'))
                        if scheme=='light' and surface=='agent' and width in (320,1440):image_trigger.click();page.screenshot(path=str(output/f'image-dialog-{width}.png'));page.keyboard.press('Escape')
                        assert not errors,errors
                        rows.append({'surface':surface,'width':width,'color_scheme':scheme,'clean_selector':'PASS','centered':'PASS','composer_estimate_removed':'PASS','brand_icons':'PASS','overflow':False})
                    context.close()
            browser.close()
        assert 'fill="#D97757"' in case.client().get('/static/provider-icons/claude.svg').text
        assert 'fill="#8E75B2"' in case.client().get('/static/provider-icons/googlegemini.svg').text
        assert 'fill="#' not in case.client().get('/static/provider-icons/openai.svg').text
        (output/'verification.json').write_text(json.dumps({'checks':rows,'paid_inference':False},indent=2));print(json.dumps(rows))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
