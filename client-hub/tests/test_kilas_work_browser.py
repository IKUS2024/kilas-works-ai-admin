"""Finished Work artifacts, revision/new conversation and responsive controls."""
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
import test_kilas_work_documents as fixture
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server


def tick(job):
    for _ in range(2):
        if fixture.fixture.db.query_one('SELECT status FROM kilas_agent_jobs WHERE id=?',(job,))['status']=='COMPLETED':return
        fixture.fixture.db.execute('UPDATE kilas_agent_jobs SET next_wake_at=? WHERE id=?',(fixture.fixture.store.stamp(),job))
        fixture.fixture.runner.execute(*fixture.fixture.store.claim_due(1)[0])


def main():
    app=fixture.fixture.app.app
    app.config.update(TESTING=True,CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    try:
        with patch.object(fixture.content_worker,'text',return_value=(fixture.SOURCE,fixture.model_policy.LUNA,{})),sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            for width,height in ((320,780),(360,780),(390,844),(820,900),(1440,900)):
                owner=fixture.fixture.repo.create_user(f'work-browser-{width}@example.test','hash')
                conversation=fixture.agent_store.new_conversation(owner)
                client=app.test_client()
                with client.session_transaction() as state:state.update(user_id=owner,role='CLIENT_OWNER',agent_conversation_id=conversation,_csrf_token='browser-work')
                cookie=client.get_cookie('session')
                context=browser.new_context(viewport={'width':width,'height':height},has_touch=width<760,reduced_motion='reduce')
                context.add_init_script("""const nativeMatchMedia = window.matchMedia.bind(window); const desktopFocus = """ + ('true' if width>=760 else 'false') + """; window.matchMedia = query => query === '(hover: hover) and (pointer: fine)' ? {matches: desktopFocus, media: query, onchange: null, addListener(){}, removeListener(){}, addEventListener(){}, removeEventListener(){}, dispatchEvent(){return false;}} : nativeMatchMedia(query);""")
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page=context.new_page();errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(origin+f'/kilas-ai/agent?conversation={conversation}',wait_until='networkidle')
                assert page.locator('.ai-mode-tabs').count()==0
                expect(page.get_by_role('heading',name='Apa yang ingin kamu lakukan?')).to_be_visible()
                page.locator('#agent-message').fill(fixture.REQUEST)
                page.get_by_role('button',name='Kirim',exact=True).click()
                expect(page.locator('[data-job-id]')).to_have_count(1)
                assert page.evaluate("document.activeElement.id === 'agent-message'") is (width>=760),(width,'work composer focus after response')
                job=fixture.fixture.store.list_jobs(owner)[0]['id'];expect(page.locator('.work-file')).to_have_count(1,timeout=15000)
                page.reload(wait_until='networkidle')
                card=page.locator('.work-file')
                expect(card.get_by_text('proposal-kerja-sama.pdf',exact=True)).to_be_visible()
                for action in ('Buka','Download'):
                    link=card.get_by_role('link',name=action,exact=True)
                    assert link.bounding_box()['height']>=44,(width,action)
                    response=context.request.get(origin+link.get_attribute('href'))
                    assert response.status==200 and response.body().startswith(b'%PDF')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,'conversation')
                page.screenshot(path=str(Path(tempfile.gettempdir())/f'kilas-work-chat-{width}.png'),full_page=True)
                page.goto(origin+f'/kilas-ai/agent/jobs/{job}',wait_until='networkidle')
                assert page.locator('.work-file').evaluate('(el)=>el.compareDocumentPosition(document.querySelector(".agent-work-detail")) & Node.DOCUMENT_POSITION_FOLLOWING')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,'detail')
                page.screenshot(path=str(Path(tempfile.gettempdir())/f'kilas-work-detail-{width}.png'),full_page=True)
                page.goto(origin+f'/kilas-ai/agent?conversation={conversation}',wait_until='networkidle')
                expect(page.locator(f'[data-job-id="{job}"]')).to_have_count(1)
                expect(page.locator('.work-file')).to_have_count(1)
                original_order=page.locator('#agent-conversation > article').evaluate_all('(els)=>els.map(e=>e.dataset.jobId || e.textContent.trim())')
                page.locator('#agent-message').fill('Bikin lebih premium dan tambahkan timeline.')
                page.get_by_role('button',name='Kirim',exact=True).click()
                expect(page.locator(f'[data-job-id="{job}"]')).to_have_count(1)
                latest=fixture.fixture.store.list_jobs(owner)[0]['id'];expect(page.locator('.work-file')).to_have_count(2,timeout=15000)
                page.reload(wait_until='networkidle');expect(page.locator('.work-file')).to_have_count(2)
                current_order=page.locator('#agent-conversation > article').evaluate_all('(els)=>els.map(e=>e.dataset.jobId || e.textContent.trim())')
                assert current_order[:len(original_order)]==original_order,(width,'old result moved')
                expect(page.locator(f'[data-job-id="{job}"]')).to_have_count(1)
                page.goto(origin+'/kilas-ai/agent?view=history',wait_until='networkidle')
                expect(page.locator(f'[data-job-id="{job}"]')).to_have_count(1)
                expect(page.locator(f'[data-job-id="{latest}"]')).to_have_count(1)
                page.goto(origin+f'/kilas-ai/agent/jobs/{job}',wait_until='networkidle')
                expect(page.locator('.work-file')).to_have_count(1)
                page.goto(origin+f'/kilas-ai/agent?conversation={conversation}',wait_until='networkidle')
                active=fixture.fixture.store.create(owner,'Pantau perubahan harga sampai saya stop',conversation_id=conversation)
                page.reload(wait_until='networkidle')
                expect(page.locator(f'[data-job-id="{active}"]')).to_have_count(1)
                expect(page.locator('[data-active-count],[data-notification-count]')).to_have_count(0)
                expect(page.locator(f'[data-job-id="{job}"]')).to_have_count(1)
                if width<760:page.get_by_role('button',name='Buka riwayat').click()
                page.get_by_role('button',name='+ Chat baru',exact=True).click()
                expect(page.get_by_role('heading',name='Apa yang ingin kamu lakukan?')).to_be_visible()
                assert fixture.fixture.store.get(owner,active)['status']=='PLANNING'
                assert not errors,errors
                fixture.fixture.store.control(owner,active,'stop')
                context.close()
            browser.close()
    finally:server.shutdown()
    print('PASS: Work PDF/open/download/revision; result stays inline at its original position after navigation/new instruction/reload, retained in History/detail; background continuity; 320/360/390/820/1440')


if __name__=='__main__':main()
