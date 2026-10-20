"""Responsive alternate UI and ambiguous retry; local synthetic provider only."""
import json
import shutil
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_kilas_voice_alternate import AlternateTests
from test_kilas_audio import f, provider


def main():
    AlternateTests.setUpClass()
    server=make_server('127.0.0.1',0,f.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    out=Path('/tmp/kilas-voice-alternate-review');out.mkdir(exist_ok=True)
    report=[]
    try:
        with sync_playwright() as pw,patch.object(provider,'voices',return_value=[{'id':'actualVoice123','name':'QA Calm','style':'Warm'}]),patch.object(provider,'speech',return_value=(AlternateTests.audio,'synthetic')) as speech:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (390,768,1440):
                case=AlternateTests('test_duplicate_key_and_cross_source_conflict');case.id=lambda:'browser-alternate-'+str(width);case.setUp()
                ident=case.source(script='Keep these exact words.')
                context=browser.new_context(viewport={'width':width,'height':1000},has_touch=width<800)
                cookie=case.client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en' if width==1440 else 'id','url':origin}])
                page=context.new_page();errors=[];posts=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                page.goto(origin+f'/kilas-translator/jobs/{ident}?mode=voiceover',wait_until='networkidle')
                button=page.locator('[data-audio-alternate]');expect(button).to_be_visible()
                expect(button).to_have_text('Generate another version' if width==1440 else 'Buat versi lain')
                page.locator('#audio-script').fill('Changed draft must never reach this take.')
                # Media retry is read-only and does not submit another job.
                page.locator('#audio-result audio').evaluate("e=>e.dispatchEvent(new Event('error'))")
                reload=page.locator('[data-audio-reload]');expect(reload).to_be_visible();reload.click();expect(reload).to_have_count(0)
                # Headers arrive but JSON never resolves: abort must release controls.
                if width==390:
                    page.evaluate("""() => {window.qaFetch=window.fetch;window.qaTimer=window.setTimeout;window.setTimeout=(fn,ms,...args)=>qaTimer(fn,ms===90000?100:ms,...args);window.fetch=(url,options)=>String(url).endsWith('/alternate')?Promise.resolve({redirected:false,ok:true,json:()=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError'))))}):qaFetch(url,options);} """)
                    button.click();expect(page.locator('#audio-error')).to_contain_text('Periksa riwayat');expect(button).to_be_enabled()
                    page.evaluate('window.fetch=qaFetch;window.setTimeout=qaTimer')
                start=speech.call_count
                def ambiguous(route):
                    posts.append(route.request.post_data)
                    route.fetch()  # Accepted by local mocked backend; response is lost.
                    route.abort()
                page.route('**/jobs/*/alternate',ambiguous)
                button.evaluate('b=>{b.click();b.click()}')
                expect(page.locator('#audio-error')).to_be_visible();expect(button).to_be_enabled()
                assert len(posts)==1 and speech.call_count==start+1
                page.reload(wait_until='networkidle')
                def retry(route):
                    posts.append(route.request.post_data);route.continue_()
                page.unroute('**/jobs/*/alternate');page.route('**/jobs/*/alternate',retry)
                page.locator('[data-audio-alternate]').click()
                page.wait_for_url(lambda url:url.split('?')[0]!=origin+f'/kilas-translator/jobs/{ident}',timeout=15000)
                expect(page.locator('#audio-result audio')).to_be_visible()
                assert speech.call_count==start+1
                # Multipart boundaries differ, but the durable operation key must match.
                def key(body):return body.split('name="operation_key"\r\n\r\n')[1].split('\r\n')[0]
                assert key(posts[0])==key(posts[1])
                assert speech.call_args.args==('Keep these exact words.','actualVoice123','en')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.locator('#audio-result').scroll_into_view_if_needed();page.screenshot(path=str(out/f'alternate-{width}.png'))
                assert not errors,errors
                report.append({'width':width,'original_preserved_new_take':True,'double_click_single_post':True,'ambiguous_reload_same_key':True,'read_only_audio_retry':True,'no_overflow':True,'paid_calls':0})
                context.close();case.doCleanups()
            browser.close()
        (out/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:server.shutdown()


if __name__=='__main__':main()
