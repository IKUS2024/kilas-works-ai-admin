"""Native navigation/first paint with delayed CSS/readiness. No mic or paid IO."""
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_home as home
from kilas_ai import live_translator as live, audio_branded_voices as branded

PAINT="""window.qaPaint=[];window.qaStartLabels=[];window.qaShifts=[];
new MutationObserver(()=>{const b=document.querySelector('#live-setup-form button');if(b&&qaStartLabels.at(-1)!==b.textContent.trim())qaStartLabels.push(b.textContent.trim())}).observe(document,{subtree:true,childList:true,characterData:true});
new PerformanceObserver(list=>{for(const v of list.getEntries())if(!v.hadRecentInput)qaShifts.push(v.value)}).observe({type:'layout-shift',buffered:true});
const until=performance.now()+4500;function sample(){const m=document.querySelector('.ai-main'),c=document.querySelector('#ai-input,#agent-message'),r=c?.getBoundingClientRect();qaPaint.push({at:performance.now(),main:!!m&&m.getBoundingClientRect().height>0,composer:!!r&&r.top<innerHeight&&r.bottom>0});if(performance.now()<until)requestAnimationFrame(sample)}requestAnimationFrame(sample);
navigator.mediaDevices.getUserMedia=async()=>{throw Error('Real microphone forbidden')};"""


def main():
    case=home.HomeTests('test_old_routes_still_render');case.id=lambda:'native-feature-switch-browser';case.setUp()
    server=make_server('127.0.0.1',0,home.fixture.base.f.fixture.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(tempfile.gettempdir())/'kilas-feature-navigation-browser';output.mkdir(exist_ok=True);report=[]
    try:
        with patch.object(live,'ready',return_value=True),patch.object(branded,'public_choices',return_value=[{'alias':'kilas-male','name':'Kilas Male'}]),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM','/usr/bin/chromium'),args=['--no-sandbox'])
            for width,delayed in ((320,'none'),(390,'kilas_home.css'),(390,'kilas_chat_models.css'),(820,'none'),(1440,'kilas_home.css'),(1440,'kilas_chat_models.css')):
                context=browser.new_context(viewport={'width':width,'height':844});cookie=case.client().get_cookie('session')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}]);context.add_init_script(PAINT)
                page=context.new_page();errors=[];pending=[];documents=[];posts=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda r:documents.append(r.url) if r.resource_type=='document' else posts.append(r.url) if r.method=='POST' else None)
                cdp=context.new_cdp_session(page);cdp.send('Network.enable');cdp.send('Network.setCacheDisabled',{'cacheDisabled':True})
                def route(r):
                    if not r.request.url.startswith(origin):r.abort();return
                    if r.request.url.endswith('/live/sessions/active'):pending.append(r);return
                    if delayed!='none' and delayed in r.request.url:
                        response=r.fetch();time.sleep(1.2);r.fulfill(response=response)
                    else:r.continue_()
                page.route('**/*',route)
                def chat_check():
                    expect(page.locator('#ai-input,#agent-message')).to_be_visible();page.wait_for_timeout(150)
                    for asset in ('kilas_home.css','kilas_chat.css','kilas_chat_models.css','kilas_task_navigation.css'):
                        assert page.locator('head link[rel=stylesheet][href*="'+asset+'"]').count()==1
                        assert page.locator('body link[rel=stylesheet][href*="'+asset+'"]').count()==0
                    result=page.evaluate("()=>{const f=performance.getEntriesByName('first-contentful-paint')[0]?.startTime;const painted=qaPaint.filter(p=>f!==undefined&&p.at>=f);return {fcp:f,frames:painted.length,blank:painted.filter(p=>!p.main).length,missingComposer:painted.filter(p=>!p.composer).length,cls:qaShifts.reduce((a,b)=>a+b,0),overflow:document.documentElement.scrollWidth>innerWidth}}");assert result['frames'] and result['blank']==0 and result['missingComposer']==0,result
                    assert not result['overflow'];return result
                def translator_check():
                    start=page.locator('#live-setup-form button[type=submit]')
                    expect(start).to_be_disabled();expect(start).to_have_text('Start');expect(start).to_have_attribute('aria-busy','true')
                    expect(page.locator('[name=consent]')).not_to_be_checked()
                    page.wait_for_timeout(200)
                    assert pending
                    while pending:pending.pop(0).fulfill(content_type='application/json',body='{"session":null}')
                    expect(start).to_be_enabled();expect(start).to_have_text('Start')
                    assert page.evaluate('qaStartLabels.every(x=>x==="Start")')
                    assert not page.locator('#live-permission-settings,#live-permission-notice').count()
                page.goto(origin+'/products/start',wait_until='domcontentloaded');first=chat_check()
                history_count=page.locator('[data-chat-sidebar] .ai-history a').count()
                for _ in range(2):
                    page.get_by_role('link',name='Translator',exact=True).click();translator_check()
                    page.get_by_role('link',name='AI Chat',exact=True).click();chat_check()
                    assert page.locator('[data-chat-sidebar] .ai-history a').count()==history_count
                page.reload(wait_until='domcontentloaded');chat_check()
                page.go_back(wait_until='domcontentloaded');translator_check()
                page.go_forward(wait_until='domcontentloaded');chat_check()
                if width in (320,1440):page.screenshot(path=str(output/f'chat-{width}-{delayed}.png'))
                assert not errors and not posts,(errors,posts)
                report.append({'width':width,'delayed':delayed,'delay_ms':1200 if delayed!='none' else 0,'first_paint':first,'native_documents':len(documents),'repeated_switches':2,'reload_back_forward':'PASS','stable_start_readiness':'PASS','paid_calls':0,'microphone_calls':0})
                print('PASS '+json.dumps(report[-1]),flush=True);context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps(report,indent=2))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
