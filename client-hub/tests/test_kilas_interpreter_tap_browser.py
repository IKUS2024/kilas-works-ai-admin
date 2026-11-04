"""Chromium -> authenticated Flask -> actual ordered relay -> synthetic wire.

No endpoint interception, physical microphone, or paid provider request.
"""
import base64
import json
import logging
import os
from pathlib import Path
from queue import Queue, Empty
import shutil
from threading import Event, Thread
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_interpreter as fixture
from test_kilas_interpreter_hardened_browser import MIC


class Wire:
    def __init__(self, fail=False):
        self.messages=[];self.incoming=Queue();self.closed=Event();self.fail=fail

    def send(self, raw):
        value=json.loads(raw);self.messages.append(value)
        if 'setup' in value:self.incoming.put(json.dumps({'setupComplete':{}}))
        if value.get('realtimeInput')=={'activityEnd':{}}:
            if self.fail:
                self.incoming.put(json.dumps({'error':{'code':500}}));return
            settings=self.messages[0]['setup']['systemInstruction']['parts'][0]['text']
            source,reply=('Selamat pagi.','Good morning.') if 'from Indonesian into English' in settings else ('Good morning.','Selamat pagi.')
            pcm=b'\x00\x20'*12000
            self.incoming.put(json.dumps({'serverContent':{
                'inputTranscription':{'text':source},'outputTranscription':{'text':reply},
                'modelTurn':{'parts':[{'inlineData':{'mimeType':'audio/pcm;rate=24000','data':base64.b64encode(pcm).decode()}}]},
                'turnComplete':True}}))

    def recv(self):
        import websocket
        if self.closed.is_set():raise websocket.WebSocketConnectionClosedException()
        try:
            return self.incoming.get(timeout=.1)
        except Empty:raise websocket.WebSocketTimeoutException() from None

    def settimeout(self, timeout):pass
    def shutdown(self):self.closed.set()


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case=fixture.InterpreterTests();case.setUp()
    server=make_server('127.0.0.1',0,case.client.application,threaded=True)
    Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}';wires=[];fail=[False];evidence=[]
    output=Path('/tmp/kilas-interpreter-tap');output.mkdir(exist_ok=True)
    def connect():
        wire=Wire(fail[0]);wires.append(wire);return wire
    try:
        with case.enabled(),patch.object(fixture.calls.wire,'connect',side_effect=connect),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
            for width,height in ((320,740),(393,852),(768,1024),(1440,1000)):
                context=browser.new_context(viewport={'width':width,'height':height},is_mobile=width<500,has_touch=width<500)
                cookie=case.client.get_cookie('session')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
                context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                context.add_init_script(MIC);page=context.new_page();errors=[]
                page.set_default_timeout(8000);page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(origin+'/kilas-translator/interpreter',wait_until='networkidle')
                page.locator('#interpreter-consent').check();page.locator('#interpreter-start').click()
                for direction,source,reply in (('left','Selamat pagi.','Good morning.'),('right','Good morning.','Selamat pagi.')):
                    button=page.locator('#interpreter-'+direction);before=len(wires)
                    button.click();page.wait_for_function("document.querySelector('#interpreter-state').dataset.state==='listening'")
                    assert len(wires)==before+1
                    wire=wires[-1]
                    assert wire.messages[0]['setup']['realtimeInputConfig']['automaticActivityDetection']=={'disabled':True}
                    assert wire.messages[1]=={'realtimeInput':{'activityStart':{}}}
                    assert not any('activityEnd' in m.get('realtimeInput',{}) for m in wire.messages)
                    expect(button).to_have_attribute('aria-label','Stop and translate')
                    # One synchronous burst exercises duplicate activation while Finish is pending.
                    page.evaluate("id=>{const b=document.getElementById(id);for(let i=0;i<10;i++)b.click();}",'interpreter-'+direction)
                    page.wait_for_function("document.querySelector('#interpreter-state').dataset.state==='ended'")
                    assert page.evaluate('micStops')>=1
                    page.locator('#interpreter-transcript').evaluate('e=>e.open=true')
                    expect(page.locator('#interpreter-original')).to_have_text(source)
                    expect(page.locator('#interpreter-caption')).to_have_text(reply)
                    expect(button).to_be_enabled();expect(button).to_have_attribute('aria-pressed','false')
                    stream=[m['realtimeInput'] for m in wire.messages if 'realtimeInput' in m]
                    assert stream[0]=={'activityStart':{}} and stream[-1]=={'activityEnd':{}}
                    assert sum('activityEnd' in m for m in stream)==1
                    assert any('audio' in m for m in stream)
                    assert len(wires)==before+1
                if width==393:
                    # Denied permission must be recoverable with no provider admission.
                    before=len(wires);page.evaluate("mockPermission='denied'");page.locator('#interpreter-left').click()
                    expect(page.locator('#interpreter-state')).to_have_text('Allow microphone access in your browser.')
                    assert len(wires)==before
                    page.evaluate("mockPermission='granted'");fail[0]=True
                    page.locator('#interpreter-left').click();page.wait_for_function("document.querySelector('#interpreter-state').dataset.state==='listening'")
                    page.locator('#interpreter-left').click()
                    expect(page.locator('#interpreter-state')).to_have_text('Gemini ended the session.')
                    fail[0]=False
                    page.locator('#interpreter-right').click();page.wait_for_function("document.querySelector('#interpreter-state').dataset.state==='listening'")
                    # Direction change closes old input before a new one; no stale translation.
                    page.locator('#interpreter-left').click();page.wait_for_function("document.querySelector('#interpreter-left').getAttribute('aria-pressed')==='true' && document.querySelector('#interpreter-state').dataset.state==='listening'")
                    page.locator('#interpreter-left').click();page.wait_for_function("document.querySelector('#interpreter-state').dataset.state==='ended'")
                    expect(page.locator('#interpreter-caption')).to_have_text('Good morning.')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                page.screenshot(path=str(output/f'translated-{width}.png'),full_page=True)
                page.locator('#interpreter-end').click()
                page.locator('#interpreter-language-a').select_option('ja');page.locator('#interpreter-language-b').select_option('fr')
                page.reload(wait_until='networkidle')
                assert page.locator('#interpreter-language-a').input_value()=='ja'
                assert page.locator('#interpreter-language-b').input_value()=='fr'
                assert not page.locator('#interpreter-consent').is_checked()
                assert not errors,errors
                evidence.append({'width':width,'result':'PASS','relay':'actual authenticated Flask and PCM queue','microphone':'synthetic oscillator','provider':'synthetic wire; no paid requests'})
                print(json.dumps(evidence[-1]),flush=True);context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps(evidence,indent=2))
    finally:
        for wire in wires:wire.shutdown()
        server.shutdown();case.doCleanups()


if __name__=='__main__':main()
