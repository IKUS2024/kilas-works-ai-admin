"""Synthetic-only browser QA: real media/recording/speech APIs are hard-blocked."""
import os
from pathlib import Path
import pytest
from test_content_projects_prototype import environment
from kilas_ai import listening_routes


def test_listening_flag_and_owner_gate(environment,monkeypatch):
    _,client=environment
    monkeypatch.delenv('KILAS_LISTENING_DEMO_ENABLED',raising=False)
    assert client.get('/kilas-ai/listening-demo').status_code==404
    monkeypatch.setenv('KILAS_LISTENING_DEMO_ENABLED','true')
    response=client.get('/kilas-ai/listening-demo')
    assert response.status_code==200
    body=response.get_data(as_text=True)
    assert 'Demo sintetis' in body and 'belum terhubung ke provider live' in body
    assert 'Capture tab nyata · belum tersedia' in body
    with client.session_transaction() as sess:
        sess.update(user_id=3,role='KILAS_ADMIN')
    assert client.get('/kilas-ai/listening-demo').status_code==404
    with client.session_transaction() as sess:
        sess.clear()
    assert client.get('/kilas-ai/listening-demo').status_code==302


@pytest.mark.skipif(not os.environ.get('KILAS_LISTENING_BROWSER_QA_DIR'),reason='Optional local Chromium QA')
def test_synthetic_stream_controls_cleanup_and_no_real_capture(environment,monkeypatch):
    from threading import Thread
    from werkzeug.serving import make_server
    from playwright.sync_api import sync_playwright,expect
    app,client=environment
    monkeypatch.setenv('KILAS_LISTENING_DEMO_ENABLED','true')
    output=Path(os.environ['KILAS_LISTENING_BROWSER_QA_DIR']);output.mkdir(parents=True,exist_ok=True)
    server=make_server('127.0.0.1',0,app);worker=Thread(target=server.serve_forever,daemon=True);worker.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM') or ('/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None),headless=True,args=['--no-sandbox'])
            context=browser.new_context(viewport={'width':1440,'height':1000})
            context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
            context.add_init_script('''
              window.forbiddenCaptureCalls=0;
              const forbidden=()=>{window.forbiddenCaptureCalls++;throw Error('Real capture forbidden in QA');};
              Object.defineProperty(navigator,'mediaDevices',{value:{getDisplayMedia:forbidden,getUserMedia:forbidden}});
              window.MediaRecorder=forbidden;
              if(window.speechSynthesis) window.speechSynthesis.speak=forbidden;
            ''')
            context.add_cookies([{'name':'session','value':client.get_cookie('session').value,'url':origin}])
            page=context.new_page();page.goto(origin+'/kilas-ai/listening-demo')
            expect(page.get_by_role('button',name='Capture tab nyata · belum tersedia')).to_be_disabled()
            page.get_by_role('button',name='Mulai demo',exact=True).click()
            expect(page.locator('#listen-status')).to_contain_text('Setujui')
            page.locator('#listen-consent').check();page.locator('#listen-suggest').check()
            page.get_by_role('button',name='Mulai demo',exact=True).click()
            expect(page.locator('#listen-original')).to_contain_text('Let us compare')
            expect(page.locator('#listen-translated')).to_contain_text('Mari kita bandingkan')
            expect(page.locator('#listen-reply')).to_have_value('Could you clarify which option you mean?')
            for name,width in (('desktop',1440),('mobile',390)):
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.screenshot(path=str(output/(name+'.png')),full_page=True)
            page.get_by_role('button',name='Berhenti',exact=True).click()
            expect(page.locator('#listen-original')).to_be_empty()
            expect(page.locator('#listen-translated')).to_be_empty()
            expect(page.locator('#listen-reply')).to_have_value('')
            page.locator('#listen-source').select_option('id');page.locator('#listen-target').select_option('en')
            page.locator('#listen-suggest').uncheck();page.get_by_role('button',name='Mulai demo',exact=True).click()
            expect(page.locator('#listen-original')).to_contain_text('Mari kita bandingkan')
            expect(page.locator('#listen-reply')).to_have_value('')
            page.evaluate('window.dispatchEvent(new Event("pagehide"))')
            expect(page.locator('#listen-status')).to_contain_text('terputus')
            expect(page.locator('#listen-original')).to_be_empty()
            expect(page.get_by_role('button',name='Mulai demo',exact=True)).to_be_enabled()
            assert page.evaluate('window.forbiddenCaptureCalls')==0
            assert page.evaluate('Object.keys(localStorage).length + Object.keys(sessionStorage).length')==0
            page.get_by_role('button',name='Mulai demo',exact=True).click()
            expect(page.locator('#listen-original')).to_contain_text('Mari kita bandingkan')
            expect(page.locator('#listening-demo')).to_have_attribute('data-state','idle',timeout=9000)
            expect(page.locator('#listen-status')).to_contain_text('Contoh selesai')
            expect(page.locator('#listen-original')).to_be_empty()
            assert page.evaluate('window.forbiddenCaptureCalls')==0
            browser.close()
    finally:
        server.shutdown();worker.join(timeout=5)
