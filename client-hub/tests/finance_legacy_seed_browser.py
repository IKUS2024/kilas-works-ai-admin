"""Actual picker with the exact initial legacy seed; loopback synthetic data only."""
import os,threading
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_finance_legacy_seed_provenance as fixture
import finance_branches as branches,finance_service as f,repo
from auth_test_helpers import authenticate

def main():
 case=fixture.LegacySeedProvenanceTests();case.setUp();bid,owner,branch,roots,_,tx=case.legacy()
 authenticate(case.client,repo.get_user_by_id(owner));cookie=case.client.get_cookie('session')
 server=make_server('127.0.0.1',0,fixture.fixture.fixture.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}';out=Path('/tmp/kilas-legacy-seed-browser');out.mkdir(exist_ok=True)
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM','/usr/bin/chromium'),args=['--no-sandbox'])
   for width in (320,390,768,1440):
    for language in ('en','id'):
     ctx=browser.new_context(viewport={'width':width,'height':1000});ctx.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':language,'url':origin}]);page=ctx.new_page();page.set_default_timeout(5000);errors=[];writes=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:writes.append(r.url) if r.method!='GET' else None);page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
     page.goto(origin+f'/business/{bid}/finance?branch_id={branch}&view=transactions&direction=EXPENSE');page.locator('[data-transaction-direction=EXPENSE]').click();dialog=page.locator('#add-expense-dialog');single=dialog.locator('[data-expense-single]');single.locator('[data-expense-cascade]').click()
     before=case.snapshot();panel=single.locator('[data-expense-cascade-panel]');actual=panel.locator('summary strong').all_text_contents();assert actual==fixture.EXPECTED,actual
     group=panel.locator('details').first;group.locator('summary').click();group.locator('[data-expense-choice]').first.click();expect(single.locator('[data-expense-cascade]')).to_have_text('Home/Rent');expect(single.locator('[data-expense-subcategory-display]')).to_have_text('Rent')
     assert not single.locator('[data-expense-subcategory-display]').evaluate('(e)=>e.matches("a,button,[href],[tabindex]")')
     assert dialog.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1');assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
     if width in (390,768):page.screenshot(path=str(out/f'legacy-{language}-{width}.png'))
     dialog.locator('[data-expense-split-toggle]').check()
     for row in dialog.locator('.expense-split-row').all():
      row.locator('[data-expense-cascade]').click();assert row.locator('[data-expense-cascade-panel] summary strong').all_text_contents()==fixture.EXPECTED
     assert before==case.snapshot();assert not writes;assert not errors,errors
     print(f'PASS exact legacy 23-to-10, single/split, readonly, no writes, {language}, {width}',flush=True);ctx.close()
   browser.close()
 finally:server.shutdown();case.doCleanups()
if __name__=='__main__':main()
