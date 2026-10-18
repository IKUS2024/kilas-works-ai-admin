import os,json,threading
from pathlib import Path
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright,expect
import test_finance_expense_entries as fixture
case=fixture.ExpenseEntryTests();case.setUp();server=make_server('127.0.0.1',0,fixture.fixture.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}';cookie=case.client.get_cookie('session');results=[]
def bounds(d):
 assert d.evaluate('(e)=>{let r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1&&r.top>=0&&r.bottom<=innerHeight+1}'),d.get_attribute('id')
 d.locator('button[type=submit]').last.scroll_into_view_if_needed();assert d.locator('button[type=submit]').last.is_visible()
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM'),args=['--no-sandbox'])
  for width in (360,768,1440):
   for lang in ('en','id'):
    ctx=browser.new_context(viewport={'width':width,'height':900},is_mobile=width<500,has_touch=width<500);ctx.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':lang,'url':origin}]);page=ctx.new_page();page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
    for scope,branch in (('business',case.branch),('personal',case.personal)):
     base=origin+case.url;qs=f'?branch_id={branch}'
     page.goto(base+qs);page.evaluate('document.fonts.ready');grid=page.locator('.finance-metric-grid');assert grid.evaluate('(e)=>getComputedStyle(e).gridTemplateColumns.split(" ").length')==(2 if width<761 else 3)
     # Long existing user-provided labels must stay bounded without changing their contents.
     page.evaluate('''()=>{document.querySelector('.finance-identity-name').textContent='Nama Bisnis Panjang untuk Keperluan Pemeriksaan Tata Letak';let o=document.querySelector('#finance-app-branch option');if(o)o.textContent='Cabang dengan nama sangat panjang untuk pemeriksaan';}''')
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
     identity=page.locator('.finance-identity-name');assert identity.evaluate('(e)=>getComputedStyle(e).textOverflow')=='ellipsis'
     page.goto(base+'/operations'+qs);page.locator('[data-finance-open="bill-add-dialog"]').click();d=page.locator('#bill-add-dialog');expect(d).to_be_visible();bounds(d);page.keyboard.press('Escape')
     page.goto(base+'/payees'+qs);page.locator('button[onclick*="payee-dialog"][onclick*="showModal"]').click();d=page.locator('#payee-dialog');expect(d).to_be_visible();bounds(d);page.keyboard.press('Escape')
     page.goto(base+'/receivables'+qs+'&section=invoices');link=page.locator('a[data-finance-write][href*="/invoices/new"]').first
     if not link.count():link=page.locator('a[data-finance-write]').filter(has_text='Invoice').first
     link.click();expect(page.locator('#invoice-editor-form')).to_be_visible();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');page.locator('#invoice-editor-form .invoice-form-actions button').last.scroll_into_view_if_needed()
     results.append({'width':width,'lang':lang,'scope':scope,'checks':'dashboard columns, long labels, Bill/Recipient modal scrolling, Invoice editor'})
    ctx.close()
  browser.close()
 print(json.dumps(results));Path('/tmp/kilas-finance-ui-polish/details.json').write_text(json.dumps(results,indent=2))
finally:server.shutdown();case.doCleanups()
