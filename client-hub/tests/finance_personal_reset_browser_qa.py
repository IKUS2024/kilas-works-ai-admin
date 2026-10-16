"""Local-only browser verification of canonical Personal, bank accounts and explicit reset."""
import json,os,shutil,threading
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright,expect
import test_finance_personal_reset as fixture
import finance_service as f,finance_branches as branches,finance_reset as reset
import db,repo


def main():
    case=fixture.PersonalResetTests('test_prepare_and_review_never_reset_financial_data');case.setUp()
    repo.update_user_profile(case.uid,'Synthetic Personal')
    repo.update_business_identity(case.b,'Synthetic Finance Studio')
    bca,bank,_,_=case.seed_personal()
    secondary=repo.create_business(case.uid,'Synthetic secondary business')
    f.ensure_finance_defaults(secondary,actor_user_id=case.uid)
    secondary_branch=branches.list_branches(secondary,case.uid)[0]['id']
    legacy,legacy_account=case.legacy_empty_personal(secondary,case.uid)
    business_second=branches.create_branch(case.b,'Synthetic inactive branch',case.uid)
    with branches.scope(case.b,business_second,case.uid):
        inactive_account=f.list_accounts(case.b,actor_user_id=case.uid)[0]['id']
        f.update_account_opening_balance(case.b,inactive_account,777,actor_user_id=case.uid)
    db.execute('UPDATE finance_branches SET is_active=FALSE WHERE id=?',(business_second,))
    output=Path(os.environ.get('FINANCE_RESET_QA_OUTPUT','/tmp/finance-personal-reset-browser'));output.mkdir(parents=True,exist_ok=True)
    server=make_server('127.0.0.1',0,fixture.prior.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}';cookie=case.client.get_cookie('session')
    report={'widths':[],'canonical_context':'single populated existing ledger','production_resets':0,'external_io':'blocked'}
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (1440,390,320):
                context=browser.new_context(viewport={'width':width,'height':1000},has_touch=width<761,reduced_motion='reduce')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}])
                context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                def goto(path):
                    assert page.goto(origin+path,wait_until='networkidle').status==200
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),page.url
                def shot(name):page.screenshot(path=str(output/f'{name}-{width}.png'),full_page=True)
                before_accounts=db.query_all('SELECT * FROM finance_accounts')
                # Every existing Personal entry resolves the same banks, with no selector or creation.
                goto(f'/business/{secondary}/finance?branch_id={legacy}&view=transactions&direction=INCOME&month=2026-09')
                values=parse_qs(urlsplit(page.url).query)
                assert values['branch_id']==[str(case.personal)] and '/business/'+str(case.b)+'/' in page.url
                assert page.locator('#finance-personal-context,#finance-app-branch,#branch-dialog,[data-dashboard-open=branch-dialog]').count()==0
                page.locator('[data-transaction-direction=INCOME]').click()
                account=page.locator('#transaction-account')
                assert set(account.locator('option').evaluate_all('(options)=>options.map(o=>o.value).filter(Boolean)'))=={str(case.pa),str(bca),str(bank)}
                page.locator('#transaction-description').fill(f'Synthetic selected BCA {width}')
                page.locator('#transaction-amount').fill('25.50');account.select_option(str(bca));shot('personal-existing-bank')
                page.locator('#add-transaction button.btn').click();page.wait_for_load_state('networkidle')
                row=db.query_one('SELECT * FROM finance_transactions WHERE description=?',(f'Synthetic selected BCA {width}',))
                assert (row['account_id'],row['branch_id'])==(bca,case.personal)
                assert before_accounts==db.query_all('SELECT * FROM finance_accounts')
                # Personal first click only prepares a warning; typed text and acknowledgement are separate.
                before=case.finance_rows();page.locator('.finance-reset-launch button').click();page.wait_for_load_state('networkidle')
                expect(page.get_by_role('heading',name='Verifikasi Reset Data Finance',exact=True)).to_be_visible()
                assert 'Finance Pribadi' in page.locator('.finance-reset-review').inner_text()
                assert case.finance_rows()==before
                page.locator('[name=confirmation]').fill('RESET')
                page.get_by_role('button',name='Hapus Data Finance dan Reset ke 0',exact=True).click()
                assert '/reset/review/' in page.url and case.finance_rows()==before
                page.locator('[name=acknowledged]').check();shot('personal-reset-verification')
                page.get_by_role('button',name='Hapus Data Finance dan Reset ke 0',exact=True).click();page.wait_for_load_state('networkidle')
                with branches.scope(case.b,case.personal,case.uid):
                    assert all(r['balance_minor']==0 for r in f.get_account_balance_report(case.b,'2026-09-30',case.uid))
                # Business controls remain, and Business reset excludes Personal and other businesses.
                f.create_transaction(case.b,'INCOME',100,case.a,case.cat,'2026-09-10',actor_user_id=case.uid)
                goto(f'{case.url}?branch_id={case.branch}&month=2026-09')
                expect(page.get_by_role('button',name='Tambah Cabang',exact=True).first).to_be_visible()
                page.get_by_role('button',name='Tambah Cabang',exact=True).first.click();expect(page.locator('#branch-dialog')).to_be_visible()
                page.locator('#branch-dialog [data-finance-close]').click()
                personal_before=db.query_all('SELECT * FROM finance_accounts WHERE branch_id=?',(case.personal,))
                other_before=db.query_all('SELECT * FROM finance_accounts WHERE business_id=?',(secondary,))
                page.locator('.finance-reset-launch button').click();page.wait_for_load_state('networkidle')
                warning=page.locator('.finance-reset-review').inner_text()
                assert 'hanya mencakup cabang Bisnis' in warning and 'Synthetic inactive branch' not in warning
                page.locator('[name=confirmation]').fill('RESET');page.locator('[name=acknowledged]').check();shot('business-reset-verification')
                page.get_by_role('button',name='Hapus Data Finance dan Reset ke 0',exact=True).click();page.wait_for_load_state('networkidle')
                assert personal_before==db.query_all('SELECT * FROM finance_accounts WHERE branch_id=?',(case.personal,))
                assert other_before==db.query_all('SELECT * FROM finance_accounts WHERE business_id=?',(secondary,))
                assert db.query_one('SELECT opening_balance_minor FROM finance_accounts WHERE id=?',(inactive_account,))['opening_balance_minor']==777
                # Personal button from a different business always reuses the same dataset.
                goto(f'/business/{secondary}/finance?branch_id={secondary_branch}&month=2026-09')
                page.locator('form[action*="/workspaces/PERSONAL"] button').click();page.wait_for_load_state('networkidle')
                assert parse_qs(urlsplit(page.url).query)['branch_id']==[str(case.personal)]
                assert page.locator('#finance-personal-context,#finance-app-branch,[data-dashboard-open=branch-dialog]').count()==0
                shot('personal-canonical-home')
                page.locator('form[action*="/workspaces/BUSINESS"] button').click();page.wait_for_load_state('networkidle')
                assert '/business/'+str(secondary)+'/' in page.url
                assert parse_qs(urlsplit(page.url).query)['branch_id']==[str(secondary_branch)]
                assert not errors,errors
                report['widths'].append(width);context.close()
            browser.close()
        report['result']='PASS';(output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    finally:server.shutdown();case.doCleanups()

if __name__=='__main__':main()
