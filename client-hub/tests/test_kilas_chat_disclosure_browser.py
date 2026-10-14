"""Sidebar-only disclosure on real local routes; synthetic data and providers."""
import json
import logging
import os
import shutil
import sys
import threading
from pathlib import Path
from unittest.mock import patch


def loopback_only(event,args):
    if event=='socket.connect' and isinstance(args[1],tuple) and args[1][0] not in ('127.0.0.1','::1','localhost'):
        raise AssertionError('External network forbidden in sidebar QA')
    if event=='socket.getaddrinfo' and args[0] not in ('127.0.0.1','::1','localhost',None):
        raise AssertionError('External DNS forbidden in sidebar QA')


sys.addaudithook(loopback_only)

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_home as fixture
from kilas_ai import agent_store, providers, store
from kilas_chat_sidebar_browser_helpers import open_chat_sidebar


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case=fixture.HomeTests('test_old_routes_still_render');case.id=lambda:'chat-disclosure-browser';case.setUp()
    database=fixture.fixture.base.f.fixture.db
    for index in range(4):
        ident=agent_store.new_conversation(case.owner)
        database.execute('UPDATE kilas_ai_conversations SET title=? WHERE id=? AND user_id=?',
                         ('Conversation history is my saved title' if index==0 else 'Saved chat '+str(index),ident,case.owner))
    thread=store.create_thread(case.owner);store.rename_thread(case.owner,thread,'Saved thread <script>')
    app=fixture.fixture.base.f.fixture.app.app
    server=make_server('127.0.0.1',0,app,threaded=True);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_DISCLOSURE_SCREENSHOTS','/tmp/kilas-chat-disclosure'));output.mkdir(parents=True,exist_ok=True)
    results=[]
    try:
        with patch.object(providers,'stream',side_effect=lambda *a,**k:fixture.fixture.answer('Synthetic saved answer.')),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox','--disable-background-networking'])
            cookie=case.client().get_cookie('session')
            for width,height in ((320,683),(390,844),(820,1024),(945,2048),(1440,900)):
                context=browser.new_context(viewport={'width':width,'height':height},has_touch=width<=945,reduced_motion='reduce')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
                page=context.new_page();errors=[];requests=[];dialogs=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('request',lambda request:requests.append((request.method,request.url)))
                page.on('dialog',lambda dialog:(dialogs.append(dialog.type),dialog.dismiss()))
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                for agent in (False,True):
                    page.goto(origin+('/kilas-ai/agent?conversation='+str(case.conversation) if agent else '/products/start'),wait_until='networkidle')
                    rail=open_chat_sidebar(page);toggle=rail.get_by_role('button',name='Chat',exact=True)
                    panel=rail.locator('[data-chat-history-content]');history=panel.locator('.ai-history');see_all=panel.get_by_role('link',name='See all',exact=True)
                    expect(toggle).to_have_attribute('aria-expanded','true');expect(toggle).to_have_attribute('aria-controls','kilas-chat-history')
                    expect(panel).to_be_visible();expect(see_all).to_have_attribute('href','/kilas-ai?attachments=1')
                    expect(rail.locator('h2')).to_have_count(1)
                    expect(rail.locator('a[href="/kilas-ai/agent?view=history"]')).to_have_count(0)
                    expect(rail.get_by_role('link',name='My Library',exact=True)).to_be_visible()
                    assert toggle.bounding_box()['height']>=44
                    snapshot=history.locator('a').evaluate_all('(es)=>es.map(e=>({href:e.getAttribute("href"),title:e.title,text:e.textContent,current:e.getAttribute("aria-current")}))')
                    assert snapshot and any(row['title']=='Saved thread <script>' for row in snapshot)
                    field=page.locator('#agent-message' if agent else '#ai-input');field.fill('An unsent synthetic draft.')
                    posts=len([request for request in requests if request[0]=='POST']);url=page.url
                    (toggle.tap if width<=945 else toggle.click)()
                    expect(toggle).to_have_attribute('aria-expanded','false');expect(panel).to_be_hidden()
                    assert panel.evaluate('e=>getComputedStyle(e).display')=='none'
                    assert panel.locator('a').evaluate_all('(es)=>es.every(e=>e.getClientRects().length===0)')
                    toggle.focus()
                    for _ in range(10):
                        page.keyboard.press('Tab')
                        assert not panel.evaluate('e=>e.contains(document.activeElement)')
                    history.locator('a').first.evaluate('e=>e.focus()')
                    assert not panel.evaluate('e=>e.contains(document.activeElement)')
                    toggle.focus();page.keyboard.press('Enter')
                    expect(toggle).to_have_attribute('aria-expanded','true');expect(see_all).to_be_visible();expect(toggle).to_be_focused()
                    assert toggle.evaluate('e=>getComputedStyle(e).outlineStyle')!='none'
                    page.keyboard.press('Space')
                    expect(toggle).to_have_attribute('aria-expanded','false');expect(panel).to_be_hidden()
                    page.screenshot(path=str(output/f'{"agent" if agent else "home"}-collapsed-{width}.png'))
                    for _ in range(4):
                        (toggle.tap if width<=945 else toggle.click)()
                    expect(toggle).to_have_attribute('aria-expanded','false')
                    toggle.click();expect(toggle).to_have_attribute('aria-expanded','true');expect(panel).to_be_visible()
                    assert history.locator('a').evaluate_all('(es)=>es.map(e=>({href:e.getAttribute("href"),title:e.title,text:e.textContent,current:e.getAttribute("aria-current")}))')==snapshot
                    assert page.url==url and len([request for request in requests if request[0]=='POST'])==posts and not dialogs
                    expect(field).to_have_value('An unsent synthetic draft.')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(output/f'{"agent" if agent else "home"}-expanded-{width}.png'))
                    field.fill('')
                    old=database.query_all('SELECT id,title FROM kilas_ai_conversations WHERE user_id=? ORDER BY id',(case.owner,))
                    before_threads=len(store.list_threads(case.owner))
                    rail.locator('.ai-new').click();page.wait_for_load_state('networkidle')
                    expect(page.get_by_role('heading',name='How can I Help you?',exact=True)).to_be_visible()
                    new=database.query_all('SELECT id,title FROM kilas_ai_conversations WHERE user_id=? ORDER BY id',(case.owner,))
                    assert len(new)==len(old)+int(agent)
                    assert [(row['id'],row['title']) for row in new if row['id'] in {item['id'] for item in old}]==[(row['id'],row['title']) for row in old]
                    assert len(store.list_threads(case.owner))==before_threads
                    rail=open_chat_sidebar(page)
                    expect(rail.get_by_role('button',name='Chat',exact=True)).to_have_attribute('aria-expanded','true')
                    target=rail.locator('.ai-history a[href="/kilas-ai/threads/'+str(thread)+'"]')
                    expect(target).to_have_attribute('title','Saved thread <script>');target.click();page.wait_for_load_state('networkidle')
                    assert page.url==origin+'/kilas-ai/threads/'+str(thread)
                    rail=open_chat_sidebar(page)
                    expect(rail.locator('.ai-history a[aria-current=page]')).to_have_attribute('href','/kilas-ai/threads/'+str(thread))
                    rail.get_by_role('link',name='See all',exact=True).click();page.wait_for_load_state('networkidle')
                    assert ('GET',origin+'/kilas-ai?attachments=1') in requests
                    assert page.url.startswith(origin+'/kilas-ai')
                    assert not errors,errors
                    results.append({'width':width,'height':height,'shell':'agent' if agent else 'home','disclosure_keyboard_touch_hidden_focus_history_new_chat_navigation':'PASS'})
                context.close()
            browser.close()
        report={'result':'PASS','cases':results,'paid_calls':0,'production_mutations':0,'reference':'parent-inspected screenshot; cloud materialization unavailable'}
        (output/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:
        server.shutdown();worker.join(3);case.doCleanups()


if __name__=='__main__':main()
