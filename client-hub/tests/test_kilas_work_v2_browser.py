"""One batched Work V2 responsive/permission/focus/progress inspection."""
import io
import json
import tempfile
import threading
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_work_v2 as fixture


def main():
    f=fixture.f
    app=f.fixture.app.app
    app.config.update(TESTING=True,CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    try:
        with patch.object(f.content_worker,'text',return_value=(f.SOURCE,f.model_policy.LUNA,{})),sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            for width,height in ((320,780),(360,780),(390,844),(820,900),(1440,900)):
                case=fixture.WorkV2Tests(methodName='test_real_docx_xlsx_pptx_and_formula_safety');case.id=lambda:'work-v2-browser-'+str(width);case.setUp()
                conversation=case.conversation
                outputs={'pdf':f.SOURCE,'docx':f.SOURCE,'xlsx':'Item,Jumlah\nLunch box,30\nAir,2\n','pptx':'# Kilas Works\nLayanan UMKM\n## Lingkup\n- Layanan customer\n## Berikutnya\n- Konfirmasi kebutuhan\n'}
                for format,source in outputs.items():case.complete(f.REQUEST+' '+format if format in ('pdf','docx') else 'Buat dokumen '+format,source)
                waiting=f.fixture.store.create(case.owner,'Buat proposal',conversation_id=conversation)
                with patch.object(f.content_worker,'text',return_value=('Apa yang perlu dicantumkan di dokumen?',f.model_policy.LUNA,{})):
                    case.tick(waiting);case.tick(waiting)
                future=f.fixture.store.now()+timedelta(days=1)
                scheduled=f.fixture.store.create(case.owner,'Pengingat cek jadwal',mode='SCHEDULED',wake_at=future,conversation_id=conversation,checkpoint={'reminder':{'subject':'Cek jadwal'}})
                running=f.fixture.store.create(case.owner,'Riset publik terbaru',conversation_id=conversation)
                claim=f.fixture.store.claim_due(1)[0]
                f.fixture.store.install_plan(f.fixture.store.get(case.owner,running),claim[1],f.fixture.planner.validate(f.fixture.proposal(),'ONE_SHOT'))
                f.fixture.store.release(*claim)
                f.fixture.db.execute('UPDATE kilas_agent_jobs SET next_wake_at=? WHERE id=?',(f.fixture.store.stamp(future),running))
                with f.fixture.store.transaction() as conn:f.fixture.store.event(conn,running,'WRITING','Internal content not for display',unread=False)
                cookie=case.client().get_cookie('session')
                context=browser.new_context(viewport={'width':width,'height':height},has_touch=width<760,reduced_motion='reduce')
                desktop='true' if width>=760 else 'false'
                context.add_init_script("const native=window.matchMedia.bind(window);window.matchMedia=q=>q==='(hover: hover) and (pointer: fine)'?{matches:"+desktop+",addEventListener(){},removeEventListener(){}}:native(q);window.__gpsCalls=0;Object.defineProperty(navigator,'geolocation',{value:{getCurrentPosition(){window.__gpsCalls++;}}});")
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page=context.new_page();errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(origin+f'/kilas-ai/agent?conversation={conversation}',wait_until='networkidle')
                expect(page.locator('[data-active-count]')).to_have_text('3')
                assert page.locator('.agent-sections a[href*=tasks]').count()==1
                assert page.locator('.agent-sections a[href*=notifications]').count()==1
                expect(page.locator('.work-file')).to_have_count(4)
                self_text=page.locator('body').inner_text()
                for unwanted in ('Connections','Advanced settings','Instruksi pelaksanaan','Internal content not for display'):assert unwanted not in self_text,(width,unwanted)
                expect(page.get_by_text('Menulis isi…',exact=True)).to_be_visible()
                expect(page.get_by_text('Menunggu jawabanmu',exact=True).first).to_be_visible()
                expect(page.get_by_text('Terjadwal',exact=True)).to_be_visible()
                assert page.evaluate('window.__gpsCalls')==0
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,'chat overflow')
                for control in page.locator('.work-file-actions a,.work-add-file,.ai-send').all():
                    assert control.bounding_box()['height']>=44,(width,'touch target')
                page.locator('#work-source-files').set_input_files([{'name':'facts.txt','mimeType':'text/plain','buffer':b'Verified Kilas Works source.'},{'name':'notes.csv','mimeType':'text/csv','buffer':b'Item,Count\nLunch box,30'}])
                expect(page.locator('.work-pending-file')).to_have_count(2)
                page.get_by_role('button',name='Hapus lampiran facts.txt',exact=True).click()
                expect(page.locator('.work-pending-file')).to_have_count(1)
                page.get_by_role('button',name='Hapus lampiran notes.csv',exact=True).click()
                expect(page.locator('.work-pending-file')).to_have_count(0)
                page.screenshot(path=str(Path(tempfile.gettempdir())/f'kilas-work-v2-chat-{width}.png'),full_page=True)
                page.locator('#agent-message').fill(f.REQUEST)
                page.get_by_role('button',name='Kirim',exact=True).click()
                expect(page.locator('.work-file')).to_have_count(5,timeout=15000)
                expect(page.locator('[data-active-count]')).to_have_text('3')
                assert page.locator('.agent-sections a[href*=tasks]').count()==1
                assert page.locator('.agent-sections a[href*=notifications]').count()==1
                assert page.evaluate("document.activeElement.id==='agent-message'") is (width>=760),(width,'completion focus')
                if width<760:
                    page.locator('#agent-message').click()
                    assert page.evaluate("document.activeElement.id==='agent-message'")
                    page.locator('#agent-message').blur()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.goto(origin+f'/kilas-ai/agent/jobs/{waiting}',wait_until='networkidle')
                expect(page.get_by_role('heading',name='Menunggu jawabanmu')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,'waiting detail')
                page.screenshot(path=str(Path(tempfile.gettempdir())/f'kilas-work-v2-detail-{width}.png'),full_page=True)
                page.goto(origin+f'/kilas-ai/agent/jobs/{running}',wait_until='networkidle')
                page.locator('#task-feedback').fill('Keep this unsaved instruction')
                f.fixture.db.execute("UPDATE kilas_agent_jobs SET status='COMPLETED',next_wake_at=NULL WHERE id=?",(running,))
                expect(page.locator('.agent-section-head p')).to_have_text('Selesai',timeout=7000)
                expect(page.locator('#task-feedback')).to_have_value('Keep this unsaved instruction')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.goto(origin+'/kilas-ai/agent?view=settings',wait_until='networkidle')
                expect(page.get_by_role('heading',name='Pengaturan Kilas AI')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,'settings')
                expect(page.locator('[data-enable-push]')).to_have_count(0)
                assert page.evaluate('window.__gpsCalls')==0
                assert not errors,errors
                context.close()
            browser.close()
    finally:server.shutdown()
    print('PASS Work V2: 320/360/390/820/1440, Office/PDF cards, progress/wait/schedule, inline persistent results, removed task/notification navigation, attachments/remove, no overflow, 44px, coarse-pointer completion/manual focus, no automatic GPS/push prompt.')


if __name__=='__main__':main()
