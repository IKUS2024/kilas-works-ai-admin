"""Scoped loopback browser QA: navigation, language flags, edits, splits and Income."""
import os,threading,json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_finance_expense_choices as fixture
from test_finance_approved_revisions import app
import finance_service as f,finance_branches as branches,db

OUT=Path('/tmp/kilas-expense-roots-browser')
def main():
 case=fixture.ExpenseChoiceTests();case.setUp();OUT.mkdir(exist_ok=True);edits={}
 for branch in (case.personal,case.branch):
  with branches.scope(case.b,branch,case.uid):
   f.ensure_finance_defaults(case.b,actor_user_id=case.uid)
   root=f.create_category(case.b,'EXPENSE','Biaya Sewa',actor_user_id=case.uid)
   child=f.create_category(case.b,'EXPENSE','Studio rental',parent_category_id=root,actor_user_id=case.uid)
   for name in ('Fuel','Parking','Tolls','Car Rental','Public Transport','Gas','Internet','Medical Care','Medicine','Laundry'):
    f.create_category(case.b,'EXPENSE',name,parent_category_id=root,actor_user_id=case.uid)
   f.create_category(case.b,'EXPENSE','Peralatan Kecil',actor_user_id=case.uid)
   english=f.create_category(case.b,'EXPENSE','English equipment',actor_user_id=case.uid)
   f.create_category(case.b,'EXPENSE','Perlengkapan',parent_category_id=english,actor_user_id=case.uid)
   for name in ('Air','Film','Vegas travel','SewaBali Studio','Fuel','Parking','Internet'):f.create_category(case.b,'EXPENSE',name,actor_user_id=case.uid)
   account=case.pa if branch==case.personal else case.a
   edits[branch]=f.create_transaction(case.b,'EXPENSE',12345,account,child,'2026-09-10',actor_user_id=case.uid)
   income=f.list_categories(case.b,'INCOME',actor_user_id=case.uid)[0]['id']
   f.create_transaction(case.b,'INCOME',123456789012345,account,income,'2026-09-10',description='Synthetic monthly income with a long client description',notes='Synthetic explanation aligned left',actor_user_id=case.uid)
 cookie=case.client.get_cookie('session');server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
 def snap():return {t:[dict(r) for r in db.query_all('SELECT * FROM '+t)] for t in ['finance_categories','finance_category_workspace_settings','finance_category_hierarchy','finance_transactions','finance_expense_allocations','finance_recurring_expenses']}
 def check(box):
  box.locator('[data-expense-cascade]').click();panel=box.locator('[data-expense-cascade-panel]');roots=panel.locator('[data-expense-root]>[data-expense-choice-label]').all_text_contents()
  for name in ('Home/Rent','Food','Utilities','English equipment','Air','Film','Vegas travel','SewaBali Studio','Fuel','Parking','Internet'):assert name in roots,(name,roots)
  for name in ('Biaya Sewa','Peralatan Kecil','Perlengkapan','Studio rental','Tolls','Car Rental','Public Transport','Gas','Medical Care','Medicine','Laundry'):assert name not in roots
  # Main picker IDs must be actual roots, even when a root and orphan share a label.
  actual_ids=panel.locator('[data-expense-root]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.expenseRoot)')
  valid_ids=box.locator('[data-expense-parent] option').evaluate_all('(nodes)=>nodes.filter(n=>n.value&&n.value!=="__add__"&&n.dataset.pickerHidden!=="true").map(n=>n.value)')
  assert actual_ids==valid_ids
  for name in ('Fuel','Parking','Internet'):assert roots.count(name)==1
  assert not panel.locator('.expense-category-heading').count()
  for name in ('Home/Rent','Food','Utilities','Transportation'):
   button=panel.locator('[data-expense-root]').filter(has_text=name);button.click()
   if panel.is_visible():
    assert panel.locator('.expense-category-heading').all_text_contents()==[name]
    assert not panel.locator('[data-expense-root]').count()
    parent=box.locator('[data-expense-parent]').input_value()
    labels=box.locator('[data-expense-child] option').evaluate_all('(opts)=>opts.filter(o=>o.dataset.parent==="'+parent+'"&&o.dataset.pickerHidden!=="true").map(o=>o.textContent)')
    assert panel.locator('[data-expense-choice]>[data-expense-choice-label]').all_text_contents()==labels
    panel.evaluate('(e)=>e.scrollTop=e.scrollHeight');assert panel.locator('.expense-category-heading').all_text_contents()==[name]
    panel.locator('[data-expense-back]').click();assert not panel.locator('.expense-category-heading').count()
   else:box.locator('[data-expense-cascade]').click()
  panel.locator('[data-expense-root]').filter(has_text='Utilities').click();panel.locator('[data-expense-choice]').filter(has_text='Electricity').click()
  expect(box.locator('[data-expense-subcategory-display]')).to_have_text('Electricity')
  assert not box.locator('[data-expense-subcategory-display]').evaluate('(e)=>e.matches("button,a,[tabindex],[href]")')
  box.locator('[data-expense-cascade]').click();panel.locator('[data-expense-root]').filter(has_text='Parking').click()
  expect(box.locator('[data-expense-cascade]')).to_have_text('Parking');expect(box.locator('[data-expense-subcategory-display]')).to_have_text('No subcategory selected.')
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);results=[]
   for width in (320,390,768,1440):
    for branch in (case.personal,case.branch):
     for lang in ('id','en'):
      ctx=browser.new_context(viewport={'width':width,'height':1000});ctx.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':lang,'url':origin}]);page=ctx.new_page();page.set_default_timeout(5000);errors=[];writes=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:writes.append(r.url) if r.method!='GET' else None);page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
      base=origin+case.url+f'?branch_id={branch}&month=2026-09&view=transactions';page.goto(base+'&direction=EXPENSE');before=snap();page.locator('[data-transaction-direction=EXPENSE]').click();dialog=page.locator('#add-expense-dialog');check(dialog.locator('[data-expense-single]'))
      dialog.locator('[data-expense-split-toggle]').check()
      for box in dialog.locator('.expense-split-row').all():check(box)
      assert dialog.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
      page.goto(origin+case.url+f'/transactions/{edits[branch]}/edit?branch_id={branch}');box=page.locator('[data-expense-single]');expect(box.locator('[data-expense-subcategory-display]')).to_have_text('Studio rental');check(box)
      page.goto(base+'&direction=INCOME');row=page.locator('.finance-income-row');expect(row).to_have_count(1)
      for selector in ('.finance-tx-description','.finance-tx-notes','.finance-tx-meta'):assert row.locator(selector).evaluate('(e)=>getComputedStyle(e).textAlign')=='left'
      assert row.locator('.finance-tx-amount').evaluate('(e)=>getComputedStyle(e).textAlign')=='right'
      desc=row.locator('.finance-tx-description').bounding_box();amount=row.locator('.finance-tx-amount').bounding_box();assert desc['x']+desc['width']<=amount['x']+1
      for category in page.locator('.finance-ledger-category-row').all():
       assert category.locator(':scope>span').evaluate('(e)=>getComputedStyle(e).textAlign')=='left'
       assert category.locator(':scope>strong').evaluate('(e)=>getComputedStyle(e).textAlign')=='right'
       name=category.locator(':scope>span').bounding_box();money=category.locator(':scope>strong').bounding_box();assert name['x']+name['width']<=money['x']+1
       assert name['width']>=60
      assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');assert before==snap();assert not writes;assert not errors,errors
      if lang=='en' and branch==case.branch and width in (390,768,1440):page.screenshot(path=str(OUT/f'income-{width}.png'),full_page=True)
      page.goto(base+'&direction=EXPENSE');page.locator('[data-transaction-direction=EXPENSE]').click();box=page.locator('[data-expense-single]');box.locator('[data-expense-cascade]').click();box.locator('[data-expense-root]').filter(has_text='Utilities').click()
      if lang=='en' and branch==case.branch and width in (390,768,1440):page.screenshot(path=str(OUT/f'only-utilities-{width}.png'))
      results.append(dict(width=width,branch=branch,language=lang));print('PASS',results[-1],flush=True);ctx.close()
   (OUT/'report.json').write_text(json.dumps({'passed':len(results),'cases':results},indent=2));browser.close()
 finally:server.shutdown();case.doCleanups()
if __name__=='__main__':main()
