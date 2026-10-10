"""Actual Video UI at all release widths; isolated owners, real images, mocked AI transport."""
import io
import json
import os
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch
from PIL import Image
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_kilas_video import VideoTests, fixture, director, provider_response, spec
from test_kilas_video_v2 import plan


def main():
    server=make_server('127.0.0.1',0,fixture.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(tempfile.gettempdir())/'kilas-video-browser';output.mkdir(exist_ok=True)
    image=io.BytesIO();Image.new('RGB',(100,120),'orange').save(image,'PNG')
    try:
        active=[spec()]
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-video-browser-only'}),patch.object(director.requests,'post',side_effect=lambda *a,**kw:provider_response(active[0])),sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            for width in (320,360,390,430,768,820,1024,1440):
                active[0]=spec()
                case=VideoTests('test_create_and_reopen_owner_history');case.id=lambda:'video-browser-'+str(width);case.setUp()
                context=browser.new_context(viewport={'width':width,'height':950},has_touch=width<761,reduced_motion='reduce',permissions=['clipboard-read','clipboard-write'])
                cookie=case.client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                def check(name):
                    page.evaluate('window.scrollTo(0,0)')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,name)
                    assert page.locator('body').evaluate('e=>getComputedStyle(e).backgroundColor')=='rgb(255, 255, 255)'
                    page.screenshot(path=str(output/f'{name}-{width}.png'),full_page=True)
                    page.screenshot(path=str(output/f'{name}-viewport-{width}.png'))
                page.goto(origin+'/products/start',wait_until='networkidle');expect(page.locator('[data-home-task=video]')).to_be_visible()
                page.locator('[data-home-task=video]').click();page.locator('#ai-send').click();expect(page.get_by_role('heading',name='Kilas Video',exact=True)).to_be_visible();check('empty')
                if width<761:
                    page.locator('[data-premium-menu]').click();expect(page.locator('.premium-navigation').get_by_role('link',name='Video',exact=True)).to_be_visible()
                    page.locator('.premium-sidebar [data-premium-close]').click()
                page.locator('.video-options summary').click();page.select_option('#video-duration','10');page.select_option('#video-tool','Seedance')
                payload={'name':'reference.png','mimeType':'image/png','buffer':image.getvalue()}
                page.locator('#video-references').set_input_files(payload);expect(page.locator('.video-preview')).to_have_count(1)
                page.locator('#video-references').set_input_files(payload);expect(page.locator('.video-preview')).to_have_count(2)
                page.get_by_role('button',name='Hapus referensi reference.png').first.click();expect(page.locator('.video-preview')).to_have_count(1)
                page.fill('#video-idea','gw mau bikin skincare buat reels, cewek Indonesia, clean, natural, produknya jangan berubah')
                def generation_feedback(route):
                    expect(page.locator('#generation-feedback')).to_be_visible()
                    expect(page.locator('#generation-feedback')).to_have_attribute('data-state','busy')
                    expect(page.locator('#video-submit')).to_be_disabled()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    route.continue_()
                page.route('**/video/plan',generation_feedback)
                page.click('#video-submit');expect(page.locator('.video-plan')).to_be_visible(timeout=15000)
                expect(page.locator('#generation-feedback')).to_have_attribute('data-state','success')
                page.locator('#generation-feedback-close').click();expect(page.locator('#generation-feedback')).to_be_hidden()
                page.unroute('**/video/plan')
                expect(page.locator('.video-reference-strip img')).to_have_count(1);expect(page.locator('.video-plan-heading')).to_contain_text('Seedance');check('result')
                expect(page.locator('.video-history>ul')).to_contain_text('Skincare Natural Reel')
                assert page.locator('#video-outline ul').count()==0
                assert page.evaluate("document.activeElement.id!=='video-idea'")
                expect(page.locator('.video-manage summary')).to_be_visible()
                package=json.loads(page.locator('#video-copy-data').text_content())
                for key in ('image_1','video_1'):
                    page.locator('[data-video-copy='+key+']').click()
                    expect(page.locator('[data-video-copy-status]')).to_contain_text('Tersalin')
                    assert page.evaluate('navigator.clipboard.readText()').replace('\r\n','\n')==package[key].replace('\r\n','\n')
                check('copy-feedback')
                page.fill('#video-idea','scene 2 lebih premium, sekarang versi Runway, orangnya dan produknya sama');page.click('#video-submit')
                expect(page.locator('.video-plan-heading')).to_contain_text('Runway',timeout=15000)
                expect(page.locator('input[name=version]')).to_have_value('2');page.reload(wait_until='networkidle');expect(page.locator('.video-plan-heading')).to_contain_text('Runway')
                page.locator('.video-manage summary').click();page.fill('#video-title','Rencana QA '+str(width));page.get_by_role('button',name='Simpan nama',exact=True).click()
                expect(page.locator('.video-plan-heading h2')).to_have_text('Rencana QA '+str(width))
                page.locator('.video-manage summary').click();page.get_by_role('button',name='Duplikat rencana',exact=True).click()
                expect(page.locator('.video-plan-heading h2')).to_contain_text('salinan')
                page.locator('.video-manage summary').click();page.locator('[data-video-delete]').click();expect(page.locator('dialog')).to_be_visible();check('delete-dialog')
                page.locator('dialog').get_by_role('button',name='Batal').click();assert not page.locator('dialog').is_visible()
                page.locator('[data-video-delete]').click();page.locator('dialog').get_by_role('button',name='Hapus rencana',exact=True).click()
                expect(page.locator('.video-history')).to_contain_text('Rencana QA '+str(width))
                for area in ('learn','workflow','tools'):
                    page.goto(origin+'/kilas-ai/video?area='+area,wait_until='networkidle');assert '?area=' not in page.url
                assert page.locator('.video-tabs').count()==0
                assert page.locator('.video-primary').get_by_text('Belajar',exact=True).count()==0
                page.goto(origin+'/kilas-ai/video',wait_until='networkidle')
                for version,(subject,english,idea) in enumerate([('mobil','car','Video mobil 10 detik'),('baju','shirt','Ganti jadi baju'),('makanan','food','Ganti jadi makanan')],1):
                    active[0]=plan(subject,english)
                    page.fill('#video-idea',idea);page.click('#video-submit')
                    expect(page.locator('input[name=version]')).to_have_value(str(version),timeout=15000)
                    expect(page.locator('#video-active-title')).to_have_text('Arahan '+subject)
                    expect(page.locator('.video-plan-heading h2')).to_have_text('Arahan '+subject)
                text=page.locator('.video-plan').inner_text().lower()
                assert 'mobil' not in text and 'baju' not in text
                page.locator('[data-video-copy=video_1]').click();assert 'food' in page.evaluate('navigator.clipboard.readText()')
                page.reload(wait_until='networkidle');expect(page.locator('#video-active-title')).to_have_text('Arahan makanan');check('replacement-chain')
                old_key=page.locator('input[name=operation_key]').input_value()
                page.route('**/video/plan',lambda route:route.fulfill(status=500,content_type='text/html',body='<html>Gateway error</html>'))
                page.fill('#video-idea','lebih premium, tanpa voice-over');page.click('#video-submit')
                expect(page.locator('#video-error')).to_contain_text('Coba Lagi')
                expect(page.locator('#generation-feedback')).to_have_attribute('data-state','error')
                expect(page.locator('input[name=version]')).to_have_value('3')
                expect(page.locator('#video-active-title')).to_have_text('Arahan makanan')
                expect(page.locator('#video-submit')).to_be_enabled()
                assert page.locator('input[name=operation_key]').input_value()!=old_key
                page.unroute('**/video/plan')
                # Retry the preserved revision on the same active project.
                page.click('#video-retry')
                expect(page.locator('input[name=version]')).to_have_value('4')
                expect(page.locator('#video-error')).to_be_hidden()
                page.route('**/video/plan',lambda route:route.fulfill(status=409,json={'processing':True,'error':'Sedang menyusun Video Plan...'}))
                page.fill('#video-idea','lebih premium');page.click('#video-submit')
                expect(page.locator('#video-status')).to_have_text('Sedang menyusun Video Plan...')
                expect(page.locator('#video-error')).to_be_hidden()
                expect(page.locator('input[name=version]')).to_have_value('4')
                page.unroute('**/video/plan')
                page.goto(origin+'/kilas-ai/video',wait_until='networkidle');page.fill('#video-idea','x'*2400);check('long-idea')
                page.route('**/video/plan',lambda route:route.fulfill(status=503,json={'error':'Rencana belum berhasil disusun. Coba lagi.'}))
                with page.expect_response(lambda r:r.url.endswith('/video/plan')):page.click('#video-submit')
                expect(page.locator('#video-error')).to_be_visible();check('error')
                expect(page.locator('#video-submit')).to_be_enabled()
                assert not errors,(width,errors)
                context.close()
            browser.close()
    finally:server.shutdown()
    print('PASS: Video create/reference/remove/revise/copy/reopen/history/rename/duplicate/delete/retired redirects/replacement chain/Home/nav at 320/360/390/430/768/820/1024/1440; screenshots '+str(output))


if __name__=='__main__':main()
