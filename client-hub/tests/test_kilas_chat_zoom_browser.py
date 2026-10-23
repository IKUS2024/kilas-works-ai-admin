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

def main():
 logging.getLogger('werkzeug').setLevel(logging.ERROR)
 case=fixture.RouteTests('test_catalog_auth_csrf_and_owner_isolation');case.id=lambda:'zoom-browser';case.setUp()
 server=make_server('127.0.0.1',0,app.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}';report=[]
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True);cookie=case.client().get_cookie('session')
   for route in ('/products/start','/kilas-ai/agent?conversation='+str(case.conversation)):
    for width in (320,390,768,1440):
     c=browser.new_context(viewport={'width':width,'height':844},is_mobile=width<768,has_touch=width<768);c.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}]);page=c.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort());page.goto(origin+route,wait_until='networkidle');cdp=c.new_cdp_session(page)
     def check(name,keyboard=False):
      page.wait_for_timeout(100)
      result=page.evaluate('''()=>{const v=visualViewport,root=document.querySelector('.kilas-home-workspace'),send=document.querySelector('#ai-send,#agent-chat-form button[type=submit]'),input=document.querySelector('#ai-input,#agent-message');let r=send.getBoundingClientRect(),b=document.body.getBoundingClientRect();return {width:innerWidth,visible:v.width,scale:v.scale,body:b.width,keyboard:document.body.classList.contains('home-keyboard-open'),documentOverflow:document.documentElement.scrollWidth>innerWidth+1,send:{left:r.left,right:r.right,bottom:r.bottom},inputWidth:input.getBoundingClientRect().width,rootScroll:root.scrollHeight>root.clientHeight,top:v.offsetTop,left:v.offsetLeft,height:v.height}}''')
      assert not result['documentOverflow'],(name,result)
      assert abs(result['body']-result['visible'])<1,(name,result)
      assert result['keyboard']==keyboard,(name,result)
      assert result['send']['left']>=result['left']-1 and result['send']['right']<=result['left']+result['visible']+1,(name,result)
      assert result['inputWidth']>=60,(name,result)
      # If every control cannot fit vertically at extreme magnification, the
      # Chat region must scroll, rather than clipping the composer permanently.
      if result['send']['bottom']>result['top']+result['height']+1:
       assert result['rootScroll'],(name,result)
       page.locator('#ai-send,#agent-chat-form button[type=submit]').scroll_into_view_if_needed()
       assert page.locator('#ai-send,#agent-chat-form button[type=submit]').evaluate('(e)=>{let r=e.getBoundingClientRect(),v=visualViewport;return r.bottom<=v.offsetTop+v.height+1}'),(name,result)
      assert not errors,errors
      if os.environ.get('KILAS_CHAT_ZOOM_SCREENSHOTS') and width==390 and name in ('normal','pinch-2','pinch-3'):
       folder=Path(os.environ['KILAS_CHAT_ZOOM_SCREENSHOTS']);folder.mkdir(parents=True,exist_ok=True);page.screenshot(path=str(folder/((('home' if route=='/products/start' else 'agent')+'-'+name)+'.png')))
      report.append({'route':route,'width':width,'case':name,'keyboard':result['keyboard'],'scale':result['scale']})
     check('normal')
     # The meta viewport must preserve pinch accessibility.
     assert 'user-scalable=no' not in page.locator('meta[name=viewport]').get_attribute('content')
     if width in (390,1440):
      for scale in (2,3):
       cdp.send('Emulation.setPageScaleFactor',{'pageScaleFactor':scale});check('pinch-'+str(scale))
      cdp.send('Emulation.setPageScaleFactor',{'pageScaleFactor':1})
      # Native visual viewport APIs cannot open a physical OS keyboard in
      # headless Chromium. Feed its documented geometry, including zoom/pan.
     if width==390:
      page.locator('#ai-input,#agent-message').focus()
      for scale,height,top,left in ((1,470,20,0),(2,235,12,30)):
       page.evaluate('''g=>{for(let [key,value] of Object.entries(g))Object.defineProperty(visualViewport,key,{configurable:true,value});visualViewport.dispatchEvent(new Event('resize'))}''',{'width':390/scale,'height':height,'scale':scale,'offsetTop':top,'offsetLeft':left});check('keyboard-'+str(scale),True)
       for key in ('width','height','scale','offsetTop','offsetLeft'):page.evaluate('k=>delete visualViewport[k]',key)
       page.evaluate("visualViewport.dispatchEvent(new Event('resize'))")
     # Browser page zoom reflows CSS width. These widths cover the corresponding
     # 200% desktop reflow, separately from actual pinch emulation above.
     if width in (320,768):
      page.evaluate('''()=>{for(let e of document.querySelectorAll('.kilas-home-workspace button,.kilas-home-workspace textarea,.kilas-home-workspace [data-kilas-feature]'))e.style.setProperty('font-size',parseFloat(getComputedStyle(e).fontSize)*2+'px','important')}''');check('text-200-percent')
     c.close()
   browser.close()
  print('ZOOM_REPORT '+json.dumps(report))
 finally:server.shutdown();case.doCleanups()
if __name__=='__main__':main()
