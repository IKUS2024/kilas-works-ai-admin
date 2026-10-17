"""Typography/layout only: synthetic local text/files, no microphone or inference."""
import json
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_home as home
from kilas_ai import agent_store,chat_models,image_models,model_preferences,live_translator as live,audio_branded_voices as branded

MEASURE="""()=>{function item(q){const n=document.querySelector(q);if(!n)return null;const r=n.getBoundingClientRect(),s=getComputedStyle(n),v=n.querySelector('svg')?.getBoundingClientRect();return {font:s.fontFamily,size:parseFloat(s.fontSize),line:parseFloat(s.lineHeight),x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom,center:r.y+r.height/2,svgCenter:v?v.y+v.height/2:null,firstLine:r.y+parseFloat(s.paddingTop)+parseFloat(s.lineHeight)/2,padBottom:parseFloat(s.paddingBottom)}}return {body:item('body'),composer:item('#ai-composer,#agent-chat-form .ai-composer'),input:item('#ai-input,#agent-message'),plus:item('.ai-attach,.work-add-file'),send:item('.ai-composer-actions .ai-send'),call:item('.ai-call-launch'),main:item('.ai-main'),models:item('.chat-model-controls'),overflow:document.documentElement.scrollWidth>innerWidth,docScroll:document.documentElement.scrollHeight,innerHeight}}"""
TEXT='''## A clear next step / Langkah berikutnya

Kita membahas rencana sederhana dengan jarak baca yang nyaman. Keep each paragraph readable and natural, including café, español, 中文 and العربية.

- Tentukan tujuan dan anggaran.
- Review the result before the next action.

Use `contoh_identifier_panjang_1234567890` inline when needed.

```python
very_long_identifier = "'''+('synthetic_text_'*18)+'''"
for item in range(3):
    print(item)
```
'''


