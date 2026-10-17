"""Critical code-first browser contracts; all inference is synthetic and blocked externally."""
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_workspace_runtime as fixture
from kilas_ai import providers,agent_store,workspace_model_tools


def main():
    server=make_server('127.0.0.1',0,fixture.application.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(tempfile.gettempdir())/'kilas-workspace-runtime-browser';output.mkdir(exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM','/usr/bin/chromium'),args=['--no-sandbox'])
            for width in map(int,os.environ.get('KILAS_QA_WIDTHS','320,768,1440').split(',')):
                case=fixture.WorkspaceTests();case.id=lambda:'workspace-browser-'+str(width);case.setUp()
                client=case.client();cookie=client.get_cookie('session');context=browser.new_context(viewport={'width':width,'height':900})
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}])
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(origin+'/kilas-ai/agent?conversation='+str(case.conversation));expect(page.locator('[name=selected_model]')).not_to_have_value('')
                dispatched=[];gate=threading.Event()
                def answer(mode,messages,**kwargs):
                    model=messages.selected_model;dispatched.append(model)
                    yield {'type':'provider','provider':'openai','model':model}
                    yield {'type':'model_metadata','requested_model':model,'returned_model':model,'provider':'openai'}
                    yield {'type':'delta','text':'A database index helps locate relevant rows. '}
                    gate.wait(5)
                    yield {'type':'delta','text':'Use indexes on columns that support frequent filters, and compare actual query plans before making changes.'}
                    yield {'type':'usage','input_tokens':100,'output_tokens':50}
                    yield {'type':'finish','reason':'stop'}
                with patch.object(providers,'stream',side_effect=answer):
                    page.locator('#agent-message').fill('Explain a database index')
                    page.locator('#agent-chat-form button[type=submit]').click()
                    expect(page.locator('#agent-thinking')).to_be_visible()
                    expect(page.locator('#agent-conversation')).to_contain_text('A database index helps')
                    page.reload();expect(page.locator('#agent-thinking')).to_be_visible();gate.set()
                    expect(page.locator('#agent-conversation')).to_contain_text('compare actual query plans',timeout=15000)
                    expect(page.locator('#agent-thinking')).to_be_hidden(timeout=15000)
                    assert dispatched==['gpt-6.1-sol'],dispatched
                # Multiple pending source inputs can be removed before submission.
                page.locator('#work-source-files').set_input_files([{'name':'one.py','mimeType':'text/x-python','buffer':b'print(1)'},{'name':'two.ts','mimeType':'text/plain','buffer':b'export const two=2;'}])
                expect(page.locator('.work-pending-file')).to_have_count(2)
                page.locator('.work-pending-file button').first.click();expect(page.locator('.work-pending-file')).to_have_count(1)
                page.locator('.work-pending-file button').click();expect(page.locator('.work-pending-file')).to_have_count(0)
                def project(model,history,instruction,**kwargs):
                    return {'calls':[{'id':'publish','name':'publish_project','arguments':{'files':[{'name':'README.md','content':'# Synthetic preview\nOpen index.html. Runtime tests have not been run.'},{'name':'index.html','content':'<!doctype html><html><title>Preview</title><style>body{font:18px sans-serif;margin:24px}</style><body><h1>Working preview</h1><button onclick="this.textContent=\'Clicked\'">Try it</button></body></html>'}]}}], 'usage':{'input_tokens':100,'output_tokens':100},'model_provenance':{'requested_model':model,'returned_model':model,'provider':'openai'}}
                with patch.object(workspace_model_tools,'turn',side_effect=project) as generated:
                    page.locator('#agent-message').fill('Create a website project ZIP with a README')
                    page.locator('#agent-chat-form button[type=submit]').click()
                    expect(page.locator('.work-file-info').filter(has_text='source-project.zip')).to_be_visible(timeout=20000)
                    assert generated.call_count==1
                page.locator('.work-html-preview summary').click()
                frame=page.frame_locator('.work-html-preview iframe');expect(frame.get_by_role('heading',name='Working preview')).to_be_visible()
                frame.get_by_role('button',name='Try it').click();expect(frame.get_by_role('button',name='Clicked')).to_be_visible()
                assert page.locator('.work-html-preview iframe').get_attribute('sandbox')=='allow-scripts'
                child=next(f for f in page.frames if f!=page.main_frame)
                assert child.evaluate('self.origin')=='null'
                assert child.evaluate('async()=>{try{await fetch("/healthz");return false}catch{return true}}')
                target=child.url
                child.evaluate('location.href="https://blocked.example.test/preview-should-not-leak"')
                page.wait_for_timeout(100)
                assert child.url==target
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert not errors,errors;page.screenshot(path=str(output/f'workspace-{width}.png'),full_page=True)
                context.close();case.doCleanups();print('PASS workspace browser: replay once, Thinking cleanup, attachments, source ZIP, opaque working preview, no overflow '+str(width),flush=True)
            browser.close()
    finally:server.shutdown()


if __name__=='__main__':main()
