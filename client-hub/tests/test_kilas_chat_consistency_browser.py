"""Real persisted chat across canonical shells; controlled keyboard viewport and provider-only mocks."""
import json
import os
import shutil
import threading
from pathlib import Path
from unittest.mock import patch
import test_kilas_home as fixture
from kilas_ai import providers, agent_store
from kilas_chat_sidebar_browser_helpers import open_chat_sidebar, click_new_chat
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

ANSWER='Jawaban sintetis yang tersimpan.\n\n'+('Paragraf panjang untuk memeriksa scroll pesan. '*40)+'\n\n```js\nconst synthetic = "'+('x'*200)+'";\n```'
VIEWPORT="""window.qaViewport=new EventTarget();Object.assign(qaViewport,{height:innerHeight,width:innerWidth,offsetTop:0,offsetLeft:0});Object.defineProperty(window,'visualViewport',{get:()=>qaViewport});Object.defineProperty(crypto,'randomUUID',{value:undefined});String.prototype.replaceAll=undefined;"""


def tools_and_layout(page, selector, navigate=False):
    expect(page.locator('[data-home-task]')).to_have_count(2)
    row=page.locator('.home-task-choices')
    assert row.evaluate("e=>{const buttons=[...e.children];return getComputedStyle(e).display==='flex'&&buttons.map(b=>b.textContent.trim()).join('|').startsWith('AI Chat|Translator')}")
    for task in ('chat','voiceover'):
        button=page.locator(f'[data-home-task={task}]');expect(button).to_be_visible()
        assert button.evaluate('e=>e.getBoundingClientRect().height>=44')
    expect(page.locator('[data-home-task=chat]')).to_have_attribute('aria-pressed','true')
    if navigate:
        original_url=page.url
        for task,path,field in [('voiceover','/kilas-translator','#audio-script')]:
            page.locator(selector).fill('Carried draft' if task!='translate' else '')
            page.locator(f'[data-home-task={task}]').click()
            expect(page.locator('[data-kilas-feature]')).to_have_count(2)
            expect(page.locator(f'[data-kilas-feature={task}]')).to_have_attribute('aria-current','page')
            assert __import__('urllib.parse',fromlist=['urlsplit']).urlsplit(page.url).path==path
            if task!='translate':expect(page.locator(field)).to_have_value('Carried draft')
            page.reload(wait_until='networkidle')
            expect(page.locator(f'[data-kilas-feature={task}]')).to_have_attribute('aria-current','page')
            if task!='translate':expect(page.locator(field)).to_have_value('Carried draft')
            page.go_back(wait_until='networkidle')
            assert page.url==original_url
            expect(page.locator('[data-home-task=chat]')).to_have_attribute('aria-pressed','true')
        page.locator(selector).fill('')

    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    form=page.locator('#agent-chat-form' if selector=='#agent-message' else '#ai-composer')
    expect(form).to_be_in_viewport()
    if selector=='#agent-message':assert page.locator('#work-source-files').evaluate('e=>e.getBoundingClientRect().width<=1')
    assert page.locator(selector).evaluate('e=>e.clientHeight<=48')


def keyboard(page, selector, height, top):
    page.evaluate('([height,top])=>{qaViewport.height=height;qaViewport.offsetTop=top;qaViewport.dispatchEvent(new Event("resize"));qaViewport.dispatchEvent(new Event("scroll"))}',[height,top])
    page.locator(selector).focus()
    bottom=page.locator('.ai-composer').last.evaluate('e=>e.getBoundingClientRect().bottom')
    assert 0<=height+top-bottom<=24,(height,top,bottom)
    expect(page.locator('[data-home-task=chat]')).to_be_in_viewport()
    expect(page.locator('.ai-send').last).to_be_in_viewport()
    timeline=page.locator('#ai-messages' if selector=='#ai-input' else '#agent-conversation')
    assert timeline.evaluate('e=>e.clientHeight>0&&e.scrollHeight-e.scrollTop-e.clientHeight<48')


