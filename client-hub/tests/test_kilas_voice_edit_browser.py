"""Actual Chromium edit/regenerate flow with synthetic translation and TTS only."""
import json
import tempfile
import shutil
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from test_kilas_voice_edit import VoiceEditTests
from test_kilas_audio import f,provider
from kilas_ai import audio_branded_voices as branded


def main():
    VoiceEditTests.setUpClass()
    server=make_server('127.0.0.1',0,f.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    out=Path(tempfile.gettempdir())/'kilas-voice-spoken-edit-review';out.mkdir(exist_ok=True)
    report=[]
    try:
        choices=[{'alias':'kilas-male','id':'otherVoice123','name':'Kilas Male','style':'Natural'},{'alias':'kilas-female','id':'actualVoice123','name':'Kilas Female','style':'Natural'}]
        with patch.object(branded,'choices',return_value=choices),patch.object(provider,'speech',return_value=(VoiceEditTests.audio,'synthetic-only')) as speech,sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (390,1440):
                case=VoiceEditTests('test_plain_auto_personal_missing_voice_and_legacy');case.id=lambda:'spoken-edit-browser-'+str(width);case.setUp()
                original='Selamat datang. Ini naskah Indonesia.';language='en' if width==390 else 'es';spoken='Welcome. This is the English script.' if language=='en' else 'Bienvenidos. Este es el texto en español.'
                ident=case.source(script=original,translate_script='yes',translated_script=spoken,language=language,translation_source='id')
                context=browser.new_context(viewport={'width':width,'height':1000})
                context.add_init_script("Object.defineProperty(crypto,'randomUUID',{value:undefined})")
                cookie=case.client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}])
                page=context.new_page();errors=[];posts=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('request',lambda request:posts.append(request.post_data) if request.method=='POST' and request.url==origin+'/kilas-translator/jobs' else None)
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                page.goto(origin+f'/kilas-translator/jobs/{ident}',wait_until='networkidle')
                edit=page.locator('#audio-result [data-audio-edit]');script=page.locator('#audio-script')
                page.on('dialog',lambda dialog:dialog.accept())
                page.locator('#voice-translate-toggle').check();page.locator('#voice-translation-target').select_option('fr');script.fill('A draft before editing.')
                # A pending translation must never replace the loaded spoken script.
                page.evaluate("window.qaFetch=fetch;window.fetch=(url,options)=>String(url).endsWith('/voice-script/translate')?new Promise(resolve=>window.qaTranslationResolve=resolve):qaFetch(url,options)")
                page.locator('#voice-translate-preview').click();page.wait_for_function('!!window.qaTranslationResolve')
                old_key=page.locator('#voiceover-panel [name=operation_key]').input_value()
                edit.click();expect(script).to_have_value(spoken)
                expect(page.locator('#voice-translate-toggle')).not_to_be_checked();expect(page.locator('#voice-translated-script')).to_have_value('')
                expect(page.locator('#voice-translated-result')).to_be_hidden();expect(page.locator('#voice-language')).to_have_value(language)
                expect(page.locator('#voice-translation-source')).to_have_value(language);expect(page.locator('#voice-translation-target')).to_have_value(language)
                expect(page.locator('#kilas-voice-choice')).to_have_value('kilas-female');expect(page.locator('#selected-voice')).to_have_value('kilas-female')
                assert page.locator('#voiceover-panel [name=operation_key]').input_value()!=old_key
                page.evaluate("qaTranslationResolve(new Response(JSON.stringify({text:'STALE TRANSLATION',source_language:'id'}),{headers:{'Content-Type':'application/json'}}));window.fetch=qaFetch")
                expect(page.locator('#voice-translate-preview')).to_be_enabled();expect(script).to_have_value(spoken);expect(page.locator('#voice-translated-script')).to_have_value('')
                script.fill(spoken+' Edited.');expect(page.locator('#voice-language')).to_have_value(language)
                before=speech.call_count
                page.locator('#voice-generate').evaluate('button=>{button.click();button.click()}')
                page.wait_for_url(lambda url:'/jobs/' in url and str(url).split('?')[0]!=origin+f'/kilas-translator/jobs/{ident}')
                expect(page.locator('#audio-result audio')).to_be_visible();assert speech.call_count==before+1
                assert speech.call_args.args==(spoken+' Edited.','actualVoice123',language);assert len(posts)==1
                assert 'name="translate_script"' not in posts[0]
                row=f.db.query_one('SELECT original_script,spoken_script FROM kilas_audio_jobs WHERE id=?',(ident,));assert row['original_script']==original and row['spoken_script']==spoken
                page.reload(wait_until='networkidle')
                if not page.locator('#audio-history').is_visible():page.locator('.reference-history-toggle').click()
                page.locator(f'#audio-history [data-audio-edit="/kilas-translator/jobs/{ident}/script"]').click();expect(script).to_have_value(spoken)
                # Alternate takes retain the same spoken snapshot and language.
                alternate=case.client.post(f'/kilas-translator/jobs/{ident}/alternate',data={'csrf_token':'audio-csrf','operation_key':'browser-alternate-123456'}).json['id']
                page.goto(origin+f'/kilas-translator/jobs/{alternate}',wait_until='networkidle')
                page.locator('#audio-result [data-audio-edit]').click();expect(script).to_have_value(spoken)
                expect(page.locator('#voice-language')).to_have_value(language)
                # Changes made while the edit request is pending are never overwritten.
                for selector,value in (('#audio-script','New draft during request.'),('#voice-translation-target','fr'),('#kilas-voice-choice','kilas-male')):
                    page.evaluate("window.qaFetch=fetch;window.fetch=(url,options)=>String(url).endsWith('/script')?qaFetch(url,options).then(response=>new Promise(resolve=>window.qaEditResolve=()=>resolve(response))):qaFetch(url,options)")
                    page.locator('#audio-result [data-audio-edit]').click();page.wait_for_function('!!window.qaEditResolve')
                    if selector=='#audio-script':script.fill(value)
                    else:page.locator(selector).select_option(value,force=True)
                    page.evaluate('qaEditResolve();delete window.qaEditResolve;window.fetch=qaFetch')
                    expect(page.locator('#audio-error')).to_contain_text('Draf telah berubah')
                    expect(page.locator('#audio-result [data-audio-edit]')).to_be_enabled()
                    if selector=='#audio-script':expect(script).to_have_value(value)
                    else:expect(page.locator(selector)).to_have_value(value)
                # Legacy translated originals cannot be mistaken for spoken text.
                f.db.execute('UPDATE kilas_audio_jobs SET spoken_script=NULL WHERE id=?',(ident,))
                page.goto(origin+f'/kilas-translator/jobs/{ident}',wait_until='networkidle')
                expect(page.locator('#audio-result [data-audio-edit]')).to_have_count(0)
                expect(page.locator('#audio-result')).to_contain_text('Naskah yang diucapkan tidak tersimpan')
                # A removed voice clears the selection, requiring an explicit replacement.
                f.db.execute('UPDATE kilas_audio_jobs SET spoken_script=?,voice_id=? WHERE id=?',(spoken,'deletedVoice123',ident))
                page.reload(wait_until='networkidle');page.locator('#audio-result [data-audio-edit]').click()
                expect(script).to_have_value(spoken);expect(page.locator('#selected-voice')).to_have_value('');expect(page.locator('#voice-generate')).to_be_disabled()
                expect(page.locator('#audio-progress')).to_contain_text('pilih suara')
                page.screenshot(path=str(out/f'spoken-edit-{width}.png'))
                assert not errors,errors
                report.append({'width':width,'translated_edit_regenerate_exact_target':language,'history_reload':True,'alternate_exact_edit':True,'stale_translation_discarded':True,'draft_and_config_races_preserved':True,'legacy_no_exact_edit':True,'removed_voice_requires_choice':True,'double_click_single_generation':True,'paid_io':False})
                context.close();case.doCleanups()
            for personal in (False,True):
                case=VoiceEditTests('test_plain_auto_personal_missing_voice_and_legacy');case.id=lambda:'plain-personal-edit-'+str(personal);case.setUp()
                ident=case.source(script='  A plain spoken script.  ',language='auto')
                if personal:
                    f.db.execute('INSERT INTO kilas_audio_personal_voices(user_id,voice_id) VALUES (?,?)',(case.user,'actualVoice123'))
                    f.db.execute("INSERT INTO kilas_audio_saved_voices(user_id,name,voice_id,operation_key,consent_at,updated_at) VALUES (?,?,'actualVoice123','saved-browser-edit','2026-10-20','2026-10-20')",(case.user,'Saved test voice'))
                    f.db.execute('UPDATE kilas_audio_jobs SET voice_is_personal=1 WHERE id=?',(ident,))
                context=browser.new_context(viewport={'width':390,'height':1000})
                cookie=case.client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}])
                page=context.new_page();page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                page.goto(origin+f'/kilas-translator/jobs/{ident}',wait_until='networkidle')
                page.locator('#audio-result [data-audio-edit]').click();expect(page.locator('#audio-script')).to_have_value('A plain spoken script.')
                expect(page.locator('#voice-language')).to_have_value('auto');expect(page.locator('#voice-translate-toggle')).not_to_be_checked()
                expected_voice='personal' if personal else 'kilas'
                expect(page.locator('[name=voice_kind][value='+expected_voice+']')).to_be_checked()
                if personal:assert page.locator('#selected-voice').input_value().startswith('personal:')
                page.locator('#audio-script').fill('A plain spoken script. Updated.')
                before=speech.call_count;page.locator('#voice-generate').click()
                page.wait_for_url(lambda url:str(url).split('?')[0]!=origin+f'/kilas-translator/jobs/{ident}')
                assert speech.call_count==before+1 and speech.call_args.args==('A plain spoken script. Updated.','actualVoice123','auto')
                assert bool(speech.call_args.kwargs.get('personal'))==personal
                report.append({'plain_script':True,'saved_personal_voice':personal,'edit_regenerate_auto_language':True,'paid_io':False})
                context.close();case.doCleanups()
            browser.close()
        (out/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:server.shutdown()


if __name__=='__main__':main()
