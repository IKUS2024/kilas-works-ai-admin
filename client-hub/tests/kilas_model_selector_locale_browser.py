"""Selector locale regression: real templates/scripts, synthetic catalogs, no inference."""
import json
import shutil
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_model_preferences as fixture
from kilas_ai import chat_models, image_models
import ui_i18n


def main():
    case = fixture.PreferenceTests('test_unsent_home_choice_survives_new_authenticated_sessions_and_reopening')
    case.setUp()
    app = fixture.fixture.fixture.fixture.base.f.fixture.app.app
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    output = Path('/tmp/kilas-model-selector-locale-browser'); output.mkdir(exist_ok=True)
    rows = []
    labels = {'id': ('Pilih model', 'Model gambar'), 'en': ('Choose model', 'Image model'),
              'es': ('Elegir modelo', 'Modelo de imagen'), 'zh': ('选择模型', '图像模型')}
    paths = {'home': '/products/start', 'thread': f'/kilas-ai/threads/{case.thread}',
             'conversation': f'/kilas-ai/agent?conversation={case.conversation}'}
    for kind, model in (('chat', 'gpt-6-luna'), ('image', 'gpt-image-1-mini')):
        case.choose(kind, model)
        case.choose(kind, model, surface='thread', conversation_id=case.thread)
        case.choose(kind, model, surface='conversation', conversation_id=case.conversation)
    def metadata(module, model):
        return {**module.spec(model), 'available': model not in ('claude-sonnet-5-5', 'claude-opus-5-5'),
                'status': 'not_configured' if model == 'claude-sonnet-5-5' else 'access_unavailable' if model == 'claude-opus-5-5' else 'verified'}
    try:
        with patch.object(chat_models, 'check', side_effect=lambda m: metadata(chat_models, m)), \
             patch.object(image_models, 'check', side_effect=lambda m: metadata(image_models, m)), \
             patch.object(chat_models.requests, 'get', side_effect=AssertionError('Provider IO forbidden')), \
             sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=shutil.which('chromium'), args=['--no-sandbox'])
            context = browser.new_context(viewport={'width': 1280, 'height': 900})
            cookie = case.client().get_cookie('session')
            context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin}])
            page = context.new_page(); errors = []; paid = []; fail = {'catalog': False, 'choose': False}
            page.on('pageerror', lambda e: errors.append(str(e)))
            def route(r):
                url = r.request.url
                if not url.startswith(origin): r.abort(); return
                if r.request.method == 'POST' and not url.endswith(('/language', '/chat/model', '/chat/image-model', '/work/preferences')):
                    paid.append(url); r.abort(); return
                if fail['catalog'] and '/kilas-ai/chat/models' in url:
                    r.fulfill(status=503, content_type='application/json', body='{}'); return
                if fail['choose'] and url.endswith('/chat/model'):
                    r.fulfill(status=503, content_type='text/plain', body='Synthetic invalid response'); return
                r.continue_()
            page.route('**/*', route)
            for surface, path in paths.items():
                page.goto(origin + path, wait_until='networkidle')
                for locale, headings in labels.items():
                    with page.expect_navigation(wait_until='networkidle'):
                        page.locator('form.language-selector').first.evaluate(
                            "(form, language) => {form.elements.language.value=language;form.requestSubmit();}", locale)
                    expect(page.locator('html')).to_have_attribute('lang', locale)
                    html = context.request.get(origin + path).text()
                    for kind, heading, name in zip(('chat', 'image'), headings, ('GPT-6 Luna', 'GPT Image 1 Mini')):
                        assert f'id="{kind}-model-heading">{heading}</h2>' in html
                        assert f'aria-label="{heading}: {name}"' in html
                        root = page.locator('[data-model-kind=' + kind + ']')
                        expect(root.locator('[data-model-label]')).to_have_text(name)
                        expect(root.locator('.chat-model-trigger')).to_have_attribute('aria-label', heading + ': ' + name)
                        expect(root.locator('.chat-model-trigger')).to_have_attribute('title', name)
                        root.locator('.chat-model-trigger').click()
                        expect(root.locator('h2')).to_have_text(heading)
                        close = ui_i18n.CATALOG['Tutup'].get(locale, 'Tutup') if locale != 'en' else ui_i18n.EN_MESSAGES.get('Tutup', ui_i18n.CATALOG['Tutup']['en'])
                        expect(root.locator('[data-model-close]')).to_have_attribute('aria-label', close)
                        keys = ('Belum tersedia', 'Akses belum tersedia') if kind == 'chat' else ()
                        notes = [key if locale == 'id' else ui_i18n.CATALOG[key][locale] for key in keys]
                        expect(root.locator('.chat-model-option:disabled small')).to_have_text(notes)
                        page.keyboard.press('Escape')
                    # A malformed selection response uses localized UI copy and preserves choice.
                    fail['choose'] = True
                    page.locator('[data-model-kind=chat] .chat-model-trigger').click()
                    page.locator('#chat-model-dialog').get_by_role('radio', name='GPT-6.1 Sol', exact=False).click()
                    key = 'Model belum dapat dipilih.'
                    expect(page.locator('#chat-model-dialog [data-model-state]')).to_have_text(key if locale == 'id' else ui_i18n.CATALOG[key][locale])
                    expect(page.locator('[data-model-kind=chat] [data-model-label]')).to_have_text('GPT-6 Luna')
                    fail['choose'] = False; page.keyboard.press('Escape')
                    fail['catalog'] = True
                    page.locator('[data-model-kind=chat] .chat-model-trigger').click()
                    key = 'Daftar model belum dapat dimuat. Buka daftar lagi untuk mencoba.'
                    expect(page.locator('#chat-model-dialog [data-model-state]')).to_have_text(key if locale == 'id' else ui_i18n.CATALOG[key][locale])
                    fail['catalog'] = False; page.keyboard.press('Escape')
                    if locale == 'en' and surface == 'home':
                        page.locator('[data-model-kind=image] .chat-model-trigger').click()
                        page.screenshot(path=str(output / 'english-image-selector.png')); page.keyboard.press('Escape')
                    rows.append({'surface': surface, 'locale': locale, 'server_and_hydrated_labels': 'PASS',
                                 'language_switch': 'PASS', 'menus_and_accessibility': 'PASS', 'recoverable_errors': 'PASS'})
            assert not errors, errors
            assert not paid, paid
            browser.close()
        report = {'checks': rows, 'provider_io': False, 'paid_inference': False, 'page_errors': errors}
        (output / 'verification.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    finally:
        server.shutdown(); case.doCleanups()


if __name__ == '__main__': main()
