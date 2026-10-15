"""Naskah microphone failure/cancellation regressions; local UI, zero provider IO."""
import json
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server
import test_kilas_home as home
from kilas_ai import audio_provider, audio_transcription_budget as budget
from kilas_ai import audio_transcription_provider as stt, providers

MIC = """window.qaMic={calls:0,stops:0,empty:false,denied:false};
navigator.mediaDevices.getUserMedia=async()=>{
 qaMic.calls++;if(qaMic.denied)throw new DOMException('Denied','NotAllowedError');
 return {getTracks:()=>[{stop:()=>qaMic.stops++}]};
};
window.MediaRecorder=class {
 static isTypeSupported(){return true}
 constructor(){this.state='inactive';this.mimeType='audio/webm';this.events={}}
 addEventListener(name,fn){this.events[name]=fn}
 start(){this.state='recording'}
 stop(){this.state='inactive';queueMicrotask(()=>{this.events.dataavailable({data:new Blob(qaMic.empty?[]:['synthetic'])});this.events.stop()})}
};"""


def main():
    case = home.HomeTests('test_old_routes_still_render')
    case.id = lambda: 'dictation-browser'
    case.setUp()
    app = home.fixture.base.f.fixture.app.app
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    output = Path(os.environ.get('KILAS_DICTATION_SCREENSHOTS', str(Path(tempfile.gettempdir())/'kilas-dictation-browser')))
    output.mkdir(parents=True, exist_ok=True)
    report = {'scope': 'local Chromium + synthetic microphone/network', 'paid_calls': 0, 'widths': []}
    try:
        blocked = AssertionError('No real provider allowed')
        with patch.object(budget, 'ready', return_value=True), patch.object(stt, 'transcribe', side_effect=blocked), patch.object(audio_provider, 'request', side_effect=blocked), patch.object(providers, '_openai', side_effect=blocked), sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for width in (320, 360, 390, 430, 1440):
                cookie = case.client().get_cookie('session')
                context = browser.new_context(viewport={'width': width, 'height': 900}, has_touch=width < 761)
                context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin}])
                context.add_init_script(MIC)
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.route('**/*', lambda r: r.continue_() if r.request.url.startswith(origin) else r.abort())
                page.goto(origin+'/kilas-translator?mode=voiceover', wait_until='networkidle')
                expect(page.locator('#voiceover-panel a[href*="/privacy"]')).to_have_count(0)
                script = page.locator('#audio-script')
                script.fill('Naskah awal.')
                assert page.evaluate('qaMic.calls') == 0
                calls = []
                pending = []

                def response(route):
                    calls.append(route.request.post_data or '')
                    route.fulfill(status=200, content_type='application/json', body=json.dumps({'status': 'COMPLETED', 'text': 'Hasil dikte.'}))

                page.route('**/voice-script/dictate', response)
                page.locator('#dictation-start').click()
                expect(page.locator('#dictation-cancel')).to_have_text('Batal')
                expect(page.locator('#dictation-cancel')).to_have_attribute('aria-label', 'Batal dikte')
                script.fill('Edit saat merekam.')
                page.locator('#dictation-stop').click()
                expect(script).to_have_value('Edit saat merekam.\nHasil dikte.')
                assert len(calls) == 1
                page.locator('#dictation-undo').click()
                expect(script).to_have_value('Edit saat merekam.')
                page.evaluate('qaMic.empty=true')
                page.locator('#dictation-start').click()
                page.locator('#dictation-stop').click()
                expect(page.locator('#dictation-error')).to_contain_text('Rekaman kosong')
                expect(page.locator('#dictation-status')).to_have_text('')
                assert len(calls) == 1
                page.evaluate('qaMic.empty=false;qaMic.denied=true')
                page.locator('#dictation-start').click()
                expect(page.locator('#dictation-error')).to_contain_text('Izin mikrofon')
                expect(page.locator('#dictation-start')).to_be_enabled()
                page.evaluate('qaMic.denied=false')
                page.unroute('**/voice-script/dictate')
                page.route('**/voice-script/dictate', lambda r: r.fulfill(status=503, content_type='application/json', body='{"error":"Kegagalan mock"}'))
                page.locator('#dictation-start').click()
                page.locator('#dictation-stop').click()
                expect(page.locator('#dictation-error')).to_have_text('Kegagalan mock')
                expect(page.locator('#dictation-status')).to_have_text('')
                expect(script).to_have_value('Edit saat merekam.')
                page.unroute('**/voice-script/dictate')
                page.route('**/voice-script/dictate', lambda r: r.abort('failed'))
                page.locator('#dictation-start').click()
                page.locator('#dictation-stop').click()
                expect(page.locator('#dictation-error')).to_contain_text('Jaringan belum tersedia')
                expect(page.locator('#dictation-status')).to_have_text('')
                expect(script).to_have_value('Edit saat merekam.')
                page.unroute('**/voice-script/dictate')
                page.route('**/voice-script/dictate', lambda r: r.fulfill(status=200, content_type='application/json', body='{}') if 'name="action"' in (r.request.post_data or '') else pending.append(r))
                page.locator('#dictation-start').click()
                page.locator('#dictation-stop').click()
                expect(page.locator('#dictation-status')).to_contain_text('Menyiapkan naskah')
                expect(page.locator('#dictation-cancel')).to_have_text('Batal')
                script.fill('Edit saat proses.')
                page.locator('#dictation-cancel').click()
                assert len(pending) == 1
                pending.pop().fulfill(status=200, content_type='application/json', body='{"status":"COMPLETED","text":"Hasil terlambat"}')
                expect(script).to_have_value('Edit saat proses.')
                page.locator('#dictation-start').click()
                expect(page.locator('#dictation-status')).to_contain_text('Mikrofon aktif')
                page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'))")
                expect(page.locator('#dictation-start')).to_be_enabled()
                page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>false})")
                page.locator('#dictation-start').click()
                expect(page.locator('#dictation-status')).to_contain_text('Mikrofon aktif')
                page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
                expect(page.locator('#dictation-start')).to_be_enabled()
                expect(script).to_have_value('Edit saat proses.')
                assert page.evaluate('qaMic.stops') == 7
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
                assert not errors, errors
                page.screenshot(path=str(output/f'dictation-{width}.png'), full_page=True)
                report['widths'].append(width)
                context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        server.shutdown()
        case.doCleanups()


if __name__ == '__main__':
    main()
