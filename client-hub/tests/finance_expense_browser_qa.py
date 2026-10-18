"""Actual local expense UI; synthetic financial writes only, all external IO blocked."""
import io,os,threading,json
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_finance_expense_entries as fixture
import finance_service as f,db

def main():
    case=fixture.ExpenseEntryTests('test_one_ledger_debit_allocated_reports_exact_retry_void');case.setUp()
    app=fixture.fixture.app
    server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}';cookie=case.client.get_cookie('session')
    output=Path('/tmp/kilas-finance-expense-browser');output.mkdir(exist_ok=True)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM'),args=['--no-sandbox'])
            for width in (int(v) for v in os.environ.get('FINANCE_QA_WIDTHS','320,390,768,1440').split(',')):
                context=browser.new_context(viewport={'width':width,'height':1000},accept_downloads=True)
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                url=origin+case.url+f'?branch_id={case.branch}&view=transactions&direction=EXPENSE&month=2026-09'
                page.goto(url);page.locator('[data-transaction-direction=EXPENSE]').click()
                dialog=page.locator('#add-expense-dialog');expect(dialog).to_be_visible()
                form=dialog.locator('[data-expense-form]');form.locator('[name=amount]').fill('123.45');form.locator('[name=occurred_on]').fill('2026-09-10');form.locator('[name=account_id]').select_option(str(case.a))
                form.locator('[data-expense-split-toggle]').check()
                rows=form.locator('.expense-split-row');assert rows.count()==2
                cats={c['id']:c for c in f.list_categories(case.b,'EXPENSE',include_children=True,actor_user_id=case.uid)}
                for i,value in enumerate(case.splits()):
                    category=cats[value['category_id']];row=rows.nth(i)
                    row.locator('[name=split_category_id]').select_option(str(category.get('parent_category_id') or category['id']))
                    if category.get('parent_category_id'):row.locator('select[name=split_subcategory_id]').select_option(str(category['id']))
                    row.locator('[name=split_amount]').fill('100.00' if i==0 else '23.45')
                form.locator('[name=counterparty_name]').fill('Synthetic shop');form.locator('[name=notes]').fill('Synthetic split receipt')
                raw=io.BytesIO();Image.new('RGB',(20,20),'white').save(raw,'JPEG')
                form.locator('[name=receipt]').set_input_files({'name':'receipt.jpg','mimeType':'image/jpeg','buffer':raw.getvalue()})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert dialog.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
                page.screenshot(path=str(output/f'expense-{width}.png'))
                before=db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n']
                if width==320:
                    with page.expect_navigation():dialog.get_by_role('button',name='Save',exact=True).click()
                    assert db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n']==before+1
                    tx=db.query_one('SELECT id FROM finance_transactions ORDER BY id DESC LIMIT 1')['id']
                    page.goto(origin+case.url+f'/transactions/{tx}/edit?branch_id={case.branch}')
                    expect(page.locator('[name=split_enabled]')).to_be_checked()
                    assert page.locator('[name=split_amount]').nth(1).input_value()=='23.45'
                    expect(page.get_by_role('link',name='View receipt',exact=True)).to_be_visible()
                    with page.expect_download() as download:page.get_by_role('link',name='View receipt',exact=True).click()
                    assert Path(download.value.path()).read_bytes()==raw.getvalue()
                    page.locator('[name=notes]').fill('Edited note')
                    with page.expect_navigation():page.get_by_role('button',name='Save',exact=True).click()
                    assert db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n']==before+1
                else:
                    dialog.get_by_role('button',name='Cancel',exact=True).click();expect(dialog).not_to_be_visible()
                    assert db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n']==before
                assert not errors,errors
                print(f'PASS expense/splits/receipt/layout/save-edit-or-cancel/no-overflow {width}',flush=True)
                context.close()
            browser.close()
    finally:server.shutdown();case.doCleanups()

if __name__=='__main__':main()
