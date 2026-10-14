"""Synthetic media/suppliers; actual Chromium frontend -> Flask -> ledger/audio.

No API route fulfillment, paid IO, physical microphone, or acoustic quality claim.
Unlike offline unit tests this file needs loopback TCP; non-loopback Python and
page connections are blocked. Chromium background networking is disabled.
"""
import base64
import hashlib
import ipaddress
import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch


def loopback_only(event, args):
    if event not in ('socket.connect', 'socket.sendto'):
        return
    address = args[-1]
    if isinstance(address, str):
        return  # Local Unix sockets are allowed.
    try:
        allowed = ipaddress.ip_address(address[0]).is_loopback
    except (ValueError, TypeError, IndexError):
        allowed = False
    if not allowed:
        raise OSError('Synthetic browser QA blocks non-loopback connections')


import sys
sys.addaudithook(loopback_only)
os.environ.pop('DATABASE_URL', None)

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server
import test_kilas_live_translator_flow as flow
import test_kilas_audio as audio
from kilas_ai import live_translator_realtime as realtime, live_translator_segments as segments


MEDIA = """
window.qa={rms:0,mics:0,starts:0,stops:0,plays:0,worklets:[],audio:null,decoded:[]};
navigator.mediaDevices.getUserMedia=async()=>{
 qa.mics++;qa.starts++;let stopped=false;
 const track={addEventListener(){},stop(){if(!stopped){stopped=true;qa.mics--;qa.stops++;}}};
 return {getTracks:()=>[track]};
};
window.MediaRecorder=class{
 static isTypeSupported(){return true;}
 constructor(){this.state='inactive';this.mimeType='audio/wav';this.events={};}
 addEventListener(name,fn){this.events[name]=fn;}
 start(){this.state='recording';}
 stop(){if(this.state!=='recording')return;this.state='inactive';
  const bytes=Uint8Array.from(atob(window.qaWav),c=>c.charCodeAt(0));
  this.events.dataavailable({data:new Blob([bytes],{type:'audio/wav'})});this.events.stop();}
};
window.AudioContext=class{
 constructor(){this.state='suspended';this.currentTime=0;this.destination={};this.audioWorklet={addModule:async()=>{}};}
 async resume(){this.state='running';}
 async close(){this.state='closed';}
 createMediaStreamSource(){return {connect(){},disconnect(){}};}
 createAnalyser(){return {fftSize:2048,disconnect(){},getFloatTimeDomainData(array){array.fill(qa.rms);if(qa.rms>=.015)qa.lastVoice=performance.now();}};}
 async decodeAudioData(raw){qa.decoded.push(Array.from(new Uint8Array(raw)));
  const decoder=new OfflineAudioContext(1,44100,44100);return decoder.decodeAudioData(raw);}
 createBufferSource(){const ctx=this;return {connect(){},disconnect(){},stop(){qa.audio=null;},
  start(){if(qa.mics)throw Error('Playback captured by synthetic microphone');qa.plays++;this.began=ctx.currentTime;this.context=ctx;qa.audio=this;}};}
};
window.AudioWorkletNode=class{
 constructor(context){this.port={onmessage:null,postMessage:value=>{if(value.finish){clearInterval(this.timer);queueMicrotask(()=>this.port.onmessage?.({data:{finished:true}}));}}};
  this.timer=setInterval(()=>{if(!this.port.onmessage)return;const values=new Int16Array(800);values.fill(qa.rms>=.015?4000:0);
   if(qa.rms>=.015)qa.lastVoice=performance.now();this.port.onmessage({data:{bytes:values.buffer,rms:qa.rms}});},50);qa.worklets.push(this);}
 connect(){}disconnect(){clearInterval(this.timer);}
};
window.qaFinishAudio=()=>{const source=qa.audio;source.context.currentTime=source.began+source.buffer.duration;source.onended();};
"""


class AutomaticSocket(flow.SyntheticSocket):
    def send(self, message):
        super().send(message)
        if json.loads(message)['commit']:
            self.acknowledge()


