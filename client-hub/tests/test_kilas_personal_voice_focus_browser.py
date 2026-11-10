"""Add Voice stays separate from script creation; disposable DB, mocked providers."""
import json
import os
import shutil
import threading
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server
from test_kilas_personal_voice import PersonalVoiceTests, personal
from test_kilas_audio import f, provider, wav


def main():
    PersonalVoiceTests.setUpClass()
    server = make_server('127.0.0.1', 0, f.app.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    output = Path('/tmp/kilas-add-voice-focused-browser')
    output.mkdir(exist_ok=True)
    report = []
    try:
        with patch.object(provider, 'voices', return_value=[{'id': 'stockPrivate123', 'name': 'Kilas Natural', 'style': 'Natural'}]), patch.object(provider, 'clone_voice', return_value='personalPrivate123') as clone, patch.object(provider, 'speech') as speech, sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM') or shutil.which('chromium'), args=['--no-sandbox'])
            for width in (320, 390, 1440):
                case = PersonalVoiceTests('test_create_persist_retry_no_public_identifier')
                case.id = lambda: f'focused-add-voice-{width}'
                case.setUp()
                case.credit(300)
                context = browser.new_context(viewport={'width': width, 'height': 950})
                cookie = case.client.get_cookie('session')
                context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin}, {'name': 'kilas_language', 'value': 'id', 'url': origin}])
                page = context.new_page()
                errors, generation_posts = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: generation_posts.append(request.url) if request.method == 'POST' and '/kilas-translator/jobs' in request.url else None)
                page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin) else route.abort())
                page.goto(origin + '/kilas-translator?mode=voiceover', wait_until='networkidle')
                page.locator('[name=voice_kind][value=personal]').check()
                script = page.locator('#audio-script')
                expect(script).to_have_value('')
                page.locator('#add-saved-voice').click()

                def focused():
                    expect(page.locator('#voice-recorder')).to_be_visible()
                    for selector in ('.voice-script-workspace', '#audio-script', '#voice-dictation', '#voice-script-assist', '#voice-translate-toggle', '#voice-generate', '.audio-heading p'):
                        expect(page.locator(selector)).to_be_hidden()
                    expect(page.locator('#voice-generate')).to_be_disabled()
                    expect(page.locator('#record-voice-name')).to_be_visible()
                    expect(page.locator('#voice-sample-file')).to_be_visible()
                    expect(page.locator('#save-personal-voice')).to_be_visible()

                focused()
                page.locator('#voice-sample-file').set_input_files({'name': 'synthetic-voice.wav', 'mimeType': 'audio/wav', 'buffer': wav(2)})
                expect(page.locator('#record-playback')).to_be_visible()
                page.locator('#voice-consent').check()
                # Failed saves keep the sample and remain in Add Voice, never reveal a script request.
                with patch.object(provider, 'clone_voice', side_effect=provider.ProviderError()):
                    page.locator('#save-personal-voice').click()
                    expect(page.locator('#record-error')).to_be_visible()
                focused()
                expect(script).to_have_value('')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output / f'add-voice-{width}.png'), full_page=True)
                with page.expect_response('**/personal-voice') as response:
                    page.locator('#save-personal-voice').click()
                assert response.value.ok
                expect(page.locator('#voice-recorder')).to_be_hidden()
                expect(script).to_be_visible()
                expect(script).to_have_value('')
                expect(page.locator('#voice-generate')).to_be_visible()
                assert personal.get(case.user) == 'personalPrivate123'

                # Cancelling, repeated open, and switching voice preserve the original draft.
                script.fill('Draf ini harus tetap ada.')
                saved = page.locator('#saved-voice-choice').input_value()
                before = clone.call_count
                for _ in range(2):
                    page.locator('#add-saved-voice').click()
                    focused()
                    # Even an implicit/programmatic form submit cannot start paid generation here.
                    page.locator('#voiceover-panel form').evaluate("form => form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}))")
                    page.locator('#record-cancel').click()
                    expect(page.locator('#add-saved-voice')).to_be_focused()
                    expect(script).to_be_visible()
                    expect(script).to_have_value('Draf ini harus tetap ada.')
                    expect(page.locator('#saved-voice-choice')).to_have_value(saved)
                page.locator('#add-saved-voice').click()
                focused()
                page.locator('[name=voice_kind][value=kilas]').check()
                expect(page.locator('#voice-recorder')).to_be_hidden()
                expect(script).to_be_visible()
                expect(page.locator('#voice-generate')).to_be_enabled()
                expect(script).to_have_value('Draf ini harus tetap ada.')
                assert clone.call_count == before
                assert not generation_posts and not errors, (generation_posts, errors)
                speech.assert_not_called()
                report.append({'width': width, 'empty_script_save_failure_retry_cancel_reopen_voice_switch': 'PASS', 'generation_requests': 0, 'page_errors': 0})
                context.close()
                case.doCleanups()
            browser.close()
        (output / 'verification.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
