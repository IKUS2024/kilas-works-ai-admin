"""Disposable owners: global languages, navigation, Finance forms and responsive layout."""
import os
import json
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_ai_unified as fixture
import repo
import finance_service as finance


def main():
    case = fixture.UnifiedTests('test_ordinary_and_capability_never_create_jobs')
    case.id = lambda: 'global-ui-browser'
    case.setUp()
    app = fixture.base.f.fixture.app.app
    business = repo.create_business(case.owner, 'Home')
    finance.ensure_finance_defaults(business)
    account = finance.list_accounts(business)[0]['id']
    finance.update_account_opening_balance(business, account, 12345678901230000, actor_user_id=case.owner)
    customer = finance.create_customer(business, 'Home', actor_user_id=case.owner)
    invoice = finance.create_finance_invoice(business, customer, '2026-10-03', '2026-10-10',
        [{'description': 'Home', 'quantity': 1, 'unit_price_minor': 125000}], actor_user_id=case.owner)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    output = Path(tempfile.gettempdir()) / 'kilas-global-ui-qa'
    output.mkdir(exist_ok=True)
    results, failures = [], []
    routes = [('home', '/products/start'), ('ai', '/kilas-ai'), ('video', '/kilas-ai/video'),
              ('settings', '/account'), ('preferences', '/kilas-ai/agent?view=settings'),
              ('finance-entry', '/products/finance'), ('finance', f'/business/{business}/finance'),
              ('balances', f'/business/{business}/finance?view=accounts'),
              ('transactions', f'/business/{business}/finance?view=transactions'),
              ('invoices', f'/business/{business}/finance/receivables?section=invoices'),
              ('invoice', f'/business/{business}/finance/invoices/{invoice}'),
              ('reports', f'/business/{business}/finance/reports'),
              ('bills', f'/business/{business}/finance/operations'),
              ('budget', f'/business/{business}/finance/budget')]
    try:
        with patch.dict(os.environ, {'KILAS_FINANCE_BETA': 'on'}), sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            cookie = case.client().get_cookie('session')
            for language in ('id', 'en', 'es', 'zh'):
                for width in (320, 360, 390, 430, 768, 820, 1024, 1440):
                    context = browser.new_context(viewport={'width': width, 'height': 950}, has_touch=width < 761)
                    context.add_cookies([{'name': 'kilas_language', 'value': language, 'url': origin}])
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    for name, url in [('login', '/login'), ('signup', '/register'), ('forgot', '/forgot-password')]:
                        response = page.goto(origin + url, wait_until='networkidle')
                        assert response.status == 200
                        assert page.locator('html').get_attribute('lang') == language
                        assert page.locator('.language-selector').is_visible()
                        results.append((name, language, width))
                    # Exercise the real preference form; the cookie survives a reload and route changes.
                    if width == 390:
                        page.locator('.language-selector select').select_option(language)
                        # Wait for POST/303 navigation before reloading the active document.
                        with page.expect_navigation(wait_until='networkidle'):
                            page.locator('.language-selector button').click()
                        page.reload()
                        assert page.locator('html').get_attribute('lang') == language
                    context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin}])
                    for name, url in routes:
                        try:
                            response = page.goto(origin + url, wait_until='networkidle')
                            assert response.status == 200, response.status
                            assert page.locator('html').get_attribute('lang') == language
                            assert page.locator('body').evaluate('e=>getComputedStyle(e).backgroundColor') == 'rgb(255, 255, 255)'
                            overflow = page.evaluate("""() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,items:[...document.querySelectorAll('body *')].filter(e=>e.getClientRects().length&&e.getBoundingClientRect().right>innerWidth+1).slice(0,10).map(e=>({tag:e.tagName,cls:e.className,right:Math.round(e.getBoundingClientRect().right)}))})""")
                            assert overflow['scroll'] <= width, overflow
                            assert page.locator('a[href="/products/start"]').count() >= 1
                            assert page.locator('a[href*="workspace/more"]').count() == 0
                            if name == 'home':
                                assert page.locator('a[href="/products/services"]').count() >= 2
                                expect(page.get_by_role('heading', name={'id': 'Home', 'en': 'Home', 'es': 'Inicio', 'zh': '首页'}[language], exact=True)).to_be_visible()
                            if name == 'video':
                                expect(page.locator('#video-submit')).to_have_text({'id': 'Susun Video Plan', 'en': 'Create Video Plan', 'es': 'Crear plan de vídeo', 'zh': '生成视频方案'}[language])
                            if name in ('finance', 'balances'):
                                assert '123.456.789.012.300' in page.locator('body').inner_text()
                            if name == 'invoice':
                                assert 'Home' in page.locator('.invoice-document').inner_text()
                            if width in (390, 1440):
                                page.screenshot(path=str(output / f'{name}-{language}-{width}.png'), full_page=True)
                            assert not errors, errors
                            results.append((name, language, width))
                        except Exception as error:
                            failures.append({'page': name, 'language': language, 'width': width, 'error': str(error)[:1000]})
                            page.screenshot(path=str(output / f'failure-{name}-{language}-{width}.png'), full_page=True)
                            errors.clear()
                    context.close()
                    print(f'checked {language} {width}: failures {len(failures)}', flush=True)
            browser.close()
    finally:
        server.shutdown()
        case.doCleanups()
    (output / 'results.json').write_text(json.dumps({'passed': results, 'failures': failures}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'pages_passed': len(results), 'failures': failures, 'evidence': str(output)}, ensure_ascii=False))
    assert not failures


if __name__ == '__main__':
    main()
