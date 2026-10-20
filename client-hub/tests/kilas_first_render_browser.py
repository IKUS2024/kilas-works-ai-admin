"""Cold/warm first-paint and native feature navigation; no mic or paid requests."""
import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_model_preferences as fixture
from kilas_ai import live_translator as live, audio_branded_voices as branded, chat_models, translator_languages as languages

TRACE = """window.qaFrames=[];window.qaShifts=[];window.qaMic=0;
new PerformanceObserver(list=>{for(const e of list.getEntries())qaShifts.push(e.value)}).observe({type:'layout-shift',buffered:true});
navigator.mediaDevices.getUserMedia=async()=>{qaMic++;throw Error('Microphone forbidden')};
const round=n=>Math.round(n*100)/100;
function sample(){const main=document.querySelector('#kw-main'),nav=document.querySelector('.home-task-choices'),input=document.querySelector('#ai-input,#agent-message'),form=document.querySelector('#live-setup-form'),voice=document.querySelector('#voiceover-panel'),picker=document.querySelector('.translator-picker');const rect=e=>e?{x:round(e.getBoundingClientRect().x),y:round(e.getBoundingClientRect().y),width:round(e.getBoundingClientRect().width),height:round(e.getBoundingClientRect().height)}:null;
qaFrames.push({at:performance.now(),main:rect(main),nav:nav?getComputedStyle(nav).display:'',content:rect(input||form||voice),picker:rect(picker),font:document.fonts.check('16px Manrope')});if(qaFrames.length<1500)requestAnimationFrame(sample)}requestAnimationFrame(sample);"""


