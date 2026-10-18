"""Actual Chat composer and downloads at three widths; provider/E2B mocked."""
import base64,os,tempfile,threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_thread_projects as f
import app


def main():
    server=make_server('127.0.0.1',0,app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM'),args=['--no-sandbox'])
            for width in (320,768,1440):
                case=f.ThreadProjects();case.id=lambda:'thread-project-browser-'+str(width);case.setUp()
                outputs=f.frames({'report.html':f.HTML,'sales.csv':f.CSV})
                vm=case.sandbox({'exit_code':0,'stdout':'410000 226000 184000\n','stderr':'','timed_out':False,'outputs':{n:base64.b64encode(v.encode()).decode() for n,v in outputs.items()}})
                create=case.enabled(vm)
                cookie=case.client().get_cookie('session');context=browser.new_context(viewport={'width':width,'height':900},accept_downloads=True)
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
                page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                with patch.object(f.native.requests,'post',return_value=case.provider()) as model:
                    page.goto(origin+f'/kilas-ai/threads/{case.thread}')
                    page.locator('[data-chat-model-selector][data-model-kind=chat] .chat-model-trigger').click()
                    page.locator('.chat-model-option').filter(has_text='GPT-6 Luna').click()
                    expect(page.locator('[name=selected_model]')).to_have_value('gpt-6-luna')
                    page.locator('#ai-input').fill('Buat laporan penjualan Kopi 10x20000 biaya12000, Teh8x15000 biaya7000, Roti5x18000 biaya10000 dan jadikan ZIP dengan HTML dan CSV.')
                    page.locator('#ai-send').click()
                    expect(page.locator('.ai-file-card').filter(has_text='report.html')).to_be_visible(timeout=20000)
                    expect(page.locator('#ai-send')).to_be_enabled(timeout=5000)
                    assert model.call_count==1 and create.call_count==1
                    with page.expect_download() as download:
                        page.locator('.ai-file-card').filter(has_text='sales.csv').get_by_role('link',name='Download').click()
                    assert Path(download.value.path()).read_bytes()==f.CSV
                    page.reload();expect(page.locator('.ai-file-card').filter(has_text='execution-output.zip')).to_be_visible(timeout=10000)
                    assert model.call_count==1 and create.call_count==1
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert not errors,errors
                    page.screenshot(path=str(Path(tempfile.gettempdir())/f'kilas-thread-project-{width}.png'),full_page=True)
                    print(f'PASS thread composer/native tools/mock VM/cards/download hash/reload once/no overflow {width}',flush=True)
                context.close();case.doCleanups()
            browser.close()
    finally:server.shutdown()


if __name__=='__main__':main()