class BrowserApplicationFlowTests(unittest.TestCase):
    setUp = flow.ApplicationFlowTests.setUp
    funded = flow.ApplicationFlowTests.funded
    on = flow.ApplicationFlowTests.on
    credit = flow.ApplicationFlowTests.credit
    signal = flow.ApplicationFlowTests.signal
    transcribe = flow.ApplicationFlowTests.transcribe
    context = flow.ApplicationFlowTests.context
    output_transport = flow.ApplicationFlowTests.output_transport
    wait = flow.ApplicationFlowTests.wait
    setUpClass = flow.ApplicationFlowTests.__dict__['setUpClass']

    def browser_flow(self, mode, cancel=False):
        received, release = Event(), Event()
        self.addCleanup(release.set)
        stable = 'Halo. Halo. Kalimat terakhir lengkap.'
        translated = 'Hello. Hello. Complete final sentence.'
        supplier_socket = AutomaticSocket(stable)
        self.credit(300)
        output = Path(os.environ.get('KILAS_LIVE_APP_SCREENSHOTS',
            str(Path(tempfile.gettempdir()) / 'kilas-live-translator-app-browser')))
        output.mkdir(parents=True, exist_ok=True)
        with self.context(translated, realtime_on=mode == 'realtime-v1'), \
                patch.object(realtime, 'connect', return_value=supplier_socket) as connect, \
                patch.object(segments.transport, 'request',
                    return_value=self.output_transport(release, received)) as speech, sync_playwright() as pw:
            app = audio.f.app.app
            server = make_server('127.0.0.1', 0, app, threaded=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            origin = f'http://127.0.0.1:{server.server_port}'
            browser = pw.chromium.launch(headless=True,
                executable_path=os.environ.get('KILAS_QA_CHROMIUM', '/usr/bin/chromium'),
                args=['--no-sandbox', '--disable-background-networking', '--disable-component-update',
                      '--disable-sync', '--no-first-run'])
            try:
                context = browser.new_context(viewport={'width': 390, 'height': 844})
                cookie = self.client.get_cookie('session')
                context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin}])
                context.add_init_script('window.qaWav=' + json.dumps(base64.b64encode(self.signal()).decode()) + ';' + MEDIA)
                page = context.new_page()
                errors, requests = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: requests.append((request.method, request.url.removeprefix(origin))))
                page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
                page.goto(origin + '/kilas-translator/live', wait_until='networkidle')
                expect(page.get_by_role('button', name='Start', exact=True)).to_be_enabled()
                self.assertEqual(page.evaluate('qa.starts'), 0)
                page.locator('[name=consent]').check()
                page.get_by_role('button', name='Start', exact=True).click()
                expect(page.locator('#live-state')).to_have_text('Mendengarkan')
                page.wait_for_function('qa.starts===1 && qa.mics===1')
                session_row = audio.f.db.query_one('SELECT id,status FROM kilas_live_translator_sessions WHERE user_id=?', (self.user,))
                ident = session_row['id']
                self.assertEqual(session_row['status'], 'ACTIVE')
                page.evaluate('qa.rms=.2')
                page.wait_for_function('!!qa.lastVoice')
                page.wait_for_timeout(150)
                page.evaluate('qa.rms=0')
                expect(page.locator('#live-state')).to_have_text('Memproses', timeout=4000)
                self.assertTrue(received.wait(3), 'Browser did not reach actual speech supplier boundary')
                self.assertEqual(page.evaluate('qa.mics'), 0)
                self.assertEqual(page.evaluate('qa.plays'), 0)
                turn = audio.f.db.query_one('SELECT operation_key,status FROM kilas_live_translator_turns WHERE session_id=?', (ident,))
                self.assertEqual(turn['status'], 'PROCESSING')
                path = '/kilas-translator/live/sessions/' + ident + '/turns/' + turn['operation_key']
                self.assertEqual(self.client.get(path + '/audio').status_code, 404)
                speech.assert_called_once()
                if cancel:
                    page.locator('#live-end').click()
                    expect(page.locator('#live-active')).to_be_hidden()
                    self.wait(lambda: audio.f.db.query_one('SELECT status FROM kilas_live_translator_sessions WHERE id=?',
                        (ident,))['status'] == 'ENDED', 'Browser End was not persisted')
                    release.set()
                    self.wait(lambda: audio.f.db.query_one('SELECT status FROM kilas_audio_jobs WHERE user_id=?',
                        (self.user,))['status'] == 'FAILED', 'End did not settle actual browser turn')
                    self.assertEqual(self.client.get(path + '/audio').status_code, 404)
                    page.wait_for_timeout(300)
                    self.assertEqual(page.evaluate('qa.plays'), 0)
                    self.assertEqual(page.evaluate('qa.decoded.length'), 0)
                    self.assertEqual(audio.f.db.query_one('SELECT status FROM kilas_live_translator_sessions WHERE id=?', (ident,))['status'], 'ENDED')
                else:
                    release.set()
                    page.wait_for_function('qa.plays===1', timeout=4000)
                    expect(page.locator('#live-state')).to_have_text('Hasil')
                    expect(page.locator('#live-translation')).to_have_text(translated)
                    self.assertEqual(page.evaluate('qa.mics'), 0)
                    self.assertEqual(bytes(page.evaluate('qa.decoded[0]')), self.raw)
                    self.assertEqual(page.evaluate('qa.decoded.length'), 1)
                    self.assertEqual(self.client.get(path + '/audio').data, self.raw)
                    page.screenshot(path=str(output / (mode + '-result.png')), full_page=True)
                    page.wait_for_timeout(300)
                    self.assertEqual(page.evaluate('qa.starts'), 1)
                    page.evaluate('qaFinishAudio()')
                    page.wait_for_function('qa.starts===2 && qa.mics===1')
                    expect(page.locator('#live-state')).to_have_text('Mendengarkan')
                    page.locator('#live-end').click()
                    expect(page.locator('#live-active')).to_be_hidden()
                    self.wait(lambda: audio.f.db.query_one('SELECT status FROM kilas_live_translator_sessions WHERE id=?',
                        (ident,))['status'] == 'ENDED', 'Browser End was not persisted')
                    self.assertEqual(page.evaluate('qa.mics'), 0)
                    job = audio.f.db.query_one('SELECT status,actual_ms,seconds_charged FROM kilas_audio_jobs WHERE user_id=?', (self.user,))
                    self.assertEqual(job['status'], 'COMPLETED')
                    self.assertGreater(job['seconds_charged'], 0)
                    self.assertEqual(audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs WHERE user_id=?', (self.user,))['n'], 1)
                speech.assert_called_once()
                self.translation_mock.assert_called_once()
                if mode == 'realtime-v1':
                    self.batch_mock.assert_not_called()
                    connect.assert_called_once()
                    self.assertEqual(self.translation_mock.call_args.args[2][0]['content'], stable)
                    self.assertEqual(sum(method == 'POST' and url == path for method, url in requests), 0)
                    self.assertEqual(sum(method == 'POST' and url == path + '/input/start' for method, url in requests), 1)
                    self.assertEqual(sum(method == 'POST' and url == path + '/input/commit' for method, url in requests), 1)
                else:
                    self.batch_mock.assert_called_once()
                    connect.assert_not_called()
                    self.assertEqual(sum(method == 'POST' and url == path for method, url in requests), 1)
                self.assertFalse(errors, errors)
                (output / (mode + ('-cancel' if cancel else '-complete') + '.json')).write_text(json.dumps({
                    'kind': 'real browser modules and Flask routes; synthetic media and suppliers',
                    'physical_microphone': False, 'paid_network_calls': 0,
                    'input_mode': mode, 'cancelled_during_output': cancel,
                    'whole_mp3_sha256': hashlib.sha256(self.raw).hexdigest(),
                    'single_translation_and_tts': True, 'page_errors': errors,
                }, indent=2))
                context.close()
            finally:
                release.set()
                realtime.cancel(self.user, ident) if 'ident' in locals() else None
                browser.close()
                server.shutdown()
                thread.join(3)

    def test_batch_frontend_actual_flask_pipeline_complete_audio_and_end(self):
        self.browser_flow('batch')

    def test_realtime_frontend_actual_flask_pipeline_complete_audio_and_end(self):
        self.browser_flow('realtime-v1')

    def test_browser_end_during_actual_output_never_plays_or_replays(self):
        self.browser_flow('batch', cancel=True)


if __name__ == '__main__':
    unittest.main()
