"""Focused actual setup/form UX with synthetic admission/media; zero paid IO."""
import json
import os
import threading
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_home as home
from test_kilas_live_translator_browser import MEDIA
from kilas_ai import live_translator as live, audio_branded_voices as branded, audio_provider


def main():
    case=home.HomeTests('test_old_routes_still_render')
    case.id=lambda:'translator-consent-copy-browser'
    case.setUp()
    app=home.fixture.base.f.fixture.app.app
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    try:
        with patch.object(live,'ready',return_value=True),patch.object(branded,'public_choices',return_value=[{'alias':'kilas-male','name':'Kilas Male','style':'Natural'}]),patch.object(audio_provider,'request',side_effect=AssertionError('Paid IO forbidden')),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM','/usr/bin/chromium'),args=['--no-sandbox'])
            for width,locale,expected in ((360,'id','Saya punya izin'),(1440,'en','I have permission'),(360,'es','Tengo permiso'),(1440,'zh','我有权')):
                context=browser.new_context(viewport={'width':width,'height':900})
                cookie=case.client().get_cookie('session')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':locale,'url':origin}])
                context.add_init_script(MEDIA)
                page=context.new_page(); errors=[];state={'starts':[],'policy':0}
                page.on('pageerror',lambda e:errors.append(str(e)))
                def route(r):
                    path=r.request.url.removeprefix(origin)
                    if path.startswith('/privacy'):state['policy']+=1
                    if path=='/kilas-translator/live/sessions/active':
                        r.fulfill(content_type='application/json',body='{"session":null}')
                    elif path=='/kilas-translator/live/sessions':
                        state['starts'].append(r.request.post_data)
                        r.fulfill(status=201,content_type='application/json',body=json.dumps({'session_id':'a'*48}))
                    elif path.endswith('/end'):
                        r.fulfill(content_type='application/json',body='{"status":"ENDED"}')
                    elif r.request.url.startswith(origin):r.continue_()
                    else:r.abort()
                page.route('**/*',route)
                page.goto(origin+'/kilas-translator/live',wait_until='networkidle')
                consent=page.locator('[name=consent]');start=page.locator('#live-setup-form button[type=submit]')
                expect(start).to_be_enabled();expect(consent).not_to_be_checked()
                expect(consent).to_have_attribute('required','')
                expect(page.locator('.live-consent')).to_contain_text(expected)
                expect(page.locator('.live-consent a')).to_have_count(0)
                start.click();assert not state['starts'] and page.evaluate('qa.starts')==0
                consent.check();start.click();page.wait_for_function('qa.starts===1')
                assert len(state['starts'])==1 and 'name="consent"\r\n\r\nyes' in state['starts'][0]
                assert state['policy']==0 and len(context.pages)==1
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.locator('#live-end').click();page.wait_for_function('qa.mics===0')
                assert not errors,errors
                print(f'PASS consent explicit / no link opening / Start / End / localized copy {locale} {width}',flush=True)
                context.close()
            browser.close()
        assert case.client().get('/privacy').status_code==200
    finally:
        server.shutdown();case.doCleanups()


if __name__=='__main__':main()
