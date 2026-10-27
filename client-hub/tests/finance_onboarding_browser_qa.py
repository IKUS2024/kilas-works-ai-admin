"""Disposable local Chromium Finance onboarding, navigation and account switching."""
import json
import logging
import os
import shutil
import sys
import threading
import uuid
from pathlib import Path
from unittest.mock import patch


def local_only(event, args):
    if event == 'socket.connect' and isinstance(args[1], tuple) and args[1][0] not in ('127.0.0.1', '::1', 'localhost'):
        raise AssertionError('External network forbidden')
    if event == 'socket.getaddrinfo' and args[0] not in ('127.0.0.1', '::1', 'localhost', None):
        raise AssertionError('External DNS forbidden')


sys.addaudithook(local_only)
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_customer_auth_sessions import CustomerAuthTests
import security


def main():
    case = CustomerAuthTests('test_cross_module_continuity_home_launch_and_deep_link_refresh')
    case.setUp()
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server = make_server('127.0.0.1', 0, case.app, threaded=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    output = Path(os.environ.get('KILAS_ONBOARDING_QA_DIR', '/tmp/kilas-onboarding-qa'))
    output.mkdir(parents=True, exist_ok=True)
    results, errors = [], []
    password = 'synthetic-onboarding-browser-password'
    try:
        with patch.dict(os.environ, {'KILAS_FINANCE_BETA': 'on'}), sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=shutil.which('chromium'), headless=True,
                                         args=['--no-sandbox', '--disable-background-networking'])
            for width in (320, 390, 820, 1440):
                label = uuid.uuid4().hex
                emails = [f'finance-browser-{label}-{index}@example.test' for index in range(2)]
                users = [case.repo.create_user(email, security.hash_password(password)) for email in emails]
                context = browser.new_context(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin) else route.abort())
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))

                def login(email):
                    page.goto(origin + '/login')
                    page.locator('#auth-email').fill(email)
                    page.locator('#auth-password').fill(password)
                    with page.expect_navigation():
                        page.locator('.auth-form button[type=submit]').click()
                    assert page.url == origin + '/products/start'

                login(emails[0])
                page.locator('[data-premium-menu]').click()
                with page.expect_navigation():
                    page.locator('.chat-product-entry button').filter(has_text='Finance').click()
                assert page.url == origin + '/products/finance?step=business'
                field = page.locator('input[name="business_name"]')
                expect(field).to_be_visible()
                assert page.locator('.premium-sidebar-account').count() == 0
                assert page.locator('[data-chat-sidebar]').count() == 1
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                page.screenshot(path=str(output / f'finance-form-{width}.png'), animations='disabled')

                trigger = page.locator('[data-premium-menu]')
                trigger.click()
                expect(trigger).to_have_attribute('aria-expanded', 'true')
                drawer = page.locator('#premium-sidebar')
                expect(drawer).to_have_css('transform', 'matrix(1, 0, 0, 1, 0, 0)')
                bounds = drawer.bounding_box()
                assert bounds and abs(bounds['x']) < 1 and bounds['width'] <= width
                expect(drawer.locator('.chat-library-entry').first).to_be_visible()
                expect(drawer.locator('.chat-product-entry').filter(has_text='Finance')).to_be_visible()
                page.screenshot(path=str(output / f'finance-drawer-{width}.png'), animations='disabled')
                page.keyboard.press('Escape')
                expect(trigger).to_have_attribute('aria-expanded', 'false')
                expect(trigger).to_be_focused()

                profile = page.locator('.kilas-reference-header .kilas-profile-menu')
                profile.locator(':scope > summary').click()
                expect(profile.locator('.kilas-profile-identity')).to_have_text(emails[0])
                profile.locator('.kilas-profile-language > summary').click()
                profile.locator('select[name="language"]').select_option('id')
                with page.expect_navigation():
                    profile.locator('.language-selector button').click()
                expect(page.locator('html')).to_have_attribute('lang', 'id')
                assert page.url == origin + '/products/finance?step=business'

                business_name = f'Synthetic Finance {width}'
                page.locator('input[name="business_name"]').fill(business_name)
                with page.expect_navigation():
                    page.locator('.finance-business-form button[type="submit"]').click()
                assert '/login' not in page.url and '?step=business' not in page.url
                businesses = case.repo.list_businesses_for_user(users[0])
                assert len(businesses) == 1 and businesses[0]['business_name'] == business_name
                page.goto(origin + '/products/finance', wait_until='networkidle')
                expect(page.locator('.finance-existing-list')).to_contain_text(business_name)
                assert page.locator('[data-chat-sidebar]').count() == 1
                page.goto(origin + '/logout')
                assert page.url == origin + '/login'
                page.go_back(wait_until='networkidle')
                page.wait_for_url(origin + '/login')
                page.go_forward(wait_until='networkidle')
                assert page.url == origin + '/login'
                login(emails[1])
                page.goto(origin + '/products/finance?step=business', wait_until='networkidle')
                expect(page.locator('input[name="business_name"]')).to_be_visible()
                body = page.locator('body').inner_text()
                assert emails[0] not in body and business_name not in body
                assert case.repo.list_businesses_for_user(users[1]) == []
                results.append({'width': width, 'current_drawer': True, 'drawer_within_viewport': True,
                                'keyboard_escape_and_focus': True, 'language_change': True,
                                'business_creation': True, 'logout_back_forward': True,
                                'account_switch_isolated': True, 'horizontal_overflow': False})
                context.close()
            browser.close()
        assert not errors, errors
        report = {'result': 'PASS', 'cases': results, 'page_errors': errors,
                  'paid_provider_calls': 0, 'production_writes': 0, 'physical_mobile': False,
                  'evidence': 'Local synthetic app; original supplied screenshots viewed by parent only'}
        (output / 'browser.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        server.shutdown()
        worker.join(3)
        case.doCleanups()


if __name__ == '__main__':
    main()
