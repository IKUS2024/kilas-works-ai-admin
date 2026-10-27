"""Chromium, disposable SQLite, synthetic microphone and mocked provider only."""
import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_copilot as fixture
from kilas_ai import copilot, audio_provider, live_translator, translator_languages

FAKE_MIC = """
window.micRequests=0;window.stoppedTracks=0;window.processFrames=0;
window.micPermission='granted';window.pendingMic=null;
navigator.mediaDevices.getUserMedia=async()=>{
  window.micRequests++;
  if(window.micPermission==='denied')throw new DOMException('denied','NotAllowedError');
  if(window.micPermission==='pending')await new Promise(resolve=>window.pendingMic=resolve);
  const track={stop(){window.stoppedTracks++},addEventListener(){}};
  return {getTracks:()=>[track],getAudioTracks:()=>[track]};
};
window.AudioContext=class {
  constructor(){this.sampleRate=32000;this.destination={};}
  async resume(){}
  createMediaStreamSource(){return {connect(){},disconnect(){}};}
  createGain(){return {gain:{value:1},connect(){},disconnect(){}};}
  createScriptProcessor(){
    const node={connect(){},disconnect(){clearInterval(node.timer)},onaudioprocess:null};
    node.timer=setInterval(()=>{
      const a=new Float32Array(4096);for(let i=0;i<a.length;i++)a[i]=Math.sin(i/10)*.2;
      if(node.onaudioprocess){window.processFrames++;node.onaudioprocess({inputBuffer:{getChannelData:()=>a}});}
    },20);return node;
  }
  async close(){}
};
"""


