"""Six-reference responsive UI evidence using disposable accounts, no paid IO."""
import json, logging, os, threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_experience as home
import test_kilas_interpreter as interpreter
import test_kilas_audio as audio
from kilas_ai import chat_models, image_models, audio_branded_voices as branded

def main():
    output=Path(os.environ.get('KILAS_REFERENCE_SCREENSHOTS','.impeccable/review')).resolve();output.mkdir(parents=True,exist_ok=True)
    report={'paid_calls':0,'synthetic_audio':True,'captures':[],'checks':[]}
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    app=audio.f.app.app
    server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            def page_for(client,width,height):
                context=browser.new_context(viewport={'width':width,'height':height},reduced_motion='reduce')
                cookie=client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
                page=context.new_page();page.errors=[];page.on('pageerror',lambda e:page.errors.append(str(e)))
                page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                return context,page
            def capture(page,name,width):
                page.evaluate('document.activeElement?.blur();document.querySelectorAll("*").forEach(e=>{if(e.scrollTop)e.scrollTop=0});scrollTo(0,0)');page.wait_for_timeout(100)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(name,width,'horizontal overflow')
                assert not page.errors,(name,width,page.errors)
                if name.startswith('call-'):
                    bounds=page.evaluate("""()=>{const dialog=document.querySelector('#ai-call-dialog'),chrome=dialog.querySelector('.reference-call-chrome'),capsule=dialog.querySelector('.reference-call-status'),footer=dialog.querySelector('.ai-call-footer');const rect=e=>({top:e.getBoundingClientRect().top,bottom:e.getBoundingClientRect().bottom,height:e.getBoundingClientRect().height});return {height:innerHeight,chrome:rect(chrome),capsule:rect(capsule),footer:rect(footer),scroll:dialog.scrollTop}}""")
                    assert bounds['chrome']['top']>=0 and bounds['chrome']['height']>=36,(name,width,bounds)
                    if name=='call-connecting':assert bounds['capsule']['height']>=40 and bounds['capsule']['bottom']<=bounds['footer']['top']+1,(name,width,bounds)
                    report.setdefault('call_regions',[]).append({'name':name,'width':width,**bounds})
                report.setdefault('geometry',[]).append({'name':name,'width':width,**page.evaluate("""()=>{const h=document.querySelector('.kilas-reference-header'),w=document.querySelector('body>.wrap');return {header:h?{top:h.getBoundingClientRect().top,height:h.getBoundingClientRect().height,display:getComputedStyle(h).display,position:getComputedStyle(h).position}:null,wrap:w?{top:w.getBoundingClientRect().top,left:w.getBoundingClientRect().left,width:w.getBoundingClientRect().width,position:getComputedStyle(w).position}:null,scrollY}}""")})
                path=output/f'{name}-{width}.png';page.screenshot(path=str(path),full_page=True);report['captures'].append(str(path))
            sizes=((1440,1000),(1024,768),(820,1100),(768,1024),(412,760),(390,760),(320,700),(844,390))
            case=home.ExperienceTests('test_starters_follow_ui_language_without_changing_models');case.setUp()
            try:
                thread=home.store.create_thread(case.owner)
                home.store.append_user_once(case.owner,thread,'Synthetic latest message. '+('Long content '*30),'SMART','polish-filled-chat')
                with patch.object(chat_models,'check',side_effect=lambda m:{**chat_models.spec(m),'available':True,'images':True,'status':'verified'}),patch.object(image_models,'check',side_effect=lambda m:{**image_models.spec(m),'available':True,'status':'verified'}):
                    for width,height in sizes:
                        context,page=page_for(case.client(),width,height);page.goto(origin+'/products/start',wait_until='networkidle')
                        expect(page.locator('.kilas-new-chat-logo')).to_be_visible();capture(page,'chat',width)
                        page.locator('[data-model-kind=chat] .chat-model-trigger').click()
                        expect(page.locator('#chat-model-dialog')).to_be_visible()
                        box=page.locator('#chat-model-dialog').bounding_box()
                        assert box['x']>=0 and box['x']+box['width']<=width+1 and box['y']>=0 and box['y']+box['height']<=height+1,(width,box)
                        capture(page,'chat-model-menu',width)
                        page.locator('#chat-model-dialog [data-model-close]').click()
                        page.locator('#ai-input').fill('Synthetic unsent draft '+('long content '*12));page.locator('#ai-files').set_input_files({'name':'synthetic.txt','mimeType':'text/plain','buffer':b'synthetic attachment'})
                        expect(page.locator('#ai-pending .ai-pending-item')).to_have_count(1);page.locator('#ai-pending button').click();page.locator('#ai-input').fill('')
                        page.locator('[data-premium-menu]').click();expect(page.locator('#premium-sidebar')).not_to_have_attribute('inert','');capture(page,'drawer',width);page.keyboard.press('Escape')
                        assert page.locator('[data-premium-menu]').get_attribute('aria-expanded')=='false'
                        page.locator('[data-ai-call-launch]').click();expect(page.locator('#ai-call-settings')).to_be_visible();capture(page,'call-setup',width)
                        # Hold readiness pending to inspect real connecting state without mic/provider admission.
                        page.evaluate("""()=>{const fetch=window.fetch;window.fetch=(url,options)=>String(url).endsWith('/call/readiness')?new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true})):fetch(url,options)}""")
                        page.locator('#ai-call-start').click();expect(page.locator('#ai-call-dialog')).to_have_attribute('data-state','connecting');capture(page,'call-connecting',width)
                        page.locator('#ai-call-mute').click();expect(page.locator('#ai-call-mute')).to_have_attribute('aria-pressed','true');page.locator('#ai-call-hold').click();expect(page.locator('#ai-call-hold')).to_have_attribute('aria-pressed','true');page.locator('#ai-call-speaker').click();expect(page.locator('#ai-call-speaker')).to_have_attribute('aria-pressed','false')
                        page.locator('#ai-call-end').click();expect(page.locator('#ai-call-dialog')).not_to_be_visible()
                        page.locator('#ai-input').fill('Retained keyboard draft');page.set_viewport_size({'width':width,'height':380});page.wait_for_timeout(100)
                        assert page.locator('#ai-composer').evaluate('e=>e.getBoundingClientRect().bottom<=innerHeight+1')
                        capture(page,'chat-keyboard',width)
                        page.set_viewport_size({'width':width,'height':height})
                        page.goto(origin+f'/kilas-ai/threads/{thread}',wait_until='networkidle')
                        expect(page.locator('#ai-messages')).to_contain_text('Synthetic latest message.')
                        page.locator('#ai-input').fill('A multiline draft\n'*8)
                        page.locator('#ai-files').set_input_files([{'name':f'synthetic-long-attachment-{i}.txt','mimeType':'text/plain','buffer':b'synthetic attachment'} for i in range(2)])
                        expect(page.locator('#ai-pending .ai-pending-item')).to_have_count(2)
                        geometry=page.evaluate("""()=>{const r=s=>document.querySelector(s).getBoundingClientRect();return {messages:r('#ai-messages').toJSON(),composer:r('#ai-composer').toJSON(),pending:r('#ai-pending').toJSON()}}""")
                        assert geometry['messages']['bottom']<=geometry['composer']['top']+1,(width,geometry)
                        assert geometry['pending']['top']>=geometry['composer']['top'] and geometry['composer']['bottom']<=height+1,(width,geometry)
                        capture(page,'chat-filled-attachments',width)
                        report['checks'].append({'surface':'chat/call','width':width,'errors':page.errors,'filled':geometry});context.close()
            finally:case.doCleanups()
            case=interpreter.InterpreterTests('test_owner_member_route_and_csrf_isolation');case.setUp()
            try:
                with case.enabled():
                    for width,height in sizes:
                        context,page=page_for(case.client,width,height);page.goto(origin+'/kilas-translator/interpreter',wait_until='networkidle');capture(page,'translator-setup',width)
                        expect(page.locator('#premium-sidebar')).to_have_count(0)
                        expect(page.locator('[data-premium-menu]')).to_have_count(0)
                        a=page.locator('#interpreter-language-a');b=page.locator('#interpreter-language-b');assert a.input_value()!=b.input_value()
                        page.locator('#interpreter-swap').click();assert a.input_value()=='en';page.reload(wait_until='networkidle');assert a.input_value()=='en';assert not page.locator('#interpreter-consent').is_checked()
                        page.locator('#interpreter-swap').click();page.locator('#interpreter-consent').check();page.locator('#interpreter-start').click();expect(page.locator('#interpreter-active')).to_be_visible();capture(page,'translator-active',width)
                        page.locator('#interpreter-end').click();expect(page.locator('#interpreter-setup')).to_be_visible();context.close();report['checks'].append({'surface':'translator','width':width,'pair_reload_consent_end':True})
            finally:case.doCleanups()
            audio.AudioTests.setUpClass();case=audio.AudioTests('test_shared_balance_actual_seconds');case.setUp();case.credit(300)
            try:
                with patch.dict(os.environ,{'KILAS_AUDIO_UPLOAD_TRANSLATION_VISIBLE':'false'}),patch.object(branded,'choices',return_value=[{'alias':'kilas-male','id':'available456','name':'Kilas Male','style':'Natural'},{'alias':'kilas-female','id':'available123','name':'Kilas Female','style':'Natural'}]),patch.object(branded,'sample_aliases',return_value=['kilas-male','kilas-female']),patch.object(audio.provider,'voices',return_value=[{'id':'available456','name':'Kilas Male','style':'Natural'}]):
                    for width,height in sizes:
                        context,page=page_for(case.client,width,height);page.goto(origin+'/kilas-translator?mode=voiceover',wait_until='networkidle');expect(page.locator('#audio-script')).to_have_value('');expect(page.locator('#audio-history')).not_to_be_visible();capture(page,'voiceover',width)
                        expect(page.locator('#premium-sidebar')).to_have_count(0)
                        expect(page.locator('[data-premium-menu]')).to_have_count(0)
                        page.locator('.reference-history-toggle').click();expect(page.locator('#audio-history')).to_be_visible();page.locator('.reference-history-toggle').click();expect(page.locator('#audio-history')).not_to_be_visible()
                        page.locator('#audio-script').fill('Synthetic long script. '*100);expect(page.locator('#reference-script-count')).to_contain_text('2,300');page.locator('#audio-script').fill('');context.close();report['checks'].append({'surface':'voiceover','width':width,'fresh':True})
            finally:case.doCleanups()
            browser.close()
    finally:server.shutdown()
    (output/'six-reference-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
