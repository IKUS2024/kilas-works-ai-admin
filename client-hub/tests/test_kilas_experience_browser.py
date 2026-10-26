"""Real Flask/Chromium responsive tasks. Synthetic accounts/providers; zero paid IO."""
import json,os,threading,logging
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_experience as fixture
from kilas_ai import providers,audio_provider,audio_branded_voices as branded,chat_models,image_models


def main():
    case=fixture.ExperienceTests('test_exact_script_handoff_no_generation_no_open_redirect_and_csrf');case.setUp()
    app=fixture.home.fixture.base.f.fixture.app.app
    own=case.attachment(case.owner);case.attachment(case.owner,'Long filename '+('VeryLongName'*18)+'.jpg');case.attachment(case.other,'Foreign secret.jpg')
    case.audio(case.owner,'Saved Voice Over result')
    # Valid synthetic audio for the player; no provider generation.
    import test_kilas_audio as audio
    fixture.db.execute('UPDATE kilas_audio_jobs SET result_content=? WHERE user_id=?',(audio.mp3(1),case.owner))
    server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_EXPERIENCE_SCREENSHOTS','../../experience-qa')).resolve();output.mkdir(parents=True,exist_ok=True)
    report={'paid_calls':0,'viewports':[],'scope':'local Flask + Chromium with owner-scoped synthetic records'}
    script='\n  Ini naskah promosi. Tetap persis & editable.\n\nAkhir naskah.  '
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    try:
        with patch.object(chat_models,'check',side_effect=lambda m:{**chat_models.spec(m),'available':True,'images':True,'status':'verified'}),patch.object(image_models,'check',side_effect=lambda m:{**image_models.spec(m),'available':True,'status':'verified'}),patch.object(providers,'stream',side_effect=lambda *a,**k:fixture.home.fixture.answer(script)),patch.object(audio_provider,'request',side_effect=AssertionError('No audio provider')),patch.object(branded,'public_choices',return_value=[{'alias':'kilas-male','name':'Kilas Male','style':'Natural'},{'alias':'kilas-female','name':'Kilas Female','style':'Natural'}]),sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            for width,height in ((1440,1000),(820,1000),(390,844),(320,700)):
                cookie=case.client().get_cookie('session');context=browser.new_context(viewport={'width':width,'height':height},has_touch=width<761)
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}])
                page=context.new_page();errors=[];writes=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda r:writes.append(r.url) if r.method=='POST' else None)
                page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                page.goto(origin+'/products/start',wait_until='networkidle')
                expect(page.locator('.home-starters,[data-home-starter]')).to_have_count(0)
                expect(page.locator('.kilas-new-chat-logo')).to_be_visible()
                page.screenshot(path=str(output/f'home-{width}.png'),full_page=True)
                page.locator('#ai-input').fill('Tulis naskah promosi sintetis.');page.locator('#ai-send').click()
                expect(page.locator('.chat-voice-draft')).to_be_visible();thread_url=page.url
                page.locator('.chat-voice-draft').click();page.wait_for_load_state('networkidle')
                expect(page.locator('#audio-script')).to_have_value(script)
                expect(page.locator('#voice-script-duration,.voice-duration-note')).to_have_count(0)
                assert not any('/jobs' in url for url in writes)
                expect(page.locator('.audio-draft-return a')).to_have_attribute('href',urlsplit(thread_url).path)
                page.screenshot(path=str(output/f'voice-draft-{width}.png'),full_page=True)
                page.locator('#audio-script').fill('Naskah edit yang tetap aman.');page.locator('#kilas-voice-choice').select_option('kilas-female')
                expect(page.locator('#selected-voice')).to_have_value('kilas-female')
                page.locator('.audio-draft-return a').click();page.wait_for_load_state('networkidle');expect(page.locator('.chat-voice-draft')).to_be_visible()
                page.go_back(wait_until='networkidle');page.go_forward(wait_until='networkidle');expect(page.locator('.chat-voice-draft')).to_be_visible()
                # Selected visible prose transfers as selected, without auto-generating.
                page.locator('.ai-assistant .ai-message-text p').first.evaluate('(e)=>{const r=document.createRange();r.selectNodeContents(e);const s=getSelection();s.removeAllRanges();s.addRange(r);}')
                selected=page.evaluate('getSelection().toString()');page.locator('.chat-voice-draft').click();page.wait_for_load_state('networkidle');expect(page.locator('#audio-script')).to_have_value(selected)
                page.goto(origin+'/kilas-ai/library',wait_until='networkidle')
                expect(page.locator('.library-asset')).to_have_count(3);assert 'Foreign secret' not in page.locator('.kilas-library').inner_text()
                assert page.locator('.library-preview img').first.is_hidden() # Missing/broken preview fallback.
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                page.screenshot(path=str(output/f'library-{width}.png'),full_page=True)
                page.locator('#library-type').select_option('audio');page.locator('.library-tools button').click();page.wait_for_load_state('networkidle');expect(page.locator('.library-asset')).to_have_count(1)
                page.go_back(wait_until='networkidle');expect(page.locator('.library-asset')).to_have_count(3)
                page.goto(origin+'/kilas-translator?mode=voiceover',wait_until='networkidle')
                expect(page.locator('.audio-latest-result,#audio-result audio')).to_have_count(0)
                page.screenshot(path=str(output/f'voice-fresh-{width}.png'),full_page=True)
                if not page.locator('#audio-history').is_visible():page.locator('.reference-history-toggle').click()
                page.locator('[data-audio-history]').first.click()
                expect(page.locator('#audio-result audio')).to_be_visible()
                expect(page.locator('#audio-result a').filter(has_text='MP3')).to_have_count(1)
                page.goto(origin+'/kilas-ai/usage',wait_until='networkidle');expect(page.locator('.credits-pay-button')).to_be_disabled();expect(page.locator('.credits-preview-note')).to_be_visible()
                page.screenshot(path=str(output/f'credits-{width}.png'),full_page=True)
                page.goto(origin+'/creative-services/#cs-event',wait_until='networkidle');page.locator('[data-service-id]').first.click();page.wait_for_url('**/#contact')
                page.locator('#cs-brief-date').fill('2026-11-20');page.locator('#cs-brief-location').fill('Jakarta');page.locator('#cs-brief-needs').fill('Dokumentasi acara komunitas.');page.locator('.cs-brief-prepare').click()
                msg=page.locator('#cs-brief-message').input_value();assert all(value in msg for value in ('Basic','2026-11-20','Jakarta','Dokumentasi acara komunitas.'))
                edited=msg+'\nTambahan saya sendiri.';page.locator('#cs-brief-message').fill(edited)
                href=page.locator('#cs-contact-whatsapp').get_attribute('href');assert parse_qs(urlsplit(href).query)['text']==[edited]
                assert not any('wa.me' in url for url in writes)
                page.screenshot(path=str(output/f'creative-brief-{width}.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                assert not errors,(width,errors)
                report['viewports'].append({'width':width,'home_draft_voice_handoff_exact_back_forward_library_filter_preview_credits_creative':'PASS'})
                context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
