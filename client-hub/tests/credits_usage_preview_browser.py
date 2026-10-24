"""Responsive screenshot and interaction verification, using the data-free preview app."""
import argparse
import json
import logging
from pathlib import Path
import sys
import threading

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from preview_credits_usage import create_preview


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='/tmp/kilas-credits-review')
    parser.add_argument('--browser', default='/usr/bin/chromium')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server = make_server('127.0.0.1', 0, create_preview(), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    report = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=args.browser)
            for language in ('en', 'id'):
                for device, width, height in (('desktop', 1440, 1080), ('tablet', 834, 1112), ('mobile', 390, 844), ('narrow', 320, 800), ('laptop', 1024, 900)):
                    context = browser.new_context(viewport={'width': width, 'height': height}, has_touch=width < 900)
                    context.add_cookies([{'name': 'kilas_language', 'value': language, 'url': origin}])
                    page = context.new_page()
                    errors, unexpected, writes = [], [], []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('request', lambda req: unexpected.append(req.url) if not req.url.startswith(origin) else None)
                    page.on('request', lambda req: writes.append(req.url) if req.method not in ('GET', 'HEAD') else None)
                    page.goto(origin + '/kilas-ai/usage', wait_until='networkidle')
                    page.evaluate('document.fonts.ready')
                    expect(page.locator('h1')).to_have_text('Credits & Usage' if language == 'en' else 'Kredit & Penggunaan')
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (language, width, 'overflow')
                    expect(page.locator('.credits-pay-button')).to_be_disabled()
                    assert page.locator('.credits-topup form').count() == 0
                    assert page.locator('.credits-estimate strong').inner_text() == '—'
                    assert page.locator('.credits-balance-value>span').first.inner_text() == '—'
                    assert page.locator('.credits-preview-note a').get_attribute('href').endswith('?view=legacy')
                    if device in ('desktop', 'tablet', 'mobile'):
                        page.screenshot(path=str(output / f'credits-{language}-{device}.png'), full_page=True)
                    # Arbitrary amount entry stays presentation-only and never produces a rate.
                    page.locator('#credits-amount').fill('123.45')
                    page.locator('#credits-amount').blur()
                    expect(page.locator('#credits-amount-error')).not_to_be_visible()
                    page.locator('#credits-currency').select_option('IDR')
                    expect(page.locator('[data-credits-currency-symbol]')).to_have_text('Rp')
                    expect(page.locator('#credits-amount')).to_have_value('')
                    page.locator('#credits-amount').fill('-1')
                    page.locator('#credits-amount').blur()
                    expect(page.locator('#credits-amount-error')).to_be_visible()
                    page.locator('#credits-amount').fill('50000')
                    page.locator('#credits-amount').blur()
                    expect(page.locator('#credits-amount-error')).not_to_be_visible()
                    expect(page.locator('.credits-pay-button')).to_be_disabled()
                    # WAI tab keyboard behavior and distinct empty states.
                    page.locator('#credits-usage-tab').focus()
                    page.keyboard.press('ArrowRight')
                    expect(page.locator('#credits-payments-panel')).to_be_visible()
                    expect(page.locator('#credits-payments-tab')).to_be_focused()
                    expect(page.locator('#credits-usage-panel')).not_to_be_visible()
                    if device == 'desktop':
                        page.screenshot(path=str(output / f'credits-{language}-payments.png'), full_page=True)
                    page.keyboard.press('Home')
                    expect(page.locator('#credits-usage-panel')).to_be_visible()
                    expect(page.locator('[data-premium-menu], #premium-sidebar, .premium-backdrop')).to_have_count(0)
                    expect(page.locator('.kilas-tool-home')).to_be_visible()
                    profile = page.locator('.kilas-profile-menu')
                    profile.locator('>summary').click()
                    expect(profile.locator('a').first).to_have_text('Credits & Usage' if language == 'en' else 'Kredit & Penggunaan')
                    profile.locator('>summary').click()
                    assert not errors, errors
                    assert not unexpected, unexpected
                    assert not writes, writes
                    report.append({'language': language, 'width': width, 'height': height, 'overflow': False, 'console_errors': errors, 'external_requests': unexpected, 'write_requests': writes})
                    context.close()
            browser.close()
    finally:
        server.shutdown()
    (output / 'browser-report.json').write_text(json.dumps(report, indent=2))
    print(f'PASS: {len(report)} responsive/localization cases; tabs, input, disabled payment, navigation and no network writes. Screenshots: {output}')


if __name__ == '__main__':
    main()
