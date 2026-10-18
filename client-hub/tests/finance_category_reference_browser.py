"""Actual Chromium category/forms endpoints; synthetic local ledger, no providers."""
import os,threading
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_finance_category_reference as fixture
import finance_service as f,finance_branches as branches,db

def main():
 case=fixture.CategoryReferenceTests();case.setUp();server=make_server('127.0.0.1',0,fixture.fixture.fixture.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}';cookie=case.client.get_cookie('session');output=Path('/tmp/kilas-category-reference-browser');output.mkdir(exist_ok=True)
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM'),args=['--no-sandbox'])
   for width in map(int,os.environ.get('KILAS_QA_WIDTHS','320,390,768,1440').split(',')):
    for scope in ('PERSONAL','BUSINESS'):
     branch=case.personal if scope=='PERSONAL' else case.branch;account=case.pa if scope=='PERSONAL' else case.a
     context=browser.new_context(viewport={'width':width,'height':1000});context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}]);page=context.new_page();page.set_default_timeout(5000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
     base=origin+case.url+f'?branch_id={branch}&view=transactions&direction=EXPENSE'
     with branches.scope(case.b,branch,case.uid):
      roots=f.list_categories(case.b,'EXPENSE',actor_user_id=case.uid);parent=next(v for v in roots if f.list_category_children(case.b,v['id'],actor_user_id=case.uid));kids=f.list_category_children(case.b,parent['id'],actor_user_id=case.uid);other=next(v for v in roots if v['id']!=parent['id']);otherkids=f.list_category_children(case.b,other['id'],actor_user_id=case.uid)
     page.goto(base);page.locator('[data-transaction-direction=EXPENSE]').click();dialog=page.locator('#add-expense-dialog');form=dialog.locator('[data-expense-form]');single=form.locator('[data-expense-single]');a=single.locator('[data-expense-parent]');b=single.locator('[data-expense-child]')
     a.select_option(str(parent['id']));b.select_option(str(kids[0]['id']));assert b.bounding_box()['y']>a.bounding_box()['y'];a.select_option(str(other['id']));assert b.input_value()==''
     assert b.evaluate('(e)=>Array.from(e.options).filter(o=>o.value&&o.value!=="__add__"&&!o.disabled).every(o=>o.dataset.parent===e.closest("[data-expense-picker]").querySelector("[data-expense-parent]").value)')
     form.locator('[data-expense-split-toggle]').check();rows=form.locator('.expense-split-row')
     for index,(root,children,amount) in enumerate(((parent,kids,'50.00'),(other,otherkids,'50.01'))):
      row=rows.nth(index);row.locator('[data-expense-parent]').select_option(str(root['id']));child=row.locator('[data-expense-child]');assert child.bounding_box()['y']>row.locator('[data-expense-parent]').bounding_box()['y']
      if children:child.select_option(str(children[0]['id']))
      row.locator('[name=split_amount]').fill(amount)
     form.locator('[name=account_id]').select_option(str(account));form.locator('[name=amount]').fill('100.01');form.locator('[name=occurred_on]').fill('2025-01-01');form.locator('[name=notes]').fill('Synthetic category reference expense')
     assert dialog.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
     tx=None
     if width==320:
      before=db.query_one('SELECT count(*) AS n FROM finance_transactions')['n']
      with page.expect_navigation():dialog.get_by_role('button',name='Save',exact=True).click()
      assert db.query_one('SELECT count(*) AS n FROM finance_transactions')['n']==before+1;tx=db.query_one('SELECT id FROM finance_transactions ORDER BY id DESC LIMIT 1')['id']
      page.goto(origin+case.url+f'/transactions/{tx}/edit?branch_id={branch}');expect(page.locator('[data-expense-split-toggle]')).to_be_checked();edit=page.locator('[data-expense-form]');row=edit.locator('.expense-split-row').first;assert row.locator('[data-expense-child]').input_value()==str(kids[0]['id']);row.locator('[data-expense-parent]').select_option(str(other['id']));assert row.locator('[data-expense-child]').input_value()==''
     else:dialog.get_by_role('button',name='Cancel',exact=True).click()
     def manager():
      page.goto(base);page.locator('[data-transaction-direction=EXPENSE]').click();page.get_by_role('link',name='Manage categories',exact=True).click();box=page.locator('#category-dialog');expect(box).to_be_visible();return box
     box=manager();section=box.locator('[data-category-direction-section=EXPENSE]');root=section.locator('[data-category-group="'+str(parent['id'])+'"]');box.locator('[data-category-list-edit]').click();assert root.locator('[data-category-archive]').first.is_visible();assert box.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
     page.screenshot(path=str(output/f'categories-{scope.lower()}-{width}.png'))
     root.locator(':scope > summary [data-category-edit-popup]').click();editor=page.locator('#category-editor-dialog');edit=editor.locator('[data-category-edit-form]');expect(editor).to_be_visible();assert edit.locator('input[name=icon_key]').count()==18;edit.locator('label:has(input[value=care])').click();assert edit.locator('input[value=care]').is_checked();assert editor.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1');page.screenshot(path=str(output/f'editor-{scope.lower()}-{width}.png'))
     if width==320:
      edit.locator('[name=name]').fill('Customer root '+scope)
      with page.expect_navigation():edit.get_by_role('button',name='Save Changes',exact=True).click()
      assert db.query_one('SELECT icon_key FROM finance_category_preferences WHERE business_id=? AND category_id=?',(case.b,parent['id']))['icon_key']=='care'
      box=manager();box.locator('[data-category-list-edit]').click();section=box.locator('[data-category-direction-section=EXPENSE]');root=section.locator('[data-category-group="'+str(parent['id'])+'"]')
      with page.expect_response(lambda r:'/categories?' in r.url and r.request.method=='POST') as response:root.locator(':scope > summary [data-category-move=down]').click()
      assert response.value.status==200
      root.locator(':scope > summary .finance-category-tree-head-copy').click();root.locator('[data-category-add-child-popup]').click();create=editor.locator('[data-category-create-form]');expect(editor).to_be_visible();assert create.locator('[name=parent_category_id]').input_value()==str(parent['id']);create.locator('[name=name]').fill('Synthetic child '+scope);create.locator('label:has(input[value=water])').click()
      with page.expect_navigation():create.locator('[data-category-editor-submit]').click()
      new=db.query_one('SELECT s.category_id FROM finance_category_workspace_settings s WHERE s.business_id=? AND s.display_name=?',(case.b,'Synthetic child '+scope))['category_id'];assert db.query_one('SELECT parent_category_id FROM finance_category_hierarchy WHERE child_category_id=?',(new,))['parent_category_id']==parent['id']
      box=manager();box.locator('[data-category-list-edit]').click();root=box.locator('[data-category-group="'+str(parent['id'])+'"]');root.locator(':scope > summary .finance-category-tree-head-copy').click();child=root.locator('[data-category-row][data-category-id="'+str(new)+'"]');child.locator('[data-category-edit-popup]').click();edit.locator('[name=name]').fill('Edited child '+scope)
      with page.expect_navigation():edit.get_by_role('button',name='Save Changes',exact=True).click()
      box=manager();box.locator('[data-category-list-edit]').click();root=box.locator('[data-category-group="'+str(parent['id'])+'"]');root.locator(':scope > summary .finance-category-tree-head-copy').click();used=root.locator('[data-category-row][data-category-id="'+str(kids[0]['id'])+'"]');page.once('dialog',lambda d:d.accept());used.locator('[data-category-archive]').click();page.wait_for_load_state('networkidle')
      assert not db.query_one('SELECT is_active FROM finance_category_workspace_settings WHERE business_id=? AND category_id=? AND scope_key=?',(case.b,kids[0]['id'],'PERSONAL:'+str(case.uid) if scope=='PERSONAL' else 'BUSINESS'))['is_active'];assert db.query_one('SELECT parent_category_id FROM finance_category_hierarchy WHERE child_category_id=?',(kids[0]['id'],))['parent_category_id']==parent['id']
      page.goto(origin+case.url+f'/transactions/{tx}/edit?branch_id={branch}');expect(page.locator('[data-expense-split-toggle]')).to_be_checked();assert page.locator('.expense-split-row').first.locator('[data-expense-child]').input_value()==str(kids[0]['id']);page.locator('[name=notes]').fill('Edited archived category note')
      with page.expect_navigation():page.get_by_role('button',name='Save',exact=True).click()
      assert db.query_one('SELECT notes FROM finance_transactions WHERE id=?',(tx,))['notes']=='Edited archived category note';assert db.query_one('SELECT count(*) AS n FROM finance_transactions')['n']==before+1
     else:editor.get_by_role('button',name='Cancel',exact=True).click()
     assert not errors,errors;print(f'PASS {scope} {width}: Add/Edit/Split dependencies, management/icon/order/archive/save-or-cancel, no overflow',flush=True);context.close()
   browser.close()
 finally:server.shutdown();case.doCleanups()
if __name__=='__main__':main()
