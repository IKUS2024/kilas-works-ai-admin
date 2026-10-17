"""Saved unavailable choices and long names in real Chromium; no inference."""
import json,shutil,threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_model_preferences as f
from kilas_ai import chat_models,image_models


def main():
    case=f.PreferenceTests('test_unsent_home_choice_survives_new_authenticated_sessions_and_reopening');case.setUp()
    server=make_server('127.0.0.1',0,f.fixture.fixture.fixture.base.f.fixture.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}';output=Path('/tmp/kilas-model-preference-browser');output.mkdir(exist_ok=True)
    state={'unavailable':False};rows=[]
    def access(model):return {**f.fixture.available(model),'available':not(state['unavailable'] and model=='claude-sonnet-5-5'),'status':'access_unavailable' if state['unavailable'] else 'verified'}
    def image_access(model):return {**image_models.spec(model),'available':not(state['unavailable'] and model=='gemini-3.1-flash-lite-image'),'status':'access_unavailable' if state['unavailable'] else 'verified'}
    try:
        with patch.object(chat_models,'check',side_effect=access),patch.object(image_models,'check',side_effect=image_access),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (320,768,1440):
                state['unavailable']=False
                case.choose('chat','claude-sonnet-5-5');case.choose('image','gemini-3.1-flash-lite-image')
                context=browser.new_context(viewport={'width':width,'height':900})
                cookie=case.client().get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                page.goto(origin+'/products/start',wait_until='networkidle')
                trigger=page.locator('[data-model-kind=chat] .chat-model-trigger');image_trigger=page.locator('[data-model-kind=image] .chat-model-trigger')
                expect(trigger).to_contain_text('Claude Sonnet 5.5');expect(image_trigger).to_contain_text('Gemini 3.1 Flash Lite Image')
                assert page.locator('[data-model-label]').evaluate_all('nodes=>nodes.every(e=>e.scrollWidth<=e.clientWidth+1)')
                group=page.locator('.chat-model-controls').bounding_box();header=page.locator('.home-workspace-top').bounding_box()
                assert abs(group['x']+group['width']/2-header['x']-header['width']/2)<2
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(output/f'long-names-{width}.png'))
                state['unavailable']=True;page.reload(wait_until='networkidle')
                expect(trigger).to_contain_text('Claude Sonnet 5.5');expect(image_trigger).to_contain_text('Gemini 3.1 Flash Lite Image')
                expect(page.locator('[data-model-warning=chat]')).to_be_visible();expect(page.locator('[data-model-warning=image]')).to_be_visible()
                assert page.evaluate("window.KilasChatModels.value()==='claude-sonnet-5-5' && window.KilasImageModels.value()==='gemini-3.1-flash-lite-image'")
                trigger.click();expect(page.locator('#chat-model-dialog').get_by_role('radio',name='Claude Sonnet 5.5',exact=False)).to_be_disabled();page.keyboard.press('Escape')
                image_trigger.click();expect(page.locator('#image-model-dialog').get_by_role('radio',name='Gemini 3.1 Flash Lite Image',exact=False)).to_have_count(0);page.keyboard.press('Escape')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(output/f'unavailable-{width}.png'))
                image_trigger.click();page.locator('#image-model-dialog').get_by_role('radio',name='GPT Image 1 Mini',exact=False).click();expect(page.locator('[data-model-warning=image]')).not_to_be_visible()
                trigger.click();page.locator('#chat-model-dialog').get_by_role('radio',name='GPT-6.1 Sol',exact=False).click();expect(page.locator('[data-model-warning=chat]')).not_to_be_visible()
                assert not errors,errors
                rows.append({'width':width,'long_names_unclipped':'PASS','centered':'PASS','saved_unavailable_choice_retained':'PASS','visible_warnings':'PASS','explicit_replacement':'PASS','overflow':False})
                context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps({'checks':rows,'paid_inference':False},indent=2));print(json.dumps(rows))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
