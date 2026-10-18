"""Real local browser, synthetic financial data only; no external HTTP/providers."""
import os,threading,io,json
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_finance_purchase_plans as fixture
import finance_service as f,finance_branches as branches,db

def main():
 case=fixture.PurchasePlanTests('test_plan_never_debits_purchase_payments_allocate_once_and_retry_is_atomic');case.setUp()
 app=fixture.fixture.fixture.app;server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}';cookie=case.client.get_cookie('session')
 output=Path('/tmp/kilas-finance-full-browser');output.mkdir(exist_ok=True)
 raw=io.BytesIO();Image.new('RGB',(12,12),'white').save(raw,'JPEG')
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM'),args=['--no-sandbox'])
   for width in tuple(map(int,os.environ.get('KILAS_QA_WIDTHS','320,390,768,1440').split(','))):
    for scope in os.environ.get('KILAS_QA_SCOPES','BUSINESS,PERSONAL').split(','):
     branch=case.branch if scope=='BUSINESS' else case.personal;account=case.a if scope=='BUSINESS' else case.pa
     context=browser.new_context(viewport={'width':width,'height':1000},accept_downloads=True);context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}]);page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
     base=origin+case.url+f'?branch_id={branch}&month=2026-09'
     page.goto(base);cards=page.locator('.finance-metric-grid>[data-finance-metric]');assert cards.count()==6;assert cards.evaluate_all('(els)=>els.map(e=>e.dataset.financeMetric)')==['income','expense','account','bill','invoice','people']
     boxes=[v.bounding_box() for v in cards.all()];cols=2 if width<760 else 3;assert boxes[0]['y']==boxes[cols-1]['y'];assert boxes[cols]['y']>boxes[0]['y']
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.screenshot(path=str(output/f'dashboard-{scope.lower()}-{width}.png'))
     page.goto(base+'&view=transactions&direction=EXPENSE');page.locator('[data-finance-instant-filter]').select_option(str(account));page.wait_for_url('**account_id='+str(account)+'*');assert page.locator('[data-finance-instant-filter]').input_value()==str(account)
     page.locator('[data-transaction-direction=EXPENSE]').click();dialog=page.locator('#add-expense-dialog');form=dialog.locator('[data-expense-form]');expect(dialog).to_be_visible();assert form.locator('[name=description]').get_attribute('type')=='hidden'
     if width==390:
      # Bottom actions use the real scoped AJAX/CSRF endpoint, not test inserts.
      single=form.locator('[data-expense-single]');page.once('dialog',lambda d:d.accept('Synthetic new category'))
      single.locator('[data-expense-parent]').select_option('__add__');expect(single.locator('[data-expense-parent] option:checked')).to_have_text('Synthetic new category')
      page.once('dialog',lambda d:d.accept('Synthetic new subcategory'))
      single.locator('[data-expense-child]').select_option('__add__');expect(single.locator('[data-expense-child] option:checked')).to_have_text('Synthetic new subcategory')
      parent_id=single.locator('[data-expense-parent]').input_value();child_id=single.locator('[data-expense-child]').input_value()
      assert db.query_one('SELECT parent_category_id FROM finance_category_hierarchy WHERE child_category_id=?',(child_id,))['parent_category_id']==int(parent_id)
     toggle=form.locator('[data-expense-split-toggle]');parent=form.locator('[data-expense-single] [data-expense-parent]');assert toggle.bounding_box()['y']<parent.bounding_box()['y'];toggle.check();expect(form.locator('[data-expense-single]')).to_be_hidden()
     with branches.scope(case.b,branch,case.uid):
      cats=f.list_categories(case.b,'EXPENSE',include_children=True,actor_user_id=case.uid);leaves=[v for v in cats if not f.list_category_children(case.b,v['id'],actor_user_id=case.uid)]
     rows=form.locator('.expense-split-row')
     for index,cat in enumerate(leaves[:2]):
      row=rows.nth(index);row.locator('[data-expense-parent]').select_option(str(cat.get('parent_category_id') or cat['id']));child=row.locator('[data-expense-child]');assert child.bounding_box()['y']>row.locator('[data-expense-parent]').bounding_box()['y']
      if cat.get('parent_category_id'):child.select_option(str(cat['id']))
      row.locator('[name=split_amount]').fill('50.00' if index==0 else '50.01')
     form.locator('[name=amount]').fill('100.01');form.locator('[name=occurred_on]').fill('2025-08-10');form.locator('[name=account_id]').select_option(str(account));form.locator('[name=notes]').fill('Synthetic installment purchase');form.locator('[name=receipt]').set_input_files({'name':'synthetic.jpg','mimeType':'image/jpeg','buffer':raw.getvalue()})
     expect(form.locator('[data-installment-fields]')).to_be_hidden();form.locator('.expense-additional>summary').click();form.locator('[data-installment-toggle]').check();expect(form.locator('[data-installment-fields]')).to_be_visible();form.locator('[name=installment_duration]').fill('1');form.locator('[name=installment_unit]').select_option('YEARS');assert form.locator('[name=installment_count]').input_value()=='12'
     form.locator('[name=installment_first_date]').fill('2025-09-30');form.locator('[name=installment_frequency]').select_option('CUSTOM');form.locator('[name=installment_dates]').fill('2025-09-30\n2025-10-31');assert form.locator('[name=installment_count]').input_value()=='2';form.locator('[name=installment_frequency]').select_option('MONTHLY');assert form.locator('[name=installment_count]').input_value()=='12'
     assert dialog.evaluate('e=>e.scrollWidth<=e.clientWidth+1');page.screenshot(path=str(output/f'installment-{scope.lower()}-{width}.png'))
     if width==320:
      before=db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n']
      with page.expect_navigation():dialog.get_by_role('button',name='Save',exact=True).click()
      assert db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n']==before
      plan=db.query_one('SELECT id FROM finance_installment_plans ORDER BY id DESC LIMIT 1')['id'];items=case.items(plan);assert len(items)==12;assert sum(v['amount_minor'] for v in items)==10001;assert items[-1]['due_on']=='2026-08-31'
      page.goto(origin+case.url+f'/installments/{plan}?branch_id={branch}');expect(page.get_by_role('heading',name='Installment plan',exact=True)).to_be_visible()
      with page.expect_download() as download:page.get_by_role('link',name='View receipt',exact=True).click()
      assert Path(download.value.path()).read_bytes()==raw.getvalue()
      # Existing Bills UI, not a hidden ledger write, records the first payment.
      page.goto(origin+case.url+f'/operations?branch_id={branch}&month=2025-09&view=list&payment_status=unpaid');page.locator('[data-finance-open="bill-pay-list-'+str(items[0]['recurring_id'])+'-2025-09-30"]').click();pay=page.locator('#bill-pay-list-'+str(items[0]['recurring_id'])+'-2025-09-30');pay.locator('[name=account_id]').select_option(str(account));pay.locator('[name=paid_on]').fill('2025-09-30')
      with page.expect_navigation():pay.locator('button[type=submit]').click()
      assert db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n']==before+1
     else:dialog.get_by_role('button',name='Cancel',exact=True).click();expect(dialog).to_be_hidden()
     if width==390:
      before=db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n']
      page.goto(origin+case.url+f'/operations?branch_id={branch}&month=2026-10&view=recurring');page.locator('[data-finance-open="bill-add-dialog"]').click();bill=page.locator('#bill-add-dialog');bill.locator('[name=name]').fill('Synthetic monthly bill '+scope);bill.locator('[name=amount]').fill('100.01');bill.locator('[name=cadence]').select_option('MONTHLY')
      cat=leaves[0];parent_id=cat.get('parent_category_id') or cat['id'];bill.locator('[data-bill-category-picker]>summary').click();bill.locator('[data-category-value="'+str(parent_id)+'"]').click()
      if cat.get('parent_category_id'):bill.locator('[name=subcategory_id]').select_option(str(cat['id']))
      bill.locator('[name=next_due_on]').fill('2026-10-31');bill.locator('[name=begin_next_month]').check();assert bill.locator('[name=next_due_on]').input_value()=='2026-11-30';bill.locator('[name=end_mode]').select_option('DATE');bill.locator('[name=end_on]').fill('2027-01-31')
      with page.expect_navigation():bill.locator('button[type=submit]').click()
      rule=db.query_one('SELECT * FROM finance_recurring_expenses WHERE name=?',('Synthetic monthly bill '+scope,));assert rule['next_due_on']=='2026-11-30' and rule['anchor_day']==31 and rule['end_on']=='2027-01-31';assert db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n']==before
      page.goto(origin+case.url+f'/operations?branch_id={branch}&month=2026-11&view=recurring');page.locator('[data-finance-open="bill-edit-'+str(rule['id'])+'"]').click();edit=page.locator('#bill-edit-'+str(rule['id']));edit.locator('[name=end_mode]').select_option('UNTIL_STOPPED');expect(edit.locator('[name=end_on]')).to_be_hidden()
      with page.expect_navigation():edit.locator('button[type=submit]').click()
      assert db.query_one('SELECT end_on FROM finance_recurring_expenses WHERE id=?',(rule['id'],))['end_on'] is None;assert db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n']==before
     assert not errors,errors;print(f'PASS {scope} {width}: cards, immediate filter, split subcategories, collapsed/year/custom installment, layout, save/payment-or-cancel',flush=True);context.close()
   browser.close()
 finally:server.shutdown();case.doCleanups()
if __name__=='__main__':main()
