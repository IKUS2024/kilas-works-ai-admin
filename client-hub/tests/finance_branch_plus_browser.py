"""Local synthetic Branch +/selection/read-only checks; no production writes or providers."""
import json,os,threading
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_finance_expense_entries as fixture
import db,finance_branches as branches

def main():
 case=fixture.ExpenseEntryTests();case.setUp();alternate=branches.create_branch(case.b,'Synthetic second branch',case.uid);server=make_server('127.0.0.1',0,fixture.fixture.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}';cookie=case.client.get_cookie('session');out=Path('/tmp/kilas-finance-branch-plus');out.mkdir(exist_ok=True);results=[];before=db.query_one('SELECT count(*) n FROM finance_branches')['n'];transactions=db.query_one('SELECT count(*) n FROM finance_transactions')['n']
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM'),args=['--no-sandbox'])
   for width in (360,390,768,1024,1440):
    for lang,label in (('en','Add Branch'),('id','Tambah Cabang')):
     ctx=browser.new_context(viewport={'width':width,'height':950},is_mobile=width<500,has_touch=width<500);ctx.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':lang,'url':origin}]);page=ctx.new_page();page.set_default_timeout(5000);errors=[];posts=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None);page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort());base=origin+case.url
     page.goto(base+f'?branch_id={case.branch}&month=2026-09');plus=page.locator('.finance-app-more');expect(plus).to_be_visible();assert plus.text_content().strip()=='';assert plus.get_attribute('aria-label')==label;assert plus.get_attribute('title')==label;assert plus.locator('svg').count()==1
     b=plus.bounding_box();assert b['width']==44 and b['height']==44
     styles=page.locator('.finance-app-branch select').evaluate('(e)=>({color:getComputedStyle(e).color,weight:getComputedStyle(e).fontWeight})');assert styles['weight']=='650';assert styles['color']!='rgb(32, 35, 41)'
     # Same existing dialog, real pointer/keyboard open/close, and existing cancel preserves input/branch.
     plus.click();d=page.locator('#branch-dialog');expect(d).to_be_visible();assert d.locator('form').first.get_attribute('action').split('?')[0].endswith('/branches');assert d.bounding_box()['width']<=width
     d.locator('details summary').first.click();d.locator('input[name=name]').first.fill('Unsaved synthetic branch');d.locator('[data-finance-close]').click();expect(d).to_be_hidden();assert not posts
     plus.focus();page.keyboard.press('Enter');expect(d).to_be_visible();page.keyboard.press('Escape');expect(d).to_be_hidden();plus.focus();page.keyboard.press('Space');expect(d).to_be_visible();page.keyboard.press('Escape');assert not posts
     if width in (390,1440) and lang=='en':page.screenshot(path=str(out/f'business-{width}.png'),full_page=True)
     with page.expect_navigation():page.locator('#finance-app-branch').select_option(str(alternate))
     assert page.locator('#finance-app-branch').input_value()==str(alternate);assert 'branch_id='+str(alternate) in page.url
     # Legacy all-branch GET still resolves one active branch; direct all-branch POST is denied.
     page.goto(base+'?branch_id=all');assert page.locator('#finance-app-branch').input_value()==str(case.branch)
     page.goto(base+f'?branch_id={case.personal}');assert page.locator('.finance-app-more').count()==0;assert page.locator('.finance-app-branch').count()==0;assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1');assert not errors
     results.append({'width':width,'language':lang,'business_plus_dialog_navigation':'PASS','personal_hidden':'PASS','legacy_all_get_resolves_one_branch':'PASS','no_posts':True});ctx.close()
   browser.close()
  denied=case.client.post(case.url+'/branches',data={'branch_id':'all','name':'Not allowed'});assert denied.status_code in (403,409),denied.status_code
  foreign=case.client.get(f'/business/{case.other}/finance');assert foreign.status_code in (403,404),foreign.status_code
  assert db.query_one('SELECT count(*) n FROM finance_branches')['n']==before;assert db.query_one('SELECT count(*) n FROM finance_transactions')['n']==transactions
  (out/'report.json').write_text(json.dumps(results,indent=2));print(json.dumps({'combinations':len(results),'read_only_post':denied.status_code,'foreign_tenant':foreign.status_code,'branch_rows_unchanged':True,'transactions_unchanged':True}))
 finally:server.shutdown();case.doCleanups()

if __name__=='__main__':main()
