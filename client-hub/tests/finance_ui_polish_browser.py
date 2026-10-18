"""Scoped presentation checks on local real Finance pages; synthetic DB, external IO blocked."""
import json,os,threading
from pathlib import Path
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright,expect
import test_finance_expense_entries as fixture


def main():
 case=fixture.ExpenseEntryTests();case.setUp();server=make_server('127.0.0.1',0,fixture.fixture.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}';cookie=case.client.get_cookie('session');out=Path('/tmp/kilas-finance-ui-polish');out.mkdir(exist_ok=True);results=[];issues=[]
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM'),args=['--no-sandbox'])
   for width in map(int,os.environ.get('KILAS_QA_WIDTHS','360,390,768,1024,1440').split(',')):
    for lang in ('en','id'):
     ctx=browser.new_context(viewport={'width':width,'height':950},is_mobile=width<500,has_touch=width<500);ctx.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':lang,'url':origin}]);page=ctx.new_page();page.set_default_timeout(5000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
     for scope,branch in (('business',case.branch),('personal',case.personal)):
      base=origin+case.url;query=f'?branch_id={branch}'
      views={'dashboard':base+query,'income':base+query+'&view=transactions&direction=INCOME','expense':base+query+'&view=transactions&direction=EXPENSE','accounts':base+query+'&view=accounts','bills':base+'/operations'+query,'invoices':base+'/receivables'+query+'&section=invoices','recipients':base+'/payees'+query}
      for name,url in views.items():
       response=page.goto(url,wait_until='load');page.evaluate('document.fonts.ready');assert response.status==200,(name,response.status)
       geom=page.evaluate('''()=>{let rect=s=>{let e=document.querySelector(s),r=e?.getBoundingClientRect();return r?{x:r.x,y:r.y,w:r.width,h:r.height,b:r.bottom}:null};let mode=rect('.finance-app-mode');let halves=[...document.querySelectorAll('.finance-app-mode>span,.finance-app-mode button')].map(e=>({h:e.getBoundingClientRect().height,w:e.getBoundingClientRect().width,font:getComputedStyle(e).fontSize}));return {overflow:document.documentElement.scrollWidth>innerWidth+1,mode,halves,branch:rect('#finance-app-branch'),month:rect('#finance-app-month'),identity:rect('.finance-identity'),title:rect('h1'),columns:getComputedStyle(document.querySelector('.finance-metrics-grid')||document.body).gridTemplateColumns}}''')
       entry={'width':width,'lang':lang,'scope':scope,'view':name,**geom};results.append(entry)
       if geom['overflow']:issues.append([width,lang,scope,name,'page overflow'])
       if os.environ.get('KILAS_QA_ASSERT_POLISH')=='1':
        assert not geom['overflow'],entry
        assert abs(geom['halves'][0]['h']-geom['halves'][1]['h'])<1,entry
        assert abs(geom['halves'][0]['w']-geom['halves'][1]['w'])<1,entry
        assert geom['mode']['h']>=44,entry
        if geom['branch'] and max(geom['branch']['y'],geom['mode']['y'])<min(geom['branch']['b'],geom['mode']['b']):assert abs(geom['branch']['b']-geom['mode']['b'])<1,entry
       if lang=='en' and scope=='business' and width in (390,768,1440) and name in ('income','dashboard','invoices'):page.screenshot(path=str(out/f'{os.environ.get("KILAS_QA_PHASE","after")}-{name}-{width}.png'),full_page=True)
       # Exercise real open/close controls without submissions; retain existing form order.
       if name in ('income','expense'):
        selector='[data-transaction-direction='+('INCOME' if name=='income' else 'EXPENSE')+']';page.locator(selector).click();dialog=page.locator('#add-transaction-dialog' if name=='income' else '#add-expense-dialog');expect(dialog).to_be_visible()
        assert dialog.evaluate('(e)=>{let r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1&&r.top>=0&&r.bottom<=innerHeight+1}'),(width,scope,name,'dialog bounds')
        assert dialog.evaluate('(e)=>getComputedStyle(e).overflowY!="hidden"||e.scrollHeight<=e.clientHeight+1'),(width,scope,name,'dialog scroll')
        # All form actions remain reachable by scrolling, not clipped by viewport.
        if name=='expense':
         assert dialog.locator('[data-expense-photo]').get_attribute('accept')=='image/jpeg,image/png,image/webp'
         if width==390 and lang=='en' and scope=='business':page.screenshot(path=str(out/'after-expense-dialog-390.png'))
        page.keyboard.press('Escape');expect(dialog).to_be_hidden()
       if name=='accounts':
        launcher=page.locator('.finance-transfer-launch button')
        if launcher.count():
         launcher.click();d=page.locator('#internal-transfer-dialog');expect(d).to_be_visible();assert d.bounding_box()['width']<=width;page.keyboard.press('Escape')
       if name=='recipients':
        launcher=page.locator('[data-payee-open]')
        if launcher.count():launcher.first.click();page.keyboard.press('Escape')
      assert not errors,(width,lang,scope,errors)
     ctx.close()
   browser.close()
  (out/'report.json').write_text(json.dumps({'pages':len(results),'dialog_checks':sum(r['view'] in ('income','expense') for r in results),'issues':issues,'results':results},indent=2));print(json.dumps({'pages':len(results),'issues':issues}))
 finally:server.shutdown();case.doCleanups()

if __name__=='__main__':main()
