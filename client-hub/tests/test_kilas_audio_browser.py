"""Real upload/audio/download/paywall DOM across all seven launch widths; mock provider only."""
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_kilas_audio import AudioTests, f, provider, wav


def main():
    AudioTests.setUpClass()
    server=make_server('127.0.0.1',0,f.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(tempfile.gettempdir())/'kilas-audio-browser';output.mkdir(exist_ok=True)
    try:
        with patch.object(provider,'voices',return_value=[{'id':'available123','name':'QA Warm','style':'Female · Warm'},{'id':'available456','name':'QA Professional','style':'Male · Professional'}]),patch.object(provider,'speech',return_value=(AudioTests.audio,'qa-request')),patch.object(provider,'dub',return_value='qa-dubbing'),patch.object(provider,'dub_status',return_value={'status':'dubbed','source_language':'id'}),patch.object(provider,'dub_result',return_value=AudioTests.audio),sync_playwright() as p:
            browser=p.chromium.launch()
            for width in (320,360,390,430,768,1024,1440):
                case=AudioTests('test_shared_balance_actual_seconds');case.id=lambda:'audio-browser-'+str(width);case.setUp();case.credit(300)
                context=browser.new_context(viewport={'width':width,'height':900},has_touch=width<761,reduced_motion='reduce')
                cookie=case.client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
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
                page.goto(origin+'/products/start',wait_until='networkidle');page.get_by_role('link',name='Buka Kilas Translator').click();expect(page.get_by_role('heading',name='Kilas Translator',exact=True)).to_be_visible();check('translate')
                # Exercise the actual global file validator and server multipart cap together.
                raw=wav(3)+(b'\0'*(13*1024*1024) if width==1440 else b'')
                page.locator('#audio-file').set_input_files({'name':'synthetic.wav','mimeType':'audio/wav','buffer':raw})
                expect(page.locator('#audio-duration')).to_contain_text('memakai 3s',timeout=20000)
                assert page.locator('#audio-file').evaluate('el=>el.validity.valid')
                page.select_option('#translate-panel select[name=language]','en');page.locator('#translate-panel button[type=submit]').click()
                expect(page).to_have_url(__import__('re').compile(r'/kilas-translator/jobs/\d+'),timeout=20000)
                expect(page.locator('#audio-result audio')).to_be_visible(timeout=20000);expect(page.locator('.audio-balance')).not_to_contain_text('sedang dicadangkan');expect(page.locator('[data-audio-history-status]')).to_have_text('Selesai');check('result')
                audio=page.locator('#audio-result audio');expect(audio).to_have_attribute('src',__import__('re').compile('/result'))
                audio.evaluate('el=>el.play()');assert audio.evaluate('el=>!el.paused')
                audio.evaluate('el=>el.pause()')
                with page.expect_download() as downloaded:page.get_by_role('link',name='Download MP3').click()
                assert downloaded.value.suggested_filename.endswith('-English.mp3')
                page.reload(wait_until='networkidle');expect(page.locator('#audio-result audio')).to_be_visible()
                page.get_by_role('link',name='Translate another').click();page.locator('#voiceover-tab').click();expect(page.locator('#voiceover-panel')).to_be_visible()
                page.fill('#audio-script','Safe synthetic voice over.');expect(page.locator('#voice-estimate')).to_contain_text('reservasi')
                page.locator('[name=voice][value=available456]').check();check('voiceover')
                page.get_by_role('button',name='Generate Voice Over').click();expect(page.locator('#audio-result audio')).to_be_visible(timeout=20000)
                expect(page.locator('#voiceover-tab')).to_have_attribute('aria-selected','true');page.reload(wait_until='networkidle');expect(page.locator('#audio-result audio')).to_be_visible();check('voice-result')
                expect(page.locator('.audio-history li')).to_have_count(2)
                page.locator('#audio-packs').scroll_into_view_if_needed();check('pricing');expect(page.get_by_role('button',name='Beli 5 menit')).to_be_visible()
                page.get_by_role('button',name='Beli 5 menit').click();expect(page.get_by_role('heading',name='Beli Saldo Audio')).to_be_visible();check('invoice')
                zero=f.repo.create_user(f'audio-zero-{width}@example.test','hash');client=f.app.app.test_client()
                with client.session_transaction() as s:s.update(user_id=zero,role='CLIENT_OWNER',_csrf_token='zero-csrf')
                cookie=client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page.goto(origin+'/kilas-translator',wait_until='networkidle');expect(page.get_by_role('heading',name='Saldo Audio belum tersedia')).to_be_visible();expect(page.locator('#translate-panel button[type=submit]')).to_be_disabled();check('paywall')
                page.goto(origin+'/kilas-ai/video',wait_until='networkidle');expect(page.get_by_role('heading',name='Kuota Kilas Video belum tersedia')).to_be_visible();expect(page.locator('#video-submit')).to_be_disabled()
                assert not errors,errors
                context.close();case.doCleanups();print('PASS audio browser width',width,flush=True)
            browser.close()
    finally:server.shutdown()
    print('PASS Audio browser: upload, shared balance, MP3 preview/download, modes/voices, history/reload, checkout/paywalls, seven widths, no overflow/JS errors')


if __name__=='__main__':main()
