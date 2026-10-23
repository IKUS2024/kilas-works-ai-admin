"""Chat viewport regressions: local synthetic account, no generation or external IO."""
import json,logging,threading,os,sys
from pathlib import Path

def loopback_only(event,args):
 if event=="socket.connect" and isinstance(args[1],tuple) and args[1][0] not in ("127.0.0.1","::1","localhost"):
  raise AssertionError("External transport forbidden")
sys.addaudithook(loopback_only)
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
import test_kilas_chat_models as fixture
import app
from kilas_ai import agent_store

def main():
 logging.getLogger('werkzeug').setLevel(logging.ERROR)
 case=fixture.RouteTests('test_catalog_auth_csrf_and_owner_isolation');case.id=lambda:'zoom-browser';case.setUp()
 server=make_server('127.0.0.1',0,app.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}';report=[]
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,executable_path=os.environ.get("KILAS_CHROMIUM"));cookie=case.client().get_cookie('session')
   history=agent_store.new_conversation(case.owner)
   agent_store.append(case.owner,'user','Synthetic retained history.\n'*100,conversation_id=history)
   for route in ('/products/start','/kilas-ai/agent?conversation='+str(case.conversation),'/kilas-ai/agent?conversation='+str(history)):
    for width,height in ((320,844),(390,844),(390,704),(768,844),(1440,844)):
     c=browser.new_context(viewport={'width':width,'height':height},device_scale_factor=945/390 if (width,height)==(390,704) else 1,is_mobile=width<768,has_touch=width<768);c.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}]);page=c.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort());page.goto(origin+route,wait_until='networkidle');cdp=c.new_cdp_session(page)
     def check(name,keyboard=False):
      page.wait_for_timeout(100)
      result=page.evaluate('''()=>{const v=visualViewport,root=document.querySelector('.kilas-home-workspace'),send=document.querySelector('#ai-send,#agent-chat-form button[type=submit]'),input=document.querySelector('#ai-input,#agent-message');let r=send.getBoundingClientRect(),b=document.body.getBoundingClientRect();return {width:innerWidth,visible:v.width,scale:v.scale,body:b.width,keyboard:document.body.classList.contains('home-keyboard-open'),documentOverflow:document.documentElement.scrollWidth>innerWidth+1,send:{left:r.left,right:r.right,bottom:r.bottom},inputWidth:input.getBoundingClientRect().width,rootScroll:root.scrollHeight>root.clientHeight,top:v.offsetTop,left:v.offsetLeft,height:v.height}}''')
      assert not result['documentOverflow'],(name,result)
      assert abs(result['body']-result['visible'])<1,(name,result)
      assert result['keyboard']==keyboard,(name,result)
      assert result['send']['left']>=result['left']-1 and result['send']['right']<=result['left']+result['visible']+1,(name,result)
      assert result['inputWidth']>=60,(name,result)
      assert result['send']['bottom']<=result['top']+result['height']+1,(name,result)
      if page.locator('body').evaluate('(e)=>e.classList.contains("home-chat-compact")'):
       assert not result['rootScroll'],(name,result)
       assert page.locator('#ai-input,#agent-message').evaluate('''e=>{let s=getComputedStyle(e);return s.whiteSpace==='pre'&&s.textOverflow==='ellipsis'&&parseFloat(s.lineHeight)+parseFloat(s.paddingTop)+parseFloat(s.paddingBottom)<=e.clientHeight+1}'''),('placeholder must not wrap into a clipped second line',name,result)
       assert page.locator('.home-chat-options>summary').is_visible()
       assert page.locator('.home-chat-options-panel').get_attribute('role')=='group'
       if page.locator('.agent-message').count():
        assert page.locator('#agent-conversation').evaluate('(e)=>e.scrollHeight>e.clientHeight'),'history must retain its own scroll'
      if not page.locator('body').evaluate('(e)=>e.classList.contains("home-chat-compact")'):
       assert page.locator('.home-chat-options').get_attribute('hidden') is not None
       assert page.locator('.ai-composer-actions [data-ai-call-launch]').count()==1
      assert not errors,errors
      if os.environ.get('KILAS_CHAT_ZOOM_SCREENSHOTS') and width==390 and name in ('normal','pinch-2','pinch-3'):
       folder=Path(os.environ['KILAS_CHAT_ZOOM_SCREENSHOTS']);folder.mkdir(parents=True,exist_ok=True);page.screenshot(path=str(folder/((('home' if route=='/products/start' else 'agent')+'-'+name)+'.png')))
      report.append({'route':route,'width':width,'height':height,'case':name,'keyboard':result['keyboard'],'scale':result['scale']})
     check('normal')
     # The meta viewport must preserve pinch accessibility.
     assert 'user-scalable=no' not in page.locator('meta[name=viewport]').get_attribute('content')
     if width in (390,1440):
      for scale in (2,3):
       cdp.send('Emulation.setPageScaleFactor',{'pageScaleFactor':scale});check('pinch-'+str(scale))
      if width==390:
       cdp.send('Emulation.setPageScaleFactor',{'pageScaleFactor':2})
       page.locator('.home-chat-options>summary').click()
       for trigger in page.locator('.chat-model-trigger').all():
        trigger.click();dialog=page.locator('dialog[open]');dialog.wait_for()
        assert dialog.evaluate('(e)=>{const r=e.getBoundingClientRect(),v=visualViewport;return r.left>=v.offsetLeft && r.right<=v.offsetLeft+v.width && r.top>=v.offsetTop && r.bottom<=v.offsetTop+v.height}'),'model dialog outside pinch viewport'
        dialog.locator('[data-model-close]').click()
       call=page.locator('.home-chat-options-panel [data-ai-call-launch]')
       assert call.count()==1
       call.scroll_into_view_if_needed()
       sent=[]
       page.on('request',lambda request:sent.append(request.url) if request.method=='POST' else None)
       page.locator('#ai-send,#agent-chat-form button[type=submit]').evaluate('(e)=>e.disabled=true')
       page.evaluate('window.__micRequests=0;Object.defineProperty(navigator.mediaDevices,"getUserMedia",{configurable:true,value:()=>{window.__micRequests++;return Promise.reject(Error("forbidden test microphone"))}})')
       call.click();page.wait_for_timeout(100)
       assert page.locator('#ai-call-dialog').is_visible()
       assert page.evaluate('window.__micRequests')==0 and not sent,'busy Chat must not start a call'
       page.locator('#ai-call-dialog').evaluate('(e)=>e.close()')
       page.wait_for_timeout(30)
       assert page.locator('.home-chat-options>summary').evaluate('(e)=>document.activeElement===e'),'call returns focus to visible options'
       page.locator('#ai-send,#agent-chat-form button[type=submit]').evaluate('(e)=>e.disabled=false')
       assert page.locator('.home-chat-options-panel [data-home-task=voiceover]').count()==1
       page.keyboard.press('Escape')
       assert not page.locator('.home-chat-options').evaluate('(e)=>e.open')
      cdp.send('Emulation.setPageScaleFactor',{'pageScaleFactor':1})
      # Native visual viewport APIs cannot open a physical OS keyboard in
      # headless Chromium. Feed its documented geometry, including zoom/pan.
     if width==390:
      page.locator('#ai-input,#agent-message').focus()
      for scale,keyboard_height,top,left in ((1,470,20,0),(2,235,12,30)):
       page.evaluate('''g=>{for(let [key,value] of Object.entries(g))Object.defineProperty(visualViewport,key,{configurable:true,value});visualViewport.dispatchEvent(new Event('resize'))}''',{'width':390/scale,'height':keyboard_height,'scale':scale,'offsetTop':top,'offsetLeft':left});check('keyboard-'+str(scale),True)
       for key in ('width','height','scale','offsetTop','offsetLeft'):page.evaluate('k=>delete visualViewport[k]',key)
       page.evaluate("visualViewport.dispatchEvent(new Event('resize'))")
     # Browser page zoom reflows CSS width. These widths cover the corresponding
     # 200% desktop reflow, separately from actual pinch emulation above.
     if width==1440:
      page.locator('#ai-input,#agent-message').focus()
      page.set_viewport_size({'width':720,'height':422});check('focused-desktop-reflow-200-percent')
      page.set_viewport_size({'width':1440,'height':844});check('focused-desktop-reflow-reset')
     if width in (320,768):
      page.evaluate('''()=>{for(let e of document.querySelectorAll('.kilas-home-workspace button,.kilas-home-workspace textarea,.kilas-home-workspace [data-kilas-feature]'))e.style.setProperty('font-size',parseFloat(getComputedStyle(e).fontSize)*2+'px','important')}''');check('text-200-percent')
     c.close()
   browser.close()
  print('ZOOM_REPORT '+json.dumps(report))
 finally:server.shutdown();case.doCleanups()
if __name__=='__main__':main()
