"""Local-only placement checks. Never submits final reset or writes production data."""
import json,os,shutil,threading
from pathlib import Path
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright,expect
import test_finance_personal_reset as fixture
import db


def main():
    case=fixture.PersonalResetTests('test_reset_launch_is_only_on_personal_and_business_dashboard');case.setUp()
    output=Path(os.environ.get('FINANCE_DASHBOARD_QA_OUTPUT','/tmp/finance-reset-dashboard-browser'));output.mkdir(parents=True,exist_ok=True)
    server=make_server('127.0.0.1',0,fixture.prior.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}';cookie=case.client.get_cookie('session')
    report=dict(widths=[],modes=['PERSONAL','BUSINESS'],languages=['id','en','es','zh'],final_reset_submissions=0,production_writes=0,external_io='blocked')
    before=case.finance_rows()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (1440,390,320):
                context=browser.new_context(viewport={'width':width,'height':1000},reduced_motion='reduce')
                context.add_cookies([dict(name=cookie.key,value=cookie.value,url=origin)])
                context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                page=context.new_page();errors=[];posts=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('request',lambda request:posts.append(request.url) if request.method=='POST' else None)
                def goto(path):
                    assert page.goto(origin+path,wait_until='networkidle').status==200,path
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),page.url
                for mode,branch in (('personal',case.personal),('business',case.branch)):
                    home=f'{case.url}?branch_id={branch}&month=2026-09'
                    for language in report['languages']:
                        context.add_cookies([dict(name='kilas_language',value=language,url=origin)])
                        goto(home)
                        launch=page.locator('.finance-primary-navigation > .finance-reset-launch')
                        assert launch.count()==1 and page.locator('.finance-reset-launch').count()==1
                        expect(launch.locator('button')).to_be_visible()
                        assert page.locator('.finance-context-toolbar .finance-reset-launch').count()==0
                        assert launch.locator('button').evaluate('(b)=>{const r=b.getBoundingClientRect();const p=b.closest(".finance-primary-navigation").getBoundingClientRect();return r.left>=p.left-1&&r.right<=p.right+1&&r.top>=p.top-1&&r.bottom<=p.bottom+1&&r.right<=innerWidth&&r.left>=0}')
                        if mode=='personal':assert page.locator('#finance-app-branch,[data-dashboard-open=branch-dialog]').count()==0
                        if language=='id':page.screenshot(path=str(output/f'{mode}-dashboard-{width}.png'),full_page=True)
                    context.add_cookies([dict(name='kilas_language',value='id',url=origin)])
                    for query in ('view=transactions','view=transactions&direction=INCOME','view=transactions&direction=EXPENSE','view=accounts'):
                        goto(home+'&'+query);assert page.locator('.finance-reset-launch').count()==0
                    for path in ('operations','budget','payees','receivables','reports'):
                        goto(f'{case.url}/{path}?branch_id={branch}&month=2026-09')
                        assert page.locator('.finance-reset-launch').count()==0
                    # Only a disposable local request is prepared: no final reset submission.
                    goto(home);count=db.query_one('SELECT count(*) AS n FROM finance_reset_requests')['n']
                    page.locator('.finance-primary-navigation .finance-reset-launch button').click();page.wait_for_load_state('networkidle')
                    assert '/reset/review/' in page.url
                    assert page.locator('.finance-reset-launch').count()==0
                    expect(page.locator('[name=confirmation]')).to_be_visible()
                    expect(page.locator('[name=acknowledged]')).to_be_visible()
                    assert db.query_one('SELECT count(*) AS n FROM finance_reset_requests')['n']==count+1
                    assert db.query_one('SELECT count(*) AS n FROM finance_reset_requests WHERE processed_at IS NOT NULL')['n']==0
                    assert before==case.finance_rows()
                assert not errors,errors
                assert all(url.split('?')[0].endswith('/reset/prepare') for url in posts),posts
                report['widths'].append(width);context.close()
            browser.close()
        report['result']='PASS';(output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
