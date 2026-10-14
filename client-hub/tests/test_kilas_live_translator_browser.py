"""Local Chromium session UI, synthetic mic/analyser/playback/network. No paid IO."""
import json
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_home as home
from kilas_ai import live_translator as live, audio_branded_voices as branded, audio_provider

MEDIA="""window.qa={rms:0,mics:0,starts:0,stops:0,plays:0,closed:0,permission:'allow',empty:false};
navigator.mediaDevices.getUserMedia=async()=>{if(qa.permission==='deny')throw new DOMException('Denied','NotAllowedError');qa.mics++;qa.starts++;let stopped=false;return {getTracks:()=>[{stop:()=>{if(!stopped){stopped=true;qa.mics--;qa.stops++;}}}]}};
window.MediaRecorder=class{static isTypeSupported(){return true}constructor(){this.state='inactive';this.mimeType='audio/webm';this.events={}}addEventListener(name,fn){this.events[name]=fn}start(){this.state='recording'}stop(){if(this.state!=='recording')return;this.state='inactive';this.events.dataavailable({data:new Blob(qa.empty?[]:['synthetic'])});this.events.stop()}};
window.AudioContext=class{constructor(){this.state='suspended';this.currentTime=0;this.destination={};qa.context=this}resume(){this.state='running';return Promise.resolve()}close(){this.state='closed';qa.closed++;return Promise.resolve()}createMediaStreamSource(){return {connect(){},disconnect(){}}}createAnalyser(){return {fftSize:2048,disconnect(){},getFloatTimeDomainData(array){array.fill(qa.rms);if(qa.rms>.015)qa.lastVoice=performance.now()}}}decodeAudioData(){return Promise.resolve({duration:1.4})}createBufferSource(){return {connect(){},disconnect(){},start(){if(qa.mics)throw Error('Playback captured by mic');qa.plays++;qa.audio=this},stop(){qa.audio=null}}}};
"""


