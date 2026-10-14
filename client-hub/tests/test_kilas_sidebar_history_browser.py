"""In-place full/recent owned history on real local routes; no paid providers."""
import json
import logging
import os
import shutil
import sys
import threading
from pathlib import Path


def loopback_only(event,args):
    if event=='socket.connect' and isinstance(args[1],tuple) and args[1][0] not in ('127.0.0.1','::1','localhost'):
        raise AssertionError('External network forbidden in history QA')
    if event=='socket.getaddrinfo' and args[0] not in ('127.0.0.1','::1','localhost',None):
        raise AssertionError('External DNS forbidden in history QA')


sys.addaudithook(loopback_only)

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_home as fixture
from kilas_ai import agent_store, store
from kilas_chat_sidebar_browser_helpers import open_chat_sidebar


def snapshot(listing):
    return listing.locator('a').evaluate_all('(es)=>es.map(e=>({href:e.getAttribute("href"),title:e.title,text:e.textContent,current:e.getAttribute("aria-current")}))')


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case=fixture.HomeTests('test_old_routes_still_render');case.id=lambda:'history-browser';case.setUp()
    database=fixture.fixture.base.f.fixture.db
    agents=[case.conversation]+[agent_store.new_conversation(case.owner) for _ in range(44)]
    legacy=[store.create_thread(case.owner) for _ in range(106)]
    store.append_user_once(case.owner,legacy[0],'Saved synthetic conversation.','SMART','history-synthetic-message')
    agent_store.append(case.owner,'user','Saved synthetic conversation.',agents[0])
    for table,ids in (('kilas_ai_conversations',agents),('kilas_ai_threads',legacy)):
        for ident in ids:database.execute(f'UPDATE {table} SET title=?,updated_at=? WHERE id=?',('Owned <script> '+str(ident),'2026-10-14T04:00:00+00:00',ident))
    agent_store.new_conversation(case.other);store.rename_thread(case.other,store.create_thread(case.other),'Foreign private history')
    archived=agent_store.new_conversation(case.owner);database.execute('UPDATE kilas_ai_conversations SET archived_at=? WHERE id=?',('2026-10-14T04:00:00+00:00',archived))
    hidden=store.create_thread(case.owner);store.append_user_once(case.owner,hidden,'Hidden synthetic attachment.','SMART','agent-attachments:history-private')
    expected=['/kilas-ai/agent?conversation='+str(ident) for ident in reversed(agents)]+['/kilas-ai/threads/'+str(ident) for ident in reversed(legacy)]
    app=fixture.fixture.base.f.fixture.app.app
    server=make_server('127.0.0.1',0,app,threaded=True);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_HISTORY_SCREENSHOTS','/tmp/kilas-history-in-place'));output.mkdir(parents=True,exist_ok=True)
    results=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox','--disable-background-networking'])
            cookie=case.client().get_cookie('session')
            for width,height in ((390,844),(820,1024),(1440,900)):
                context=browser.new_context(viewport={'width':width,'height':height},has_touch=width<=820,reduced_motion='reduce')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
                page=context.new_page();documents=[];posts=[];errors=[];dialogs=[]
                page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else posts.append(request.url) if request.method=='POST' else None)
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('dialog',lambda dialog:(dialogs.append(dialog.type),dialog.dismiss()))
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                for agent in (False,True):
                    page.goto(origin+('/kilas-ai/agent?conversation='+str(agents[0]) if agent else '/kilas-ai/threads/'+str(legacy[0])),wait_until='networkidle')
                    field=page.locator('#agent-message' if agent else '#ai-input');field.fill('Unsent current draft.\nKeep every line.')
                    page.locator('#work-source-files' if agent else '#ai-files').set_input_files({'name':'unsent-note.txt','mimeType':'text/plain','buffer':b'Pending synthetic file.'})
                    pending=page.locator('#work-pending-files' if agent else '#ai-pending');expect(pending).to_contain_text('unsent-note.txt')
                    rail=open_chat_sidebar(page);listing=rail.locator('.ai-history');toggle=rail.locator('[data-chat-history-expand]');section=rail.get_by_role('button',name='Chat',exact=True)
                    recent=snapshot(listing);url=page.url;document_count=len(documents);post_count=len(posts)
                    page.evaluate('window.historyIdentity=crypto.randomUUID()');identity=page.evaluate('historyIdentity')
                    expect(toggle).to_have_text('See all');expect(toggle).to_have_attribute('aria-expanded','false')
                    (toggle.tap if width<=820 else toggle.click)()
                    expect(toggle).to_have_text('See less');expect(toggle).to_have_attribute('aria-expanded','true')
                    expect(listing).to_have_attribute('aria-busy','false')
                    more=rail.locator('[data-chat-history-more]')
                    pages=1
                    while more.is_visible():
                        before=listing.locator('a').count();more.click();expect(listing).to_have_attribute('aria-busy','false')
                        assert listing.locator('a').count()>before;pages+=1;assert pages<20
                    full=snapshot(listing)
                    assert [row['href'] for row in full]==expected,(width,agent,len(full))
                    assert len(full)==151 and len({row['href'] for row in full})==151
                    assert all('<script>' in row['text'] and 'Foreign' not in row['text'] for row in full)
                    assert listing.locator('script').count()==0
                    current='/kilas-ai/agent?conversation='+str(agents[0]) if agent else '/kilas-ai/threads/'+str(legacy[0])
                    expect(listing.locator('a[aria-current=page]')).to_have_attribute('href',current)
                    assert listing.evaluate('e=>e.scrollHeight>e.clientHeight && getComputedStyle(e).overflowY==="auto"')
                    expect(listing.locator('a').last).to_be_visible();listing.locator('a').last.scroll_into_view_if_needed()
                    page.screenshot(path=str(output/f'{"agent" if agent else "legacy"}-all-{width}.png'))
                    for _ in range(3):
                        toggle.focus();page.keyboard.press('Space');expect(toggle).to_have_text('See all');expect(toggle).to_have_attribute('aria-expanded','false')
                        assert snapshot(listing)==recent
                        expect(field).to_have_value('Unsent current draft.\nKeep every line.');expect(pending).to_contain_text('unsent-note.txt')
                        page.keyboard.press('Enter');expect(toggle).to_have_text('See less');expect(toggle).to_have_attribute('aria-expanded','true')
                        assert [row['href'] for row in snapshot(listing)]==expected
                    if width==390 and not agent:
                        # Agent refresh hands this component a detached DOMParser document.
                        page.evaluate("""()=>{const nodes=[...document.querySelector('.ai-history').querySelectorAll('a')].slice(0,6);
                          const doc=new DOMParser().parseFromString('<nav>'+nodes.map(n=>n.outerHTML).join('')+'</nav>','text/html');
                          const first=doc.querySelector('a');first.textContent='Updated <script> history title';first.title=first.textContent;
                          KilasChatHistory.replaceRecent(doc.querySelector('nav'));}""")
                        expect(listing.locator('a').first).to_have_text('Updated <script> history title')
                        expect(toggle).to_have_text('See less')
                        toggle.click();expect(toggle).to_have_text('See all');recent=snapshot(listing)
                        expect(listing.locator('a').first).to_have_text('Updated <script> history title')
                        toggle.click();expect(listing).to_have_attribute('aria-busy','false')
                        while more.is_visible():more.click();expect(listing).to_have_attribute('aria-busy','false')
                        assert [row['href'] for row in snapshot(listing)]==expected
                    section.click();expect(rail.locator('[data-chat-history-content]')).to_be_hidden();expect(section).to_have_attribute('aria-expanded','false')
                    assert not listing.evaluate('e=>e.contains(document.activeElement)')
                    section.click();expect(toggle).to_have_text('See less');expect(section).to_have_attribute('aria-expanded','true')
                    # A late first-page response cannot replace recent mode after See less.
                    if width==390 and not agent:
                        toggle.click();expect(toggle).to_have_text('See all')
                        page.evaluate('KilasChatHistory.replaceRecent(document.querySelector(".ai-history"))')
                        held=[];page.route('**/sidebar/history*',lambda route:held.append(route))
                        toggle.click();expect(toggle).to_have_text('See less');page.wait_for_function('document.querySelector(".ai-history").getAttribute("aria-busy")==="true"')
                        self_wait=0
                        while not held and self_wait<20:page.wait_for_timeout(25);self_wait+=1
                        assert held
                        toggle.click();expect(toggle).to_have_text('See all')
                        held[0].fulfill(status=200,content_type='application/json',body=json.dumps({'items':[],'next_cursor':None}))
                        page.wait_for_timeout(150);assert snapshot(listing)==recent
                        page.unroute('**/sidebar/history*')
                        # Failed reads are explicit and retry only the read in place.
                        page.route('**/sidebar/history*',lambda route:route.fulfill(status=503,content_type='application/json',body='{}'))
                        toggle.click();expect(rail.locator('[data-chat-history-status]')).to_contain_text('could not be loaded')
                        expect(more).to_be_enabled();expect(more).to_have_text('Try again')
                        toggle.click();expect(toggle).to_have_text('See all');assert snapshot(listing)==recent
                        page.unroute('**/sidebar/history*')
                    assert page.url==url and len(documents)==document_count and page.evaluate('historyIdentity')==identity
                    assert len(posts)==post_count and not dialogs and not errors,(posts,dialogs,errors)
                    expect(field).to_have_value('Unsent current draft.\nKeep every line.');expect(pending).to_contain_text('unsent-note.txt')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    results.append({'width':width,'shell':'agent' if agent else 'legacy','all_records':151,'pages':pages,'in_place_draft_selection_less_collapse_keyboard_touch':'PASS'})
                    # Explicit test navigation follows the draft-preservation assertions.
                    if width<761:rail.locator('[data-premium-close]').click()
                    field.fill('');pending.locator('button').click();expect(pending).to_be_empty()
                context.close()
            browser.close()
        report={'result':'PASS','cases':results,'paid_calls':0,'production_mutations':0,'physical_device':False}
        (output/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:server.shutdown();worker.join(3);case.doCleanups()


if __name__=='__main__':main()
