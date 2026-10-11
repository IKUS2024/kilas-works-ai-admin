"""Content-sized chat bubbles on actual routes, using synthetic owners/media only."""
import json
import os
import shutil
import threading
import time
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_home as fixture
from kilas_ai import providers, agent_store


SHORT = 'Halo! Mau dibantu apa?'
LONG_USER = ('Contoh teks panjang yang perlu tetap terbaca dan membungkus secara alami. ' * 10
             + '\nhttps://example.test/' + 'jalurpanjang' * 24)
LONG = '''## Contoh penjelasan

Ini paragraf panjang untuk memastikan teks tetap mudah dibaca ketika ukuran layar berubah. ''' + ('Kalimat berikut membungkus secara alami tanpa memotong isi pesan. ' * 12) + '''

- Langkah pertama dengan **teks tebal**.
- Langkah kedua dengan `kode singkat`.

1. Periksa bahan.
2. Susun hasil.

```python
contoh = "''' + ('x' * 160) + '''"
print(contoh)
```

| Bahan | Catatan | Status |
| --- | --- | --- |
| Naskah | Contoh sintetis | Siap |

https://example.test/''' + ('jalurpanjang' * 24) + '''

Paragraf terakhir tetap utuh.'''


def main():
    baseline = os.environ.get('KILAS_BUBBLE_BASELINE') == '1'
    output = Path(os.environ.get('KILAS_BUBBLE_SCREENSHOTS', '/tmp/kilas-chat-bubbles'))
    output.mkdir(parents=True, exist_ok=True)
    case = fixture.HomeTests('test_old_routes_still_render')
    case.id = lambda: 'bubble-browser'
    case.setUp()
    app = fixture.fixture.base.f.fixture.app.app
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    answer = {'text': SHORT}
    report = {'baseline': baseline, 'provider': 'mocked only', 'surfaces': []}

    def stream(*args, **kwargs):
        for event in fixture.fixture.answer(answer['text']):
            if event['type'] == 'delta':
                text = event['text']
                yield {'type': 'delta', 'text': text[:8]}
                time.sleep(.12)
                yield {'type': 'delta', 'text': text[8:]}
            else:
                yield event

    try:
        with patch.object(providers, 'stream', side_effect=stream), sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=shutil.which('chromium'), args=['--no-sandbox'])
            for width in (320, 390, 820, 1440):
                for agent in (False, True):
                    kind = 'agent' if agent else 'legacy'
                    # Each viewport gets a fresh synthetic owner within the fixture DB,
                    # so unrelated free-tier quotas do not accumulate across layouts.
                    case.owner = fixture.fixture.base.f.fixture.repo.create_user(
                        f'bubble-{kind}-{width}@example.test', 'hash')
                    case.conversation = agent_store.new_conversation(case.owner)
                    cookie = case.client(case.owner).get_cookie('session')
                    context = browser.new_context(viewport={'width': width, 'height': 900}, has_touch=width < 761)
                    context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin}])
                    context.add_init_script("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.__copied=text}}})")
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin) else route.abort())
                    page.goto(origin + ('/kilas-ai/agent?conversation=' + str(case.conversation) if agent else '/products/start'), wait_until='networkidle')
                    field = page.locator('#agent-message' if agent else '#ai-input')
                    timeline = page.locator('#agent-conversation' if agent else '#ai-messages')
                    send = page.locator('#agent-chat-form button[type=submit]' if agent else '#ai-send')
                    role = '.agent-message-' if agent else '.ai-'
                    body = '.agent-message-text' if agent else '.ai-message-text'
                    assistant = timeline.locator(role + 'assistant').last
                    user = timeline.locator(role + 'user').last
                    answer['text'] = SHORT
                    field.fill('hallo')
                    # Preserve each composer's existing submit convention.
                    field.press('Enter') if agent else send.click()
                    expect(assistant.locator(body)).to_have_text(SHORT, timeout=20000)
                    expect(send).to_be_enabled(timeout=20000)
                    expect(field).to_have_value('')
                    measurements = {}
                    for name, message in (('assistant', assistant), ('user', user)):
                        measurements[name] = message.locator(body).evaluate('''e=>{
                            const s=getComputedStyle(e),r=e.getBoundingClientRect(),p=e.parentElement.getBoundingClientRect();
                            return {width:r.width,height:r.height,parentWidth:p.width,left:r.left,right:r.right,
                                parentLeft:p.left,parentRight:p.right,font:s.fontFamily,fontSize:s.fontSize,
                                lineHeight:s.lineHeight,padding:s.padding,minHeight:s.minHeight};
                        }''')
                    page.screenshot(path=str(output / f'{kind}-{width}-short.png'))
                    if not baseline:
                        for name, value in measurements.items():
                            assert value['fontSize'] == '16px', (kind, width, value)
                            assert value['lineHeight'] == '24px', (kind, width, value)
                            assert 'system-ui' in value['font']
                            assert value['height'] <= 44, (kind, width, name, value)
                            assert value['width'] < (230 if name == 'assistant' else 110), (kind, width, name, value)
                        assert abs(measurements['assistant']['left'] - measurements['assistant']['parentLeft']) < 2
                        assert abs(measurements['user']['right'] - measurements['user']['parentRight']) < 2
                    copy = assistant.locator('.ai-copy')
                    expect(copy.locator('svg')).to_have_count(1)
                    copy.click()
                    expect(copy).to_have_attribute('aria-label', 'Tersalin')
                    assert page.evaluate('window.__copied') == assistant.locator(body).text_content()
                    answer['text'] = LONG
                    field.fill(LONG_USER)
                    page.locator('#work-source-files' if agent else '#ai-files').set_input_files(
                        {'name': 'bubble-example.txt', 'mimeType': 'text/plain', 'buffer': b'Synthetic text for layout verification.'})
                    send.click()
                    expect(assistant.locator(body)).to_contain_text('Paragraf terakhir tetap utuh.', timeout=20000)
                    expect(send).to_be_enabled(timeout=20000)
                    expect(page.locator('#work-pending-files' if agent else '#ai-pending')).to_be_empty()
                    expect(assistant.get_by_role('heading', name='Contoh penjelasan')).to_be_visible()
                    expect(assistant.locator('ul li')).to_have_count(2)
                    expect(assistant.locator('ol li')).to_have_count(2)
                    expect(assistant.locator('pre code')).to_contain_text('print(contoh)')
                    expect(assistant.locator('table')).to_have_count(1)
                    assert assistant.locator('pre').evaluate('e=>e.scrollWidth>e.clientWidth')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), (kind, width, 'page overflow')
                    assert timeline.evaluate('e=>e.scrollWidth<=e.clientWidth+1'), (kind, width, 'timeline overflow')
                    for message in (assistant, user):
                        assert message.locator(body).evaluate('e=>e.getBoundingClientRect().width<=e.parentElement.getBoundingClientRect().width+1')
                    copy = assistant.locator('.ai-copy')
                    copy.click()
                    assert page.evaluate('window.__copied') == assistant.locator(body).text_content()
                    timeline.evaluate('e=>e.scrollTop=e.scrollHeight')
                    page.screenshot(path=str(output / f'{kind}-{width}-long.png'))
                    page.reload(wait_until='networkidle')
                    expect(timeline).to_contain_text('Paragraf terakhir tetap utuh.')
                    expect(timeline).to_contain_text('bubble-example.txt')
                    field.fill('Draf tetap tersimpan di composer')
                    field.press('Shift+Enter')
                    assert field.input_value().endswith('\n')
                    assert send.is_enabled()
                    field.fill('')
                    assert not errors, errors
                    report['surfaces'].append({'route': kind, 'width': width, 'short': measurements,
                        'long_markdown_url_code_table_files_copy_streaming_keyboard_reload': 'PASS'})
                    context.close()
            browser.close()
        (output / 'verification.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        server.shutdown()
        case.doCleanups()


if __name__ == '__main__':
    main()
