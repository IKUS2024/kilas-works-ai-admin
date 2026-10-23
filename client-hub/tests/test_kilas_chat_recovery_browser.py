"""Real composer recovery with synthetic providers; loopback traffic only."""
import json
import logging
import os
from pathlib import Path
import sys
import threading
from unittest.mock import patch

def loopback_only(event,args):
    if event=='socket.connect' and isinstance(args[1],tuple) and args[1][0] not in ('127.0.0.1','::1','localhost'):
        raise AssertionError('External transport forbidden')
sys.addaudithook(loopback_only)
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_chat_models as fixture
from kilas_ai import providers,agent_store,workspace_streams
import app,db


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case=fixture.RouteTests('test_catalog_auth_csrf_and_owner_isolation');case.id=lambda:'recovery-browser';case.setUp()
    server=make_server('127.0.0.1',0,app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    calls={};release=threading.Event();report=[]
    def answer(mode,messages,**kwargs):
        text=messages[-1]['content'];text=text if isinstance(text,str) else text[0]['text']
        calls[text]=calls.get(text,0)+1
        yield {'type':'provider','provider':'openai','model':'gpt-6.1-sol'}
        if text.startswith('FAIL') and calls[text]==1:raise providers.ProviderError('synthetic_failure')
        yield {'type':'delta','text':'Synthetic answer '+text}
        if text.startswith('CANCEL'):release.wait(5)
        yield {'type':'usage','input_tokens':100,'output_tokens':10}
        yield {'type':'finish','reason':'stop'}
    try:
        with patch.object(providers,'stream',side_effect=answer),sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            cookie=case.client().get_cookie('session')
            for width in (390,1440):
                conversation=agent_store.new_conversation(case.owner)
                context=browser.new_context(viewport={'width':width,'height':900},has_touch=width==390)
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page=context.new_page();errors=[];sent=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('request',lambda request:sent.append(request.post_data) if '/agent/chat' in request.url and request.method=='POST' else None)
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                page.goto(origin+f'/kilas-ai/agent?conversation={conversation}',wait_until='networkidle')
                field=page.locator('#agent-message');send=page.locator('#agent-chat-form button[type=submit]')
                # Provider failure is terminal; retrying the same prompt gets a new operation.
                prompt='FAIL '+str(width);field.fill(prompt);send.click();expect(send).to_be_enabled(timeout=15000)
                first=page.locator('[name=operation_key]').input_value()
                field.fill(prompt);send.click();expect(send).to_be_enabled(timeout=15000);expect(field).to_have_value('')
                assert calls[prompt]==2
                assert page.locator('[name=operation_key]').input_value()!=first
                # Lose the HTTP response after the real server has processed it. Retry replays;
                # it must not dispatch or reserve a second paid operation.
                prompt='UNCERTAIN '+str(width)
                def lose(route):route.fetch();route.abort('failed')
                page.route('**/agent/chat',lose);field.fill(prompt);send.click();expect(send).to_be_enabled(timeout=15000)
                expect(field).to_have_value(prompt);uncertain_key=page.locator('[name=operation_key]').input_value()
                page.unroute('**/agent/chat',lose);send.click();expect(send).to_be_enabled(timeout=15000);expect(field).to_have_value('')
                assert calls[prompt]==1
                assert page.locator('[name=operation_key]').input_value()!=uncertain_key
                # Real multipart File objects must also preserve the uncertain retry key.
                from PIL import Image
                import io
                png=io.BytesIO();Image.new('RGB',(12,8),'green').save(png,'PNG')
                prompt='UNCERTAIN UPLOAD '+str(width)
                page.locator('#work-source-files').set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':png.getvalue()})
                page.route('**/agent/chat',lose);field.fill(prompt);send.click();expect(send).to_be_enabled(timeout=15000)
                expect(field).to_have_value(prompt);page.unroute('**/agent/chat',lose)
                send.click();expect(send).to_be_enabled(timeout=15000);expect(field).to_have_value('')
                assert calls[prompt]==1
                # Explicit cancellation and then a new message; no reload required.
                release.clear();prompt='CANCEL '+str(width);field.fill(prompt);send.click()
                expect(page.locator('.agent-message-assistant').last).to_contain_text('Synthetic answer '+prompt,timeout=10000)
                page.locator('[data-unified-stop]').click();release.set();expect(send).to_be_enabled(timeout=15000)
                for _ in range(100):
                    active=db.query_one("SELECT id FROM kilas_workspace_streams WHERE user_id=? AND state='RUNNING'",(case.owner,))
                    if not active:break
                    threading.Event().wait(.02)
                field.fill('AFTER CANCEL '+str(width));send.click();expect(send).to_be_enabled(timeout=15000);expect(field).to_have_value('')
                assert calls['AFTER CANCEL '+str(width)]==1
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert not errors,errors
                report.append({'width':width,'terminal_failure_retry':True,'uncertain_response_replay_without_second_dispatch':True,'cancel_then_new_message':True,'page_errors':0})
                context.close()
            browser.close()
        print(json.dumps(report,indent=2))
    finally:release.set();server.shutdown();case.doCleanups()

if __name__=='__main__':main()
