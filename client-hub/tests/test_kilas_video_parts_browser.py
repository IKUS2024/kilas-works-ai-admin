"""Real browser connected-clip UI, clipboard, revision persistence and responsive contracts."""
import json
import os
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_kilas_video import VideoTests, fixture, director, provider_response
from test_kilas_video_parts import multipart


def main():
    server=make_server('127.0.0.1',0,fixture.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(tempfile.gettempdir())/'kilas-video-parts-browser';output.mkdir(exist_ok=True)
    active=[multipart()]
    try:
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-browser-only'}),patch.object(director.requests,'post',side_effect=lambda *a,**kw:provider_response(active[0])),sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            for width in (320,360,390,430,768,820,1024,1440):
                case=VideoTests('test_create_and_reopen_owner_history');case.id=lambda:'video-parts-browser-'+str(width);case.setUp()
                context=browser.new_context(viewport={'width':width,'height':950},has_touch=width<761,reduced_motion='reduce',permissions=['clipboard-read','clipboard-write'])
                cookie=case.client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(origin+'/kilas-ai/video',wait_until='networkidle')
                expect(page.locator('#video-multi-controls')).to_be_hidden()
                page.locator('input[name=plan_mode][value=multi]').check()
                page.select_option('#video-clip-strategy','10')
                expect(page.locator('#video-split-preview')).to_have_text('3 klip · 0–10s / 10–20s / 20–30s')
                page.fill('#video-total-duration','10');page.select_option('#video-clip-strategy','15')
                assert not page.locator('#video-total-duration').evaluate('e=>e.checkValidity()')
                page.fill('#video-total-duration','180');page.select_option('#video-clip-strategy','5')
                expect(page.locator('#video-split-preview')).to_contain_text('Maksimal 8 klip')
                assert not page.locator('#video-total-duration').evaluate('e=>e.checkValidity()')
                page.fill('#video-total-duration','45');page.select_option('#video-clip-strategy','15');expect(page.locator('#video-split-preview')).to_have_text('3 klip · 0–15s / 15–30s / 30–45s')
                page.fill('#video-total-duration','25');page.select_option('#video-clip-strategy','auto')
                expect(page.locator('#video-split-preview')).to_have_text('3 klip · 0–9s / 9–17s / 17–25s')
                page.fill('#video-total-duration','30');page.select_option('#video-clip-strategy','10')
                for version,(subject,english,instruction) in enumerate([('mobil','car','Video mobil 30 detik'),('baju','shirt','Ganti jadi baju'),('makanan','food','Ganti jadi makanan'),('makanan','food','lebih premium, tanpa voice-over')],1):
                    active[0]=multipart(subject,english)
                    page.fill('#video-idea',instruction);page.click('#video-submit')
                    expect(page.locator('input[name=version]')).to_have_value(str(version),timeout=15000)
                    expect(page.locator('.video-scenes>li')).to_have_count(3)
                    expect(page.locator('#video-active-title')).to_have_text('Arahan '+subject)
                    assert page.evaluate("document.activeElement.id!=='video-idea'")
                package=json.loads(page.locator('#video-copy-data').text_content())
                for key in ('image_1','video_1','image_2','video_2','image_3','video_3'):
                    page.locator('[data-video-copy='+key+']').click()
                    expect(page.locator('[data-video-copy='+key+']')).to_contain_text('Tersalin')
                    assert page.evaluate('navigator.clipboard.readText()').replace('\r\n','\n')==package[key].replace('\r\n','\n'),(width,key)
                assert page.locator('[data-video-copy]').count()==6
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                page.evaluate('window.scrollTo(0,0)')
                page.screenshot(path=str(output/f'multipart-{width}.png'),full_page=True)
                page.screenshot(path=str(output/f'multipart-viewport-{width}.png'))
                page.locator('#video-clip-1').evaluate('e=>window.scrollTo(0,e.getBoundingClientRect().top+scrollY)')
                page.screenshot(path=str(output/f'part-copy-{width}.png'))
                url=page.url;page.reload(wait_until='networkidle')
                expect(page.locator('input[name=version]')).to_have_value('4')
                assert json.loads(page.locator('#video-copy-data').text_content())==package
                page.goto(origin+'/kilas-ai/video');page.locator('.video-history>ul a').first.click()
                assert page.url==url
                expect(page.locator('.video-scenes>li')).to_have_count(3)
                # Revision changes total duration, and the refreshed form agrees after reopen.
                active[0]=multipart('makanan','food',25)
                page.fill('#video-idea','sekarang 25 detik');page.click('#video-submit')
                expect(page.locator('input[name=version]')).to_have_value('5')
                expect(page.locator('#video-total-duration')).to_have_value('25')
                expect(page.locator('#video-split-preview')).to_have_text('3 klip · 0–10s / 10–20s / 20–25s')
                latest=json.loads(page.locator('#video-copy-data').text_content())
                for language in ('en','es','zh','id'):
                    context.add_cookies([{'name':'kilas_language','value':language,'url':origin}])
                    page.reload(wait_until='networkidle')
                    assert json.loads(page.locator('#video-copy-data').text_content())==latest
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,language)
                assert not errors,(width,errors)
                context.close()
            browser.close()
        print('PASS: connected clips, 6 image/video clipboard actions, revision chain, history, reload and latest duration at 8 widths')
    finally:server.shutdown()


if __name__=='__main__':main()
