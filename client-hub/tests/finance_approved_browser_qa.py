"""Real local Flask/Chromium acceptance; disposable synthetic ledger, external IO blocked."""
import io,json,os,shutil,threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from PIL import Image
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright,expect
import test_finance_approved_revisions as fixtures
import finance_service as f,repo

def main():
    case=fixtures.ApprovedFinanceTests('test_equal_debit_credit_conserves_native_total_and_excludes_cashflow');case.setUp()
    output=Path(os.environ.get('FINANCE_QA_OUTPUT','/tmp/finance-approved-browser'));output.mkdir(parents=True,exist_ok=True)
    repo.update_user_profile(case.uid,'Synthetic Personal');repo.update_business_identity(case.b,'Synthetic Studio')
    import datetime
    today=datetime.date.today().isoformat();month=today[:7]
    category=f.list_categories(case.b,'EXPENSE',actor_user_id=case.uid)[0]['id']
    f.create_transaction(case.b,'INCOME',2500000,case.a,case.cat,today,description='Synthetic income',actor_user_id=case.uid)
    f.create_transaction(case.b,'EXPENSE',450000,case.a,category,today,description='Synthetic expense',actor_user_id=case.uid)
    f.set_monthly_budget(case.b,month,category,1000000,'IDR',actor_user_id=case.uid)
    server=make_server('127.0.0.1',0,fixtures.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}';cookie=case.client.get_cookie('session')
    report={'widths':[],'metrics':[],'direction_filters':[],'production_writes':0,'external_io':'blocked'}
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (1440,390,320):
                context=browser.new_context(viewport={'width':width,'height':1000},has_touch=width<761,reduced_motion='reduce')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}])
                page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                def goto(branch=case.branch,extra=''):
                    assert page.goto(f'{origin}{case.url}?branch_id={branch}&month={month}{extra}',wait_until='networkidle').status==200
                    assert page.locator('.kilas-feature-navigation').count()==0
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),('overflow',width,page.url)
                def shot(name):page.screenshot(path=str(output/f'{name}-{width}.png'),full_page=True)
                for branch,account,mode in ((case.branch,case.a,'business'),(case.personal,case.pa,'personal')):
                    for direction in ('INCOME','EXPENSE'):
                        goto(branch,f'&view=transactions&direction={direction}')
                        filters=page.locator('.finance-transaction-search')
                        assert filters.locator('select[name=direction]').count()==0
                        expect(filters.locator('input[type=hidden][name=direction]')).to_have_value(direction)
                        filters.locator('[name=search]').fill('Synthetic')
                        filters.locator('[name=account_id]').select_option(str(account))
                        filters.get_by_role('button',name='Terapkan',exact=True).click();page.wait_for_load_state('networkidle')
                        expected={'branch_id':str(branch),'view':'transactions','direction':direction,'search':'Synthetic','account_id':str(account)}
                        def assert_context():
                            query=parse_qs(urlsplit(page.url).query)
                            for key,value in expected.items():assert query.get(key)==[value],(key,page.url)
                        assert_context();shot(f'{mode}-{direction.lower()}-filters')
                        page.locator('.finance-ledger-month a').first.click();page.wait_for_load_state('networkidle');assert_context()
                        page.locator('.finance-ledger-month [data-finance-open="period-dialog"]').click()
                        period=page.locator('#period-dialog')
                        period.locator('[name=period_mode]').select_option('month')
                        period.locator('[name=period_year]').select_option(month[:4])
                        period.locator('[name=period_month]').select_option(month[5:])
                        period.get_by_role('button',name='Tampilkan',exact=True).click();page.wait_for_load_state('networkidle');assert_context()
                        assert parse_qs(urlsplit(page.url).query).get('month')==[month]
                        report['direction_filters'].append({'width':width,'mode':mode,'direction':direction,'result':'PASS'})
                    goto(branch,'&view=transactions')
                    expect(page.locator('.finance-transaction-search select[name=direction]')).to_be_visible()
                goto();expect(page.locator('.finance-identity-name')).to_have_text('Synthetic Studio')
                expect(page.locator('.finance-app-greeting h1')).to_have_text('Synthetic Studio')
                assert page.locator('#finance-app-currency,#finance-app-business').count()==0
                assert page.locator('.finance-budget-ring').bounding_box()['height']<=90
                report['metrics'].append({'width':width,'styles':page.locator('.finance-metric:is(.income,.expense,[data-finance-metric="account"])').evaluate_all('(els)=>els.map(e=>({background:getComputedStyle(e).backgroundColor,color:getComputedStyle(e.querySelector("strong")).color,label:getComputedStyle(e.querySelector(".finance-metric-label")).color}))')})
                shot('home');page.get_by_role('button',name='Tambah Cabang',exact=True).first.click()
                expect(page.locator('#branch-dialog')).to_be_visible();assert page.locator('#branch-dialog input[name=business_name]').count()==0
                page.locator('#branch-dialog [data-finance-close]').click()
                businessRect=page.locator('.finance-identity').bounding_box();goto(case.personal)
                expect(page.locator('.finance-identity-name')).to_have_text('Synthetic Personal')
                assert abs(page.locator('.finance-identity').bounding_box()['y']-businessRect['y'])<2
                shot('personal');goto(case.personal,'&view=transactions&direction=INCOME')
                if width==1440:assert page.locator('.finance-ledger-category-card').count()==0
                page.locator('[data-transaction-direction=INCOME]').click();sheet=page.locator('#add-transaction-dialog');expect(sheet).to_be_visible()
                assert sheet.locator('select[name=direction]').count()==0
                assert sheet.locator('#transaction-category').is_hidden()
                assert sheet.locator('[data-counterparty-field]').count()==0
                names=sheet.locator('input:not([type=hidden]):visible,select:visible,textarea:visible').evaluate_all('(els)=>els.map(e=>e.name)')
                assert names==['description','occurred_on','amount','account_id','notes'],names
                assert sheet.locator('select[name=account_id] option').count()==2
                sheet.locator('[name=description]').fill(f'Synthetic income {width}');sheet.locator('[name=amount]').fill('125.50')
                sheet.locator('[name=account_id]').select_option(str(case.pa));sheet.locator('[name=notes]').fill('Synthetic optional note');shot('income-form')
                sheet.get_by_role('button',name='Simpan Transaksi',exact=True).click();page.wait_for_load_state('networkidle')
                expect(page.locator('.finance-ledger-category-card')).to_be_visible()
                expect(page.locator('.finance-tx-description').filter(has_text=f'Synthetic income {width}')).to_be_visible()
                expect(page.locator('.finance-tx-notes').first).to_have_text('Synthetic optional note');assert 'direction=INCOME' in page.url
                page.reload(wait_until='networkidle');shot('income-saved')
                goto(case.personal,'&view=transactions&direction=EXPENSE');page.locator('[data-transaction-direction=EXPENSE]').click()
                expect(page.locator('#transaction-category')).to_be_visible();assert sheet.locator('select[name=direction]').count()==0
                shot('expense-form');page.locator('#add-transaction-dialog [data-finance-close]').click()
                goto(extra='&view=accounts');page.locator('.finance-transfer-launch button').click()
                transfer=page.locator('#internal-transfer-dialog');expect(transfer).to_be_visible()
                transfer.locator('[name=from_account_id]').select_option(str(case.a))
                assert not errors, errors
                assert transfer.locator(f'[name=to_account_id] option[value="{case.a}"]').evaluate('(option)=>option.disabled'), transfer.locator('[name=from_account_id],[name=to_account_id]').evaluate_all('(els)=>els.map(e=>({value:e.value,options:[...e.options].map(o=>({value:o.value,disabled:o.disabled}))}))')
                transfer.locator('[name=to_account_id]').select_option(str(case.dest));transfer.locator('[name=amount]').fill('5.25');shot('transfer-form')
                before=f.get_finance_summaries(case.b,today,today,actor_user_id=case.uid)
                transfer.get_by_role('button',name='Simpan Transfer',exact=True).click();page.wait_for_load_state('networkidle')
                assert before==f.get_finance_summaries(case.b,today,today,actor_user_id=case.uid)
                page.locator('.finance-transfer-launch button').click();expect(transfer.locator('.finance-transfer-record').first).to_be_visible()
                transfer.locator('[data-finance-close]').click();goto();page.locator('.finance-identity').click()
                identity=page.locator('#finance-identity-dialog');expect(identity).to_be_visible()
                image=io.BytesIO();Image.new('RGB',(16,16),'blue').save(image,format='PNG')
                identity.locator('[name=photo]').set_input_files({'name':'synthetic-logo.png','mimeType':'image/png','buffer':image.getvalue()})
                identity.get_by_role('button',name='Simpan',exact=True).click();page.wait_for_load_state('networkidle')
                expect(page.locator('.finance-identity img')).to_be_visible();assert page.locator('.finance-identity img').evaluate('(img)=>img.complete&&img.naturalWidth===16')
                assert not errors,errors
                report['widths'].append(width);context.close()
            browser.close()
        report['result']='PASS';(output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    finally:server.shutdown();case.doCleanups()

if __name__=='__main__':main()
