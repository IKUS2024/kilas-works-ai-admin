"""Actual local Flask + Chromium acceptance; synthetic owners, forbidden external IO."""
import json
import os
from pathlib import Path
import threading
import shutil
import tempfile
from unittest.mock import patch
from werkzeug.serving import make_server
from kilas_chat_sidebar_browser_helpers import open_chat_sidebar, click_new_chat
from playwright.sync_api import sync_playwright, expect
import test_kilas_home as fixture
from kilas_ai import providers


def choose_task(page,task):
    expect(page.locator('.home-task-choices')).to_be_visible()
    page.locator('[data-home-task='+task+']').click()


def check_chat_presentation(page):
    user=page.locator('.ai-user .ai-message-text').last
    assistant=page.locator('.ai-assistant .ai-message-text').last
    assert user.evaluate('e=>Math.abs(e.getBoundingClientRect().right-e.closest(".ai-message").getBoundingClientRect().right)<3 && e.getBoundingClientRect().width<=e.closest(".ai-message").clientWidth*.91')
    assert assistant.evaluate('e=>Math.abs(e.getBoundingClientRect().left-e.closest(".ai-message").getBoundingClientRect().left)<3')
    assert page.locator('.ai-thread-menu summary').inner_text()==''
    assert page.locator('.ai-thread-menu summary svg').count()==1
    copy=page.locator('.ai-assistant .ai-copy').last
    assert copy.inner_text()=='' and copy.locator('svg').count()==1
    page.evaluate('navigator.clipboard.writeText=async text=>{window.qaCopiedText=text}')
    copy.click();expect(copy).to_have_attribute('aria-label','Tersalin')
    assert page.evaluate('window.qaCopiedText')==assistant.text_content()
    assert copy.inner_text()==''
    expect(page.locator('#ai-notice')).to_have_text('Tersalin')
    page.locator('.ai-thread-menu summary').click()
    assert page.locator('[data-action=rename] input[name=title]').is_visible()
    page.locator('.ai-thread-menu summary').click()


