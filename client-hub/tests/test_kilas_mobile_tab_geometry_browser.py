"""Synthetic mobile keyboard geometry: labels must fit their own non-overlapping tabs."""
import json,logging,os,threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
import test_kilas_chat_models as fixture
import app


def geometry(page):
    return page.evaluate('''()=>{const nav=document.querySelector('.home-task-choices');const b=e=>{let r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height}};
    return {body:document.body.className,overflow:document.documentElement.scrollWidth>innerWidth,tabs:[...nav.querySelectorAll(':scope > button,:scope > a')].map(e=>({box:b(e),label:b(e.querySelector('span')),text:e.textContent.trim(),style:{font:getComputedStyle(e).fontSize,flex:getComputedStyle(e).flex,minHeight:getComputedStyle(e).minHeight,height:getComputedStyle(e).height,reflow:document.querySelector('.kilas-home-workspace').dataset.chatReflow},scroll:e.scrollWidth,client:e.clientWidth})),model:b(document.querySelector('.home-workspace-top')),nav:b(nav),send:b(document.querySelector('#ai-send'))}}''')


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case=fixture.RouteTests('test_catalog_auth_csrf_and_owner_isolation');case.id=lambda:'mobile-tabs';case.setUp()
    server=make_server('127.0.0.1',0,app.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_TAB_QA','/tmp/kilas-mobile-tabs'));output.mkdir(exist_ok=True);report=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/chromium')
            for managed in (True,False):
              with patch.dict(os.environ,{'KILAS_AI_MANAGED_MODELS_ENABLED':'true' if managed else 'false'}):
                for width in (390,320,1440):
                    context=browser.new_context(viewport={'width':width,'height':844},is_mobile=width<700,has_touch=width<700);cookie=case.client().get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}]);page=context.new_page();errors=[];writes=[]
                    page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:writes.append(r.url) if r.method not in ('GET','HEAD') else None);page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort());page.goto(origin+'/products/start',wait_until='networkidle')
                    def check(name):
                        result=geometry(page);assert not result['overflow'],(name,result)
                        assert len(result['tabs'])==3,(name,result)
                        for t in result['tabs']:
                            assert t['box']['height']>=44,(name,result)
                            assert t['label']['x']>=t['box']['x'] and t['label']['right']<=t['box']['right']+1,(name,result)
                            assert t['label']['y']>=t['box']['y'] and t['label']['bottom']<=t['box']['bottom']+1,(name,result)
                            assert t['scroll']<=t['client']+1,(name,result)
                        for a,b in zip(result['tabs'],result['tabs'][1:]):assert a['box']['right']<=b['box']['x']+1,(name,result)
                        assert page.locator('.home-chat-options').count()==0
                        if managed and name!='keyboard-zoom':
                            assert page.locator('.home-task-choices .home-workspace-top').count()==0
                            assert result['model']['bottom']<=result['nav']['y']+1,(name,result)
                        if 'keyboard' in name or name in ('reopened','long-labels','layout-resize','layout-reopen'):
                            assert result['send']['bottom']<=page.evaluate('visualViewport.height+visualViewport.offsetTop')+1,(name,result)
                        if name=='normal':page.screenshot(path=str(output/f'managed-{managed}-{width}-normal.png'),full_page=True)
                        report.append({'managed':managed,'width':width,'case':name,'geometry':result})
                    def long_labels():
                        page.locator('.home-task-choices').evaluate('e=>{const labels=["Percakapan AI dengan konteks panjang","Penerjemah percakapan langsung","Sulih suara untuk naskah panjang"];[...e.querySelectorAll(":scope > button,:scope > a")].forEach((b,i)=>b.querySelector("span").textContent=labels[i])}')
                    def check_scroll_access():
                        # Focus must reveal every task without scrolling the document.
                        for tab in page.locator('.home-task-choices > button,.home-task-choices > a').all():
                            tab.focus()
                            assert tab.evaluate('e=>{const r=e.getBoundingClientRect(),n=e.parentElement.getBoundingClientRect();return r.right>n.left&&r.left<n.right}')
                        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                        page.locator('.home-task-choices').evaluate('e=>e.scrollLeft=0')
                    check('normal')
                    if width<700:
                        page.locator('#ai-input').focus()
                        for phase,height,top in [('keyboard',340,18),('closed',844,0),('reopened',300,12)]:
                            page.evaluate('g=>{for(const [k,v] of Object.entries(g))Object.defineProperty(visualViewport,k,{configurable:true,value:v});visualViewport.dispatchEvent(new Event("resize"))}',{'width':width,'height':height,'scale':1,'offsetTop':top,'offsetLeft':0});check(phase)
                        page.screenshot(path=str(output/f'managed-{managed}-{width}-keyboard.png'),clip={'x':0,'y':12,'width':width,'height':300})
                        long_labels();check('long-labels')
                        page.screenshot(path=str(output/f'managed-{managed}-{width}-long.png'),clip={'x':0,'y':12,'width':width,'height':300})
                        page.evaluate('g=>{for(const [k,v] of Object.entries(g))Object.defineProperty(visualViewport,k,{configurable:true,value:v});visualViewport.dispatchEvent(new Event("resize"))}',{'width':width/2,'height':235,'scale':2,'offsetTop':12,'offsetLeft':0});check('keyboard-zoom')
                        page.evaluate('()=>{for(const k of ["width","height","scale","offsetTop","offsetLeft"])delete visualViewport[k]}')
                        for phase,height in [('layout-resize',360),('layout-close',844),('layout-reopen',340)]:
                            page.set_viewport_size({'width':width,'height':height});page.wait_for_function("Math.abs(parseFloat(document.documentElement.style.getPropertyValue('--home-viewport-height'))-visualViewport.height)<1");check(phase)
                        page.set_viewport_size({'width':width,'height':844});page.wait_for_function("Math.abs(parseFloat(document.documentElement.style.getPropertyValue('--home-viewport-height'))-visualViewport.height)<1");check('normal-with-long-labels')
                        check_scroll_access()
                    else:
                        long_labels();check('desktop-long-labels');check_scroll_access()
                    assert not errors and not writes,(errors,writes);context.close()
            browser.close()
    finally:server.shutdown();case.tearDown()
    (output/'report.json').write_text(json.dumps(report,indent=2));print('PASS:',len(report),'tab geometry cases')

if __name__=='__main__':main()