def main():
    case=fixture.PreferenceTests('test_unsent_home_choice_survives_new_authenticated_sessions_and_reopening');case.setUp()
    app=fixture.fixture.fixture.fixture.base.f.fixture.app.app
    server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}';output=Path('/tmp/kilas-first-render-browser');output.mkdir(exist_ok=True);report=[]
    case.choose('chat','gpt-6-luna');case.choose('image','gpt-image-1-mini')
    paths={'chat':'/products/start','translator':'/kilas-translator/live','voiceover':'/kilas-translator?mode=voiceover'}
    try:
        with patch.object(languages,'classic_names',return_value=languages.names(languages.CLASSIC)),patch.object(live,'ready',return_value=True),patch.object(branded,'public_choices',return_value=[{'alias':'kilas-male','name':'Kilas Male'}]),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
            scenarios=[(width,mode) for width in (320,820,1440) for mode in ('cold-css','warm')]+[(390,'cold-script'),(390,'cold-font')]
            for width,mode in scenarios:
                context=browser.new_context(viewport={'width':width,'height':900});cookie=case.client().get_cookie('session')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}]);context.add_init_script(TRACE)
                page=context.new_page();errors=[];unexpected=[];documents=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                def observed(request):
                    if request.resource_type=='document':documents.append(request.url)
                    if not request.url.startswith(origin):unexpected.append(request.url)
                    if request.method=='POST' and not any(request.url.endswith(p) for p in ('/kilas-translator?mode=voiceover','/kilas-ai/work/preferences')):unexpected.append(request.url)
                page.on('request',observed)
                if mode!='warm':
                    def route(r):
                        if not r.request.url.startswith(origin):r.abort();return
                        delayed=(mode=='cold-css' and 'kilas_home.css' in r.request.url or mode=='cold-script' and 'kilas_translator_picker.js' in r.request.url or mode=='cold-font' and 'manrope-variable.ttf' in r.request.url)
                        if delayed:response=r.fetch();time.sleep(.8);r.fulfill(response=response)
                        else:r.continue_()
                    page.route('**/*',route)
                def verify(surface,reason):
                    selector={'chat':'#ai-input','translator':'#live-setup-form','voiceover':'#voiceover-panel'}[surface]
                    expect(page.locator(selector)).to_be_visible()
                    if surface=='translator':
                        expect(page.locator('.translator-picker')).to_have_count(2)
                        expect(page.locator('[name=consent]')).not_to_be_checked()
                        expect(page.locator('[name=language_a]')).to_have_value('id')
                        expect(page.locator('[name=language_b]')).to_have_value('en')
                    if surface=='chat':
                        expect(page.locator('[data-model-kind=chat] [data-model-label]')).to_have_text('GPT-6 Luna')
                        expect(page.locator('[data-model-kind=image] [data-model-label]')).to_have_text('GPT Image 1 Mini')
                    page.wait_for_timeout(120)
                    data=page.evaluate("""()=>{const fcp=performance.getEntriesByName('first-contentful-paint')[0]?.startTime;const frames=qaFrames.filter(p=>fcp!==undefined&&p.at>=fcp);return {fcp,frames:frames.length,incomplete:frames.filter(p=>!p.main?.height||!p.content?.height||p.nav!=='flex').length,geometry:[...new Set(frames.map(p=>JSON.stringify([p.main?.x,p.main?.width,p.content?.x,p.content?.y,p.content?.width,p.content?.height,p.picker?.height])))],cls:qaShifts.reduce((a,b)=>a+b,0),overflow:document.documentElement.scrollWidth>innerWidth,mic:qaMic,bodyStyles:[...document.querySelectorAll('body link[rel=stylesheet]')].map(e=>e.href)}}""")
                    assert data['frames'] and data['incomplete']==0,(surface,reason,data)
                    assert not data['bodyStyles'] and not data['overflow'] and not data['mic'],data
                    assert data['cls']<.01,(surface,reason,data)
                    # Compare geometry across hydration; font-delayed text may change wrapping.
                    if mode!='cold-font':assert len(data['geometry'])==1,(surface,reason,data)
                    report.append({'width':width,'mode':mode,'surface':surface,'navigation':reason,**data})
                for surface,path in paths.items():
                    page.goto(origin+path,wait_until='networkidle');verify(surface,'direct')
                for repeat in range(2):
                    page.get_by_role('link',name='Translator',exact=True).click();verify('translator','voiceover-to-translator')
                    page.get_by_role('link',name='AI Chat',exact=True).click();verify('chat','translator-to-chat')
                    page.get_by_role('button',name='Voice Over',exact=True).click();verify('voiceover','chat-to-voiceover')
                    page.get_by_role('link',name='AI Chat',exact=True).click();verify('chat','voiceover-to-chat')
                    page.get_by_role('link',name='Translator',exact=True).click();verify('translator','chat-to-translator')
                    page.get_by_role('link',name='Voice Over',exact=True).click();verify('voiceover','translator-to-voiceover')
                page.go_back(wait_until='networkidle');verify('translator','back')
                page.go_forward(wait_until='networkidle');verify('voiceover','forward')
                page.reload(wait_until='networkidle');verify('voiceover','reload')
                assert not errors and not unexpected,(errors,unexpected)
                for surface,path in paths.items():
                    page.goto(origin+path,wait_until='networkidle')
                    page.screenshot(path=str(output/f'{surface}-{width}-{mode}.png'))
                print('PASS '+json.dumps({'width':width,'mode':mode,'checks':18,'page_errors':errors,'documents':len(documents)}),flush=True)
                context.close()
            # Native selects remain usable when JavaScript is disabled.
            context=browser.new_context(java_script_enabled=False);cookie=case.client().get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}]);page=context.new_page();page.goto(origin+paths['translator'])
            expect(page.locator('select[data-translator-language]').nth(0)).to_be_visible();expect(page.locator('[data-translator-trigger]').nth(0)).to_be_hidden();page.locator('[name=language_a]').select_option('fr');expect(page.locator('[name=language_a]')).to_have_value('fr');context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps({'checks':report,'paid_inference':False,'no_javascript_fallback':'PASS'},indent=2))
        print(json.dumps({'checks':len(report),'no_javascript_fallback':'PASS','paid_inference':False}))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
