"""Real Chromium, disposable Flask/SQLite, synthetic audio and mocked relay only."""
import base64,json,logging,math,os,re,shutil,struct,threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_interpreter as fixture
import ui_i18n

SOURCE='أين المحطة؟ <script>alert(1)</script>'
REPLY='Where is the station? <b>literal text</b>'
MIC="""window.micRequests=0;window.micStops=0;window.mockPermission='granted';
navigator.mediaDevices.getUserMedia=async()=>{
 window.micRequests++;
 if(window.mockPermission==='denied')throw new DOMException('denied','NotAllowedError');
 const ctx=new AudioContext(),osc=ctx.createOscillator(),out=ctx.createMediaStreamDestination();
 osc.frequency.value=220;osc.connect(out);osc.start();
 for(const track of out.stream.getTracks()){const stop=track.stop.bind(track);track.stop=()=>{window.micStops++;stop();osc.stop();ctx.close();};}
 return out.stream;
};"""
def contrast(a,b):
 def lum(rgb):
  s=[v/255 for v in rgb];s=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in s]
  return sum(v*w for v,w in zip(s,(.2126,.7152,.0722)))
 x,y=sorted((lum(a),lum(b)));return (y+.05)/(x+.05)

def main():
 logging.getLogger('werkzeug').setLevel(logging.ERROR)
 case=fixture.InterpreterTests();case.setUp()
 server=make_server('127.0.0.1',0,case.client.application,threaded=True)
 threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
 output=Path(os.environ.get('KILAS_INTERPRETER_HARDENED_SHOTS','/tmp/kilas-interpreter-hardened'));output.mkdir(exist_ok=True)
 evidence=[]
 try:
  with case.enabled(),patch.dict(os.environ,{'KILAS_COPILOT_VISIBLE':'true'}),sync_playwright() as pw:
   executable=os.environ.get('KILAS_QA_CHROMIUM') or shutil.which('chromium')
   browser=pw.chromium.launch(**({'executable_path':executable} if executable else {}),headless=True,args=['--no-sandbox'])
   cookie=case.client.get_cookie('session')
   for locale in ('en','id','es','zh'):
    def copy(key):
     with case.client.application.test_request_context(headers={'Cookie':'kilas_language='+locale}):return ui_i18n.translate(key)
    for width,height in ((360,780),(393,852),(768,1024),(1440,1000)):
     context=browser.new_context(viewport={'width':width,'height':height})
     context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':locale,'url':origin}])
     context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
     context.add_init_script(MIC);page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
     mode=['normal'];starts=[];ends=[]
     audio=b''.join(struct.pack('<h',int(8000*math.sin(i/12))) for i in range(24000))
     frames=[{'index':0,'type':'original','text':SOURCE},{'index':1,'type':'text','text':REPLY}]
     for at in range(0,len(audio),9600):frames.append({'index':len(frames),'type':'audio','pcm':base64.b64encode(audio[at:at+9600]).decode()})
     frames.append({'index':len(frames),'type':'turn_complete'})
     def relay(route):
      request=route.request;path=request.url.split('?')[0]
      if path.endswith('/end'):ends.append(path);return route.fulfill(json={'state':'CLOSED'})
      if mode[0]=='auth':return route.fulfill(status=401,content_type='text/html',body='<h1>Authentication required</h1>')
      if path.endswith('/readiness'):
       if mode[0]=='network':return route.abort('failed')
       return route.fulfill(json={'available':mode[0]!='unavailable','reason':'call_unavailable'})
      if '/chunks/' in path:return route.fulfill(json={'accepted_index':int(path.rsplit('/',1)[1])})
      if request.method=='POST':
       starts.append(request.post_data);return route.fulfill(status=202,json={'call_id':path.rsplit('/',1)[1],'state':'CONNECTING'})
      from urllib.parse import parse_qs,urlsplit
      after=int(parse_qs(urlsplit(request.url).query).get('after',['0'])[0])
      items=frames[after:]
      return route.fulfill(json={'state':'LISTENING','frames':items,'next_index':after+len(items),'total_frames':len(frames)})
     page.route('**/kilas-translator/interpreter/**',relay)
     page.goto(origin+'/kilas-translator/interpreter',wait_until='networkidle')
     expect(page.locator('#interpreter-start')).to_have_text(copy('Lanjut'))
     expect(page.locator('.interpreter-setup-description')).to_have_text(copy('Terjemahkan percakapan lewat suara.'))
     assert page.locator('#interpreter-language-a option').count()==99
     assert 'AI Chat' not in page.locator('body').inner_text()
     assert page.locator('[data-chat-sidebar]').count()==0
     assert page.evaluate('micRequests')==0
     if width in (393,1440):page.screenshot(path=str(output/f'setup-{locale}-{width}.png'),full_page=True)
     page.locator('#interpreter-start').click()
     expect(page.locator('#interpreter-error')).to_have_text(copy('Setujui pemrosesan ucapan terlebih dahulu.'))
     assert page.evaluate('micRequests')==0 and not starts
     page.locator('#interpreter-language-a').select_option('ar')
     page.locator('#interpreter-language-b').select_option('en')
     page.locator('#interpreter-swap').click();page.locator('#interpreter-swap').click()
     assert page.locator('#interpreter-language-a').input_value()=='ar'
     assert page.locator('#interpreter-language-b').input_value()=='en'
     styles=page.evaluate("""()=>Object.fromEntries(['#interpreter-start','.interpreter-setup-description'].map(s=>{const e=document.querySelector(s),c=getComputedStyle(e);return [s,{color:c.color,background:c.backgroundColor,image:c.backgroundImage,size:c.fontSize}]}))""")
     assert styles['#interpreter-start']['image']=='none',styles
     rgb=lambda value:tuple(map(float,re.findall(r'[\d.]+',value)[:3]))
     assert contrast(rgb(styles['#interpreter-start']['color']),rgb(styles['#interpreter-start']['background']))>=4.5,styles
     assert contrast(rgb(styles['.interpreter-setup-description']['color']),(255,255,255))>=4.5,styles
     page.locator('#interpreter-consent').check();page.locator('#interpreter-start').dblclick()
     assert page.evaluate('micRequests')==0 and not starts
     assert not page.locator('#interpreter-transcript').get_attribute('open')
     page.locator('#interpreter-left').click()
     page.wait_for_function("document.querySelector('#interpreter-state').dataset.state==='speaking'")
     expect(page.locator('#interpreter-state')).to_have_text(copy('Terjemahan diputar. Tunggu giliran.'))
     assert len(starts)==1 and page.evaluate('micRequests')==1
     page.locator('#interpreter-left').click();assert len(starts)==1
     expect(page.locator('#interpreter-caption')).to_have_text(REPLY)
     assert not page.locator('#interpreter-caption').is_visible()
     page.locator('#interpreter-transcript > summary').click()
     expect(page.locator('#interpreter-original')).to_have_text(SOURCE)
     expect(page.locator('#interpreter-caption')).to_have_text(REPLY)
     assert page.locator('#interpreter-original script,#interpreter-caption b').count()==0
     assert page.locator('#interpreter-original').get_attribute('dir')=='auto'
     assert page.locator('#interpreter-original').get_attribute('lang')=='ar'
     assert page.locator('#interpreter-original').evaluate("e=>getComputedStyle(e).direction")=='rtl'
     assert page.locator('#interpreter-caption').get_attribute('lang')=='en'
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
     page.wait_for_function("document.querySelector('#interpreter-state').dataset.state==='listening'")
     expect(page.locator('#interpreter-state')).to_have_text(copy('Mendengarkan'))
     if width in (393,1440):page.screenshot(path=str(output/f'transcript-{locale}-{width}.png'),full_page=True)
     assert not page.evaluate("(s)=>Object.values(localStorage).some(v=>v.includes(s))",REPLY)
     latest_reply=REPLY
     if width==393:
      second_source='لا، خمسة عشر وليس خمسين.'
      latest_reply='No, fifteen, not fifty.'
      frames.extend([{'index':len(frames),'type':'original','text':second_source},{'index':len(frames)+1,'type':'text','text':latest_reply}])
      expect(page.locator('#interpreter-original')).to_have_text(second_source)
      expect(page.locator('#interpreter-caption')).to_have_text(latest_reply)
     mode[0]='auth'
     expect(page.locator('#interpreter-login')).to_be_visible()
     expect(page.locator('#interpreter-state')).to_have_text(copy('Sesi akun berakhir. Masuk kembali.'))
     expect(page.locator('#interpreter-left')).to_be_disabled()
     assert page.evaluate('micStops')>=1 and len(starts)==1
     expect(page.locator('#interpreter-caption')).to_have_text(latest_reply)
     assert page.locator('#interpreter-login').get_attribute('href')=='/login'
     expect(page.locator('#interpreter-login')).to_be_focused()
     if width==393:
      # Fixed off-screen skip links can enter a scrolled full-page screenshot.
      # Keep keyboard access real; normalize scroll only for ordinary pointer QA.
      skip=page.locator('.premium-skip')
      rect=skip.bounding_box();assert rect['y']+rect['height']<=0
      skip.focus();expect(skip).to_be_focused()
      assert skip.bounding_box()['y']>=0
      page.locator('#interpreter-login').focus()
      rect=skip.bounding_box();assert rect['y']+rect['height']<=0
      page.evaluate("()=>{document.activeElement.blur();window.scrollTo(0,0);}")
      page.screenshot(path=str(output/f'auth-{locale}-{width}.png'),full_page=True)
     page.locator('#interpreter-end').click()
     expect(page.locator('#interpreter-start')).to_be_disabled()
     assert page.locator('#interpreter-original').text_content()=='' and page.locator('#interpreter-caption').text_content()==''
     if width==393:
      for failure,key in (('unavailable','Translator sedang tidak tersedia.'),('network','Koneksi terputus. Pilih arah untuk mulai lagi.'),('permission','Izinkan mikrofon di browser.'),('audio','Audio belum siap. Izinkan audio browser, lalu pilih arah lagi.')):
       mode[0]=failure;before=len(starts);page.reload(wait_until='networkidle')
       assert not page.locator('#interpreter-consent').is_checked() and page.evaluate('micRequests')==0
       page.locator('#interpreter-consent').check();page.locator('#interpreter-start').click()
       if failure=='permission':page.evaluate("window.mockPermission='denied'")
       if failure=='audio':page.evaluate("()=>{AudioContext.prototype.resume=async()=>{throw new Error('synthetic audio failure')};}")
       page.locator('#interpreter-left').click()
       expect(page.locator('#interpreter-state')).to_have_text(copy(key))
       assert len(starts)==before
       expect(page.locator('#interpreter-left')).to_be_enabled()
       page.locator('#interpreter-end').click()
      # A real UI locale Apply/reload preserves conversation languages and never consent/audio.
      mode[0]='normal';page.reload(wait_until='networkidle')
      page.locator('.kilas-profile-menu > summary').first.click()
      page.locator('.kilas-profile-language > summary').first.click()
      changed='id' if locale!='id' else 'en'
      page.locator('form[action="/language"] select').first.select_option(changed)
      with page.expect_navigation():page.locator('form[action="/language"] button').first.click()
      assert page.locator('html').get_attribute('lang')==changed
      assert page.locator('#interpreter-language-a').input_value()=='ar' and page.locator('#interpreter-language-b').input_value()=='en'
      assert not page.locator('#interpreter-consent').is_checked() and page.evaluate('micRequests')==0
     assert not errors,errors
     evidence.append({'locale':locale,'width':width,'result':'PASS','paid_calls':0,'hardware':'Chromium synthetic device','admissions':len(starts),'end_requests':len(ends)})
     print(json.dumps(evidence[-1]),flush=True);context.close()
   browser.close()
  (output/'verification.json').write_text(json.dumps(evidence,indent=2))
 finally:server.shutdown();case.doCleanups()
if __name__=='__main__':main()

