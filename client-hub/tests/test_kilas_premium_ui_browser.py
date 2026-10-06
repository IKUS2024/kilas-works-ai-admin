"""Rendered white customer UI acceptance on disposable local owners only."""
import os
import tempfile
import threading
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_ai_unified as fixture
import repo
import finance_service as finance
import security


def main():
    case = fixture.UnifiedTests('test_ordinary_and_capability_never_create_jobs')
    case.id = lambda: 'premium-ui-browser'
    case.setUp()
    app = fixture.base.f.fixture.app.app
    business = repo.create_business(case.owner, 'Kilas UI QA')
    finance.ensure_finance_defaults(business)
    account = finance.list_accounts(business)[0]['id']
    finance.update_account_opening_balance(business, account, 123456789012300, actor_user_id=case.owner)
    reset_token, reset_hash = security.generate_reset_token()
    repo.create_password_reset_token(case.owner, reset_hash, (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat())
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    output = Path(tempfile.gettempdir()) / 'kilas-premium-ui-qa'
    output.mkdir(exist_ok=True)
    try:
        with patch.dict(os.environ, {'KILAS_FINANCE_BETA': 'on'}), sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            cookie = case.client().get_cookie('session')
            for width in (320, 360, 390, 430, 768, 820, 1024, 1440):
                context = browser.new_context(viewport={'width': width, 'height': 1000}, has_touch=width < 761, reduced_motion='reduce')
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))

                def capture(name, url):
                    response = page.goto(origin + url, wait_until='networkidle')
                    assert response.status == 200, (name, response.status, page.url)
                    page.evaluate('document.fonts.ready')
                    assert page.locator('body').evaluate('e=>getComputedStyle(e).backgroundColor') == 'rgb(255, 255, 255)', name
                    contrast = page.evaluate("""() => {
                      const rgba=s=>{const m=s.match(/[\\d.]+/g);if(!m)return [255,255,255,1];const v=m.map(Number);if(s.startsWith('color(srgb'))for(let i=0;i<3;i++)v[i]*=255;return v};
                      const lum=c=>c.map(v=>{v/=255;return v<=.04045?v/12.92:Math.pow((v+.055)/1.055,2.4)}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
                      const issues=[];
                      for(const e of document.querySelectorAll('body *')) {
                        if(![...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()))continue;
                        if(!e.getClientRects().length||e.closest('[hidden],button:disabled,[inert]'))continue;
                        const s=getComputedStyle(e);if(s.visibility!=='visible'||Number(s.opacity)<1)continue;
                        let p=e,bg=[255,255,255],layers=[];
                        while(p){layers.push(rgba(getComputedStyle(p).backgroundColor));p=p.parentElement;}
                        for(const layer of layers.reverse()){const alpha=layer.length>3?layer[3]:1;bg=bg.map((v,i)=>layer[i]*alpha+v*(1-alpha));}
                        const a=lum(rgba(s.color).slice(0,3)),b=lum(bg),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
                        const large=parseFloat(s.fontSize)>=24||(parseFloat(s.fontSize)>=18.66&&parseInt(s.fontWeight)>=700);
                        if(ratio<(large?3:4.5))issues.push({tag:e.tagName,cls:e.className,ratio:ratio.toFixed(2),color:s.color,bg});
                      }
                      return issues;
                    }""")
                    assert not contrast, (name, width, contrast[:12])
                    page.screenshot(path=str(output / f'{name}-{width}.png'), full_page=True)
                    if width == 1440:
                        css = page.evaluate("[...document.styleSheets].map(s=>{try{return [...s.cssRules].map(r=>r.cssText).join('\\n')}catch{return ''}}).join('\\n')")
                        rendered = re.sub(r'<link[^>]*rel="stylesheet"[^>]*>', '', page.content())
                        (output / f'{name}-rendered.html').write_text(rendered.replace('</head>', '<style>' + css + '</style></head>'), encoding='utf-8')
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, width, page.evaluate("[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,12).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right}))"))

                for name, url in [('login', '/login'), ('signup', '/register'), ('forgot', '/forgot-password'), ('reset', '/reset-password/' + reset_token)]:
                    capture(name, url)
                    expect(page.locator('form input:not([type=hidden])').first).to_be_visible()
                page.goto(origin + '/login')
                page.locator('#auth-password').fill('synthetic-local-only')
                page.get_by_role('button', name='Tampilkan password', exact=True).click()
                assert page.locator('#auth-password').get_attribute('type') == 'text'
                context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin}])
                capture('home', '/products/start')
                expect(page.get_by_role('heading', name='Home', exact=True)).to_be_visible()
                assert page.locator('a[href="/products/services"]').count() >= 2
                assert page.locator('.premium-navigation').get_by_text('Assist').count() == 0
                if width < 761:
                    page.get_by_role('button', name='Buka navigasi', exact=True).click()
                    expect(page.locator('.premium-sidebar')).to_be_visible()
                    assert not page.locator('.premium-sidebar').evaluate('e=>e.inert')
                    page.screenshot(path=str(output / f'home-navigation-{width}.png'))
                    page.keyboard.press('Escape')
                    assert page.locator('.premium-sidebar').evaluate('e=>e.inert')
                capture('connections', '/kilas-ai/agent?view=connections')
                expect(page.get_by_role('button', name='Hubungkan Google', exact=True)).to_have_count(0)
                expect(page.get_by_role('link', name='Connections', exact=True)).to_have_count(0)
                capture('preferences', '/kilas-ai/agent?view=settings')
                capture('schedules', '/kilas-ai/automation')
                capture('schedule-form', '/kilas-ai/automation/new')
                capture('account', '/account')
                page.locator('[data-profile-edit]').last.click()
                expect(page.locator('#account-profile-dialog')).to_be_visible()
                assert page.locator('#account-profile-dialog').evaluate('e=>e.getBoundingClientRect().width<=innerWidth-16')
                page.screenshot(path=str(output / f'account-dialog-{width}.png'))
                page.keyboard.press('Escape')
                capture('subscription', '/kilas-ai/usage')
                capture('finance-entry', '/products/finance')
                capture('finance-setup', '/products/finance?step=business')
                capture('chat', '/kilas-ai')
                assert page.locator('.ai-mode-tabs,#ai-search').count() == 0
                if width < 761:
                    page.get_by_role('button', name='Buka riwayat', exact=True).click()
                    page.screenshot(path=str(output / f'chat-navigation-{width}.png'))
                    page.keyboard.press('Escape')
                for name, suffix in [('finance-home', ''), ('finance-transactions', '?view=transactions'), ('finance-accounts', '?view=accounts'), ('finance-invoices', '/receivables'), ('finance-reports', '/reports')]:
                    capture(name, f'/business/{business}/finance{suffix}')
                assert not errors, errors
                context.close()
            browser.close()
    finally:
        server.shutdown()
        case.doCleanups()
    print(f'PASS: auth/Home/AI/no Connections/preferences/account/dialogs/subscription/Finance; white canvas and no overflow at eight widths; screenshots {output}')


if __name__ == '__main__':
    main()
