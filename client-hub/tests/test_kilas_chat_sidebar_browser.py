"""Shared owned history, persisted attachments and draft-safe sidebar navigation."""
import json
import os
import shutil
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_home as fixture
from kilas_ai import providers,store,agent_store
from kilas_chat_sidebar_browser_helpers import open_chat_sidebar,click_new_chat


def main():
    case=fixture.HomeTests('test_old_routes_still_render');case.id=lambda:'sidebar-browser';case.setUp()
    app=fixture.fixture.base.f.fixture.app.app
    server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_SIDEBAR_SCREENSHOTS','/tmp/kilas-sidebar-review'));output.mkdir(parents=True,exist_ok=True)
    report={'provider':'mocked only','widths':[],'production_mutations':0}
    try:
        with patch.object(providers,'stream',side_effect=lambda *a,**k:fixture.fixture.answer('Jawaban tersimpan untuk sidebar.')),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            cookie=case.client().get_cookie('session')
            for width in (320,390,1440):
                context=browser.new_context(viewport={'width':width,'height':900},has_touch=width<761)
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page=context.new_page();errors=[];posts=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
                page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                for agent in (False,True):
                    page.goto(origin+('/kilas-ai/agent?conversation='+str(case.conversation) if agent else '/products/start'),wait_until='networkidle')
                    field=page.locator('#agent-message' if agent else '#ai-input');timeline=page.locator('#agent-conversation' if agent else '#ai-messages')
                    field.fill('Halo, draf belum dikirim '+str(width))
                    page.locator('#work-source-files' if agent else '#ai-files').set_input_files({'name':'sidebar-draft.txt','mimeType':'text/plain','buffer':b'Synthetic attachment kept intact.'})
                    pending=page.locator('#work-pending-files' if agent else '#ai-pending');expect(pending).to_contain_text('sidebar-draft.txt')
                    rail=open_chat_sidebar(page)
                    assert page.locator('.kilas-home-workspace .home-agent-new,.kilas-home-workspace .ai-new,.home-history').count()==0
                    assert rail.locator('.ai-new').count()==1
                    before=len(posts);url=page.url;draft=field.input_value()
                    for target in (rail.locator('.ai-new'),rail.locator('.ai-history a').first):
                        if not target.count():continue
                        page.once('dialog',lambda d:d.dismiss());target.click()
                        assert page.url==url and len(posts)==before
                        expect(field).to_have_value(draft);expect(pending).to_contain_text('sidebar-draft.txt')
                    if width<761:
                        for close in ('escape','button','backdrop'):
                            if close=='escape':page.keyboard.press('Escape')
                            elif close=='button':rail.locator('[data-premium-close]').click()
                            else:page.locator('.premium-backdrop').click(position={'x':width-3,'y':450})
                            expect(page.locator('[data-premium-menu]')).to_have_attribute('aria-expanded','false')
                            expect(field).to_have_value(draft);expect(pending).to_contain_text('sidebar-draft.txt');open_chat_sidebar(page)
                        rail.locator('[data-premium-close]').click()
                    send=page.locator('#agent-chat-form button[type=submit]' if agent else '#ai-send')
                    send.click();expect(send).to_be_enabled(timeout=20000);expect(field).to_have_value('')
                    expect(timeline).to_contain_text('Jawaban tersimpan untuk sidebar.');expect(pending).to_be_empty()
                    saved=page.url;rail=open_chat_sidebar(page);active=rail.locator('.ai-history a[aria-current=page]')
                    expect(active).to_have_count(1);expect(active).to_have_attribute('href',saved.removeprefix(origin));assert active.get_attribute('title')
                    page.screenshot(path=str(output/f'{"agent" if agent else "legacy"}-sidebar-{width}.png'))
                    page.reload(wait_until='networkidle');expect(timeline).to_contain_text('Jawaban tersimpan untuk sidebar.');expect(timeline).to_contain_text('sidebar-draft.txt')
                    before_threads=len(store.list_threads(case.owner));before_agent=len(agent_store.recent_conversations(case.owner))
                    click_new_chat(page,agent=agent);expect(page.get_by_text('How can I Help you?',exact=True)).to_be_visible()
                    assert len(store.list_threads(case.owner))==before_threads
                    assert len(agent_store.recent_conversations(case.owner))==before_agent+int(agent)
                    rail=open_chat_sidebar(page);link=rail.locator('.ai-history a[href="'+saved.removeprefix(origin)+'"]');expect(link).to_be_visible();link.click();page.wait_for_load_state('networkidle')
                    expect(timeline).to_contain_text('sidebar-draft.txt');assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                rail=open_chat_sidebar(page);rail.locator('.kilas-profile-menu>summary').click();rail.locator('.kilas-profile-options a').first.click();page.wait_for_load_state('networkidle');expect(open_chat_sidebar(page).locator('.ai-history')).not_to_be_empty()
                page.goto(origin+'/products/start',wait_until='networkidle');page.locator('#ai-input').fill('Naskah bawaan dari Home.')
                page.locator('[data-home-task=voiceover]').click();page.wait_for_load_state('networkidle')
                script=page.locator('#audio-script');expect(script).to_have_value('Naskah bawaan dari Home.')
                assert script.evaluate('e=>e.value===e.defaultValue')
                expect(page.locator('#premium-sidebar,[data-chat-sidebar]')).to_have_count(0)
                page.once('dialog',lambda d:d.dismiss());page.locator('[data-kilas-feature=chat]').click();expect(script).to_have_value('Naskah bawaan dari Home.')
                script.fill('Naskah belum dibuat.');page.once('dialog',lambda d:d.dismiss());page.locator('[data-kilas-feature=chat]').click();expect(script).to_have_value('Naskah belum dibuat.')
                assert not errors,errors
                report['widths'].append({'width':width,'legacy':'PASS','agent':'PASS','draft_files_drawer_cancel':'PASS','voice_draft_cancel':'PASS'});context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
