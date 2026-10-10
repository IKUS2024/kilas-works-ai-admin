"""Selected-tab provider pipeline, offline fixtures only; no capture/provider calls."""
import io
import json
import os
import wave
from pathlib import Path
import pytest
from werkzeug.datastructures import FileStorage
from test_content_projects_prototype import environment,post
from kilas_ai import live_assist as live,live_assist_routes
from test_chat_transcription import wav


def fixture_audio():
    out=io.BytesIO()
    with wave.open(out,'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(b'\x00\x10'*160000)
    return out.getvalue()


@pytest.fixture
def active(environment,monkeypatch):
    monkeypatch.setenv('KILAS_LIVE_ASSIST_ENABLED','true')
    calls=[]
    monkeypatch.setattr(live.stt,'budget_ready',lambda:True)
    monkeypatch.setattr(live.stt,'configured',lambda:True)
    monkeypatch.setattr(live.stt,'transcribe',lambda audio:(calls.append('stt') or 'Tell me about your experience.',{}))
    def text(instruction,content):
        calls.append((instruction,content));return 'Apa pengalamanmu?' if instruction.startswith('Translate') else 'Boleh saya menjelaskan pengalaman nyata saya di bidang [isi pengalamanmu]?'
    monkeypatch.setattr(live,'text_request',text)
    try:yield *environment,calls
    finally:
        with live._lock:
            for value in live._sessions.values():value['timer'].cancel()
            live._sessions.clear()


def start(client,mode='video',target='id',consent='yes'):
    return post(client,'/kilas-ai/live-assist/start',mode=mode,target=target,consent=consent)


def chunk(client,token,sequence=1,raw=None):
    return post(client,'/kilas-ai/live-assist/chunk',session_id=token,sequence=sequence,audio=(io.BytesIO(fixture_audio() if raw is None else raw),'tab.wav','audio/wav'))


def test_flag_capture_local_only_and_existing_role_gate(environment,monkeypatch):
    _,client=environment
    monkeypatch.delenv('KILAS_LIVE_ASSIST_ENABLED',raising=False)
    assert client.get('/kilas-ai/live-assist').status_code==404
    monkeypatch.setenv('KILAS_LIVE_ASSIST_ENABLED','true')
    monkeypatch.setattr(live.stt,'budget_ready',lambda:False)
    body=client.get('/kilas-ai/live-assist').data
    assert b'data-provider-ready="false"' in body and b'Pemrosesan provider belum aktif' in body
    assert b'Belum ada caption.' in body and b'Demo sintetis' not in body
    assert start(client).status_code==503
    assert not live._sessions
    with client.session_transaction() as s:s.update(user_id=3,role='KILAS_ADMIN')
    assert client.get('/kilas-ai/live-assist').status_code==404


def test_consent_csrf_and_options(active):
    _,client,calls=active
    assert client.post('/kilas-ai/live-assist/start',data={}).status_code==400
    assert start(client,consent='').status_code==409
    assert start(client,mode='phone-system-audio').status_code==409
    assert start(client,target='not-a-language').status_code==409
    assert not calls and not live._sessions


def test_near_live_source_translation_retry_and_order(active):
    _,client,calls=active
    token=start(client).json['session_id']
    response=chunk(client,token)
    assert response.status_code==200 and response.json=={'sequence':1,'original':'Tell me about your experience.','translated':'Apa pengalamanmu?'}
    assert response.headers['Cache-Control']=='private, no-store'
    assert chunk(client,token).json==response.json and len(calls)==2
    assert chunk(client,token,raw=wav(9)).status_code==409
    assert chunk(client,token,sequence=3).status_code==409
    assert chunk(client,token,sequence=2).status_code==200
    assert chunk(client,token,sequence=13).status_code==409


@pytest.mark.parametrize('raw',[b'bad',wav(12),wav(0),b'x'*(live.MAX_BYTES+1)],ids=['magic','duration','empty','size'])
def test_chunk_validation_never_reaches_provider(active,raw):
    _,client,calls=active;token=start(client).json['session_id']
    assert chunk(client,token,raw=raw).status_code==409 and not calls


def test_cross_owner_stop_and_chunks_deny_access(active):
    _,client,calls=active;token=start(client).json['session_id']
    with client.session_transaction() as s:s.update(user_id=2,role='CLIENT_OWNER')
    assert chunk(client,token).status_code==404
    assert post(client,'/kilas-ai/live-assist/stop',session_id=token).status_code==404
    assert not calls


def test_call_reply_explicit_editable_context_no_fabricated_experience(active):
    _,client,calls=active;token=start(client,mode='call').json['session_id']
    assert post(client,'/kilas-ai/live-assist/reply',session_id=token,operation_key='reply-operation-001').status_code==409
    chunk(client,token)
    response=post(client,'/kilas-ai/live-assist/reply',session_id=token,operation_key='reply-operation-001',facts='Saya belajar desain selama 6 bulan.')
    assert response.status_code==200
    instruction,content=calls[-1]
    assert 'Never invent interview experience' in instruction
    assert json.loads(content)['user_facts']=='Saya belajar desain selama 6 bulan.'
    assert post(client,'/kilas-ai/live-assist/reply',session_id=token,operation_key='reply-operation-001').status_code==409
    for i in (2,3):assert post(client,'/kilas-ai/live-assist/reply',session_id=token,operation_key=f'reply-operation-00{i}').status_code==200
    assert post(client,'/kilas-ai/live-assist/reply',session_id=token,operation_key='reply-operation-004').status_code==409


def test_failed_chunk_never_resubmits_and_stop_erases_session(active,monkeypatch):
    _,client,calls=active;token=start(client).json['session_id']
    def failed(audio):calls.append('failure');raise live.stt.TranscriptionError('failed')
    monkeypatch.setattr(live.stt,'transcribe',failed)
    assert chunk(client,token).status_code==503
    assert chunk(client,token).status_code==409 and calls==['failure']
    assert post(client,'/kilas-ai/live-assist/stop',session_id=token).json=={'stopped':True}
    assert token not in live._sessions and chunk(client,token).status_code==404


def test_stop_during_provider_call_discards_late_text(active,monkeypatch):
    _,client,calls=active;token=start(client).json['session_id']
    def late(audio):live.stop(1,token);return 'Late transcript',{}
    monkeypatch.setattr(live.stt,'transcribe',late)
    assert chunk(client,token).status_code==503 and token not in live._sessions
    assert calls==[] # Stop fences translation too, not just rendering.


def test_expiration_clears_content_and_restart_does_not_replay(active):
    _,client,calls=active;token=start(client).json['session_id'];chunk(client,token)
    value=live._sessions[token]
    live.expire(token)
    assert value['captions']==[] and value['results']=={}
    assert chunk(client,token).status_code==404


def test_one_active_session_per_owner_and_text_guard(active):
    _,client,calls=active
    assert start(client).status_code==200
    assert start(client).status_code==409


def test_digital_silence_is_not_sent_or_fabricated_as_caption(active):
    _,client,calls=active;token=start(client).json['session_id']
    response=chunk(client,token,raw=wav(10))
    assert response.json=={'sequence':1,'original':'','translated':'','silence':True} and not calls


def test_parallel_chunk_requests_cannot_start_more_than_one_provider_call(active,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    _,client,calls=active;token=start(client).json['session_id'];entered=Event();release=Event()
    def held(audio):
        calls.append('stt');entered.set();assert release.wait(2);return 'Synthetic source',{}
    monkeypatch.setattr(live.stt,'transcribe',held)
    item=lambda:FileStorage(stream=io.BytesIO(fixture_audio()),filename='tab.wav',content_type='audio/wav')
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(live.chunk,1,token,1,item());assert entered.wait(2)
        with pytest.raises(live.LiveError,match='chunk_busy'):live.chunk(1,token,2,item())
        with pytest.raises(live.LiveError,match='chunk_not_replayed'):live.chunk(1,token,1,item())
        release.set();assert pending.result()['original']=='Synthetic source'
    assert calls.count('stt')==1


def test_text_adapter_fixed_existing_model_response_bounds_and_no_send(monkeypatch):
    monkeypatch.setenv('KILAS_LIVE_ASSIST_ENABLED','true');monkeypatch.setenv('OPENAI_API_KEY','synthetic-only')
    monkeypatch.setattr(live.stt,'budget_ready',lambda:True)
    calls=[]
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,size):yield json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{"text":"Synthetic translation"}'}}]}).encode()
    monkeypatch.setattr(live.requests,'post',lambda url,**kwargs:(calls.append((url,kwargs)) or Response()))
    assert live.text_request('Translate faithfully','Synthetic')=='Synthetic translation'
    payload=calls[0][1]['json']
    assert payload['model']==live.model_policy.luna_model() and payload['max_completion_tokens']==512 and payload['store'] is False
    monkeypatch.setattr(live.stt,'budget_ready',lambda:False)
    with pytest.raises(live.LiveError,match='budget_unavailable'):live.text_request('Translate','Synthetic')
    assert len(calls)==1


@pytest.mark.skipif(not os.environ.get('KILAS_LIVE_BROWSER_QA_DIR'),reason='Optional browser QA with completely injected capture')
def test_browser_selected_tab_indicator_captions_translation_editable_reply_and_cleanup(active,monkeypatch):
    import base64
    from threading import Thread
    from werkzeug.serving import make_server
    from playwright.sync_api import sync_playwright,expect
    app,client,calls=active
    output=Path(os.environ['KILAS_LIVE_BROWSER_QA_DIR']);output.mkdir(parents=True,exist_ok=True)
    server=make_server('127.0.0.1',0,app,threaded=True);worker=Thread(target=server.serve_forever,daemon=True);worker.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    script='''
    window.liveQA={picker:0,microphone:0,speech:0,closed:0,stopped:0,surface:'browser'};
    const stats=window.liveQA;
    Object.defineProperty(navigator,'mediaDevices',{value:{getUserMedia(){stats.microphone++;throw Error('Real microphone forbidden');},getDisplayMedia(options){stats.picker++;stats.options=options;const tracks=['audio','video'].map(kind=>Object.assign(new EventTarget(),{kind,readyState:'live',stop(){this.readyState='ended';stats.stopped++;},getSettings(){return {displaySurface:stats.surface};}}));return Promise.resolve({getTracks:()=>tracks,getAudioTracks:()=>tracks.filter(t=>t.kind==='audio'),getVideoTracks:()=>tracks.filter(t=>t.kind==='video')});}}});
    if(window.speechSynthesis)window.speechSynthesis.speak=()=>{stats.speech++;throw Error('Auto speech forbidden');};
    window.AudioContext=class {constructor(){this.audioWorklet={addModule:async()=>{}};this.destination={};}createMediaStreamSource(){return {connect(){},disconnect(){}};}createGain(){return {gain:{value:1},connect(){},disconnect(){}};}async resume(){}async close(){stats.closed++;}};
    window.MediaStream=class {constructor(tracks){this.tracks=tracks;}};
    window.AudioWorkletNode=class {constructor(){this.port={postMessage(){}};window.liveNode=this;}connect(){}disconnect(){}};
    '''
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM') or None,headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000});context.add_init_script(script)
            context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
            context.add_cookies([{'name':'session','value':client.get_cookie('session').value,'url':origin}])
            monkeypatch.setattr(live.stt,'budget_ready',lambda:False)
            page=context.new_page();page.goto(origin+'/kilas-ai/live-assist')
            expect(page.locator('#live-provider')).to_be_disabled()
            page.locator('#live-start').click();assert page.evaluate('window.liveQA.picker')==0
            page.locator('#live-consent').check();page.locator('#live-start').click()
            expect(page.locator('#live-assist')).to_have_attribute('data-state','active')
            expect(page.locator('#live-status')).to_contain_text('pemrosesan provider tidak aktif')
            page.evaluate("window.liveNode.port.onmessage({data:{kind:'level',level:0.6}})")
            assert page.locator('#live-meter').evaluate('node=>node.value')==.6
            assert page.locator('#live-original').inner_text()=='' and not calls
            page.locator('#live-stop').click();assert page.evaluate('window.liveQA.stopped')==2
            monkeypatch.setattr(live.stt,'budget_ready',lambda:True)
            page.reload();page.locator('#live-mode').select_option('call');page.locator('#live-consent').check();page.locator('#live-provider').check()
            page.locator('#live-facts').fill('Saya belajar desain selama enam bulan.')
            page.locator('#live-start').click()
            expect(page.locator('#live-status')).to_contain_text('menunggu potongan pertama')
            page.evaluate("payload=>window.liveNode.port.onmessage({data:{kind:'chunk',buffer:Uint8Array.from(atob(payload),c=>c.charCodeAt(0)).buffer}})",base64.b64encode(fixture_audio()).decode())
            expect(page.locator('#live-original')).to_contain_text('Tell me about your experience.')
            expect(page.locator('#live-translated')).to_contain_text('Apa pengalamanmu?')
            page.locator('#live-suggest').click();expect(page.locator('#live-reply')).to_have_value('Boleh saya menjelaskan pengalaman nyata saya di bidang [isi pengalamanmu]?')
            assert json.loads(calls[-1][1])['user_facts']=='Saya belajar desain selama enam bulan.'
            page.locator('#live-reply').fill('Jawaban saya yang benar-benar sudah diperiksa.')
            for label,width in [('desktop',1440),('mobile',390)]:
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(output/(label+'.png')),full_page=True)
            assert page.evaluate('window.liveQA.microphone+window.liveQA.speech')==0
            assert page.evaluate('Object.keys(localStorage).length+Object.keys(sessionStorage).length')==0
            page.evaluate('window.dispatchEvent(new Event("pagehide"))')
            expect(page.locator('#live-original')).to_be_empty();expect(page.locator('#live-translated')).to_be_empty();expect(page.locator('#live-reply')).to_have_value('')
            assert page.evaluate('window.liveQA.stopped')==2 and page.evaluate('window.liveQA.closed')==1
            # Verify the shipped worklet in Chromium against generated non-sensitive PCM.
            # No real display/microphone source, no audible output and no provider transport.
            fixture_context=browser.new_context()
            fixture_context.add_init_script("window.captureCalls=0;const deny=()=>{window.captureCalls++;throw Error('Real capture forbidden');};Object.defineProperty(navigator,'mediaDevices',{value:{getDisplayMedia:deny,getUserMedia:deny}});")
            fixture_context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
            fixture_context.add_cookies([{'name':'session','value':client.get_cookie('session').value,'url':origin}])
            fixture_page=fixture_context.new_page();fixture_page.goto(origin+'/kilas-ai/live-assist')
            result=fixture_page.evaluate('''async()=>{
                const ctx=new OfflineAudioContext(1,480000,48000);await ctx.audioWorklet.addModule('/static/kilas_live_worklet.mjs');
                const node=new AudioWorkletNode(ctx,'kilas-tab-pcm'),source=ctx.createBufferSource(),buffer=ctx.createBuffer(1,480000,48000);
                buffer.getChannelData(0).fill(0.2);source.buffer=buffer;
                const chunks=[];node.port.onmessage=event=>{if(event.data.kind==='chunk')chunks.push(event.data.buffer.byteLength);};
                source.connect(node);node.connect(ctx.destination);source.start();const rendered=await ctx.startRendering();await new Promise(r=>setTimeout(r,50));
                node.port.postMessage('stop');node.disconnect();source.disconnect();
                return {chunks,silentOutput:rendered.getChannelData(0).every(sample=>sample===0),captureCalls:window.captureCalls};
            }''')
            assert result=={'chunks':[320044],'silentOutput':True,'captureCalls':0}
            fixture_context.close()
            browser.close()
    finally:server.shutdown();worker.join(timeout=2)
