"""Focused UI acceptance on disposable local data; no provider or paid calls."""
import json
import os
import tempfile
import threading
import logging
from pathlib import Path
from unittest.mock import patch
from flask import url_for
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_home as home
import repo
import finance_service as finance
from kilas_ai import live_translator, audio_branded_voices, store


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case = home.HomeTests('test_old_routes_still_render')
    case.id = lambda: 'ui-consistency-browser'
    case.setUp()
    app = home.fixture.base.f.fixture.app.app
    business = repo.create_business(case.owner, 'Synthetic UI business')
    finance.ensure_finance_defaults(business)
    thread = store.create_thread(case.owner)
    store.append_user_once(case.owner,thread,'Halo','SMART','synthetic-ui-message')
    store.append_assistant(case.owner,thread,'Halo, ada yang bisa dibantu?','SMART','synthetic','synthetic','synthetic-ui-message',{})
    with app.test_request_context():
        finance_url = url_for('finance.dashboard', business_id=business)
        settings_url = url_for('finance.invoice_settings', business_id=business)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    output = Path(os.environ.get('KILAS_UI_CONSISTENCY_SCREENSHOTS', str(Path(tempfile.gettempdir()) / 'kilas-ui-consistency-20261012')))
    output.mkdir(parents=True, exist_ok=True)
    results = []
    try:
        with patch.dict(os.environ, {'KILAS_FINANCE_BETA': 'on','KILAS_AUDIO_UPLOAD_TRANSLATION_VISIBLE':'false'}), patch.object(live_translator, 'ready', return_value=True), patch.object(audio_branded_voices, 'public_choices', return_value=[{'alias':'kilas-male','name':'Kilas Male','style':'Natural'},{'alias':'kilas-female','name':'Kilas Female','style':'Natural'}]), sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            for width, height in ((360,800),(390,844),(768,1024),(1024,768),(1440,900),(844,390)):
                context = browser.new_context(viewport={'width':width,'height':height}, has_touch=width<1025)
                cookie = case.client().get_cookie('session')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin) else route.abort())

                def capture(name, path):
                    response = page.goto(origin+path, wait_until='networkidle')
                    if response is None:  # A hash-only navigation still needs a direct-load check.
                        response = page.reload(wait_until='networkidle')
                    assert response.status == 200, (name, response.status, page.url)
                    page.evaluate('document.fonts.ready')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'), (name,width,'horizontal overflow')
                    assert not errors, (name,errors)
                    page.screenshot(path=str(output/f'{name}-{width}x{height}.png'), full_page=True)
                    results.append({'page':name,'width':width,'height':height,'result':'PASS'})

                def tabs(active):
                    row = page.locator('.home-task-choices').first
                    assert row.inner_text().splitlines() == ['AI Chat','Translator','Voice Over'], row.inner_text()
                    controls = row.locator(':scope>a,:scope>button,:scope>form>button')
                    assert controls.count() == 4
                    geometry = controls.evaluate_all('(es)=>es.map(e=>({h:e.getBoundingClientRect().height,r:getComputedStyle(e).borderRadius,f:getComputedStyle(e).fontSize,b:getComputedStyle(e).borderStyle}))')
                    assert all(g['h']>=44 and g['r']=='8px' and g['b']=='solid' for g in geometry), geometry
                    assert len({g['f'] for g in geometry}) == 1, geometry
                    assert controls.locator('svg').count() == 4
                    if width<=760:
                        assert row.evaluate('e=>getComputedStyle(e).flexWrap') == 'nowrap'
                        assert len({round(b['y']) for b in controls.evaluate_all('(es)=>es.map(e=>({y:e.getBoundingClientRect().y}))')}) == 1
                        assert row.evaluate('e=>e.scrollWidth>e.clientWidth')
                        row.evaluate('e=>e.scrollLeft=e.scrollWidth')
                        expect(controls.last).to_be_in_viewport()
                        page.screenshot(path=str(output/f'tabs-{active}-{width}x{height}.png'))
                        row.evaluate('e=>e.scrollLeft=0')
                    expect(row.locator('[aria-current=page],[aria-pressed=true]')).to_have_text(active)

                capture('home','/products/start'); tabs('AI Chat')
                capture('chat',f'/kilas-ai/threads/{thread}'); tabs('AI Chat')
                user = page.locator('.ai-user .ai-message-text')
                answer = page.locator('.ai-assistant .ai-message-text')
                assert user.bounding_box()['width'] < 130
                assert user.bounding_box()['x'] > answer.bounding_box()['x']
                assert user.evaluate('e=>getComputedStyle(e).fontFamily') == page.locator('body').evaluate('e=>getComputedStyle(e).fontFamily')
                sidebar = page.locator('#premium-sidebar')
                if sidebar.evaluate('e=>e.inert'):
                    page.locator('[data-premium-menu]').click()
                sidebar.locator('.kilas-profile-menu>summary').click()
                identity = sidebar.locator('.kilas-profile-identity')
                expect(identity).to_be_visible()
                assert identity.locator('a,button,input').count() == 0
                assert identity.evaluate('e=>e.tabIndex') == -1
                assert sidebar.locator('.kilas-profile-options a[href*="/account"]').count() == 0
                page.screenshot(path=str(output/f'profile-{width}x{height}.png'),full_page=True)

                # Real DOM layout under a simulated visualViewport shrink, not hardware keyboard evidence.
                page.goto(origin+f'/kilas-ai/threads/{thread}',wait_until='networkidle')
                page.evaluate('''() => {window.qaViewport=new EventTarget();Object.assign(qaViewport,{height:300,offsetTop:20});Object.defineProperty(window,'visualViewport',{value:qaViewport,configurable:true});}''')
                page.add_script_tag(url=origin+'/static/kilas_home.js')
                box = page.locator('#ai-composer').bounding_box()
                assert box['y']+box['height'] <= 320, box
                page.screenshot(path=str(output/f'keyboard-{width}x{height}.png'),full_page=True)
                # Accepted submission collapses a long draft before streaming completes.
                page.goto(origin+f'/kilas-ai/threads/{thread}',wait_until='networkidle')
                page.evaluate('''() => {const original=window.fetch;window.fetch=(url,...args)=>String(url).endsWith('/send')?Promise.resolve(new Response(new ReadableStream({start(c){window.qaStream=c;c.enqueue(new TextEncoder().encode('event: delta\\ndata: {"text":"Synthetic reply"}\\n\\n'));}}),{headers:{'Content-Type':'text/event-stream'}})):original(url,...args);}''')
                field=page.locator('#ai-input');field.fill('Synthetic long draft.\n'*15)
                assert field.bounding_box()['height']>40
                field.focus();page.locator('#ai-send').click()
                expect(field).to_have_value('')
                assert field.bounding_box()['height']<=42
                page.evaluate('qaStream.enqueue(new TextEncoder().encode("event: done\\ndata: {}\\n\\n"));qaStream.close()')
                expect(page.locator('#ai-send')).to_be_enabled()
                assert field.evaluate('e=>document.activeElement===e') == page.evaluate("matchMedia('(hover: hover) and (pointer: fine)').matches")
                field.click();expect(field).to_be_focused()

                capture('voiceover','/kilas-translator?mode=voiceover'); tabs('Voice Over')
                assert page.locator('#premium-sidebar,.finance-app-sidebar').count() == 0
                expect(page.locator('.audio-tabs')).to_be_hidden()
                if width<=600:
                    assert all(b['height']<=90 for b in page.locator('.audio-voice').evaluate_all('(es)=>es.map(e=>({height:e.getBoundingClientRect().height}))'))
                page.locator('[name=voice_kind][value=personal]').check()
                expect(page.locator('#personal-voice-setup')).to_be_visible()
                page.locator('[name=voice_kind][value=kilas]').check()
                expect(page.locator('#kilas-voice-options')).to_be_visible()
                page.reload(wait_until='networkidle');tabs('Voice Over')
                capture('translator','/kilas-translator/live'); tabs('Translator')
                assert page.locator('#premium-sidebar,.finance-app-sidebar').count() == 0
                assert not page.locator('.live-privacy').get_attribute('open')
                assert not page.get_by_text('Ucapan dikirim ke ElevenLabs',exact=False).is_visible()
                page.locator('.live-privacy>summary').click()
                expect(page.get_by_text('Ucapan dikirim ke ElevenLabs',exact=False)).to_be_visible()
                assert page.locator('[name=consent]').get_attribute('required') is not None

                capture('finance',finance_url); tabs('Finance')
                expect(page.locator('.finance-app-sidebar')).to_be_visible()
                capture('finance-settings',settings_url); tabs('Finance')
                expect(page.locator('.finance-app-sidebar')).to_be_visible()
                assert page.locator('.premium-sidebar').count() == 0
                for path in ('/account','/account?workspace=home','/account#business','/account#security'):
                    capture('account-'+path.rsplit('#',1)[-1].replace('/','').replace('?','-'),path)
                    assert page.locator('aside,#premium-sidebar,[data-chat-sidebar],.finance-app-sidebar').count() == 0
                    expect(page.locator('.account-back-finance')).to_be_visible()
                    assert page.locator('.account-back-finance').get_attribute('href').startswith(('/business/','/products/finance'))
                    assert page.locator('[data-account-tab]').count() == 3
                    page.reload(wait_until='networkidle')
                    assert page.locator('aside,#premium-sidebar').count() == 0
                context.close()
            browser.close()
    finally:
        server.shutdown();case.doCleanups()
        (output/'report.json').write_text(json.dumps({'kind':'local Chromium, synthetic data; keyboard viewport simulation only','paid_calls':0,'checks':results},indent=2))
    print(json.dumps({'result':'PASS','captures':len(results),'output':str(output)}))


if __name__ == '__main__':
    main()
