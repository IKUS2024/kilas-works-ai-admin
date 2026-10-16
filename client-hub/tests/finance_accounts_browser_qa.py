"""Read-only Accounts layout acceptance with synthetic local fixtures."""
import json,os,shutil,threading
from pathlib import Path
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright,expect
import test_finance_account_presentation as fixture
import db


def main():
    case=fixture.AccountPresentationTests('test_collapsed_groups_show_current_totals_keep_details_and_signed_credit');case.setUp()
    case.seed(case.branch);case.seed(case.personal)
    output=Path(os.environ.get('FINANCE_ACCOUNTS_QA_OUTPUT','/tmp/finance-accounts-browser'));output.mkdir(parents=True,exist_ok=True)
    before={table:db.query_all('SELECT * FROM '+table) for table in ('finance_accounts','finance_transactions','finance_transaction_revisions')}
    server=make_server('127.0.0.1',0,fixture.prior.prior.prior.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}';cookie=case.client.get_cookie('session')
    report=dict(widths=[],languages=['id','en','es','zh'],modes=['PERSONAL','BUSINESS'],external_io='blocked',production_writes=0,form_submissions=0)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (1440,390,320):
                context=browser.new_context(viewport=dict(width=width,height=1000),reduced_motion='reduce')
                context.add_cookies([dict(name=cookie.key,value=cookie.value,url=origin)])
                context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                page=context.new_page();errors=[];posts=[]
                page.on('pageerror',lambda error:errors.append(str(error)));page.on('request',lambda request:posts.append(request.url) if request.method=='POST' else None)
                for mode,branch in (('business',case.branch),('personal',case.personal)):
                    for language in report['languages']:
                        context.add_cookies([dict(name='kilas_language',value=language,url=origin)])
                        assert page.goto(origin+f'{case.url}?branch_id={branch}&view=accounts',wait_until='networkidle').status==200
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        total=page.locator('.finance-account-overall-total > strong');expect(total).to_be_visible()
                        style=total.evaluate('(e)=>({size:parseFloat(getComputedStyle(e).fontSize),weight:Number(getComputedStyle(e).fontWeight)})')
                        assert style['size']>=28 and style['weight']>=750,style
                        assert page.locator('.finance-account-overall-total').bounding_box()['height']<130
                        groups=page.locator('.finance-account-hb-group')
                        assert groups.count()>=3 and page.locator('.finance-account-hb-group[open]').count()==0
                        assert page.locator('.finance-account-liability-label').count()==1
                        expect(page.locator('.finance-account-total-note')).to_be_visible()
                        assert page.locator('.finance-reset-launch').count()==0
                        for item in groups.all():
                            expect(item.locator('summary .finance-account-group-total')).to_be_visible()
                            assert item.locator('summary .finance-account-group-total').evaluate('(e)=>{let r=e.getBoundingClientRect();return r.right<=innerWidth&&r.left>=0}')
                        if language=='id':
                            if width in (1440,320):page.screenshot(path=str(output/f'{mode}-collapsed-{width}.png'),full_page=True)
                            debit=groups.filter(has=page.locator('.finance-account-hb-row-main > strong',has_text='Synthetic debit one')).first
                            debit.locator('summary').click();expect(debit.locator('.finance-account-hb-row-main > strong',has_text='Synthetic debit one')).to_be_visible()
                            expect(debit.locator('.finance-account-hb-row-main > strong',has_text='Synthetic debit two')).to_be_visible()
                            if width==390:page.screenshot(path=str(output/f'{mode}-expanded-{width}.png'),full_page=True)
                assert not errors and not posts,(errors,posts)
                report['widths'].append(width);context.close()
            browser.close()
        assert before=={table:db.query_all('SELECT * FROM '+table) for table in before}
        report['result']='PASS';(output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
