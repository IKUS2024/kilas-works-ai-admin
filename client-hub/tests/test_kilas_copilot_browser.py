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
    arabic = [False]
    broken_translation=[False]
    hold = threading.Event()
    slow = [False]
    provider_entered=threading.Event()
    def stt(raw):
        provider_calls.append('stt')
        if slow[0]:
            provider_entered.set();hold.wait(8)
        return 'شكراً على مساعدتك' if arabic[0] else 'Where did you study, and what relevant work experience do you have?'
    def text(system, content, **options):
        provider_calls.append('text')
        if system.startswith('Translate'):
            if broken_translation[0]:
                yield from fixture.answer('{bad json');return
            yield from fixture.answer(json.dumps({'source_translation': 'Anda sekolah di mana, dan pengalaman kerja apa yang relevan?', 'reply_translation': 'Saya bersekolah di … (isi sendiri). Pengalaman saya yang relevan adalah … (isi sendiri). Tugas saya mencakup … (isi sendiri), dengan hasil … (isi sendiri).'}))
        else:
            yield from fixture.answer('على الرحب والسعة، يسعدني مساعدتك.' if arabic[0] else "I studied at … (fill in yourself). My relevant experience is … (fill in yourself). My role involved … (fill in yourself), and the result was … (fill in yourself).")
    try:
        with patch.object(copilot, 'configured', return_value=True), patch.object(copilot, 'transcribe', side_effect=stt), patch.object(copilot, 'text_stream', side_effect=text), patch.object(audio_provider, 'request', side_effect=AssertionError('Real provider forbidden')), patch.object(translator_languages, 'classic_names', return_value=translator_languages.names(translator_languages.CLASSIC)), sync_playwright() as pw:
            executable = os.environ.get('KILAS_QA_CHROMIUM') or ('/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None)
            browser = pw.chromium.launch(**({'executable_path': executable} if executable else {}), headless=True, args=['--no-sandbox'])
            cookie = case.client.get_cookie('session')
            for width,height in ((360,740),(393,786),(768,1024),(1440,900)):
                context = browser.new_context(viewport={'width': width, 'height': height})
                context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin},{'name':'kilas_language','value':'id','url':origin}])
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
                assert page.locator('.copilot-help').count()==0
                expect(page.locator('.copilot-footer')).to_be_visible()
                expect(page.locator('.copilot-footer')).to_contain_text('AI hanya memberikan teks')
                expect(page.locator('.copilot-language-badge')).to_have_text('Bahasa percakapan otomatis')
                assert 'Powered by OpenAI' not in page.locator('body').inner_text()
                assert page.locator('[data-copilot-style=santai]').is_visible()
                assert page.locator('#copilot-trigger').bounding_box()['y']+page.locator('#copilot-trigger').bounding_box()['height']<height-20
                assert page.locator('.copilot-task-nav').bounding_box()['height']<=48
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                brand=page.locator('body>.premium-mobile-header>.premium-brand').bounding_box()
                assert abs(brand['x']+brand['width']/2-width/2)<2,brand
                assert page.locator('.copilot-main h1').bounding_box()['width']<=width-32
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
                expect(page.locator('.copilot-reply')).to_have_text("I studied at … (fill in yourself). My relevant experience is … (fill in yourself). My role involved … (fill in yourself), and the result was … (fill in yourself).")
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
                expect(page.locator('.copilot-reply-translation').first).to_have_text('Saya bersekolah di … (isi sendiri). Pengalaman saya yang relevan adalah … (isi sendiri). Tugas saya mencakup … (isi sendiri), dengan hasil … (isi sendiri).')
                expect(page.locator('#copilot')).to_have_attribute('data-state','idle')
                expect(page.locator('.copilot-source').first).to_have_text('Where did you study, and what relevant work experience do you have?')
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
                expect(page.locator('#premium-sidebar .kilas-profile-options')).to_contain_text('Kredit & Penggunaan')
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
                page.locator('[data-premium-menu]').click()
                expect(page.locator('body')).to_have_class(__import__('re').compile('.*premium-menu-open.*'))
                for path,active in (('/kilas-translator/live?classic=1','Translator'),('/kilas-translator?mode=voiceover','Voice Over')):
                    page.goto(origin+path,wait_until='networkidle')
                    expect(page.locator('.copilot-task-nav a[aria-current=page]')).to_have_text(active)
                    assert page.locator('#premium-sidebar').count()==0
                    assert page.locator('[data-premium-menu]').count()==0
                    assert not page.locator('body').evaluate("e=>e.classList.contains('premium-menu-open')")
                    assert page.locator('body>.wrap').evaluate('e=>{const box=e.getBoundingClientRect();return Math.abs(box.x-(innerWidth-box.width)/2)<2}')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(path,width)
                    assert page.evaluate('micRequests')==0
                    if active=='Voice Over':
                        assert page.locator('#audio-script').count()==1
                        page.locator('[aria-controls=audio-history]').click()
                        expect(page.locator('#audio-history')).to_be_visible()
                        page.locator('[aria-controls=audio-history]').click()
                    else:assert page.locator('#live-setup-form').count()==1
                    page.screenshot(path=str(output/f'{active.replace(" ","-")}-{width}.png'),full_page=True)
                    if active=='Voice Over':
                        page.locator('#audio-script').fill('Unsaved Voice Over script')
                        page.once('dialog',lambda dialog:dialog.dismiss())
                        page.locator('.copilot-task-nav a').filter(has_text='Copilot').click()
                        expect(page.locator('#audio-script')).to_have_value('Unsaved Voice Over script')
                        assert '/kilas-translator' in page.url
                report['cases'].append({'width':width,'reply_top_off':off_y,'reply_top_on':on_y,'one_tap_start_stop_results_translation_history_permission_cancel_profile_overflow':'PASS'})
                page.goto(origin+'/kilas-ai',wait_until='networkidle')
                page.go_back(wait_until='networkidle')
                assert page.locator('#premium-sidebar').count()==0
                page.go_forward(wait_until='networkidle')
                assert page.locator('#premium-sidebar').count()==1
                assert page.locator('.premium-menu-open').count()==0
                context.close()
            # A separate disposable owner keeps the additional language fixture
            # inside the real per-account budget; no quota guard is mocked.
            rtl_case=fixture.CopilotTests();rtl_case.setUp();rtl_case.premium();rtl_cookie=rtl_case.client.get_cookie('session')
            rtl=browser.new_context(viewport={'width':393,'height':786})
            rtl.add_cookies([{'name':rtl_cookie.key,'value':rtl_cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}]);rtl.add_init_script(FAKE_MIC)
            rtl_page=rtl.new_page();rtl_page.goto(origin+'/kilas-ai',wait_until='networkidle');arabic[0]=True
            rtl_page.locator('#copilot-mic').click();rtl_page.wait_for_function('processFrames>4');rtl_page.locator('#copilot-trigger').click()
            expect(rtl_page.locator('.copilot-reply')).to_have_text('على الرحب والسعة، يسعدني مساعدتك.')
            # A complete text delta may still be in the streaming element.
            # Inspect the final rendered result after the saved completion.
            expect(rtl_page.locator('#copilot')).to_have_attribute('data-state','idle')
            expect(rtl_page.locator('.copilot-reply')).to_have_attribute('dir','auto')
            rtl_page.wait_for_function("getComputedStyle(document.querySelector('.copilot-reply')).direction==='rtl'",timeout=5000)
            assert rtl_page.locator('.copilot-reply').evaluate('e=>getComputedStyle(e).direction')=='rtl'
            rtl_page.screenshot(path=str(output/'results-ar-393.png'),full_page=True);arabic[0]=False;rtl.close()
            report['cases'].append({'arabic_auto_direction_mocked_reply':'PASS'})
            # A stalled session POST cannot delay listening; cancellation after
            # stop aborts it before any provider processing can start.
            delayed=browser.new_context(viewport={'width':393,'height':786})
            delayed.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}]);delayed.add_init_script(FAKE_MIC)
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
            context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}]);context.add_init_script(FAKE_MIC)
            page = context.new_page();page.goto(origin+'/kilas-ai',wait_until='networkidle')
            provider_entered.clear();slow[0]=True;page.locator('#copilot-mic').click();page.wait_for_function('processFrames>4');page.locator('#copilot-mic').click()
            expect(page.locator('#copilot-state')).to_contain_text('Mengenali')
            expect(page.locator('#copilot-trigger')).to_be_disabled()
            # Status is queued before STT enters; wait for the admitted call so
            # its normal start cannot be miscounted as a second-tap duplicate.
            assert provider_entered.wait(3), 'Admitted STT must enter before duplicate-call snapshot'
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
            # Optional-stage recovery keeps one primary/history turn and never
            # touches the microphone or STT again; controls survive reload.
            slow[0]=False;hold.set();arabic[0]=False
            repair_owner=fixture.CopilotTests();repair_owner.setUp();repair_owner.premium();repair_cookie=repair_owner.client.get_cookie('session')
            repair=browser.new_context(viewport={'width':393,'height':850})
            repair.add_cookies([{'name':repair_cookie.key,'value':repair_cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}]);repair.add_init_script(FAKE_MIC)
            repair_page=repair.new_page();repair_page.goto(origin+'/kilas-ai',wait_until='networkidle')
            repair_page.locator('#copilot-translate').check();repair_page.locator('[data-copilot-style=profesional]').click()
            broken_translation[0]=True;repair_page.locator('#copilot-mic').click();repair_page.wait_for_function('processFrames>4');repair_page.locator('#copilot-trigger').click()
            expect(repair_page.locator('#copilot')).to_have_attribute('data-state','idle');expect(repair_page.locator('.copilot-translation-retry')).to_be_visible()
            expect(repair_page.locator('.copilot-reply')).to_contain_text('I studied at');expect(repair_page.locator('.copilot-reply-translation')).to_have_text('Terjemahan gagal. Jawaban tersimpan.')
            repair_page.evaluate('document.activeElement?.blur();window.scrollTo(0,0)')
            repair_page.screenshot(path=str(output/'translation-failed-393.png'),full_page=True)
            repair_page.reload(wait_until='networkidle');assert repair_page.locator('#copilot-translate').is_checked();assert repair_page.locator('#copilot-style').input_value()=='profesional'
            before_stt=provider_calls.count('stt');before_text=provider_calls.count('text');broken_translation[0]=False
            repair_page.locator('.copilot-translation-retry').click();repair_page.evaluate("document.querySelector('.copilot-translation-retry')?.click()")
            expect(repair_page.locator('#copilot')).to_have_attribute('data-state','idle');expect(repair_page.locator('.copilot-reply-translation')).to_contain_text('Saya bersekolah')
            assert provider_calls.count('stt')==before_stt;assert provider_calls.count('text')==before_text+1;assert repair_page.locator('.copilot-reply').count()==1;assert repair_page.evaluate('micRequests')==0
            repair_page.evaluate('document.activeElement?.blur();window.scrollTo(0,0)')
            repair_page.screenshot(path=str(output/'translation-recovered-393.png'),full_page=True);repair.close()
            report['cases'].append({'translation_failure_preserves_primary_explicit_translation_only_retry_no_mic_no_stt_one_history_turn':'PASS'})
            browser.close()
            # Native browser MediaStream + AudioContext + PCM/WAV path. Only the
            # hardware source is Chromium's synthetic mic; no JS capture mocks.
            native=pw.chromium.launch(**({'executable_path':executable} if executable else {}),headless=True,args=['--no-sandbox','--use-fake-device-for-media-stream'])
            native_context=native.new_context(viewport={'width':393,'height':786},permissions=['microphone'])
            native_context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}])
            native_context.add_init_script('''
                window.nativeMicCalls=0;window.nativeTracks=[];window.workletCalls=0;
                const Worklet=window.AudioWorkletNode;window.AudioWorkletNode=class extends Worklet{constructor(...args){super(...args);window.workletCalls++;}};
                const get=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
                navigator.mediaDevices.getUserMedia=async options=>{window.nativeMicCalls++;const stream=await get(options);window.nativeTracks=stream.getTracks();return stream;};
            ''')
            native_page=native_context.new_page()
            native_page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
            native_page.goto(origin+'/kilas-ai',wait_until='networkidle')
            assert native_page.evaluate('nativeMicCalls')==0
            native_page.locator('#copilot-mic').click()
            expect(native_page.locator('#copilot-state')).to_have_text('Mendengarkan…')
            assert native_page.evaluate("nativeTracks.length===1&&nativeTracks[0].readyState==='live'&&workletCalls===1")
            before_native=len(provider_calls);native_page.wait_for_timeout(1600)
            assert len(provider_calls)==before_native
            native_page.locator('#copilot-trigger').click()
            expect(native_page.locator('.copilot-reply')).to_have_text("I studied at … (fill in yourself). My relevant experience is … (fill in yourself). My role involved … (fill in yourself), and the result was … (fill in yourself).")
            assert native_page.evaluate("nativeMicCalls===1&&nativeTracks.every(track=>track.readyState==='ended')")
            report['cases'].append({'native_browser_mediastream_audio_context_pcm_wav_one_tap':'PASS','hardware':'Chromium synthetic device','paid_calls':0})
            native.close()
            # Existing one-sync-worker deployment: short admission/status/cancel
            # must all work while the synthetic provider remains blocked.
            sync_server=make_server('127.0.0.1',0,application,threaded=False)
            threading.Thread(target=sync_server.serve_forever,daemon=True).start()
            hold.clear();provider_entered.clear();slow[0]=True
            op='sync_background_'+str(time.time_ns());origin_sync=f'http://127.0.0.1:{sync_server.server_port}'
            try:
                response=requests.post(origin_sync+f'/kilas-ai/copilot/sessions/{case.ident}/{op}/process',cookies={cookie.key:cookie.value},data={'csrf_token':'copilot-csrf','consent':'yes'},files={'audio':('recording.wav',fixture.recording(),'audio/wav')},timeout=2)
                assert response.status_code==202;assert provider_entered.wait(2)
                started=time.monotonic();assert requests.get(origin_sync+'/healthz',timeout=1).status_code==200;assert time.monotonic()-started<1
                snapshot=requests.get(origin_sync+response.json()['status_url'],cookies={cookie.key:cookie.value},timeout=1)
                assert snapshot.json()['state']=='processing'
                before=provider_calls.count('text')
                canceled=requests.post(origin_sync+f'/kilas-ai/copilot/sessions/{case.ident}/{op}/cancel',cookies={cookie.key:cookie.value},data={'csrf_token':'copilot-csrf'},timeout=1)
                assert canceled.status_code==200;assert not copilot.active(case.owner,case.ident,op)
                hold.set();time.sleep(.3);assert provider_calls.count('text')==before;assert copilot.turns(case.owner,case.ident)==[]
                report['cases'].append({'single_sync_wsgi_responsive_during_provider_wait_and_cancel':'PASS'})
            finally:hold.set();sync_server.shutdown()
    finally:
        hold.set();server.shutdown()
    (output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__ == '__main__': main()
