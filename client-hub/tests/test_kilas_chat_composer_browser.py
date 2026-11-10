"""Immediate composer feedback, square stop, and safe retry on real chat routes."""
import json
import logging
import shutil
import threading
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_home as fixture
import test_kilas_chat_models as model_fixture
from kilas_ai import chat_models, providers, agent_store


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case = fixture.HomeTests('test_old_routes_still_render')
    case.id = lambda: 'composer-browser'
    case.setUp()
    app = fixture.fixture.base.f.fixture.app.app
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    release = threading.Event()
    calls = []
    report = []

    def stream(*args, **kwargs):
        calls.append(True)
        yield {'type': 'delta', 'text': 'Jawaban sintetis.'}
        release.wait(10)
        yield {'type': 'finish', 'reason': 'stop'}

    try:
        with patch.object(chat_models, 'check', side_effect=model_fixture.available), patch.object(providers, 'stream', side_effect=stream), sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=shutil.which('chromium'), args=['--no-sandbox'])
            for width in (320, 390, 1440):
                for agent in (False, True):
                    print(f"Checking {'agent' if agent else 'legacy'} composer at {width}px", flush=True)
                    owner = fixture.fixture.base.f.fixture.repo.create_user(f'composer-{agent}-{width}@example.test', 'hash')
                    conversation = agent_store.new_conversation(owner)
                    cookie = case.client(owner).get_cookie('session')
                    context = browser.new_context(viewport={'width': width, 'height': 900}, has_touch=width < 761)
                    context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': origin}, {'name': 'kilas_language', 'value': 'id', 'url': origin}])
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin) else route.abort())
                    page.goto(origin + (f'/kilas-ai/agent?conversation={conversation}' if agent else '/products/start'), wait_until='networkidle')
                    form = page.locator('#agent-chat-form' if agent else '#ai-composer')
                    field = page.locator('#agent-message' if agent else '#ai-input')
                    send = form.locator('button[type=submit]')
                    stop = form.locator('.ai-stop')
                    transcript = page.locator('#agent-conversation' if agent else '#ai-messages')
                    role = '.agent-message-user' if agent else '.ai-user'
                    # Hold session recovery, before the send or new-thread response exists.
                    page.evaluate('''() => {
                      const original = window.KilasChatRecovery.session;
                      window.KilasChatRecovery.session = async signal => {
                        await new Promise((resolve, reject) => {
                          window.__releaseSession = resolve;
                          signal.addEventListener('abort', () => reject(new DOMException('Stopped', 'AbortError')), {once:true});
                        });
                        return original(signal);
                      };
                    }''')
                    field.fill('hallo')
                    state = form.evaluate('''form => {
                      form.requestSubmit();
                      const input=form.querySelector('textarea'),stop=form.querySelector('.ai-stop');
                      const bubble=document.querySelector('.ai-user .ai-message-text,.agent-message-user .agent-message-text');
                      return {input:input.value,bubble:bubble?.textContent,stopHidden:stop.hidden};
                    }''')
                    assert state == {'input': '', 'bubble': 'hallo', 'stopHidden': False}, state
                    expect(send).to_be_hidden()
                    expect(stop).to_be_visible()
                    expect(stop).to_have_attribute('aria-label', 'Berhenti')
                    expect(stop.locator('svg rect')).to_have_count(1)
                    assert stop.text_content().strip() == ''
                    box = stop.bounding_box()
                    assert box['width'] == box['height'] and box['width'] >= 44, box
                    # The existing empty layout is 760px; a conversation is 880px.
                    # Compare slots in the same conversation layout, not across that transition.
                    send_box = form.evaluate('''form => {
                      const send=form.querySelector('button[type=submit]'),stop=form.querySelector('.ai-stop');
                      stop.hidden=true;send.hidden=false;
                      const r=send.getBoundingClientRect(),box={x:r.x,y:r.y,width:r.width,height:r.height};
                      send.hidden=true;stop.hidden=false;return box;
                    }''')
                    assert all(abs(box[key] - send_box[key]) <= 1 for key in ('x','y','width','height')), (box, send_box)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    if width == 390:
                        page.screenshot(path=f'/tmp/chat-composer-{agent}-390.png')
                    # Stop before any request is accepted restores the draft, not a duplicate bubble.
                    stop.click()
                    expect(field).to_have_value('hallo')
                    expect(send).to_be_visible()
                    expect(send).to_be_enabled()
                    expect(transcript.locator(role)).to_have_count(0)
                    # A network failure before acknowledgement restores the exact draft.
                    endpoint = '**/agent/chat' if agent else '**/threads'
                    def fail(route):
                        route.abort('failed') if route.request.method == 'POST' else route.continue_()
                    page.route(endpoint, fail)
                    send.click()
                    expect(field).to_have_value('')
                    page.evaluate('window.__releaseSession()')
                    expect(send).to_be_enabled(timeout=15000)
                    expect(field).to_have_value('hallo')
                    expect(transcript.locator(role)).to_have_count(0)
                    page.unroute(endpoint, fail)
                    # Retry is immediate too; exactly one user bubble, and stop stays in the send slot.
                    release.clear()
                    send.click()
                    expect(field).to_have_value('')
                    expect(transcript.locator(role)).to_have_count(1)
                    page.evaluate('window.__releaseSession()')
                    expect(transcript).to_contain_text('Jawaban sintetis.', timeout=20000)
                    expect(field).to_have_value('')
                    stop.click()
                    release.set()
                    expect(send).to_be_enabled(timeout=20000)
                    expect(send).to_be_visible()
                    expect(stop).to_be_hidden()
                    expect(field).to_have_value('')
                    expect(transcript.locator(role)).to_have_count(1)
                    assert not errors, errors
                    report.append({'surface': 'agent' if agent else 'legacy', 'width': width, 'synchronous_clear_and_bubble': True, 'square_stop_in_send_slot': True, 'network_failure_restores_draft': True, 'cancel_before_acceptance_restores_draft': True, 'cancel_after_acceptance_keeps_input_empty': True, 'page_errors': 0})
                    context.close()
            browser.close()
        print(json.dumps(report, indent=2))
    finally:
        release.set()
        server.shutdown()
        case.doCleanups()


if __name__ == '__main__':
    main()