def main():
    case=fixture.HomeTests('test_old_routes_still_render');case.id=lambda:'unified-home-browser';case.setUp()
    app=fixture.fixture.base.f.fixture.app.app
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_HOME_SCREENSHOTS',str(Path(tempfile.gettempdir())/'kilas-home-review')));output.mkdir(parents=True,exist_ok=True)
    report={'origin':'local synthetic Flask','paid_requests':0,'capture_requests':0,'widths':[],'checks':[]}
    try:
        with patch.object(providers,'stream',side_effect=lambda *a,**k:fixture.fixture.answer('Ini jawaban sintetis untuk pemeriksaan Home. Naskah dan riwayat tetap tersimpan dalam percakapan ini.\n\n```js\nconst sample = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx;\n```')),sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            with case.client().session_transaction() as values:values['active_product']='finance'
            cookie=case.client().get_cookie('session')
            for width in (1440,390,320):
                context=browser.new_context(viewport={'width':width,'height':1000},has_touch=width<761,reduced_motion='reduce')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                # Never permit external browser requests or invoke real media permissions.
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                page.add_init_script("navigator.mediaDevices.getDisplayMedia=()=>{throw Error('Capture forbidden in QA')};navigator.mediaDevices.getUserMedia=()=>{throw Error('Capture forbidden in QA')}")
                assert page.goto(origin+'/products/start',wait_until='networkidle').status==200
                expect(page.get_by_role('heading',name='How can I Help you?',exact=True)).to_be_visible()
                assert page.locator('[data-home-task]').count()==4
                assert page.locator('.premium-navigation a[href="/products/start"]').count()==1
                assert page.locator('.premium-navigation').get_by_role('link',name='Percakapan',exact=True).count()==0
                assert page.locator('.home-project-options, .premium-home-secondary').count()==0
                assert page.locator('form input[name=product][value=finance]').count()==1
                assert page.locator('.premium-home-ai').count()==0
                assert page.locator('.premium-navigation a[href="/kilas-ai/video"]').count()==0
                assert page.locator('.premium-navigation a[href="/kilas-translator"]').count()==0
                assert page.locator('.home-workspace-footer, .home-recent').count()==0
                assert page.get_by_text('Belum tersedia untuk akun ini',exact=True).count()==0
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.evaluate('document.fonts.ready')
                page.screenshot(path=str(output/f'home-{width}.png'),full_page=True)
                # Exact owner regression before AI routes can update product selection.
                home_nav=page.locator('.premium-navigation').inner_text()
                if width<761:page.get_by_role('button',name='Buka navigasi',exact=True).click()
                page.locator('.premium-sidebar-account a').first.click();page.wait_for_load_state('networkidle')
                assert page.url.endswith('/account?workspace=home')
                expect(page.locator('.account-workspace-access')).to_be_visible()
                expect(page.get_by_role('heading',name='Akun saya',exact=True)).to_be_visible()
                assert page.locator('.premium-navigation').inner_text()==home_nav
                if width<761:page.get_by_role('button',name='Buka navigasi',exact=True).click()
                page.screenshot(path=str(output/f'account-from-finance-home-{width}.png'),full_page=True)
                if width<761:page.keyboard.press('Escape')
                page.locator('[data-account-tab=security]').click();page.go_back()
                assert '?workspace=home' in page.url
                for suffix in ('','?workspace=finance','?workspace=invalid'):
                    page.goto(origin+'/account'+suffix,wait_until='networkidle')
                    assert page.locator('.account-workspace-access').count()==0
                    assert page.locator('.premium-navigation').inner_text()==home_nav
                    expect(page.locator('.account-back-finance')).to_be_visible()
                if width<761:page.get_by_role('button',name='Buka navigasi',exact=True).click()
                page.screenshot(path=str(output/f'account-direct-finance-{width}.png'),full_page=True)
                session_cookie=next(item['value'] for item in context.cookies() if item['name']=='session')
                assert app.session_interface.get_signing_serializer(app).loads(session_cookie)['active_product']=='finance'
                page.goto(origin+'/products/start',wait_until='networkidle')
                # Spacious Home: controls sit below the canvas; composer stays within the viewport.
                layout=page.evaluate("""() => {const b=s=>document.querySelector(s).getBoundingClientRect();return {composer:b('#ai-composer').bottom,choices:b('.home-tool-selector').bottom,top:b('#ai-composer').top,canvas:b('.ai-main').height}}""")
                assert layout['composer']<=1000 and layout['choices']<=layout['top'],layout
                assert layout['canvas']>700,layout
                assert page.locator('#ai-input').evaluate('e=>e.clientHeight<=48')
                page.locator('#ai-input').fill('Synthetic long draft\n'*20)
                assert page.locator('#ai-input').evaluate('e=>e.clientHeight<=144 && e.clientHeight>48')
                page.locator('#ai-input').fill('')
                assert page.locator('#ai-send svg').count()==1
                if width<761:
                    # Reduced visible height simulates keyboard layout; no real device IME claim.
                    page.set_viewport_size({'width':width,'height':460})
                    page.locator('#ai-input').focus()
                    expect(page.locator('#ai-send')).to_be_in_viewport()
                    assert page.locator('#ai-composer').evaluate('e=>e.getBoundingClientRect().bottom<=innerHeight')
                    page.screenshot(path=str(output/f'home-small-height-{width}.png'))
                    page.set_viewport_size({'width':width,'height':1000})
                if width<761:
                    for _ in range(3):
                        page.get_by_role('button',name='Buka navigasi',exact=True).click()
                        expect(page.locator('.premium-sidebar')).to_be_visible()
                        page.keyboard.press('Escape')
                        assert page.locator('.premium-sidebar').evaluate('e=>e.inert')
                box=page.locator('#ai-input');box.fill('Draft chat tersimpan di layar')
                # Immediate navigation carries the current brief; no extra Send required.
                box.fill('x'*2401);choose_task(page,'video')
                expect(box).to_have_value('x'*2401);expect(page.locator('#ai-notice')).to_contain_text('terlalu panjang')
                box.fill('Draft chat tersimpan di layar')
                # Pending chat uploads must survive task-switch attempts.
                page.locator('#ai-files').set_input_files({'name':'brief.txt','mimeType':'text/plain','buffer':b'Synthetic brief'})
                choose_task(page,'video')
                expect(page.locator('#home-task-value')).to_have_value('chat')
                expect(page.locator('#ai-pending')).to_contain_text('brief.txt')
                page.get_by_role('button',name='Hapus lampiran brief.txt',exact=True).click()
                box.fill('Ide video sintetis');choose_task(page,'video')
                page.screenshot(path=str(output/f'home-video-{width}.png'),full_page=True)
                expect(page.locator('#video-idea')).to_have_value('Ide video sintetis')
                assert page.locator('form[action="/kilas-ai/video/plan"] input[name=csrf_token]').count()==1
                assert page.locator('input[name=references]').get_attribute('type')=='file'
                assert page.locator('form[action="/kilas-ai/video/plan"]').get_attribute('enctype')=='multipart/form-data'
                page.get_by_role('link',name='Kembali ke Kilas AI Home',exact=True).click();page.wait_for_load_state('networkidle')
                expect(page.locator('#ai-input')).to_be_visible()
                # Browser back returns the real form; forward returns Home without duplicate listeners.
                page.go_back(wait_until='networkidle');expect(page.locator('#video-idea')).to_have_value('Ide video sintetis')
                page.go_forward(wait_until='networkidle')
                page.locator('#ai-input').fill('Bahasa tujuan Indonesia');choose_task(page,'translate');expect(page.locator('#translate-panel')).to_be_visible()
                expect(page.get_by_text('Bahasa tujuan Indonesia',exact=False)).to_be_visible()
                assert page.locator('#audio-file').get_attribute('name')=='file'
                assert page.locator('#translate-panel form').get_attribute('enctype')=='multipart/form-data'
                page.get_by_role('link',name='Kembali ke Kilas AI Home',exact=True).click();page.wait_for_load_state('networkidle')
                page.locator('#ai-input').fill('Naskah suara sintetis.');choose_task(page,'voiceover');expect(page.locator('#voiceover-panel')).to_be_visible()
                expect(page.locator('#audio-script')).to_have_value('Naskah suara sintetis.')
                page.get_by_role('link',name='Kembali ke Kilas AI Home',exact=True).click();page.wait_for_load_state('networkidle')
                page.locator('#ai-input').fill('Halo, ini uji chat sintetis.');page.locator('#ai-send').click()
                expect(page.locator('.ai-assistant')).to_contain_text('Ini jawaban sintetis',timeout=15000)
                expect(page.locator('#ai-send')).to_be_enabled()
                check_chat_presentation(page)
                page.screenshot(path=str(output/f'chat-stream-{width}.png'),full_page=True)
                thread_url=page.url;assert '/kilas-ai/threads/' in thread_url
                page.reload(wait_until='networkidle');expect(page.locator('.ai-assistant')).to_contain_text('Ini jawaban sintetis')
                check_chat_presentation(page)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                if width<761:
                    page.set_viewport_size({'width':width,'height':460})
                    page.locator('#ai-input').focus();expect(page.locator('#ai-send')).to_be_in_viewport()
                    page.set_viewport_size({'width':width,'height':1000})
                page.screenshot(path=str(output/f'chat-history-{width}.png'),full_page=True)
                page.goto(origin+'/products/start');open_chat_sidebar(page)
                history_link=page.locator('[data-chat-sidebar] a[href="'+thread_url.removeprefix(origin)+'"]')
                expect(history_link).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(output/f'home-history-{width}.png'),full_page=True)
                history_link.click();page.wait_for_load_state('networkidle')
                expect(page.locator('.ai-assistant')).to_contain_text('Ini jawaban sintetis')
                assert page.locator('.premium-navigation').get_by_role('link',name='Percakapan',exact=True).count()==0
                home_link=page.locator('.premium-navigation').get_by_role('link',name='Home',exact=True)
                if width<761:
                    page.get_by_role('button',name='Buka navigasi',exact=True).click()
                home_link.click();page.wait_for_load_state('networkidle')
                expect(page.locator('#ai-input')).to_be_visible()
                page.go_back(wait_until='networkidle');expect(page.locator('.ai-assistant')).to_contain_text('Ini jawaban sintetis')
                page.go_forward(wait_until='networkidle');expect(page.locator('#ai-input')).to_be_visible()
                # Stop aborts the existing transport; blocked switching keeps the task stable.
                page.evaluate("""() => {window.homeQAOriginalFetch=window.fetch;window.fetch=(url,options)=>String(url).endsWith('/send')?new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')))):window.homeQAOriginalFetch(url,options)}""")
                page.locator('#ai-input').fill('Pesan untuk uji Stop');page.locator('#ai-send').click()
                expect(page.locator('#ai-stop')).to_be_visible()
                choose_task(page,'video');expect(page.locator('#home-task-value')).to_have_value('chat')
                page.locator('#ai-stop').click();expect(page.locator('#ai-send')).to_be_enabled()
                page.evaluate('window.fetch=window.homeQAOriginalFetch')
                # Long conversations scroll independently without pushing the composer off-screen.
                page.locator('#ai-messages').evaluate("e=>{e.hidden=false;e.closest('.ai-main').classList.remove('is-empty');e.innerHTML='<p>'+('Synthetic scroll content '.repeat(1500))+'</p>';document.querySelector('.ai-empty').hidden=true}")
                assert page.locator('#ai-messages').evaluate('e=>e.scrollHeight>e.clientHeight')
                expect(page.locator('#ai-send')).to_be_in_viewport()
                page.goto(origin+'/products/start',wait_until='networkidle')
                home_nav=page.locator('.premium-navigation').inner_text()
                assert page.locator('.premium-sidebar-account a').first.get_attribute('href')=='/account?workspace=home'
                if width<761:page.get_by_role('button',name='Buka navigasi',exact=True).click()
                page.locator('.premium-sidebar-account a').first.click()
                page.wait_for_load_state('networkidle')
                assert page.locator('.premium-navigation').inner_text()==home_nav
                expect(page.locator('.account-workspace-access')).to_be_visible()
                expect(page.get_by_role('heading',name='Akun saya',exact=True)).to_be_visible()
                expect(page.locator('.premium-sidebar-account a[aria-current=page]')).to_have_attribute('href','/account?workspace=home')
                assert page.locator('.premium-navigation a[aria-current=page]').count()==0
                page.screenshot(path=str(output/f'account-{width}.png'),full_page=True)
                if width<761:
                    page.get_by_role('button',name='Buka navigasi',exact=True).click()
                    expect(page.locator('.premium-sidebar')).to_be_visible()
                    page.screenshot(path=str(output/f'account-navigation-{width}.png'))
                    page.keyboard.press('Escape')
                    assert page.locator('.premium-sidebar').evaluate('e=>e.inert')
                page.locator('[data-account-tab=security]').click();expect(page.locator('#account-panel-security')).to_be_visible()
                page.locator('[data-account-tab=personal]').click();expect(page.locator('#account-panel-personal')).to_be_visible()
                page.go_back();expect(page.locator('#account-panel-security')).to_be_visible()
                page.go_back();expect(page.locator('#account-panel-personal')).to_be_visible()
                page.locator('.account-workspace-links a[href$="#audio-settings-title"]').click()
                expect(page.locator('#audio-settings-title')).to_be_visible()
                assert page.locator('form[action="/kilas-translator/checkout"]').count()==3
                page.go_back(wait_until='networkidle');expect(page.locator('.account-workspace-access')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert not errors,errors
                report['widths'].append(width);context.close()
            # Locale is the selected cookie, including JS task descriptions.
            context=browser.new_context(viewport={'width':1440,'height':1000});context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
            page=context.new_page();page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
            page.goto(origin+'/products/start',wait_until='networkidle');expect(page.get_by_role('heading',name='What would you like to do today?',exact=True)).to_be_visible()
            choose_task(page,'voiceover');expect(page.locator('#voiceover-panel')).to_be_visible();expect(page.locator('[data-kilas-feature=voiceover]')).to_have_attribute('aria-current','page')
            page.screenshot(path=str(output/'home-en-1440.png'),full_page=True)
            browser.close()
        report['checks']=['single entry','no optional organization or duplicate Finance','no lower Home clutter; top contextual history; no unavailable placeholder','mobile drawer repeated open/Escape','immediate feature click with target length guard','attachment guard/remove','native handoff CSRF/upload forms','back/forward','translation notes','voiceover draft','real chat mocked provider','saved history/reload/open/return Home/back/forward','stop/blocked task switch','selected locale','spacious viewport canvas and bottom task choices/composer','compact auto-growing icon composer and native four-tool menu','new/loaded right-user left-AI and copy/options icons','Home account actual click with unchanged Finance session, direct/invalid hints','small-height keyboard layout simulation','independent long-message scroll','MyAccount same Home navigation and active link','account mobile drawer and tab browser back','existing audio purchase destination','no overflow','no browser JS errors']
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
