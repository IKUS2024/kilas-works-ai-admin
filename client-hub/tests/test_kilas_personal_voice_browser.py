"""Real browser microphone/MediaRecorder, consent and audio UX; provider calls mocked."""
import os
import hashlib
import json
import tempfile
import threading
import re
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from test_kilas_personal_voice import PersonalVoiceTests,personal,branded
from test_kilas_audio import f,provider
from kilas_ai import audio_voice_script


def main():
    PersonalVoiceTests.setUpClass()
    server=make_server('127.0.0.1',0,f.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(tempfile.gettempdir())/'kilas-personal-voice-browser';output.mkdir(exist_ok=True)
    try:
        with patch.object(provider,'voices',return_value=[{'id':'stockPrivate123','name':'Kilas Natural','style':'Natural'}]),patch.object(provider,'clone_voice',return_value='personalPrivate123') as clone,patch.object(provider,'delete_voice'),patch.object(provider,'speech',return_value=(PersonalVoiceTests.audio,'qa-request')) as speech,sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM'),args=['--no-sandbox','--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream'])
            for width in map(int,os.environ.get('KILAS_QA_WIDTHS','320,360,390,430,768,1024,1440').split(',')):
                case=PersonalVoiceTests('test_create_persist_retry_no_public_identifier');case.id=lambda:'personal-browser-'+str(width);case.setUp();case.credit(300)
                c=browser.new_context(viewport={'width':width,'height':950},has_touch=width<761,permissions=['microphone'],reduced_motion='reduce')
                cookie=case.client.get_cookie('session');c.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}]);page=c.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(origin+'/kilas-translator',wait_until='networkidle');page.locator('#voiceover-tab').click();page.locator('[name=voice_kind][value=personal]').check()
                expect(page.locator('#saved-voice-choice')).to_have_value('');expect(page.locator('#voice-generate')).to_be_disabled()
                page.locator('#add-saved-voice').click();page.locator('#record-voice-name').fill('Suara Saya');page.locator('#record-start').click();expect(page.locator('#record-state')).to_contain_text('Mikrofon aktif')
                expect(page.locator('#record-timer')).not_to_have_text('0:00');page.locator('#record-stop').click()
                expect(page.locator('#record-playback')).to_be_visible();page.locator('#record-playback').evaluate('el=>el.play()');assert not page.locator('#record-playback').evaluate('el=>el.paused');page.locator('#record-playback').evaluate('el=>el.pause()')
                expect(page.locator('#save-personal-voice')).to_be_disabled();page.locator('#voice-consent').check();expect(page.locator('#save-personal-voice')).to_be_enabled()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.screenshot(path=str(output/f'recording-{width}.png'),full_page=True)
                with page.expect_response('**/personal-voice') as response:page.locator('#save-personal-voice').click()
                assert response.value.ok,response.value.text()
                expect(page.locator('#personal-voice-state')).to_have_text('Siap digunakan');assert personal.get(case.user)=='personalPrivate123'
                page.reload(wait_until='networkidle');page.locator('#voiceover-tab').click();page.locator('[name=voice_kind][value=personal]').check();expect(page.locator('#personal-voice-state')).to_have_text('Siap digunakan');assert 'personalPrivate123' not in page.content() and 'stockPrivate123' not in page.content()
                expect(page.locator('#open-recorder,#voice-preview-missing')).to_have_count(0)
                expect(page.locator('#personal-preview')).to_be_hidden();expect(page.locator('#play-personal-preview')).to_be_enabled()
                before_play=(clone.call_count,speech.call_count)
                original=personal.saved_preview(case.user,int(page.locator('#saved-voice-choice').input_value()))
                with page.expect_response('**/personal-voices/*/preview') as preview:page.locator('#play-personal-preview').click()
                assert preview.value.ok and preview.value.body()==original
                expect(page.locator('#personal-preview')).to_be_visible();assert not page.locator('#personal-preview').evaluate('el=>el.paused')
                page.wait_for_function('document.querySelector("#personal-preview").currentTime>0')
                assert before_play==(clone.call_count,speech.call_count)
                page.locator('[name=voice_kind][value=kilas]').check();expect(page.locator('#personal-preview')).to_be_hidden();assert page.locator('#personal-preview').evaluate('el=>el.paused')
                page.locator('[name=voice_kind][value=personal]').check()
                for ident in ('add-saved-voice','rename-saved-voice','delete-saved-voice','saved-voice-choice'):
                    expect(page.locator('#'+ident)).to_be_visible()
                before_cancel=clone.call_count
                page.locator('#add-saved-voice').click();page.locator('#record-cancel').click()
                expect(page.locator('#add-saved-voice')).to_be_focused();expect(page.locator('#voice-generate')).to_be_enabled()
                assert clone.call_count==before_cancel
                page.locator('#audio-script').fill('Halo, saya di Bali.');page.locator('#voice-translate-toggle').check();expect(page.locator('#voice-generate')).to_be_disabled()
                before=speech.call_count
                with patch.object(audio_voice_script,'translate',return_value={'text':'Hello, I am in Bali.','source_language':'id'}):
                    page.locator('#voice-translate-preview').click();expect(page.locator('#voice-translated-script')).to_have_value('Hello, I am in Bali.')
                assert speech.call_count==before;expect(page.locator('#audio-script')).to_have_value('Halo, saya di Bali.')
                page.locator('#voice-translated-script').fill('Hello, today I am enjoying Bali.')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.screenshot(path=str(output/f'translation-{width}.png'),full_page=True)
                page.locator('#voice-generate').click();expect(page).to_have_url(re.compile(r'/kilas-translator/jobs/\d+'),timeout=20000)
                assert speech.call_args.args[0]=='Hello, today I am enjoying Bali.' and speech.call_args.args[1]=='personalPrivate123' and speech.call_args.kwargs['personal']
                page.goto(origin+'/kilas-translator',wait_until='networkidle');page.locator('#voiceover-tab').click();page.locator('[name=voice_kind][value=personal]').check()
                for text,language in [('Selamat datang di Kilas Works.','Indonesian'),('Welcome to Kilas Works. Today we are building something new.','English')]:
                    page.locator('#audio-script').fill(text);expect(page.locator('#voice-language-status')).to_contain_text(language)
                    page.locator('#voice-generate').click();expect(page).to_have_url(re.compile(r'/kilas-translator/jobs/\d+'),timeout=20000)
                    expect(page.locator('#audio-result audio')).to_be_visible();assert speech.call_args.args[0]==text and speech.call_args.args[1]=='personalPrivate123'
                    page.locator('#audio-result audio').evaluate('el=>el.play()');assert not page.locator('#audio-result audio').evaluate('el=>el.paused');page.locator('#audio-result audio').evaluate('el=>el.pause()')
                    with page.expect_download() as downloaded:page.get_by_role('link',name='Download MP3').click()
                    assert downloaded.value.suggested_filename.endswith('.mp3')
                    page.goto(origin+'/kilas-translator',wait_until='networkidle');page.locator('#voiceover-tab').click();page.locator('[name=voice_kind][value=personal]').check()
                if width==390:
                    page.locator('#add-saved-voice').click();page.locator('#record-start').click();expect(page.locator('#record-timer')).not_to_have_text('0:00');page.locator('#record-stop').click();expect(page.locator('#record-playback')).to_be_visible();page.locator('#voice-consent').check()
                    with patch.object(provider,'clone_voice',side_effect=provider.ProviderError()):
                        page.locator('#save-personal-voice').click();expect(page.locator('#record-error')).to_contain_text('belum berhasil');assert personal.get(case.user)=='personalPrivate123'
                    page.locator('#record-cancel').click();expect(page.locator('#voice-recorder')).to_be_hidden()
                    page.locator('#add-saved-voice').click();page.locator('#record-voice-name').fill('Suara Presentasi');page.locator('#record-start').click();expect(page.locator('#record-timer')).not_to_have_text('0:00');page.locator('#record-stop').click();expect(page.locator('#record-playback')).to_be_visible();page.locator('#voice-consent').check()
                    with patch.object(provider,'clone_voice',return_value='secondPersonalPrivate456'):
                        page.locator('#save-personal-voice').click();expect(page.locator('#voice-recorder')).to_be_hidden()
                    assert page.locator('#saved-voice-choice option').count()==2
                    second=page.locator('#saved-voice-choice').input_value()
                    page.locator('#rename-saved-voice').click();page.locator('#saved-voice-new-name').fill('Narasi Presentasi Indonesia');page.locator('#save-voice-name').click();expect(page.locator('#saved-voice-rename')).to_be_hidden()
                    expect(page.locator('#saved-voice-choice option:checked')).to_have_text('Narasi Presentasi Indonesia')
                    page.screenshot(path=str(output/'library-390.png'),full_page=True)
                    page.reload(wait_until='networkidle');page.locator('#voiceover-tab').click();page.locator('[name=voice_kind][value=personal]').check();page.select_option('#saved-voice-choice',second)
                    expect(page.locator('#selected-voice')).to_have_value('personal:'+second)
                    page.locator('#play-personal-preview').click();expect(page.locator('#personal-preview')).to_be_visible()
                    first=page.locator('#saved-voice-choice option').first.get_attribute('value');page.select_option('#saved-voice-choice',first)
                    expect(page.locator('#personal-preview')).to_be_hidden();assert not page.locator('#personal-preview').get_attribute('src')
                    page.select_option('#saved-voice-choice',second)
                    with patch.object(provider,'request',return_value={}):
                        page.once('dialog',lambda d:d.accept());page.locator('#delete-saved-voice').click();expect(page.locator('#saved-voice-choice option')).to_have_count(1)
                    assert personal.get(case.user)=='personalPrivate123'
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');assert not errors,errors
                page.screenshot(path=str(output/f'voiceover-{width}.png'),full_page=True)
                print('PASS personal voice microphone/playback/consent/persistence/ID+EN/generation/download/overflow '+str(width),flush=True)
                c.close();case.doCleanups()
            # A published English fixture is served only through the validated
            # alias route; no private original or provider generation is used.
            case=PersonalVoiceTests('test_create_persist_retry_no_public_identifier');case.id=lambda:'branded-sample-browser';case.setUp()
            voice={'alias':'kilas-male','id':'syntheticBranded123','name':'Kilas Male','style':'Natural'}
            with tempfile.TemporaryDirectory() as folder,patch.object(branded,'SAMPLE_ROOT',Path(folder)),patch.object(branded,'choices',return_value=[voice]):
                root=Path(folder);(root/'kilas-male.mp3').write_bytes(PersonalVoiceTests.audio)
                (root/'manifest.json').write_text(json.dumps({'kilas-male':{'text':branded.SAMPLE_TEXT,'voice_sha256':hashlib.sha256(voice['id'].encode()).hexdigest(),'audio_sha256':hashlib.sha256(PersonalVoiceTests.audio).hexdigest()}}))
                c=browser.new_context(viewport={'width':390,'height':950});cookie=case.client.get_cookie('session');c.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}]);page=c.new_page()
                page.goto(origin+'/kilas-translator?mode=voiceover',wait_until='networkidle');before=(clone.call_count,speech.call_count)
                with page.expect_response('**/voices/kilas-male/sample') as result:page.locator('#play-kilas-preview').click()
                assert result.value.ok and result.value.body()==PersonalVoiceTests.audio
                page.wait_for_function('document.querySelector("#kilas-preview").currentTime>0')
                page.locator('[name=voice_kind][value=personal]').check();expect(page.locator('#kilas-preview')).to_be_hidden();assert page.locator('#kilas-preview').evaluate('el=>el.paused')
                assert before==(clone.call_count,speech.call_count);c.close();case.doCleanups();print('PASS branded English cached fixture playback / voice binding / no provider calls',flush=True)
            browser.close()
    finally:server.shutdown()


if __name__=='__main__':main()
