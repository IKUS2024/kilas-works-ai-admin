"""Replay an external read-only category snapshot through the real local picker.

Usage: python finance_expense_mapping_browser.py /path/to/category-snapshot.json
No production connections or writes; snapshots must contain category metadata only.
"""
import copy,json,sys,threading
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
import test_finance_expense_choices as fixture
import finance_category_catalog as catalog
from test_finance_approved_revisions import app


def mapped(snap,key,locale):
 rows=[dict(r) for r in snap['rows'] if r['scope_key']==key]
 settings=[dict(r,category_id=r['id'],display_name=r['name']) for r in rows]
 scope=dict(scope_key=key,workspace_type='PERSONAL' if ':' in key else 'BUSINESS',owner_user_id=int(key.split(':')[1]) if ':' in key else 9)
 policy=next((r for r in snap['versions'] if r['scope_key']==key and r['version']==4),None)
 def all_rows(sql,params=()):
  if 'FROM finance_catalog_items' in sql:return [r for r in snap['metadata'] if r['scope_key']==key]
  if 'FROM finance_category_preferences' in sql:return [r for r in snap['preferences'] if r['scope_key']==key]
  if 'FROM finance_category_workspace_settings' in sql:return settings
  if 'FROM audit_log' in sql:return snap['audit']
  raise AssertionError(sql)
 def one(sql,params=()):
  if 'FROM finance_category_catalog_versions' in sql:return policy
  if 'FROM finance_branch_workspaces' in sql:return snap['workspace']
  raise AssertionError(sql)
 with Flask(__name__).test_request_context(headers={'Cookie':'kilas_language='+locale}),patch.object(catalog.db,'query_all',side_effect=all_rows),patch.object(catalog.db,'query_one',side_effect=one):
  return [r for r in catalog.decorate(10,scope,copy.deepcopy(rows)) if r['direction']=='EXPENSE']


def main():
 snap=json.loads(Path(sys.argv[1]).read_text());cases=[(key,locale,mapped(snap,key,locale)) for key in ('PERSONAL:9','BUSINESS') for locale in ('en','id')]
 case=fixture.ExpenseChoiceTests();case.setUp();cookie=case.client.get_cookie('session');server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}';results=[]
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
   for key,locale,rows in cases:
    ctx=browser.new_context(viewport={'width':768,'height':1000});ctx.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':locale,'url':origin}]);page=ctx.new_page();posts=[];page.on('request',lambda r:posts.append(r.url) if r.method!='GET' else None);page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
    page.goto(origin+case.url+f'?branch_id={case.personal}&direction=EXPENSE&view=transactions');page.locator('[data-transaction-direction=EXPENSE]').click();box=page.locator('[data-expense-single]')
    # Replace only local DOM options with the actual scoped category mapping.
    # Real shipped JS builds the panel; no ledger/service mutation is invoked.
    box.evaluate('''(box,rows)=>{const parent=box.querySelector('[data-expense-parent]'),child=box.querySelector('[data-expense-child]');for(const select of [parent,child])select.replaceChildren(new Option('Choose',''));for(const row of rows){const option=new Option(row.display_name,String(row.id));option.dataset.pickerHidden=String(!!row.expense_picker_hidden);if(row.parent_category_id)option.dataset.parent=String(row.parent_category_id);(row.parent_category_id?child:parent).append(option);}box.refreshExpensePicker();box.openExpensePicker();}''',rows)
    panel=box.locator('[data-expense-cascade-panel]');actual=panel.locator('[data-expense-root]').evaluate_all('(nodes)=>nodes.map(n=>Number(n.dataset.expenseRoot))');expected=[r['id'] for r in rows if not r['parent_category_id'] and not r['expense_picker_hidden']];assert actual==expected,(key,locale,actual,expected);assert len(actual)==10
    labels=panel.locator('[data-expense-root]>[data-expense-choice-label]').all_text_contents();assert labels[-1]=='Misc/one-time' and labels[1]=='Food'
    parents={r['id']:r for r in rows};old_promoted=[r['id'] for r in rows if r['parent_category_id'] and not r['expense_picker_hidden'] and parents.get(r['parent_category_id'],{}).get('expense_picker_hidden')];assert not set(old_promoted)&set(actual)
    transport=next(r for r in rows if not r['parent_category_id'] and r['display_name']=='Transportation');children=[r for r in rows if r['parent_category_id']==transport['id'] and not r['expense_picker_hidden']]
    panel.locator('[data-expense-root="'+str(transport['id'])+'"]').click()
    if children:
     child_ids=panel.locator('[data-expense-choice]').evaluate_all('(nodes)=>nodes.map(n=>Number(n.dataset.expenseChoice))');assert child_ids==[r['id'] for r in children]
     assert {'Fuel','Parking','Tolls','Car Rental'}<={r['display_name'] for r in children}
    assert not posts
    result=dict(scope=key,locale=locale,root_ids=actual,root_labels=labels,removed_promoted_ids=old_promoted,canonical_transport_children=[{'id':r['id'],'name':r['display_name']} for r in children]);results.append(result);print('PASS actual mapping',key,locale,'roots',len(actual),'removed promotions',len(old_promoted),'transport children',len(children),flush=True);ctx.close()
   browser.close()
  out=Path('/tmp/kilas-expense-roots-mapping.json');out.write_text(json.dumps(results,indent=2))
 finally:server.shutdown();case.doCleanups()
if __name__=='__main__':main()
