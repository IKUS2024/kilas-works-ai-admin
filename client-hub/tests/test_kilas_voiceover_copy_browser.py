"""Compact script-area copy and working controls, with synthetic text AI only."""
import json
import os
import shutil
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from test_kilas_audio import AudioTests,f,provider
from test_kilas_audio_browser import script_reply
from kilas_ai import providers


def main():
    AudioTests.setUpClass()
    server=make_server('127.0.0.1',0,f.app.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_VOICE_COPY_SCREENSHOTS','/tmp/kilas-voice-copy-review'));output.mkdir(parents=True,exist_ok=True)
    report={'paid_io':False,'widths':[]};video_only=os.environ.get('KILAS_VOICE_COPY_VIDEO_ONLY')=='1'
    try:
        with patch.object(provider,'voices',return_value=[{'id':'copyVoice123','name':'QA voice','style':'Warm'}]),patch.object(providers,'stream',side_effect=script_reply),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (320,390,1440):
                case=AudioTests('test_shared_balance_actual_seconds');case.id=lambda:'voice-copy-'+str(width);case.setUp();case.credit(300)
                context=browser.new_context(viewport={'width':width,'height':1000},has_touch=width<761)
                cookie=case.client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page=context.new_page();errors=[];jobs=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda r:jobs.append(r.url) if r.method=='POST' and '/kilas-translator/jobs' in r.url else None)
                page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                page.goto(origin+'/kilas-translator?mode=voiceover',wait_until='networkidle')
                if video_only:
                    with patch.dict(os.environ,{'KILAS_AUDIO_UPLOAD_TRANSLATION_VISIBLE':'false','KILAS_VOICE_VIDEO_SCRIPT_ENABLED':'false'}):
                        page.goto(origin+'/kilas-translator?mode=voiceover',wait_until='networkidle')
                    expect(page.locator('.audio-heading h1')).to_have_text('Voice Over');expect(page.locator('.audio-heading p')).to_have_count(0)
                    page.locator('#voice-video-script>summary').click()
                    expect(page.locator('#voice-video-script')).to_have_attribute('data-ready','false')
                    expect(page.get_by_text('Transkripsi video belum aktif.',exact=True)).to_be_visible()
                    expect(page.locator('.voice-video-limits')).to_have_text('MP4 · maks. 250 MB · 10 menit')
                    for ident in ('voice-video-file','voice-video-consent','voice-video-extract'):expect(page.locator('#'+ident)).to_be_disabled()
                    expect(page.locator('#voice-video-consent')).to_have_attribute('name','consent');expect(page.locator('#voice-video-consent')).to_have_attribute('value','yes')
                    expect(page.locator('#voice-video-privacy-terms')).to_be_hidden()
                    expect(page.locator('#audio-script')).to_be_editable();expect(page.locator('#voice-assist-copy')).to_be_visible()
                    page.locator('#voice-video-script').scroll_into_view_if_needed();page.screenshot(path=str(output/f'voice-video-compact-{width}.png'))
                    page.locator('.voice-video-privacy summary').click();expect(page.locator('#voice-video-privacy-terms')).to_be_visible()
                    expect(page.locator('#voice-video-privacy-terms')).to_contain_text('ElevenLabs memakai logging bawaan')
                    expect(page.locator('#voice-video-privacy-terms')).to_contain_text('File sementara di Kilas dihapus')
                    expect(page.locator('#voice-video-privacy-terms')).to_contain_text('tidak dipotong')
                    if width==390:page.screenshot(path=str(output/'voice-video-privacy-390.png'))
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert not jobs and not errors,(jobs,errors)
                    report['widths'].append({'width':width,'off_status_limits_privacy_consent_manual_controls':'PASS','generate_calls':0})
                    context.close();case.doCleanups();continue
                script=page.locator('#audio-script');script.scroll_into_view_if_needed()
                expect(script).to_have_attribute('placeholder','Tulis apa yang ingin diucapkan...')
                expect(page.locator('.audio-script-retention')).to_be_hidden();expect(page.locator('#voice-language-status')).to_be_hidden()
                expect(page.locator('#voice-assist-status')).to_have_text('')
                gap=page.locator('#voice-script-assist').evaluate('e=>e.getBoundingClientRect().top-document.querySelector("#audio-script").getBoundingClientRect().bottom')
                assert 6<=gap<=10,(width,gap)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(output/f'voice-script-{width}.png'))
                page.locator('.voice-script-info summary').click();expect(page.locator('.audio-script-retention')).to_be_visible()
                expect(page.locator('#voice-language-status')).to_be_visible();page.locator('.voice-script-info summary').click()
                page.locator('#voice-script-assist > summary').click();expect(page.locator('.voice-assist-usage')).to_be_visible()
                expect(page.locator('#voice-assist-generate')).to_be_visible();script.fill('Naskah sebelum bantuan.')
                page.locator('#voice-assist-generate').click();expect(page.locator('#voice-assist-status')).to_contain_text('masuk ke kolom',timeout=20000)
                assert script.input_value().startswith('Produk ini cocok')
                page.evaluate('navigator.clipboard.writeText=async text=>window.qaCopy=text')
                page.locator('#voice-assist-copy').click();expect(page.locator('#voice-assist-status')).to_have_text('Naskah disalin.')
                assert page.evaluate('qaCopy')==script.input_value()
                page.locator('#voice-assist-undo').click();expect(script).to_have_value('Naskah sebelum bantuan.')
                page.locator('#voice-translate-toggle').check();expect(page.locator('#voice-translation-options')).to_be_visible()
                page.route('**/voice-script/translate',lambda r:r.fulfill(status=503,content_type='application/json',body='{"error":"Terjemahan sintetis belum tersedia."}'))
                page.locator('#voice-translate-preview').click();expect(page.locator('#voice-translation-error')).to_have_text('Terjemahan sintetis belum tersedia.')
                expect(script).to_have_value('Naskah sebelum bantuan.');expect(page.locator('#voice-estimate')).to_be_visible()
                assert not jobs and not errors,(jobs,errors)
                report['widths'].append({'width':width,'layout_controls_copy_ai_undo_translation_error':'PASS','generate_calls':0});context.close();case.doCleanups()
            browser.close()
        (output/('video-copy-verification.json' if video_only else 'verification.json')).write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:server.shutdown()


if __name__=='__main__':main()
