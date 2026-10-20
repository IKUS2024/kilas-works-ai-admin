"""Expense read-only subcategory synchronization and layout; disposable ledger, loopback IO only.

PYTHONPATH=client-hub:client-hub/tests KILAS_QA_CHROMIUM=/usr/bin/chromium \
  python client-hub/tests/finance_expense_category_browser.py
Set KILAS_QA_ENGINE=webkit for the same checks with installed Playwright WebKit.
"""
import json
import os
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_finance_category_reference as fixture
import db
import finance_branches as branches
import finance_service as finance


def ledger_snapshot():
    tables = db.query_all("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'finance_%' ORDER BY name")
    return {r['name']: sorted(json.dumps(dict(v), sort_keys=True, default=str)
                             for v in db.query_all('SELECT * FROM "'+r['name']+'"')) for r in tables}


def choose(box, parent, child=None):
    if box.locator('[data-expense-cascade-panel]').is_hidden():
        box.locator('[data-expense-cascade]').click()
    group = box.locator('[data-expense-group="'+str(parent)+'"]')
    if not group.evaluate('(e)=>e.open'):
        group.locator('summary').click()
    expect(group.locator('.finance-category-icon').first).to_be_visible()
    assert group.locator('summary').bounding_box()['height'] >= 48
    assert group.bounding_box()['height'] >= 48
    if child:
        group.locator('[data-expense-choice="'+str(child)+'"]').click()
        expect(box.locator('[data-expense-child]')).to_have_value(str(child))
        expect(box.locator('[data-expense-cascade-panel]')).to_be_hidden()
    return group


