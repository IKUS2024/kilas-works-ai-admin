"""Real local Chat layout with controlled keyboard viewport events; no paid QA."""
import json
import logging
import os
import shutil
import sys
import threading
from pathlib import Path


def loopback_only(event,args):
    if event=='socket.connect' and isinstance(args[1],tuple) and args[1][0] not in ('127.0.0.1','::1','localhost'):
        raise AssertionError('External network forbidden in Chat focus QA')
    if event=='socket.getaddrinfo' and args[0] not in ('127.0.0.1','::1','localhost',None):
        raise AssertionError('External DNS forbidden in Chat focus QA')


sys.addaudithook(loopback_only)

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_home as fixture
from kilas_ai import agent_store, store

VIEWPORT="""window.qaViewport=new EventTarget();Object.assign(qaViewport,{height:innerHeight,width:innerWidth,offsetTop:0,scale:1});Object.defineProperty(window,'visualViewport',{get:()=>qaViewport});"""


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case=fixture.HomeTests('test_old_routes_still_render');case.id=lambda:'chat-focus-browser';case.setUp()
    thread=store.create_thread(case.owner)
    store.append_user_once(case.owner,thread,'Saved synthetic message.','SMART','focus-synthetic-message')
    store.append_assistant(case.owner,thread,'Saved synthetic reply.','SMART','synthetic','synthetic','focus-synthetic-message',{})
    conversation=agent_store.new_conversation(case.owner)
    agent_store.append(case.owner,'user','Saved synthetic message.',conversation)
    agent_store.append(case.owner,'assistant','Saved synthetic reply.',conversation)
    app=fixture.fixture.base.f.fixture.app.app
    server=make_server('127.0.0.1',0,app,threaded=True);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_FOCUS_SCREENSHOTS','/tmp/kilas-chat-focus'));output.mkdir(parents=True,exist_ok=True)
    results=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox','--disable-background-networking'])
            cookie=case.client().get_cookie('session')
            for width,height in ((360,780),(390,844),(820,1024),(1440,900)):
                context=browser.new_context(viewport={'width':width,'height':height},has_touch=width<=820,reduced_motion='reduce')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
                context.add_init_script(VIEWPORT)
                page=context.new_page();errors=[];posts=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('request',lambda request:posts.append(request.url) if request.method=='POST' else None)
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                for agent,empty,path in ((False,True,'/products/start'),(True,True,'/kilas-ai/agent?conversation='+str(case.conversation)),
                                         (False,False,'/kilas-ai/threads/'+str(thread)),(True,False,'/kilas-ai/agent?conversation='+str(conversation))):
                    page.goto(origin+path,wait_until='networkidle')
                    field=page.locator('#agent-message' if agent else '#ai-input')
                    logo=page.locator('.kilas-home-workspace .kilas-new-chat-logo')
                    heading=page.get_by_role('heading',name='How can I Help you?',exact=True)
                    brand=page.locator('.home-workspace-top')
                    expect(brand).to_be_visible()
                    if empty:
                        expect(logo).to_be_visible();expect(heading).to_be_visible()
                        assert logo.bounding_box()['width']==96
                    else:expect(logo).to_be_hidden();expect(heading).to_be_hidden()
                    before=len(posts);url=page.url
                    normal_bottom_gap=height-page.locator('.ai-composer').last.evaluate('e=>e.getBoundingClientRect().bottom')
                    (field.tap if width<=820 else field.click)()
                    expect(field).to_have_value('')
                    if empty:expect(logo).to_be_visible();expect(heading).to_be_visible()
                    if width<=820:
                        for visible,top in ((420,0),(390,60),(420,20)):
                            page.evaluate('([height,top])=>{qaViewport.height=height;qaViewport.offsetTop=top;qaViewport.dispatchEvent(new Event("resize"));qaViewport.dispatchEvent(new Event("scroll"));}',[visible,top])
                            page.screenshot(path=str(output/f'{"agent" if agent else "home"}-{"empty" if empty else "saved"}-keyboard-{width}.png'))
                            expect(brand).to_be_visible()
                            if empty:expect(logo).to_be_visible();expect(heading).to_be_visible()
                            else:expect(logo).to_be_hidden();expect(heading).to_be_hidden()
                            tabs=page.locator('.home-tool-selector').bounding_box()
                            if empty:
                                pane=page.locator('#agent-conversation' if agent else '.ai-empty').bounding_box()
                                for element in (logo,heading):
                                    bounds=element.bounding_box()
                                    assert bounds['y']>=pane['y']-1 and bounds['y']+bounds['height']<=pane['y']+pane['height']+1,(width,agent,visible,bounds,pane)
                                    assert bounds['y']+bounds['height']<=tabs['y']+1,(width,agent,visible,bounds,tabs)
                            else:
                                pane=page.locator('#agent-conversation' if agent else '#ai-messages').bounding_box()
                                assert pane['height']>0 and pane['y']+pane['height']<=tabs['y']+1,(width,agent,visible,pane,tabs)
                            bottom=page.locator('.ai-composer').last.evaluate('e=>e.getBoundingClientRect().bottom')
                            assert 0<=visible+top-bottom<=28,(width,visible,top,bottom)
                            expect(page.locator('.ai-send').last).to_be_in_viewport()
                            expect(page.locator('[data-home-task=chat]')).to_be_in_viewport()
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        field.fill('a');field.fill('')
                        if empty:expect(logo).to_be_visible();expect(heading).to_be_visible()
                        field.fill('Unsent keyboard draft.');field.blur()
                        page.evaluate('qaViewport.height=innerHeight;qaViewport.offsetTop=0;qaViewport.dispatchEvent(new Event("resize"))')
                        expect(brand).to_be_visible()
                        if empty:expect(logo).to_be_visible();expect(heading).to_be_visible()
                        expect(field).to_have_value('Unsent keyboard draft.')
                        field.fill('')
                        # Some mobile browsers resize layout and visual viewports together.
                        page.set_viewport_size({'width':width,'height':420})
                        page.evaluate('qaViewport.height=innerHeight;qaViewport.offsetTop=0;qaViewport.dispatchEvent(new Event("resize"))')
                        field.focus();expect(brand).to_be_visible()
                        if empty:
                            expect(logo).to_be_visible();expect(heading).to_be_visible()
                            pane=page.locator('#agent-conversation' if agent else '.ai-empty').bounding_box()
                            for element in (logo,heading):
                                bounds=element.bounding_box()
                                assert bounds['y']>=pane['y']-1 and bounds['y']+bounds['height']<=pane['y']+pane['height']+1,('layout-resize',width,agent,bounds,pane)
                        bottom=page.locator('.ai-composer').last.evaluate('e=>e.getBoundingClientRect().bottom')
                        # Preserve the normal footer hint/gutters on layout-resize browsers.
                        assert 0<=420-bottom<=normal_bottom_gap+1,('layout-resize',width,agent,bottom,normal_bottom_gap)
                        page.set_viewport_size({'width':width,'height':height})
                        page.evaluate('qaViewport.height=innerHeight;qaViewport.offsetTop=0;qaViewport.dispatchEvent(new Event("resize"))')
                        field.blur()
                        if empty:assert logo.bounding_box()['width']==96
                    else:
                        field.fill('Desktop draft.');field.blur();expect(brand).to_be_visible()
                        if empty:expect(logo).to_be_visible();expect(heading).to_be_visible()
                        field.fill('')
                    assert page.url==url and len(posts)==before
                    assert not errors,errors
                    results.append({'width':width,'shell':'agent' if agent else 'home','state':'empty' if empty else 'saved','focus_keyboard_visibility_and_composer':'PASS'})
                context.close()
            browser.close()
        report={'result':'PASS','cases':results,'paid_calls':0,'physical_device_IME':False,'reference':'parent inspected actual video frames; local Library materialization failed'}
        (output/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:
        server.shutdown();worker.join(3);case.doCleanups()


if __name__=='__main__':main()
