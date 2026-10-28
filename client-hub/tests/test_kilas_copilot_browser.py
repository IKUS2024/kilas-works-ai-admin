"""Chromium, disposable SQLite, synthetic microphone and mocked provider only."""
import json
import os
import threading
import time
import requests
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
    provider_entered=threading.Event()
    def stt(raw):
        provider_calls.append('stt')
        if slow[0]:
            provider_entered.set();hold.wait(8)
        return 'When can you start?'
    def text(system, content, **options):
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
            for width,height in ((360,740),(393,786),(768,1024),(1440,900)):
                context = browser.new_context(viewport={'width': width, 'height': height})
                context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin}])
                context.add_init_script(FAKE_MIC)
                page = context.new_page(); errors=[]
                page.on('pageerror', lambda error: errors.append(str(error)))
                writes=[];page.on('request',lambda request:writes.append(request.url) if request.method=='POST' else None)
                page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin) else route.abort())
                page.goto(origin+'/kilas-ai', wait_until='networkidle')
                expect(page.locator('#copilot-state')).to_have_text('Mikrofon mati')
                assert page.evaluate('micRequests') == 0
                expect(page.locator('#copilot-wave')).to_be_hidden()
                expect(page.locator('#copilot-mic')).to_have_attribute('aria-pressed','false')
                assert not page.locator('#copilot-translate').is_checked()
                expect(page.locator('#copilot-target-wrap')).to_be_hidden()
                assert not page.locator('textarea').count()
                assert 'AI Chat' not in page.locator('body').inner_text()
                assert page.locator('.kilas-profile-menu[open]').count() == 0
                assert page.locator('.premium-skip').evaluate('e=>e.getBoundingClientRect().bottom<0')
                page.screenshot(path=str(output/f'idle-{width}.png'),full_page=True,animations='disabled')
                page.locator('#copilot-translate').check()
                page.screenshot(path=str(output/f'idle-on-{width}.png'),full_page=True,animations='disabled')
                page.locator('#copilot-translate').uncheck()
                assert page.locator('#copilot-consent').count()==0
                assert page.locator('.copilot-help[open]').count()==0
                expect(page.locator('.copilot-footer')).to_be_visible()
                expect(page.locator('.copilot-footer')).to_contain_text('AI hanya memberikan teks')
                expect(page.locator('#copilot-guidance')).to_contain_text('Audio diproses OpenAI setelah berhenti.')
                expect(page.locator('.copilot-language-badge')).to_have_text('Bahasa percakapan otomatis')
                assert 'Powered by OpenAI' not in page.locator('body').inner_text()
                assert page.locator('[data-copilot-style=santai]').is_visible()
                assert page.locator('#copilot-trigger').bounding_box()['y']+page.locator('#copilot-trigger').bounding_box()['height']<height-20
                assert page.locator('.copilot-task-nav').bounding_box()['height']<=48
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                brand=page.locator('body>.premium-mobile-header>.premium-brand').bounding_box()
                assert abs(brand['x']+brand['width']/2-width/2)<2,brand
                assert page.locator('.copilot-main h1').bounding_box()['width']<=width-32
                page.locator('.copilot-help>summary').click()
                expect(page.locator('#copilot-guidance')).to_be_visible()
                box=page.locator('.copilot-help-panel').bounding_box();assert box['x']>=0 and box['x']+box['width']<=width
                page.locator('.copilot-help>summary').click()
                page.locator('[data-copilot-style=profesional]').click()
                expect(page.locator('[data-copilot-style=profesional]')).to_have_attribute('aria-pressed','true')
                # Two rapid taps before permission resolves admit one capture.
                page.evaluate("document.querySelector('#copilot-mic').click();document.querySelector('#copilot-trigger').click()")
                expect(page.locator('#copilot-state')).to_have_text('Mendengarkan…')
                assert page.evaluate('micRequests')==1
                assert writes==[], 'Listening must not wait for or create a server session'
                before = len(provider_calls)
                page.wait_for_function('processFrames>4')
                assert len(provider_calls) == before, 'No provider work before explicit second tap'
                assert page.locator('#copilot-mic').get_attribute('aria-pressed') == 'true'
                expect(page.locator('#copilot-trigger')).to_have_attribute('aria-pressed','true')
                page.screenshot(path=str(output/f'listening-{width}.png'), full_page=True)
                page.locator('#copilot-trigger').click()
                expect(page.locator('.copilot-reply')).to_have_text('Could you clarify the timeline?')
                expect(page.locator('#copilot-state')).to_contain_text('Jawaban siap')
                expect(page.locator('#copilot')).to_have_attribute('data-state','idle')
                off_y=page.locator('.copilot-answer-card').first.bounding_box()['y'];assert off_y<500
                assert fixture.copilot.turns(case.owner,int(page.locator('#copilot').get_attribute('data-session-id')))[-1]['style']=='profesional'
                assert page.evaluate('stoppedTracks') >= 1
                assert page.locator('.copilot-source').count() == 0
                assert len(provider_calls) == before+2
                page.screenshot(path=str(output/f'results-off-{width}.png'),full_page=True,animations='disabled')
                page.wait_for_timeout(150)
                assert page.evaluate('micRequests') == 1, 'No automatic rearm'
                page.locator('#copilot-translate').check()
                expect(page.locator('#copilot-target-wrap')).to_be_visible()
                assert page.locator('#copilot-target option:checked').text_content() == 'Bahasa Indonesia'
                page.locator('#copilot-trigger').click();page.wait_for_function('processFrames>10')
                page.locator('#copilot-mic').click()
                expect(page.locator('.copilot-reply')).to_have_count(2)
                expect(page.locator('.copilot-reply-translation').first).to_have_text('Bisa jelaskan jadwalnya?')
                expect(page.locator('#copilot')).to_have_attribute('data-state','idle')
                expect(page.locator('.copilot-source').first).to_have_text('When can you start?')
                on_y=page.locator('.copilot-answer-card').first.bounding_box()['y'];assert on_y<820
                page.locator('#copilot-larger').click();page.locator('#copilot-larger').click()
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
                page.evaluate("micPermission='denied'")
                page.locator('#copilot-mic').click();expect(page.locator('#copilot-error')).to_contain_text('Izin mikrofon ditolak')
                page.evaluate("micPermission='pending'")
                page.locator('#copilot-mic').click();expect(page.locator('#copilot-cancel')).to_be_visible()
                expect(page.locator('#copilot-state')).to_have_text('Menghubungkan mikrofon…')
                pending_calls=page.evaluate('micRequests');page.evaluate("document.querySelector('#copilot-trigger').click()")
                expect(page.locator('#copilot-trigger')).to_be_disabled()
                assert page.evaluate('micRequests')==pending_calls
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
                    if active=='Voice Over':
                        page.locator('#audio-script').fill('Unsaved Voice Over script')
                        page.once('dialog',lambda dialog:dialog.dismiss())
                        page.locator('.copilot-task-nav a').filter(has_text='Copilot').click()
                        expect(page.locator('#audio-script')).to_have_value('Unsaved Voice Over script')
                        assert '/kilas-translator' in page.url
                report['cases'].append({'width':width,'reply_top_off':off_y,'reply_top_on':on_y,'one_tap_start_stop_results_translation_history_permission_cancel_profile_overflow':'PASS'})
                context.close()
            # A stalled session POST cannot delay listening; cancellation after
            # stop aborts it before any provider processing can start.
            delayed=browser.new_context(viewport={'width':393,'height':786})
            delayed.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}]);delayed.add_init_script(FAKE_MIC)
            stalled=delayed.new_page();stalled.goto(origin+'/kilas-ai',wait_until='networkidle')
            stalled.evaluate('''()=>{const fetch=window.fetch;window.createAttempts=0;window.fetch=(url,options)=>String(url)==='/kilas-ai/copilot/sessions'?(window.createAttempts++,new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError'))))):fetch(url,options)}''')
            stalled.locator('#copilot-mic').click();expect(stalled.locator('#copilot-state')).to_have_text('Mendengarkan…')
            assert stalled.evaluate('createAttempts')==0
            stalled.wait_for_function('processFrames>4');before_stall=len(provider_calls)
            stalled.locator('#copilot-mic').click();stalled.wait_for_function('createAttempts===1')
            stalled.locator('#copilot-cancel').click();expect(stalled.locator('#copilot')).to_have_attribute('data-state','idle')
            assert stalled.evaluate('stoppedTracks')==1 and len(provider_calls)==before_stall
            report['cases'].append({'listen_without_network_and_cancel_deferred_session':'PASS'})
            delayed.close()
            # Network/interrupt/cancellation verification with the real request stack.
            context = browser.new_context(viewport={'width':1280,'height':900})
            context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}]);context.add_init_script(FAKE_MIC)
            page = context.new_page();page.goto(origin+'/kilas-ai',wait_until='networkidle')
            slow[0]=True;page.locator('#copilot-mic').click();page.wait_for_function('processFrames>4');page.locator('#copilot-mic').click()
            expect(page.locator('#copilot-state')).to_contain_text('Mengenali')
            expect(page.locator('#copilot-trigger')).to_be_disabled()
            before_repeat=len(provider_calls)
            page.evaluate("document.querySelector('#copilot-trigger').click();document.querySelector('#copilot-mic').click()")
            assert len(provider_calls)==before_repeat
            page.locator('#copilot-cancel').click();expect(page.locator('#copilot-state')).to_have_text('Mikrofon mati')
            hold.set();slow[0]=False;page.wait_for_timeout(250)
            expect(page.locator('.copilot-reply')).to_have_count(0)
            page.locator('#copilot-mic').click();page.wait_for_function('processFrames>10')
            page.goto(origin+'/products/start',wait_until='networkidle')
            assert page.evaluate('micRequests') == 0
            assert not page.locator('.copilot-reply').count()
            report['cases'].append({'cancellation_in_flight_and_navigation_cleanup':'PASS'})
            browser.close()
            # Native browser MediaStream + AudioContext + PCM/WAV path. Only the
            # hardware source is Chromium's synthetic mic; no JS capture mocks.
            native=pw.chromium.launch(**({'executable_path':executable} if executable else {}),headless=True,args=['--no-sandbox','--use-fake-device-for-media-stream'])
            native_context=native.new_context(viewport={'width':393,'height':786},permissions=['microphone'])
            native_context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
            native_context.add_init_script('''
                window.nativeMicCalls=0;window.nativeTracks=[];
                const get=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
                navigator.mediaDevices.getUserMedia=async options=>{window.nativeMicCalls++;const stream=await get(options);window.nativeTracks=stream.getTracks();return stream;};
            ''')
            native_page=native_context.new_page()
            native_page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
            native_page.goto(origin+'/kilas-ai',wait_until='networkidle')
            assert native_page.evaluate('nativeMicCalls')==0
            native_page.locator('#copilot-mic').click()
            expect(native_page.locator('#copilot-state')).to_have_text('Mendengarkan…')
            assert native_page.evaluate("nativeTracks.length===1&&nativeTracks[0].readyState==='live'")
            before_native=len(provider_calls);native_page.wait_for_timeout(1600)
            assert len(provider_calls)==before_native
            native_page.locator('#copilot-trigger').click()
            expect(native_page.locator('.copilot-reply')).to_have_text('Could you clarify the timeline?')
            assert native_page.evaluate("nativeMicCalls===1&&nativeTracks.every(track=>track.readyState==='ended')")
            report['cases'].append({'native_browser_mediastream_audio_context_pcm_wav_one_tap':'PASS','hardware':'Chromium synthetic device','paid_calls':0})
            native.close()
            # Reproduce production's single sync WSGI worker: no cancel POST can
            # be served while this response is open. Heartbeats detect abort and
            # fence the next model without changing global Gunicorn settings.
            sync_server=make_server('127.0.0.1',0,application,threaded=False)
            threading.Thread(target=sync_server.serve_forever,daemon=True).start()
            hold.clear();provider_entered.clear();slow[0]=True
            op='sync_disconnect_'+str(time.time_ns())
            response=None
            try:
                response=requests.post(f'http://127.0.0.1:{sync_server.server_port}/kilas-ai/copilot/sessions/{case.ident}/{op}/process',
                    cookies={cookie.key:cookie.value},data={'csrf_token':'copilot-csrf','consent':'yes'},
                    files={'audio':('recording.wav',fixture.recording(),'audio/wav')},stream=True,timeout=(3,5))
                assert response.status_code==200
                assert provider_entered.wait(2)
                lines=response.iter_lines(chunk_size=1)
                assert any(b'heartbeat' in next(lines) for _ in range(8))
                before=provider_calls.count('text');response.close()
                deadline=time.monotonic()+3
                while copilot.active(case.owner,case.ident,op) and time.monotonic()<deadline:time.sleep(.05)
                assert not copilot.active(case.owner,case.ident,op)
                hold.set();time.sleep(.25)
                assert provider_calls.count('text')==before
                assert copilot.turns(case.owner,case.ident)==[]
                report['cases'].append({'single_sync_wsgi_disconnect_fence':'PASS'})
            finally:
                if response:response.close()
                hold.set();sync_server.shutdown()
    finally:
        hold.set();server.shutdown()
    (output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__ == '__main__': main()
