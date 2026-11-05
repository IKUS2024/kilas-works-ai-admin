"""Subscription preview responsive navigation and absence of payment side effects."""
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
    parser.add_argument('--output', default='/tmp/kilas-subscription-review')
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
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.browser)
            for language in ('en', 'id', 'es', 'zh'):
                for width in (320, 360, 393, 834, 1440):
                    context = browser.new_context(viewport={'width': width, 'height': 900})
                    context.add_cookies([{'name': 'kilas_language', 'value': language, 'url': origin}])
                    page = context.new_page()
                    errors, writes = [], []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.on('request', lambda r: writes.append(r.url) if r.method not in ('GET', 'HEAD') or not r.url.startswith(origin) else None)
                    page.goto(origin + '/kilas-ai/usage', wait_until='networkidle')
                    profile = page.locator('.kilas-profile-menu')
                    profile.locator('>summary').click()
                    profile.get_by_role('link', name={'en':'Credit & Usage','id':'Kredit & Penggunaan','es':'Créditos y uso','zh':'积分与用量'}[language], exact=True).click()
                    expect(page.locator('#subscription-title')).to_have_text({'en':'Credit & Usage','id':'Kredit & Penggunaan','es':'Créditos y uso','zh':'积分与用量'}[language])
                    assert page.locator('.subscription-features li').count() == 9
                    assert page.locator('.subscription-features small, .subscription-badge, .subscription-plan-intro, .subscription-current p, .subscription-existing p, #subscription-plans .subscription-heading p').count() == 0
                    expect(page.locator('.subscription-notice')).to_have_text({'en':'Preview · Quotas, purchases & credit deductions are inactive','id':'Pratinjau · Kuota, pembelian & potongan kredit belum aktif','es':'Vista previa · Cuotas, compras y deducciones de créditos inactivos','zh':'预览 · 额度、购买及积分扣除尚未启用'}[language])
                    words={'en':('messages','day','month'),'id':('pesan','hari','bulan'),'es':('mensajes','día','mes'),'zh':('条消息','天','月')}[language]
                    messages,day,month=words
                    expect(page.locator('.subscription-quota')).to_have_count(2)
                    expect(page.locator('.subscription-quota').first).to_have_text(f'70 {messages} / {day} · 500 {messages} / {month}')
                    expect(page.locator('.subscription-plan-pro .subscription-quota')).to_have_count(0)
                    expect(page.locator('.subscription-plan-pro .subscription-price')).to_contain_text('Rp99.000')
                    expect(page.locator('.subscription-credit-amount')).to_have_text({'en':'2,000 credits','id':'2.000 kredit','es':'2.000 créditos','zh':'2,000 积分'}[language])
                    expect(page.locator('.subscription-pending')).to_have_text({'en':'Proposed: no expiry · Used after free allowance runs out','id':'Rancangan: tanpa kedaluwarsa · Dipakai setelah kuota gratis habis','es':'Propuesta: sin caducidad · Se usa al agotar la cuota gratuita','zh':'拟议：不过期 · 免费额度用尽后使用'}[language])
                    expect(page.locator('.subscription-estimate')).to_have_count(4)
                    estimates = page.locator('.subscription-estimates').inner_text()
                    assert all(n in estimates for n in ('40', '125', '80', '87', '1'))
                    assert not any(value in page.locator('.subscription-plan-pro').inner_text() for value in ('/ month','/ bulan','/ mes','/ 月','8.000','8,000'))
                    assert width >= 760 or page.locator('.subscription-plan').first.bounding_box()['height'] < 570
                    expect(page.locator('.subscription-current')).to_have_attribute('data-current-plan', 'FREE')
                    assert page.locator('html').get_attribute('lang') == language
                    for label in page.locator('main h1,main h2,main h3,main button,main dt').all_inner_texts():
                        assert not label.rstrip().endswith(('.', '。')), label
                    assert page.locator('main form, main input[type=file]').count() == 0
                    assert 'Kuota dapat berubah' not in page.locator('main').inner_text()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(output / f'plans-{language}-{width}.png'), full_page=True)
                    for action in ('close', 'escape', 'back'):
                        page.locator('#subscription-open-payment').click()
                        expect(page.locator('#payment-title')).to_be_visible()
                        expect(page.locator('#payment-title')).to_be_focused()
                        expect(page.locator('#payment-title')).to_have_text({'en':'Payment','id':'Pembayaran','es':'Pago','zh':'付款'}[language])
                        expect(page.locator('.subscription-bank dd').nth(0)).to_have_text('10180016000684')
                        expect(page.locator('.subscription-bank dd').nth(1)).to_have_text('KILAS TEKNOLOGI KREATIF')
                        assert '/ bulan' not in page.locator('#payment-preview').inner_text() if language != 'id' else True
                        expect(page.locator('#subscription-plans')).not_to_be_visible()
                        for button in page.locator('#payment-preview button').all():
                            expect(button).to_be_disabled()
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                        if action == 'close':
                            page.screenshot(path=str(output / f'payment-{language}-{width}.png'), full_page=True)
                            page.locator('#subscription-close-payment').click()
                        elif action == 'escape': page.keyboard.press('Escape')
                        else: page.go_back()
                        expect(page.locator('#subscription-title')).to_be_visible()
                        expect(page.locator('#subscription-open-payment')).to_be_focused()
                    page.go_forward()
                    expect(page.locator('#payment-title')).to_be_visible()
                    page.reload()
                    expect(page.locator('#payment-title')).to_be_visible()
                    page.keyboard.press('Escape')
                    expect(page.locator('#subscription-title')).to_be_visible()
                    expect(page.locator('.subscription-existing')).to_have_count(0)
                    expect(page.locator('main a[href*="view=legacy"]')).to_have_count(0)
                    expect(page.locator('.subscription-footer')).to_be_visible()
                    expect(page.locator('#subscription-open-payment')).to_be_visible()
                    # Actual legacy route and billing forms remain covered in route tests.
                    assert not errors, errors
                    assert not writes, writes
                    report.append({'language': language, 'width': width, 'overflow': False, 'errors': errors, 'writes': writes})
                    context.close()
            browser.close()
    finally: server.shutdown()
    (output / 'browser-report.json').write_text(json.dumps(report, indent=2))
    print(f'PASS: {len(report)} viewport/language cases; profile navigation, inert payment, repeated open/close, Escape, Back/Forward, reload, retained footer and removed lower billing section.')

if __name__ == '__main__': main()
