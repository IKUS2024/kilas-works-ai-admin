"""Real Chromium gestures/actions/layout using synthetic local conversations only."""
import json,logging,shutil,threading,os
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_history_actions as f
from kilas_ai import agent_store,store,chat_models,image_models
from kilas_chat_sidebar_browser_helpers import open_chat_sidebar
import db


def touch(page,session,node,move=False):
    node.scroll_into_view_if_needed();r=node.bounding_box();x=r['x']+min(70,r['width']/2);y=r['y']+r['height']/2
    session.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y}]})
    if move:session.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':x,'y':y+32}]})
    page.wait_for_timeout(650)
    session.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})


def empty_fit(page):
    timeline=page.locator('#agent-conversation') if page.locator('#agent-conversation').count() else page.locator('.ai-empty')
    result=timeline.evaluate('e=>({scroll:e.scrollHeight,client:e.clientHeight,overflow:getComputedStyle(e).overflowY})')
    if result['scroll']>result['client']+1:
        page.screenshot(path='/tmp/history-empty-failure.png')
        print(page.evaluate("[...document.querySelectorAll('.ai-main,.ai-empty,.agent-welcome,#agent-conversation,.kilas-new-chat-logo,h1,h3,.ai-composer-area,.home-tool-selector,.home-workspace-top,.wrap,.premium-home')].map(e=>({tag:e.tagName,c:e.className,h:e.clientHeight,sh:e.scrollHeight,box:e.getBoundingClientRect().toJSON(),flex:getComputedStyle(e).flex,height:getComputedStyle(e).height,min:getComputedStyle(e).minHeight,margin:getComputedStyle(e).margin,display:getComputedStyle(e).display}))"))
    assert result['scroll']<=result['client']+1,result
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth && document.documentElement.scrollHeight<=innerHeight+1 && scrollY===0')
    timeline.evaluate('e=>e.scrollTop=120');assert timeline.evaluate('e=>e.scrollTop')==0
    expect(page.locator('[data-ai-call-launch]')).to_be_in_viewport()
    expect(page.locator('#agent-message,#ai-input')).to_be_in_viewport()


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case=f.HistoryActionTests('test_empty_creation_draft_and_model_selection_never_enter_history');case.setUp()
    output=Path('/tmp/kilas-history-actions-browser');output.mkdir(exist_ok=True);rows=[]
    empty_agent=agent_store.new_conversation(case.owner);empty_thread=store.create_thread(case.owner)
    for i in range(28):
        agent_store.append(case.owner,'user' if i%2==0 else 'assistant','Synthetic populated discussion '+str(i)+'\n'+('Context retained. '*15),case.conversation)
        store.append_user_once(case.owner,case.thread,'Synthetic populated discussion '+str(i)+' '+('Retained content. '*15),'FAST','gesture_populated_'+str(i))
    for i in range(26):
        ident=agent_store.new_conversation(case.owner);agent_store.append(case.owner,'user','Synthetic older history '+str(i),ident)
        db.execute('UPDATE kilas_ai_agent_messages SET created_at=? WHERE conversation_id=?',('2026-10-10T10:'+str(i).zfill(2)+':00+00:00',ident))
    server=make_server('127.0.0.1',0,f.f.fixture.fixture.base.f.fixture.app.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    try:
        with patch.object(chat_models,'check',side_effect=f.f.available),patch.object(image_models,'check',side_effect=lambda m:{**image_models.spec(m),'available':True,'status':'verified'}),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in map(int,os.environ.get('KILAS_HISTORY_QA_WIDTHS','320,820,1440').split(',')):
                context=browser.new_context(viewport={'width':width,'height':900},has_touch=width<=820,reduced_motion='reduce')
                cookie=case.client().get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
                page=context.new_page();page.set_default_timeout(10000);errors=[];documents=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:documents.append(r.url) if r.resource_type=='document' else None)
                page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                cdp=context.new_cdp_session(page)
                for surface,path in [('home','/products/start'),('agent',f'/kilas-ai/agent?conversation={empty_agent}'),('legacy',f'/kilas-ai/threads/{empty_thread}')]:
                    page.goto(origin+path,wait_until='networkidle');empty_fit(page)
                    assert page.locator('.home-workspace-brand,.home-chat-heading,.agent-rename,[data-image-cost-disclosure]').count()==0
                    assert page.locator('[data-chat-sidebar] .ai-new').count()==1
                    assert page.locator(f'[data-chat-sidebar] a[href="/kilas-ai/agent?conversation={empty_agent}"], [data-chat-sidebar] a[href="/kilas-ai/threads/{empty_thread}"]').count()==0
                    if width==320:
                        page.locator('#agent-message,#ai-input').focus();page.set_viewport_size({'width':width,'height':360});page.wait_for_timeout(100);empty_fit(page);page.set_viewport_size({'width':width,'height':900});page.locator('#agent-message,#ai-input').blur()
                    if surface=='home':page.screenshot(path=str(output/f'empty-{width}.png'))
                    rows.append({'surface':surface,'width':width,'empty_no_scroll':'PASS','empty_history_hidden':'PASS','keyboard_fit':width==320})
                # Fresh owned action fixtures per width; never operate on production data.
                agent=agent_store.new_conversation(case.owner);agent_store.append(case.owner,'user','Current gesture fixture '+str(width)+'\n'+('Synthetic long content.\n'*60),agent)
                legacy=store.create_thread(case.owner);store.append_user_once(case.owner,legacy,'Deletion fixture '+str(width),'FAST','delete_fixture_'+str(width))
                page.goto(origin+f'/kilas-ai/agent?conversation={agent}',wait_until='networkidle')
                chat=page.locator('#agent-conversation');assert chat.evaluate('e=>e.scrollHeight>e.clientHeight');chat.evaluate('e=>e.scrollTop=100');assert chat.evaluate('e=>e.scrollTop')>0
                field=page.locator('#agent-message');field.fill('Unsent synthetic draft');model=page.evaluate('window.KilasChatModels.value()');url=page.url
                rail=open_chat_sidebar(page);link=rail.locator(f'.ai-history a[href="/kilas-ai/agent?conversation={agent}"]');count=len(documents)
                if width<=820:
                    touch(page,cdp,link,move=True);expect(page.locator('#chat-history-menu')).not_to_be_visible();assert page.url==url
                    touch(page,cdp,link)
                else:link.click(button='right')
                menu=page.locator('#chat-history-menu');expect(menu).to_be_visible();expect(menu.get_by_role('menuitem')).to_have_count(2);expect(menu).to_contain_text('Rename');expect(menu).to_contain_text('Delete');assert page.url==url and len(documents)==count
                page.screenshot(path=str(output/f'menu-{width}.png'))
                menu.get_by_role('menuitem',name='Rename',exact=True).click();rename=page.locator('[data-chat-rename-dialog]');expect(rename).to_be_visible();rename.locator('[name=title]').fill('Renamed synthetic '+str(width));rename.get_by_role('button',name='Save',exact=True).click();expect(rename).not_to_be_visible();expect(link).to_have_text('Renamed synthetic '+str(width));expect(field).to_have_value('Unsent synthetic draft');assert len(documents)==count and page.evaluate('window.KilasChatModels.value()')==model
                link.focus();page.keyboard.press('Shift+F10');expect(menu).to_be_visible();page.keyboard.press('ArrowDown');expect(menu.get_by_role('menuitem',name='Delete',exact=True)).to_be_focused();page.keyboard.press('Escape');expect(menu).not_to_be_visible();expect(link).to_be_focused()
                if width<=760:assert page.locator('#premium-sidebar').evaluate('e=>!e.inert')
                victim=rail.locator(f'.ai-history a[href="/kilas-ai/threads/{legacy}"]');victim.click(button='right');menu.get_by_role('menuitem',name='Delete',exact=True).click();confirm=page.locator('[data-chat-delete-dialog]');expect(confirm).to_be_visible();expect(confirm).to_contain_text('cannot be undone');confirm.get_by_role('button',name='Cancel',exact=True).click();expect(victim).to_be_visible();assert store.thread(case.owner,legacy)
                victim.click(button='right');menu.get_by_role('menuitem',name='Delete',exact=True).click();confirm.get_by_role('button',name='Delete',exact=True).click();expect(confirm).not_to_be_visible();expect(victim).to_have_count(0);assert store.thread(case.owner,legacy) is None;expect(field).to_have_value('Unsent synthetic draft');assert page.url==url
                # Dynamic paginated rows inherit the same keyboard context menu.
                rail.locator('[data-chat-history-expand]').click();expect(rail.locator('[data-chat-history-expand]')).to_have_text('See less');expect(rail.locator('.ai-history')).to_have_attribute('aria-busy','false');dynamic=rail.locator('.ai-history a').last;dynamic.scroll_into_view_if_needed();dynamic.focus();page.keyboard.press('Shift+F10');expect(menu).to_be_visible();page.keyboard.press('Escape')
                field.fill('');target=rail.locator('.ai-history a').last;target.scroll_into_view_if_needed();page.wait_for_timeout(120);href=target.get_attribute('href');(target.tap if width<=820 else target.click)();page.wait_for_url(origin+href,wait_until='networkidle');assert page.url==origin+href
                assert not errors,errors;assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                rows.append({'surface':'sidebar','width':width,'touch_or_right_click':'PASS','move_cancel':'PASS','keyboard':'PASS','rename_preserves_draft':'PASS','delete_confirmation':'PASS','synthetic_delete':'PASS','normal_tap':'PASS','paginated_menu':'PASS','populated_scroll':'PASS'})
                context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps({'checks':rows,'paid_inference':False,'production_mutations':False},indent=2));print(json.dumps(rows))
    finally:server.shutdown();case.doCleanups()

if __name__=='__main__':main()
