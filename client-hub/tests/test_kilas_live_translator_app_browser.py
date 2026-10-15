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
import time
import unittest
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock, patch


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
from kilas_ai import providers, usage


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

    @contextmanager
    def actual_browser(self):
        """Actual app endpoints, with only media devices and suppliers injected."""
        server = make_server('127.0.0.1', 0, audio.f.app.app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
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
                    yield page, requests, errors
                finally:
                    row = audio.f.db.query_one("SELECT id FROM kilas_live_translator_sessions WHERE user_id=? AND status='ACTIVE'", (self.user,))
                    if row:
                        realtime.cancel(self.user, row['id'])
                        flow.sessions.end(self.user, row['id'])
                    browser.close()
        finally:
            server.shutdown()
            thread.join(3)

    def speak(self, page):
        page.evaluate('qa.lastVoice=0;qa.rms=.2')
        page.wait_for_function('!!qa.lastVoice')
        page.wait_for_timeout(150)
        page.evaluate('qa.rms=0')

    def browser_flow(self, mode, cancel=False, provider_languages=('id', 'en')):
        received, release = Event(), Event()
        self.addCleanup(release.set)
        stable = 'Halo. Halo. Kalimat terakhir lengkap.'
        translated = 'Hello. Hello. Complete final sentence.'
        supplier_socket = AutomaticSocket(stable)
        self.credit(300)
        output = Path(os.environ.get('KILAS_LIVE_APP_SCREENSHOTS',
            str(Path(tempfile.gettempdir()) / 'kilas-live-translator-app-browser')))
        output.mkdir(parents=True, exist_ok=True)
        with self.context(translated, realtime_on=mode == 'realtime-v1', provider_languages=provider_languages), \
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
                # Keep dispatching Playwright routes while the realtime input's
                # last chunk and commit complete; Event.wait can block those callbacks.
                deadline=time.monotonic()+3
                while not received.is_set() and time.monotonic()<deadline:
                    page.wait_for_timeout(10)
                self.assertTrue(received.is_set(), 'Browser did not reach actual speech supplier boundary')
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
                    metadata = self.client.get(path).json
                    self.assertEqual((metadata['source_language'], metadata['target_language']), ('id', 'en'))
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

    def test_out_of_pair_response_recovers_for_new_speech_without_paid_replay_or_stale_error(self):
        """Observed invalid_language_pair: reject it before any speech request."""
        self.credit(300)
        translated = 'A new complete translation. Every word remains present.'
        calls = []

        def translate(*args, **kwargs):
            calls.append(args[2][0]['content'])
            result = ({'text': 'This out-of-pair result must never play.',
                       'source_language': 'zh', 'target_language': 'en'} if len(calls) == 1 else
                      {'text': translated, 'source_language': 'id', 'target_language': 'en'})
            yield {'type': 'delta', 'text': json.dumps(result)}
            yield {'type': 'usage', 'input_tokens': 21, 'output_tokens': 19}
            yield {'type': 'finish', 'reason': 'stop'}

        def connect():
            return AutomaticSocket('Complete stable source utterance.')

        with self.context(realtime_on=True), patch.object(realtime, 'connect', side_effect=connect) as socket, \
                patch.object(providers, '_openai', side_effect=translate) as translation, \
                patch.object(segments.transport, 'request', return_value=self.output_transport()) as speech, \
                patch.object(usage, 'finish', wraps=usage.finish) as settle, self.actual_browser() as (page, requests, errors):
            page.locator('[name=consent]').check()
            page.get_by_role('button', name='Start', exact=True).click()
            expect(page.locator('#live-state')).to_have_text('Mendengarkan')
            self.speak(page)
            expect(page.locator('#live-error')).to_be_visible(timeout=5000)
            page.wait_for_function('qa.starts===2 && qa.mics===1', timeout=5000)
            expect(page.locator('#live-state')).to_have_text('Mendengarkan')
            row = audio.f.db.query_one('SELECT operation_key,session_id,status,error_code FROM kilas_live_translator_turns WHERE session_id IN (SELECT id FROM kilas_live_translator_sessions WHERE user_id=?)', (self.user,))
            self.assertEqual((row['status'], row['error_code']), ('FAILED', 'translation_language_mismatch'))
            ident, failed_key = row['session_id'], row['operation_key']
            failed_path = '/kilas-translator/live/sessions/' + ident + '/turns/' + failed_key
            failed = self.client.get(failed_path).json
            self.assertEqual(failed['status'], 'FAILED')
            self.assertEqual(failed['code'], 'translation_language_mismatch')
            self.assertTrue(failed['recoverable'])
            self.assertEqual(self.client.get(failed_path + '/audio').status_code, 404)
            self.assertEqual(page.evaluate('qa.plays'), 0)
            self.assertEqual(page.evaluate('qa.decoded.length'), 0)
            expect(page.locator('#live-translation')).to_be_hidden()
            speech.assert_not_called()
            translation.assert_called_once()
            socket.assert_called_once()
            self.batch_mock.assert_not_called()
            ledger = audio.f.db.query_one('SELECT status,input_tokens,output_tokens,estimated_cost_usd FROM kilas_ai_usage WHERE user_id=? AND operation_key=?', (self.user, failed_key + '-text'))
            self.assertEqual((ledger['status'], ledger['input_tokens'], ledger['output_tokens']), ('FAILED', 21, 19))
            self.assertGreater(float(ledger['estimated_cost_usd']), 0)
            self.assertEqual(audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs WHERE user_id=?', (self.user,))['n'], 0)
            self.assertEqual(audio.f.db.query_one('SELECT seconds FROM kilas_audio_balances WHERE user_id=?', (self.user,))['seconds'], 300)
            self.assertEqual(sum(call.args[1] == failed_key + '-text' for call in settle.call_args_list), 1)
            page.wait_for_timeout(350)
            translation.assert_called_once()
            socket.assert_called_once()
            duplicate = self.client.post(failed_path, data={'csrf_token': 'audio-csrf',
                'recording': (BytesIO(self.signal()), 'synthetic.wav', 'audio/wav')})
            self.assertEqual(duplicate.status_code, 409)
            translation.assert_called_once()
            self.batch_mock.assert_not_called()
            self.speak(page)
            page.wait_for_function('qa.plays===1', timeout=5000)
            expect(page.locator('#live-state')).to_have_text('Hasil')
            expect(page.locator('#live-translation')).to_have_text(translated)
            expect(page.locator('#live-error')).to_be_hidden()
            self.assertEqual(bytes(page.evaluate('qa.decoded[0]')), self.raw)
            self.assertEqual(page.evaluate('qa.mics'), 0)
            speech.assert_called_once()
            self.assertEqual(translation.call_count, 2)
            self.assertEqual(socket.call_count, 2)
            self.assertEqual(settle.call_count, 2)
            turns = audio.f.db.query_all('SELECT operation_key,status FROM kilas_live_translator_turns WHERE session_id=? ORDER BY created_at', (ident,))
            self.assertEqual([turn['status'] for turn in turns], ['FAILED', 'COMPLETED'])
            self.assertNotEqual(turns[0]['operation_key'], turns[1]['operation_key'])
            self.assertEqual(audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs WHERE user_id=?', (self.user,))['n'], 1)
            self.assertEqual(sum(method == 'POST' and url.endswith('/input/start') for method, url in requests), 2)
            self.assertEqual(sum(method == 'POST' and url.endswith('/input/commit') for method, url in requests), 2)
            self.assertEqual(sum(method == 'POST' and url == failed_path for method, url in requests), 0)
            page.evaluate('qaFinishAudio()')
            page.wait_for_function('qa.starts===3 && qa.mics===1')
            page.locator('#live-end').click()
            expect(page.locator('#live-active')).to_be_hidden()
            self.wait(lambda: audio.f.db.query_one('SELECT status FROM kilas_live_translator_sessions WHERE id=?', (ident,))['status'] == 'ENDED', 'End was not persisted')
            self.assertFalse(errors, errors)

    def test_bounded_known_regions_are_canonicalized_in_actual_realtime_app_flow(self):
        self.browser_flow('realtime-v1', provider_languages=('ID-id', 'EN-us'))

    def test_two_successive_valid_realtime_utterances_complete_once_then_end_blocks_late_work(self):
        self.credit(300)
        sources = ['Ucapan pertama lengkap. Pertama, pertama.',
                   'Ucapan kedua lengkap. Kedua, kedua.']
        translations = ['First complete utterance. First, first.',
                        'Second complete utterance. Second, second.']
        raws = [self.raw, audio.mp3(2.1)]
        self.assertNotEqual(raws[0], raws[1])
        seen, sockets, responses = [], [], []

        def connect():
            socket = AutomaticSocket(sources[len(sockets)])
            sockets.append(socket)
            return socket

        def translate(*args, **kwargs):
            seen.append(args[2][0]['content'])
            index = len(seen) - 1
            yield {'type': 'delta', 'text': json.dumps({
                'text': translations[index], 'source_language': 'id', 'target_language': 'en',
            })}
            yield {'type': 'usage', 'input_tokens': 20 + index, 'output_tokens': 18 + index}
            yield {'type': 'finish', 'reason': 'stop'}

        def speech_response(*args, **kwargs):
            raw = raws[len(responses)]
            response = MagicMock(status_code=200)
            response.__enter__.return_value = response
            response.iter_content.side_effect = lambda size: iter([raw[:80], raw[80:]])
            responses.append(response)
            return response

        with self.context(realtime_on=True), patch.object(realtime, 'connect', side_effect=connect) as connection, \
                patch.object(providers, '_openai', side_effect=translate) as translation, \
                patch.object(segments.transport, 'request', side_effect=speech_response) as speech, \
                patch.object(usage, 'finish', wraps=usage.finish) as settle, self.actual_browser() as (page, requests, errors):
            page.evaluate("""()=>{qa.overlaps=0;
                const create=AudioContext.prototype.createBufferSource;
                AudioContext.prototype.createBufferSource=function(){const node=create.call(this),start=node.start;
                  node.start=function(){if(qa.audio){qa.overlaps++;throw Error('Overlapping translated audio');}return start.call(this);};return node;};}""")
            page.locator('[name=consent]').check()
            page.get_by_role('button', name='Start', exact=True).click()
            expect(page.locator('#live-state')).to_have_text('Mendengarkan')
            ident = audio.f.db.query_one('SELECT id FROM kilas_live_translator_sessions WHERE user_id=?', (self.user,))['id']
            keys = []
            for index in range(2):
                self.speak(page)
                page.wait_for_function('qa.plays===' + str(index + 1), timeout=5000)
                expect(page.locator('#live-state')).to_have_text('Hasil')
                expect(page.locator('#live-translation')).to_have_text(translations[index])
                expect(page.locator('#live-error')).to_be_hidden()
                self.assertEqual(page.evaluate('qa.mics'), 0)
                self.assertEqual(page.evaluate('qa.starts'), index + 1)
                self.assertEqual(page.evaluate('qa.decoded.length'), index + 1)
                self.assertEqual(bytes(page.evaluate('qa.decoded[' + str(index) + ']')), raws[index])
                turns = audio.f.db.query_all('SELECT operation_key,status FROM kilas_live_translator_turns WHERE session_id=? ORDER BY created_at', (ident,))
                self.assertEqual(len(turns), index + 1)
                self.assertEqual([turn['status'] for turn in turns], ['COMPLETED'] * (index + 1))
                key = turns[index]['operation_key']
                keys.append(key)
                path = '/kilas-translator/live/sessions/' + ident + '/turns/' + key
                metadata = self.client.get(path).json
                self.assertEqual((metadata['source_language'], metadata['target_language']), ('id', 'en'))
                self.assertEqual(metadata['translated_text'], translations[index])
                self.assertNotIn('segments', metadata)
                self.assertEqual(sum(method == 'GET' and url == path + '/audio' for method, url in requests), 1)
                self.assertEqual(sum(method == 'POST' and url == path for method, url in requests), 0)
                self.assertEqual(sum(method == 'POST' and url == path + '/input/start' for method, url in requests), 1)
                self.assertEqual(sum(method == 'POST' and url == path + '/input/commit' for method, url in requests), 1)
                self.assertEqual(speech.call_args.kwargs['json']['text'], translations[index])
                self.assertEqual(translation.call_count, index + 1)
                self.assertEqual(speech.call_count, index + 1)
                self.assertEqual(settle.call_count, index + 1)
                # Voice-like input while output plays cannot start another turn.
                page.evaluate('()=>{qa.rms=.4;qa.lateEnded=qa.audio.onended;}')
                page.wait_for_timeout(300)
                self.assertEqual(page.evaluate('qa.mics'), 0)
                self.assertEqual(page.evaluate('qa.plays'), index + 1)
                self.assertEqual(connection.call_count, index + 1)
                page.evaluate('qa.rms=0;qaFinishAudio()')
                page.wait_for_function('qa.starts===' + str(index + 2) + ' && qa.mics===1')
                expect(page.locator('#live-state')).to_have_text('Mendengarkan')
            self.assertNotEqual(keys[0], keys[1])
            self.assertEqual(seen, sources)
            self.assertEqual(page.evaluate('qa.overlaps'), 0)
            self.batch_mock.assert_not_called()
            for key in keys:
                self.assertEqual(sum(call.args[1] == key + '-text' for call in settle.call_args_list), 1)
            jobs = audio.f.db.query_all('SELECT operation_key,status,original_script,result_content,actual_ms,seconds_charged FROM kilas_audio_jobs WHERE user_id=? ORDER BY created_at', (self.user,))
            self.assertEqual(len(jobs), 2)
            for index, job in enumerate(jobs):
                self.assertEqual(job['operation_key'], keys[index] + '-audio')
                self.assertEqual(job['status'], 'COMPLETED')
                self.assertIsNone(job['original_script'])
                self.assertIsNone(job['result_content'])
                self.assertGreater(job['seconds_charged'], 0)
                self.assertEqual(job['seconds_charged'], (job['actual_ms'] + 999) // 1000)
            self.assertEqual(audio.f.db.query_one('SELECT seconds FROM kilas_audio_balances WHERE user_id=?', (self.user,))['seconds'], 300 - sum(job['seconds_charged'] for job in jobs))
            usage_rows = audio.f.db.query_all('SELECT operation_key,status FROM kilas_ai_usage WHERE user_id=?', (self.user,))
            self.assertEqual({row['operation_key'] for row in usage_rows}, {key + '-text' for key in keys})
            self.assertEqual([row['status'] for row in usage_rows], ['COMPLETE', 'COMPLETE'])
            stt_rows = audio.f.db.query_all('SELECT operation_key,status,charge_micro FROM kilas_vo_stt_operations WHERE user_id=?', (self.user,))
            self.assertEqual({row['operation_key'] for row in stt_rows}, {flow.realtime_budget.ledger_key(key) for key in keys})
            self.assertEqual([row['status'] for row in stt_rows], ['COMPLETED', 'COMPLETED'])
            self.assertEqual([row['charge_micro'] for row in stt_rows], [flow.realtime_budget.RESERVE_MICRO] * 2)
            # Capture a stale callback, then End both locally and in the real app.
            page.evaluate('()=>{qa.latePCM=qa.worklets.at(-1).port.onmessage;}')
            page.locator('#live-end').click()
            expect(page.locator('#live-active')).to_be_hidden()
            self.wait(lambda: audio.f.db.query_one('SELECT status FROM kilas_live_translator_sessions WHERE id=?', (ident,))['status'] == 'ENDED', 'End was not persisted')
            page.evaluate('qa.latePCM({data:{bytes:new Int16Array(800).buffer,rms:.5}});qa.lateEnded();qa.rms=.5')
            page.wait_for_timeout(300)
            self.assertEqual(page.evaluate('qa.mics'), 0)
            self.assertEqual(page.evaluate('qa.starts'), 3)
            self.assertEqual(page.evaluate('qa.plays'), 2)
            self.assertEqual(page.evaluate('qa.decoded.length'), 2)
            late = self.client.post('/kilas-translator/live/sessions/' + ident + '/turns/live-' + 'c' * 32 + '/input/start', data={'csrf_token': 'audio-csrf'})
            self.assertEqual(late.status_code, 409)
            self.assertEqual(connection.call_count, 2)
            self.assertEqual(translation.call_count, 2)
            self.assertEqual(speech.call_count, 2)
            self.assertEqual(settle.call_count, 2)
            self.assertFalse(errors, errors)


if __name__ == '__main__':
    unittest.main()
