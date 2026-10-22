"""Restored/latest and Recent actions in Chromium; all provider IO synthetic."""
import json
import shutil
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_kilas_audio_latest_result import LatestResultTests
from test_kilas_audio import f, provider
from kilas_ai import audio_branded_voices as branded


def main():
    LatestResultTests.setUpClass()
    server=make_server('127.0.0.1',0,f.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    out=Path('/tmp/kilas-latest-result-review');out.mkdir(exist_ok=True)
    report=[]
    try:
        choices=[{'alias':'kilas-female','id':'actualVoice123','name':'Kilas Female','style':'Natural'}]
        with sync_playwright() as pw,patch.object(branded,'choices',return_value=choices),patch.object(provider,'speech',side_effect=AssertionError('Navigation must never generate')):
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (390,1440):
                case=LatestResultTests('test_latest_and_recent_actions_use_same_successful_job_snapshot');case.id=lambda:'latest-browser-'+str(width);case.setUp()
                spoken='Bienvenidos. Esta es la última traducción.'
                ident=case.source(script='Selamat datang.',translate_script='yes',translated_script=spoken,language='es',translation_source='id')
                context=browser.new_context(viewport={'width':width,'height':1000})
                cookie=case.client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
                page=context.new_page();errors=[];posts=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                latest=page.locator('.audio-latest-result')
                alternate=latest.locator('[data-audio-alternate]')
                # Exercise the real Home button and POST handoff, including an empty draft.
                for draft in ('','  Keep my transferred script. 日本語 & punctuation.  '):
                    page.goto(origin+'/products/start',wait_until='networkidle')
                    page.locator('#ai-input,#agent-message').fill(draft)
                    page.locator('[data-home-task=voiceover]').click()
                    page.wait_for_url('**/kilas-translator?mode=voiceover')
                    expect(alternate).to_be_visible()
                    expect(alternate).to_have_attribute('data-audio-alternate',f'/kilas-translator/jobs/{ident}/alternate')
                    expect(page.locator('#audio-script')).to_have_value(draft)
                    page.locator('#translate-tab').click();page.locator('#voiceover-tab').click()
                    expect(page.locator('#audio-script')).to_have_value(draft)
                page.goto(origin+'/kilas-translator?mode=voiceover',wait_until='networkidle')
                for navigation in ('entry','tabs','refresh'):
                    if navigation=='tabs':
                        page.locator('#translate-tab').click();page.locator('#voiceover-tab').click()
                    elif navigation=='refresh':page.reload(wait_until='networkidle')
                    expect(alternate).to_be_visible();expect(alternate).to_have_text('Generate another version')
                    expect(alternate).to_have_attribute('data-audio-alternate',f'/kilas-translator/jobs/{ident}/alternate')
                # The restored card uses the existing delegated edit handler and latest spoken language/voice.
                latest.locator('[data-audio-edit]').click()
                expect(page.locator('#audio-script')).to_have_value(spoken)
                expect(page.locator('#voice-language')).to_have_value('es')
                expect(page.locator('#selected-voice')).to_have_value('kilas-female')
                expect(page.locator('#voice-translate-toggle')).not_to_be_checked()
                page.locator('#audio-script').fill('Unsaved draft must not change alternate context.')
                def capture(route):
                    posts.append(route.request.post_data)
                    route.fulfill(status=200,content_type='application/json',body=json.dumps({'url':f'/kilas-translator/jobs/{ident}'}))
                page.route('**/jobs/*/alternate',capture)
                alternate.click();page.wait_for_url(origin+f'/kilas-translator/jobs/{ident}')
                assert len(posts)==1 and 'Unsaved draft' not in posts[0]
                expect(page.locator('#audio-result [data-audio-alternate]')).to_be_visible()
                # Opening the same item through Recent preserves the same action and edit context.
                page.goto(origin+'/kilas-translator?mode=voiceover',wait_until='networkidle')
                page.locator(f'[data-audio-history="{ident}"]').click()
                expect(page.locator('#audio-result [data-audio-alternate]')).to_have_attribute('data-audio-alternate',f'/kilas-translator/jobs/{ident}/alternate')
                page.locator('#audio-result [data-audio-edit]').click()
                expect(page.locator('#audio-script')).to_have_value(spoken);expect(page.locator('#voice-language')).to_have_value('es')
                page.goto(origin+'/kilas-translator?mode=voiceover',wait_until='networkidle')
                latest.screenshot(path=str(out/f'latest-{width}.png'))
                # Explicit non-success results must not inherit a latest successful action.
                for status in ('QUEUED','PROCESSING','FAILED'):
                    f.db.execute('UPDATE kilas_audio_jobs SET status=? WHERE id=?',(status,ident))
                    page.goto(origin+f'/kilas-translator/jobs/{ident}',wait_until='networkidle')
                    expect(page.locator('[data-audio-alternate]')).to_have_count(0)
                f.db.execute('DELETE FROM kilas_audio_jobs WHERE id=?',(ident,))
                page.goto(origin+'/kilas-translator?mode=voiceover',wait_until='networkidle')
                expect(page.locator('.audio-latest-result')).to_have_count(0);expect(page.locator('[data-audio-alternate]')).to_have_count(0)
                assert not errors,errors
                report.append({'width':width,'direct_entry_tabs_refresh_recent':True,'real_home_handoff_empty_and_transferred_draft':True,'latest_language_and_voice_edit':True,'alternate_bound_to_result_not_draft':True,'loading_failed_empty_no_alternate':True,'paid_calls':0})
                context.close();case.doCleanups()
            browser.close()
        (out/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:server.shutdown()


if __name__=='__main__':main()