def main():
    case=fixture.HomeTests('test_old_routes_still_render');case.id=lambda:'canonical-chat-browser';case.setUp();offering=patch.dict(os.environ,{'KILAS_AUDIO_UPLOAD_TRANSLATION_VISIBLE':'false'});offering.start();case.addCleanup(offering.stop)
    app=fixture.fixture.base.f.fixture.app.app
    server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_CHAT_SCREENSHOTS','/tmp/kilas-chat-consistency'));output.mkdir(parents=True,exist_ok=True)
    engine=os.environ.get('KILAS_CHAT_ENGINE','chromium');report={'engine':engine,'paid_requests':0,'keyboard':'visualViewport simulation, not real OS IME','cases':[]}
    try:
        with patch.object(providers,'stream',side_effect=lambda *a,**k:fixture.fixture.answer(ANSWER)),sync_playwright() as pw:
            launch={'headless':True}
            if engine=='chromium' and shutil.which('chromium'):launch.update(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            browser=getattr(pw,engine).launch(**launch)
            cookie=case.client().get_cookie('session')
            for width,height in ((320,780),(390,844),(820,1180),(1180,820),(1440,900)):
                context=browser.new_context(viewport={'width':width,'height':height},has_touch=width<1200,reduced_motion='reduce')
                context.add_init_script(VIEWPORT);context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                # Home -> send -> persisted legacy route -> reload/history/new chat.
                for work in (False,True):
                    path='/kilas-ai/agent?conversation='+str(case.conversation) if work else '/products/start'
                    page.goto(origin+path,wait_until='networkidle')
                    selector='#agent-message' if work else '#ai-input';form='#agent-chat-form' if work else '#ai-composer';send=page.locator(form+' button[type=submit]')
                    tools_and_layout(page,selector,navigate=True)
                    message=('Halo Kilas, pertanyaan sintetis.\n'*18)+str(width)+str(work)
                    page.fill(selector,message);assert page.locator(selector).evaluate('e=>e.clientHeight>48')
                    # Failure retains exact draft, including line breaks, and height.
                    route='**/agent/chat' if work else '**/threads/*/send'
                    page.route(route,lambda r:r.fulfill(status=429,content_type='application/json',body='{"error":"Batas sintetis"}'))
                    send.click();expect(send).to_be_enabled();expect(page.locator(selector)).to_have_value(message)
                    assert page.locator(selector).evaluate('e=>e.clientHeight>48')
                    page.unroute(route)
                    # An error followed by DONE cannot masquerade as success.
                    failed='data: {"type":"error"}\n\ndata: {"type":"done"}\n\n' if work else 'event: error\ndata: {"message":"Gagal sintetis"}\n\nevent: done\ndata: {}\n\n'
                    page.route(route,lambda r:r.fulfill(status=200,content_type='text/event-stream',body=failed))
                    send.click();expect(send).to_be_enabled();expect(page.locator(selector)).to_have_value(message);page.unroute(route)
                    empty='data: {"type":"done"}\n\n' if work else 'event: done\ndata: {}\n\n'
                    page.route(route,lambda r:r.fulfill(status=200,content_type='text/event-stream',body=empty))
                    send.click();expect(send).to_be_enabled();expect(page.locator(selector)).to_have_value(message);page.unroute(route)
                    send.click();expect(send).to_be_enabled(timeout=20000);expect(page.locator(selector)).to_have_value('')
                    assert page.locator(selector).evaluate('e=>e.clientHeight<=48')
                    assistant=page.locator('.agent-message-assistant .agent-message-text' if work else '.ai-assistant .ai-message-text').last
                    expect(assistant).to_contain_text('Jawaban sintetis yang tersimpan.')
                    saved=page.url
                    page.reload(wait_until='networkidle');tools_and_layout(page,selector);expect(assistant).to_contain_text('Jawaban sintetis yang tersimpan.')
                    user=page.locator('.agent-message-user .agent-message-text' if work else '.ai-user .ai-message-text').last
                    for bubble in (user,assistant):assert bubble.evaluate('e=>parseFloat(getComputedStyle(e).borderRadius)>=12&&getComputedStyle(e).backgroundColor!=="rgba(0, 0, 0, 0)"')
                    assert assistant.evaluate('e=>e.getBoundingClientRect().right<=e.closest(\"#ai-messages,#agent-conversation\").getBoundingClientRect().right+1')
                    assert user.evaluate('e=>e.getBoundingClientRect().right>=e.parentElement.getBoundingClientRect().right-4')
                    assert assistant.evaluate('e=>e.getBoundingClientRect().left<=e.parentElement.getBoundingClientRect().left+4')
                    copy=assistant.locator('..').locator('.ai-copy');assert copy.inner_text()=='' and copy.locator('svg').count()==1
                    # Copy retains the original Markdown, including code fences, after reload.
                    page.evaluate('navigator.clipboard.writeText=async text=>window.qaCopied=text');copy.click();expect(copy).to_have_attribute('aria-label','Tersalin');assert page.evaluate('qaCopied')==ANSWER
                    keyboard(page,selector,420,0);keyboard(page,selector,390,60)
                    page.locator(selector).fill('Keyboard draft\n'*15);keyboard(page,selector,420,20)
                    page.locator(selector).fill('');page.evaluate('qaViewport.height=innerHeight;qaViewport.offsetTop=0;qaViewport.dispatchEvent(new Event("resize"))')
                    assert page.locator('.ai-composer').last.evaluate('e=>innerHeight-e.getBoundingClientRect().bottom<60')
                    page.screenshot(path=str(output/f'{engine}-{"agent" if work else "legacy"}-{width}.png'))
                    click_new_chat(page,agent=work)
                    tools_and_layout(page,selector);expect(page.get_by_text('How can I Help you?',exact=True)).to_be_visible()
                    # Opening the original saved destination from Home history preserves the same tools/composer.
                    page.goto(origin+'/products/start',wait_until='networkidle');open_chat_sidebar(page)
                    link=page.locator('[data-chat-sidebar] a[href="'+saved.removeprefix(origin)+'"]');expect(link).to_be_visible();link.click();page.wait_for_load_state('networkidle')
                    tools_and_layout(page,selector);expect(page.locator('#agent-conversation' if work else '#ai-messages')).to_contain_text('Jawaban sintetis yang tersimpan.')
                assert not errors,errors
                report['cases'].append({'width':width,'height':height,'legacy':'PASS','agent':'PASS'});context.close()
            browser.close()
        (output/f'{engine}-verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:server.shutdown();case.doCleanups()

if __name__=='__main__':main()
