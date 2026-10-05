"""Real DOM/clipboard/regeneration checks for the storyboard-first Video surface."""
import json
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from test_kilas_video import VideoTests,fixture,director,provider_response,spec
from test_kilas_video_parts import multipart


def main():
    server=make_server('127.0.0.1',0,fixture.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(tempfile.gettempdir())/'kilas-video-storyboard-browser';output.mkdir(exist_ok=True)
    active=[spec()]
    try:
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only'}),patch.object(director.requests,'post',side_effect=lambda *a,**kw:provider_response(active[0])) as calls,sync_playwright() as p:
            browser=p.chromium.launch()
            for width in (320,360,390,430,768,1440):
                active[0]=multipart() if width in (390,1440) else spec()
                case=VideoTests('test_create_and_reopen_owner_history');case.id=lambda:'storyboard-browser-'+str(width);case.setUp()
                context=browser.new_context(viewport={'width':width,'height':900},has_touch=width<761,reduced_motion='reduce',permissions=['clipboard-read','clipboard-write'])
                cookie=case.client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(origin+'/kilas-ai/video',wait_until='networkidle')
                if active[0].get('parts'):
                    page.locator('input[name=plan_mode][value=multi]').check();page.select_option('#video-clip-strategy','10')
                page.locator('.video-options summary').click();page.select_option('#video-tool','Google Flow')
                page.fill('#video-idea','Bikin storyboard dulu untuk produk, orang dan tempat sama, prompt English')
                page.click('#video-submit');expect(page.locator('.video-scene-prompts')).to_have_count(len(active[0]['scenes']),timeout=15000)
                payload=json.loads(page.locator('#video-copy-data').text_content())
                for key in ('image_1','video_1'):
                    button=page.locator(f'[data-video-copy="{key}"]');button.click()
                    expect(button).to_contain_text('Tersalin')
                    assert page.evaluate('navigator.clipboard.readText()').replace('\r\n','\n')==payload[key].replace('\r\n','\n'),(width,key)
                assert page.locator('[data-video-copy]').count()==2*len(active[0]['scenes'])
                assert payload['image_1']!=payload['video_1']
                assert payload['image_1'] not in payload['video_1']
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                page.locator('.video-scene-prompts').first.evaluate('el=>scrollTo(0,el.getBoundingClientRect().top+scrollY-16)')
                page.screenshot(path=str(output/f'scene-{width}.png'))
                page.evaluate('scrollTo(0,0)');page.screenshot(path=str(output/f'full-{width}.png'),full_page=True)
                page.fill('#video-idea','Draft revisi yang belum dikirim')
                before=calls.call_count
                page.locator('[data-video-regenerate=video]').click();expect(page.locator('input[name=version]')).to_have_value('2')
                self_copy=json.loads(page.locator('#video-copy-data').text_content());assert self_copy['all_images']==payload['all_images']
                assert calls.call_count==before+1
                expect(page.locator('#video-idea')).to_have_value('Draft revisi yang belum dikirim')
                page.locator('[data-video-regenerate=storyboard]').click();expect(page.locator('input[name=version]')).to_have_value('3')
                assert calls.call_count==before+2
                page.reload(wait_until='networkidle');expect(page.locator('input[name=version]')).to_have_value('3')
                assert json.loads(page.locator('#video-copy-data').text_content())['all_images']==payload['all_images']
                context.add_cookies([{'name':'kilas_language','value':'en','url':origin}]);page.reload(wait_until='networkidle')
                expect(page.locator('[data-video-copy=image_1]').first).to_have_text('Copy Image Prompt')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert not errors,errors
                context.close()
            browser.close()
        print('PASS storyboard still/video copies, locked regeneration, pending draft, persistence, English controls and no overflow at 6 widths')
    finally:server.shutdown()


if __name__=='__main__':main()
