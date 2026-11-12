"""Real Chromium account keyboard/labels QA; synthetic SQLite, no external calls."""
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import threading


def local_only(event, args):
    if event == 'socket.connect' and isinstance(args[1], tuple) and args[1][0] not in ('127.0.0.1', '::1', 'localhost'):
        raise AssertionError('External network forbidden')
    if event == 'socket.getaddrinfo' and args[0] not in ('127.0.0.1', '::1', 'localhost', None):
        raise AssertionError('External DNS forbidden')


sys.addaudithook(local_only)
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_customer_auth_sessions import CustomerAuthTests


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case = CustomerAuthTests('test_cross_module_continuity_home_launch_and_deep_link_refresh')
    case.setUp()
    server = None
    results, errors, unexpected_posts = [], [], []
    output = Path(os.environ.get('ACCOUNT_UI_QA_DIR', '/tmp/account-ui-qa'))
    output.mkdir(parents=True, exist_ok=True)
    try:
        server = make_server('127.0.0.1', 0, case.app, threaded=True)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=shutil.which('chromium'), headless=True,
                args=['--no-sandbox', '--disable-background-networking'])
            for width in (390, 1440):
                context = browser.new_context(viewport={'width': width, 'height': 900}, locale='en-US')
                context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: unexpected_posts.append(request.url)
                    if request.method == 'POST' and request.url != origin + '/login' else None)
                page.goto(origin + '/login', wait_until='networkidle')
                expect(page.locator('html')).to_have_attribute('lang', 'en')
                toggle = page.locator('.password-toggle')
                expect(toggle).to_have_attribute('aria-label', 'Show password')
                toggle.click()
                expect(toggle).to_have_attribute('aria-label', 'Hide password')
                expect(page.locator('#auth-password')).to_have_attribute('type', 'text')
                toggle.click()
                expect(toggle).to_have_attribute('aria-label', 'Show password')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'login overflow'
                page.locator('#auth-email').fill(case.email)
                page.locator('#auth-password').fill(case.password)
                with page.expect_navigation():
                    page.locator('.auth-form button[type=submit]').click()
                page.goto(origin + '/account#security', wait_until='networkidle')
                def selected(name):
                    expect(page.locator(f'#account-tab-{name}')).to_have_attribute('aria-selected', 'true')
                    expect(page.locator(f'#account-panel-{name}')).to_be_visible()
                    assert page.locator('[data-account-tab][tabindex="0"]').count() == 1
                    assert page.url.endswith('#' + name)
                selected('security')
                page.locator('#account-tab-security').focus()
                for key, name in [('ArrowRight', 'personal'), ('ArrowLeft', 'security'), ('Home', 'personal'), ('End', 'security')]:
                    page.keyboard.press(key)
                    selected(name)
                    expect(page.locator(f'#account-tab-{name}')).to_be_focused()
                page.reload(wait_until='networkidle')
                selected('security')
                page.locator('#account-tab-personal').click()
                selected('personal')
                page.locator('[data-profile-edit]').first.click()
                expect(page.get_by_role('dialog', name='Edit personal profile')).to_be_visible()
                page.locator('[data-profile-close]').click()
                page.locator('[data-email-change-open]').first.click()
                expect(page.get_by_role('dialog', name='Change Email')).to_be_visible()
                page.locator('[data-email-change-close]').click()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'account overflow'
                page.screenshot(path=str(output / f'account-{width}.png'), full_page=True)
                results.append({'width': width, 'password_labels': 'PASS', 'keyboard_tabs': 'PASS', 'named_dialogs': 'PASS', 'overflow': False})
                context.close()
            browser.close()
        assert not errors and not unexpected_posts, (errors, unexpected_posts)
        report = {'result': 'PASS', 'cases': results, 'external_calls': 0, 'production_mutations': 0}
        (output / 'result.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        if server:
            server.shutdown()
            worker.join(3)
        case.doCleanups()


if __name__ == '__main__':
    main()