def main():
    case = fixture.CopilotTests('test_primary_idle_no_capture_and_reversible_legacy_entry')
    case.setUp(); case.premium()
    application = case.app
    server = make_server('127.0.0.1', 0, application, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    output = Path('/tmp/kilas-copilot-browser'); output.mkdir(exist_ok=True)
    report = {'paid_provider_calls': 0, 'real_microphone_calls': 0, 'cases': []}
    provider_calls = []
    hold = threading.Event()
    slow = [False]
    def stt(raw):
        provider_calls.append('stt')
        if slow[0]: hold.wait(8)
        return 'When can you start?'
    def text(system, content):
        provider_calls.append('text')
        if system.startswith('Translate'):
            yield from fixture.answer(json.dumps({'source_translation': 'Kapan Anda bisa mulai?', 'reply_translation': 'Bisa jelaskan jadwalnya?'}))
        else:
            yield from fixture.answer('Could you clarify the timeline?')
    try:
        with patch.object(copilot, 'configured', return_value=True), patch.object(copilot, 'transcribe', side_effect=stt), patch.object(copilot, 'text_stream', side_effect=text), patch.object(audio_provider, 'request', side_effect=AssertionError('Real provider forbidden')), patch.object(translator_languages, 'classic_names', return_value=translator_languages.names(translator_languages.CLASSIC)), sync_playwright() as pw:
            executable = os.environ.get('KILAS_QA_CHROMIUM') or ('/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None)
            browser = pw.chromium.launch(**({'executable_path': executable} if executable else {}), headless=True, args=['--no-sandbox'])
            cookie = case.client.get_cookie('session')
            for width in (360, 768, 1440):
                context = browser.new_context(viewport={'width': width, 'height': 960})
                context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin}])
                context.add_init_script(FAKE_MIC)
                page = context.new_page(); errors=[]
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin) else route.abort())
                page.goto(origin+'/kilas-ai', wait_until='networkidle')
                expect(page.locator('#copilot-state')).to_have_text('Mikrofon mati')
                assert page.evaluate('micRequests') == 0
                assert not page.locator('#copilot-translate').is_checked()
                expect(page.locator('#copilot-target-wrap')).to_be_hidden()
                assert not page.locator('textarea').count()
                assert 'AI Chat' not in page.locator('body').inner_text()
                assert page.locator('.kilas-profile-menu[open]').count() == 0
                page.screenshot(path=str(output/f'idle-{width}.png'),full_page=True,animations='disabled')
                page.locator('#copilot-mic').click()
                expect(page.locator('#copilot-error')).to_contain_text('Centang izin')
                assert page.evaluate('micRequests') == 0
                page.locator('#copilot-consent').check()
                page.locator('#copilot-mic').click()
                expect(page.locator('#copilot-state')).to_have_text('Mendengarkan…')
                before = len(provider_calls)
                page.wait_for_function('processFrames>4')
                assert len(provider_calls) == before, 'No provider work before explicit second tap'
                assert page.locator('#copilot-mic').get_attribute('aria-pressed') == 'true'
                page.screenshot(path=str(output/f'listening-{width}.png'), full_page=True)
                page.locator('#copilot-mic').click()
                expect(page.locator('.copilot-reply')).to_have_text('Could you clarify the timeline?')
                expect(page.locator('#copilot-state')).to_contain_text('Jawaban siap')
                assert page.evaluate('stoppedTracks') >= 1
                assert page.locator('.copilot-source').count() == 0
                assert len(provider_calls) == before+2
                page.screenshot(path=str(output/f'results-off-{width}.png'),full_page=True,animations='disabled')
                page.wait_for_timeout(150)
                assert page.evaluate('micRequests') == 1, 'No automatic rearm'
                page.locator('#copilot-translate').check()
                expect(page.locator('#copilot-target-wrap')).to_be_visible()
                assert page.locator('#copilot-target option:checked').text_content() == 'Bahasa Indonesia'
                page.locator('#copilot-mic').click();page.wait_for_function('processFrames>10')
                page.locator('#copilot-mic').click()
                expect(page.locator('.copilot-reply')).to_have_count(2)
                expect(page.locator('.copilot-reply-translation').first).to_have_text('Bisa jelaskan jadwalnya?')
                expect(page.locator('.copilot-source').first).to_have_text('When can you start?')
                page.locator('#copilot-text-size').select_option('26')
                assert page.locator('.copilot-reply').first.evaluate('e=>getComputedStyle(e).fontSize') == '26px'
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
                page.screenshot(path=str(output/f'results-on-{width}.png'), full_page=True)
                page.locator('#copilot-translate').uncheck()
                assert page.locator('.copilot-source').count() == 0
                assert page.locator('.copilot-reply-translation').count() == 0
                session_url=page.url;page.reload(wait_until='networkidle')
                expect(page.locator('.copilot-reply')).to_have_count(2)
                assert page.evaluate('micRequests') == 0
                assert page.locator('.copilot-source').count() == 0
                # Drawer/Profile starts closed; preserves the existing account controls.
                page.locator('[data-premium-menu]').click()
                expect(page.locator('#premium-sidebar')).to_be_visible()
                page.wait_for_function("Math.abs(document.querySelector('#premium-sidebar').getBoundingClientRect().x)<1")
                expect(page.locator('#premium-sidebar .chat-products')).to_contain_text('Finance')
                page.screenshot(path=str(output/f'sidebar-closed-{width}.png'),full_page=False,animations='disabled')
                page.locator('#premium-sidebar .kilas-profile-menu>summary').click()
                expect(page.locator('#premium-sidebar .kilas-profile-options')).to_contain_text('Credits & Usage')
                assert abs(page.locator('#premium-sidebar').bounding_box()['x'])<1
                page.screenshot(path=str(output/f'sidebar-{width}.png'), full_page=False, animations='disabled')
                page.keyboard.press('Escape')
                # Permission failure and cancellation while getUserMedia remains unresolved.
                page.locator('#copilot-consent').check()
                page.evaluate("micPermission='denied'")
                page.locator('#copilot-mic').click();expect(page.locator('#copilot-error')).to_contain_text('Izin mikrofon ditolak')
                page.evaluate("micPermission='pending'")
                page.locator('#copilot-mic').click();expect(page.locator('#copilot-cancel')).to_be_visible()
                page.locator('#copilot-cancel').click();page.evaluate('pendingMic()')
                expect(page.locator('#copilot-state')).to_have_text('Mikrofon mati')
                page.wait_for_function('stoppedTracks>=1')
                page.evaluate("micPermission='granted'")
                page.locator('#copilot-mic').click();expect(page.locator('#copilot-state')).to_have_text('Mendengarkan…')
                page.locator('#copilot-cancel').click()
                assert page.evaluate('stoppedTracks') >= 2
                assert not errors,errors
                for path,active in (('/kilas-translator/live?classic=1','Translator'),('/kilas-translator?mode=voiceover','Voice Over')):
                    page.goto(origin+path,wait_until='networkidle')
                    expect(page.locator('.copilot-task-nav a[aria-current=page]')).to_have_text(active)
                    assert page.locator('#premium-sidebar').count()==1
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(path,width)
                    assert page.evaluate('micRequests')==0
                    if active=='Voice Over':assert page.locator('#audio-script').count()==1
                    else:assert page.locator('#live-setup-form').count()==1
                    page.screenshot(path=str(output/f'{active.replace(" ","-")}-{width}.png'),full_page=True)
                report['cases'].append({'width':width,'idle_start_stop_results_translation_history_consent_permission_cancel_profile_overflow':'PASS'})
                context.close()
            # Network/interrupt/cancellation verification with the real request stack.
            context = browser.new_context(viewport={'width':1280,'height':900})
            context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}]);context.add_init_script(FAKE_MIC)
            page = context.new_page();page.goto(origin+'/kilas-ai',wait_until='networkidle');page.locator('#copilot-consent').check()
            slow[0]=True;page.locator('#copilot-mic').click();page.wait_for_function('processFrames>4');page.locator('#copilot-mic').click()
            expect(page.locator('#copilot-state')).to_contain_text('Mengenali')
            page.locator('#copilot-cancel').click();expect(page.locator('#copilot-state')).to_have_text('Mikrofon mati')
            hold.set();slow[0]=False;page.wait_for_timeout(250)
            expect(page.locator('.copilot-reply')).to_have_count(0)
            page.locator('#copilot-mic').click();page.wait_for_function('processFrames>10')
            page.goto(origin+'/products/start',wait_until='networkidle')
            assert page.evaluate('micRequests') == 0
            assert not page.locator('.copilot-reply').count()
            report['cases'].append({'cancellation_in_flight_and_navigation_cleanup':'PASS'})
            browser.close()
    finally:
        hold.set();server.shutdown()
    (output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__ == '__main__': main()
