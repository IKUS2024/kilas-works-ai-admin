"""Canonical unified conversation acceptance at five widths; controlled providers."""
import io
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_ai_unified as fixture


def main():
    f=fixture.base.f
    server=make_server('127.0.0.1',0,f.fixture.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    raw=io.BytesIO();Image.new('RGB',(24,24),'orange').save(raw,'PNG')
    source=f.SOURCE.replace('Rp5.000.000','belum ditentukan')
    search={'text':'Python diperiksa dari sumber resmi.','citations':[{'url':'https://www.python.org/downloads/','title':'Python'}],'model':fixture.model_policy.LUNA,'usage':{}}
    def reply(*a,**k):return fixture.answer('Jawaban terverifikasi. Pertimbangkan biaya operasional dan cadangan kas. Uji permintaan sebelum memilih usaha agar jumlah pegawai tetap kecil.')
    try:
        with patch.object(fixture.providers,'stream',side_effect=reply),patch.object(f.content_worker,'text',return_value=(source,fixture.model_policy.LUNA,{})),patch.object(fixture.unified_runtime.tools,'web_search_steps',side_effect=lambda *a,**k:iter([{'result':search}])),patch.dict(os.environ,{'KILAS_AI_OPENAI_IMAGE_MODEL':'configured-image'}),patch.object(fixture.unified_runtime.tools,'image',return_value={'raw':raw.getvalue(),'mime':'image/png','model':'configured-image','usage':{}}),sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            for width in (320,360,390,820,1440):
                case=fixture.UnifiedTests('test_ordinary_and_capability_never_create_jobs');case.id=lambda:'unified-browser-'+str(width);case.setUp()
                cookie=case.client().get_cookie('session')
                context=browser.new_context(viewport={'width':width,'height':900},has_touch=width<760,reduced_motion='reduce')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page=context.new_page();errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(origin+'/kilas-ai',wait_until='networkidle')
                assert page.locator('.ai-mode-tabs,#ai-search').count()==0
                assert page.locator('button').filter(has_text='+ Chat baru').count()==1
                def send(text):
                    count=page.locator('.agent-message-user').count()
                    page.locator('#agent-message').fill(text)
                    page.get_by_role('button',name='Kirim',exact=True).click()
                    expect(page.locator('.agent-message-user')).to_have_count(count+1)
                    expect(page.locator('#agent-message')).to_have_value('',timeout=15000)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,text)
                    if width<760:assert page.evaluate("document.activeElement.id!=='agent-message'")
                send('halo')
                send('menurut lu modal 150 juta mending laundry atau cafe?')
                send('versi Python terbaru sekarang apa?')
                expect(page.locator('.agent-message-assistant a[href="https://www.python.org/downloads/"]')).to_be_visible()
                send('kamu bisa bikin PDF ga?')
                assert case.jobs.list_jobs(case.owner)==[]
                send('buat logo Kilas Works')
                expect(page.locator('.work-file')).to_have_count(1,timeout=15000)
                expect(page.locator('.work-file img')).to_be_visible()
                send('buat kode SVG logo Kilas Works')
                assert len(case.jobs.list_jobs(case.owner))==1
                send('buat proposal singkat Kilas Demo dalam PDF')
                expect(page.locator('.work-file')).to_have_count(2,timeout=15000)
                old=page.locator('[data-job-id]').first.get_attribute('data-job-id')
                send('ingatkan aku besok jam 8 bayar tagihan')
                expect(page.locator('[data-active-count],[data-notification-count]')).to_have_count(0)
                expect(page.get_by_text('Terjadwal',exact=True).first).to_be_visible()
                send('halo lagi')
                assert page.locator('[data-job-id]').first.get_attribute('data-job-id')==old
                page.locator('#work-source-files').set_input_files({'name':'qa.txt','mimeType':'text/plain','buffer':b'Kilas Demo verified input.'})
                expect(page.locator('.work-pending-file')).to_have_count(1)
                page.get_by_role('button',name='Hapus lampiran qa.txt',exact=True).click()
                expect(page.locator('.work-pending-file')).to_have_count(0)
                # Pending image thumbnails and files are additive and removable.
                image={'name':'photo.png','mimeType':'image/png','buffer':raw.getvalue()}
                page.locator('#work-source-files').set_input_files(image)
                expect(page.locator('.work-pending-file img')).to_be_visible()
                page.get_by_role('button',name='Hapus lampiran photo.png',exact=True).click()
                expect(page.locator('.work-pending-file')).to_have_count(0)
                page.locator('#work-source-files').set_input_files(image)
                page.locator('#work-source-files').set_input_files({**image,'name':'second.png'})
                expect(page.locator('.work-pending-file')).to_have_count(2)
                page.get_by_role('button',name='Hapus lampiran second.png',exact=True).click()
                expect(page.locator('.work-pending-file')).to_have_count(1)
                document=f.pdf.render('# Fakta QA\n\nInformasi yang terkonfirmasi untuk Kilas Demo.')
                name='dokumen-dengan-nama-panjang-untuk-menguji-kartu-lampiran-yang-tetap-ringkas.pdf'
                upload={'name':name,'mimeType':'application/pdf','buffer':document['content']}
                page.locator('#work-source-files').set_input_files(upload)
                page.get_by_role('button',name='Hapus lampiran '+name,exact=True).click()
                expect(page.locator('.work-pending-file')).to_have_count(1)
                page.locator('#work-source-files').set_input_files(upload)
                expect(page.locator('.work-pending-file')).to_have_count(2)
                assert page.locator('.work-pending-file .work-attachment-name').last.evaluate("e=>getComputedStyle(e).textOverflow==='ellipsis' && e.scrollWidth>e.clientWidth")
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(Path(tempfile.gettempdir())/f'kilas-cleanup-pending-{width}.png'))
                send('Tolong jelaskan isi lampiran ini')
                expect(page.locator('.work-sent-file')).to_have_count(2)
                expect(page.locator('.work-sent-file img')).to_be_visible()
                expect(page.locator('.work-pending-file')).to_have_count(0)
                page.screenshot(path=str(Path(tempfile.gettempdir())/f'kilas-cleanup-sent-{width}.png'))
                attached=page.locator('.agent-message-user').filter(has=page.locator('.work-sent-file'))
                attached_id=attached.get_attribute('data-message-id')
                hrefs=page.locator('.work-sent-file').evaluate_all('(els)=>els.map(e=>e.href)')
                for href in hrefs:assert context.request.get(href).status==200
                send('Terima kasih atas penjelasannya')
                expect(page.locator(f'[data-message-id="{attached_id}"] .work-sent-file')).to_have_count(2)
                page.reload(wait_until='networkidle')
                expect(page.locator(f'[data-message-id="{attached_id}"] .work-sent-file')).to_have_count(2)
                assert page.locator('[data-job-id]').first.get_attribute('data-job-id')==old
                original=page.locator('input[name=conversation_id]').input_value()
                fixture.agent_store.append(case.owner,'user','Judul percakapan yang sangat panjang untuk membuktikan elipsis pada sidebar',case.conversation)
                f.fixture.db.execute('UPDATE kilas_ai_conversations SET title=? WHERE id=?',('Judul percakapan yang sangat panjang untuk membuktikan elipsis',case.conversation))
                page.reload(wait_until='networkidle')
                if width<760:page.get_by_role('button',name='Buka riwayat').click()
                row=page.locator('.ai-history a[aria-current=page]')
                assert row.evaluate("e=>getComputedStyle(e).whiteSpace==='nowrap' && getComputedStyle(e).textOverflow==='ellipsis' && e.scrollWidth>e.clientWidth && e.getBoundingClientRect().height<=48")
                assert page.locator('#agent-sidebar a[href*=tasks],#agent-sidebar a[href*=notifications]').count()==0
                page.screenshot(path=str(Path(tempfile.gettempdir())/f'kilas-cleanup-sidebar-{width}.png'))
                page.get_by_role('button',name='+ Chat baru',exact=True).click()
                expect(page.get_by_role('heading',name='Apa yang ingin kamu lakukan?')).to_be_visible()
                expect(page.locator('.work-sent-file,[data-job-id]')).to_have_count(0)
                page.goto(origin+'/kilas-ai/agent?view=history',wait_until='networkidle')
                assert page.locator(f'nav[aria-label="Riwayat percakapan"] a[href$="conversation={original}"]').count()==1
                page.goto(origin+f'/kilas-ai/agent?conversation={original}',wait_until='networkidle')
                expect(page.locator(f'[data-message-id="{attached_id}"] .work-sent-file')).to_have_count(2)
                assert page.locator('[data-job-id]').first.get_attribute('data-job-id')==old
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.locator('#agent-message').click();assert page.evaluate("document.activeElement.id==='agent-message'")
                page.locator('#agent-message').blur()
                assert not errors,errors
                page.screenshot(path=str(Path(tempfile.gettempdir())/f'kilas-unified-{width}.png'),full_page=True)
                context.close()
            browser.close()
    finally:server.shutdown()
    print('PASS: unified Chat/results, attachment previews/removal/persistence/downloads/reopen, clean sidebar, compact history and focus at 320/360/390/820/1440')


if __name__=='__main__':main()
