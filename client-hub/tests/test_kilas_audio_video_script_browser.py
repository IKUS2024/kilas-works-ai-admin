"""Real MP4 multipart/local decoding with provider mock, and deterministic draft races."""
import json
import os
import shutil
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_kilas_audio_video_script import VideoScriptTests, f, stt
from kilas_ai import audio_provider


def main():
    VideoScriptTests.setUpClass()
    server=make_server('127.0.0.1',0,f.app.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_AUDIO_VIDEO_SCREENSHOTS','/tmp/kilas-audio-video-script'));output.mkdir(parents=True,exist_ok=True)
    try:
        with patch.object(audio_provider,'voices',return_value=[{'id':'qaVoice123','name':'QA','style':'Synthetic'}]),sync_playwright() as p:
            browser=p.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width,height in ((320,800),(390,844),(820,1180),(1440,900)):
                case=VideoScriptTests('test_real_mp4_decode_original_text_only_no_tts_job_or_credit_debit');case.id=lambda:'video-script-browser-'+str(width);case.setUp();case.credit(300)
                with case.funded(),patch.dict(os.environ,{'KILAS_AUDIO_UPLOAD_TRANSLATION_VISIBLE':'false'}),patch.object(stt.requests,'post',return_value=case.response('Ucapan asli yang bisa diedit.')) as paid:
                    context=browser.new_context(viewport={'width':width,'height':height},has_touch=width<1024)
                    cookie=case.client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}])
                    page=context.new_page();errors=[];jobs=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:jobs.append(r.url) if r.method=='POST' and r.url.endswith('/kilas-translator/jobs') else None)
                    page.goto(origin+'/kilas-translator?mode=voiceover',wait_until='networkidle')
                    expect(page.locator('#audio-script')).to_have_count(1);expect(page.locator('#translate-panel')).to_have_count(0)
                    expect(page.locator('#voice-video-file,#voice-video-extract')).to_have_count(0)
                    expect(page.locator('#voice-dictation')).to_be_visible()
                    page.fill('#audio-script','Original draft.')
                    expect(page.locator('#audio-script')).to_have_value('Original draft.')
                    assert paid.call_count==0 and jobs==[] and not errors
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    context.close()
                case.doCleanups();print('PASS removed video UI / retained editable Naskah',width,flush=True)
            # Legacy completed output: real local MP3 decoding, never restored as original.
            for width,height in ((390,844),(1440,900)):
                case=VideoScriptTests('test_legacy_reconstruction_preserves_entire_job_and_never_restores_original');case.id=lambda:'legacy-script-browser-'+str(width);case.setUp();case.credit(300);ident=case.legacy_job()
                with case.funded(),patch.dict(os.environ,{'KILAS_AUDIO_UPLOAD_TRANSLATION_VISIBLE':'false'}),patch.object(stt.requests,'post',return_value=case.response('English spoken output, reconstructed.')) as paid:
                    context=browser.new_context(viewport={'width':width,'height':height});cookie=case.client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}]);page=context.new_page();jobs=[];errors=[]
                    page.on('request',lambda r:jobs.append(r.url) if r.method=='POST' and r.url.endswith('/kilas-translator/jobs') else None);page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(origin+'/kilas-translator/jobs/'+str(ident),wait_until='networkidle');buttons=page.locator('[data-audio-reconstruct]');expect(buttons).to_have_count(2)
                    expect(page.locator('#audio-script')).to_have_count(1);expect(page.locator('[data-audio-edit]')).to_have_count(0)
                    page.once('dialog',lambda d:d.accept());buttons.first.click();expect(page.locator('#audio-script')).to_have_value('English spoken output, reconstructed.',timeout=20000)
                    expect(page.locator('#voice-video-status')).to_contain_text('bukan naskah asli');assert paid.call_count==1 and jobs==[]
                    assert f.db.query_one('SELECT original_script FROM kilas_audio_jobs WHERE id=?',(ident,))['original_script'] is None
                    # A dynamically inserted result button still uses delegated ownership-bound navigation.
                    page.evaluate("document.querySelector('[data-audio-reconstruct]').outerHTML=document.querySelector('[data-audio-reconstruct]').outerHTML;window.confirm=()=>true;window.qaLegacyFetch=fetch;window.fetch=(url,options)=>String(url).includes('/reconstruct-script')&&options?.body?.get('action')!=='cancel'?new Promise(resolve=>window.qaLegacyResolve=resolve):qaLegacyFetch(url,options)")
                    page.fill('#audio-script','Unsaved draft.');buttons.last.click();expect(page.locator('#voice-video-stop')).to_be_visible()
                    page.fill('#audio-script','Changed while processing.')
                    page.evaluate("qaLegacyResolve({ok:true,redirected:false,json:async()=>({status:'COMPLETED',text:'Buffered reconstruction.',source_kind:'audio_reconstruction',job_id:"+str(ident)+"})})")
                    expect(page.locator('#voice-video-apply')).to_be_visible();expect(page.locator('#audio-script')).to_have_value('Changed while processing.')
                    page.locator('#voice-video-apply').click();expect(page.locator('#audio-script')).to_have_value('Buffered reconstruction.');expect(page.locator('#voice-video-status')).to_contain_text('bukan naskah asli')
                    page.locator('#voice-video-undo').click();expect(page.locator('#audio-script')).to_have_value('Changed while processing.')
                    buttons.first.click();expect(page.locator('#voice-video-apply')).to_be_hidden();page.locator('#voice-video-stop').click()
                    page.evaluate("qaLegacyResolve({ok:true,redirected:false,json:async()=>({status:'COMPLETED',text:'Late canceled text.',source_kind:'audio_reconstruction',job_id:"+str(ident)+"})})")
                    expect(page.locator('#audio-script')).to_have_value('Changed while processing.');expect(page.locator('#voice-video-status')).to_contain_text('Dihentikan')
                    buttons.first.click();page.evaluate("qaLegacyResolve({ok:true,redirected:false,json:async()=>({status:'COMPLETED',text:'Wrong job text.',source_kind:'audio_reconstruction',job_id:0})})")
                    expect(page.locator('#voice-video-status')).to_contain_text('tidak cocok');expect(page.locator('#audio-script')).to_have_value('Changed while processing.')
                    assert jobs==[] and paid.call_count==1 and not errors,(jobs,errors)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(output/f'legacy-reconstruction-{width}.png'),full_page=True)
                    with patch.dict(os.environ,{'KILAS_VOICE_VIDEO_SCRIPT_ENABLED':'false'}):
                        page.goto(origin+'/kilas-translator/jobs/'+str(ident),wait_until='networkidle');expect(page.locator('[data-audio-reconstruct]').first).to_be_disabled();expect(page.locator('#audio-script')).to_be_editable()
                    context.close()
                case.doCleanups();print('PASS legacy reconstruction browser',width,flush=True)
            browser.close()
    finally:server.shutdown()


if __name__=='__main__':main()
