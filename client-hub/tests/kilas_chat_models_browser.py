"""Real Chromium and real Flask routes; synthetic owners/provider metadata only."""
import json
import shutil
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_chat_models as f
from kilas_ai import chat_models,image_models


def main():
    case=f.RouteTests('test_catalog_auth_csrf_and_owner_isolation');case.setUp()
    server=make_server('127.0.0.1',0,f.fixture.fixture.base.f.fixture.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}';output=Path('/tmp/kilas-chat-model-browser');output.mkdir(exist_ok=True)
    rows=[]
    def access(model):return {**f.available(model),'available':model!='claude-fable-5-1','status':'verified' if model!='claude-fable-5-1' else 'access_unavailable'}
    try:
        with patch.object(chat_models,'check',side_effect=access),patch.object(image_models,'check',side_effect=lambda m:{**image_models.spec(m),'available':True,'status':'verified'}),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (320,390,768,1024,1440):
                context=browser.new_context(viewport={'width':width,'height':900})
                cookie=case.client().get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                for surface,path in [('agent',f'/kilas-ai/agent?conversation={case.conversation}'),('legacy',f'/kilas-ai/threads/{case.thread}')]:
                    response=page.goto(origin+path,wait_until='networkidle');assert response.status==200
                    trigger=page.locator('[data-model-kind=chat] .chat-model-trigger');expect(trigger).to_contain_text('GPT-6.1 Sol' if width==320 else 'Claude Sonnet 5.5') if width!=320 else expect(trigger).to_contain_text('GPT-6.1 Sol')
                    field=page.locator('#agent-message' if surface=='agent' else '#ai-input');field.fill('Synthetic unsent draft')
                    trigger.click();dialog=page.locator('#chat-model-dialog');expect(dialog).to_be_visible()
                    expect(dialog.locator('.chat-model-option')).to_have_count(10)
                    expect(dialog.get_by_role('radio',name='Claude Fable 5.1',exact=False)).to_be_disabled()
                    rect=dialog.bounding_box();assert rect['x']>=-1 and rect['x']+rect['width']<=width+1
                    if width<=600:assert abs(rect['y']+rect['height']-900)<2 and abs(rect['width']-width)<2,(rect,page.locator('#chat-model-dialog').evaluate('e=>({width:getComputedStyle(e).width,maxWidth:getComputedStyle(e).maxWidth,inset:getComputedStyle(e).inset})'))
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.keyboard.press('End');assert page.evaluate("document.activeElement.textContent.includes('Gemini 4 Argon')")
                    page.keyboard.press('Home');assert page.evaluate("document.activeElement.textContent.includes('GPT-6 Luna')")
                    page.screenshot(path=str(output/f'{surface}-{width}.png'))
                    dialog.get_by_role('radio',name='Claude Sonnet 5.5',exact=False).click()
                    expect(dialog).not_to_be_visible();expect(trigger).to_contain_text('Claude Sonnet 5.5');expect(field).to_have_value('Synthetic unsent draft')
                    page.reload(wait_until='networkidle');expect(trigger).to_contain_text('Claude Sonnet 5.5')
                    trigger.click();page.keyboard.press('Escape');expect(dialog).not_to_be_visible();expect(trigger).to_be_focused()
                    image_trigger=page.locator('[data-model-kind=image] .chat-model-trigger')
                    image_trigger.click();image_dialog=page.locator('#image-model-dialog');expect(image_dialog).to_be_visible()
                    expect(image_dialog.locator('.chat-model-option')).to_have_count(6)
                    expect(image_dialog.locator('.model-provider-icon')).to_have_count(6)
                    image_dialog.get_by_role('radio',name='GPT Image 1 Mini',exact=False).click()
                    expect(page.locator('[data-image-cost-preview]')).to_contain_text('US$0.005')
                    expect(trigger).to_contain_text('Claude Sonnet 5.5')
                    image_trigger.click();image_dialog.get_by_role('radio',name='Gemini 3 Pro Image',exact=False).click()
                    expect(page.locator('[data-image-cost-preview]')).to_contain_text('US$0.1344')
                    page.reload(wait_until='networkidle');expect(image_trigger).to_contain_text('Gemini 3 Pro Image');expect(trigger).to_contain_text('Claude Sonnet 5.5')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    image_trigger.click();page.screenshot(path=str(output/f'image-{surface}-{width}.png'));page.keyboard.press('Escape')
                    expect(image_trigger).to_be_focused()
                    assert not errors,errors
                    rows.append({'surface':surface,'width':width,'overflow':False,'keyboard_focus':'PASS','persisted':'PASS','draft_retained':True})
                context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps({'checks':rows,'paid_inference':False},indent=2));print(json.dumps(rows))
    finally:server.shutdown();case.doCleanups()

if __name__=='__main__':main()
