"""Synthetic responsive checkout/payment geometry; no external requests or paid transitions."""
import json,logging,os,shutil,sys,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from test_creative_checkout import CreativeCheckoutTests
logging.getLogger('werkzeug').setLevel(logging.ERROR)
case=CreativeCheckoutTests('test_repeated_submit_and_persistence');case.id=lambda:'card-geometry';case.setUp()
server=make_server('127.0.0.1',0,case.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
output=Path(os.environ.get('KILAS_CHECKOUT_LAYOUT_OUTPUT','/tmp/checkout-card-layout'));output.mkdir(parents=True,exist_ok=True);results=[]
try:
 invoices={service:case.create('creative_'+service+'_basic')[0] for service in ('event','social')}
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
  ctx=browser.new_context();cookie=case.client.get_cookie('session');ctx.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}]);ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort());page=ctx.new_page()
  for width in (320,360,390,393,412,430,1024,1440):
   page.set_viewport_size({'width':width,'height':900})
   for service in ('event','social'):
    for state,path in [('checkout','/creative-services/checkout/creative_'+service+'_basic'),('payment',f'/creative-services/payment/{invoices[service]}')]:
     page.goto(origin+path);photo=page.locator('.selected-service img');photo.evaluate('(i)=>i.decode()');page.locator('.selected-service').screenshot(path=str(output/f'{service}-{state}-{width}-card.png'));page.screenshot(path=str(output/f'{service}-{state}-{width}.png'),full_page=True)
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,service,state)
     assert photo.get_attribute('alt').startswith('Ilustrasi ')
     metrics=page.locator('.selected-service').evaluate('''card=>{const b=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}};return {image:b(card.querySelector('img')),title:b(card.querySelector('h2')),price:b(card.querySelector('.price')),natural:[card.querySelector('img').naturalWidth,card.querySelector('img').naturalHeight],textFits:[...card.querySelectorAll('h2,.price')].every(e=>e.scrollWidth<=e.clientWidth+1),height:document.documentElement.scrollHeight}}''')
     assert metrics['natural']==[1859,846]
     assert abs(metrics['image']['width']/metrics['image']['height']-1859/846)<0.02
     assert metrics['textFits'],metrics
     if width<=600:
      assert 110<=metrics['image']['height']<=175,metrics
      assert metrics['image']['width']>=width-60,metrics
      assert metrics['title']['y']>=metrics['image']['bottom'],metrics
      limit=1160 if state=='payment' else 1200 if service=='event' else 1300
      assert metrics['height']<=limit,(width,service,state,metrics)
      targets=page.locator('.primary,.copy,.menu summary,.back,.brand,input:not([type=hidden]):not([type=file]),select,textarea').evaluate_all('(els)=>els.map(e=>({height:e.getBoundingClientRect().height,font:parseFloat(getComputedStyle(e).fontSize),tag:e.tagName}))')
      assert all(t['height']>=44 for t in targets),targets
      assert all(t['font']>=16 for t in targets if t['tag'] in ['INPUT','SELECT','TEXTAREA']),targets
     else:
      assert metrics['image']['right']<metrics['title']['x'],metrics
     if state=='payment':
      account=page.locator('#account-number')
      assert account.inner_text()=='010180016000684'
      assert account.evaluate('(e)=>e.scrollWidth<=e.getBoundingClientRect().width+1')
     m=photo.evaluate('(i)=>{let r=i.getBoundingClientRect();return {width:r.width,height:r.height,fit:getComputedStyle(i).objectFit}}');results.append(dict(viewport=width,service=service,state=state,document_height=metrics['height'],**m))
  browser.close()
 (output/'geometry.json').write_text(json.dumps(results,indent=2));print('PASS',len(results),'checkout/payment card layouts; decoded full-scene images, compact page heights and accessible controls')
finally:server.shutdown();case.tearDown()
