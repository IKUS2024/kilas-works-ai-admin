"""Hold selector JS/catalog responses to inspect true initial names. No paid IO."""
import json
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from test_kilas_model_initial_render import InitialModelRenderTests
from kilas_ai import chat_models,image_models,model_preferences,store,agent_store
from kilas_ai import live_translator as live,audio_branded_voices as branded

TRACE="""window.qaLabels={chat:[],image:[]};new MutationObserver(()=>{for(const node of document.querySelectorAll('[data-model-label]')){const kind=node.closest('[data-model-kind]').dataset.modelKind,text=node.textContent.trim();if(qaLabels[kind].at(-1)!==text)qaLabels[kind].push(text)}}).observe(document,{subtree:true,childList:true,characterData:true});navigator.mediaDevices.getUserMedia=async()=>{throw Error('Real microphone forbidden')};"""


def main():
    case=InitialModelRenderTests('test_saved_account_names_and_icons_exist_before_any_javascript');case.id=lambda:'initial-label-browser';case.setUp()
    model_preferences.remember(case.owner,'chat','gpt-6-luna');model_preferences.remember(case.owner,'image','gpt-image-1-mini');thread=store.create_thread(case.owner)
    model_preferences.remember(case.owner,'chat','claude-sonnet-5-5');model_preferences.remember(case.owner,'image','gpt-image-2.5-sunburst');conversation=agent_store.new_conversation(case.owner)
    model_preferences.remember(case.owner,'chat','claude-opus-5-5');model_preferences.remember(case.owner,'image','gemini-3-pro-image')
    server=make_server('127.0.0.1',0,case.client().application,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(tempfile.gettempdir())/'kilas-model-initial-browser';output.mkdir(exist_ok=True);report=[]
    expected={'home':{'chat':'Claude Opus 5.5','image':'Gemini 3 Pro Image'},'thread':{'chat':'GPT-6 Luna','image':'GPT Image 1 Mini'},'conversation':{'chat':'Claude Sonnet 5.5','image':'GPT Image 2.5 Sunburst'}}
    ids={'home':('claude-opus-5-5','gemini-3-pro-image'),'thread':('gpt-6-luna','gpt-image-1-mini'),'conversation':('claude-sonnet-5-5','gpt-image-2.5-sunburst')}
    paths={'home':'/products/start','thread':f'/kilas-ai/threads/{thread}','conversation':f'/kilas-ai/agent?conversation={conversation}'}
    try:
        with patch.object(live,'ready',return_value=True),patch.object(branded,'public_choices',return_value=[{'alias':'kilas-male','name':'Kilas Male'}]),patch.object(chat_models.requests,'get',side_effect=AssertionError('Provider IO forbidden')),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM','/usr/bin/chromium'),args=['--no-sandbox'])
            for width,surface,unavailable in [(w,s,False) for w in (360,1440) for s in paths]+[(360,'home',True),(1440,'home',True)]:
                def image_info(model):return {**image_models.spec(model),'available':not(unavailable and model=='gemini-3-pro-image'),'status':'access_unavailable' if unavailable and model=='gemini-3-pro-image' else 'verified'}
                with patch.object(image_models,'check',side_effect=image_info),patch.object(image_models,'cached_metadata',side_effect=lambda m:image_info(m) if unavailable else None):
                    context=browser.new_context(viewport={'width':width,'height':900});cookie=case.client().get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}]);context.add_init_script(TRACE)
                    page=context.new_page();scripts=[];catalogs=[];posts=[];errors=[]
                    page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
                    def route(r):
                        if not r.request.url.startswith(origin):r.abort();return
                        if '/static/kilas_chat_models.js?' in r.request.url:scripts.append(r);return
                        if '/kilas-ai/chat/models' in r.request.url or '/kilas-ai/chat/image-models' in r.request.url:catalogs.append(r);return
                        r.continue_()
                    page.route('**/*',route)
                    def labels(scope):
                        for kind,name in expected[scope].items():expect(page.locator('[data-model-kind='+kind+'] [data-model-label]')).to_have_text(name)
                        assert page.evaluate('Object.values(qaLabels).every(values=>values.length===1)'),page.evaluate('qaLabels')
                    def settle(scope,first=False):
                        labels(scope)
                        if first:assert page.evaluate('typeof window.KilasChatModels')=='undefined'
                        while scripts:
                            r=scripts.pop(0);r.fulfill(response=r.fetch())
                        page.wait_for_function('!!window.KilasChatModels&&!!window.KilasImageModels');labels(scope)
                        if first:
                            assert page.evaluate('KilasChatModels.value()')==''
                            expect(page.locator('[data-model-kind=chat] .model-provider-icon')).to_be_visible()
                        page.wait_for_timeout(100);assert catalogs or not first
                        while catalogs:
                            r=catalogs.pop(0);r.fulfill(response=r.fetch())
                        a,b=ids[scope];page.wait_for_function('([a,b])=>KilasChatModels.value()===a&&KilasImageModels.value()===b',arg=[a,b]);labels(scope)
                    page.goto(origin+paths[surface],wait_until='commit');settle(surface,True)
                    warning=page.locator('[data-model-warning=image]')
                    if unavailable:expect(warning).to_be_visible();expect(warning).to_contain_text('unavailable')
                    else:expect(warning).to_be_hidden()
                    page.screenshot(path=str(output/f'{surface}-{width}-{unavailable}.png'))
                    page.reload(wait_until='commit');settle(surface,True)
                    page.get_by_role('link',name='Translator',exact=True).click();expect(page.locator('#live-setup-form button')).to_have_text('Start');expect(page.locator('[name=consent]')).not_to_be_checked()
                    page.get_by_role('link',name='AI Chat',exact=True).click();settle('home')
                    page.go_back(wait_until='domcontentloaded');expect(page.locator('#live-setup-form')).to_be_visible()
                    page.go_back(wait_until='commit');settle(surface)
                    page.go_forward(wait_until='domcontentloaded');page.go_forward(wait_until='commit');settle('home')
                    assert all(url==origin+'/kilas-ai/work/preferences' for url in posts) and not errors,(posts,errors)
                    assert model_preferences.get(case.owner,'chat')=='claude-opus-5-5'
                    assert chat_models.preference(case.owner,'thread',thread)=='gpt-6-luna'
                    report.append({'width':width,'surface':surface,'unavailable':unavailable,'before_javascript':'PASS','during_catalog_delay':'PASS','reload_switch_back_forward':'PASS','label_mutations':page.evaluate('qaLabels'),'paid_calls':0});print('PASS '+json.dumps(report[-1]),flush=True)
                    context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps(report,indent=2))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
