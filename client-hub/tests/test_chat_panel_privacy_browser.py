"""Bounded real route/draft/privacy UI coverage; only synthetic owners, no provider IO."""
import json
import os
import shutil
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_tabs_copy as f


def main():
    stage = os.environ.get('KILAS_CHAT_PANEL_STAGE', 'final')
    case = f.TabsCopyTests('test_feature_routes_keep_inputs_user_content_and_essential_notices')
    case.id = lambda: 'chat-panel-privacy-browser'
    case.setUp()
    server = make_server('127.0.0.1', 0, f.fixture.app.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    output = Path(os.environ.get('KILAS_CHAT_PANEL_SCREENSHOTS', '/tmp/chat-panel-privacy'))/stage
    output.mkdir(parents=True, exist_ok=True)
    report = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=shutil.which('chromium'), args=['--no-sandbox'])
            for width in (320, 1440):
                context = browser.new_context(viewport={'width': width, 'height': 1000})
                cookie = case.client.get_cookie('session')
                context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin}])
                page = context.new_page(); errors = []; calls = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda req: calls.append(req.url) if req.method == 'POST' else None)
                page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin) else route.abort())
                keys = ('agent_chat', 'voiceover') if stage == 'baseline' else ('home', 'legacy_chat', 'agent_chat', 'voiceover')
                for key in keys:
                    response = page.goto(origin+case.paths[key], wait_until='networkidle')
                    assert response.status == 200
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (key, width)
                    if stage == 'final' and key in ('home', 'legacy_chat', 'agent_chat'):
                        expect(page.locator('[data-chat-projects]')).to_have_count(0)
                        expect(page.locator('script[src*="kilas_chat_projects"]')).to_have_count(0)
                        expect(page.locator('[data-home-task]')).to_have_count(3)
                        field = page.locator('#agent-message' if key == 'agent_chat' else '#ai-input')
                        field.fill('Draf belum dikirim tetap ada.')
                        if width == 320:
                            page.locator('[data-premium-menu]').click(); page.keyboard.press('Escape')
                        expect(field).to_have_value('Draf belum dikirim tetap ada.')
                        field.fill('')
                    if stage == 'final' and key == 'voiceover':
                        page.locator('#voice-video-script>summary').click()
                        expect(page.locator('.voice-video-privacy')).to_have_count(0)
                        expect(page.locator('#voice-video-consent')).to_be_disabled()
                        expect(page.locator('#voice-video-consent')).to_have_attribute('aria-describedby', 'voice-video-privacy-terms')
                        script = page.locator('#audio-script'); script.fill('Naskah belum dikirim tetap ada.')
                        expect(page.locator('#voice-video-privacy-terms')).to_contain_text('4.000')
                        with page.expect_popup() as popup:
                            page.get_by_role('link', name='Kebijakan Privasi', exact=True).click()
                        policy = popup.value; policy.wait_for_load_state()
                        expect(policy.locator('#audio-processing')).to_contain_text('ElevenLabs memakai logging bawaan')
                        assert policy.url.endswith('/privacy#audio-processing')
                        policy.close(); expect(script).to_have_value('Naskah belum dikirim tetap ada.')
                    page.screenshot(path=str(output/f'{key}-{width}.png'))
                    report.append({'surface': key, 'width': width, 'status': 'PASS'})
                assert not errors, errors
                assert all(url.endswith('/kilas-ai/work/preferences') for url in calls), calls
                context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps({'pages': report, 'provider_io': False, 'generation_posts': 0}, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        server.shutdown(); case.doCleanups()


if __name__ == '__main__': main()
