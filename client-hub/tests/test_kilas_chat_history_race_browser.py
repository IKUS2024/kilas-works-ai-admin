"""Synthetic, loopback-only regression for history/stream races."""
import os, shutil, threading, time
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_home as fixture
from kilas_ai import agent_store, providers


def main():
    case=fixture.HomeTests('test_old_routes_still_render');case.id=lambda:'history-race';case.setUp()
    app=fixture.fixture.base.f.fixture.app.app
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    def answer(*args,**kwargs):
        yield {'type':'delta','text':'Awal jawaban. '}
        time.sleep(2)
        yield {'type':'delta','text':'Akhir jawaban.'}
        yield {'type':'finish','reason':'stop'}
    try:
        with patch.object(providers,'stream',side_effect=answer),sync_playwright() as p:
            browser=p.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for race in ('discovery','poll'):
                owner=fixture.fixture.base.f.fixture.repo.create_user(f'history-race-{race}@example.test','hash')
                conversation=agent_store.new_conversation(owner)
                cookie=case.client(owner).get_cookie('session')
                ctx=browser.new_context(viewport={'width':390,'height':844})
                ctx.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                ctx.add_init_script("""(()=>{const original=window.fetch;window.__race=%s;window.fetch=async(...args)=>{
                  const url=String(args[0]);
                  if(window.__race==='discovery'&&url.includes('/work/streams?conversation_id=')){
                    window.__held=true;await new Promise(resolve=>window.__release=resolve);
                    return new Response(JSON.stringify({streams:[{id:999999}]}),{status:200,headers:{'content-type':'application/json'}});
                  }
                  if(window.__race==='poll'&&window.__holdPoll&&url.includes('/kilas-ai/agent?')){
                    const response=await original(...args);window.__held=true;
                    await new Promise(resolve=>window.__release=resolve);return response;
                  }
                  return original(...args);
                };})();""" % repr(race))
                page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                page.goto(origin+f'/kilas-ai/agent?conversation={conversation}',wait_until='domcontentloaded')
                if race=='poll':
                    page.wait_for_timeout(500);page.evaluate("window.__holdPoll=true;window.dispatchEvent(new Event('focus'))")
                page.wait_for_function('window.__held===true')
                field=page.locator('#agent-message');send=page.locator('#agent-chat-form button[type=submit]')
                field.fill('Pesan untuk memeriksa history');send.click()
                expect(page.locator('#agent-conversation')).to_contain_text('Awal jawaban.',timeout=20000)
                page.evaluate('window.__release()')
                page.wait_for_timeout(300)
                assert send.is_disabled(),race
                expect(page.locator('#agent-conversation')).to_contain_text('Akhir jawaban.',timeout=20000)
                expect(send).to_be_enabled(timeout=20000)
                expect(page.locator('#agent-conversation .agent-message-user')).to_have_count(1)
                expect(page.locator('#agent-conversation .agent-message-assistant')).to_have_count(1)
                assert not errors,errors
                page.reload(wait_until='networkidle')
                expect(page.locator('#agent-conversation')).to_contain_text('Awal jawaban. Akhir jawaban.')
                ctx.close()
            browser.close()
        print('History discovery and stale poll races: PASS')
    finally:
        server.shutdown();case.doCleanups()

if __name__=='__main__':main()
