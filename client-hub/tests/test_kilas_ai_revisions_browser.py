"""Responsive revisions, retained chat and synthetic microphone UI; zero paid IO."""
import json
import os
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_home as home
from kilas_ai import providers, audio_provider, audio_branded_voices as branded
from kilas_ai import audio_transcription_budget as budget, store


MIC = """window.qaMic={stops:0,calls:0};
navigator.mediaDevices.getUserMedia=async()=>{qaMic.calls++;return {getTracks:()=>[{stop:()=>qaMic.stops++}]}};
window.MediaRecorder=class {
 static isTypeSupported(){return true}
 constructor(){this.state='inactive';this.mimeType='audio/webm';this.events={}}
 addEventListener(name,fn){this.events[name]=fn}
 start(){this.state='recording'}
 stop(){this.state='inactive';this.events.dataavailable({data:new Blob(['synthetic'])});this.events.stop()}
};"""


def main():
    case=home.HomeTests('test_old_routes_still_render');case.id=lambda:'revisions-browser';case.setUp()
    app=home.fixture.base.f.fixture.app.app
    server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_REVISIONS_SCREENSHOTS','/tmp/kilas-revisions-browser'));output.mkdir(parents=True,exist_ok=True)
    report={'scope':'local Flask + Chromium, synthetic provider and microphone','paid_calls':0,'viewports':[]}
    try:
        with patch.object(providers,'stream',side_effect=lambda *a,**k:home.fixture.answer('Jawaban tersimpan untuk QA sintetis.')),patch.object(audio_provider,'request',side_effect=AssertionError('No real audio transport')),patch.object(branded,'public_choices',return_value=[{'alias':'kilas-male','name':'Kilas Male','style':'Natural'},{'alias':'kilas-female','name':'Kilas Female','style':'Natural'}]),sync_playwright() as p:
            options={'headless':True}
            if os.environ.get('KILAS_QA_CHROMIUM'):options.update(executable_path=os.environ['KILAS_QA_CHROMIUM'],args=['--no-sandbox'])
            browser=p.chromium.launch(**options)
            for width,height in ((1440,900),(820,1000),(390,844),(320,700)):
                client=case.client();cookie=client.get_cookie('session')
                context=browser.new_context(viewport={'width':width,'height':height},has_touch=width<761)
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}]);context.add_init_script(MIC)
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                page.goto(origin+'/products/start',wait_until='networkidle')
                expect(page.get_by_role('heading',name='How can I Help you?',exact=True)).to_be_visible()
                logo=page.locator('.kilas-new-chat-logo');expect(logo).to_be_visible()
                assert logo.evaluate('e=>e.complete&&e.naturalWidth===1254&&e.naturalHeight===1254')
                page.screenshot(path=str(output/f'new-chat-{width}.png'),full_page=True)
                assert page.locator('[data-home-task]').count()==2
                expect(page.locator('.kilas-translator-pending')).to_have_attribute('aria-disabled','true')
                expect(page.locator('#ai-input')).to_be_visible()
                page.locator('#ai-input').fill('Pesan pertama untuk revisi '+str(width));page.locator('#ai-send').click()
                expect(page.locator('.ai-assistant')).to_contain_text('Jawaban tersimpan untuk QA sintetis.')
                expect(logo).not_to_be_visible()
                old_url=page.url
                def rail():
                    if page.locator('#premium-sidebar').evaluate('e=>e.inert'):page.locator('[data-premium-menu]').click()
                    return page.locator('#premium-sidebar')
                sidebar=rail();assert sidebar.locator('[name=product]').count()==0
                sidebar.locator('.kilas-profile-menu>summary').click()
                options=sidebar.locator('.kilas-profile-options');expect(options.get_by_role('link',name='Subscription',exact=True)).to_be_visible()
                options.locator('.kilas-profile-language>summary').click();expect(options.locator('select[name=language]')).to_be_visible()
                page.screenshot(path=str(output/f'profile-{width}.png'),full_page=True)
                sidebar.locator('.kilas-profile-menu>summary').click()
                sidebar.locator('.ai-new').click();page.wait_for_load_state('networkidle')
                expect(page.get_by_role('heading',name='How can I Help you?',exact=True)).to_be_visible()
                assert page.locator('.ai-message').count()==0
                page.goto(old_url,wait_until='networkidle');expect(page.locator('.ai-assistant')).to_contain_text('Jawaban tersimpan')
                page.go_back(wait_until='networkidle');expect(page.get_by_role('heading',name='How can I Help you?',exact=True)).to_be_visible()
                page.go_forward(wait_until='networkidle');expect(page.locator('.ai-assistant')).to_contain_text('Jawaban tersimpan')
                sidebar=rail();sidebar.get_by_role('link',name='My Library',exact=True).click();page.wait_for_load_state('networkidle');expect(page.get_by_role('heading',name='My Library',exact=True)).to_be_visible()
                page.goto(origin+'/products/start',wait_until='networkidle');page.locator('#ai-input').fill('Naskah lama yang tetap ada.');page.locator('[data-home-task=voiceover]').click();page.wait_for_load_state('networkidle')
                script=page.locator('#audio-script');expect(script).to_have_value('Naskah lama yang tetap ada.')
                assert page.locator('#premium-sidebar,[data-chat-sidebar]').count()==0
                expect(page.locator('.kilas-feature-navigation')).to_be_visible()
                expect(page.locator('#dictation-start')).to_be_disabled();expect(page.locator('#dictation-status')).to_contain_text('belum aktif')
                assert page.evaluate('qaMic.calls')==0
                assert page.locator('#voice-video-file,#voice-video-extract,.audio-balance').count()==0
                expect(page.locator('[name=voice_kind][value=kilas]')).to_be_checked()
                expect(page.locator('#kilas-voice-choice')).to_have_value('kilas-male')
                page.locator('#kilas-voice-choice').select_option('kilas-female');expect(page.locator('#selected-voice')).to_have_value('kilas-female')
                page.screenshot(path=str(output/f'voice-over-{width}.png'),full_page=True)
                with patch.object(budget,'ready',return_value=True):page.reload(wait_until='networkidle')
                script=page.locator('#audio-script');script.fill('Naskah yang sudah ada.');page.locator('#voice-dictation details>summary').click();page.locator('#dictation-consent').check()
                page.route('**/voice-script/dictate',lambda r:r.fulfill(status=200,content_type='application/json',body=json.dumps({'status':'COMPLETED','text':'Ucapan sintetis.'})))
                page.locator('#dictation-start').click();expect(page.locator('#dictation-status')).to_contain_text('Mikrofon aktif')
                script.fill('Perubahan saat merekam.');page.locator('#dictation-stop').click();expect(script).to_have_value('Perubahan saat merekam.\nUcapan sintetis.')
                assert page.evaluate('qaMic.stops')==1
                page.locator('#dictation-undo').click();expect(script).to_have_value('Perubahan saat merekam.')
                page.locator('#dictation-start').click();page.locator('#dictation-cancel').click();expect(script).to_have_value('Perubahan saat merekam.')
                assert page.evaluate('qaMic.stops')==2
                page.unroute('**/voice-script/dictate');page.route('**/voice-script/dictate',lambda r:r.fulfill(status=503,content_type='application/json',body='{"error":"Gagal sintetis; naskah aman."}'))
                page.locator('#dictation-start').click();page.locator('#dictation-stop').click();expect(page.locator('#dictation-error')).to_have_text('Gagal sintetis; naskah aman.');expect(script).to_have_value('Perubahan saat merekam.')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                assert not errors,(width,errors)
                report['viewports'].append({'width':width,'history_new_back_forward_library_profile_audio_dictation_cancel_error':'PASS'})
                context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
