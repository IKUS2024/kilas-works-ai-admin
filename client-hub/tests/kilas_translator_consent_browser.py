"""Simple explicit consent: Chromium -> authenticated Flask, synthetic media only."""
import os
import threading
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_kilas_live_translator_browser import MEDIA
from test_kilas_translator_consent import TranslatorConsentTests
import test_kilas_audio as audio


def main():
    server=make_server('127.0.0.1',0,audio.f.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM','/usr/bin/chromium'),args=['--no-sandbox'])
            for width,locale in ((360,'id'),(1440,'en'),(360,'es'),(1440,'zh')):
                case=TranslatorConsentTests('test_simple_setup_has_unchecked_required_checkbox_without_inline_policy')
                case.id=lambda locale=locale:'simple-consent-browser-'+locale;case.setUp()
                context=browser.new_context(viewport={'width':width,'height':900});cookie=case.client.get_cookie('session')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':locale,'url':origin}]);context.add_init_script(MEDIA)
                context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                page=context.new_page();errors=[];posts=[];policy=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                context.on('request',lambda r:posts.append(r.post_data) if r.url.endswith('/live/sessions') and r.method=='POST' else policy.append(r.url) if '/privacy' in r.url else None)
                page.goto(origin+'/kilas-translator/live',wait_until='networkidle')
                start=page.locator('#live-setup-form button[type=submit]');checkbox=page.locator('[name=consent]')
                expect(start).to_be_enabled();expect(start).to_have_text('Start');expect(checkbox).not_to_be_checked()
                expect(checkbox).to_have_attribute('required','');expect(page.locator('.live-consent a')).to_have_count(0)
                expect(page.locator('#live-permission-notice,#live-permission-settings')).to_have_count(0)
                start.click();assert not posts and page.evaluate('qa.starts')==0 and not case.rows()
                checkbox.check();start.click();page.wait_for_function('qa.starts===1')
                assert len(posts)==1 and 'name="consent"\r\n\r\nyes' in posts[0]
                assert not policy and len(context.pages)==1
                page.locator('#live-end').click();page.wait_for_function('qa.mics===0')
                page.reload(wait_until='networkidle');expect(checkbox).not_to_be_checked();expect(start).to_have_text('Start')
                assert not case.rows() and not errors,errors
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                print(f'PASS simple checkbox / no consent no send / explicit Start / End / fresh reload {locale} {width}',flush=True)
                context.close();case.doCleanups()
            browser.close()
    finally:server.shutdown()


if __name__=='__main__':main()
