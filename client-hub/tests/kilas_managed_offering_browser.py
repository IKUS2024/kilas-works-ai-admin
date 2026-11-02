"""Managed Kilas AI UI: local real app/accounts, mocked provider, no paid calls."""
import io,json,logging,os,threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_managed_offering as fixture
from kilas_ai import providers,store
import app


def main():
    out=Path(os.environ.get('KILAS_MANAGED_QA_ARTIFACTS','/tmp/kilas-managed-offering-browser'));out.mkdir(parents=True,exist_ok=True)
    case=fixture.ManagedOfferingTests();case.id=lambda:'managed-browser';case.setUp()
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server=make_server('127.0.0.1',0,app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    cookie=case.client().get_cookie('session');calls=[];report=[]
    def answer(mode,messages,**kwargs):
        calls.append(messages.selected_model)
        yield from fixture.fixture.answer(mode,messages,**kwargs)
    try:
        with patch.object(providers,'stream',side_effect=answer),sync_playwright() as pw:
            executable='/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None
            browser=pw.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}),args=['--no-sandbox'])
            for width,height in ((320,740),(393,852),(820,1180),(1440,900)):
                for locale in ('en','id'):
                    ctx=browser.new_context(viewport={'width':width,'height':height},has_touch=width<900)
                    ctx.add_cookies([{'name':'session','value':cookie.value,'url':origin},{'name':'kilas_language','value':locale,'url':origin}])
                    page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                    page.goto(origin+'/products/start',wait_until='networkidle')
                    assert page.locator('[data-chat-model-selector],#chat-model-dialog,#image-model-dialog,#copilot').count()==0
                    assert page.get_by_text('Kilas AI',exact=True).count()>0
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(out/f'home-{locale}-{width}.png'),animations='disabled')
                    thread=store.create_thread(case.owner)
                    path=origin+f'/kilas-ai/threads/{thread}'
                    page.goto(path,wait_until='networkidle')
                    field=page.locator('#ai-input');send=page.locator('#ai-send')
                    field.fill('Bandingkan dokumen ini. Jangan buat file baru.')
                    page.locator('#ai-files').set_input_files({'name':'synthetic.txt','mimeType':'text/plain','buffer':b'Budget: 150 million. Latest correction: 175 million.'})
                    expect(page.locator('#ai-pending')).to_contain_text('synthetic.txt')
                    send.click();expect(send).to_be_enabled(timeout=15000)
                    expect(page.locator('#ai-messages')).to_contain_text('Budget tetap 150 juta')
                    expect(field).to_have_value('')
                    page.reload(wait_until='networkidle')
                    expect(page.locator('#ai-messages')).to_contain_text('Budget tetap 150 juta')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(out/f'history-{locale}-{width}.png'),animations='disabled')
                    field.fill('Saved draft only')
                    page.goto(origin+'/products/start',wait_until='networkidle');page.go_back(wait_until='networkidle')
                    expect(page.locator('#ai-input')).to_have_value('Saved draft only')
                    assert not errors,errors
                    report.append({'width':width,'locale':locale,'picker_absent':True,'mocked_luna_stream':True,'file_upload':True,'history':True,'draft':True,'overflow':False,'js_errors':0})
                    ctx.close()
            browser.close()
        assert set(calls)=={'gpt-6-luna'},calls
        (out/'verification.json').write_text(json.dumps({'result':'PASS','cases':report,'provider_calls':'mocked only','paid_api_calls':0},indent=2))
        print(json.dumps({'result':'PASS','cases':len(report),'mocked_dispatches':len(calls),'artifacts':str(out)}))
    finally:server.shutdown();case.doCleanups()

if __name__=='__main__':main()
