"""Scoped Home design/state acceptance. Synthetic accounts; no provider or submit."""
import json,os,threading,logging
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_experience as fixture
from kilas_ai import chat_models,image_models


def main():
    case=fixture.ExperienceTests('test_starters_follow_ui_language_without_changing_models');case.setUp()
    app=fixture.home.fixture.base.f.fixture.app.app
    server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}';phase=os.environ.get('KILAS_HOME_POLISH_CAPTURE','after')
    output=Path(os.environ.get('KILAS_HOME_POLISH_SCREENSHOTS','../../home-polish-qa')).resolve();output.mkdir(parents=True,exist_ok=True)
    report={'phase':phase,'paid_calls':0,'viewports':[]}
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    try:
        with patch.object(chat_models,'check',side_effect=lambda m:{**chat_models.spec(m),'available':True,'images':True,'status':'verified'}),patch.object(image_models,'check',side_effect=lambda m:{**image_models.spec(m),'available':True,'status':'verified'}),sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            for width,height in ((1440,1000),(820,1000),(412,915),(390,844),(320,700)):
                cookie=case.client().get_cookie('session');context=browser.new_context(viewport={'width':width,'height':height},has_touch=width<761)
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
                page=context.new_page();errors=[];writes=[]
                page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:writes.append(r.url) if r.method=='POST' else None)
                page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                page.goto(origin+'/products/start',wait_until='networkidle')
                expect(page.locator('.home-starters,[data-home-starter]')).to_have_count(0)
                expect(page.locator('.kilas-new-chat-logo')).to_be_visible()
                expect(page.locator('.ai-empty h1')).to_be_visible()
                expect(page.locator('[data-home-task=voiceover]')).to_be_visible()
                geometry=page.evaluate("()=>({width:innerWidth,composerBottom:document.querySelector('#ai-composer').getBoundingClientRect().bottom,overflow:document.documentElement.scrollWidth>innerWidth})")
                page.screenshot(path=str(output/f'{phase}-home-{width}.png'),full_page=True)
                assert not geometry['overflow'] and 0<=height-geometry['composerBottom']<60,(width,geometry)
                field=page.locator('#ai-input');notice=page.locator('#ai-notice')
                field.fill('Synthetic genuine unsent draft');field.blur();expect(field).to_have_value('Synthetic genuine unsent draft');expect(notice).to_be_empty()
                page.locator('#ai-files').set_input_files({'name':'synthetic-draft.txt','mimeType':'text/plain','buffer':b'synthetic'})
                expect(page.locator('#ai-pending .ai-pending-item')).to_have_count(1)
                field.fill('');expect(page.locator('#ai-pending .ai-pending-item')).to_have_count(1)
                page.locator('#ai-pending button').click();expect(notice).to_be_empty()
                trigger=page.locator('[data-model-kind=chat] .chat-model-trigger');trigger.click();expect(page.locator('#chat-model-dialog')).to_be_visible();page.keyboard.press('Escape')
                expect(page.locator('#chat-model-dialog')).not_to_be_visible()
                if width<=412:
                    identity=page.evaluate("()=>({font:getComputedStyle(document.querySelector('.ai-empty h1')).fontSize,logo:getComputedStyle(document.querySelector('.kilas-new-chat-logo')).display,tabs:[...document.querySelectorAll('.home-task-choices>*')].map(e=>e.getBoundingClientRect().width)})")
                    field.focus();page.set_viewport_size({'width':width,'height':460})
                    expect(page.locator('body')).to_have_class(__import__('re').compile('home-keyboard-open'))
                    focused_identity=page.evaluate("()=>({font:getComputedStyle(document.querySelector('.ai-empty h1')).fontSize,logo:getComputedStyle(document.querySelector('.kilas-new-chat-logo')).display,tabs:[...document.querySelectorAll('.home-task-choices>*')].map(e=>e.getBoundingClientRect().width)})")
                    assert focused_identity==identity,(width,identity,focused_identity)
                    assert page.locator('#ai-composer').evaluate('e=>e.getBoundingClientRect().bottom<=innerHeight'),width
                    assert page.locator('#ai-composer').evaluate('e=>innerHeight-e.getBoundingClientRect().bottom<60'),width
                    page.screenshot(path=str(output/f'{phase}-keyboard-{width}.png'),full_page=True)
                    page.set_viewport_size({'width':width,'height':height});field.blur()
                page.goto(origin+'/kilas-ai/library',wait_until='networkidle');page.go_back(wait_until='networkidle')
                expect(page.locator('.home-starters,[data-home-starter]')).to_have_count(0);expect(notice).to_be_empty()
                page.set_viewport_size({'width':width,'height':460})
                page.wait_for_function("Math.abs(parseFloat(document.documentElement.style.getPropertyValue('--home-viewport-height'))-innerHeight)<2")
                assert page.locator('#ai-composer').evaluate('e=>0<=innerHeight-e.getBoundingClientRect().bottom&&innerHeight-e.getBoundingClientRect().bottom<60'),width
                page.screenshot(path=str(output/f'{phase}-short-{width}.png'),full_page=True)
                # Exercise the populated Home transcript layout with synthetic DOM content,
                # without submitting a chat or contacting a provider.
                page.evaluate('''()=>{document.querySelector('.ai-empty').hidden=true;document.querySelector('.ai-main').classList.remove('is-empty');const m=document.querySelector('#ai-messages');m.hidden=false;for(let i=0;i<80;i++){const p=document.createElement('p');p.textContent='Synthetic transcript line '+i;m.append(p)}}''')
                for transcript_height in (height,460):
                    page.set_viewport_size({'width':width,'height':transcript_height})
                    page.wait_for_function("Math.abs(parseFloat(document.documentElement.style.getPropertyValue('--home-viewport-height'))-innerHeight)<2")
                    result=page.evaluate('''()=>{const m=document.querySelector('#ai-messages'),c=document.querySelector('#ai-composer'),t=document.querySelector('.home-tool-selector');m.scrollTop=150;return {scrollable:m.scrollHeight>m.clientHeight,readingPosition:m.scrollTop,bottom:c.getBoundingClientRect().bottom,overlap:m.getBoundingClientRect().bottom>t.getBoundingClientRect().top+1,overflow:document.documentElement.scrollWidth>innerWidth}}''')
                    assert result['scrollable'] and result['readingPosition']>0 and not result['overlap'] and not result['overflow'],(width,transcript_height,result)
                    assert 0<=transcript_height-result['bottom']<60,(width,transcript_height,result)
                field.focus();page.set_viewport_size({'width':width,'height':380})
                page.wait_for_function("Math.abs(parseFloat(document.documentElement.style.getPropertyValue('--home-viewport-height'))-innerHeight)<2")
                assert page.locator('#ai-composer').evaluate('e=>0<=innerHeight-e.getBoundingClientRect().bottom&&innerHeight-e.getBoundingClientRect().bottom<60'),width
                assert page.locator('#ai-messages').evaluate('e=>e.scrollTop>0'),width
                assert not writes and not errors,(writes,errors)
                if width<=412:
                    # Android-like visualViewport-only resize/offset, keeping layout
                    # width/height unchanged. This is a simulation, not device hardware.
                    keyboard_page=context.new_page()
                    keyboard_page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                    keyboard_page.on('pageerror',lambda e:errors.append(str(e)))
                    keyboard_page.on('request',lambda r:writes.append(r.url) if r.method=='POST' else None)
                    keyboard_page.add_init_script("""(()=>{const v=new EventTarget();v.height=innerHeight;v.offsetTop=0;Object.defineProperty(window,'visualViewport',{value:v});window.qaViewport=(height,offsetTop=0)=>{v.height=height;v.offsetTop=offsetTop;v.dispatchEvent(new Event('resize'))}})()""")
                    keyboard_page.goto(origin+'/products/start',wait_until='networkidle')
                    keyboard_page.locator('#ai-input').fill('Synthetic retained keyboard draft')
                    appearance="""()=>({font:getComputedStyle(document.querySelector('.ai-empty h1')).fontSize,logo:getComputedStyle(document.querySelector('.kilas-new-chat-logo')).display,logoWidth:getComputedStyle(document.querySelector('.kilas-new-chat-logo')).width,starterCount:document.querySelectorAll('.home-starters,[data-home-starter]').length,tabs:[...document.querySelectorAll('.home-task-choices>*')].map(e=>({width:e.getBoundingClientRect().width,font:getComputedStyle(e).fontSize,padding:getComputedStyle(e).padding}))})"""
                    closed=keyboard_page.evaluate(appearance)
                    for _ in range(2):
                        keyboard_page.locator('#ai-input').focus();keyboard_page.evaluate('qaViewport(380,48)')
                        expect(keyboard_page.locator('body')).to_have_class(__import__('re').compile('home-keyboard-open'))
                        assert keyboard_page.evaluate(appearance)==closed,width
                        bounds=keyboard_page.evaluate("()=>{const e=document.querySelector('.ai-empty'),r=document.querySelector('#ai-composer').getBoundingClientRect();e.scrollTop=e.scrollHeight;return {bottom:r.bottom,top:r.top,scrollable:e.scrollHeight>e.clientHeight,scrolled:e.scrollTop>0}}")
                        assert bounds['bottom']<=428 and bounds['top']>=48 ,(width,bounds)
                        expect(keyboard_page.locator('#ai-input')).to_have_value('Synthetic retained keyboard draft')
                        keyboard_page.screenshot(path=str(output/f'{phase}-visual-keyboard-{width}.png'),full_page=True)
                        keyboard_page.locator('#ai-input').blur();keyboard_page.evaluate(f'qaViewport({height})')
                        expect(keyboard_page.locator('body')).not_to_have_class(__import__('re').compile('home-keyboard-open'))
                        assert keyboard_page.evaluate(appearance)==closed,width
                    keyboard_page.close();assert not writes and not errors,(writes,errors);geometry['visual_viewport_focus_blur_identity_draft']='PASS'
                geometry['short_empty_and_populated_scroll_keyboard']='PASS'
                geometry['state_checks']='PASS';report['viewports'].append(geometry);context.close()
            browser.close()
        (output/f'{phase}-verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
