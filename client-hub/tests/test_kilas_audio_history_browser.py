"""Recent pagination against local Flask; synthetic stored media, no provider IO."""
import json
import os
import shutil
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from test_kilas_audio import f,provider,mp3
from test_kilas_audio_history import AudioHistoryTests
from kilas_ai import providers,audio_branded_voices as branded,audio_transcription_provider as stt


def main():
    clip=mp3(60)
    server=make_server('127.0.0.1',0,f.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_AUDIO_HISTORY_SCREENSHOTS','/tmp/kilas-audio-history-browser'));output.mkdir(parents=True,exist_ok=True)
    report={'scope':'local Flask/Chromium and synthetic stored MP3','paid_calls':0,'cases':[]}
    try:
        blocked=AssertionError('No provider IO during pagination')
        with patch.object(provider,'request',side_effect=blocked),patch.object(providers,'_openai',side_effect=blocked),patch.object(stt,'transcribe',side_effect=blocked),patch.object(branded,'public_choices',return_value=[{'alias':'kilas-male','name':'Kilas Male'}]),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox','--autoplay-policy=no-user-gesture-required'])
            for count,width in ((0,390),(4,390),(5,390),(9,390),(9,1440)):
                case=AudioHistoryTests('test_zero_four_five_nine_and_identical_timestamp_order')
                case.id=lambda:f'audio-history-browser-{count}-{width}'
                case.setUp();ids=case.seed(count)
                if count==9 and width==1440:
                    for upload in case.seed(5):f.db.execute("UPDATE kilas_audio_jobs SET mode='translate' WHERE id=?",(upload,))
                f.db.execute('INSERT INTO kilas_audio_balances(user_id,seconds) VALUES (?,1000)',(case.user,))
                if ids:f.db.execute('UPDATE kilas_audio_jobs SET result_content=?,actual_ms=60000 WHERE id=?',(clip,ids[-1]))
                context=browser.new_context(viewport={'width':width,'height':900},has_touch=width<761)
                cookie=case.client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}])
                page=context.new_page();errors=[];navigations=[];documents=[];paid=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('framenavigated',lambda frame:navigations.append(frame.url) if frame==page.main_frame else None)
                page.on('request',lambda r:paid.append(r.url) if r.method=='POST' else None)
                page.on('request',lambda r:documents.append(r.url) if r.is_navigation_request() and r.resource_type=='document' else None)
                page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                url=origin+(f'/kilas-translator/jobs/{ids[-1]}' if ids else '/kilas-translator')+'?mode=voiceover'
                page.goto(url,wait_until='networkidle')
                expect(page.locator('a[href^="/kilas-learning"], [data-home-task="learning"]')).to_have_count(0)
                expect(page.locator('.home-task-choices')).not_to_contain_text('Learning')
                history=page.locator('#audio-history')
                expect(history).not_to_be_visible()
                page.locator('.reference-history-toggle').click()
                expect(history).to_be_visible()
                expect(history.locator('[data-audio-history]')).to_have_count(min(4,count))
                expect(history.locator('.audio-history-pages')).to_have_count(int(count>4))
                if count<=4:
                    assert not errors and not paid,(errors,paid)
                    page.reload(wait_until='networkidle')
                    expect(page.locator('a[href^="/kilas-learning"], [data-home-task="learning"]')).to_have_count(0)
                    expect(history.locator('[data-audio-history]')).to_have_count(min(4,count))
                    page.screenshot(path=str(output/f'history-{count}-{width}.png'),full_page=True)
                    report['cases'].append({'records':count,'width':width,'visible':min(4,count),'pagination':False})
                    context.close();case.doCleanups();continue
                page.fill('#audio-script','Keep my unsaved draft.')
                page.locator('#voice-translate-toggle').check()
                page.select_option('#voice-translation-target','es')
                page.evaluate("""() => {
                  window.qaNodes=['audio-script','voiceover-panel','personal-voice-setup','audio-result'].map(id=>document.getElementById(id));
                  window.qaAudio=document.querySelector('#audio-result audio');qaAudio.loop=true;
                  window.qaForm=document.querySelector('#voiceover-panel form');window.qaKey=qaForm.querySelector('[name=operation_key]').value;
                }""")
                page.locator('#audio-result audio').evaluate('(e)=>e.play()')
                seen=list(reversed(ids))[:4]
                for number,length in ((2,1 if count==5 else 4),*(([(3,1)]) if count==9 else [])):
                    button=history.locator(f'[data-audio-history-page="{number}"]');button.scroll_into_view_if_needed()
                    y=page.evaluate('scrollY');current_time=page.evaluate('qaAudio.currentTime')
                    button.click()
                    expect(history.locator('[data-audio-history-state]')).to_have_attribute('data-page',str(number))
                    expect(history.locator('[data-audio-history]')).to_have_count(length)
                    expect(history.locator(f'[data-audio-history-page="{number}"]')).to_be_disabled()
                    assert abs(page.evaluate('scrollY')-y)<=1,(count,width,number,y,page.evaluate('scrollY'))
                    assert page.evaluate('qaAudio.isConnected && !qaAudio.paused && qaAudio===document.querySelector("#audio-result audio")')
                    assert page.evaluate('qaAudio.currentTime')>=current_time-.1
                    assert page.evaluate('qaNodes.every(n=>n.isConnected) && qaForm===document.querySelector("#voiceover-panel form") && qaKey===qaForm.querySelector("[name=operation_key]").value')
                    expect(page.locator('#audio-script')).to_have_value('Keep my unsaved draft.')
                    expect(page.locator('#voice-translate-toggle')).to_be_checked()
                    expect(page.locator('#voice-translation-target')).to_have_value('es')
                    seen.extend(int(value) for value in history.locator('[data-audio-history]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.audioHistory)'))
                assert seen==list(reversed(ids)),seen
                # A failed page request leaves the current list and draft intact.
                page.route('**/kilas-translator/history?*',lambda route:route.abort('failed'))
                history.locator('[data-audio-history-page="1"]').click()
                expect(history.locator('[data-audio-history-message]')).to_contain_text('belum dapat dimuat')
                expect(history.locator('[data-audio-history-state]')).to_have_attribute('data-page','3' if count==9 else '2')
                page.unroute('**/kilas-translator/history?*')
                # Editing while a request is pending must not lose text or focus.
                pending=[];page.route('**/kilas-translator/history?*',lambda route:pending.append(route))
                history.locator('[data-audio-history-page="1"]').click()
                expect(history.locator('[data-audio-history-content]')).to_have_attribute('aria-busy','true')
                page.fill('#audio-script','Edited while history was loading.')
                assert pending
                response=pending[0].fetch();pending[0].fulfill(response=response)
                expect(history.locator('[data-audio-history-state]')).to_have_attribute('data-page','1')
                expect(page.locator('#audio-script')).to_have_value('Edited while history was loading.')
                expect(page.locator('#audio-script')).to_be_focused()
                page.unroute('**/kilas-translator/history?*')
                assert page.evaluate('qaAudio.isConnected && !qaAudio.paused')
                assert len(navigations)==1 and page.url==url,navigations
                # Existing delegated Edit actions still work on a newly loaded page.
                history.locator('[data-audio-history-page="2"]').click()
                expect(history.locator('[data-audio-history-state]')).to_have_attribute('data-page','2')
                page.once('dialog',lambda dialog:dialog.accept())
                history.locator('[data-audio-edit]').first.click()
                expect(page.locator('#audio-script')).to_have_value('Original script')
                assert page.evaluate('qaAudio.isConnected && !qaAudio.paused')
                if count==9 and width==1440:
                    page.locator('#translate-tab').click()
                    expect(history.locator('[data-audio-history-state]')).to_have_attribute('data-kind','translate')
                    expect(history.locator('[data-audio-history]')).to_have_count(4)
                    page.evaluate("""() => {const input=document.querySelector('#audio-file'),files=new DataTransfer();files.items.add(new File(['synthetic local selection'],'keep-selected.wav',{type:'audio/wav'}));input.files=files.files;window.qaFile=input;}""")
                    button=history.locator('[data-audio-history-page="2"]');button.scroll_into_view_if_needed()
                    y=page.evaluate('scrollY');active_url=page.url;button.click()
                    expect(history.locator('[data-audio-history-state]')).to_have_attribute('data-page','2')
                    expect(history.locator('[data-audio-history]')).to_have_count(1)
                    expect(page.locator('#translate-tab')).to_have_attribute('aria-selected','true')
                    assert page.evaluate('qaFile===document.querySelector("#audio-file") && qaFile.files[0].name==="keep-selected.wav"')
                    assert abs(page.evaluate('scrollY')-y)<=1 and page.url==active_url
                    assert page.evaluate('qaAudio.isConnected && !qaAudio.paused')
                assert not errors and not paid,(errors,paid)
                assert len(documents)==1,documents
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(output/f'history-{count}-{width}.png'),full_page=True)
                report['cases'].append({'records':count,'width':width,'pages':(count+3)//4,'scroll_form_audio_and_retry':'PASS','document_loads':len(documents)})
                page.reload(wait_until='networkidle')
                expect(page.locator('a[href^="/kilas-learning"], [data-home-task="learning"]')).to_have_count(0)
                expect(page.locator('.home-task-choices')).not_to_contain_text('Learning')
                report['cases'][-1]['retired_learning_absent_after_refresh']=True
                context.close();case.doCleanups()
            browser.close()
        (output/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:server.shutdown()


if __name__=='__main__':main()
