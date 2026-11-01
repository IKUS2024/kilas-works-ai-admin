"""Actual UI plus mocked Chat. Loopback only, never a production account."""
import io,json,logging,os,sys,threading
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_chat_models as fixture
from kilas_ai import providers,store
import app,db,security

def loopback_only(event,args):
    if event=='socket.connect' and isinstance(args[1],tuple) and args[1][0] not in ('127.0.0.1','::1','localhost'):
        raise AssertionError('External transport forbidden')
sys.addaudithook(loopback_only)


def main():
    out=Path(os.environ.get('KILAS_CHAT_HARDENING_ARTIFACTS','/tmp/kilas-chat-hardening-browser'));out.mkdir(parents=True,exist_ok=True)
    case=fixture.RouteTests();case.id=lambda:'hardening-browser';case.setUp()
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server=make_server('127.0.0.1',0,app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    password='Synthetic-local-login-20261101'
    db.execute('UPDATE users SET password_hash=? WHERE id=?',(security.hash_password(password),case.owner))
    email=db.query_one('SELECT email FROM users WHERE id=?',(case.owner,))['email']
    cookie=case.client(case.owner).get_cookie('session');calls=[];report=[]
    def answer(mode,messages,**kwargs):
        calls.append(1)
        yield from fixture.answer(mode,messages,**kwargs)
    try:
        with patch.object(providers,'stream',side_effect=answer),sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            for width,height in ((360,740),(393,852),(820,1180),(1440,900)):
                ctx=browser.new_context(viewport={'width':width,'height':height},has_touch=width<900)
                ctx.add_cookies([{'name':'session','value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
                page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                page.goto(origin+'/products/start',wait_until='networkidle')
                assert page.locator('#copilot').count()==0
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(out/f'idle-{width}.png'),animations='disabled')
                if width==393:
                    for locale,label in [('id','Periksa jawaban AI.'),('en','Check AI answers.'),('es','Revisa las respuestas de la IA.'),('zh','请核对 AI 的回答。')]:
                        ctx.add_cookies([{'name':'kilas_language','value':locale,'url':origin}]);page.reload(wait_until='networkidle')
                        expect(page.locator('.ai-hint')).to_have_text(label)
                        page.screenshot(path=str(out/f'idle-{locale}-393.png'),animations='disabled')
                    ctx.add_cookies([{'name':'kilas_language','value':'en','url':origin}])
                    page.goto(origin+f'/kilas-ai/threads/{case.thread}',wait_until='networkidle')
                    field=page.locator('#ai-input');send=page.locator('#ai-send');routeurl=f'**/threads/{case.thread}/send'
                    def lose(route):route.fetch();route.abort('failed')
                    for scenario in ('text','photo'):
                        before=len(calls);rows=len(store.messages(case.owner,case.thread))
                        if scenario=='photo':
                            image=io.BytesIO();Image.new('RGB',(12,8),'orange').save(image,'PNG')
                            page.locator('#ai-files').set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':image.getvalue()})
                        page.route(routeurl,lose);field.fill('Jelaskan konsep API '+scenario+'.');send.click();expect(send).to_be_enabled(timeout=15000)
                        expect(field).not_to_have_value('');assert len(calls)==before+1
                        page.unroute(routeurl,lose);send.click();expect(send).to_be_enabled(timeout=15000);expect(field).to_have_value('')
                        assert len(calls)==before+1,(scenario,calls)
                        assert len(store.messages(case.owner,case.thread))==rows+2
                    page.screenshot(path=str(out/'result-393.png'),animations='disabled')
                    # Browser denies oversize before sending; draft remains editable.
                    page.locator('#ai-files').set_input_files({'name':'large.jpg','mimeType':'image/jpeg','buffer':b'x'*(9*1024**2)})
                    expect(page.locator('#ai-notice')).to_contain_text('8 MB')
                    assert page.locator('#ai-pending').inner_text()==''
                    # Expired cookie and a subsequent explicit sign-in in another tab.
                    ctx.clear_cookies(name='session');field.fill('Keep this draft for login.');send.click();expect(send).to_be_enabled(timeout=15000)
                    expect(page.locator('#ai-notice a[href="/login"]')).to_be_visible()
                    expect(field).to_have_value('Keep this draft for login.')
                    # Finish the anonymous HTTP response before simulating the
                    # next login response's cookie (do not race cookie writes).
                    page.wait_for_load_state('networkidle')
                    link=page.locator('#ai-notice a[href="/login"]')
                    assert link.get_attribute('target')=='_blank' and 'noopener' in link.get_attribute('rel')
                    assert link.evaluate('e=>e.getBoundingClientRect().height')>=44
                    page.evaluate("""()=>{window.__loginClicks=[];for(const name of ['pointerdown','mousedown','mouseup','click'])document.addEventListener(name,event=>{const a=document.querySelector('#ai-notice a'),r=a?.getBoundingClientRect();const item={type:name,tag:event.target.tagName,href:event.target.closest('a')?.getAttribute('href'),trusted:event.isTrusted,point:[event.clientX,event.clientY],link:r?[r.x,r.y,r.width,r.height]:null,active:document.activeElement?.id};window.__loginClicks.push(item);setTimeout(()=>item.prevented=event.defaultPrevented,0);},true)}""")
                    dialogs=[]
                    def dialog_seen(dialog):
                        dialogs.append({'type':dialog.type,'message':dialog.message});dialog.dismiss()
                    page.on('dialog',dialog_seen)
                    try:
                        with ctx.expect_page(timeout=10000) as popup:
                            page.locator('#ai-notice a[href="/login"]').click()
                        login=popup.value
                    except Exception:
                        diagnostic={'url':page.url,'pages':[p.url for p in ctx.pages],
                            'link':page.locator('#ai-notice').inner_html(),'dialogs':dialogs,
                            'draft_retained':field.input_value()=='Keep this draft for login.','clicks':page.evaluate('window.__loginClicks')}
                        (out/'login-diagnostic.json').write_text(json.dumps(diagnostic,indent=2))
                        print('LOGIN_DIAGNOSTIC',json.dumps(diagnostic),flush=True)
                        page.screenshot(path=str(out/'login-failure-393.png'))
                        raise
                    assert not dialogs,dialogs
                    page.remove_listener('dialog',dialog_seen)
                    login.wait_for_load_state('networkidle')
                    assert login.evaluate('window.opener===null')
                    login.locator('input[name="email"]').fill(email)
                    login.locator('input[name="password"]').fill(password)
                    login.locator('button.auth-submit').click()
                    login.wait_for_url(lambda url:'/login' not in url,timeout=15000)
                    login.wait_for_load_state('networkidle');login.close()
                    before=len(calls);send.click();expect(send).to_be_enabled(timeout=15000);
                    expect(field).to_have_value('');assert len(calls)==before+1
                    # Accepted HTTP + interrupted durable SSE with an attachment:
                    # preserve both draft and file, then replay the same operation.
                    page.goto(origin+f'/kilas-ai/agent?conversation={case.conversation}',wait_until='networkidle')
                    agent=page.locator('#agent-message');agent_send=page.locator('#agent-chat-form button[type=submit]')
                    page.locator('#work-source-files').set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':image.getvalue()})
                    expect(page.locator('#work-pending-files .chat-upload-policy')).to_contain_text('documents 2 MiB')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(out/'upload-policy-393.png'),animations='disabled')
                    before=len(calls)
                    def interrupt(route):
                        response=route.fetch()
                        frames=[frame for frame in response.body().split(b'\n\n') if b'"type": "done"' not in frame and b'"type":"done"' not in frame]
                        route.fulfill(response=response,body=b'\n\n'.join(frames))
                    def disconnect(route):route.abort('failed')
                    page.route('**/agent/chat',interrupt);page.route('**/work/streams/*',disconnect)
                    agent.fill('Explain this attachment after interruption.');agent_send.click();expect(agent_send).to_be_enabled(timeout=20000)
                    expect(agent).to_have_value('Explain this attachment after interruption.')
                    assert page.locator('#work-source-files').evaluate('e=>e.files.length')==1
                    assert len(calls)==before+1
                    page.unroute('**/agent/chat',interrupt);page.unroute('**/work/streams/*',disconnect)
                    agent_send.click();expect(agent_send).to_be_enabled(timeout=20000);expect(agent).to_have_value('')
                    assert len(calls)==before+1
                    # Return to the legacy view to check shared Chat contrast.
                    page.goto(origin+f'/kilas-ai/threads/{case.thread}',wait_until='networkidle')
                    # Computed color checks against actual active and hint backgrounds.
                    colors=page.evaluate("""()=>['.home-task-choices [aria-pressed=true],.home-task-choices [aria-current=page]','.ai-hint'].map(s=>{const e=document.querySelector(s);return {selector:s,color:getComputedStyle(e).color}})""")
                    assert colors[0]['color']=='rgb(173, 61, 0)',colors
                    assert colors[1]['color']=='rgb(98, 106, 122)',colors
                    page.evaluate('document.documentElement.style.zoom=2');assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    report.append({'legacy_text_and_photo_uncertain_retry_dispatch_once':True,'expired_session_draft_and_login_recovery':True,'accepted_agent_stream_retains_draft_file_and_replays_once':True,'file_oversize_rejected_client':True,'four_locales':True,'contrast_colors':colors,'zoom200':True})
                assert not errors,errors
                report.append({'width':width,'overflow':False,'page_errors':0});ctx.close()
            browser.close()
    finally:server.shutdown();case.doCleanups()
    (out/'results.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

if __name__=='__main__':main()
