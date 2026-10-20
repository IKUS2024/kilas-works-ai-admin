"""Shared chrome only: real-route before/after body geometry/style/pixel evidence."""
import hashlib,json,os,threading,subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from jinja2 import ChoiceLoader,DictLoader
import test_finance_expense_entries as fixture
import db

OUT=Path(os.environ.get('FINANCE_HEADER_EVIDENCE','/workspace/finance-header-evidence'))
PHASE=os.environ.get('FINANCE_HEADER_PHASE','after')
STYLE_KEYS=['display','position','fontFamily','fontSize','fontWeight','lineHeight','color','backgroundColor','paddingTop','paddingRight','paddingBottom','paddingLeft','marginTop','marginRight','marginBottom','marginLeft','gap','gridTemplateColumns','gridTemplateRows','textAlign','whiteSpace','borderRadius']
SNAPSHOT=r'''(keys)=>{const marker=document.getElementById('finance-identity-dialog'),roots=[];for(let n=marker.nextElementSibling;n;n=n.nextElementSibling)if(!['SCRIPT','STYLE','LINK'].includes(n.tagName))roots.push(n);const visible=roots.filter(e=>e.getBoundingClientRect().height),top=visible[0]?.getBoundingClientRect().top||0;const round=v=>Math.round(v*100)/100;const anchored=e=>{for(let n=e;n&&n!==marker.parentElement;n=n.parentElement)if(['sticky','fixed'].includes(getComputedStyle(n).position))return true;return false};const nodes=roots.flatMap(e=>[e,...e.querySelectorAll('*')]).filter(e=>!['SCRIPT','STYLE','LINK','PATH'].includes(e.tagName));return {top,rootTags:roots.map(e=>e.tagName+'.'+e.className),text:roots.map(e=>e.textContent).join('').replace(/\s+/g,' ').trim(),nodes:nodes.map(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e),hidden=!r.width&&!r.height;return {anchored:anchored(e),tag:e.tagName,cls:typeof e.className==='string'?e.className:'svg',rect:[round(r.x),hidden?0:round(r.y-top),round(r.width),round(r.height)],styles:Object.fromEntries(keys.map(k=>[k,s[k]]))}}),forms:roots.flatMap(e=>[...(e.matches('form')?[e]:[]),...e.querySelectorAll('form')]).map(f=>({action:new URL(f.getAttribute("action")||location.href,location.href).pathname,method:f.method,fields:[...f.elements].filter(e=>!/(csrf|submission|idempotency|expected_updated)/i.test(e.name)).map(e=>[e.name,e.type,e.value,e.disabled,e.required])}))}}'''

