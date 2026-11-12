"""Input-driven waveform through real Chromium capture and Flask, synthetic wire only."""
import json
from contextlib import ExitStack
import logging
import os
from pathlib import Path
import shutil
from threading import Thread
from time import sleep
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_interpreter as fixture
from test_kilas_interpreter_hardened_browser import MIC
from test_kilas_interpreter_tap_browser import Wire

MIC_LEVEL = MIC.replace("osc.frequency.value=220;osc.connect(out);osc.start();",
    "osc.frequency.value=220;const gain=ctx.createGain();gain.gain.value=0;window.micGain=gain.gain;window.micStream=out.stream;osc.connect(gain);gain.connect(out);osc.start();")

class MeterWire(Wire):
    def send(self, raw):
        if 'setup' in json.loads(raw):
            # Delay setup on the sender, not recv(): Wire deliberately uses a
            # short read timeout only after its immediate setup handshake.
            sleep(1.5)
        super().send(raw)


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case=fixture.InterpreterTests();case.setUp()
    server=make_server('127.0.0.1',0,case.client.application,threaded=True)
    Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}';wires=[];evidence=[]
    output=Path('/tmp/kilas-interpreter-meter');output.mkdir(exist_ok=True)
    def connect():
        wire=MeterWire();wires.append(wire);return wire
    try:
        with patch.object(fixture.calls.wire,'connect',side_effect=connect),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
            for width,height in ((320,740),(393,852),(768,1024),(1440,1000)):
                # Keep real production admission limits. Each viewport exercises
                # six fresh sessions, so it needs its own disposable account.
                if width!=320:
                    case=fixture.InterpreterTests()
                    case.id=lambda width=width:f'kilas-meter-browser-{width}'
                    case.setUp()
                with ExitStack() as scope:
                    scope.callback(case.doCleanups)
                    scope.enter_context(case.enabled())
                    context=browser.new_context(viewport={'width':width,'height':height},reduced_motion='reduce' if width==768 else 'no-preference')
                    cookie=case.client.get_cookie('session')
                    context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
                    context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                    context.add_init_script(MIC_LEVEL)
                    scope.callback(context.close)
                    page=context.new_page();errors=[];responses=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('response',lambda response:responses.append({'url':response.url,'status':response.status}) if '/interpreter/' in response.url and response.status>=400 else None)
                    def listening():
                        try:
                            page.wait_for_function("document.querySelector('#interpreter-state').dataset.state==='listening'")
                        except Exception:
                            diagnostic=page.evaluate("""()=>{const state=document.querySelector('#interpreter-state'),logo=document.querySelector('#interpreter-orb');return {state:state?.dataset.state,status:state?.textContent,pressed:logo?.getAttribute('aria-pressed'),disabled:logo?.disabled,micRequests:window.micRequests,micStops:window.micStops};}""")
                            diagnostic.update(width=width,wires=len(wires),errors=list(errors),failed_responses=list(responses))
                            (output/f'failure-{width}.json').write_text(json.dumps(diagnostic,indent=2))
                            print(json.dumps({'failure':diagnostic}),flush=True)
                            raise
                    page.goto(origin+'/kilas-translator/interpreter',wait_until='networkidle')
                    assert page.evaluate('micRequests')==0
                    expect(page.locator('#interpreter-active')).to_be_visible()
                    expect(page.locator('#interpreter-navigation')).to_be_visible()
                    assert page.locator('#interpreter-setup,#interpreter-start,#interpreter-swap').count()==0
                    expect(page.locator('#interpreter-consent-notice')).to_be_visible()
                    assert page.locator('#interpreter').get_attribute('data-speech-consent')=='false'
                    meter=page.locator('#interpreter-microphone');logo=page.locator('#interpreter-orb')
                    expect(meter).to_be_hidden();assert page.evaluate('micRequests')==0
                    logo.click();expect(meter).to_have_attribute('data-active','true')
                    # Capturing locally is not evidence that the provider connected.
                    expect(page.locator('#interpreter-state')).to_have_text('Connecting…')
                    expect(meter).to_have_text('Microphone on')
                    listening()
                    expect(page.locator('#interpreter-state')).to_have_text('Connected · listening')
                    bars='[data-mic-bar]'
                    assert page.locator(bars).evaluate_all('nodes=>nodes.every(n=>parseFloat(n.style.height)===3)')
                    page.evaluate('micGain.value=.03')
                    page.wait_for_function("parseFloat(document.querySelectorAll('[data-mic-bar]')[4].style.height)>8")
                    low=page.locator(bars).nth(4).evaluate('n=>parseFloat(n.style.height)')
                    page.evaluate('micGain.value=.15')
                    page.wait_for_function("parseFloat(document.querySelectorAll('[data-mic-bar]')[4].style.height)>22")
                    assert page.locator(bars).nth(4).evaluate('n=>parseFloat(n.style.height)')>low
                    page.screenshot(path=str(output/f'speech-{width}.png'),full_page=True)
                    page.evaluate('micGain.value=0')
                    page.wait_for_function("Array.from(document.querySelectorAll('[data-mic-bar]')).every(n=>parseFloat(n.style.height)===3)")
                    expect(meter).to_be_visible();page.screenshot(path=str(output/f'silence-{width}.png'),full_page=True)
                    if width==768:assert page.locator(bars).first.evaluate('n=>getComputedStyle(n).transitionDuration')=='0s'
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    before=len(wires);logo.click();expect(meter).to_be_hidden()
                    page.wait_for_function("document.querySelector('#interpreter-state').dataset.state==='idle'")
                    expect(meter).to_be_hidden();assert page.evaluate('micRequests===micStops')
                    logo.click();listening()
                    expect(meter).to_be_visible();assert len(wires)==before
                    page.locator('#interpreter-right').click();expect(meter).to_be_hidden()
                    logo.click();listening()
                    page.evaluate("micStream.getTracks()[0].dispatchEvent(new Event('ended'))")
                    expect(page.locator('#interpreter-state')).to_have_text('Check the connected microphone, then choose a direction again.')
                    expect(meter).to_be_hidden()
                    logo.click();listening()
                    # Native dropdown changes cancel capture immediately without choosing
                    # the opposite card or starting another provider/microphone.
                    for control,code in (('a','ja'),('b','fr')):
                        expect(page.locator('#interpreter-language-'+control)).to_be_enabled()
                        before=len(wires);requests=page.evaluate('micRequests')
                        page.locator('#interpreter-language-'+control).select_option(code)
                        expect(meter).to_be_hidden()
                        assert page.evaluate('micRequests===micStops')
                        assert len(wires)==before and page.evaluate('micRequests')==requests
                        expect(page.locator('#interpreter-right')).to_have_attribute('aria-pressed','true')
                        expect(page.locator('#interpreter-navigation')).to_be_visible()
                        logo.click();listening()
                    assert 'from French into Japanese' in wires[-1].messages[0]['setup']['systemInstruction']['parts'][0]['text']
                    # Withdrawing consent ends capture and cannot silently re-admit.
                    before=len(wires);requests=page.evaluate('micRequests')
                    page.locator('#interpreter-end').click()
                    expect(meter).to_be_hidden();assert page.evaluate('micRequests===micStops')
                    expect(page.locator('#interpreter-consent-notice')).to_be_visible()
                    assert page.locator('#interpreter').get_attribute('data-speech-consent')=='false'
                    assert page.evaluate('micRequests')==requests and len(wires)==before
                    expect(page.locator('#interpreter-direction-heading')).to_have_text('Agree & start')
                    assert page.evaluate('micRequests')==requests and len(wires)==before
                    logo.click();listening()
                    page.evaluate("window.dispatchEvent(new Event('pagehide'))")
                    expect(meter).to_be_hidden();assert page.evaluate('micRequests===micStops')
                    page.locator('#interpreter-end').click();expect(page.locator('#interpreter-active')).to_be_visible();assert page.locator('#interpreter').get_attribute('data-speech-consent')=='false'
                    assert not errors,errors
                    evidence.append({'width':width,'result':'PASS','input':'real AudioWorklet with synthetic amplitude/silence','connection':'delayed setup distinguished from local mic','reset':'Finish, playback, idle, repeat, direction, dropdowns, consent withdrawal, track ended, pagehide','reduced_motion':width==768})
                    print(json.dumps(evidence[-1]),flush=True)
            browser.close()
        (output/'verification.json').write_text(json.dumps(evidence,indent=2))
    finally:
        for wire in wires:wire.shutdown()
        server.shutdown();case.doCleanups()

if __name__=='__main__':main()