def main():
    case=home.HomeTests('test_old_routes_still_render');case.id=lambda:'live-translator-browser';case.setUp()
    app=home.fixture.base.f.fixture.app.app
    server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_LIVE_SCREENSHOTS',str(Path(tempfile.gettempdir())/'kilas-live-translator-browser')));output.mkdir(parents=True,exist_ok=True);report={'kind':'synthetic browser session; no actual speech or provider requests','paid_calls':0,'reference_match':False,'viewports':[]}
    try:
        with patch.object(live,'ready',return_value=True),patch.object(branded,'public_choices',return_value=[{'alias':'kilas-male','name':'Kilas Male','style':'Natural'},{'alias':'kilas-female','name':'Kilas Female','style':'Natural'}]),patch.object(audio_provider,'request',side_effect=AssertionError('Paid transport forbidden')),sync_playwright() as pw:
            options={'headless':True}
            if os.environ.get('KILAS_QA_CHROMIUM'):options.update(executable_path=os.environ['KILAS_QA_CHROMIUM'],args=['--no-sandbox'])
            browser=pw.chromium.launch(**options)
            for width,height in ((320,780),(360,800),(390,844),(430,900),(820,1100),(1440,900)):
                c=browser.new_context(viewport={'width':width,'height':height});cookie=case.client().get_cookie('session');c.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}]);c.add_init_script(MEDIA)
                page=c.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));state={'complete':False,'posts':0,'ends':0,'pairs':[],'sent_at':None,'hold_start':True,'pending':[]}
                def route(r):
                    path=r.request.url.removeprefix(origin)
                    if path=='/kilas-translator/live/sessions':
                        state['pairs'].append(r.request.post_data)
                        if state['hold_start']:state['pending'].append(r)
                        else:r.fulfill(status=201,content_type='application/json',body=json.dumps({'session_id':'a'*48}))
                    elif path.endswith('/end'):
                        state['ends']+=1;r.fulfill(content_type='application/json',body='{"status":"ENDED"}')
                    elif path=='/kilas-translator/live/sessions/'+'a'*48:
                        r.fulfill(content_type='application/json',body='{"status":"ACTIVE","processing":false}')
                    elif '/turns/' in path:
                        if path.endswith('/audio'):r.fulfill(content_type='audio/mpeg',body=b'synthetic')
                        elif r.request.method=='POST':
                            state['posts']+=1;state['sent_at']=page.evaluate('performance.now()-qa.lastVoice');r.fulfill(status=202,content_type='application/json',body='{"status":"PROCESSING"}')
                        else:r.fulfill(content_type='application/json',body=json.dumps({'status':'COMPLETED','audio_url':path+'/audio','translated_text':'Hello, this is a safe translation test.'} if state['complete'] else {'status':'PROCESSING'}))
                    elif r.request.url.startswith(origin):r.continue_()
                    else:r.abort()
                page.route('**/*',route)
                page.goto(origin+'/kilas-translator/live',wait_until='networkidle')
                expect(page.locator('select[name=voice]')).to_have_value('kilas-male');assert page.evaluate('qa.starts')==0
                current=page.locator('.kilas-feature-navigation [aria-current=page]')
                assert current.evaluate('e=>e.getBoundingClientRect().height<=80&&getComputedStyle(e).whiteSpace==="nowrap"')
                assert page.locator('#premium-sidebar,[data-chat-sidebar],textarea').count()==0
                page.locator('[name=consent]').check();page.get_by_role('button',name='Start',exact=True).click()
                expect(page.locator('#live-active')).to_be_visible();expect(page.locator('.kilas-live-orb')).to_have_attribute('aria-label','Memproses')
                page.get_by_role('button',name='Akhiri sesi',exact=True).click();expect(page.get_by_role('button',name='Start',exact=True)).to_be_enabled()
                assert page.evaluate('qa.starts')==0
                assert len(state['pending'])==1
                state['pending'].pop().fulfill(status=201,content_type='application/json',body=json.dumps({'session_id':'b'*48}))
                state['hold_start']=False
                page.get_by_role('button',name='Start',exact=True).click();page.wait_for_function('qa.starts===1')
                assert page.locator('#live-active button:visible').count()==1;expect(page.get_by_role('button',name='Akhiri sesi',exact=True)).to_be_visible()
                expect(page.locator('#live-state')).to_have_text('Mendengarkan')
                page.evaluate('qa.rms=.2');page.wait_for_function('!!qa.lastVoice');page.evaluate('qa.rms=0');page.wait_for_timeout(1700);assert state['posts']==0
                page.wait_for_function('qa.mics===0',timeout=2000);page.wait_for_timeout(100);assert state['posts']==1 and state['sent_at']>=1990,state
                expect(page.locator('#live-state')).to_have_text('Memproses')
                state['complete']=True;page.wait_for_function('qa.plays===1');assert page.evaluate('qa.mics')==0
                expect(page.locator('#live-translation')).to_have_text('Hello, this is a safe translation test.')
                expect(page.locator('#live-state')).to_have_text('Hasil')
                page.evaluate('qa.rms=.4');page.wait_for_timeout(3200);assert state['posts']==1 and page.evaluate('qa.starts')==1
                # Playback completion resumes listening; End stops the resumed mic immediately.
                page.evaluate('qa.context.currentTime+=qa.audio.buffer.duration;qa.audio.onended()');page.wait_for_function('qa.starts===2');page.get_by_role('button',name='Akhiri sesi',exact=True).click();expect(page.locator('#live-active')).to_be_hidden();assert page.evaluate('qa.mics')==0
                # Reverse pair/female selection is frozen in Start payload; End cancels pending turn.
                page.select_option('[name=language_a]','en');page.select_option('[name=language_b]','id');page.select_option('[name=voice]','kilas-female');state['complete']=False
                page.get_by_role('button',name='Start',exact=True).click();page.wait_for_function('qa.starts===3');page.evaluate('qa.rms=.2');page.wait_for_timeout(100);page.evaluate('qa.rms=0');page.wait_for_function('qa.mics===0',timeout=5000)
                page.get_by_role('button',name='Akhiri sesi',exact=True).click();state['complete']=True;page.wait_for_timeout(700);assert page.evaluate('qa.plays')==1 and page.evaluate('qa.mics')==0
                assert 'name="language_a"\r\n\r\nen' in state['pairs'][-1] and 'kilas-female' in state['pairs'][-1]
                # Empty capture does not reach STT/network and resumes a fresh listening cycle.
                posts=state['posts'];page.evaluate('qa.empty=true;qa.rms=0')
                page.get_by_role('button',name='Start',exact=True).click();page.wait_for_function('qa.starts===4')
                page.evaluate('qa.rms=.2');page.wait_for_timeout(100);page.evaluate('qa.rms=0');page.wait_for_function('qa.starts===5',timeout=5000)
                expect(page.locator('#live-error')).to_contain_text('Rekaman kosong');assert state['posts']==posts
                expect(page.locator('#live-error')).to_have_css('color','rgb(255, 175, 182)')
                assert page.evaluate('qa.mics')==1
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(output/f'listening-{width}.png'),full_page=True)
                page.get_by_role('button',name='Akhiri sesi',exact=True).click();assert page.evaluate('qa.mics')==0
                page.evaluate("qa.permission='deny'");page.get_by_role('button',name='Start',exact=True).click();expect(page.locator('#live-error')).to_be_visible();expect(page.get_by_role('button',name='Lanjutkan',exact=True)).to_be_visible();expect(page.locator('#live-state')).to_have_text('Sesi dijeda');assert page.evaluate('qa.mics')==0
                page.get_by_role('button',name='Akhiri sesi',exact=True).click();expect(page.get_by_role('button',name='Start',exact=True)).to_be_enabled()
                with patch.object(live,'ready',return_value=False):page.reload(wait_until='networkidle')
                expect(page.get_by_role('button',name='Start',exact=True)).to_be_disabled();expect(page.locator('.kilas-translator-pending')).to_be_visible();assert page.evaluate('qa.starts')==0
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');assert not errors,errors
                page.screenshot(path=str(output/f'disabled-{width}.png'),full_page=True);report['viewports'].append({'width':width,'silence_min_ms':state['sent_at'],'session_pair_voice_resume_feedback_End_permission_gates':'PASS'});c.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:server.shutdown();case.doCleanups()

if __name__=='__main__':main()