def main():
    case=home.HomeTests('test_old_routes_still_render');case.id=lambda:'typography-browser';case.setUp()
    empty=agent_store.new_conversation(case.owner);populated=agent_store.new_conversation(case.owner)
    for i in range(5):
        agent_store.append(case.owner,'user','Synthetic discussion '+str(i),populated)
        agent_store.append(case.owner,'assistant',TEXT,populated)
    model_preferences.remember(case.owner,'chat','gemini-3.5-flash-lite');model_preferences.remember(case.owner,'image','gemini-3.1-flash-lite-image')
    server=make_server('127.0.0.1',0,home.fixture.base.f.fixture.app.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(tempfile.gettempdir())/'kilas-typography-browser';output.mkdir(exist_ok=True);report=[]
    try:
        with patch.object(live,'ready',return_value=True),patch.object(branded,'public_choices',return_value=[{'alias':'kilas-male','name':'Kilas Male'}]),patch.object(chat_models,'check',side_effect=lambda m:{**chat_models.spec(m),'available':True,'images':True,'status':'verified'}),patch.object(image_models,'check',side_effect=lambda m:{**image_models.spec(m),'available':True,'status':'verified'}),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM','/usr/bin/chromium'),args=['--no-sandbox'])
            for width in (320,360,390,768,1024,1440):
                context=browser.new_context(viewport={'width':width,'height':900},has_touch=width<1024,reduced_motion='reduce');cookie=case.client().get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}]);context.add_init_script("navigator.mediaDevices.getUserMedia=async()=>{throw Error('Microphone forbidden')}")
                context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort());page=context.new_page();errors=[];posts=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
                for surface,path in [('home','/products/start'),('agent',f'/kilas-ai/agent?conversation={empty}')]:
                    page.goto(origin+path,wait_until='networkidle');page.evaluate('document.fonts.ready');metrics=page.evaluate(MEASURE)
                    assert metrics['body']['size']==16 and 'Manrope' in metrics['body']['font']
                    assert not metrics['overflow'] and metrics['docScroll']<=901
                    assert all(abs(metrics[k]['svgCenter']-metrics['input']['firstLine'])<=1 for k in ('plus','send','call')),metrics
                    assert all(abs(metrics[k]['center']-metrics[k]['svgCenter'])<=1 and metrics[k]['h']>=44 for k in ('plus','send','call')),metrics
                    assert abs((metrics['plus']['x']-metrics['composer']['x'])-(metrics['composer']['right']-metrics['call']['right']))<=1,metrics
                    assert abs(metrics['models']['x']+metrics['models']['w']/2-(metrics['main']['x']+metrics['main']['w']/2))<=1,metrics
                    assert metrics['plus']['x']<metrics['input']['x']<metrics['send']['x']<metrics['call']['x']
                    field=page.locator('#ai-input,#agent-message');field.fill('Baris pertama\nSecond line for discussion\nBaris ketiga\nFourth line')
                    multi=page.evaluate(MEASURE);assert multi['input']['h']>44 and not multi['overflow']
                    assert all(abs(multi[k]['bottom']-multi['input']['bottom'])<=1 for k in ('plus','send','call')),multi
                    field.fill('')
                    picker=page.locator('#ai-files,#work-source-files');picker.set_input_files({'name':'synthetic-planning-notes-with-a-long-name.txt','mimeType':'text/plain','buffer':b'Synthetic layout fixture.'})
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                    pending=page.locator('#ai-pending,#work-pending-files');expect(pending).to_contain_text('synthetic-planning')
                    pending.locator('button').first.click();expect(pending).to_have_text('')
                    field.focus();page.set_viewport_size({'width':width,'height':360});page.wait_for_timeout(100)
                    keyboard=page.evaluate(MEASURE);assert not keyboard['overflow'] and keyboard['docScroll']<=361,keyboard
                    expect(page.locator('.ai-call-launch')).to_be_in_viewport();page.set_viewport_size({'width':width,'height':900});field.blur()
                    if width in (320,768,1440):page.screenshot(path=str(output/f'{surface}-{width}.png'))
                    report.append({'surface':surface,'width':width,'single_line_alignment_error_px':max(abs(metrics[k]['svgCenter']-metrics['input']['firstLine']) for k in ('plus','send','call')),'multiline_attachment_keyboard':'PASS','font':metrics['body']['font'],'input_px':metrics['input']['size'],'empty_no_scroll':'PASS'})
                page.goto(origin+f'/kilas-ai/agent?conversation={populated}',wait_until='networkidle');page.evaluate('document.fonts.ready')
                prose=page.locator('.agent-message-assistant .agent-message-text').first
                assert prose.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)===16&&Math.abs(parseFloat(getComputedStyle(e).lineHeight)-26.4)<.2&&getComputedStyle(e).textAlign!=="justify"')
                code=prose.locator('pre code').first;expect(code).to_be_visible();assert 'monospace' in code.evaluate('e=>getComputedStyle(e).fontFamily')
                assert code.evaluate('e=>e.parentElement.scrollWidth>e.parentElement.clientWidth')
                timeline=page.locator('#agent-conversation');assert timeline.evaluate('e=>e.scrollHeight>e.clientHeight')
                timeline.evaluate('e=>e.scrollTop=30');page.locator('#agent-message').fill('Draft while reading');assert abs(timeline.evaluate('e=>e.scrollTop')-30)<=1
                page.locator('#agent-message').fill('');assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                if width in (320,768,1440):page.screenshot(path=str(output/f'prose-{width}.png'))
                # Text-size zoom is independent of a physical device/pinch zoom.
                page.goto(origin+'/products/start',wait_until='networkidle');page.evaluate("document.documentElement.style.fontSize='20px'");page.wait_for_timeout(100)
                zoom=page.evaluate(MEASURE);assert zoom['body']['size']==20 and zoom['input']['size']==20 and not zoom['overflow'],zoom
                assert all(abs(zoom[k]['svgCenter']-zoom['input']['firstLine'])<=1 for k in ('plus','send','call')),zoom
                for surface,path in [('translator','/kilas-translator/live'),('voiceover','/kilas-translator?mode=voiceover')]:
                    page.goto(origin+path,wait_until='networkidle');assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                    controls=page.locator('#live-setup-form select,#kilas-voice-choice,#audio-script')
                    for control in controls.all():assert control.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)>=16')
                    if surface=='translator':
                        expect(page.locator('[name=consent]')).not_to_be_checked();expect(page.locator('.live-consent a')).to_have_count(0);expect(page.locator('#live-setup-form button')).to_have_text('Start')
                    else:expect(page.locator('#play-personal-preview,#open-recorder,#personal-preview')).to_have_count(0)
                    if width in (320,768,1440):page.screenshot(path=str(output/f'{surface}-{width}.png'),full_page=True)
                    report.append({'surface':surface,'width':width,'editable_input_min_px':16,'overflow':False})
                assert all(url==origin+'/kilas-ai/work/preferences' for url in posts) and not errors,(posts,errors)
                print('PASS typography/alignment/empty+populated/attachments/keyboard/textzoom/modules '+str(width),flush=True);context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps(report,indent=2))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
