"""Real composers with controlled SSE completion; no provider calls or keyboard UA assumptions."""
import threading
import test_kilas_work_documents as fixture
from kilas_ai import store
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server


def main():
    app = fixture.fixture.app.app
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            # Small fine-pointer and large coarse-pointer cases prevent width-based shortcuts.
            for width, touch in ((320, True), (360, True), (390, True), (820, True), (390, False), (1440, False)):
                owner = fixture.fixture.repo.create_user(f'focus-{width}-{touch}@example.test', 'hash')
                conversation = fixture.agent_store.new_conversation(owner)
                thread = store.create_thread(owner)
                client = app.test_client()
                with client.session_transaction() as state:
                    state.update(user_id=owner, role='CLIENT_OWNER', agent_conversation_id=conversation, _csrf_token='focus-test')
                cookie = client.get_cookie('session')
                context = browser.new_context(viewport={'width': width, 'height': 844}, has_touch=touch)
                context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin}])
                for work in (False, True):
                    page = context.new_page()
                    page.goto(origin + (f'/kilas-ai/agent?conversation={conversation}' if work else f'/kilas-ai/threads/{thread}'), wait_until='networkidle')
                    selector = '#agent-message' if work else '#ai-input'
                    form = '#agent-chat-form' if work else '#ai-composer'
                    button = f'{form} button[type="submit"]' if work else '#ai-send'
                    assert page.evaluate("matchMedia('(hover: hover) and (pointer: fine)').matches") == (not touch)
                    page.evaluate('''({selector, work}) => {
                        const input = document.querySelector(selector);
                        window.focusEvents = 0;
                        input.addEventListener('focus', () => window.focusEvents++);
                        const original = window.fetch;
                        window.fetch = (url, options = {}) => {
                            if (options.method !== 'POST') return original(url, options);
                            const encoder = new TextEncoder();
                            const frame = value => work ? 'data: '+JSON.stringify(value)+'\\n\\n' : 'event: '+value.type+'\\ndata: '+JSON.stringify(value)+'\\n\\n';
                            const stream = new ReadableStream({start(controller) {
                                controller.enqueue(encoder.encode(frame({type:'delta', text:'Jawaban uji.'})));
                                window.finishResponse = () => {
                                    controller.enqueue(encoder.encode(frame({type:'done'})));
                                    controller.close();
                                };
                                options.signal?.addEventListener('abort', () => controller.error(new DOMException('Stopped','AbortError')));
                            }});
                            return Promise.resolve(new Response(stream, {headers:{'Content-Type':'text/event-stream'}}));
                        };
                    }''', {'selector': selector, 'work': work})
                    input = page.locator(selector)
                    input.tap() if touch else input.click()
                    input.fill('Halo Kilas')
                    # Submitting while focused reproduces keyboard-send instead of button blur.
                    if work:
                        input.press('Enter')
                    else:
                        page.locator(form).evaluate('(form) => form.requestSubmit()')
                    page.wait_for_function('typeof window.finishResponse === "function"')
                    focused_during_stream = input.evaluate('(el) => el === document.activeElement')
                    if touch:
                        assert not focused_during_stream
                    before = page.evaluate('({focus:focusEvents, y:scrollY, height:visualViewport.height, top:visualViewport.offsetTop})')
                    page.evaluate('finishResponse()')
                    expect(page.locator(button)).to_be_enabled()
                    expect(input).to_have_value('')
                    after = page.evaluate('({focus:focusEvents, y:scrollY, height:visualViewport.height, top:visualViewport.offsetTop})')
                    assert after['focus'] == before['focus'] + (0 if touch or focused_during_stream else 1), (width, touch, work, before, after)
                    assert input.evaluate('(el) => el === document.activeElement') == (not touch)
                    assert all(after[key] == before[key] for key in ('y', 'height', 'top')), (width, touch, work, before, after)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    input.tap() if touch else input.click()
                    expect(input).to_be_focused()
                    input.fill('Baris pertama')
                    input.press('Shift+Enter')
                    assert '\n' in input.input_value()
                    # Stop follows the same completion cleanup without stealing mobile focus.
                    if not work:
                        page.locator(form).evaluate('(form) => form.requestSubmit()')
                        expect(page.locator('#ai-stop')).to_be_visible()
                        page.locator('#ai-stop').click()
                        expect(page.locator(button)).to_be_enabled()
                        assert input.evaluate('(el) => el === document.activeElement') == (not touch)
                    page.close()
                context.close()
            browser.close()
    finally:
        server.shutdown()
    print('PASS: Chat/Work submit blur, streaming/DONE focus and viewport, desktop autofocus, manual touch, Shift+Enter, Chat Stop; 320/360/390/820/1440; capability rather than width')


if __name__ == '__main__':
    main()
