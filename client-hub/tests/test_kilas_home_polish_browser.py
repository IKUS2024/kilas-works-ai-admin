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
                expect(page.locator('.home-starters')).to_be_visible()
                geometry=page.evaluate('''()=>{const r=s=>document.querySelector(s).getBoundingClientRect();return {width:innerWidth,heroTop:r('.ai-empty').top,starterToTools:r('.home-tool-selector').top-r('.home-starters').bottom,composerBottom:r('#ai-composer').bottom,overflow:document.documentElement.scrollWidth>innerWidth,starterSizes:[...document.querySelectorAll('.home-starters button')].map(e=>({width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height}))}}''')
                page.screenshot(path=str(output/f'{phase}-home-{width}.png'),full_page=True)
                if phase=='before':report['viewports'].append(geometry);context.close();continue
                assert page.locator('.home-starters button').count()==3 and page.locator('.home-starters a').count()==0
                expect(page.locator('[data-home-task=voiceover]')).to_be_visible()
                assert not geometry['overflow'],(width,geometry)
                assert max(x['width'] for x in geometry['starterSizes'])-min(x['width'] for x in geometry['starterSizes'])<2
                assert max(x['height'] for x in geometry['starterSizes'])-min(x['height'] for x in geometry['starterSizes'])<2
                assert geometry['composerBottom']<=height,(width,geometry)
                assert height-geometry['composerBottom']<60,(width,geometry)
                buttons=page.locator('[data-home-starter]');field=page.locator('#ai-input');notice=page.locator('#ai-notice')
                buttons.first.click();draft=field.input_value();buttons.first.dblclick();expect(field).to_have_value(draft);expect(notice).to_be_empty()
                field.fill('Synthetic genuine unsent draft');buttons.nth(1).click();expect(field).to_have_value('Synthetic genuine unsent draft');expect(notice).to_contain_text('Your draft is preserved')
                field.fill('');expect(field).to_have_value('');expect(notice).to_be_empty();assert field.evaluate('e=>e.matches(":placeholder-shown")')
                buttons.nth(1).click();expect(notice).to_be_empty();expect(field).not_to_be_empty()
                # Preserve attachment selection while guarding real text and when populating an empty draft.
                page.locator('#ai-files').set_input_files({'name':'synthetic-draft.txt','mimeType':'text/plain','buffer':b'synthetic'})
                expect(page.locator('#ai-pending .ai-pending-item')).to_have_count(1)
                field.fill('Genuine text with a pending attachment');buttons.first.click();expect(field).to_have_value('Genuine text with a pending attachment');expect(page.locator('#ai-pending .ai-pending-item')).to_have_count(1)
                field.fill('');buttons.first.click();expect(notice).to_be_empty();expect(page.locator('#ai-pending .ai-pending-item')).to_have_count(1)
                page.locator('#ai-pending button').click();field.fill('')
                # Clearing an owned starter notice must not clear an unrelated upload/model error.
                field.fill('Genuine draft');buttons.nth(1).click();page.evaluate("document.querySelector('#ai-notice').textContent='Synthetic attachment error'")
                field.fill('');expect(notice).to_have_text('Synthetic attachment error')
                page.reload(wait_until='networkidle');field=page.locator('#ai-input');expect(notice).to_be_empty()
                page.evaluate("document.dispatchEvent(new Event('kilas:request-started'))");buttons.first.click();expect(field).to_be_empty();page.evaluate("document.dispatchEvent(new Event('kilas:request-finished'))")
                trigger=page.locator('[data-model-kind=chat] .chat-model-trigger');trigger.click();expect(page.locator('#chat-model-dialog')).to_be_visible();page.keyboard.press('Escape')
                expect(page.locator('#chat-model-dialog')).not_to_be_visible()
                if width<=412:
                    field.focus();page.set_viewport_size({'width':width,'height':460})
                    expect(page.locator('body')).to_have_class(__import__('re').compile('home-keyboard-open'))
                    assert page.locator('#ai-composer').evaluate('e=>e.getBoundingClientRect().bottom<=innerHeight'),width
                    assert page.locator('#ai-composer').evaluate('e=>innerHeight-e.getBoundingClientRect().bottom<60'),width
                    page.screenshot(path=str(output/f'{phase}-keyboard-{width}.png'),full_page=True)
                    page.set_viewport_size({'width':width,'height':height});field.blur()
                page.goto(origin+'/kilas-ai/library',wait_until='networkidle');page.go_back(wait_until='networkidle')
                expect(page.locator('.home-starters button')).to_have_count(3);expect(notice).to_be_empty()
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
                geometry['short_empty_and_populated_scroll_keyboard']='PASS'
                geometry['state_checks']='PASS';report['viewports'].append(geometry);context.close()
            browser.close()
        (output/f'{phase}-verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