def main():
    case = fixture.CategoryReferenceTests()
    case.setUp()
    app = fixture.fixture.fixture.app
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    cookie = case.client.get_cookie('session')
    engine = os.environ.get('KILAS_QA_ENGINE', 'chromium')
    output = Path(os.environ.get('KILAS_QA_OUTPUT', '/tmp/kilas-expense-category-qa'))
    output.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            launch = {'args':['--no-sandbox'], 'executable_path':os.environ.get('KILAS_QA_CHROMIUM', '/usr/bin/chromium')} if engine == 'chromium' else {}
            browser = getattr(p, engine).launch(**launch)
            for width in map(int, os.environ.get('KILAS_QA_WIDTHS', '320,390,768,820,1024,1440').split(',')):
                for scope in ('PERSONAL', 'BUSINESS'):
                    branch, account = (case.personal, case.pa) if scope == 'PERSONAL' else (case.branch, case.a)
                    with branches.scope(case.b, branch, case.uid):
                        roots = finance.list_categories(case.b, 'EXPENSE', actor_user_id=case.uid)
                        groups = [(r, finance.list_category_children(case.b, r['id'], actor_user_id=case.uid)) for r in roots]
                        if len([g for g in groups if g[1]]) < 2:
                            empty_root = next(r for r, kids in groups if not kids)
                            finance.create_category(case.b, 'EXPENSE', 'Synthetic selectable child', parent_category_id=empty_root['id'], actor_user_id=case.uid)
                            groups = [(r, finance.list_category_children(case.b, r['id'], actor_user_id=case.uid)) for r in roots]
                        (parent, children), (other, other_children) = [g for g in groups if g[1]][:2]
                    context = browser.new_context(viewport={'width':width, 'height':1100}, is_mobile=width < 1100, has_touch=width < 1100)
                    context.add_cookies([{'name':cookie.key, 'value':cookie.value, 'url':origin}, {'name':'kilas_language', 'value':'en', 'url':origin}])
                    page = context.new_page()
                    page.set_default_timeout(5000)
                    errors, writes = [], []
                    page.on('pageerror', lambda e:errors.append(str(e)))
                    page.on('request', lambda r:writes.append(r.url) if r.method != 'GET' else None)
                    page.route('**/*', lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                    base = origin+case.url+f'?branch_id={branch}&view=transactions&direction=EXPENSE'
                    page.goto(base)
                    page.locator('[data-transaction-direction=EXPENSE]').click()
                    dialog = page.locator('#add-expense-dialog')
                    form = dialog.locator('[data-expense-form]')
                    single = form.locator('[data-expense-single]')
                    form.locator('[name=amount]').fill('100.01')
                    form.locator('[name=occurred_on]').fill('2025-01-01')
                    form.locator('[name=account_id]').select_option(str(account))
                    expect(single.locator('[data-expense-subcategory-display]')).to_have_text('No subcategory selected.')
                    before = ledger_snapshot()
                    choose(single, parent['id'], children[0]['id'])
                    summary = single.locator('[data-expense-cascade]').text_content()
                    leaf_name = single.locator('[data-expense-child] option[value="'+str(children[0]['id'])+'"]').text_content()
                    assert summary==single.locator('[data-expense-parent] option:checked').text_content()
                    group = choose(single, parent['id'])
                    expect(group.locator('[aria-pressed=true]')).to_have_attribute('data-expense-choice', str(children[0]['id']))
                    # Escape closes only the picker, leaves the draft and modal intact.
                    group.locator('summary').focus()
                    page.keyboard.press('Escape')
                    expect(dialog).to_be_visible()
                    expect(single.locator('[data-expense-cascade-panel]')).to_be_hidden()
                    date = form.locator('[name=occurred_on]').bounding_box()
                    amount = form.locator('[name=amount]').bounding_box()
                    if width > 480:
                        assert amount['x'] - date['x'] - date['width'] >= 17, (date, amount)
                    else:
                        assert amount['y'] - date['y'] - date['height'] >= 13, (date, amount)
                    bars=[single.locator('[data-expense-cascade]').bounding_box(),single.locator('[data-expense-subcategory-display]').bounding_box()]
                    assert abs(bars[0]['width']-bars[1]['width'])<1 and abs(bars[0]['height']-bars[1]['height'])<1,bars
                    assert form.locator('[data-expense-split-toggle]').bounding_box()['y']>bars[1]['y']+bars[1]['height']
                    expect(single.locator('.expense-cascade-label')).to_contain_text('Category/Subcategory')
                    assert dialog.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    if width in (390, 768, 1440):
                        page.screenshot(path=str(output/f'{engine}-{scope.lower()}-expense-{width}.png'))
                        choose(single, parent['id'])
                        page.screenshot(path=str(output/f'{engine}-{scope.lower()}-picker-{width}.png'))
                    # This area is a display, never a category-management action.
                    readout=single.locator('[data-expense-subcategory-display]')
                    expect(readout).to_have_text(leaf_name)
                    assert readout.evaluate('(e)=>e.tabIndex === -1 && !e.matches("a,button,input,select,textarea,[tabindex],[href]")')
                    assert single.locator('.expense-subcategory-readout a,.expense-subcategory-readout button,.expense-subcategory-readout [tabindex]').count()==0
                    assert form.locator('[data-expense-manage-categories]').count()==0
                    readout.click()
                    expect(page.locator('#category-dialog')).to_be_hidden()
                    expect(dialog).to_be_visible()
                    single.locator('[data-expense-cascade]').focus()
                    page.keyboard.press('Tab')
                    assert not readout.evaluate('(e)=>e===document.activeElement')
                    expect(form.locator('[name=amount]')).to_have_value('100.01')
                    expect(single.locator('[data-expense-cascade]')).to_have_text(summary)
                    assert page.url == base
                    assert ledger_snapshot() == before and not writes
                    # Switching parent clears the old child; validation must block saving it.
                    choose(single, other['id'])
                    expect(single.locator('[data-expense-child]')).to_have_value('')
                    expect(readout).to_have_text('No subcategory selected.')
                    dialog.get_by_role('button', name='Save', exact=True).click()
                    expect(single.locator('[data-expense-cascade-panel]')).to_be_visible()
                    assert not writes
                    single.locator('[data-expense-choice="'+str(other_children[0]['id'])+'"]').click()
                    form.locator('[data-expense-split-toggle]').check()
                    rows = form.locator('.expense-split-row')
                    for i, (root, leaf, value) in enumerate(((parent, children[0], '50.00'), (other, other_children[0], '50.01'))):
                        choose(rows.nth(i), root['id'], leaf['id'])
                        rows.nth(i).locator('[name=split_amount]').fill(value)
                        expected=rows.nth(i).locator('[data-expense-child] option[value="'+str(leaf['id'])+'"]').text_content()
                        expect(rows.nth(i).locator('[data-expense-subcategory-display]')).to_have_text(expected)
                    assert ledger_snapshot() == before and not writes
                    if width == 768:
                        with page.expect_navigation():
                            dialog.get_by_role('button', name='Save', exact=True).click()
                        tx = db.query_one('SELECT id FROM finance_transactions ORDER BY id DESC LIMIT 1')['id']
                        page.goto(origin+case.url+f'/transactions/{tx}/edit?branch_id={branch}')
                        edit = page.locator('[data-expense-form]')
                        expect(edit.locator('[data-expense-split-toggle]')).to_be_checked()
                        row = edit.locator('.expense-split-row').first
                        expect(row.locator('[data-expense-child]')).to_have_value(str(children[0]['id']))
                        expect(row.locator('[data-expense-cascade]')).to_have_text(row.locator('[data-expense-parent] option:checked').text_content())
                        assert edit.locator('[name=split_amount]').nth(1).input_value() == '50.01'
                        expect(row.locator('[data-expense-subcategory-display]')).to_have_text(leaf_name)
                        # The shared picker is also used by other-source expense edits.
                        with branches.scope(case.b,branch,case.uid):
                            legacy=finance.create_transaction(case.b,'EXPENSE',10001,account,children[0]['id'],'2025-01-01',source_type='FINANCE_OPERATOR',source_ref=f'{branch:032x}',actor_user_id=case.uid)
                        page.goto(origin+case.url+f'/transactions/{legacy}/edit?branch_id={branch}')
                        category_only=page.locator('[data-expense-category-only]');expect(category_only).to_be_visible()
                        expect(category_only.locator('[data-expense-subcategory-display]')).to_have_text(leaf_name)
                        legacy_before=ledger_snapshot();choose(category_only,other['id'])
                        expect(category_only.locator('[data-expense-subcategory-display]')).to_have_text('No subcategory selected.')
                        category_only.locator('[data-expense-choice="'+str(other_children[0]['id'])+'"]').click()
                        other_name=category_only.locator('[data-expense-child] option[value="'+str(other_children[0]['id'])+'"]').text_content()
                        expect(category_only.locator('[data-expense-subcategory-display]')).to_have_text(other_name)
                        assert ledger_snapshot()==legacy_before
                    else:
                        dialog.get_by_role('button', name='Cancel', exact=True).click()
                        expect(dialog).to_be_hidden()
                        assert ledger_snapshot() == before and not writes
                    assert not errors, errors
                    print(f'PASS {engine} {scope} {width}: hierarchy/read-only-subcategory/reset/no-selection-writes/validation/splits/layout/save-or-cancel', flush=True)
                    context.close()
            browser.close()
    finally:
        server.shutdown()
        case.doCleanups()


if __name__ == '__main__':
    main()
