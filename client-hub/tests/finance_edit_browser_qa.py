"""Package-one acceptance using synthetic local data; all external browser IO blocked."""
import json,os,shutil,threading
from pathlib import Path
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright,expect
import test_finance_edit_package as fixture
import finance_service as f,finance_branches as branches
import db


def main():
    case=fixture.FinanceEditPackageTests('test_navigation_order_active_direction_and_search_absence_both_modes');case.setUp()
    output=Path(os.environ.get('FINANCE_EDIT_QA_OUTPUT','/tmp/finance-edit-browser'));output.mkdir(parents=True,exist_ok=True)
    server=make_server('127.0.0.1',0,fixture.prior.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}';cookie=case.client.get_cookie('session')
    report=dict(widths=[],modes=['PERSONAL','BUSINESS'],external_io='blocked',production_writes=0,reset_submissions=0)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (1440,390,320):
                context=browser.new_context(viewport=dict(width=width,height=1000),reduced_motion='reduce')
                context.add_cookies([dict(name=cookie.key,value=cookie.value,url=origin),dict(name='kilas_language',value='id',url=origin)])
                context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                def goto(path):
                    assert page.goto(origin+path,wait_until='networkidle').status==200,path
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),page.url
                for mode,branch,source in (('business',case.branch,case.a),('personal',case.personal,case.pa)):
                    rule,tx,category=case.bill(branch,source)
                    with branches.scope(case.b,branch,case.uid):
                        target=case.dest if mode=='business' else f.create_account(case.b,'Synthetic second Personal bank','BANK',actor_user_id=case.uid)
                        before=case.balances();schedule=f.get_recurring_expense(case.b,rule,case.uid);posting=f.list_recurring_postings(case.b,rule,case.uid)
                    home=f'{case.url}?branch_id={branch}&month=2026-09'
                    goto(home);nav=page.locator('.finance-primary-navigation')
                    links=nav.locator(':scope > a').evaluate_all('(items)=>items.map(a=>a.href)')
                    assert 'direction=INCOME' in links[1] and 'direction=EXPENSE' in links[2] and 'view=transactions' in links[3] and 'view=accounts' in links[4]
                    assert nav.locator(':scope > :last-child').get_attribute('class')=='finance-reset-launch'
                    assert page.locator('.finance-legacy-switch,[name=business_id]').count()==0
                    for index,direction in ((1,'INCOME'),(2,'EXPENSE'),(3,None)):
                        link=nav.locator(':scope > a').nth(index);link.scroll_into_view_if_needed();link.click();page.wait_for_load_state('networkidle')
                        assert page.locator('input[type=search]').count()==0
                        assert page.locator('.finance-reset-launch').count()==0
                        if direction:assert 'direction='+direction in page.url
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    goto(f'{case.url}/operations?branch_id={branch}&month=2026-09&view=list&payment_status=paid')
                    edit=page.locator(f'a[href*="/transactions/{tx}/edit?"]');expect(edit).to_be_visible();edit.click();page.wait_for_load_state('networkidle')
                    form=page.locator('form.card');form.locator('[name=amount]').fill('3.50');form.locator('[name=occurred_on]').fill('2026-09-11')
                    form.locator('[name=account_id]').select_option(str(target));form.locator('[name=description]').fill(f'Synthetic browser edit {mode} {width}')
                    if width==390:page.screenshot(path=str(output/f'{mode}-bill-edit-{width}.png'),full_page=True)
                    form.locator('button.btn').click();page.wait_for_load_state('networkidle')
                    row=f.get_transaction(case.b,tx)
                    assert (row['amount_minor'],row['account_id'],row['occurred_on'])==(350,target,'2026-09-11')
                    with branches.scope(case.b,branch,case.uid):
                        after=case.balances();assert after[source]==before[source]+100 and after[target]==before[target]-350
                        assert schedule==f.get_recurring_expense(case.b,rule,case.uid) and posting==f.list_recurring_postings(case.b,rule,case.uid)
                    goto(home+'&view=transactions&direction=EXPENSE')
                    expect(page.get_by_text(f'Synthetic browser edit {mode} {width}',exact=True)).to_be_visible()
                    if width==320:page.screenshot(path=str(output/f'{mode}-expenses-{width}.png'),full_page=True)
                assert not errors,errors
                report['widths'].append(width);context.close()
            browser.close()
        report['result']='PASS';(output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