def main():
 case=fixture.ExpenseEntryTests();case.setUp();db.execute('UPDATE businesses SET business_name=? WHERE id=?',('Bisnis Utama',case.b));OUT.mkdir(exist_ok=True)
 if PHASE=='before':
  # Render the exact original shared shell without checking out/reverting work.
  originals={name:subprocess.check_output(['git','show','59d7b050:client-hub/templates/'+name],text=True) for name in ('base.html','_finance_app_shell.html')}
  fixture.fixture.app.jinja_env.loader=ChoiceLoader([DictLoader(originals),fixture.fixture.app.jinja_env.loader]);fixture.fixture.app.jinja_env.cache.clear()
 server=make_server('127.0.0.1',0,fixture.fixture.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}';cookie=case.client.get_cookie('session');results={};issues=[]
 views={'dashboard':'','income':'&view=transactions&direction=INCOME','expenses':'&view=transactions&direction=EXPENSE','transactions':'&view=transactions','accounts':'&view=accounts','receipt':'/receipts/new','bills':'/operations','budget':'/budget','invoices':'/receivables?section=invoices','payees':'/payees','reports':'/reports','assistant':'/assistant','bank':'/bank-imports','bank-new':'/bank-imports/new','analyst':'/analyst','operator':'/operator','invoice-new':'/invoices/new','invoice-settings':'/invoices/settings'}
 baseline=json.loads((OUT/'before.json').read_text()) if PHASE=='after' else {}
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
   for width in map(int,os.environ.get('FINANCE_HEADER_WIDTHS','320,390,768,1440').split(',')):
    for lang in os.environ.get('FINANCE_HEADER_LANGUAGES','en,id').split(','):
     ctx=browser.new_context(viewport={'width':width,'height':1100},is_mobile=width<500,has_touch=width<500);ctx.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':lang,'url':origin}]);page=ctx.new_page();page.set_default_timeout(5000);errors=[];writes=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:writes.append(r.url) if r.method!='GET' else None);page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) and r.request.method=='GET' else r.abort())
     for scope,branch in (('business',case.branch),('personal',case.personal)):
      for name,suffix in views.items():
       if scope not in os.environ.get('FINANCE_HEADER_SCOPES','business,personal').split(','):continue
       if name not in os.environ.get('FINANCE_HEADER_VIEWS',','.join(views)).split(','):continue
       if lang=='id' and name not in ('dashboard','income','expenses','transactions','receipt'):continue
       path=case.url+(suffix if suffix.startswith('/') else '');query=suffix if suffix.startswith('&') else '';url=origin+path+('&' if '?' in path else '?')+f'branch_id={branch}&month=2026-09&display_currency=IDR'+query
       response=page.goto(url)
       if name in ('assistant','bank','bank-new','analyst','operator') or (scope=='personal' and name=='receipt'):
        assert response.status==404,(name,response.status);continue
       assert response.status==200,(name,response.status,url);page.evaluate('document.fonts.ready');page.evaluate('scrollTo(0,0)');page.add_style_tag(content='*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}')
       key=f'{width}-{lang}-{scope}-{name}';snapshot=page.evaluate(SNAPSHOT,STYLE_KEYS);assert snapshot['rootTags'],key
       top=snapshot.pop('top');snapshot['height']=page.evaluate('document.documentElement.scrollHeight');snapshot['bodyTop']=top
       geom=page.evaluate('''()=>({overflow:document.documentElement.scrollWidth>innerWidth+1,headerBottom:document.querySelector('.finance-context-toolbar').getBoundingClientRect().bottom,navScroll:document.querySelector('.finance-primary-navigation').scrollWidth,navWidth:document.querySelector('.finance-primary-navigation').clientWidth})''');snapshot['header']=geom
       if width in (390,768,1440) and lang=='en' and scope=='business' and name in ('income','receipt','dashboard'):
        page.screenshot(path=str(OUT/f'{PHASE}-{name}-{width}.png'),full_page=True)
        # Pixel comparison uses a fixed body rectangle, excluding its permitted vertical shift.
        body_height=page.evaluate('''()=>{const marker=document.getElementById('finance-identity-dialog');let roots=[];for(let n=marker.nextElementSibling;n;n=n.nextElementSibling)if(!['SCRIPT','STYLE','LINK'].includes(n.tagName)&&n.getBoundingClientRect().height)roots.push(n);const y=roots[0].getBoundingClientRect().top;window.__headerCaptureRoots=roots.map(e=>[e,e.style.transform]);for(const e of roots)e.style.transform=`translateY(${-1*(y-Math.floor(y))}px)`;return Math.min(800,Math.ceil(Math.max(...roots.map(e=>e.getBoundingClientRect().bottom))-Math.floor(y)))}''');page.screenshot(path=str(OUT/f'{PHASE}-body-{name}-{width}.png'),clip={'x':0,'y':int(top),'width':width,'height':body_height})
        page.evaluate('for(const [e,t] of window.__headerCaptureRoots)e.style.transform=t')
       if PHASE=='after':
        prior=baseline[key]
        assert snapshot['rootTags']==prior['rootTags'],(key,'body roots changed')
        assert snapshot['text']==prior['text'],(key,'body text changed')
        assert snapshot['forms']==prior['forms'],(key,'body forms changed')
        assert len(snapshot['nodes'])==len(prior['nodes']),(key,'body elements changed')
        for i,(a,b) in enumerate(zip(snapshot['nodes'],prior['nodes'])):
         assert a['tag']==b['tag'] and a['cls']==b['cls'] and a['styles']==b['styles'],(key,i,'body styles changed',a,b)
         assert all(abs(a['rect'][j]-b['rect'][j])<=1.1 for j in (0,2,3)) and (a['anchored'] or abs(a['rect'][1]-b['rect'][1])<=1.1),(key,i,'body geometry changed',a,b)
        assert not geom['overflow'],(key,'page overflow')
        # Every visible header control fits its own row and remains touch sized.
        for control in page.locator('.finance-chrome :is(button,a,select,input:not([type=hidden]),summary)').all():
         if not control.is_visible():continue
         r=control.bounding_box();assert r['x']>=-1 and r['x']+r['width']<=width+1 if not control.evaluate('(e)=>!!e.closest(".finance-primary-navigation")') else True,(key,'header control clips')
        # Native navigation can scroll to the first and last tab using touch or keyboard.
        nav=page.locator('.finance-primary-navigation');last=nav.locator('a').last;last.focus();assert last.evaluate('(e)=>{const p=e.parentElement.getBoundingClientRect(),r=e.getBoundingClientRect();return r.left>=p.left-1&&r.right<=p.right+1}'),(key,'last tab unreachable',last.bounding_box(),nav.bounding_box(),nav.evaluate('(e)=>[e.scrollLeft,e.scrollWidth,e.clientWidth]'));nav.locator('a').first.focus()
        language=page.locator('.finance-chrome-language');language.locator('summary').focus();page.keyboard.press('Enter');expect(language.locator('select')).to_be_visible();page.keyboard.press('Escape');expect(language.locator('select')).not_to_be_visible()
        page.locator('.finance-identity').click();expect(page.locator('#finance-identity-dialog')).to_be_visible();page.keyboard.press('Escape')
        bell=page.locator('.finance-app-bell');assert 'payment_status=unpaid' in bell.get_attribute('href') and f'branch_id={branch}' in bell.get_attribute('href')
       results[key]=snapshot
      assert not errors,(width,lang,scope,errors);assert not writes,(width,lang,scope,writes)
     print('PASS',PHASE,width,lang,flush=True);ctx.close()
   browser.close()
  (OUT/f'{PHASE}.json').write_text(json.dumps(results));print('TOTAL',len(results),flush=True)
 finally:server.shutdown();case.doCleanups()
if __name__=='__main__':main()
