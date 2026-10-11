"""One baseline+confirmation batch for scoped descriptions; provider IO forbidden."""
import json,os,shutil,threading
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from test_kilas_tabs_copy import TabsCopyTests,fixture


def main():
    stage=os.environ.get('KILAS_TABS_COPY_STAGE','final');case=TabsCopyTests('test_feature_routes_keep_inputs_user_content_and_essential_notices');case.id=lambda:'tabs-copy-browser';case.setUp()
    server=make_server('127.0.0.1',0,fixture.app.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_TABS_COPY_SCREENSHOTS','/tmp/kilas-tabs-copy'))/stage;output.mkdir(parents=True,exist_ok=True);report=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (320,1440):
                context=browser.new_context(viewport={'width':width,'height':1000});cookie=case.client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}]);page=context.new_page();errors=[];posts=[]
                page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
                page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                selected=('home','video_new','voiceover') if stage=='baseline' else ('home','video_new','video_result','voiceover','work_tasks','reminders','projects','live_assist')
                for key in selected:
                    response=page.goto(origin+case.paths[key],wait_until='networkidle');assert response.status==200,(key,response.status)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,key)
                    if stage=='final':
                        if key=='home':
                            expect(page.locator('.ai-empty p')).to_have_count(0);expect(page.locator('.ai-hint')).to_have_text('Periksa jawaban AI.')
                            page.locator('#ai-input').fill('Unsent description stays.')
                            if width<761:page.locator('[data-premium-menu]').click();page.keyboard.press('Escape')
                            expect(page.locator('#ai-input')).to_have_value('Unsent description stays.')
                        if key=='video_new':
                            expect(page.locator('.video-heading>div>p')).to_have_count(0);expect(page.locator('#video-composer')).to_be_visible();page.locator('.video-production-info summary').click();expect(page.locator('.video-production-info p')).to_be_visible();page.locator('.video-production-info summary').click()
                        if key=='voiceover':expect(page.locator('#voice-generate')).to_have_count(1)
                    page.screenshot(path=str(output/f'{key}-{width}.png'))
                    report.append({'tab':key,'width':width,'status':'PASS'})
                assert not errors and all(url.endswith('/kilas-ai/work/preferences') for url in posts),(errors,posts)
                context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps({'paid_io':False,'generation_posts':0,'fixture_timezone_preference_posts':len(posts),'pages':report},indent=2));print(json.dumps(report,indent=2))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
