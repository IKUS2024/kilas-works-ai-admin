"""Synthetic browser recovery and canceled-entry QA. No production connections."""
import json
import logging
import os
from pathlib import Path
import shutil
import threading
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_finance_entry_context as fixture
import repo
import finance_branches as branches
import finance_service as finance


def main():
    case = fixture.FinanceEntryContextTests()
    case.setUp()
    newer = repo.create_business(case.uid, 'Synthetic empty business')
    finance.ensure_finance_defaults(newer, actor_user_id=case.uid)
    bank_name = 'Synthetic saved personal bank'
    with branches.scope(case.b, case.personal, case.uid):
        finance.create_account(case.b, bank_name, 'BANK',
                               opening_balance_minor=1234500, actor_user_id=case.uid)
    before = case.snapshot()
    app = fixture.fixture.app
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    output = Path(os.environ.get('FINANCE_ENTRY_QA_OUTPUT', '/tmp/finance-entry-context-qa'))
    output.mkdir(parents=True, exist_ok=True)
    results = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=shutil.which('chromium'), args=['--no-sandbox'])
            for width in (320, 390, 1440):
                context = browser.new_context(viewport={'width': width, 'height': 1000}, reduced_motion='reduce')
                cookie = case.client.get_cookie('session')
                context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin},
                                     {'name': 'kilas_language', 'value': 'en', 'url': origin}])
                context.route('**/*', lambda route: route.continue_()
                              if urlparse(route.request.url).netloc == urlparse(origin).netloc
                              else route.abort())
                page = context.new_page()
                page.set_default_timeout(10000)
                errors, mutations = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: mutations.append(urlparse(request.url).path)
                        if request.method not in ('GET', 'HEAD', 'OPTIONS') else None)

                def open_product():
                    page.goto(origin + '/products/catalog')
                    page.locator('form').filter(has=page.locator('input[name="product"][value="finance"]')).locator('button').click()

                def choose(business_id):
                    form = page.locator('form').filter(has=page.locator('input[name="action"][value="open"]')).filter(
                        has=page.locator(f'input[name="business_id"][value="{business_id}"]'))
                    form.locator('button').click()
                    page.wait_for_url('**/business/**/finance?**')

                # A new browser must choose, rather than silently showing an empty business.
                open_product()
                page.wait_for_url('**/products/finance')
                expect(page.get_by_text('Synthetic empty business', exact=True)).to_be_visible()
                expect(page.get_by_text('Other business', exact=True)).to_have_count(0)
                choose(case.b)
                page.goto(origin + case.url + f'?branch_id={case.personal}&view=accounts')
                expect(page.locator('.finance-account-hb-row-main > strong', has_text=bank_name)).to_have_count(1)
                page.goto(origin + f'/business/{newer}/finance')
                switch = page.locator('[data-finance-business-switch]')
                expect(switch).to_be_visible()
                expect(switch).to_have_text('Switch business')
                branch_picker = page.locator('#finance-app-branch')
                expect(branch_picker).to_be_visible()
                assert branch_picker.bounding_box()['width'] >= 80, 'Business switch must not crowd the branch picker'
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output / f'empty-business-recovery-{width}.png'), full_page=True)
                switch.click()
                page.wait_for_url('**/products/finance')
                page.go_back()
                expect(page.locator('[data-finance-business-switch]')).to_be_visible()
                page.go_forward()
                page.wait_for_url('**/products/finance')
                choose(case.b)
                assert parse_qs(urlparse(page.url).query)['branch_id'] == [str(case.personal)]
                for _ in range(2):
                    open_product()
                    page.wait_for_url('**/business/**/finance?**')
                    assert urlparse(page.url).path == case.url
                    assert parse_qs(urlparse(page.url).query)['branch_id'] == [str(case.personal)]
                    page.reload()
                page.goto(origin + case.url + f'?branch_id={case.personal}&view=accounts')
                bank = page.locator('.finance-account-hb-row-main > strong', has_text=bank_name)
                group = page.locator('.finance-account-hb-group').filter(has=bank)
                group.locator('summary').click()
                expect(bank).to_be_visible()
                page.screenshot(path=str(output / f'recovered-bank-{width}.png'), full_page=True)
                # Filling and dismissing real input must never submit a transaction.
                page.goto(origin + case.url + f'?branch_id={case.personal}&view=transactions&direction=INCOME')
                page.locator('[data-transaction-direction="INCOME"]').click()
                expect(page.locator('#add-transaction-dialog')).to_be_visible()
                page.locator('#transaction-description').fill('Synthetic canceled income')
                page.locator('#transaction-amount').fill('12.34')
                page.locator('[data-finance-close="add-transaction-dialog"]').click()
                expect(page.locator('#add-transaction-dialog')).not_to_be_visible()
                page.reload()
                page.goto(origin + case.url + f'?branch_id={case.personal}&view=transactions&direction=EXPENSE')
                page.locator('[data-transaction-direction="EXPENSE"]').click()
                expect(page.locator('#add-expense-dialog')).to_be_visible()
                page.locator('#add-expense input[name="amount"]').fill('12.34')
                page.locator('[data-finance-close="add-expense-dialog"]').click()
                expect(page.locator('#add-expense-dialog')).not_to_be_visible()
                page.reload()
                assert all(path in ('/products/start', '/products/finance') for path in mutations), mutations
                assert not errors, errors
                assert case.snapshot() == before
                results.append({'width': width, 'result': 'PASS', 'ledger_writes': 0,
                                'reentry_repeats': 2, 'external_network': 'blocked'})
                context.close()
            browser.close()
        (output / 'report.json').write_text(json.dumps(results, indent=2))
        print(json.dumps(results))
    finally:
        server.shutdown()
        case.doCleanups()


if __name__ == '__main__':
    main()
