"""Keyboard viewport cycles and draft/control visibility on disposable chat data.

Chromium resize/visualViewport simulation, not physical Android keyboard evidence.
No chats are submitted; external requests and provider IO are blocked.
"""
import json
import logging
import shutil
import threading
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server
import test_kilas_home as home
from kilas_ai import agent_store, chat_models, image_models, live_translator, store

VIEWPORT = """(()=>{
 const v=new EventTarget();Object.assign(v,{height:innerHeight,width:innerWidth,offsetTop:0,offsetLeft:0,scale:1});
 Object.defineProperty(window,'visualViewport',{value:v});
 window.qaViewport=(height,top=0)=>{Object.assign(v,{height,offsetTop:top});v.dispatchEvent(new Event('resize'))};
})()"""
GEOMETRY = """()=>{
 const box=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,w:r.width,h:r.height}};
 const root=document.querySelector('.kilas-home-workspace'),input=root.querySelector('#ai-input,#agent-message');
 const selectors=['.kilas-reference-header','.home-tool-selector','.ai-attach,.work-add-file','#ai-send,#agent-chat-form button[type=submit]','.ai-call-launch'];
 return {height:visualViewport.height,top:visualViewport.offsetTop,input:box(input),
   controls:selectors.map(s=>{const e=document.querySelector(s),r=box(e);return {selector:s,...r,visible:e.checkVisibility(),hit:s==='.home-tool-selector'||e.contains(document.elementFromPoint(r.x+r.w/2,r.y+r.h/2))}}),
   composer:box(root.querySelector('#ai-composer,#agent-chat-form .ai-composer')),
   docOverflow:document.documentElement.scrollWidth>innerWidth,rootScroll:root.scrollTop,
   inline:document.body.classList.contains('home-keyboard-inline')};
}"""
DRAFT = 'Unsent Indonesian draft / Draf tetap aman.\nSecond line for typing.\nThird line.'


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case=home.HomeTests('test_old_routes_still_render');case.id=lambda:'keyboard-stability';case.setUp()
    app=home.fixture.base.f.fixture.app.app
    thread=store.create_thread(case.owner)
    for i in range(18):
        key=f'keyboard-fixture-{i}'
        store.append_user_once(case.owner,thread,f'Synthetic message {i}', 'SMART',key)
        store.append_assistant(case.owner,thread,'Synthetic stored answer.\n'*4,'SMART','synthetic','synthetic',key,{})
    empty=agent_store.new_conversation(case.owner);history=agent_store.new_conversation(case.owner)
    for i in range(18):
        agent_store.append(case.owner,'user',f'Synthetic agent message {i}',history)
        agent_store.append(case.owner,'assistant','Synthetic stored answer.\n'*4,history)
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    output=Path('/tmp/kilas-chat-keyboard');output.mkdir(exist_ok=True);report=[]
    routes=[('home','/products/start'),('thread',f'/kilas-ai/threads/{thread}'),
            ('agent-empty',f'/kilas-ai/agent?conversation={empty}'),('agent-history',f'/kilas-ai/agent?conversation={history}')]
    try:
        with patch.object(live_translator,'ready',return_value=True), \
             patch.object(chat_models,'check',side_effect=lambda m:{**chat_models.spec(m),'available':True,'images':True,'status':'verified'}), \
             patch.object(image_models,'check',side_effect=lambda m:{**image_models.spec(m),'available':True,'status':'verified'}),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for mode in ('layout','visual'):
                for width in (320,360,390,393,430,768,1440):
                    context=browser.new_context(viewport={'width':width,'height':844},has_touch=width<761)
                    cookie=case.client().get_cookie('session')
                    context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                    if mode=='visual':context.add_init_script(VIEWPORT)
                    context.add_init_script("window.qaMicRequests=0;navigator.mediaDevices.getUserMedia=()=>{window.qaMicRequests++;return Promise.reject(Error('Microphone forbidden in keyboard QA'))}")
                    context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                    page=context.new_page();errors=[];writes=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('request',lambda r:writes.append(r.url) if r.method=='POST' else None)
                    for name,path in routes:
                        page.goto(origin+path,wait_until='networkidle')
                        field=page.locator('#ai-input,#agent-message');field.fill(DRAFT);field.focus()

                        def resize(height,top=0):
                            if mode=='visual':page.evaluate('g=>qaViewport(g[0],g[1])',[height,top])
                            else:page.set_viewport_size({'width':width,'height':height})
                            page.wait_for_timeout(25)

                        for cycle in range(2):
                            for height in (480,499,501,390,300,390):
                                resize(height,12 if mode=='visual' else 0)
                                expect(field).to_be_focused();expect(field).to_have_value(DRAFT)
                                metrics=page.evaluate(GEOMETRY)
                                assert metrics['inline'] and not metrics['docOverflow'],(mode,width,name,height,metrics)
                                assert metrics['rootScroll']==0,(mode,width,name,metrics)
                                assert metrics['input']['w']>=60 and metrics['input']['y']>=metrics['top']
                                assert metrics['composer']['bottom']<=height+metrics['top']+1,(mode,width,name,height,metrics)
                                for c in metrics['controls']:
                                    assert c['visible'] and c['hit'] and c['y']>=metrics['top']-1 and c['bottom']<=height+metrics['top']+1,(mode,width,name,height,c)
                                expect(page.locator('.home-task-choices')).to_contain_text('AI Chat')
                                expect(page.locator('.ai-regenerate,.chat-voice-draft')).to_have_count(0)
                            # Focus transfers must not hide the navigation while the keyboard closes.
                            page.locator('.home-task-choices').locator('button,a').first.focus()
                            assert page.evaluate(GEOMETRY)['inline']
                            field.focus();field.fill('Multiline draft\n'*9)
                            resize(350,12 if mode=='visual' else 0)
                            multi=page.evaluate(GEOMETRY)
                            assert multi['composer']['bottom']<=350+multi['top']+1
                            assert field.evaluate('e=>{e.scrollTop=e.scrollHeight;return e.scrollHeight<=e.clientHeight||e.scrollTop>0}')
                            picker=page.locator('#ai-files,#work-source-files')
                            picker.set_input_files([{'name':'synthetic-notes.txt','mimeType':'text/plain','buffer':b'Fixture notes.'}])
                            for attached_height in (350,300):
                                resize(attached_height,12 if mode=='visual' else 0)
                                for selector in ('.ai-attach,.work-add-file','#ai-send,#agent-chat-form button[type=submit]','#ai-pending button,#work-pending-files button'):
                                    c=page.locator(selector).first;expect(c).to_be_in_viewport()
                                    assert c.evaluate('e=>{const r=e.getBoundingClientRect(),v=visualViewport;return r.top>=v.offsetTop&&r.bottom<=v.offsetTop+v.height+1&&e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}'),(mode,width,name,attached_height,selector)
                                attached=page.evaluate(GEOMETRY)
                                assert attached['composer']['bottom']<=attached_height+attached['top']+1,(mode,width,name,attached)
                                for control in attached['controls']:
                                    assert control['visible'] and control['hit'] and control['bottom']<=attached_height+attached['top']+1,(mode,width,name,control)
                                if cycle==0 and width==320 and attached_height==300:
                                    page.screenshot(path=str(output/f'{name}-{mode}-320-pending.png'))
                            page.locator('#ai-pending button,#work-pending-files button').first.click()
                            field.fill(DRAFT);field.focus()
                            timeline=page.locator('#ai-messages,#agent-conversation')
                            if name in ('thread','agent-history'):
                                timeline.evaluate('e=>e.scrollTop=80');before=timeline.evaluate('e=>e.scrollTop')
                                resize(390,12 if mode=='visual' else 0)
                                assert abs(timeline.evaluate('e=>e.scrollTop')-before)<2
                            if cycle==0 and width in (320,430,1440):
                                page.screenshot(path=str(output/f'{name}-{mode}-{width}.png'))
                            field.blur();resize(844)
                            expect(field).to_have_value(DRAFT)
                            assert not page.evaluate(GEOMETRY)['inline']
                            field.focus()
                        if name=='home':
                            if width==390:
                                field.focus();resize(390)
                                call=page.locator('[data-ai-call-launch]');call.click()
                                expect(page.locator('#ai-call-dialog')).to_be_visible()
                                assert page.evaluate('qaMicRequests')==0
                                page.locator('#ai-call-dialog').evaluate('e=>e.close()')
                                expect(call).to_be_focused();expect(field).to_have_value(DRAFT)
                            field.blur();resize(844)
                            page.locator('.home-task-choices a').filter(has_text='Translator').click()
                            page.wait_for_load_state('networkidle')
                            page.go_back(wait_until='networkidle');expect(field).to_have_value(DRAFT)
                            page.go_forward(wait_until='networkidle');page.go_back(wait_until='networkidle');expect(field).to_have_value(DRAFT)
                        report.append({'mode':mode,'width':width,'surface':name,'cycles':2,'result':'PASS'})
                    assert not errors and all(u.endswith('/kilas-ai/work/preferences') for u in writes),(errors,writes)
                    context.close();print(f'PASS keyboard {mode} {width}: all four chat states',flush=True)
            browser.close()
        (output/'verification.json').write_text(json.dumps({'physical_android':False,'paid_calls':0,'checks':report},indent=2))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
