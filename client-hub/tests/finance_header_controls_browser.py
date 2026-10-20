"""Real chrome controls on fixture routes; POSTs inspected and fulfilled locally."""
import json,threading
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_finance_expense_entries as fixture
import db


def main():
 case=fixture.ExpenseEntryTests();case.setUp();server=make_server('127.0.0.1',0,fixture.fixture.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}';cookie=case.client.get_cookie('session');results=[]
 for branch in (case.branch,case.personal):case.client.get(case.url,query_string={'branch_id':branch})
 tables=('finance_categories','finance_category_workspace_settings','finance_category_hierarchy','finance_transactions','finance_expense_allocations','finance_accounts','finance_recurring_expenses')
 def snap():return {t:[dict(r) for r in db.query_all('SELECT * FROM '+t)] for t in tables}
 before=snap()
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
   for width in (320,390,768,1440):
    for lang in ('en','id'):
     for scope,branch in (('business',case.branch),('personal',case.personal)):
      ctx=browser.new_context(viewport={'width':width,'height':1000},has_touch=width<500,is_mobile=width<500);ctx.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':lang,'url':origin}]);page=ctx.new_page();page.set_default_timeout(5000);posts=[];errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
      def route(r):
       if not r.request.url.startswith(origin):return r.abort()
       if r.request.method!='GET':
        assert r.request.url==origin+'/language' or '/finance/workspaces/' in r.request.url
        posts.append((r.request.url,parse_qs(r.request.post_data)));return r.fulfill(status=303,headers={'Location':page.url})
       return r.continue_()
      page.route('**/*',route);base=origin+case.url+f'?branch_id={branch}&view=transactions&direction=INCOME&month=2026-09&display_currency=IDR';page.goto(base)
      # Very long customer labels must fit without changing the underlying values.
      page.locator('.finance-identity-name').evaluate("e=>e.textContent='Nama Bisnis Utama Sangat Panjang untuk Pemeriksaan Header'")
      if scope=='business':page.locator('#finance-app-branch option:checked').evaluate("e=>e.textContent='Cabang Utama dengan Nama Sangat Panjang untuk Pemeriksaan'")
      assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
      assert page.locator('.finance-identity-name').evaluate('(e)=>getComputedStyle(e).textOverflow')=='ellipsis'
      if scope=='business':
       with page.expect_navigation():page.locator('#finance-app-branch').select_option(str(branch))
       q=parse_qs(urlsplit(page.url).query);assert q['branch_id']==[str(branch)] and q['month']==['2026-09'] and q['direction']==['INCOME'] and q['display_currency']==['IDR']
      period=page.locator('.finance-chrome-period');(period.locator('summary').tap() if width<500 else period.locator('summary').click());expect(period.locator('input[type=month]')).to_be_visible()
      assert period.locator('.finance-chrome-popover-panel').evaluate('(e)=>{const r=e.getBoundingClientRect();return r.x>=0&&r.right<=innerWidth}')
      with page.expect_navigation():period.locator('input[type=month]').fill('2026-08')
      q=parse_qs(urlsplit(page.url).query);assert q['branch_id']==[str(branch)] and q['month']==['2026-08'] and q['direction']==['INCOME'] and q['display_currency']==['IDR']
      profile=page.locator('.finance-identity');profile.focus();page.keyboard.press('Enter');expect(page.locator('#finance-identity-dialog')).to_be_visible();page.keyboard.press('Escape')
      language=page.locator('.finance-chrome-language');(language.locator('summary').tap() if width<500 else language.locator('summary').click());expect(language.locator('select')).to_be_visible()
      assert language.locator('.finance-chrome-popover-panel').evaluate('(e)=>{const r=e.getBoundingClientRect();return r.x>=0&&r.right<=innerWidth}')
      language.locator('select').select_option('id' if lang=='en' else 'en');language.locator('button').click();assert posts[-1][0]==origin+'/language';assert posts[-1][1]['next']==[urlsplit(page.url).path+'?'+urlsplit(page.url).query]
      assert posts[-1][1]['language']==['id' if lang=='en' else 'en'];page.keyboard.press('Escape')
      mode=page.locator('.finance-app-mode form');expected=mode.evaluate('(f)=>Object.fromEntries(new FormData(f))');mode.locator('button').click();assert '/workspaces/' in posts[-1][0];assert all(posts[-1][1][key]==[value] for key,value in expected.items());assert expected['month']=='2026-08' and expected['display_currency']=='IDR'
      assert not errors,errors;assert before==snap();results.append({'width':width,'language':lang,'scope':scope,'checks':'long labels, branch GET context, month GET context, keyboard profile, touch popovers, language POST return URL, workspace POST payload, no financial writes'});print('PASS controls',width,lang,scope,flush=True);ctx.close()
   browser.close()
  out=Path('/workspace/finance-header-evidence/controls.json');out.write_text(json.dumps(results,indent=2))
 finally:server.shutdown();case.doCleanups()
if __name__=='__main__':main()
