"""Real upload/audio/download/paywall DOM across all seven launch widths; mock provider only."""
import os
import shutil
import struct
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_kilas_audio import AudioTests, f, provider, wav
from kilas_ai import providers, model_policy, audio_branded_voices as branded


def script_reply(*args, **kwargs):
    yield {'type':'provider','provider':'openai','model':model_policy.LUNA}
    yield {'type':'delta','text':'Produk ini cocok untuk kebutuhan harian. Silakan periksa detail sebelum memilih dan membeli.'}
    yield {'type':'usage','input_tokens':4,'output_tokens':16}
    yield {'type':'finish','reason':'stop'}


DICTATION_MOCK = """window.SpeechRecognition=class {
 start(){window.qaDictation=this;window.qaMicStarts=(window.qaMicStarts||0)+1;}
 stop(){window.qaMicStops=(window.qaMicStops||0)+1;this.onend?.();}
 abort(){window.qaMicAborts=(window.qaMicAborts||0)+1;this.onend?.();}
};"""


def main():
    AudioTests.setUpClass()
    server=make_server('127.0.0.1',0,f.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_AUDIO_SCREENSHOTS',str(Path(tempfile.gettempdir())/'kilas-audio-browser')));output.mkdir(exist_ok=True)
    try:
        with patch.object(branded,'choices',return_value=[{'alias':'kilas-male','id':'available456','name':'Kilas Male','style':'Natural'},{'alias':'kilas-female','id':'available123','name':'Kilas Female','style':'Natural'}]),patch.object(provider,'voices',return_value=[{'id':'available123','name':'QA Warm','style':'Female · Warm'},{'id':'available456','name':'QA Professional','style':'Male · Professional'}]),patch.object(provider,'speech',return_value=(AudioTests.audio,'qa-request')),patch.object(provider,'dub',return_value='qa-dubbing'),patch.object(provider,'dub_status',return_value={'status':'dubbed','source_language':'id'}),patch.object(provider,'dub_result',return_value=AudioTests.audio),patch.object(providers,'stream',side_effect=script_reply),sync_playwright() as p:
            browser=p.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (320,360,390,430,768,1024,1440):
                case=AudioTests('test_shared_balance_actual_seconds');case.id=lambda:'audio-browser-'+str(width);case.setUp();case.credit(300)
                context=browser.new_context(viewport={'width':width,'height':900},has_touch=width<761,reduced_motion='reduce')
                context.add_init_script(DICTATION_MOCK + "Object.defineProperty(crypto,'randomUUID',{value:undefined});")
                context.grant_permissions(['clipboard-read','clipboard-write'])
                cookie=case.client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}])
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                def check(name):
                    page.evaluate('document.activeElement?.blur();scrollTo(0,0)')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,name)
                    if page.locator('input[type=file]').count():
                        style=page.locator('input[type=file]').first.evaluate("el=>{const s=getComputedStyle(el,'::file-selector-button');return [s.backgroundColor,s.color,s.fontSize]}")
                        assert style[0]=='rgb(247, 247, 246)' and style[1]=='rgb(32, 35, 41)' and style[2]=='14px',style
                    if page.locator('.audio-pack').count():
                        assert page.locator('.audio-pack>strong').evaluate_all("es=>es.every(el=>getComputedStyle(el).whiteSpace==='nowrap' && el.scrollWidth<=el.clientWidth)")
                    if page.locator('#audio-script').count():
                        assert page.locator('#audio-script').evaluate('el=>getComputedStyle(el).backgroundColor')=='rgb(255, 255, 255)'
                    page.screenshot(path=str(output/f'{name}-{width}.png'),full_page=True)
                def clean_workbench():
                    expect(page.locator('#audio-packs')).to_have_count(0)
                    expect(page.get_by_role('heading',name='Saldo untuk dua cara berkarya.')).to_have_count(0)
                    expect(page.locator('.audio-balance')).to_have_count(0)
                page.goto(origin+'/kilas-translator?mode=translate',wait_until='networkidle');expect(page.get_by_role('heading',name='Kilas Translator',exact=True)).to_be_visible();check('translate')
                clean_workbench()
                # Exercise the actual global file validator and server multipart cap together.
                raw=wav(3)
                if width==1440:
                    raw+=b'JUNK'+struct.pack('<I',26*1024*1024)+b'\0'*(26*1024*1024)
                    raw=raw[:4]+struct.pack('<I',len(raw)-8)+raw[8:]
                page.locator('#audio-file').set_input_files({'name':'synthetic.wav','mimeType':'audio/wav','buffer':raw})
                expect(page.locator('#audio-duration')).to_contain_text('memakai 3s',timeout=20000)
                assert page.locator('#audio-file').evaluate('el=>el.validity.valid')
                page.select_option('#translate-panel select[name=language]','en');page.locator('#translate-panel button[type=submit]').click()
                expect(page).to_have_url(__import__('re').compile(r'/kilas-translator/jobs/\d+'),timeout=20000)
                expect(page.locator('#audio-result audio')).to_be_visible(timeout=20000);expect(page.locator('.audio-balance')).to_have_count(0);expect(page.locator('[data-audio-history-status]')).to_have_text('Selesai');check('result')
                audio=page.locator('#audio-result audio');expect(audio).to_have_attribute('src',__import__('re').compile('/result'))
                audio.evaluate('el=>el.play()');assert audio.evaluate('el=>!el.paused')
                audio.evaluate('el=>el.pause()')
                with page.expect_download() as downloaded:page.get_by_role('link',name='Download MP3').click()
                assert downloaded.value.suggested_filename.endswith('-English.mp3')
                page.reload(wait_until='networkidle');expect(page.locator('#audio-result audio')).to_be_visible()
                page.get_by_role('link',name='Translate another').click();page.locator('#voiceover-tab').click();expect(page.locator('#voiceover-panel')).to_be_visible()
                assert page.evaluate('window.qaMicStarts||0')==0
                page.locator('#voice-script-assist > summary').click()
                page.locator('.voice-dictation-info > summary').click()
                expect(page.locator('#voice-assist-mic-note')).to_be_visible()
                page.locator('.voice-dictation-info > summary').click()
                expect(page.locator('#voice-assist-script')).to_have_count(0)
                expect(page.get_by_role('button',name='Pakai naskah')).to_have_count(0)
                page.locator('#voice-assist-generate').click();expect(page.locator('#voice-assist-status')).to_contain_text('terlebih dahulu')
                expect(page.locator('#voice-assist-copy')).to_be_disabled()
                page.select_option('#voice-assist-mode','generate')
                page.locator('#voice-assist-mic').click();expect(page.locator('#voice-assist-mic-stop')).to_be_visible()
                page.evaluate("qaDictation.onresult({resultIndex:0,results:[Object.assign([{transcript:'Naskah promosi yang singkat.'}],{isFinal:true})]})")
                expect(page.locator('#voice-assist-prompt')).to_have_value('Naskah promosi yang singkat.')
                page.locator('#voice-assist-mic-stop').click();expect(page.locator('#voice-assist-mic-stop')).to_be_hidden()
                expect(page.locator('#audio-script')).to_have_value('')
                audio_jobs=[];page.on('request',lambda req:audio_jobs.append(req.url) if req.method=='POST' and '/kilas-translator/jobs' in req.url else None)
                page.locator('#voice-assist-generate').click();expect(page.locator('#voice-assist-status')).to_contain_text('masuk ke kolom',timeout=20000)
                expect(page.locator('#audio-script')).to_have_value('Produk ini cocok untuk kebutuhan harian. Silakan periksa detail sebelum memilih dan membeli.')
                expect(page.locator('#voice-assist-history')).to_have_attribute('href',__import__('re').compile('/kilas-ai/threads/'))
                page.locator('#voice-assist-undo').click();expect(page.locator('#audio-script')).to_have_value('')
                page.fill('#audio-script','Naskah asli sebelum dirapikan.')
                # Direct AI apply invalidates a previous translated preview via the ordinary input event.
                page.locator('#voice-translate-toggle').check()
                page.route('**/voice-script/translate',lambda route:route.fulfill(status=200,content_type='application/json',body='{"text":"Previous translation","source_language":"id"}'))
                page.locator('#voice-translate-preview').click();expect(page.locator('#voice-translated-result')).to_be_visible()
                page.select_option('#voice-assist-mode','tidy')
                page.locator('#voice-assist-generate').click();expect(page.locator('#voice-assist-status')).to_contain_text('masuk ke kolom',timeout=20000)
                expect(page.locator('#voice-translated-result')).to_be_hidden()
                page.locator('#voice-assist-undo').click();expect(page.locator('#audio-script')).to_have_value('Naskah asli sebelum dirapikan.')
                expect(page.locator('#voice-translated-result')).to_be_hidden()
                page.locator('#voice-translate-toggle').uncheck();page.unroute('**/voice-script/translate')
                page.locator('#voice-assist-generate').click();expect(page.locator('#voice-assist-status')).to_contain_text('masuk ke kolom',timeout=20000)
                page.fill('#audio-script','Naskah sintetis yang telah saya edit.')
                expect(page.locator('#voice-assist-undo')).to_be_hidden()
                page.locator('#voice-assist-copy').click();expect(page.locator('#voice-assist-status')).to_have_text('Naskah disalin.')
                assert page.evaluate('navigator.clipboard.readText()')=='Naskah sintetis yang telah saya edit.'
                assert audio_jobs==[],audio_jobs
                page.locator('#voice-assist-mic').click();page.evaluate("qaDictation.onerror({error:'not-allowed'});qaDictation.onend()")
                expect(page.locator('#voice-assist-status')).to_contain_text('Izin mic tidak diberikan')
                page.route('**/voice-script',lambda route:route.fulfill(status=429,content_type='application/json',body='{"error":"Batas chat QA"}'))
                page.locator('#voice-assist-generate').click();expect(page.locator('#voice-assist-status')).to_have_text('Batas chat QA')
                expect(page.locator('#audio-script')).to_have_value('Naskah sintetis yang telah saya edit.')
                expect(page.locator('#voice-assist-generate')).to_be_enabled();page.unroute('**/voice-script')
                if width==320:
                    # Delay the response so edits cannot be overwritten, even if changed back to the snapshot.
                    page.evaluate("""window.qaOriginalFetch=window.fetch;window.fetch=(url,options)=>String(url).endsWith('/voice-script')?new Promise((resolve,reject)=>{window.qaResolve=resolve;options.signal.addEventListener('abort',()=>reject(new DOMException('Stopped','AbortError')))}):qaOriginalFetch(url,options);""")
                    page.locator('#voice-assist-generate').click();page.wait_for_function('!!window.qaResolve')
                    page.fill('#audio-script','Pengguna masih mengetik.');page.fill('#audio-script','Naskah sintetis yang telah saya edit.')
                    page.evaluate("qaResolve(new Response('event: delta\\ndata: {\"text\":\"Hasil terlambat\"}\\n\\nevent: done\\ndata: {}\\n\\n',{headers:{'Content-Type':'text/event-stream'}}));window.qaResolve=null")
                    expect(page.locator('#voice-assist-status')).to_contain_text('tidak menimpa')
                    expect(page.locator('#audio-script')).to_have_value('Naskah sintetis yang telah saya edit.')
                    page.locator('#voice-assist-generate').click();expect(page.locator('#voice-assist-stop')).to_be_visible()
                    page.locator('#voice-assist-stop').click();expect(page.locator('#voice-assist-status')).to_contain_text('AI dihentikan')
                    expect(page.locator('#audio-script')).to_have_value('Naskah sintetis yang telah saya edit.')
                    expect(page.locator('#voice-assist-generate')).to_be_enabled();expect(page.locator('#voice-assist-stop')).to_be_hidden()
                    page.evaluate('window.fetch=qaOriginalFetch')
                    page.locator('#voice-assist-mic').click();page.locator('#voice-script-assist > summary').click()
                    expect(page.locator('#voice-assist-mic-stop')).to_be_hidden();page.wait_for_function('(window.qaMicAborts||0)>0')
                    page.locator('#voice-script-assist > summary').click()
                    fallback=browser.new_context(viewport={'width':390,'height':900})
                    fallback.add_init_script('window.SpeechRecognition=undefined;window.webkitSpeechRecognition=undefined;')
                    fallback.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}])
                    typed=fallback.new_page();typed.goto(origin+'/kilas-translator',wait_until='networkidle');typed.locator('#voiceover-tab').click();typed.locator('#voice-script-assist > summary').click()
                    expect(typed.locator('#voice-assist-mic')).to_be_disabled();expect(typed.locator('#voice-assist-mic-note')).to_contain_text('Ketik arahan')
                    typed.select_option('#voice-assist-mode','generate');typed.fill('#voice-assist-prompt','Naskah dari ide yang diketik.');typed.locator('#voice-assist-generate').click();expect(typed.locator('#voice-assist-status')).to_contain_text('masuk ke kolom',timeout=20000)
                    expect(typed.locator('#audio-script')).not_to_have_value('')
                    fallback.close()
                assert audio_jobs==[],audio_jobs
                check('script-assist')
                page.locator('#voice-script-assist > summary').click()
                page.fill('#audio-script','Safe synthetic voice over.');expect(page.locator('#voice-estimate')).to_have_count(0)
                clean_workbench()
                page.locator('[name=voice_kind][value=kilas]').check();page.select_option('#kilas-voice-choice','kilas-male');check('voiceover')
                def generation_feedback(route):
                    expect(page.locator('#generation-feedback')).to_be_visible()
                    expect(page.locator('#generation-feedback')).to_have_attribute('data-state','busy')
                    expect(page.get_by_role('button',name='Sedang memproses...')).to_be_disabled()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    route.continue_()
                action=page.locator('#voiceover-panel form[data-audio-form]').get_attribute('action')
                page.route('**'+action,generation_feedback)
                redirect_dialogs=[]
                def record_redirect_dialog(dialog):redirect_dialogs.append(dialog.type);dialog.dismiss()
                page.on('dialog',record_redirect_dialog)
                page.get_by_role('button',name='Buat Voice Over').click();expect(page.locator('#audio-result audio')).to_be_visible(timeout=20000)
                page.remove_listener('dialog',record_redirect_dialog)
                assert redirect_dialogs==[],('Generate result redirect must not be interrupted',redirect_dialogs)
                expect(page.locator('#generation-feedback')).to_have_attribute('data-state','success')
                expect(page.locator('#generation-feedback')).to_contain_text('Audio tersimpan')
                page.locator('#generation-feedback-close').click();expect(page.locator('#generation-feedback')).to_be_hidden()
                page.unroute('**'+action)
                expect(page.locator('#voiceover-tab')).to_have_attribute('aria-selected','true');page.reload(wait_until='networkidle');expect(page.locator('#audio-result audio')).to_be_visible();check('voice-result')
                expect(page.locator('.audio-history li')).to_have_count(1)
                expect(page.locator('.audio-history [data-audio-history-state]')).to_have_attribute('data-kind','voiceover')
                edit=page.locator('#audio-result [data-audio-edit]')
                expect(edit).to_be_visible();page.fill('#audio-script','Unsaved newer draft.')
                page.once('dialog',lambda dialog:dialog.dismiss());edit.click();expect(edit).to_be_enabled();expect(page.locator('#audio-script')).to_have_value('Unsaved newer draft.')
                page.once('dialog',lambda dialog:dialog.accept());edit.click();expect(page.locator('#audio-script')).to_have_value('Safe synthetic voice over.')
                expect(page.locator('#voiceover-tab')).to_have_attribute('aria-selected','true')
                assert len(audio_jobs)==1,audio_jobs
                assert page.locator('[data-audio-edit]').evaluate_all("es=>es.every(e=>!e.closest('a'))")
                if width==320:
                    page.evaluate("window.qaEditFetch=fetch;window.fetch=(url,options)=>String(url).endsWith('/script')?new Promise(resolve=>window.qaEditResolve=resolve):qaEditFetch(url,options)")
                    page.locator('[name=voice_kind][value=kilas]').check();page.select_option('#kilas-voice-choice','kilas-male')
                    edit.click();page.wait_for_function('!!window.qaEditResolve');page.get_by_role('button',name='Buat Voice Over').click();assert len(audio_jobs)==1
                    page.fill('#audio-script','Changed during Edit fetch.')
                    page.evaluate("qaEditResolve(new Response(JSON.stringify({script:'Safe synthetic voice over.'}),{headers:{'Content-Type':'application/json'}}));window.fetch=qaEditFetch")
                    expect(page.locator('#audio-error')).to_contain_text('Draf telah berubah')
                    expect(page.locator('#audio-script')).to_have_value('Changed during Edit fetch.')
                if width==320:
                    page.fill('#audio-script','Draft before AI.');page.locator('#voice-script-assist > summary').click()
                    page.select_option('#voice-assist-mode','tidy')
                    page.evaluate("window.qaAIFetch=fetch;window.fetch=(url,options)=>String(url).endsWith('/voice-script')?new Promise(resolve=>window.qaAIResolve=resolve):qaAIFetch(url,options)")
                    page.locator('#voice-assist-generate').click();page.wait_for_function('!!window.qaAIResolve')
                    page.once('dialog',lambda dialog:dialog.accept());edit.click();expect(page.locator('#audio-script')).to_have_value('Safe synthetic voice over.')
                    page.evaluate("qaAIResolve(new Response('event: delta\\ndata: {\"text\":\"Late AI output\"}\\n\\nevent: done\\ndata: {}\\n\\n',{headers:{'Content-Type':'text/event-stream'}}));window.fetch=qaAIFetch")
                    expect(page.locator('#voice-assist-status')).to_contain_text('tidak menimpa')
                    expect(page.locator('#audio-script')).to_have_value('Safe synthetic voice over.')
                page.fill('#audio-script','Safe synthetic voice over.')
                page.locator('#translate-tab').click();expect(page.locator('#translate-panel')).to_be_visible()
                expect(page).to_have_url(__import__('re').compile('mode=translate'))
                page.reload(wait_until='networkidle');expect(page.locator('#translate-panel')).to_be_visible()
                page.locator('#voiceover-tab').click();expect(page.locator('#voiceover-panel')).to_be_visible()
                expect(page.locator('[data-kilas-feature=voiceover]')).to_have_attribute('aria-current','page')
                with page.expect_download() as wav_download:page.get_by_role('link',name='Download WAV',exact=True).click()
                assert wav_download.value.suggested_filename.endswith('.wav')
                wav_path=output/f'download-{width}.wav';wav_download.value.save_as(wav_path)
                assert wav_path.read_bytes()[:4]==b'RIFF' and wav_path.read_bytes()[8:12]==b'WAVE'
                page.route('**'+action,lambda route:route.fulfill(status=503,content_type='application/json',body='{"error":"Gangguan QA sintetis"}'))
                page.locator('[name=voice_kind][value=kilas]').check();page.select_option('#kilas-voice-choice','kilas-male')
                page.fill('#audio-script','Synthetic failure check.')
                page.get_by_role('button',name='Buat Voice Over').click()
                expect(page.locator('#generation-feedback')).to_have_attribute('data-state','error')
                expect(page.locator('#generation-feedback')).to_contain_text('Gangguan QA sintetis')
                expect(page.get_by_role('button',name='Buat Voice Over')).to_be_enabled()
                page.unroute('**'+action)

                # Low balance remains an error; temporary purchase UI is hidden.
                page.route('**'+action,lambda route:route.fulfill(status=402,content_type='application/json',body='{"error":"Saldo QA sintetis habis"}'))
                page.get_by_role('button',name='Buat Voice Over').click()
                expect(page.locator('#generation-feedback')).to_contain_text('Saldo QA sintetis habis')
                expect(page.locator('#audio-error-purchase')).to_be_hidden()
                page.unroute('**'+action);page.locator('#generation-feedback-close').click()
                page.goto(origin+'/kilas-ai/usage',wait_until='networkidle')
                expect(page.locator('#audio-settings-title,form[action="/kilas-translator/checkout"]')).to_have_count(0)
                # Existing checkout accounting stays covered server-side by test_kilas_audio.py.
                zero=f.repo.create_user(f'audio-zero-{width}@example.test','hash');client=f.app.app.test_client()
                from auth_test_helpers import authenticate
                authenticate(client,f.repo.get_user_by_id(zero),_csrf_token='zero-csrf')
                cookie=client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}])
                page.goto(origin+'/kilas-translator',wait_until='networkidle');expect(page.locator('.audio-balance,.audio-notice')).to_have_count(0);expect(page.locator('#translate-panel button[type=submit]')).to_be_disabled();check('paywall')
                clean_workbench()
                expect(page.locator('.audio-notice a')).to_have_count(0)
                page.goto(origin+'/kilas-ai/video',wait_until='networkidle');expect(page.get_by_role('heading',name='Kuota Kilas Video belum tersedia')).to_be_visible();expect(page.locator('#video-submit')).to_be_disabled()
                # Current presentation; explicit ON above retains full historical upload coverage.
                with patch.dict(os.environ,{'KILAS_AUDIO_UPLOAD_TRANSLATION_VISIBLE':'false'}):
                    cookie=case.client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}])
                    page.goto(origin+'/kilas-translator?mode=translate',wait_until='networkidle')
                    expect(page.get_by_role('heading',name='Voice Over',exact=True)).to_be_visible()
                    expect(page.locator('#translate-tab,#translate-panel,#audio-file,[data-kilas-feature=translate]')).to_have_count(0)
                    expect(page.locator('[data-kilas-feature]')).to_have_count(2)
                    expect(page.locator('#voiceover-panel')).to_be_visible()
                    page.locator('#voiceover-tab').press('ArrowRight');expect(page.locator('#voiceover-panel')).to_be_visible()
                    expect(page.locator('#voice-translate-toggle')).to_be_visible()
                    page.locator('#audio-script').fill('Editable current Voice Over draft')
                    page.locator('#voice-script-assist > summary').click();expect(page.locator('#voice-assist-generate')).to_be_visible()
                    page.goto(origin+'/kilas-translator',wait_until='networkidle')
                    history=page.locator('[data-audio-history]').last.get_attribute('href')
                    page.goto(origin+history,wait_until='networkidle');expect(page.locator('#audio-result audio')).to_be_visible()
                    expect(page.get_by_role('link',name='Download MP3')).to_be_visible()
                    expect(page.get_by_role('link',name='Translate another')).to_have_count(0)
                    page.reload(wait_until='networkidle');expect(page.locator('#voiceover-panel')).to_be_visible()
                    if width==390:
                        # Existing owned result Edit still works in a single-tab studio at zero balance.
                        voice_history=page.locator('[data-audio-history]').first.get_attribute('href')
                        f.db.execute('UPDATE kilas_audio_balances SET seconds=0 WHERE user_id=?',(case.user,))
                        page.goto(origin+voice_history,wait_until='networkidle')
                        expect(page.get_by_role('link',name='Download MP3')).to_be_visible()
                        expect(page.get_by_role('link',name='Download WAV')).to_be_visible()
                        before=len(audio_jobs)
                        page.locator('#audio-result [data-audio-edit]').click()
                        expect(page.locator('#audio-script')).to_have_value('Safe synthetic voice over.')
                        expect(page.locator('#voiceover-tab')).to_have_attribute('aria-selected','true')
                        expect(page.get_by_role('button',name='Buat Voice Over')).to_be_disabled()
                        assert len(audio_jobs)==before and f.db.query_one('SELECT seconds FROM kilas_audio_balances WHERE user_id=?',(case.user,))['seconds']==0
                        page.locator('#voice-translate-toggle').check()
                        page.route('**/voice-script/translate',lambda route:route.fulfill(content_type='application/json',body='{"text":"Synthetic script translation","source_language":"en"}'))
                        page.locator('#voice-translate-preview').click()
                        expect(page.locator('#voice-translated-script')).to_have_value('Synthetic script translation')
                        page.unroute('**/voice-script/translate')
                    check('voiceover-only')
                page.goto(origin+'/kilas-translator',wait_until='networkidle');expect(page.locator('#audio-file')).to_be_visible()
                assert not errors,errors
                context.close();case.doCleanups();print('PASS audio browser width',width,flush=True)
            browser.close()
    finally:server.shutdown()
    print('PASS Audio browser: upload, shared balance, MP3 preview/download, modes/voices, history/reload, checkout/paywalls, seven widths, no overflow/JS errors')


if __name__=='__main__':main()
