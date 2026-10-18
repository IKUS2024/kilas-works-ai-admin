"""Android-like Chromium, real cached-v4 MP3 fetch/decode/playback; no provider IO."""
import hashlib
import json
import os
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
import test_kilas_live_translator as f
from kilas_ai import live_translator as live,live_translator_store as sessions,live_translator_segments as segments
from kilas_ai import audio_branded_voices as voices,audio_provider as provider


def main():
    case=f.LiveTranslatorTests('test_pair_consent_voice_owner_and_concurrent_session_checks')
    case.id=lambda:'translator-auto-audio-browser';case.setUp();case.credit(300)
    app=f.audio.f.app.app
    # Previously published English demo, not a private original/user turn.
    raw=(voices.SAMPLE_ROOT/'kilas-male.mp3').read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    ident=None;report={'real_provider_calls':0,'physical_android_tested':False}
    try:
        def transcript(pcm,capability,**kwargs):
            assert kwargs['detect_language'];case.transcribe(pcm,capability)
            return {'text':'Synthetic source.','language_code':'ind','language_probability':.98}
        with case.funded(),case.on(),patch.object(voices,'resolve',return_value=f.VOICE),patch.object(live.stt,'transcribe',side_effect=transcript),patch.object(live,'translation',return_value={'text':voices.SAMPLE_TEXT,'source_language':'id','target_language':'en'}) as translation,patch.object(segments,'speech',return_value=raw) as synthesis,patch.object(provider,'request',side_effect=AssertionError('Provider IO forbidden')),sync_playwright() as pw:
            ident=sessions.create(case.user,'auto','en','kilas-male')
            def turn(number):
                key=case.key(number);info=sessions.claim(case.user,ident,key)
                live.process(case.user,ident,key,case.signal(),info,whole_output=True)
                ready=case.client.get('/kilas-translator/live/sessions/'+ident+'/turns/'+key)
                assert ready.status_code==200;return ready.json['audio_url']
            url=turn(1)
            browser=pw.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM','/usr/bin/chromium'),args=['--no-sandbox','--autoplay-policy=user-gesture-required'])
            context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,user_agent='Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36')
            cookie=case.client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
            page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            def route(request):
                if not request.request.url.startswith(origin):request.abort()
                elif request.request.method!='GET':raise AssertionError('Unexpected mutation')
                else:request.continue_()
            page.route('**/*',route);page.goto(origin+'/kilas-translator/live?classic=1',wait_until='networkidle')
            page.evaluate('''async url=>{
              const {TranslatorPlayback}=await import('/static/kilas_live_translator_playback.mjs?auto-audio-context-20261018');
              window.qa={url,started:0,completed:0,requests:0,microphones:0};
              navigator.mediaDevices.getUserMedia=()=>{qa.microphones++;throw Error('Unexpected microphone')};
              qa.player=new TranslatorPlayback({getContext:()=>qa.context,fetchAudio:async(...args)=>{qa.requests++;return fetch(...args)}});
              const play=document.createElement('button');play.id='fixture-play';play.type='button';play.textContent='Play fixture';
              play.onclick=()=>{qa.error=null;if(!qa.context||qa.context.state==='closed')qa.context=new AudioContext();
                qa.promise=qa.player.prepare(new AbortController().signal,()=>true).then(()=>qa.player.play(qa.url,new AbortController().signal,()=>true,()=>qa.started++)).then(()=>qa.completed++).catch(error=>{qa.error=error.name==='AbortError'?error.name:error.code||error.name});};
              const cancel=document.createElement('button');cancel.id='fixture-cancel';cancel.type='button';cancel.textContent='Cancel fixture';
              cancel.onclick=()=>{qa.player.cancel();qa.context.close()};document.body.append(play,cancel);
            }''',url)
            page.locator('#fixture-play').click();page.wait_for_function('qa.started===1')
            before=page.evaluate('qa.context.currentTime');page.wait_for_timeout(150);assert page.evaluate('qa.context.currentTime')>before
            page.locator('#fixture-cancel').click();page.wait_for_function("qa.error==='AbortError'&&qa.context.state==='closed'")
            page.locator('#fixture-play').click();page.wait_for_function('qa.completed===1',timeout=10000)
            fetched=case.client.get(url);assert fetched.status_code==200 and hashlib.sha256(fetched.data).hexdigest()==digest
            next_url=turn(2)
            page.evaluate('url=>qa.url=url',next_url);page.locator('#fixture-play').click();page.wait_for_function('qa.completed===2',timeout=10000)
            # Beginning the next utterance retires the old RAM artifact honestly.
            page.evaluate('url=>qa.url=url',url);page.locator('#fixture-play').click();page.wait_for_function("qa.error==='audio_expired'")
            assert synthesis.call_count==2 and translation.call_count==2
            assert page.evaluate('qa.microphones')==0 and not errors,errors
            report.update(cached_v4_mp3_sha256=digest,decoded_played_clock_advanced=True,cancel_cleanup=True,retained_artifact_refetch=True,next_utterance=True,expired_old_artifact='audio_expired',mocked_synthesis_calls=2,requests=page.evaluate('qa.requests'),completed_playbacks=page.evaluate('qa.completed'))
            context.close();browser.close()
        output=Path('/tmp/kilas-translator-auto-audio-qa');output.mkdir(exist_ok=True);(output/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    finally:
        if ident:sessions.end(case.user,ident)
        server.shutdown();case.doCleanups()


if __name__=='__main__':main()
