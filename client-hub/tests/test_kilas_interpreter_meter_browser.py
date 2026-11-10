"""Input-driven waveform through real Chromium capture and Flask, synthetic wire only."""
import json
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
        with case.enabled(),patch.object(fixture.calls.wire,'connect',side_effect=connect),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
            for width,height in ((320,740),(393,852),(768,1024),(1440,1000)):
                context=browser.new_context(viewport={'width':width,'height':height},reduced_motion='reduce' if width==768 else 'no-preference')
                cookie=case.client.get_cookie('session')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
                context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                context.add_init_script(MIC_LEVEL)
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(origin+'/kilas-translator/interpreter',wait_until='networkidle')
                page.locator('#interpreter-consent').check();page.locator('#interpreter-start').click()
                meter=page.locator('#interpreter-microphone');logo=page.locator('#interpreter-orb')
                expect(meter).to_be_hidden();assert page.evaluate('micRequests')==0
                logo.click();expect(meter).to_have_attribute('data-active','true')
                # Capturing locally is not evidence that the provider connected.
                expect(page.locator('#interpreter-state')).to_have_text('Connecting…')
                expect(meter).to_have_text('Microphone on')
                page.wait_for_function("document.querySelector('#interpreter-state').dataset.state==='listening'")
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
                logo.click();page.wait_for_function("document.querySelector('#interpreter-state').dataset.state==='listening'")
                expect(meter).to_be_visible();assert len(wires)==before
                page.locator('#interpreter-right').click();expect(meter).to_be_hidden()
                logo.click();page.wait_for_function("document.querySelector('#interpreter-state').dataset.state==='listening'")
                page.evaluate("micStream.getTracks()[0].dispatchEvent(new Event('ended'))")
                expect(page.locator('#interpreter-state')).to_have_text('Check the connected microphone, then choose a direction again.')
                expect(meter).to_be_hidden()
                logo.click();page.wait_for_function("document.querySelector('#interpreter-state').dataset.state==='listening'")
                page.evaluate("window.dispatchEvent(new Event('pagehide'))")
                expect(meter).to_be_hidden();assert page.evaluate('micRequests===micStops')
                page.locator('#interpreter-end').click();expect(page.locator('#interpreter-setup')).to_be_visible()
                assert not errors,errors
                evidence.append({'width':width,'result':'PASS','input':'real AudioWorklet with synthetic amplitude/silence','connection':'delayed setup distinguished from local mic','reset':'Finish, playback, idle, repeat, direction, track ended, pagehide','reduced_motion':width==768})
                print(json.dumps(evidence[-1]),flush=True);context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps(evidence,indent=2))
    finally:
        for wire in wires:wire.shutdown()
        server.shutdown();case.doCleanups()

if __name__=='__main__':main()
