"""Fresh Voice Over entry and explicit results in Chromium; synthetic provider only."""
import json
import shutil
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_kilas_audio_latest_result import FreshEntryTests
from test_kilas_audio import f, provider
from kilas_ai import audio_branded_voices as branded


def main():
    FreshEntryTests.setUpClass()
    server=make_server('127.0.0.1',0,f.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    out=Path('/tmp/kilas-fresh-entry-review');out.mkdir(exist_ok=True)
    report=[]
    try:
        choices=[{'alias':'kilas-female','id':'actualVoice123','name':'Kilas Female','style':'Natural'}]
        with sync_playwright() as pw,patch.object(branded,'choices',return_value=choices),patch.object(provider,'speech',side_effect=AssertionError('Navigation must never generate')):
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (390,1440):
                case=FreshEntryTests('test_default_direct_entry_is_fresh_without_mutating_history');case.id=lambda:'fresh-browser-'+str(width);case.setUp()
                spoken='Bienvenidos. Esta es la última traducción.'
                ident=case.source(script='Selamat datang.',translate_script='yes',translated_script=spoken,language='es',translation_source='id')
                context=browser.new_context(viewport={'width':width,'height':1000})
                cookie=case.client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
                page=context.new_page();errors=[];posts=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('dialog',lambda dialog:dialog.accept())
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                def fresh():
                    expect(page.locator('.audio-latest-result,#audio-result audio,#audio-result [data-audio-alternate]')).to_have_count(0)
                    expect(page.locator('#audio-result')).to_have_attribute('data-job-status','')
                    expect(page.locator('#voiceover-panel')).to_be_visible()
                for draft in ('','  Keep my transferred script. 日本語 & punctuation.  '):
                    page.goto(origin+'/products/start',wait_until='networkidle')
                    page.locator('#ai-input,#agent-message').fill(draft)
                    page.locator('[data-home-task=voiceover]').click();page.wait_for_url('**/kilas-translator?mode=voiceover')
                    fresh();expect(page.locator('#audio-script')).to_have_value(draft)
                    page.locator('#translate-tab').click();page.locator('#voiceover-tab').click()
                    fresh();expect(page.locator('#audio-script')).to_have_value(draft)
                for path in ('/kilas-translator?mode=voiceover','/kilas-translator'):
                    with patch.dict('os.environ',{'KILAS_AUDIO_UPLOAD_TRANSLATION_VISIBLE':'false'}):
                        page.goto(origin+path,wait_until='networkidle');fresh()
                        page.reload(wait_until='networkidle');fresh()
                page.screenshot(path=str(out/f'fresh-{width}.png'),full_page=True)
                # Recent explicitly opens the owned historical result and its actual actions.
                page.locator(f'[data-audio-history="{ident}"]').click()
                result=page.locator('#audio-result');alternate=result.locator('[data-audio-alternate]')
                expect(result.locator('audio')).to_be_visible();expect(alternate).to_have_text('Generate another version')
                expect(alternate).to_have_attribute('data-audio-alternate',f'/kilas-translator/jobs/{ident}/alternate')
                result.locator('[data-audio-edit]').click()
                expect(page.locator('#audio-script')).to_have_value(spoken)
                expect(page.locator('#voice-language')).to_have_value('es')
                expect(page.locator('#selected-voice')).to_have_value('kilas-female')
                expect(page.locator('#voice-translate-toggle')).not_to_be_checked()
                page.locator('#audio-script').fill('Unsaved draft must not change alternate context.')
                def capture(route):
                    posts.append(route.request.post_data)
                    route.fulfill(status=200,content_type='application/json',body=json.dumps({'url':f'/kilas-translator/jobs/{ident}'}))
                page.route('**/jobs/*/alternate',capture)
                with page.expect_navigation(wait_until='networkidle'):alternate.click()
                page.wait_for_url(origin+f'/kilas-translator/jobs/{ident}')
                assert len(posts)==1 and 'Unsaved draft' not in posts[0]
                page.reload(wait_until='networkidle');expect(alternate).to_be_visible()
                # A newly generated synthetic result follows the existing explicit redirect.
                result.locator('[data-audio-edit]').click()
                expect(page.locator('#audio-script')).to_have_value(spoken)
                expect(page.locator('#selected-voice')).to_have_value('kilas-female')
                expect(result.locator('[data-audio-edit]')).to_be_enabled()
                page.locator('#audio-script').fill(spoken+' Updated.')
                expect(page.locator('#voice-generate')).to_be_enabled()
                with patch.object(provider,'speech',return_value=(case.audio,'synthetic-only')) as speech:
                    page.locator('#voice-generate').click()
                    page.wait_for_url(lambda url:'/jobs/' in url and str(url).split('?')[0]!=origin+f'/kilas-translator/jobs/{ident}')
                    expect(result.locator('audio')).to_be_visible();expect(alternate).to_be_visible()
                    speech.assert_called_once_with(spoken+' Updated.','actualVoice123','es')
                new=int(page.url.split('/jobs/')[1].split('?')[0])
                expect(alternate).to_have_attribute('data-audio-alternate',f'/kilas-translator/jobs/{new}/alternate')
                page.reload(wait_until='networkidle');expect(result.locator('audio')).to_be_visible()
                # Active job deep links survive refresh and acquire actions after completion polling.
                f.db.execute("UPDATE kilas_audio_jobs SET status='PROCESSING' WHERE id=?",(new,))
                page.reload(wait_until='networkidle');expect(result).to_have_attribute('data-job-status','PROCESSING')
                expect(alternate).to_have_count(0)
                assert f.db.query_one('SELECT status FROM kilas_audio_jobs WHERE id=?',(new,))['status']=='PROCESSING'
                f.db.execute("UPDATE kilas_audio_jobs SET status='COMPLETED' WHERE id=?",(new,))
                page.evaluate("window.dispatchEvent(new Event('focus'))")
                expect(result.locator('audio')).to_be_visible();expect(alternate).to_be_visible()
                f.db.execute("UPDATE kilas_audio_jobs SET status='FAILED' WHERE id=?",(new,))
                page.reload(wait_until='networkidle');expect(alternate).to_have_count(0)
                page.goto(origin+'/kilas-translator?mode=voiceover',wait_until='networkidle');fresh()
                assert f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs WHERE user_id=?',(case.user,))['n']==2
                assert not errors,errors
                report.append({'width':width,'fresh_direct_default_home_tabs_refresh':True,'draft_preserved':True,'explicit_recent_result_and_alternate':True,'final_language_voice_edit':True,'new_result_redirect':True,'active_job_refresh_completion_poll':True,'history_preserved':True,'paid_calls':0})
                context.close();case.doCleanups()
            browser.close()
        (out/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:server.shutdown()


if __name__=='__main__':main()
