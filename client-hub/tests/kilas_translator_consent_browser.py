"""Actual Chromium -> authenticated Flask consent/Start/End; synthetic media only."""
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_kilas_live_translator_browser import MEDIA
from test_kilas_translator_consent import TranslatorConsentTests
import test_kilas_audio as audio
from kilas_ai import translator_consent as consent


def main():
    app=audio.f.app.app
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(tempfile.gettempdir())/'kilas-translator-permission-browser';output.mkdir(exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM','/usr/bin/chromium'),args=['--no-sandbox'])
            for width,locale,allow in ((360,'id','Izinkan dan mulai'),(1440,'en','Allow and start'),(360,'es','Permitir e iniciar'),(1440,'zh','允许并开始')):
                case=TranslatorConsentTests('test_first_use_has_no_backfill_or_checkbox_and_declares_recipients')
                case.id=lambda locale=locale:'permission-browser-'+locale;case.setUp()
                context=browser.new_context(viewport={'width':width,'height':900})
                cookie=case.client.get_cookie('session')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':locale,'url':origin}])
                context.add_init_script(MEDIA)
                page=context.new_page();errors=[];posts=[];policy=[]
                context.on('request',lambda r: posts.append(r.post_data) if r.url.endswith('/live/sessions') and r.method=='POST' else policy.append(r.url) if '/privacy' in r.url else None)
                context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(origin+'/kilas-translator/live',wait_until='networkidle')
                start=page.locator('#live-setup-form button[type=submit]')
                expect(start).to_be_enabled();expect(start).to_have_text(allow)
                expect(page.locator('#live-setup-form input[type=checkbox]')).to_have_count(0)
                expect(page.locator('#live-permission-notice')).to_contain_text('ElevenLabs')
                expect(page.locator('#live-permission-notice')).to_contain_text('OpenAI')
                assert not case.rows() and page.evaluate('qa.starts')==0
                # A generic form POST without the affirmative submitter cannot grant permission.
                assert page.evaluate("async()=>{const r=await fetch('/kilas-translator/live/sessions',{method:'POST',body:new FormData(document.querySelector('#live-setup-form'))});return r.status}")==409
                assert not case.rows() and page.evaluate('qa.starts')==0
                page.screenshot(path=str(output/f'first-{locale}-{width}.png'),full_page=True)
                start.click();page.wait_for_function('qa.starts===1')
                assert consent._granted(case.user) and len(case.rows())==1
                assert 'name="processing_consent"\r\n\r\naccept' in posts[-1]
                assert not policy and len(context.pages)==1
                page.locator('#live-end').click();page.wait_for_function('qa.mics===0')
                before=case.rows()
                page.reload(wait_until='networkidle');expect(start).to_have_text('Start')
                expect(page.locator('#live-permission-notice')).to_be_hidden()
                page.screenshot(path=str(output/f'remembered-{locale}-{width}.png'),full_page=True)
                start.click();page.wait_for_function('qa.starts===1')
                assert 'name="processing_consent"' not in posts[-1] and case.rows()==before
                page.locator('#live-end').click();page.wait_for_function('qa.mics===0')
                page.locator('#live-permission-settings summary').click();page.locator('#live-permission-revoke').click()
                expect(start).to_have_text(allow);assert case.rows()[0]['revoked_at']
                assert page.evaluate('qa.starts')==1 and page.evaluate('qa.mics')==0
                start.click();page.wait_for_function('qa.starts===2')
                assert not case.rows()[0]['revoked_at']
                # Revoke from a second authenticated tab while the first is listening.
                second=context.new_page();second.goto(origin+'/kilas-translator/live',wait_until='networkidle')
                second.locator('#live-permission-settings summary').click();second.locator('#live-permission-revoke').click()
                page.wait_for_function('qa.mics===0');expect(page.locator('#live-active')).to_be_hidden()
                expect(start).to_have_text(allow);second.close()
                if locale=='en':
                    start.click();page.wait_for_function('qa.starts===3');page.locator('#live-end').click();page.wait_for_function('qa.mics===0')
                    with patch.object(consent,'VERSION','next-browser-version'):
                        # Stale remembered UI must fail server admission before microphone access.
                        start.click();expect(start).to_have_text(allow)
                        assert page.evaluate('qa.starts')==3 and page.evaluate('qa.mics')==0
                        assert len(case.rows())==1
                        start.click();page.wait_for_function('qa.starts===4')
                        assert len(case.rows())==2
                        page.locator('#live-end').click();page.wait_for_function('qa.mics===0')
                assert not policy and page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert not errors,errors
                print(f'PASS actual backend first/repeat/revoke/regrant/cross-tab/no-premature-mic {locale} {width}',flush=True)
                context.close();case.doCleanups()
            browser.close()
    finally:server.shutdown()


if __name__=='__main__':main()
