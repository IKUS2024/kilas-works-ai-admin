"""Restored existing Chat UI, real routes/SQLite, synthetic providers; loopback only."""
import json, logging, os, threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_chat_models as fixture
from kilas_ai import copilot, providers, store
from kilas_chat_sidebar_browser_helpers import open_chat_sidebar
import app


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case=fixture.RouteTests();case.setUp()
    server=make_server('127.0.0.1',0,app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path('/tmp/kilas-chat-restoration');output.mkdir(exist_ok=True)
    report=[];calls=[];fail=[False]
    def answer(mode,messages,**kwargs):
        calls.append(str(messages))
        if fail[0]:raise providers.ProviderError('synthetic_failure')
        yield {'type':'delta','text':'Synthetic restored Chat answer.'}
        yield {'type':'usage','input_tokens':50,'output_tokens':10}
        yield {'type':'finish','reason':'stop'}
    try:
        with patch.object(providers,'stream',side_effect=answer),sync_playwright() as pw:
            executable=os.environ.get('KILAS_QA_CHROMIUM') or ('/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None)
            browser=pw.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}),args=['--no-sandbox'])
            for width in (360,393,1440):
                for locale in ('en','id','es','zh'):
                    # Independent synthetic accounts keep the matrix below each real quota.
                    scenario=fixture.RouteTests();scenario.id=lambda: 'restored-'+locale+'-'+str(width);scenario.setUp()
                    cookie=scenario.client().get_cookie('session')
                    hidden=copilot.create(scenario.owner)
                    store.append_user_once(scenario.owner,hidden,'VOICE_ONLY_SYNTHETIC_HISTORY','SMART','voice_history_browser_1234')
                    context=browser.new_context(viewport={'width':width,'height':900})
                    context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':locale,'url':origin}])
                    page=context.new_page();errors=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                    # Home keeps its original agent/non-agent choice; both remain available.
                    page.goto(origin+'/products/start',wait_until='networkidle')
                    assert page.locator('#ai-input,#agent-message').count()==1
                    assert page.locator('[data-kilas-feature=copilot],#copilot').count()==0
                    assert page.locator('html').get_attribute('lang')==locale
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(output/f'home-{locale}-{width}.png'))
                    thread=store.create_thread(scenario.owner)
                    store.append_user_once(scenario.owner,thread,'SYNTHETIC_SAVED_CHAT','FAST','browser_saved_'+str(thread))
                    path=f'/kilas-ai/threads/{thread}'
                    page.goto(origin+path,wait_until='networkidle')
                    expect(page.locator('#ai-messages')).to_contain_text('SYNTHETIC_SAVED_CHAT')
                    field=page.locator('#ai-input');send=page.locator('#ai-send')
                    field.fill('Synthetic attachment test')
                    page.locator('#ai-files').set_input_files({'name':'example.txt','mimeType':'text/plain','buffer':b'SYNTHETIC attachment content only.'})
                    expect(page.locator('#ai-pending')).to_contain_text('example.txt')
                    send.click();expect(send).to_be_enabled(timeout=20000)
                    expect(page.locator('#ai-messages')).to_contain_text('Synthetic restored Chat answer.')
                    expect(field).to_have_value('')
                    page.reload(wait_until='networkidle')
                    expect(page.locator('#ai-messages')).to_contain_text('Synthetic restored Chat answer.')
                    assert page.locator('[data-kilas-feature=copilot],#copilot').count()==0
                    rail=open_chat_sidebar(page)
                    expect(rail).not_to_contain_text('VOICE_ONLY_SYNTHETIC_HISTORY')
                    assert rail.locator(f'a[href="/kilas-ai/threads/{hidden}"]').count()==0
                    page.screenshot(path=str(output/f'history-{locale}-{width}.png'))
                    close=rail.locator('[data-premium-close]')
                    if close.is_visible():close.click()
                    if locale=='en':
                        fail[0]=True;field.fill('Synthetic failure test');send.click()
                        expect(send).to_be_enabled(timeout=20000)
                        assert page.locator('#ai-notice').inner_text()
                        fail[0]=False
                    assert not errors,errors
                    report.append({'width':width,'locale':locale,'home':True,'saved_chat':True,'attachment':True,'mocked_stream':True,'copilot_hidden':True,'overflow':False,'js_errors':0})
                    context.close();scenario.doCleanups()
            browser.close()
        (output/'verification.json').write_text(json.dumps({'cases':report,'provider_calls':'synthetic only','physical_microphone_calls':0,'production_writes':0},indent=2))
        print(json.dumps({'cases':len(report),'synthetic_provider_dispatches':len(calls),'result':'PASS'}))
    finally:server.shutdown();case.doCleanups()

if __name__=='__main__':main()
