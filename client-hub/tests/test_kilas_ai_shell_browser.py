"""Shared shell interactions with isolated Chat and Agent histories and persistent tasks."""
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch
import test_kilas_agent_chat_browser as fixture
from kilas_ai import store
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server


def main():
    def answer(*args):
        yield {'type':'delta','text':'Jawaban shell terverifikasi.'}
        yield {'type':'finish','reason':'stop'}
    server=make_server('127.0.0.1',0,fixture.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    try:
        with patch.object(fixture.providers,'stream',side_effect=answer),sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            for width,height in ((1440,900),(820,900),(390,844),(360,780),(320,700)):
                owner=fixture.repo.create_user(f'shell-{width}@example.test','hash')
                client=fixture.app.app.test_client()
                with client.session_transaction() as state:state.update(user_id=owner,role='CLIENT_OWNER',_csrf_token='shell-qa')
                cookie=client.get_cookie('session')
                context=browser.new_context(viewport={'width':width,'height':height},has_touch=width<=760,reduced_motion='reduce')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page=context.new_page();errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(origin+'/kilas-ai?attachments=1',wait_until='networkidle')
                page.locator('#ai-input').fill('Pertanyaan di normal Chat')
                page.get_by_role('button',name='Kirim',exact=True).click()
                page.get_by_text('Jawaban shell terverifikasi.',exact=True).wait_for()
                normal_id=int(page.url.rsplit('/',1)[1]);assert len(store.list_threads(owner))==1
                page.locator('.ai-mode-tabs').get_by_role('link',name='Work',exact=True).click()
                expect(page.locator('.ai-mode-tabs [aria-current="page"]')).to_have_text('Work')
                page.get_by_label('Pesan untuk Kilas').fill('Riset kompetitor sampai selesai')
                page.get_by_role('button',name='Kirim',exact=True).click()
                expect(page.locator('[data-job-id]')).to_be_visible()
                job=fixture.jobs.list_jobs(owner)[0];agent_id=job['origin_conversation_id']
                dimensions=[]
                for mode in ('agent','chat'):
                    if mode=='chat':page.locator('.ai-mode-tabs').get_by_role('link',name='Chat',exact=True).click()
                    expect(page.locator('.ai-mode-tabs [aria-current="page"]')).to_have_text('Work' if mode=='agent' else 'Chat')
                    assert page.locator('.ai-app-header').count()==1
                    assert page.locator('.ai-app-header .ai-brand').inner_text()=='Kilas AI'
                    assert page.get_by_role('button',name='Buka menu chat').count()==0
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),(width,mode)
                    dimensions.append(page.evaluate("""() => ({header:document.querySelector('.ai-app-header').offsetHeight,sidebar:document.querySelector('[data-ai-sidebar]').offsetWidth,composer:getComputedStyle(document.querySelector('.ai-composer')).borderRadius,send:document.querySelector('.ai-send').offsetHeight})"""))
                    page.screenshot(path=str(Path(tempfile.gettempdir())/f'kilas-shell-{mode}-{width}.png'),full_page=True)
                    if width<=760:
                        menu=page.get_by_role('button',name='Buka riwayat',exact=True)
                        expect(menu).to_be_visible()
                        assert menu.bounding_box()['height']>=44
                        for closing in ('close','backdrop','escape'):
                            menu.click();expect(menu).to_have_attribute('aria-expanded','true')
                            expect(page.locator('[data-ai-sidebar]')).to_be_visible()
                            if width==320 and closing=='close':page.screenshot(path=str(Path(tempfile.gettempdir())/f'kilas-shell-drawer-{mode}-320.png'),full_page=True)
                            if closing=='close':page.locator('[data-ai-close]').click()
                            elif closing=='backdrop':page.locator('[data-ai-backdrop]').click(position={'x':width-4,'y':height//2})
                            else:page.keyboard.press('Escape')
                            expect(menu).to_have_attribute('aria-expanded','false')
                            expect(page.locator('[data-ai-sidebar]')).to_be_hidden()
                        menu.click()
                    if mode=='agent':
                        assert page.locator('.agent-chats').get_by_text('Riset kompetitor sampai selesai',exact=True).count()==1
                        assert page.locator('.agent-chats').get_by_text('Pertanyaan di normal Chat',exact=True).count()==0
                        page.get_by_role('button',name='+ Work baru',exact=True).click()
                        assert page.locator('.agent-message').count()==0
                        assert fixture.jobs.get(owner,job['id'])['status']=='PLANNING'
                    else:
                        assert page.locator('.ai-history').get_by_text('Pertanyaan di normal Chat',exact=True).count()==1
                        page.get_by_role('link',name='+ Chat baru',exact=True).click()
                        expect(page.locator('#ai-composer')).to_be_visible()
                        assert 'attachments=1' in page.url
                        assert len(store.list_threads(owner))==1
                        assert page.locator('#ai-search').count()==1
                        page.locator('#ai-files').set_input_files({'name':'shell.txt','mimeType':'text/plain','buffer':b'hello'})
                        expect(page.locator('.ai-pending-item')).to_be_visible()
                        page.get_by_role('button',name='Hapus lampiran shell.txt').click()
                        assert page.locator('.ai-pending-item').count()==0
                assert dimensions[0]==dimensions[1],(width,dimensions)
                page.goto(origin+f'/kilas-ai/threads/{normal_id}',wait_until='networkidle')
                expect(page.get_by_text('Jawaban shell terverifikasi.',exact=True)).to_be_visible()
                page.goto(origin+f'/kilas-ai/agent?conversation={agent_id}',wait_until='networkidle')
                expect(page.locator('[data-job-id]')).to_be_visible()
                page.get_by_role('button',name='Jeda',exact=True).click()
                expect(page.locator('.auto-status').get_by_text('Dijeda',exact=True)).to_be_visible()
                page.get_by_role('button',name='Lanjutkan',exact=True).click()
                assert fixture.jobs.get(owner,job['id'])['status']=='PLANNING'
                page.get_by_role('button',name='Hentikan',exact=True).click()
                assert fixture.jobs.get(owner,job['id'])['status']=='STOPPED'
                assert not errors,errors
                context.close()
            browser.close()
    finally:server.shutdown()
    print('PASS: shared header/tabs/composer/drawer; X/backdrop/Escape; isolated histories/New Chat; task continuity/controls; attachment/Search presence; no overflow at 320/360/390/820/1440')


if __name__=='__main__':main()
