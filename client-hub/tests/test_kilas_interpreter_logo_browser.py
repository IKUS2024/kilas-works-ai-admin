"""Actual K-logo touch/keyboard control through Flask and a synthetic wire.

The microphone is an oscillator; no physical device or paid provider is used.
"""
import json
import logging
import os
from pathlib import Path
import shutil
from threading import Thread, Timer
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_interpreter as fixture
from test_kilas_interpreter_hardened_browser import MIC
from test_kilas_interpreter_tap_browser import Wire


class LogoWire(Wire):
    def send(self, raw):
        if json.loads(raw).get('realtimeInput')=={'activityEnd':{}}:
            # Keep Processing observable while proving the mic already stopped.
            timer=Timer(.35,lambda:super(LogoWire,self).send(raw));timer.daemon=True;timer.start()
        else:super().send(raw)


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case=fixture.InterpreterTests();case.setUp()
    server=make_server('127.0.0.1',0,case.client.application,threaded=True)
    Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}';wires=[];fail=[False];evidence=[]
    output=Path('/tmp/kilas-interpreter-logo');output.mkdir(exist_ok=True)
    def connect():
        wire=LogoWire(fail[0]);wires.append(wire);return wire
    def listening(page):page.wait_for_function("document.querySelector('#interpreter-state').dataset.state==='listening'")
    def ended(page):page.wait_for_function("document.querySelector('#interpreter-state').dataset.state==='ended'")
    try:
        with case.enabled(),patch.object(fixture.calls.wire,'connect',side_effect=connect),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
            for width,height in ((320,740),(393,852),(768,1024),(1440,1000)):
                mobile=width<500
                context=browser.new_context(viewport={'width':width,'height':height},is_mobile=mobile,has_touch=mobile)
                cookie=case.client.get_cookie('session')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
                context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                context.add_init_script(MIC)
                context.add_init_script("window.audioContexts=0;const Audio=window.AudioContext;window.AudioContext=new Proxy(Audio,{construct(target,args){window.audioContexts++;return Reflect.construct(target,args);}});")
                page=context.new_page();errors=[];requests=[]
                page.on('request',lambda request:requests.append(request.url) if '/interpreter/' in request.url else None)
                page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(origin+'/kilas-translator/interpreter',wait_until='networkidle')
                page.locator('#interpreter-consent').check();page.locator('#interpreter-start').click()
                logo=page.locator('#interpreter-orb');image=logo.locator('img')
                expect(logo).to_have_role('button');expect(logo).to_be_focused()
                expect(logo).to_have_attribute('aria-label','Start listening: Indonesian to English')
                expect(page.locator('#interpreter-current-direction')).to_have_text('Indonesian → English')
                assert logo.evaluate('e=>e.tagName')=='BUTTON'
                box=logo.bounding_box();assert box['width']>=44 and box['height']>=44
                assert page.evaluate('micRequests')==0
                # Selection, including repeated mobile taps and keyboard activation,
                # must not even ask readiness or construct an audio context.
                baseline=len(requests)
                for selector,key in [('#interpreter-right',None),('#interpreter-left','Space'),('#interpreter-right','Enter'),('#interpreter-left',None)]:
                    card=page.locator(selector)
                    if key:card.press(key)
                    elif mobile:card.tap()
                    else:card.click()
                    expect(card).to_have_attribute('aria-pressed','true')
                page.wait_for_timeout(100)
                assert len(requests)==baseline
                assert page.evaluate('micRequests')==0 and page.evaluate('audioContexts')==0
                def hit_k():
                    # Hit the actual visible K pixels, never the language cards.
                    if mobile:image.tap()
                    else:image.click()
                for cycle in range(3):
                    before=len(wires)
                    if cycle==0:hit_k()
                    elif cycle==1:
                        mic_count=page.evaluate('micRequests');page.locator('#interpreter-right').press('Enter')
                        expect(page.locator('#interpreter-right')).to_have_attribute('aria-pressed','true')
                        assert page.evaluate('micRequests')==mic_count and len(wires)==before
                        hit_k()
                    else:
                        logo.focus();assert logo.evaluate("e=>getComputedStyle(e).outlineWidth")=='3px'
                        logo.press('Space')
                    listening(page)
                    source,target=('Indonesian','English') if cycle==0 else ('English','Indonesian')
                    expect(page.locator('#interpreter-current-direction')).to_have_text(source+' → '+target)
                    expect(logo).to_have_attribute('aria-pressed','true')
                    expect(logo).to_have_attribute('aria-label','Stop and translate')
                    expect(logo).to_be_enabled()
                    for selector in ['#interpreter-left','#interpreter-right']:
                        expect(page.locator(selector)).to_be_disabled()
                        page.locator(selector).evaluate('e=>{for(let i=0;i<5;i++)e.click()}')
                    expect(page.locator('#interpreter-current-direction')).to_have_text(source+' → '+target)
                    assert logo.evaluate('e=>getComputedStyle(e).borderColor')=='rgb(189, 71, 0)'
                    assert len(wires)==before+1
                    stops=page.evaluate('micStops')
                    if cycle==2:logo.press('Enter')
                    else:hit_k()
                    assert page.evaluate('micStops')==stops+1
                    expect(logo).to_have_attribute('aria-pressed','false')
                    expect(logo).to_have_attribute('aria-busy','true');expect(logo).to_be_disabled()
                    page.evaluate("()=>{for(let i=0;i<10;i++)for(const id of ['orb','left','right'])document.querySelector('#interpreter-'+id).click();}")
                    ended(page)
                    expect(logo).to_be_enabled();expect(logo).to_have_attribute('aria-busy','false')
                    expect(logo).to_have_attribute('aria-label',f'Start listening: {source} to {target}')
                    stream=[m['realtimeInput'] for m in wires[-1].messages if 'realtimeInput' in m]
                    assert stream[0]=={'activityStart':{}} and stream[-1]=={'activityEnd':{}}
                    assert sum('activityEnd' in m for m in stream)==1 and any('audio' in m for m in stream)
                    assert len(wires)==before+1
                    expect(page.locator('#interpreter-caption')).to_have_text('Good morning.' if cycle==0 else 'Selamat pagi.')
                page.locator('#interpreter-transcript').evaluate('e=>e.open=true')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                page.screenshot(path=str(output/f'logo-{width}.png'),full_page=True)
                if width==393:
                    # A second K press while browser permission is pending cancels,
                    # and a late permission result cannot attach a stale microphone.
                    before=len(wires)
                    page.evaluate("()=>{window.savedMic=navigator.mediaDevices.getUserMedia;navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>window.finishPermission=resolve);}")
                    hit_k();page.wait_for_function("typeof window.finishPermission==='function'")
                    expect(page.locator('#interpreter-left')).to_be_disabled()
                    page.locator('#interpreter-left').evaluate('e=>e.click()')
                    expect(page.locator('#interpreter-current-direction')).to_have_text('English → Indonesian')
                    hit_k();ended(page)
                    page.evaluate("async()=>{const stream=await savedMic();finishPermission(stream);navigator.mediaDevices.getUserMedia=savedMic;}")
                    expect(logo).to_have_attribute('aria-pressed','false');assert len(wires)==before
                    for mode,message in [('denied','Allow microphone access in your browser.'),('missing','Check the connected microphone, then choose a direction again.')]:
                        page.evaluate('(value)=>window.mockPermission=value',mode);hit_k()
                        expect(page.locator('#interpreter-state')).to_have_text(message)
                        expect(logo).to_be_enabled();assert len(wires)==before
                    page.evaluate("mockPermission='granted'");fail[0]=True
                    hit_k();listening(page);hit_k()
                    expect(page.locator('#interpreter-state')).to_have_text('Gemini ended the session.')
                    expect(logo).to_be_enabled();fail[0]=False
                    hit_k();listening(page);hit_k();ended(page)
                    expect(page.locator('#interpreter-caption')).to_have_text('Selamat pagi.')
                    # End and a direction change also fence input started from K.
                    hit_k();listening(page)
                    expect(page.locator('#interpreter-left')).to_be_disabled()
                    page.locator('#interpreter-left').evaluate('e=>e.click()')
                    expect(page.locator('#interpreter-current-direction')).to_have_text('English → Indonesian')
                    stops=page.evaluate('micStops');before=len(wires)
                    page.evaluate("()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'));}")
                    assert page.evaluate('micStops')==stops+1 and len(wires)==before
                    expect(page.locator('#interpreter-state')).to_contain_text('Session ended.')
                    expect(page.locator('#interpreter-right')).to_have_attribute('aria-pressed','true')
                    expect(logo).to_be_enabled()
                    page.locator('#interpreter-end').click();expect(page.locator('#interpreter-setup')).to_be_visible()
                else:page.locator('#interpreter-end').click()
                if width==768:
                    page.locator('#interpreter-language-a').select_option('ja');page.locator('#interpreter-language-b').select_option('fr')
                    page.locator('#interpreter-start').click()
                    expect(logo).to_have_attribute('aria-label','Start listening: Japanese to French')
                    hit_k();listening(page)
                    assert 'from Japanese into French' in wires[-1].messages[0]['setup']['systemInstruction']['parts'][0]['text']
                    hit_k();ended(page)
                    expect(page.locator('#interpreter-original')).to_have_attribute('lang','ja')
                    expect(page.locator('#interpreter-caption')).to_have_attribute('lang','fr')
                    page.locator('#interpreter-end').click()
                if width==1440:
                    # Run lost-cookie recovery last: the unauthenticated client
                    # cannot submit End, so its owned lease settles server-side.
                    page.locator('#interpreter-start').click();hit_k();listening(page)
                    context.clear_cookies()
                    expect(page.locator('#interpreter-login')).to_be_visible();expect(logo).to_be_disabled()
                assert not errors,errors
                evidence.append({'width':width,'result':'PASS','actual_target':'K image inside native button','input':'synthesized touch' if mobile else 'pointer','keyboard':'Space starts / Enter stops','directions':'default id→en, card-selected en→id, K reuses en→id','stop':'tracks stop immediately; one ordered activityEnd; output drains','provider':'synthetic wire; no paid requests'})
                print(json.dumps(evidence[-1]),flush=True);context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps(evidence,indent=2))
    finally:
        for wire in wires:wire.shutdown()
        server.shutdown();case.doCleanups()


if __name__=='__main__':main()
