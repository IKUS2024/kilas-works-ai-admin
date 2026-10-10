"""Actual local Flask + Chromium acceptance; synthetic owners, forbidden external IO."""
import json
import os
from pathlib import Path
import threading
import shutil
import tempfile
from unittest.mock import patch
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright, expect
import test_kilas_home as fixture
from kilas_ai import providers


def main():
    case=fixture.HomeTests('test_old_routes_still_render');case.id=lambda:'unified-home-browser';case.setUp()
    app=fixture.fixture.base.f.fixture.app.app
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_HOME_SCREENSHOTS',str(Path(tempfile.gettempdir())/'kilas-home-review')));output.mkdir(parents=True,exist_ok=True)
    report={'origin':'local synthetic Flask','paid_requests':0,'capture_requests':0,'widths':[],'checks':[]}
    try:
        with patch.object(providers,'stream',side_effect=lambda *a,**k:fixture.fixture.answer('Ini jawaban sintetis untuk pemeriksaan Home. Naskah dan riwayat tetap tersimpan dalam percakapan ini.')),sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            cookie=case.client().get_cookie('session')
            for width in (1440,390,320):
                context=browser.new_context(viewport={'width':width,'height':1000},has_touch=width<761,reduced_motion='reduce')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                # Never permit external browser requests or invoke real media permissions.
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                page.add_init_script("navigator.mediaDevices.getDisplayMedia=()=>{throw Error('Capture forbidden in QA')};navigator.mediaDevices.getUserMedia=()=>{throw Error('Capture forbidden in QA')}")
                assert page.goto(origin+'/products/start',wait_until='networkidle').status==200
                expect(page.get_by_role('heading',name='Mau ngapain hari ini?',exact=True)).to_be_visible()
                assert page.locator('[data-home-task]').count()==4
                assert page.locator('.premium-home-ai').count()==0
                assert page.locator('.premium-navigation a[href="/kilas-ai/video"]').count()==0
                assert page.locator('.premium-navigation a[href="/kilas-translator"]').count()==0
                expect(page.get_by_text('Belum tersedia untuk akun ini',exact=True)).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.evaluate('document.fonts.ready')
                page.screenshot(path=str(output/f'home-{width}.png'),full_page=True)
                if width<761:
                    for _ in range(3):
                        page.get_by_role('button',name='Buka navigasi',exact=True).click()
                        expect(page.locator('.premium-sidebar')).to_be_visible()
                        page.keyboard.press('Escape')
                        assert page.locator('.premium-sidebar').evaluate('e=>e.inert')
                box=page.locator('#ai-input');box.fill('Draft chat tersimpan di layar')
                for _ in range(3):
                    page.locator('[data-home-task=video]').click();box.fill('Ide video sintetis')
                    page.locator('[data-home-cancel]').click();expect(box).to_have_value('Draft chat tersimpan di layar')
                    page.locator('[data-home-task=video]').click();expect(box).to_have_value('Ide video sintetis')
                    page.locator('[data-home-cancel]').click()
                # Pending chat uploads must survive task-switch attempts.
                page.locator('#ai-files').set_input_files({'name':'brief.txt','mimeType':'text/plain','buffer':b'Synthetic brief'})
                page.locator('[data-home-task=video]').click()
                expect(page.locator('#home-task-value')).to_have_value('chat')
                expect(page.locator('#ai-pending')).to_contain_text('brief.txt')
                page.get_by_role('button',name='Hapus lampiran brief.txt',exact=True).click()
                page.locator('[data-home-task=video]').click();box.fill('Ide video sintetis')
                page.screenshot(path=str(output/f'home-video-{width}.png'),full_page=True)
                page.locator('#ai-send').click();expect(page.locator('#video-idea')).to_have_value('Ide video sintetis')
                assert page.locator('form[action="/kilas-ai/video/plan"] input[name=csrf_token]').count()==1
                assert page.locator('input[name=references]').get_attribute('type')=='file'
                assert page.locator('form[action="/kilas-ai/video/plan"]').get_attribute('enctype')=='multipart/form-data'
                page.get_by_role('link',name='Kembali ke Kilas AI Home',exact=True).click();page.wait_for_load_state('networkidle')
                expect(page.locator('#ai-input')).to_be_visible()
                # Browser back returns the real form; forward returns Home without duplicate listeners.
                page.go_back(wait_until='networkidle');expect(page.locator('#video-idea')).to_have_value('Ide video sintetis')
                page.go_forward(wait_until='networkidle')
                page.locator('[data-home-task=translate]').click();page.locator('#ai-input').fill('Bahasa tujuan Indonesia')
                page.locator('#ai-send').click();expect(page.locator('#translate-panel')).to_be_visible()
                expect(page.get_by_text('Bahasa tujuan Indonesia',exact=False)).to_be_visible()
                assert page.locator('#audio-file').get_attribute('name')=='file'
                assert page.locator('#translate-panel form').get_attribute('enctype')=='multipart/form-data'
                page.get_by_role('link',name='Kembali ke Kilas AI Home',exact=True).click();page.wait_for_load_state('networkidle')
                page.locator('[data-home-task=voiceover]').click();page.locator('#ai-input').fill('Naskah suara sintetis.')
                page.locator('#ai-send').click();expect(page.locator('#voiceover-panel')).to_be_visible()
                expect(page.locator('#audio-script')).to_have_value('Naskah suara sintetis.')
                page.get_by_role('link',name='Kembali ke Kilas AI Home',exact=True).click();page.wait_for_load_state('networkidle')
                page.locator('#ai-input').fill('Halo, ini uji chat sintetis.');page.locator('#ai-send').click()
                expect(page.locator('.ai-assistant')).to_contain_text('Ini jawaban sintetis',timeout=15000)
                expect(page.locator('#ai-send')).to_be_enabled()
                thread_url=page.url;assert '/kilas-ai/threads/' in thread_url
                page.reload(wait_until='networkidle');expect(page.locator('.ai-assistant')).to_contain_text('Ini jawaban sintetis')
                page.goto(origin+'/products/start');page.locator('.home-recent summary').click()
                expect(page.locator('.home-recent a[href="'+thread_url.removeprefix(origin)+'"]')).to_be_visible()
                # Stop aborts the existing transport; blocked switching keeps the task stable.
                page.evaluate("""() => {window.homeQAOriginalFetch=window.fetch;window.fetch=(url,options)=>String(url).endsWith('/send')?new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')))):window.homeQAOriginalFetch(url,options)}""")
                page.locator('#ai-input').fill('Pesan untuk uji Stop');page.locator('#ai-send').click()
                expect(page.locator('#ai-stop')).to_be_visible()
                page.locator('[data-home-task=video]').click();expect(page.locator('#home-task-value')).to_have_value('chat')
                page.locator('#ai-stop').click();expect(page.locator('#ai-send')).to_be_enabled()
                page.evaluate('window.fetch=window.homeQAOriginalFetch')
                assert not errors,errors
                report['widths'].append(width);context.close()
            # Locale is the selected cookie, including JS task descriptions.
            context=browser.new_context(viewport={'width':1440,'height':1000});context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
            page=context.new_page();page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
            page.goto(origin+'/products/start',wait_until='networkidle');expect(page.get_by_role('heading',name='What would you like to do today?',exact=True)).to_be_visible()
            page.locator('[data-home-task=voiceover]').click();expect(page.locator('#ai-send')).to_have_text('Open voiceover form')
            page.screenshot(path=str(output/'home-en-1440.png'),full_page=True)
            browser.close()
        report['checks']=['single entry','optional projects','live unavailable','mobile drawer repeated open/Escape','draft switch/cancel','attachment guard/remove','native handoff CSRF/upload forms','back/forward','translation notes','voiceover draft','real chat mocked provider','saved history/reload','stop/blocked task switch','selected locale','no overflow','no browser JS errors']
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
