"""Synthetic same-site viewer acceptance on the real app; no provider calls."""
import json,logging,os,threading
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_image_viewer as fixture
import app


def main():
    out=Path(os.environ.get('KILAS_IMAGE_VIEWER_ARTIFACTS','/tmp/kilas-image-viewer-browser'));out.mkdir(parents=True,exist_ok=True)
    case=fixture.ImageViewerTests();case.id=lambda:'image-viewer-browser';case.setUp();data=case.data
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server=make_server('127.0.0.1',0,app.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    cookie=case.client().get_cookie('session');report=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,**({'executable_path':'/usr/bin/chromium'} if Path('/usr/bin/chromium').exists() else {}),args=['--no-sandbox'])
            for width in (390,1440):
                ctx=browser.new_context(viewport={'width':width,'height':900},accept_downloads=True)
                ctx.add_cookies([{'name':'session','value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}])
                external=[];ctx.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) or route.request.url.startswith('blob:') else (external.append(route.request.url),route.abort())[-1])
                page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(origin+data['thread'],wait_until='networkidle');anchor=page.locator('.ai-image-result a[data-kilas-image]').first
                history=page.evaluate('history.length');anchor.click();dialog=page.locator('.kilas-image-viewer');expect(dialog).to_be_visible();expect(dialog.locator('img')).to_be_visible()
                assert page.evaluate('history.length')==history+1
                anchor.dispatch_event('click');assert page.evaluate('history.length')==history+1
                assert len(ctx.pages)==1 and page.url==origin+data['thread']
                assert page.locator('[data-chat-model-selector]').count()==0
                for _ in range(5):
                    page.keyboard.press('Tab');assert page.evaluate("document.querySelector('.kilas-image-viewer').contains(document.activeElement)")
                page.screenshot(path=str(out/f'managed-synthetic-viewer-{width}.png'),animations='disabled')
                with page.expect_download() as info:dialog.locator('a').click()
                download=info.value;assert Path(download.path()).read_bytes()==data['raw'];assert download.suggested_filename=='synthetic-viewer.png'
                page.keyboard.press('Escape');expect(dialog).not_to_be_visible();expect(anchor).to_be_focused();page.wait_for_function("!history.state?.kilasImagePreview")
                anchor.click();expect(dialog.locator('img')).to_be_visible();page.go_back();expect(dialog).not_to_be_visible();expect(anchor).to_be_focused()
                # Exercise the actual image SSE handler, not only delegated DOM insertion.
                events='event: image\ndata: '+json.dumps({'preview_url':data['preview'],'url':data['preview'].split('?')[0]})+'\n\nevent: done\ndata: {}\n\n'
                page.route('**/send',lambda route:route.fulfill(status=200,content_type='text/event-stream',body=events))
                page.locator('#ai-input').fill('Synthetic image stream fixture');page.locator('#ai-send').click()
                streamed=page.locator('.ai-image-result a[data-kilas-image]').last
                expect(page.locator('.ai-image-result a[data-kilas-image]')).to_have_count(2)
                streamed.click();expect(dialog.locator('img')).to_be_visible();page.keyboard.press('Escape');page.wait_for_function("!history.state?.kilasImagePreview")
                page.unroute('**/send')
                # Queued artifact and dynamically inserted (stream-like) markup use the same delegate.
                page.evaluate("url=>{const a=document.createElement('a');a.href=url;a.dataset.kilasImage='';a.dataset.imageName='Synthetic queued image';a.textContent='Synthetic queued image';a.id='synthetic-queued';document.querySelector('#ai-messages').prepend(a)}",data['artifact'])
                queued=page.locator('#synthetic-queued');queued.click();expect(dialog.locator('img')).to_be_visible()
                with page.expect_download() as info:dialog.locator('a').click()
                assert Path(info.value.path()).read_bytes()==data['raw'];page.evaluate("document.querySelector('.kilas-image-viewer button').click();document.querySelector('#synthetic-queued').click()");expect(dialog).not_to_be_visible();page.wait_for_function("!history.state?.kilasImagePreview")
                # 401, redirects, corrupt bytes and non-image responses never yield a download.
                for response in ({'status':401,'body':'unauthorized'},{'status':302,'headers':{'Location':'https://example.invalid/provider'}},{'status':200,'content_type':'text/html','body':'<script>bad</script>'},{'status':200,'content_type':'image/png','body':'broken image'}):
                    def fail_image(route):route.fulfill(**response)
                    page.route('**/attachments/*?inline=1',fail_image);anchor.click();expect(dialog.locator('[role=status]')).to_contain_text('Gambar tidak dapat dibuka');expect(dialog.locator('a')).not_to_be_visible();page.keyboard.press('Escape');page.wait_for_function("!history.state?.kilasImagePreview");page.unroute('**/attachments/*?inline=1')
                assert page.evaluate("KilasImageViewer.safeURL('https://example.invalid/provider')===null && KilasImageViewer.safeURL('/login')===null")
                assert not errors,errors
                assert not any('example.invalid' in x for x in external),external
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                report.append({'width':width,'original_download':True,'same_tab':True,'back_escape_focus':True,'double_click':True,'queued_delegate':True,'actual_sse_handler_mocked':True,'auth_and_corrupt_errors':True,'js_errors':errors})
                ctx.close()
            browser.close()
        (out/'verification.json').write_text(json.dumps({'result':'PASS','cases':report,'provider_calls':'NOT RUN','paid_calls':0},indent=2));print(json.dumps({'result':'PASS','cases':len(report),'artifacts':str(out)}))
    finally:server.shutdown();case.doCleanups()

if __name__=='__main__':main()
